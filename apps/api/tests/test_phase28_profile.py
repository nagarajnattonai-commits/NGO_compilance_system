"""Phase 28: registration verification, profile change history and server-saved reminder lead time."""
from sqlalchemy import create_engine, inspect, select, text

from app.database import SessionLocal
from app.migrate_phase28 import VERSION, apply
from app.models import Document, User
from app.organization_models import OrganizationProfileChange
from test_compliance_master import platform_client

PATH = "/api/v1/organizations/org-udaan/profile"


def add_certificate(document_id="cert-12ab"):
    with SessionLocal() as db:
        db.add(Document(id=document_id, tenant_id="tenant-demo", organization_id="org-udaan", name="12AB certificate",
                        category="12AB", uploaded_by="Master Admin"))
        db.commit()


def registration(client, kind="12AB"):
    return next(r for r in client.get(PATH).json()["registrations"] if r["kind"] == kind)


def save(client, revision, **row):
    return client.patch(PATH, json={"expected_revision": revision, "registrations": [{"kind": "12AB", **row}]})


def test_verification_needs_evidence_records_verifier_and_resets_on_changed_facts(monkeypatch):
    with platform_client(monkeypatch) as client:
        add_certificate()
        base = {"status": "ACTIVE", "number": "AAATS1234F-12AB", "issuing_authority": "Commissioner of Income Tax (Exemptions)"}
        no_evidence = save(client, 0, **base, verification_status="VERIFIED")
        assert no_evidence.status_code == 422 and "document" in no_evidence.text
        verified = save(client, 0, **base, document_id="cert-12ab", verification_status="VERIFIED")
        assert verified.status_code == 200, verified.text
        row = registration(client)
        assert row["verification_status"] == "VERIFIED" and row["verified_by"] == "Master Admin" and row["verified_at"]
        assert row["issuing_authority"] == base["issuing_authority"]
        # Saving the same facts again keeps the verification.
        assert save(client, 1, **base, document_id="cert-12ab", verification_status="VERIFIED").status_code == 200
        assert registration(client)["verification_status"] == "VERIFIED"
        # Changing a fact while still marked verified needs a fresh check.
        changed = save(client, 2, **base | {"number": "AAATS1234F-12AB-NEW"}, document_id="cert-12ab", verification_status="VERIFIED")
        assert changed.status_code == 200
        row = registration(client)
        assert row["verification_status"] == "NEEDS_REVIEW" and row["verified_by"] == "" and row["verified_at"] is None


def test_responsible_person_must_have_access_to_the_organization(monkeypatch):
    with platform_client(monkeypatch) as client:
        assert save(client, 0, responsible_user_id="not-a-member").status_code == 422
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.email == "master@example.test"))
        assert save(client, 0, responsible_user_id=admin.id).status_code == 200
        assert registration(client)["responsible_user_id"] == admin.id


def test_profile_history_keeps_field_values_and_masks_identifiers(monkeypatch):
    with platform_client(monkeypatch) as client:
        before = client.get(PATH).json()
        core = {k: before["core"][k] for k in ("name", "legal_type", "registration_number", "status", "city", "pan")}
        core.update(pan="ABCDE1234F", city="Sample Nagar")
        response = client.patch(PATH, json={"expected_revision": 0, "core": core,
                                            "details": {"contact_phone": "+919876543210", "state": "Maharashtra"}})
        assert response.status_code == 200, response.text
        history = client.get("/api/v1/organizations/org-udaan/profile-history").json()
        by_field = {row["field"]: row for row in history}
        assert by_field["city"]["new_value"] == "Sample Nagar" and by_field["city"]["old_value"] == before["core"]["city"]
        assert by_field["state"]["new_value"] == "Maharashtra"
        assert by_field["pan"]["new_value"].endswith("234F") and "ABCDE" not in by_field["pan"]["new_value"]
        assert by_field["contact_phone"]["new_value"].endswith("3210") and "98765" not in by_field["contact_phone"]["new_value"]
        assert all(row["changed_by"] == "Master Admin" and row["revision"] == 1 for row in history)
        assert client.get("/api/v1/organizations/foreign-org/profile-history").status_code == 404
        with SessionLocal() as db:
            assert db.scalars(select(OrganizationProfileChange)).all()


