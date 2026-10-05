"""Focused Phase 20 import parsing, dry-run, security and idempotency contracts."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import io
import json
from uuid import uuid4
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select

from app.auth import COOKIE_NAME, digest
from app.auth_models import AuthAccount, SessionContext
from app.database import SessionLocal
from app.main import app
from app.migrate_phase20 import VERSION, apply
from app.models import AuthSession, Membership, Organization, Subscription, Task, User, Workspace
from app.onboarding_models import OrganizationOnboarding
from app.phase20_models import ImportJob, ImportRowResult


@contextmanager
def import_client(*, tenant="tenant-demo", role="ADMIN", audience="user"):
    with TestClient(app) as client:
        token = "import-" + uuid4().hex
        with SessionLocal() as db:
            if not db.get(Workspace, tenant):
                db.add(Workspace(id=tenant, name="Import workspace")); db.flush()
            user = User(tenant_id=tenant, name="Import administrator", email=uuid4().hex + "@imports.test",
                        role=role, status="ACTIVE")
            db.add(user); db.flush()
            db.add(AuthAccount(user_id=user.id, verified=True, platform_access=audience == "admin"))
            db.add(AuthSession(token_hash=digest(token), user_id=user.id,
                               expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
            db.add(SessionContext(token_hash=digest(token), tenant_id=tenant, audience=audience))
            db.commit()
        client.cookies.set(COOKIE_NAME, token)
        client.headers["X-Setu-Request"] = "1"
        yield client, user


def upload(client, content: bytes, import_type="ORGANIZATIONS", filename="organizations.csv", content_type="text/csv"):
    return client.post("/api/v1/imports", data={"import_type": import_type},
                       files={"file": (filename, content, content_type)})


def organization_csv(*rows):
    header = "name,legal_type,registration_number,city,pan,contact_email,responsible_consultant_email\n"
    return (header + "\n".join(rows) + "\n").encode()


def validate(client, uploaded, *, resolutions=None):
    payload = uploaded.json()
    return client.post(f"/api/v1/imports/{payload['id']}/validate", json={
        "expected_revision": payload["revision"], "mapping": payload["suggested_mapping"],
        "resolutions": resolutions or {},
    })


def minimal_xlsx(rows, *, formula=False):
    cells = []
    for row_number, values in enumerate(rows, 1):
        columns = []
        for column, value in enumerate(values, 1):
            letter = chr(64 + column)
            formula_xml = f"<f>{value}</f><v>0</v>" if formula and row_number == 2 and column == 1 else f"<is><t>{value}</t></is>"
            cell_type = "" if formula and row_number == 2 and column == 1 else ' t="inlineStr"'
            columns.append(f'<c r="{letter}{row_number}"{cell_type}>{formula_xml}</c>')
        cells.append(f'<row r="{row_number}">{"".join(columns)}</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             f'<sheetData>{"".join(cells)}</sheetData></worksheet>')
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        archive.writestr("[Content_Types].xml", "<Types/>")
    return output.getvalue()


def test_dry_run_creates_nothing_then_confirm_is_row_atomic_idempotent_and_visible_in_portfolio():
    with import_client() as (client, actor):
        content = organization_csv(
            f"Imported Hope,TRUST,IMP-{uuid4().hex},Pune,,hope@example.test,{actor.email}",
            f"Imported Care,SOCIETY,IMP-{uuid4().hex},Mumbai,,,",
        )
        created = upload(client, content)
        assert created.status_code == 201, created.text
        dry_run = validate(client, created)
        assert dry_run.status_code == 200, dry_run.text
        assert dry_run.json()["status"] == "READY"
        assert dry_run.json()["valid_rows"] == 2
        with SessionLocal() as db:
            assert not db.scalar(select(Organization.id).where(Organization.name == "Imported Hope"))
        confirmed = client.post(f"/api/v1/imports/{created.json()['id']}/confirm", json={
            "expected_revision": dry_run.json()["revision"], "confirmation": "CONFIRM IMPORT",
        })
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "COMPLETED"
        assert confirmed.json()["created"] == 2
        replay = client.post(f"/api/v1/imports/{created.json()['id']}/confirm", json={
            "expected_revision": dry_run.json()["revision"], "confirmation": "CONFIRM IMPORT",
        })
        assert replay.status_code == 200 and replay.json()["already_completed"] is True
        with SessionLocal() as db:
            organizations = list(db.scalars(select(Organization).where(Organization.name.in_(("Imported Hope", "Imported Care")))).all())
            assert len(organizations) == 2
            assert all(db.get(OrganizationOnboarding, item.id).status == "IN_PROGRESS" for item in organizations)
        portfolio = client.get("/api/v1/portfolio/organizations", params={"q": "Imported"})
        assert portfolio.status_code == 200 and portfolio.json()["total"] == 2


def test_duplicate_resolution_is_explicit_and_manipulated_mapping_is_rejected():
    with import_client() as (client, _):
        with SessionLocal() as db:
            existing = db.scalar(select(Organization).where(Organization.tenant_id == "tenant-demo"))
            row = f"{existing.name},TRUST,{existing.registration_number},Pune,{existing.pan},,"
        created = upload(client, organization_csv(row))
        unresolved = validate(client, created)
        assert unresolved.status_code == 200
        assert unresolved.json()["status"] == "VALIDATION_FAILED"
        assert unresolved.json()["rows"][0]["errors"][0]["field"] == "resolution"
        resolved = client.post(f"/api/v1/imports/{created.json()['id']}/validate", json={
            "expected_revision": unresolved.json()["revision"], "mapping": created.json()["suggested_mapping"],
            "resolutions": {"2": {"action": "MAP", "organization_id": existing.id}},
        })
        assert resolved.status_code == 200 and resolved.json()["status"] == "READY"
        bad = client.post(f"/api/v1/imports/{created.json()['id']}/validate", json={
            "expected_revision": resolved.json()["revision"], "mapping": {"name": "unknown-column"}, "resolutions": {},
        })
        assert bad.status_code == 422


def test_malformed_files_formula_cells_and_limits_are_rejected():
    with import_client() as (client, _):
        assert upload(client, b"\xff\xfe\x00", filename="bad.csv").status_code == 422
        assert upload(client, b"not-a-zip", filename="bad.xlsx",
                      content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet").status_code == 422
        formula_book = minimal_xlsx([
            ["name", "legal_type", "registration_number", "city"],
            ["2+2", "TRUST", "FORMULA-1", "Pune"],
        ], formula=True)
        assert upload(client, formula_book, filename="formula.xlsx",
                      content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet").status_code == 422
        valid_book = minimal_xlsx([
            ["name", "legal_type", "registration_number", "city"],
            ["Workbook NGO", "TRUST", "XLSX-VALID-1", "Pune"],
        ])
        workbook_job = upload(client, valid_book, filename="valid.xlsx",
                              content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        assert workbook_job.status_code == 201
        assert validate(client, workbook_job).json()["status"] == "READY"
        formula_csv = upload(client, organization_csv("=cmd,TRUST,FORMULA-CSV,Pune,,,"))
        checked = validate(client, formula_csv)
        assert checked.json()["status"] == "VALIDATION_FAILED"
        too_many = ("name,legal_type,registration_number,city\n" +
                    "\n".join(f"NGO {index},TRUST,ROW-{index},Pune" for index in range(1001))).encode()
        assert upload(client, too_many).status_code == 413


def test_viewer_platform_admin_tenant_and_existing_record_boundaries():
    content = organization_csv(f"Boundary NGO,TRUST,BOUND-{uuid4().hex},Pune,,,")
    with import_client(role="VIEWER") as (viewer, _):
        assert upload(viewer, content).status_code == 403
    with import_client(audience="admin") as (platform, _):
        assert upload(platform, content).status_code == 403
    with import_client() as (owner, _):
        job = upload(owner, content).json()
    with import_client(tenant="other-import-tenant") as (other, _):
        assert other.get(f"/api/v1/imports/{job['id']}").status_code == 404
        registration = upload(other, b"organization_id,kind,status\norg-aarohan,80G,ACTIVE\n", "REGISTRATIONS")
        checked = validate(other, registration)
        assert checked.json()["status"] == "VALIDATION_FAILED"
        assert checked.json()["rows"][0]["errors"][0]["field"] == "organization_id"


def test_subscription_limits_block_whole_batch_before_mutation():
    with import_client() as (client, _):
        with SessionLocal() as db:
            subscription = db.scalar(select(Subscription).where(Subscription.tenant_id == "tenant-demo"))
            current = db.query(Organization).filter(Organization.tenant_id == "tenant-demo", Organization.status != "ARCHIVED").count()
            subscription.organization_limit = current
            db.commit()
        content = organization_csv(f"Limit NGO,TRUST,LIMIT-{uuid4().hex},Pune,,,")
        created = upload(client, content)
        dry_run = validate(client, created)
        blocked = client.post(f"/api/v1/imports/{created.json()['id']}/confirm", json={
            "expected_revision": dry_run.json()["revision"], "confirmation": "CONFIRM IMPORT",
        })
        assert blocked.status_code == 403
        assert blocked.json()["detail"] == "PLAN_LIMIT_REACHED:organizations"
        with SessionLocal() as db:
            assert not db.scalar(select(Organization.id).where(Organization.name == "Limit NGO"))


def test_confirm_commits_rows_independently_and_retry_does_not_duplicate_successes():
    with import_client() as (client, _):
        first_registration = "ATOMIC-A-" + uuid4().hex
        second_registration = "ATOMIC-B-" + uuid4().hex
        created = upload(client, organization_csv(
            f"Atomic Success,TRUST,{first_registration},Pune,, ,",
            f"Atomic Conflict,TRUST,{second_registration},Pune,, ,",
        ))
        dry_run = validate(client, created)
        assert dry_run.status_code == 200 and dry_run.json()["status"] == "READY"
        with SessionLocal() as db:
            db.add(Organization(tenant_id="tenant-demo", name="Late conflict", legal_type="TRUST",
                                registration_number=second_registration, city="Pune"))
            db.commit()
        confirmed = client.post(f"/api/v1/imports/{created.json()['id']}/confirm", json={
            "expected_revision": dry_run.json()["revision"], "confirmation": "CONFIRM IMPORT",
        })
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "COMPLETED_WITH_ERRORS"
        assert confirmed.json()["created"] == 1 and confirmed.json()["failed"] == 1
        replay = client.post(f"/api/v1/imports/{created.json()['id']}/confirm", json={
            "expected_revision": dry_run.json()["revision"], "confirmation": "CONFIRM IMPORT",
        })
        assert replay.status_code == 200 and replay.json()["created"] == 1
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(Organization).where(
                Organization.tenant_id == "tenant-demo", Organization.registration_number == first_registration,
            )) == 1


def test_invitation_user_limit_and_result_csv_formula_safety():
    with import_client() as (client, _):
        csv_data = b"organization_id,name,email,role\norg-aarohan,Imported Viewer,imported-viewer@example.test,VIEWER\n"
        created = upload(client, csv_data, "INVITATIONS", "invitations.csv")
        dry_run = validate(client, created)
        assert dry_run.status_code == 200 and dry_run.json()["status"] == "READY"
        with SessionLocal() as db:
            subscription = db.scalar(select(Subscription).where(Subscription.tenant_id == "tenant-demo"))
            from app.features import subscription_usage
            subscription.user_limit = int(subscription_usage(db, "tenant-demo")["users"])
            db.commit()
        blocked = client.post(f"/api/v1/imports/{created.json()['id']}/confirm", json={
            "expected_revision": dry_run.json()["revision"], "confirmation": "CONFIRM IMPORT",
        })
        assert blocked.status_code == 403 and blocked.json()["detail"] == "PLAN_LIMIT_REACHED:users"
        with SessionLocal() as db:
            row = db.scalar(select(ImportRowResult).where(ImportRowResult.job_id == created.json()["id"]))
            row.errors_json = json.dumps([{"field": "row", "message": "=HYPERLINK(unsafe)"}])
            db.commit()
        exported = client.get(f"/api/v1/imports/{created.json()['id']}/results.csv")
        assert exported.status_code == 200 and "'=HYPERLINK" in exported.text


def test_task_assignment_reuses_existing_authorization_and_notification_path():
    with import_client() as (client, actor):
        with SessionLocal() as db:
            task = db.scalar(select(Task).where(Task.tenant_id == "tenant-demo"))
            task_id = task.id
        csv_data = f"task_id,assignee_email\n{task_id},{actor.email}\n".encode()
        created = upload(client, csv_data, "TASK_ASSIGNMENTS", "assignments.csv")
        dry_run = validate(client, created)
        assert dry_run.status_code == 200 and dry_run.json()["status"] == "READY"
        confirmed = client.post(f"/api/v1/imports/{created.json()['id']}/confirm", json={
            "expected_revision": dry_run.json()["revision"], "confirmation": "CONFIRM IMPORT",
        })
        assert confirmed.status_code == 200 and confirmed.json()["mapped"] == 1
        with SessionLocal() as db:
            assert db.get(Task, task_id).assignee_user_id == actor.id


def test_phase20_migration_is_additive_and_idempotent(tmp_path):
    target = create_engine(f"sqlite:///{tmp_path / 'phase20.db'}")
    Workspace.__table__.create(target)
    User.__table__.create(target)
    Organization.__table__.create(target)
    assert apply(target) == VERSION
    assert apply(target) == VERSION
    assert {"import_jobs", "import_row_results"} <= set(inspect(target).get_table_names())


def test_cancelled_import_cannot_validate_execute_or_mutate_and_replay_keeps_cancelled_state():
    with import_client() as (client, _):
        content = organization_csv(f"Cancelled NGO,TRUST,CANCEL-{uuid4().hex},Pune,,,")
        uploaded = upload(client, content)
        checked = validate(client, uploaded).json()
        job_id = checked["id"]
        cancelled = client.post(f"/api/v1/imports/{job_id}/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
        assert client.get(f"/api/v1/imports/{job_id}").json()["status"] == "CANCELLED"
        assert client.post(f"/api/v1/imports/{job_id}/validate", json={
            "expected_revision":checked["revision"], "mapping":checked["mapping"], "resolutions":{},
        }).status_code == 409
        assert client.post(f"/api/v1/imports/{job_id}/confirm", json={
            "expected_revision":checked["revision"], "confirmation":"CONFIRM IMPORT",
        }).status_code == 409
        assert upload(client, content).json()["status"] == "CANCELLED"
        with SessionLocal() as db:
            assert not db.scalar(select(Organization.id).where(Organization.name == "Cancelled NGO"))
        with import_client(tenant="cancel-other-tenant") as (other, _):
            assert other.post(f"/api/v1/imports/{job_id}/cancel").status_code == 404
            assert other.get(f"/api/v1/imports/{job_id}/results").status_code == 404
        with import_client(role="VIEWER") as (viewer, _):
            assert viewer.get(f"/api/v1/imports/{job_id}").status_code == 403
            assert viewer.post(f"/api/v1/imports/{job_id}/cancel").status_code == 403
        with import_client(role="MEMBER") as (member, _):
            assert member.get(f"/api/v1/imports/{job_id}").status_code == 403
        with import_client(audience="admin") as (platform, _):
            assert platform.get(f"/api/v1/imports/{job_id}").status_code == 403
            assert platform.post(f"/api/v1/imports/{job_id}/cancel").status_code == 403


def test_resume_retrieves_saved_resolution_revision_and_results_without_executing():
    with import_client() as (client, _):
        with SessionLocal() as db:
            existing = db.scalar(select(Organization).where(Organization.tenant_id == "tenant-demo"))
            row = f"{existing.name},TRUST,{existing.registration_number},Pune,{existing.pan},,"
            organization_id = existing.id
        uploaded = upload(client, organization_csv(row))
        unresolved = validate(client, uploaded).json()
        resolved = client.post(f"/api/v1/imports/{unresolved['id']}/validate", json={
            "expected_revision":unresolved["revision"],"mapping":uploaded.json()["suggested_mapping"],
            "resolutions":{"2":{"action":"MAP","organization_id":organization_id}},
        }).json()
        reopened = client.get(f"/api/v1/imports/{resolved['id']}").json()
        rows = client.get(f"/api/v1/imports/{resolved['id']}/results").json()["rows"]
        assert reopened["status"] == "READY" and reopened["revision"] == resolved["revision"]
        assert reopened["mapping"] == resolved["mapping"]
        assert rows[0]["resolution"] == "MAP" and rows[0]["existing_organization_id"] == organization_id
        assert reopened["created"] == 0 and reopened["mapped"] == 0
        completed = client.post(f"/api/v1/imports/{resolved['id']}/confirm", json={
            "expected_revision":resolved["revision"],"confirmation":"CONFIRM IMPORT",
        })
        assert completed.json()["mapped"] == 1
        assert client.post(f"/api/v1/imports/{resolved['id']}/cancel").status_code == 409
        with SessionLocal() as db:
            job = db.get(ImportJob, uploaded.json()["id"])
            job.status = "UPLOADED"; job.expires_at = datetime.now(timezone.utc) - timedelta(days=1); db.commit()
        assert client.get(f"/api/v1/imports/{resolved['id']}").status_code == 410
