"""Phase 9 frozen review, approval, filing and reopening regression coverage."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.auth import digest
from app.auth_models import SessionContext
from app.database import SessionLocal, engine
from app.migrate_phase9 import VERSION, apply
from app.models import AuthSession, Membership, User
from app.phase9_models import ComplianceApproval, ComplianceReview
from app.phase8_models import OrganizationAccess
from test_compliance_master import platform_client
from test_documents import upload_original
from test_runtime_phase5 import configured, generate


def add_actor(name: str, email: str, token: str, roles: list[str]) -> str:
    with SessionLocal() as db:
        user = User(tenant_id="tenant-demo", name=name, email=email, role="MEMBER")
        db.add(user)
        db.flush()
        for index, role in enumerate(roles):
            db.add(Membership(
                id=f"phase9-{token}-{index}", tenant_id="tenant-demo", organization_id="org-udaan",
                name=name, email=email, role=role, status="ACTIVE",
            ))
        db.add(AuthSession(
            token_hash=digest(token), user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        db.add(SessionContext(token_hash=digest(token), tenant_id="tenant-demo", audience="user"))
        db.commit()
        return user.id


def use(client, token: str) -> None:
    client.cookies.set("setu_session", token)


def workflow_configuration(configuration):
    states = ["NOT_STARTED", "IN_PROGRESS", "UNDER_REVIEW", "CHANGES_REQUESTED", "READY_TO_FILE", "FILED", "COMPLETED"]
    configuration["workflow"] = {
        "stages": [{"id": f"stage-{index}", "state": state} for index, state in enumerate(states)],
        "transitions": [
            {"from_state": "NOT_STARTED", "to_state": "IN_PROGRESS", "allowed_roles": ["TENANT_ADMIN"]},
            {"from_state": "IN_PROGRESS", "to_state": "UNDER_REVIEW", "allowed_roles": ["TENANT_ADMIN"]},
            {"from_state": "UNDER_REVIEW", "to_state": "CHANGES_REQUESTED", "allowed_roles": ["AUDITOR"]},
            {"from_state": "UNDER_REVIEW", "to_state": "READY_TO_FILE", "allowed_roles": ["TENANT_ADMIN"], "required_approval": True},
            {"from_state": "CHANGES_REQUESTED", "to_state": "IN_PROGRESS", "allowed_roles": ["TENANT_ADMIN"]},
            {"from_state": "READY_TO_FILE", "to_state": "FILED", "allowed_roles": ["TENANT_ADMIN"], "required_evidence": True},
            {"from_state": "FILED", "to_state": "COMPLETED", "allowed_roles": ["TENANT_ADMIN"]},
            {"from_state": "COMPLETED", "to_state": "IN_PROGRESS", "allowed_roles": ["TENANT_ADMIN"]},
        ],
        "filing_proof_types": ["RECEIPT", "CERTIFICATE"],
    }
    configuration["responsibility"].update(
        owner_role="TENANT_ADMIN", fallback_role="TENANT_ADMIN", reviewer_role="AUDITOR",
        approver_role="ORGANIZATION_ADMIN", separate_preparer_reviewer=True,
        separate_reviewer_approver=True,
    )


def test_review_changes_resubmit_approval_filing_completion_and_reopen(monkeypatch):
    with platform_client(monkeypatch) as client:
        row = configured(client, code="PHASE9-FLOW", change=workflow_configuration)
        item = generate(client, row["code"])
        root = f"/api/v1/compliances/{item['id']}"
        transitions = root + "/transitions"
        reviewer_id = add_actor("Review Auditor", "review.phase9@example.test", "phase9-review", ["AUDITOR", "ORGANIZATION_ADMIN"])
        approver_id = add_actor("Independent Approver", "approve.phase9@example.test", "phase9-approve", ["ORGANIZATION_ADMIN"])
        with SessionLocal() as db:
            master = db.scalar(select(User).where(User.email == "master@example.test"))
            db.add(Membership(id="phase9-master-auditor", tenant_id="tenant-demo", organization_id="org-udaan",
                              name=master.name, email=master.email, role="AUDITOR", status="ACTIVE"))
            db.commit()

        assert client.post(transitions, json={"target_status": "IN_PROGRESS"}).status_code == 200
        assert client.post(transitions, json={"target_status": "UNDER_REVIEW"}).status_code == 200
        first = client.get(root + "/workflow-records").json()["reviews"][0]
        denied = client.post(root + f"/reviews/{first['id']}/decision",
                             json={"decision": "APPROVED", "comments": "Self review is forbidden"})
        assert denied.status_code == 403 and "SEPARATION_OF_DUTIES" in denied.text

        use(client, "phase9-review")
        changes = client.post(root + f"/reviews/{first['id']}/decision",
                              json={"decision": "CHANGES_REQUESTED", "comments": "Correct the filing package"})
        assert changes.status_code == 200, changes.text

        use(client, "master-test")
        assert client.post(transitions, json={"target_status": "IN_PROGRESS"}).status_code == 200
        assert client.post(transitions, json={"target_status": "UNDER_REVIEW"}).status_code == 200
        second = client.get(root + "/workflow-records").json()["reviews"][0]
        assert second["revision"] == 2

        use(client, "phase9-review")
        approved = client.post(root + f"/reviews/{second['id']}/decision",
                               json={"decision": "APPROVED", "comments": "Evidence package reviewed"})
        assert approved.status_code == 200, approved.text
        approval = approved.json()["approvals"][0]
        denied = client.post(root + f"/approvals/{approval['id']}/decision",
                             json={"decision": "APPROVED", "comments": "Reviewer cannot self approve"})
        assert denied.status_code == 403 and "SEPARATION_OF_DUTIES" in denied.text

        use(client, "phase9-approve")
        approved = client.post(root + f"/approvals/{approval['id']}/decision",
                               json={"decision": "APPROVED", "comments": "Independent approval recorded"})
        assert approved.status_code == 200, approved.text
        assert approved.json()["approvals"][0]["approver_id"] == approver_id

        use(client, "master-test")
        blocked = client.post(transitions, json={"target_status": "READY_TO_FILE"})
        assert blocked.status_code == 422 and "REQUIRED_CHECKLIST_INCOMPLETE" in blocked.text
        detail = client.get(root + "/runtime-detail").json()
        assert client.patch(f"/api/v1/tasks/{detail['tasks'][0]['id']}", json={"status": "DONE"}).status_code == 200
        proof = upload_original(client, expiry_at="2030-01-01")
        assert proof.status_code == 201, proof.text
        document = proof.json()["document"]
        version_id = proof.json()["file"]["version_id"]
        assert client.post(transitions, json={"target_status": "READY_TO_FILE"}).status_code == 200
        assert client.post(transitions, json={"target_status": "FILED"}).status_code == 422
        invalid = client.post(transitions, json={
            "target_status": "FILED", "submission_reference": "ACK-2026-009",
            "proof_document_id": document["id"], "proof_type": "RETURN",
        })
        assert invalid.status_code == 422 and "FILING_PROOF_TYPE_INVALID" in invalid.text
        filed = client.post(transitions, json={
            "target_status": "FILED", "submission_reference": "ACK-2026-009",
            "proof_document_id": document["id"], "proof_type": "RECEIPT",
            "filing_channel": "GOVERNMENT_PORTAL", "filing_notes": "Receipt downloaded after submission",
        })
        assert filed.status_code == 200, filed.text
        assert client.post(transitions, json={"target_status": "COMPLETED"}).status_code == 200
        assert client.post(transitions, json={"target_status": "IN_PROGRESS"}).status_code == 422
        reopened = client.post(transitions, json={"target_status": "IN_PROGRESS", "reason": "Authority requested an amended filing"})
        assert reopened.status_code == 200, reopened.text

        saved = client.get(root + "/runtime-detail").json()
        assert [review["decision"] for review in saved["reviews"]] == ["APPROVED", "CHANGES_REQUESTED"]
        assert saved["reviews"][0]["reviewer_id"] == reviewer_id
        assert saved["submissions"][0]["proof_version_id"] == version_id
        assert saved["submissions"][0]["proof_type"] == "RECEIPT"
        assert saved["submissions"][0]["filing_channel"] == "GOVERNMENT_PORTAL"
        assert any(event["action"] == "APPROVAL_DECIDED" for event in saved["audit"])


def test_standalone_required_approval_and_cancelled_regression(monkeypatch):
    with platform_client(monkeypatch) as client:
        def cancellable(configuration):
            configuration["workflow"]["stages"].insert(-1, {"id": "cancelled", "state": "CANCELLED"})
            configuration["workflow"]["transitions"].append({
                "from_state": "NOT_STARTED", "to_state": "CANCELLED", "allowed_roles": ["TENANT_ADMIN"]
            })
        row = configured(client, code="PHASE9-DIRECT", change=cancellable)
        item = generate(client, row["code"])
        root = f"/api/v1/compliances/{item['id']}"
        assert client.post(root + "/transitions", json={"target_status": "IN_PROGRESS"}).status_code == 200
        request = client.post(root + "/approvals/request", json={"target_status": "COMPLETED"})
        assert request.status_code == 201, request.text
        approval = request.json()["approvals"][0]
        decision = client.post(root + f"/approvals/{approval['id']}/decision",
                               json={"decision": "APPROVED", "comments": "Required direct approval"})
        assert decision.status_code == 200, decision.text

        generated = client.post("/api/v1/organizations/org-jal/generate-plan").json()
        cancelled = next(entry for entry in generated if entry["code"] == row["code"])
        path = f"/api/v1/compliances/{cancelled['id']}/transitions"
        assert client.post(path, json={"target_status": "CANCELLED"}).status_code == 422
        response = client.post(path, json={"target_status": "CANCELLED", "reason": "Duplicate statutory obligation"})
        assert response.status_code == 200 and response.json()["status"] == "CANCELLED"


def test_phase9_migration_is_idempotent_and_records_are_tenant_scoped(monkeypatch):
    with platform_client(monkeypatch) as client:
        assert apply(engine) == VERSION
        assert apply(engine) == VERSION
        item = generate(client, configured(client, code="PHASE9-SCOPE", change=workflow_configuration)["code"])
        root = f"/api/v1/compliances/{item['id']}"
        assert client.post(root + "/transitions", json={"target_status": "IN_PROGRESS"}).status_code == 200
        assert client.post(root + "/transitions", json={"target_status": "UNDER_REVIEW"}).status_code == 200
        with SessionLocal() as db:
            assert db.scalar(select(ComplianceReview).where(ComplianceReview.compliance_id == item["id"]))
            assert db.scalars(select(ComplianceApproval)).all() == []
            master = db.scalar(select(User).where(User.email == "master@example.test"))
            restricted = User(tenant_id="tenant-demo", name="Restricted", email="restricted.phase9@example.test", role="MEMBER")
            db.add(restricted)
            db.flush()
            db.add(OrganizationAccess(tenant_id="tenant-demo", organization_id="org-jal", user_id=restricted.id,
                                      access_role="CONTRIBUTOR", granted_by=master.id))
            db.add(AuthSession(token_hash=digest("phase9-restricted"), user_id=restricted.id,
                               expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
            db.add(SessionContext(token_hash=digest("phase9-restricted"), tenant_id="tenant-demo", audience="user"))
            outsider = User(tenant_id="other-tenant", name="Other", email="other.phase9@example.test", role="ADMIN")
            db.add(outsider)
            db.flush()
            db.add(AuthSession(token_hash=digest("phase9-other"), user_id=outsider.id,
                               expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
            db.add(SessionContext(token_hash=digest("phase9-other"), tenant_id="other-tenant", audience="user"))
            db.commit()
        use(client, "phase9-restricted")
        assert client.get(root + "/workflow-records").status_code == 403
        use(client, "phase9-other")
        assert client.get(root + "/workflow-records").status_code == 404