def test_reminder_lead_days_are_saved_per_user_and_bounded(monkeypatch):
    with platform_client(monkeypatch) as client:
        assert client.get("/api/v1/notification-preferences").json()["default_lead_days"] == 7
        saved = client.patch("/api/v1/notification-preferences", json={"default_lead_days": 21})
        assert saved.status_code == 200 and saved.json()["default_lead_days"] == 21
        assert client.get("/api/v1/notification-preferences").json()["default_lead_days"] == 21
        for bad in (0, 61):
            assert client.patch("/api/v1/notification-preferences", json={"default_lead_days": bad}).status_code == 422


def test_admin_notification_policy_keeps_in_app_mandatory(monkeypatch):
    with platform_client(monkeypatch) as client:
        assert client.get("/api/v1/admin/notification-policy").json()["mandatory_channels"] == ["IN_APP"]
        assert client.put("/api/v1/admin/notification-policy", json={"mandatory_channels": ["EMAIL"]}).status_code == 422
        saved = client.put("/api/v1/admin/notification-policy", json={"mandatory_channels": ["IN_APP", "EMAIL"]})
        assert saved.json()["mandatory_channels"] == ["EMAIL", "IN_APP"]


def test_phase28_migration_adds_columns_to_an_older_schema(tmp_path):
    target = create_engine(f"sqlite:///{tmp_path / 'phase28.db'}")
    with target.begin() as connection:
        connection.execute(text("CREATE TABLE organization_registrations (id VARCHAR(36) PRIMARY KEY, kind VARCHAR(12))"))
        connection.execute(text("INSERT INTO organization_registrations (id, kind) VALUES ('r1', '80G')"))
        connection.execute(text("CREATE TABLE user_notification_preferences (user_id VARCHAR(36) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO user_notification_preferences (user_id) VALUES ('u1')"))
    assert apply(target) == VERSION and apply(target) == VERSION
    columns = {c["name"] for c in inspect(target).get_columns("organization_registrations")}
    assert {"issuing_authority", "verification_status", "verified_by", "verified_at", "responsible_user_id"} <= columns
    assert inspect(target).has_table("organization_profile_changes")
    with target.connect() as connection:
        assert connection.execute(text("SELECT verification_status FROM organization_registrations")).scalar() == "UNVERIFIED"
        assert connection.execute(text("SELECT default_lead_days FROM user_notification_preferences")).scalar() == 7
    target.dispose()



def test_partial_registration_updates_keep_review_fields_and_flag_changed_evidence(monkeypatch):
    from app.organization_profile import ProfileInput, RegistrationInput, save_profile
    from app.models import Organization
    with platform_client(monkeypatch) as client:
        add_certificate("cert-partial")
        base = {"status": "ACTIVE", "number": "AAATS1234F-12AB", "issuing_authority": "CIT (Exemptions)",
                "document_id": "cert-partial", "verification_status": "VERIFIED"}
        assert save(client, 0, **base).status_code == 200
        # An import or document fact sends only the original registration fields.
        with SessionLocal() as db:
            actor = type("Actor", (), {"name": "Importer", "id": "importer"})()
            org = db.get(Organization, "org-udaan")
            partial = RegistrationInput.model_validate({"kind": "12AB", "status": "ACTIVE", "number": "AAATS1234F-12AB-NEW",
                                                         "document_id": "cert-partial"})
            save_profile(org.id, ProfileInput(expected_revision=1, registrations=[partial]), db, org.tenant_id, actor)
        row = registration(client)
        assert row["issuing_authority"] == "CIT (Exemptions)"
        assert row["verification_status"] == "NEEDS_REVIEW"
        assert row["verified_by"] == "" and row["verified_at"] is None
