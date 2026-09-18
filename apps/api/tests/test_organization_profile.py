from datetime import date
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from app.auth import digest
from app.auth_models import SessionContext
from app.database import Base, SessionLocal
from app.migrate_organization import apply
from app.models import AuditEvent, Document, Organization, User
from app.organization_models import OrganizationDetails, OrganizationRegistration
from app.organization_profile import DetailsInput, RegistrationInput, expanded_facts
from app.compliance_engine import evaluate_rules
from app.compliance_template_schema import TemplateConfiguration, Condition
from test_compliance_master import platform_client

PATH = "/api/v1/organizations/org-udaan/profile"

def test_structured_profile_roundtrip_revision_financial_and_safe_audit(monkeypatch):
    with platform_client(monkeypatch) as client:
        initial = client.get(PATH).json()
        assert initial["revision"] == 0 and initial["completeness"]["purpose"] == "SETUP_COMPLETENESS_NOT_LEGAL_HEALTH"
        core = {k: initial["core"][k] for k in ("name", "legal_type", "registration_number", "status", "city", "pan")}
        core.update(pan="ABCDE1234F", legal_type="SECTION_8")
        response = client.patch(PATH, json={"expected_revision":0, "core":core, "details":{"tan":"ABCD12345E", "registration_date":"2020-01-01", "registration_authority":"Sample registrar", "contact_email":"Setup@Example.test"}, "registrations":[{"kind":"12AB","status":"ACTIVE","number":"sample-12ab","effective_date":"2025-01-01","expiry_date":"2030-01-01"},{"kind":"GST","status":"NOT_REGISTERED"},{"kind":"FCRA","status":"NOT_REGISTERED"}], "financial":{"annual_revenue":"123.45","revenue_period":"2025-26"}})
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["revision"] == 1 and saved["financial"]["annual_revenue"] == "123.45"
        assert saved["core"]["legal_type"] == "SECTION 8" and saved["details"]["contact_email"] == "setup@example.test"
        assert client.patch(PATH, json={"expected_revision":0,"details":{"notes":"Stale write"}}).status_code == 409
        assert client.get(PATH).json()["revision"] == 1
        with SessionLocal() as db:
            org=db.get(Organization,"org-udaan"); facts=expanded_facts(db,org)
            assert facts["organization.12ab.expiry_date"] == date(2030,1,1)
            assert facts["organization.gst.registered"] is False and facts["organization.fcra.status"] == "NOT_REGISTERED"
            assert org.fcra_active is False
            event=db.scalar(select(AuditEvent).where(AuditEvent.action=="ORGANIZATION_PROFILE_UPDATED"))
            assert "pan" in event.summary and "ABCDE1234F" not in event.summary and "ABCD12345E" not in event.summary

def test_profile_tenant_boundaries_document_reference_and_readonly_roles(monkeypatch):
    with platform_client(monkeypatch) as client:
        with SessionLocal() as db:
            db.add(Organization(id="foreign-org",tenant_id="other",name="Foreign",legal_type="TRUST",registration_number="foreign",city="City"))
            db.add(Document(id="foreign-doc",tenant_id="other",organization_id="foreign-org",name="Certificate",category="12AB",uploaded_by="Foreign"));db.commit()
        assert client.get("/api/v1/organizations/foreign-org/profile").status_code == 404
        assert client.patch(PATH,json={"expected_revision":0,"registrations":[{"kind":"12AB","document_id":"foreign-doc"}]}).status_code == 404
        assert client.get(PATH).json()["revision"] == 0
        with SessionLocal() as db:
            actor=db.scalar(select(User).where(User.email=="master@example.test"));actor.role="VIEWER"
            db.get(SessionContext,digest("master-test")).audience="user";db.commit()
        assert client.get(PATH).status_code == 200
        assert client.patch(PATH,json={"expected_revision":0,"details":{"notes":"Denied"}}).status_code == 403
        assert client.patch("/api/v1/organizations/org-udaan",json={"status":"ARCHIVED"}).status_code == 403

def test_expanded_registry_missing_facts_are_reviewable_and_operators_typed(monkeypatch):
    with platform_client(monkeypatch):
        config=TemplateConfiguration.model_validate({"applicability":{"groups":[{"id":"g","conditions":[{"id":"c","field":"organization.12ab.status","operator":"EQUALS","value":"ACTIVE"}]}]}})
        with SessionLocal() as db:
            org=db.get(Organization,"org-udaan")
            result=evaluate_rules(config,org,expanded_facts(db,org))
            assert not result["applicable"] and result["requires_review"]
        with pytest.raises(ValidationError): Condition(id="c",field="organization.__class__",operator="EQUALS",value="anything")
        with pytest.raises(ValidationError): Condition(id="c",field="organization.pan_present",operator="CONTAINS",value="x")
        with pytest.raises(ValidationError): RegistrationInput(kind="12AB",effective_date=date(2030,1,1),expiry_date=date(2029,1,1))
        with pytest.raises(ValidationError): DetailsInput(tan="invalid")
        with pytest.raises(ValidationError): DetailsInput(website="javascript:alert(1)")

def test_additive_migration_preserves_legacy_rows_and_is_idempotent():
    engine=create_engine("sqlite:///:memory:")
    excluded={OrganizationDetails.__table__.name,OrganizationRegistration.__table__.name}
    with engine.begin() as c:
        for table in Base.metadata.sorted_tables:
            if table.name not in excluded: table.create(c)
        c.execute(Organization.__table__.insert().values(id="legacy",tenant_id="tenant",name="Preserved NGO",legal_type="TRUST",registration_number="legacy",city="City"))
    assert apply(engine)==apply(engine)
    with engine.connect() as c:
        assert c.execute(select(Organization.__table__.c.name).where(Organization.__table__.c.id=="legacy")).scalar_one()=="Preserved NGO"
        assert c.execute(select(OrganizationDetails.__table__)).all()==[]
