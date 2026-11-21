"""Phase 29: donation register (phase A of the NGO operations design)."""
from contextlib import ExitStack
from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.database import SessionLocal
from app.donation_api import financial_year
from app.donation_models import Donor
from app.models import AuditEvent, Document, Task, TenantEntitlement
from app.organization_models import OrganizationRegistration
from test_phase19_portfolio import grant, portfolio_client

ORG = "org-aarohan"


def ok(response, code=200):
    assert response.status_code == code, response.text
    return response.json()


def donor(client, organization=ORG, **values):
    body = {"organization_id": organization, "name": "Donor " + uuid4().hex[:8], "address": "12 Sample Road, Pune", **values}
    return ok(client.post("/api/v1/donations/donors", json=body), 201)


def donation(client, donor_id, received_on, amount=50_000_00, organization=ORG, **values):
    body = {"organization_id": organization, "donor_id": donor_id, "received_on": received_on.isoformat(),
            "amount_paise": amount, "mode": "BANK_TRANSFER", **values}
    return ok(client.post("/api/v1/donations", json=body), 201)


def test_financial_year_runs_april_to_march():
    assert financial_year(date(2026, 3, 31)) == "2025-26"
    assert financial_year(date(2026, 4, 1)) == "2026-27"
    assert financial_year(date(2099, 12, 1)) == "2099-00"


def test_register_flow_encrypts_identity_locks_confirmed_entries_and_numbers_receipts():
    with portfolio_client("ADMIN") as (admin, _):
        pan = "ABCPE" + str(1000 + int(uuid4().int % 8999)) + "F"
        created = donor(admin, id_type="PAN", id_number=pan.lower(), email="Donor@Example.org")
        assert created["id_masked"] == "••••••" + pan[-4:] and pan not in str(created)
        with SessionLocal() as db:
            stored = db.get(Donor, created["id"])
            assert stored.id_cipher and pan not in stored.id_cipher and stored.email == "donor@example.org"
        duplicate = admin.post("/api/v1/donations/donors", json={"organization_id": ORG, "name": "Someone else",
                                                                 "id_type": "PAN", "id_number": pan})
        assert duplicate.status_code == 409
        assert admin.post("/api/v1/donations/donors", json={"organization_id": ORG, "name": "Bad PAN",
                                                            "id_type": "PAN", "id_number": "12345"}).status_code == 422
        revealed = ok(admin.post(f"/api/v1/donations/donors/{created['id']}/reveal-identity"))
        assert revealed["id_number"] == pan

        received = date(2023, 6, 15)
        first = donation(admin, created["id"], received)
        assert first["financial_year"] == "2023-24" and first["status"] == "DRAFT" and first["fcra_flag"] is False
        assert admin.post("/api/v1/donations", json={"organization_id": ORG, "donor_id": created["id"],
                                                     "received_on": (date.today() + timedelta(days=2)).isoformat(),
                                                     "amount_paise": 100, "mode": "UPI"}).status_code == 422
        assert admin.post("/api/v1/donations", json={"organization_id": ORG, "donor_id": created["id"],
                                                     "received_on": received.isoformat(), "amount_paise": 0, "mode": "UPI"}).status_code == 422
        assert admin.post(f"/api/v1/donations/{first['id']}/receipt", json={}).status_code == 409  # draft
        confirmed = ok(admin.post(f"/api/v1/donations/{first['id']}/confirm"))
        assert confirmed["status"] == "CONFIRMED"
        assert admin.patch(f"/api/v1/donations/{first['id']}", json={"amount_paise": 1}).status_code == 409
        assert admin.delete(f"/api/v1/donations/{first['id']}").status_code == 409
        receipt = ok(admin.post(f"/api/v1/donations/{first['id']}/receipt", json={}), 201)
        assert receipt["receipt"]["receipt_number"].startswith("RCPT/2023-24/")
        assert admin.post(f"/api/v1/donations/{first['id']}/receipt", json={}).status_code == 409
        second = donation(admin, created["id"], received + timedelta(days=1))
        ok(admin.post(f"/api/v1/donations/{second['id']}/confirm"))
        next_receipt = ok(admin.post(f"/api/v1/donations/{second['id']}/receipt", json={}), 201)["receipt"]["receipt_number"]
        assert int(next_receipt.rsplit("/", 1)[1]) == int(receipt["receipt"]["receipt_number"].rsplit("/", 1)[1]) + 1

        assert admin.post(f"/api/v1/donations/{first['id']}/reverse", json={"reason": "no"}).status_code == 422
        reversed_row = ok(admin.post(f"/api/v1/donations/{first['id']}/reverse", json={"reason": "Wrong amount typed"}))
        assert reversed_row["status"] == "REVERSED" and reversed_row["reversal_reason"] == "Wrong amount typed"
        replacement = donation(admin, created["id"], received, amount=40_000_00, replaces_id=first["id"])
        assert replacement["replaces_id"] == first["id"]
        assert admin.post("/api/v1/donations", json={"organization_id": ORG, "donor_id": created["id"], "received_on": received.isoformat(),
                                                     "amount_paise": 100, "mode": "UPI", "replaces_id": second["id"]}).status_code == 422
        with SessionLocal() as db:
            actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.entity_id.in_([first["id"], created["id"]]))).all())
        assert {"DONOR_CREATED", "DONOR_IDENTITY_REVEALED", "DONATION_RECORDED", "DONATION_CONFIRMED",
                "DONATION_RECEIPT_ISSUED", "DONATION_REVERSED"} <= actions


