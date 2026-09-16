import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from fastapi.testclient import TestClient

from app.main import app
from app.auth import hash_password
from app.database import SessionLocal
from app.models import User
from contextlib import contextmanager


@contextmanager
def authenticated_client():
    with TestClient(app) as client:
        with SessionLocal() as db:
            db.add(User(tenant_id="tenant-demo", name="Test Administrator", email="admin@example.test",
                        password_hash=hash_password("Testing-passphrase-2026"), role="ADMIN"))
            db.commit()
        client.headers["X-Setu-Request"] = "1"
        assert client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": "Testing-passphrase-2026"}).status_code == 200
        yield client


def test_health_and_seeded_dashboard():
    with authenticated_client() as client:
        assert client.get("/health").json()["status"] == "ok"
        response = client.get("/api/v1/dashboard")
        assert response.status_code == 200
        assert response.json()["summary"]["total"] >= 6


def test_tenant_boundary_hides_demo_data():
    with authenticated_client() as client:
        response = client.get("/api/v1/organizations", headers={"x-tenant-id": "another-tenant"})
        assert response.status_code == 403
        assert response.json()["detail"] == "Workspace access denied"


def test_unknown_tenant_cannot_patch_compliance():
    with authenticated_client() as client:
        response = client.patch(
            "/api/v1/compliances/cmp-fcra",
            headers={"x-tenant-id": "another-tenant"},
            json={"status": "COMPLETED"},
        )
        assert response.status_code == 403


def test_create_compliance_persists_and_writes_audit_event():
    with authenticated_client() as client:
        payload = {
            "organization_id": "org-udaan",
            "code": "BOARD-01",
            "title": "Donor due diligence register",
            "category": "Governance",
            "period": "Q2 2026-27",
            "statutory_deadline": "2026-10-31",
            "internal_target": "2026-10-24",
            "priority": "HIGH",
            "owner_name": "Ananya Desai",
            "owner_initials": "AD",
            "legal_reference": "Internal governance calendar",
        }
        created = client.post("/api/v1/compliances", json=payload)
        assert created.status_code == 201
        compliance_id = created.json()["id"]

        rows = client.get("/api/v1/compliances", params={"search": "donor due diligence"}).json()
        assert [row["id"] for row in rows] == [compliance_id]

        events = client.get("/api/v1/audit-events").json()
        assert any(event["entity_id"] == compliance_id and event["action"] == "COMPLIANCE_CREATED" for event in events)


def test_internal_target_cannot_follow_statutory_deadline():
    with authenticated_client() as client:
        response = client.post(
            "/api/v1/compliances",
            json={
                "organization_id": "org-udaan",
                "code": "BAD-DATE",
                "title": "Invalid planning dates",
                "category": "General",
                "period": "FY 2026-27",
                "statutory_deadline": "2026-10-20",
                "internal_target": "2026-10-21",
                "owner_name": "Ananya Desai",
            },
        )
        assert response.status_code == 422


def test_document_link_must_belong_to_same_organization():
    with authenticated_client() as client:
        response = client.post(
            "/api/v1/documents",
            json={
                "organization_id": "org-jal",
                "compliance_id": "cmp-fcra",
                "name": "wrong-organization.pdf",
                "category": "Evidence",
                "uploaded_by": "Ananya Desai",
            },
        )
        assert response.status_code == 404


def test_create_linked_task_persists_and_is_audited():
    with authenticated_client() as client:
        response = client.post(
            "/api/v1/tasks",
            json={
                "organization_id": "org-udaan",
                "compliance_id": "cmp-audit",
                "title": "Obtain final auditor signature",
                "due_at": "2026-09-15",
                "priority": "HIGH",
                "assignee_name": "Ananya Desai",
                "assignee_initials": "AD",
            },
        )
        assert response.status_code == 201
        task_id = response.json()["id"]

        tasks = client.get("/api/v1/tasks", params={"organization_id": "org-udaan"}).json()
        assert any(task["id"] == task_id and task["status"] == "TODO" for task in tasks)
        events = client.get("/api/v1/audit-events").json()
        assert any(event["entity_id"] == task_id and event["action"] == "TASK_CREATED" for event in events)


def test_task_link_must_belong_to_same_organization():
    with authenticated_client() as client:
        response = client.post(
            "/api/v1/tasks",
            json={
                "organization_id": "org-jal",
                "compliance_id": "cmp-audit",
                "title": "Cross organization task",
                "due_at": "2026-09-15",
                "assignee_name": "Ananya Desai",
            },
        )
        assert response.status_code == 404


