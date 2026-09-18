"""Isolated platform governance, runtime snapshots and security regression coverage."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.auth import digest
from app.compliance_engine import calculate_deadline, evaluate_rules, validate_publish
from app.compliance_template_schema import TemplateConfiguration
from app.database import SessionLocal
from app.main import app
from app.models import AuthSession, ComplianceReminder, Organization, User


@contextmanager
def platform_client(monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", "master@example.test")
    with TestClient(app) as client:
        with SessionLocal() as db:
            user = User(tenant_id="tenant-demo", name="Master Admin", email="master@example.test", role="ADMIN")
            db.add(user)
            db.flush()
            db.add(AuthSession(token_hash=digest("master-test"), user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
            db.commit()
        client.cookies.set("setu_session", "master-test")
        client.headers["X-Setu-Request"] = "1"
        yield client


def config(category_id="sample-category"):
    return TemplateConfiguration.model_validate({
        "name": "Sample governance review", "category_id": category_id, "jurisdiction": "Sample jurisdiction",
        "internal_notes": "Platform-only notes", "applicability": {"match_all": True},
        "deadline": {"fixed_date": "2026-11-30", "internal_lead_days": 15},
        "workflow": {"stages": [{"id": "start", "state": "NOT_STARTED"}, {"id": "work", "state": "IN_PROGRESS"}, {"id": "done", "state": "COMPLETED"}],
            "transitions": [{"from_state": "NOT_STARTED", "to_state": "IN_PROGRESS", "allowed_roles": ["TENANT_ADMIN"]},
                {"from_state": "IN_PROGRESS", "to_state": "COMPLETED", "allowed_roles": ["TENANT_ADMIN"], "required_approval": True}]},
        "responsibility": {"owner_role": "ACCOUNTANT", "fallback_role": "TENANT_ADMIN", "approver_role": "TENANT_ADMIN"},
        "checklist": [{"id": "collect", "title": "Sample evidence check", "relative_due_days": -7}],
        "documents": [{"id": "proof", "document_type": "Sample evidence"}],
        "reminders": [{"id": "due", "offset_days": -7, "recipient_role": "ACCOUNTANT"}],
        "translations": {"kn-IN": {"name": "ಮಾದರಿ ಆಡಳಿತ ಪರಿಶೀಲನೆ"}},
    })


def create(client, code="SAMPLE-GOV"):
    category_response = client.post("/api/v1/admin/compliance-categories", json={"name": "Sample Governance"})
    assert category_response.status_code == 201, category_response.text
    payload = {"code": code, "configuration": config(category_response.json()["id"]).model_dump(mode="json")}
    response = client.post("/api/v1/admin/compliance-templates", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def publish(client, row):
    for action in ("submit-review", "approve", "publish"):
        response = client.post(f"/api/v1/admin/compliance-templates/{row['id']}/{action}", json={"expected_revision": row["revision"]})
        assert response.status_code == 200, response.text
        row = response.json()
    return row


def test_create_filter_pagination_sort_and_audit(monkeypatch):
    with platform_client(monkeypatch) as client:
        row = create(client, "sample-gov")
        assert row["code"] == "SAMPLE-GOV" and row["version"] == 1 and row["status"] == "DRAFT"
        listing = client.get("/api/v1/admin/compliance-templates", params={"search": "sample", "sort": "name", "order": "asc", "page_size": 1}).json()
        assert listing["total"] == 1 and listing["items"][0]["id"] == row["id"]
        assert "configuration" not in listing["items"][0]
        assert client.get("/api/v1/admin/compliance-templates", params={"status": "PUBLISHED"}).json()["total"] == 0
        assert client.get("/api/v1/admin/compliance-templates", params={"page": 2, "page_size": 1}).json()["items"] == []
        duplicate = client.post("/api/v1/admin/compliance-templates", json={"code": "SAMPLE-GOV", "configuration": row["configuration"]})
        assert duplicate.status_code == 409
        assert client.get("/api/v1/admin/compliance-templates", params={"sort": "sql injection"}).status_code == 422
        assert any(event["action"] == "COMPLIANCE_MASTER_CREATED" for event in client.get("/api/v1/audit-events").json())


def test_review_publish_immutable_version_clone_archive(monkeypatch):
    with platform_client(monkeypatch) as client:
        row = create(client)
        assert client.post(f"/api/v1/admin/compliance-templates/{row['id']}/publish", json={"expected_revision": 0}).status_code == 409
        row = publish(client, row)
        edit = {"expected_revision": row["revision"], "configuration": row["configuration"], "change_summary": "Changed sample rules"}
        assert client.patch(f"/api/v1/admin/compliance-templates/{row['id']}", json=edit).status_code == 409
        assert client.post(f"/api/v1/admin/compliance-templates/{row['id']}/new-version", json={"expected_revision": row["revision"]}).status_code == 422
        version = client.post(f"/api/v1/admin/compliance-templates/{row['id']}/new-version", json={"expected_revision": row["revision"], "change_summary": "Updated sample reminder"})
        assert version.status_code == 201, version.text
        draft = version.json()
        assert draft["version"] == 2 and draft["status"] == "DRAFT" and draft["current_version"] == 1
        assert client.post(f"/api/v1/admin/compliance-templates/{row['id']}/new-version", json={"expected_revision": row["revision"], "change_summary": "Duplicate version"}).status_code == 409
        draft["configuration"]["deadline"]["internal_lead_days"] = 21
        saved = client.patch(f"/api/v1/admin/compliance-templates/{row['id']}", json={"expected_revision": 0, "configuration": draft["configuration"], "change_summary": "Changed sample target"})
        assert saved.status_code == 200, saved.text
        history = client.get(f"/api/v1/admin/compliance-templates/{row['id']}/versions").json()
        assert [item["version"] for item in history] == [2, 1]
        assert client.get(f"/api/v1/admin/compliance-templates/{row['id']}", params={"version": 1}).json()["configuration"]["deadline"]["internal_lead_days"] == 15
        comparison = client.get(f"/api/v1/admin/compliance-templates/{row['id']}/compare", params={"before": 1, "after": 2}).json()
        assert comparison["changes"][0]["section"] == "deadline"
        cloned = client.post(f"/api/v1/admin/compliance-templates/{row['id']}/clone", json={"code": "SAMPLE-COPY", "configuration": draft["configuration"]})
        assert cloned.status_code == 201 and cloned.json()["version"] == 1 and cloned.json()["status"] == "DRAFT"
        active = publish(client, saved.json())
        assert active["current_version"] == 2
        archived = client.post(f"/api/v1/admin/compliance-templates/{row['id']}/archive", json={"expected_revision": active["revision"]})
        assert archived.status_code == 200 and archived.json()["current_version"] is None
        assert client.get("/api/v1/compliance-templates").json() == []


def test_draft_conflict_and_invalid_configuration(monkeypatch):
    with platform_client(monkeypatch) as client:
        row = create(client)
        row["configuration"]["name"] = ""
        payload = {"expected_revision": 0, "configuration": row["configuration"], "change_summary": "Incomplete draft"}
        assert client.patch(f"/api/v1/admin/compliance-templates/{row['id']}", json=payload).status_code == 200
        assert client.patch(f"/api/v1/admin/compliance-templates/{row['id']}", json=payload).status_code == 409
        assert not client.post(f"/api/v1/admin/compliance-templates/{row['id']}/validate").json()["valid"]
        assert client.post(f"/api/v1/admin/compliance-templates/{row['id']}/submit-review", json={"expected_revision": 1}).status_code == 422
        payload["expected_revision"] = 1
        payload["configuration"]["portal_url"] = "javascript:alert(1)"
        assert client.patch(f"/api/v1/admin/compliance-templates/{row['id']}", json=payload).status_code == 422


def test_runtime_snapshot_tasks_documents_reminders_and_tenant_boundary(monkeypatch):
    with platform_client(monkeypatch) as client:
        row = publish(client, create(client))
        assert "internal_notes" not in client.get("/api/v1/compliance-templates").json()[0]["configuration"]
        preview = client.post(f"/api/v1/admin/compliance-templates/{row['id']}/test-applicability", json={"organization_id": "org-udaan", "as_of": "2026-10-01"})
        assert preview.status_code == 200 and preview.json()["schedule"]["statutory_deadline"] == "2026-11-30"
        generated = client.post("/api/v1/organizations/org-udaan/generate-plan").json()
        instance = next(item for item in generated if item["code"] == "SAMPLE-GOV")
        assert instance["owner_name"] == "Master Admin"
        assert not any(item["code"] == "SAMPLE-GOV" for item in client.post("/api/v1/organizations/org-udaan/generate-plan").json())
        snapshot = client.get(f"/api/v1/compliances/{instance['id']}/template-snapshot").json()
        assert snapshot["version"] == 1 and snapshot["documents"][0]["document_ids"] == []
        assert len(snapshot["checklist_tasks"]) == 1
        assert client.post(f"/api/v1/compliances/{instance['id']}/transitions", json={"target_status": "IN_PROGRESS"}).status_code == 200
        assert client.post(f"/api/v1/compliances/{instance['id']}/transitions", json={"target_status": "COMPLETED"}).status_code == 422
        task = snapshot["checklist_tasks"][0]["task_id"]
        assert client.patch(f"/api/v1/tasks/{task}", json={"status": "DONE"}).status_code == 200
        proof = client.post("/api/v1/documents", json={"organization_id": "org-udaan", "name": "Existing sample evidence.pdf", "category": "Sample evidence", "uploaded_by": "Master Admin"})
        assert proof.status_code == 201, proof.text
        assert client.post(f"/api/v1/compliances/{instance['id']}/transitions", json={"target_status": "COMPLETED"}).status_code == 200
        # No re-upload required: the existing organization repository satisfies this requirement.
        assert len(client.get(f"/api/v1/compliances/{instance['id']}/template-snapshot").json()["documents"][0]["document_ids"]) == 1
        version = client.post(f"/api/v1/admin/compliance-templates/{row['id']}/new-version", json={"expected_revision": row["revision"], "change_summary": "Changed sample rules"}).json()
        version["configuration"]["checklist"][0]["title"] = "New checklist only"
        saved = client.patch(f"/api/v1/admin/compliance-templates/{row['id']}", json={"expected_revision": 0, "configuration": version["configuration"], "change_summary": "Updated sample checklist"}).json()
        publish(client, saved)
        old = client.get(f"/api/v1/compliances/{instance['id']}/template-snapshot").json()
        assert old["version"] == 1 and old["configuration"]["checklist"][0]["title"] == "Sample evidence check"
        # Separate active instance for reminder retries.
        generated = client.post("/api/v1/organizations/org-jal/generate-plan").json()
        active = next(item for item in generated if item["code"] == "SAMPLE-GOV")
        with SessionLocal() as db:
            reminder = db.scalar(select(ComplianceReminder).where(ComplianceReminder.compliance_id == active["id"]))
            reminder.scheduled_for = date.today()
            db.commit()
        first = client.post("/api/v1/automation/run").json()
        second = client.post("/api/v1/automation/run").json()
        assert first["template_reminders"] == 1 and second["template_reminders"] == 0
        assert client.get(f"/api/v1/compliances/{instance['id']}/template-snapshot", headers={"X-Tenant-ID": "another"}).status_code == 403


@pytest.mark.parametrize("role", ["ADMIN", "MEMBER", "VIEWER"])
def test_nonplatform_rbac_all_operations(monkeypatch, role):
    with platform_client(monkeypatch) as client:
        row = create(client)
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "master@example.test"))
            user.role = role
            user.email = "tenant-admin@example.test"
            db.commit()
        assert not client.get("/api/v1/admin/compliance-master/access").json()["allowed"]
        assert client.get("/api/v1/admin/compliance-templates").status_code == 403
        assert client.get(f"/api/v1/admin/compliance-templates/{row['id']}").status_code == 403
        for action in ("validate", "submit-review", "approve", "publish", "archive", "new-version", "test-applicability", "request-changes"):
            assert client.post(f"/api/v1/admin/compliance-templates/{row['id']}/{action}", json={"expected_revision": 0, "organization_id": "org-udaan"}).status_code == 403
        assert client.get("/api/v1/admin/compliance-categories").status_code == 403


@pytest.mark.parametrize("operator,values,expected", [("AND", [True, True], True), ("AND", [True, False], False), ("OR", [True, False], True), ("OR", [False, False], False)])
def test_and_or_rule_groups(operator, values, expected):
    c = config()
    organization = Organization(tenant_id="a", name="Sample", legal_type="TRUST", status="ACTIVE", fcra_active=values[0], pan="" if not values[1] else "SAMPLE", city="", registration_number="")
    c.applicability = TemplateConfiguration.model_validate({"applicability": {"operator": operator, "groups": [{"id": "group", "operator": operator,
        "conditions": [{"id": "fcra", "field": "fcra_active", "operator": "IS_TRUE"}, {"id": "pan", "field": "pan", "operator": "IS_NOT_EMPTY"}]}]}}).applicability
    assert evaluate_rules(c, organization)["applicable"] is expected
    organization.fcra_active = not values[0]
    assert evaluate_rules(c, organization)["groups"][0]["conditions"][0]["satisfied"] is (not values[0])


@pytest.mark.parametrize("condition", [
    {"field": "__class__", "operator": "EQUALS", "value": "x"},
    {"field": "fcra_active", "operator": "EQUALS", "value": "true"},
    {"field": "legal_type", "operator": "IN", "value": "TRUST"},
    {"field": "legal_type", "operator": "IN", "value": []},
    {"field": "legal_type", "operator": "RUN_JAVASCRIPT", "value": "eval()"},
])
def test_unsafe_rules_rejected(condition):
    with pytest.raises(ValidationError):
        TemplateConfiguration.model_validate({"applicability": {"groups": [{"id": "g", "conditions": [{"id": "r", **condition}]}]}})


@pytest.mark.parametrize("frequency,expected", [("MONTHLY", "2026-12-30"), ("QUARTERLY", "2027-02-28"), ("HALF_YEARLY", "2027-05-28"), ("ANNUAL", "2027-11-28"), ("CUSTOM", "2027-01-28")])
def test_fixed_recurrence(frequency, expected):
    c = config()
    c.recurrence.frequency = frequency
    c.recurrence.interval_months = 2
    c.deadline.fixed_date = date(2026, 11, 30) if frequency == "MONTHLY" else date(2026, 11, 28)
    dates = calculate_deadline(c, date(2026, 12, 1))
    assert dates["statutory_deadline"].isoformat() == expected
    assert dates["internal_target"] == dates["statutory_deadline"] - timedelta(days=15)


def test_period_event_expiry_and_fiscal_dates():
    c = config()
    c.deadline.strategy = "PERIOD_END_PLUS_DAYS"
    c.recurrence.frequency = "QUARTERLY"
    c.recurrence.anchor_date = date(2026, 4, 1)
    c.deadline.offset_days = 10
    assert calculate_deadline(c, date(2026, 9, 17))["statutory_deadline"] == date(2026, 10, 10)
    c.deadline.strategy = "FINANCIAL_YEAR_END_PLUS_DAYS"
    assert calculate_deadline(c, date(2026, 9, 17))["statutory_deadline"] == date(2027, 4, 10)
    c.deadline.strategy = "EVENT_DATE_PLUS_DAYS"
    with pytest.raises(ValueError):
        calculate_deadline(c, date(2026, 9, 17))
    assert calculate_deadline(c, date(2026, 9, 17), event_date=date(2026, 9, 1))["statutory_deadline"] == date(2026, 9, 11)
    c.deadline.strategy = "CERTIFICATE_EXPIRY_MINUS_DAYS"
    assert calculate_deadline(c, date(2026, 9, 17), expiry=date(2026, 10, 1))["statutory_deadline"] == date(2026, 9, 21)
    c.deadline.strategy = "FIXED_DATE"
    c.deadline.fixed_date = date(2024, 2, 29)
    c.recurrence.frequency = "ANNUAL"
    with pytest.raises(ValueError):
        calculate_deadline(c, date(2025, 1, 1))  # Admin review, no invented Feb-28 legal policy.


def test_invalid_workflow_publish_validation():
    c = config()
    assert validate_publish(c) == []
    c.workflow.transitions.pop()
    assert any("workflow" in error for error in validate_publish(c))
    c = config()
    c.workflow.stages.reverse()
    assert any("workflow" in error for error in validate_publish(c))


@pytest.mark.parametrize("operator,expected", [("GREATER_THAN", True), ("GREATER_THAN_OR_EQUAL", True), ("LESS_THAN", False), ("LESS_THAN_OR_EQUAL", False), ("EQUALS", False), ("NOT_EQUALS", True)])
def test_numeric_comparisons_missing_data_and_zero(operator, expected):
    c = config()
    c.applicability = TemplateConfiguration.model_validate({"applicability": {"groups": [{"id": "g", "conditions": [{"id": "r", "field": "annual_revenue", "operator": operator, "value": 0}]}]}}).applicability
    organization = Organization(tenant_id="a", name="Sample", legal_type="TRUST")
    assert evaluate_rules(c, organization, {"annual_revenue": Decimal("150000.25")})["applicable"] is expected
    assert evaluate_rules(c, organization, {"annual_revenue": None})["requires_review"]
    if operator == "EQUALS":
        assert evaluate_rules(c, organization, {"annual_revenue": Decimal("0")})["applicable"]


def test_financial_profile_tenant_isolation_and_date_rules(monkeypatch):
    with platform_client(monkeypatch) as client:
        assert client.patch("/api/v1/organizations/org-udaan/compliance-profile", json={"annual_revenue": "150000.25", "revenue_period": "Sample FY 2026-27"}).status_code == 200
        facts = client.get("/api/v1/organizations/org-udaan/compliance-profile").json()
        assert float(facts["annual_revenue"]) == 150000.25
        assert client.patch("/api/v1/organizations/org-udaan/compliance-profile", json={"annual_revenue": "150000.25"}).status_code == 422
        assert client.get("/api/v1/organizations/org-udaan/compliance-profile", headers={"X-Tenant-ID": "another"}).status_code == 403
    c = config()
    c.applicability = TemplateConfiguration.model_validate({"applicability": {"groups": [{"id": "g", "conditions": [{"id": "r", "field": "created_at", "operator": "LESS_THAN", "value": "2026-10-01"}]}]}}).applicability
    organization = Organization(name="Sample", created_at=datetime(2026, 9, 17, tzinfo=timezone.utc))
    assert evaluate_rules(c, organization)["applicable"]


def test_archive_with_pending_draft_stops_generation_and_retains_published_history(monkeypatch):
    with platform_client(monkeypatch) as client:
        row = publish(client, create(client))
        new = client.post(f"/api/v1/admin/compliance-templates/{row['id']}/new-version", json={"expected_revision": row["revision"], "change_summary": "Sample pending change"}).json()
        archived = client.post(f"/api/v1/admin/compliance-templates/{row['id']}/archive", json={"expected_revision": new["revision"]})
        assert archived.status_code == 200 and archived.json()["current_version"] is None
        assert client.get("/api/v1/compliance-templates").json() == []
        assert client.get(f"/api/v1/admin/compliance-templates/{row['id']}", params={"version": 1}).json()["configuration"] == row["configuration"]


@pytest.mark.parametrize("value", [float("inf"), float("nan"), True, "150000", -1e30])
def test_invalid_numeric_rule_values_rejected(value):
    with pytest.raises(ValidationError):
        TemplateConfiguration.model_validate({"applicability": {"groups": [{"id": "g", "conditions": [{"id": "r", "field": "annual_revenue", "operator": "GREATER_THAN", "value": value}]}]}})