def test_second_person_confirms_and_only_managers_confirm():
    with ExitStack() as stack:
        admin, _ = stack.enter_context(portfolio_client("ADMIN"))
        recorder, recorder_user = stack.enter_context(portfolio_client("MEMBER"))
        reviewer, reviewer_user = stack.enter_context(portfolio_client("MEMBER"))
        contributor, contributor_user = stack.enter_context(portfolio_client("MEMBER"))
        viewer, viewer_user = stack.enter_context(portfolio_client("VIEWER"))
        outsider, _ = stack.enter_context(portfolio_client("MEMBER"))
        with SessionLocal() as db:
            grant(db, recorder_user, ORG, "MANAGER")
            grant(db, reviewer_user, ORG, "MANAGER")
            grant(db, contributor_user, ORG, "CONTRIBUTOR")
            grant(db, viewer_user, ORG, "VIEWER")
            db.commit()
        person = donor(recorder, id_type="AADHAAR", id_number="1234 5678 " + str(1000 + int(uuid4().int % 8999)))
        entry = donation(recorder, person["id"], date(2022, 5, 1))
        assert recorder.post(f"/api/v1/donations/{entry['id']}/confirm").status_code == 403
        assert contributor.post(f"/api/v1/donations/{entry['id']}/confirm").status_code == 403
        assert viewer.post(f"/api/v1/donations/{entry['id']}/confirm").status_code == 403
        assert outsider.get("/api/v1/donations", params={"organization_id": ORG}).status_code == 403
        assert ok(reviewer.post(f"/api/v1/donations/{entry['id']}/confirm"))["confirmed_by"] == "Portfolio consultant"
        assert reviewer.post(f"/api/v1/donations/{entry['id']}/reverse", json={"reason": "Not allowed here"}).status_code == 403
        assert reviewer.post(f"/api/v1/donations/donors/{person['id']}/reveal-identity").status_code == 403
        seen = next(row for row in ok(viewer.get("/api/v1/donations/donors", params={"organization_id": ORG})) if row["id"] == person["id"])
        assert "address" not in seen and "id_masked" not in seen and seen["has_identity"] is True
        assert viewer.post("/api/v1/donations/donors", json={"organization_id": ORG, "name": "Viewer write"}).status_code == 403
        assert ok(admin.get("/api/v1/donations", params={"organization_id": ORG, "financial_year": "2022-23"}))


def test_foreign_source_into_domestic_account_warns_and_creates_task():
    with portfolio_client("ADMIN") as (admin, _):
        domestic = ok(admin.post("/api/v1/donations/bank-accounts", json={"organization_id": ORG, "label": "Main account",
                                                                          "last_four": "1234"}), 201)
        fcra = ok(admin.post("/api/v1/donations/bank-accounts", json={"organization_id": ORG, "label": "FCRA designated",
                                                                      "kind": "FCRA_DESIGNATED"}), 201)
        assert admin.post("/api/v1/donations/bank-accounts", json={"organization_id": ORG, "label": "Full number",
                                                                   "last_four": "123456789"}).status_code == 422
        foreign = donor(admin, donor_type="FOREIGN_SOURCE")
        assert foreign["is_foreign_source"] is True
        wrong = donation(admin, foreign["id"], date(2021, 7, 1), currency="USD", bank_account_id=domestic["id"])
        assert "FOREIGN_SOURCE_TO_DOMESTIC_ACCOUNT" in wrong["warnings"] and wrong["fcra_flag"] is True
        with SessionLocal() as db:
            task = db.scalar(select(Task).where(Task.title.contains(foreign["name"])))
            assert task and task.priority == "CRITICAL"
        right = donation(admin, foreign["id"], date(2021, 7, 2), bank_account_id=fcra["id"])
        assert "FOREIGN_SOURCE_TO_DOMESTIC_ACCOUNT" not in right["warnings"] and right["fcra_flag"] is True
        cash = donation(admin, donor(admin)["id"], date(2021, 7, 3), amount=5_000_00, mode="CASH")
        assert "CASH_ABOVE_DEDUCTION_LIMIT" in cash["warnings"]