def test_organization_onboarding_generates_applicable_plan():
    with authenticated_client() as client:
        response = client.post(
            "/api/v1/organizations",
            json={
                "name": "Seva Community Foundation",
                "legal_type": "TRUST",
                "registration_number": "TRUST-SEVA-2026",
                "city": "Nagpur",
                "pan": "AAATS1234Q",
                "fcra_active": False,
                "generate_compliance_plan": True,
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["organization"]["status"] == "ACTIVE"
        assert len(body["generated_compliances"]) == 3
        assert all(item["status"] == "PLANNED" for item in body["generated_compliances"])
        assert all(item["code"] != "FCRA-ANNUAL" for item in body["generated_compliances"])

        duplicate = client.post(
            "/api/v1/organizations",
            json={
                "name": "Duplicate Seva",
                "legal_type": "SOCIETY",
                "registration_number": "TRUST-SEVA-2026",
                "city": "Nagpur",
                "generate_compliance_plan": False,
            },
        )
        assert duplicate.status_code == 409


def test_controlled_compliance_lifecycle_requires_filing_proof():
    with authenticated_client() as client:
        created = client.post(
            "/api/v1/compliances",
            json={
                "organization_id": "org-udaan",
                "code": "FLOW-01",
                "title": "Lifecycle integration check",
                "category": "Governance",
                "period": "FY 2026-27",
                "statutory_deadline": "2027-03-31",
                "internal_target": "2027-03-20",
                "priority": "MEDIUM",
                "owner_name": "Ananya Desai",
            },
        ).json()
        compliance_id = created["id"]

        for target in ["IN_PROGRESS", "UNDER_REVIEW", "READY_TO_FILE"]:
            response = client.post(f"/api/v1/compliances/{compliance_id}/transitions", json={"target_status": target})
            assert response.status_code == 200

        missing_proof = client.post(
            f"/api/v1/compliances/{compliance_id}/transitions",
            json={"target_status": "FILED"},
        )
        assert missing_proof.status_code == 422

        filed = client.post(
            f"/api/v1/compliances/{compliance_id}/transitions",
            json={"target_status": "FILED", "submission_reference": "ACK-2026-001"},
        )
        assert filed.status_code == 200
        completed = client.post(
            f"/api/v1/compliances/{compliance_id}/transitions",
            json={"target_status": "COMPLETED"},
        )
        assert completed.status_code == 200
        assert completed.json()["progress"] == 100

        reopen_without_reason = client.post(
            f"/api/v1/compliances/{compliance_id}/transitions",
            json={"target_status": "IN_PROGRESS"},
        )
        assert reopen_without_reason.status_code == 422


def test_document_version_history_is_immutable_and_tenant_scoped():
    with authenticated_client() as client:
        versions = client.get("/api/v1/documents/doc-pan/versions")
        assert versions.status_code == 200
        assert versions.json()[0]["version"] == 1

        updated = client.post(
            "/api/v1/documents/doc-pan/versions",
            json={"file_type": "PDF", "size_label": "410 KB", "uploaded_by": "Ananya Desai"},
        )
        assert updated.status_code == 201
        assert updated.json()["version"] == 2

        history = client.get("/api/v1/documents/doc-pan/versions").json()
        assert [row["version"] for row in history] == [2, 1]
        denied = client.get("/api/v1/documents/doc-pan/versions", headers={"x-tenant-id": "another-tenant"})
        assert denied.status_code == 403


def test_membership_invitation_enforces_tenant_and_organization_scope():
    with authenticated_client() as client:
        response = client.post(
            "/api/v1/memberships/invitations",
            json={
                "organization_id": "org-jal",
                "name": "Meera Joshi",
                "email": "meera@example.org",
                "role": "AUDITOR",
            },
        )
        assert response.status_code == 201
        assert response.json()["status"] == "INVITED"

        scoped = client.get("/api/v1/memberships", params={"organization_id": "org-jal"}).json()
        assert any(member["email"] == "meera@example.org" for member in scoped)
        hidden = client.get("/api/v1/memberships", headers={"x-tenant-id": "another-tenant"}).json()
        assert hidden["detail"] == "Workspace access denied"


def test_compliance_comments_are_tenant_scoped_and_audited():
    with authenticated_client() as client:
        created = client.post("/api/v1/compliances/cmp-fcra/comments", json={
            "kind": "RECOVERY_PLAN", "body": "Obtain the missing bank reconciliation by Friday."
        })
        assert created.status_code == 201
        assert created.json()["author_name"] == "Test Administrator"
        comments = client.get("/api/v1/compliances/cmp-fcra/comments").json()
        assert comments[0]["kind"] == "RECOVERY_PLAN"
        assert client.get("/api/v1/compliances/cmp-fcra/comments", headers={"x-tenant-id": "another-tenant"}).status_code == 403


def test_expansion_records_support_grants_donors_csr_and_volunteers():
    with authenticated_client() as client:
        created = client.post("/api/v1/portfolio-records", json={
            "organization_id": "org-udaan", "record_type": "GRANT", "title": "Girls education grant",
            "status": "PIPELINE", "owner_name": "Ananya Desai", "value_label": "INR 10 lakh",
            "due_at": "2026-12-15", "notes": "Concept note under review",
        })
        assert created.status_code == 201
        record_id = created.json()["id"]
        assert client.patch(f"/api/v1/portfolio-records/{record_id}", json={"status": "ACTIVE"}).json()["status"] == "ACTIVE"
        rows = client.get("/api/v1/portfolio-records", params={"record_type": "GRANT"}).json()
        assert any(row["id"] == record_id for row in rows)


def test_admin_operations_records_support_workflow_and_audited_delete():
    with authenticated_client() as client:
        created = client.post("/api/v1/portfolio-records", json={
            "organization_id": "org-udaan", "record_type": "DONATION", "title": "Annual appeal donation",
            "status": "PENDING", "owner_name": "Ravi Kumar", "value_label": "INR 25,000 / TXN-1042",
            "due_at": "2026-09-11", "notes": "80G receipt requested",
        })
        assert created.status_code == 201
        record_id = created.json()["id"]
        updated = client.patch(f"/api/v1/portfolio-records/{record_id}", json={"status": "VERIFIED"})
        assert updated.status_code == 200
        assert updated.json()["status"] == "VERIFIED"
        assert any(row["id"] == record_id for row in client.get("/api/v1/portfolio-records", params={"record_type": "DONATION"}).json())

        removed = client.delete(f"/api/v1/portfolio-records/{record_id}")
        assert removed.status_code == 204
        assert all(row["id"] != record_id for row in client.get("/api/v1/portfolio-records").json())
        events = client.get("/api/v1/audit-events").json()
        assert any(event["entity_id"] == record_id and event["action"] == "DONATION_DELETED" for event in events)


def test_daily_automation_is_idempotent_and_rolls_forward_completed_work():
    with authenticated_client() as client:
        created = client.post("/api/v1/compliances", json={
            "organization_id": "org-udaan", "code": "RECUR-01", "title": "Recurring historical return",
            "category": "Governance", "period": "Cycle 2025", "statutory_deadline": "2025-08-31",
            "internal_target": "2025-08-20", "priority": "MEDIUM", "owner_name": "Ananya Desai",
        }).json()
        with SessionLocal() as db:
            from app.models import Compliance, Submission
            item = db.get(Compliance, created["id"])
            item.status = "COMPLETED"
            item.progress = 100
            db.add(Submission(tenant_id="tenant-demo", compliance_id=item.id, acknowledgement_ref="ACK-OLD"))
            db.commit()
        first = client.post("/api/v1/automation/run")
        second = client.post("/api/v1/automation/run")
        assert first.status_code == second.status_code == 200
        assert first.json()["recurring_created"] == 1
        assert second.json()["recurring_created"] == 0
        matches = client.get("/api/v1/compliances", params={"search": "Recurring historical"}).json()
        assert len(matches) == 2


def test_grounded_assistant_returns_only_tenant_record_sources():
    with authenticated_client() as client:
        response = client.post("/api/v1/assistant/query", json={"question": "Which tasks need attention?", "organization_id": "org-udaan"})
        assert response.status_code == 200
        body = response.json()
        assert "Operational assistance only" in body["disclaimer"]
        assert all(source["type"] == "task" for source in body["sources"])


def test_localization_preferences_tenant_configuration_and_overrides():
    with authenticated_client() as client:
        settings = client.get("/api/v1/localization/settings")
        assert settings.status_code == 200
        assert [row["locale_code"] for row in settings.json()["locales"]] == ["en-IN", "hi-IN", "kn-IN", "mr-IN"]
        assert settings.json()["locales"][0]["is_default"] is True

        preference = client.patch("/api/v1/localization/preferences", json={
            "locale": "kn-IN", "timezone": "Asia/Kolkata", "time_format": "24h",
        })
        assert preference.status_code == 200
        assert preference.json()["locale"] == "kn-IN"
        assert preference.json()["time_format"] == "24h"
        assert client.patch("/api/v1/localization/preferences", json={
            "locale": "kn-IN", "timezone": "Not/A_Timezone", "time_format": "24h",
        }).status_code == 422

        locales = settings.json()["locales"]
        payload = [{
            "locale_code": row["locale_code"], "display_name": row["display_name"],
            "enabled": True, "is_default": row["locale_code"] == "hi-IN",
            "sort_order": 1 if row["locale_code"] == "hi-IN" else row["sort_order"] + 1,
        } for row in locales]
        updated = client.put("/api/v1/localization/locales", json=payload)
        assert updated.status_code == 200
        assert next(row for row in updated.json() if row["locale_code"] == "hi-IN")["is_default"] is True

        override = client.put("/api/v1/localization/overrides", json={
            "locale_code": "kn-IN", "translation_key": "Common.actions.save", "translation_value": "ಉಳಿಸಿ ಈಗ",
        })
        assert override.status_code == 200
        override_id = override.json()["id"]
        rows = client.get("/api/v1/localization/overrides", params={"locale_code": "kn-IN"}).json()
        assert rows[0]["translation_value"] == "ಉಳಿಸಿ ಈಗ"
        assert client.delete(f"/api/v1/localization/overrides/{override_id}").status_code == 204
