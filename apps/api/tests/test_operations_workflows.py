"""Existing operational record CRUD, capabilities, audit and scope contracts."""
import pytest
from sqlalchemy import select
from app.database import SessionLocal
from app.models import AuditEvent
from app.phase8_models import OrganizationAccess
from test_phase19_portfolio import portfolio_client, grant
from test_phase20_imports import import_client

RECORD_TYPES = ["GRANT", "DONOR", "CSR_PROJECT", "VOLUNTEER", "MEMBERSHIP", "VOLUNTEER_ACTIVITY",
                "MANAGEMENT_MEMBER", "DONATION", "CAMPAIGN", "SPONSOR", "EVENT", "MESSAGE",
                "INQUIRY", "CERTIFICATE", "DOCUMENT_TEMPLATE", "CONTENT_PAGE", "NEWS", "GALLERY_ITEM",
                "TESTIMONIAL", "TRAINING_VIDEO"]

@pytest.mark.parametrize("record_type", RECORD_TYPES)
def test_existing_record_fields_updates_date_clear_and_audited_delete(record_type):
    with portfolio_client(role="ADMIN") as (client, _):
        created = client.post("/api/v1/portfolio-records", json={"organization_id":"org-aarohan",
            "record_type":record_type,"title":"Operational reference", "status":"CUSTOM_LABEL",
            "owner_name":"Responsible person","value_label":"Reference text", "due_at":"2030-01-01", "notes":"Internal note"})
        assert created.status_code == 201, created.text
        item = created.json(); assert item["can_edit"] and item["can_delete"]
        updated = client.patch(f"/api/v1/portfolio-records/{item['id']}", json={
            "title":"Updated reference","status":"RECORDED","owner_name":"New contact",
            "value_label":"Updated value","due_at":None,"notes":"Updated notes"})
        assert updated.status_code == 200, updated.text
        assert updated.json()["due_at"] is None and updated.json()["owner_name"] == "New contact"
        rows = client.get("/api/v1/portfolio-records", params={"organization_id":"org-aarohan","record_type":record_type}).json()
        assert any(row["id"] == item["id"] and row["notes"] == "Updated notes" for row in rows)
        assert client.delete(f"/api/v1/portfolio-records/{item['id']}").status_code == 204
        with SessionLocal() as db:
            actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == item["id"])))
            assert {f"{record_type}_CREATED",f"{record_type}_UPDATED",f"{record_type}_DELETED"} <= actions

def test_record_ui_capabilities_respect_workspace_and_organization_roles_and_tenant_boundaries():
    with portfolio_client(role="ADMIN") as (admin, _):
        item = admin.post("/api/v1/portfolio-records", json={"organization_id":"org-aarohan","record_type":"GRANT","title":"Scoped record"}).json()
        hidden = admin.post("/api/v1/portfolio-records", json={"organization_id":"org-udaan","record_type":"DONOR","title":"Hidden record"}).json()
        with portfolio_client() as (member, user):
            with SessionLocal() as db:
                grant(db,user,"org-aarohan",role="VIEWER");db.commit()
            rows = member.get("/api/v1/portfolio-records").json()
            assert all(row["organization_id"] == "org-aarohan" for row in rows)
            assert all(not row["can_edit"] and not row["can_delete"] for row in rows)
            assert member.patch(f"/api/v1/portfolio-records/{item['id']}", json={"notes":"bypass"}).status_code == 403
            assert member.delete(f"/api/v1/portfolio-records/{item['id']}").status_code == 403
            assert member.get("/api/v1/portfolio-records?organization_id=org-udaan").status_code in {403,404}
            assert member.patch(f"/api/v1/portfolio-records/{hidden['id']}", json={"status":"ACTIVE"}).status_code == 403
            with SessionLocal() as db:
                access = db.scalar(select(OrganizationAccess).where(OrganizationAccess.user_id == user.id))
                access.access_role = "CONTRIBUTOR"; db.commit()
            rows = member.get("/api/v1/portfolio-records").json()
            assert all(row["can_edit"] and not row["can_delete"] for row in rows)
            assert member.patch(f"/api/v1/portfolio-records/{item['id']}", json={"notes":"Authorized update"}).status_code == 200
            assert member.delete(f"/api/v1/portfolio-records/{item['id']}").status_code == 403
        with portfolio_client(role="VIEWER") as (viewer, _):
            assert all(not row["can_edit"] for row in viewer.get("/api/v1/portfolio-records").json())
            assert viewer.patch(f"/api/v1/portfolio-records/{item['id']}", json={"notes":"bypass"}).status_code == 403
        with import_client(tenant="other-operations-tenant") as (other, _):
            assert other.get("/api/v1/portfolio-records").json() == []
            assert other.patch(f"/api/v1/portfolio-records/{item['id']}", json={"title":"bypass"}).status_code == 404
            assert other.delete(f"/api/v1/portfolio-records/{item['id']}").status_code == 404