def test_statement_flags_gaps_creates_tasks_and_tracks_certificates():
    with portfolio_client("ADMIN") as (admin, _):
        with SessionLocal() as db:
            reg = db.scalar(select(OrganizationRegistration).where(OrganizationRegistration.organization_id == "org-udaan",
                                                                   OrganizationRegistration.kind == "80G"))
            if reg:
                reg.status, reg.verification_status = "PENDING", "UNVERIFIED"
            db.add(Document(id="doc-10bd-" + uuid4().hex[:6], tenant_id="tenant-demo", organization_id="org-udaan",
                            name="10BD acknowledgement", category="Tax", uploaded_by="Admin"))
            db.commit()
        org = "org-udaan"
        with_pan = donor(admin, organization=org, id_type="PAN", id_number="AAAPZ" + str(1000 + int(uuid4().int % 8999)) + "Q")
        without = donor(admin, organization=org, address="")
        year_day = date(2020, 9, 10)
        for person in (with_pan, without):
            entry = donation(admin, person["id"], year_day, organization=org)
            ok(admin.post(f"/api/v1/donations/{entry['id']}/confirm"))
            issued = ok(admin.post(f"/api/v1/donations/{entry['id']}/receipt", json={}), 201)
            assert issued["receipt_warning"] == "REGISTRATION_80G_NOT_ACTIVE_AND_VERIFIED"
        donation(admin, with_pan["id"], year_day, organization=org)  # stays a draft
        summary = ok(admin.get("/api/v1/donations/statement", params={"organization_id": org, "financial_year": "2020-21"}))
        assert summary["due_on"] == "2021-05-31" and summary["rules_status"] == "PENDING_CA_REVIEW"
        assert summary["totals"]["confirmed_count"] == 2 and summary["totals"]["draft_count"] == 1
        gap = next(item for item in summary["donor_issues"] if item["donor_id"] == without["id"])
        assert set(gap["missing"]) == {"IDENTITY", "ADDRESS"}
        assert summary["statement"] is None
        assert admin.get("/api/v1/donations/statement", params={"organization_id": org, "financial_year": "2020-22"}).status_code == 422

        prepared = ok(admin.post("/api/v1/donations/statement", json={"organization_id": org, "financial_year": "2020-21"}), 201)
        again = ok(admin.post("/api/v1/donations/statement", json={"organization_id": org, "financial_year": "2020-21"}), 201)
        statement_id = prepared["statement"]["id"]
        assert again["statement"]["id"] == statement_id
        with SessionLocal() as db:
            tasks = db.scalars(select(Task).where(Task.organization_id == org, Task.title.contains("for 2020-21"))).all()
            assert len(tasks) == 2 and all(task.due_at == date(2021, 5, 31) for task in tasks)
        assert admin.patch(f"/api/v1/donations/statement/{statement_id}", json={"status": "FILED"}).status_code == 422
        filed = ok(admin.patch(f"/api/v1/donations/statement/{statement_id}",
                               json={"status": "FILED", "filed_on": "2021-05-20", "acknowledgement_number": "ACK-2021-1"}))
        assert filed["statement"]["status"] == "FILED"
        assert [c["donor_id"] for c in filed["certificates"]] == [with_pan["id"]]
        certificate = filed["certificates"][0]
        assert certificate["amount_paise"] == 50_000_00
        assert admin.patch(f"/api/v1/donations/certificates/{certificate['id']}", json={"status": "SENT"}).status_code == 422
        done = ok(admin.patch(f"/api/v1/donations/certificates/{certificate['id']}",
                              json={"status": "SENT", "certificate_number": "10BE-0001"}))
        assert done["certificates"][0]["status"] == "SENT" and done["certificates"][0]["sent_on"]
        with SessionLocal() as db:
            assert {task.status for task in db.scalars(select(Task).where(Task.organization_id == org,
                                                                         Task.title.contains("for 2020-21"))).all()} == {"DONE"}


def test_disabled_entitlement_blocks_the_register():
    with portfolio_client("ADMIN") as (admin, _):
        with SessionLocal() as db:
            db.add(TenantEntitlement(tenant_id="tenant-demo", feature_key="donation_register", enabled=False))
            db.commit()
        try:
            response = admin.get("/api/v1/donations", params={"organization_id": ORG})
            assert response.status_code == 403 and "donation_register" in response.text
        finally:
            with SessionLocal() as db:
                for row in db.scalars(select(TenantEntitlement).where(TenantEntitlement.feature_key == "donation_register")).all():
                    db.delete(row)
                db.commit()
