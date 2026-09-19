import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from threading import Barrier
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from app.auth import digest
from app.auth_models import WorkspaceAccess, SessionContext
from app.database import SessionLocal, engine
from app.models import AuthSession, Organization, User, Workspace, Membership, ComplianceSnapshot, Compliance, Task, AuditEvent
from app.organization_models import OrganizationRegistration
from app.runtime_models import ApplicabilityDecision, OrganizationEventFact, ComplianceOwnership
from app.runtime_membership import actor_roles
from app.runtime_cycles import generate_due_instances, generate_next_cycle
from app.migrate_runtime import apply
from test_compliance_master import create, publish, platform_client
from test_documents import upload_original

def configured(client, code="RUNTIME-SAMPLE", change=None):
    row=create(client,code)
    if change:
        change(row["configuration"])
        response=client.patch(f"/api/v1/admin/compliance-templates/{row['id']}",json={"expected_revision":0,"configuration":row["configuration"],"change_summary":"Sample runtime configuration"})
        assert response.status_code==200,response.text
        row=response.json()
    return publish(client,row)
def generate(client,code):
    response=client.post("/api/v1/organizations/org-udaan/generate-plan")
    assert response.status_code==200,response.text
    return next(c for c in response.json() if c["code"]==code)
def switch_role(role):
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.email=="master@example.test"));user.role=role
        db.get(SessionContext,digest("master-test")).audience="user";db.commit()

def test_additional_workspace_owner_manual_assignment_and_inactive_access(monkeypatch):
    with platform_client(monkeypatch) as client:
        def change(c):c["responsibility"].update(owner_role="CONSULTANT",fallback_role="CONSULTANT")
        row=configured(client,change=change)
        with SessionLocal() as db:
            db.add(Workspace(id="consultant-primary",name="Consultant primary"));db.flush()
            user=User(tenant_id="consultant-primary",name="Authorized consultant",email="consultant@example.test",role="VIEWER");db.add(user);db.flush();identifier=user.id
            db.add(WorkspaceAccess(user_id=user.id,tenant_id="tenant-demo",role="MEMBER",active=True))
            db.add(Membership(tenant_id="tenant-demo",organization_id="org-udaan",name=user.name,email=user.email,role="CONSULTANT",status="ACTIVE"));db.commit()
        item=generate(client,row["code"]);assert item["owner_name"]=="Authorized consultant"
        detail=client.get(f"/api/v1/compliances/{item['id']}/runtime-detail").json();assert detail["owner"]["owner_id"]==identifier and not detail["owner_required"]
        candidates=client.get(f"/api/v1/compliances/{item['id']}/owner-candidates").json();admin_id=next(c["id"] for c in candidates if c["name"]=="Master Admin")
        response=client.post(f"/api/v1/compliances/{item['id']}/owner",json={"owner_id":admin_id,"expected_owner_id":identifier,"reason":"Primary administrator takes ownership"});assert response.status_code==200,response.text
        saved=client.get(f"/api/v1/compliances/{item['id']}/runtime-detail").json();assert saved["owner"]["assigned_by"]==admin_id
        assert client.post(f"/api/v1/compliances/{item['id']}/owner",json={"owner_id":identifier,"expected_owner_id":identifier,"reason":"Stale edit"}).status_code==409
        with SessionLocal() as db:
            db.scalar(select(WorkspaceAccess).where(WorkspaceAccess.user_id==identifier)).active=False;db.commit()
        assert client.post(f"/api/v1/compliances/{item['id']}/owner",json={"owner_id":identifier,"expected_owner_id":admin_id,"reason":"Invalid access"}).status_code==422
        switch_role("MEMBER")
        assert client.post(f"/api/v1/compliances/{item['id']}/owner",json={"owner_id":admin_id,"reason":"Unauthorized"}).status_code==403

def test_effective_workspace_role_prevents_original_admin_privilege(monkeypatch):
    with platform_client(monkeypatch):
        with SessionLocal() as db:
            user=db.scalar(select(User).where(User.email=="master@example.test"));db.add(Workspace(id="secondary",name="Secondary"));db.flush()
            db.add(WorkspaceAccess(user_id=user.id,tenant_id="secondary",role="MEMBER",active=True));db.commit()
            db.info["actor_id"]=user.id
            assert "TENANT_ADMIN" not in actor_roles(db,"secondary","unassigned")
            assert "TENANT_ADMIN" in actor_roles(db,"tenant-demo","org-udaan")

def test_owner_required_never_resolves_unrelated_or_viewer(monkeypatch):
    with platform_client(monkeypatch) as client:
        row=configured(client,change=lambda c:c["responsibility"].update(owner_role="AUDITOR",fallback_role="AUDITOR"))
        with SessionLocal() as db:
            user=db.scalar(select(User).where(User.email=="master@example.test"));db.add(Membership(tenant_id="other-tenant",organization_id="org-udaan",name=user.name,email=user.email,role="AUDITOR",status="ACTIVE"));db.commit()
        item=generate(client,row["code"]);assert item["owner_name"]=="Owner Required"
        assert client.get(f"/api/v1/compliances/{item['id']}/runtime-detail").json()["owner_required"]

def test_material_decisions_overrides_clear_and_instance_history_preserved(monkeypatch):
    with platform_client(monkeypatch) as client:
        def change(c):c["applicability"]={"match_all":False,"groups":[{"id":"fcra","conditions":[{"id":"status","field":"organization.fcra.status","operator":"EQUALS","value":"ACTIVE"}]}]}
        row=configured(client,change=change)
        path="/api/v1/organizations/org-udaan"
        first=client.post(path+"/evaluate-compliance").json()["results"][0];assert first["effective_result"]=="REQUIRES_REVIEW"
        assert len(client.get(path+"/applicability-history").json())==1
        client.post(path+"/evaluate-compliance");assert len(client.get(path+"/applicability-history").json())==1
        assert client.patch(path+"/profile",json={"expected_revision":0,"registrations":[{"kind":"FCRA","status":"ACTIVE"}]}).status_code==200
        second=client.post(path+"/evaluate-compliance").json()["results"][0];assert second["comparison"]=="NEWLY_APPLICABLE"
        item=generate(client,row["code"]);detail_path=f"/api/v1/compliances/{item['id']}/runtime-detail"
        assert client.patch(path+"/profile",json={"expected_revision":1,"registrations":[{"kind":"FCRA","status":"NOT_REGISTERED"}]}).status_code==200
        assert client.get(detail_path).json()["requires_reevaluation"]
        assert client.post(path+"/evaluate-compliance").json()["results"][0]["comparison"]=="NO_LONGER_APPLICABLE"
        override_path=path+f"/templates/{row['id']}/override"
        forced=client.post(override_path,json={"decision":"FORCE_APPLICABLE","reason":"Approved documented applicability assessment"});assert forced.status_code==200,forced.text
        effective=forced.json()["results"][0];assert effective["rule_result"]=="NOT_APPLICABLE" and effective["effective_result"]=="APPLICABLE"
        assert client.post(override_path,json={"decision":"CLEAR_OVERRIDE","reason":"Return to configured rule"}).status_code==409
        cleared=client.post(override_path,json={"decision":"CLEAR_OVERRIDE","reason":"Return to configured rule","expected_override_id":forced.json()["override_id"]});assert cleared.status_code==200
        assert cleared.json()["results"][0]["effective_result"]=="NOT_APPLICABLE"
        saved=client.get(detail_path).json();assert saved["compliance"]["status"]=="NOT_STARTED" and len(saved["tasks"])==1
        assert saved["snapshot"]["configuration"]["applicability"]["groups"][0]["conditions"][0]["value"]=="ACTIVE"
        with SessionLocal() as db:
            snapshots=db.scalars(select(ApplicabilityDecision)).all();assert len(snapshots)==5
            assert all("ABCDE" not in s.facts_snapshot for s in snapshots)
        switch_role("MEMBER")
        assert client.post(override_path,json={"decision":"FORCE_NOT_APPLICABLE","reason":"Unauthorized attempt","expected_override_id":cleared.json()["override_id"]}).status_code==403

def test_template_scoped_event_capture_date_source_and_duplicate_protection(monkeypatch):
    with platform_client(monkeypatch) as client:
        def change(c):c["recurrence"]["frequency"]="EVENT_BASED";c["deadline"].update(strategy="EVENT_DATE_PLUS_DAYS",fixed_date=None,event_key="organization.review",offset_days=12)
        row=configured(client,change=change);path="/api/v1/organizations/org-udaan/events"
        payload={"template_id":row["id"],"event_key":"organization.review","event_date":"2026-09-18","source":"Organization board record #17"}
        assert client.post(path,json={**payload,"event_key":"guessed.event"}).status_code==422
        response=client.post(path,json=payload);assert response.status_code==201,response.text;event=response.json()
        assert client.post(path,json=payload).json()["id"]==event["id"]
        result=client.post(path+f"/{event['id']}/generate").json();assert len(result["generated_ids"])==1
        assert client.get(f"/api/v1/compliances/{result['generated_ids'][0]}/runtime-detail").json()["compliance"]["statutory_deadline"]=="2026-09-30"
        assert client.post(path+f"/{event['id']}/generate").json()["generated_ids"]==[]
        assert client.post("/api/v1/organizations/org-foreign/events",json=payload).status_code==404
        assert client.get(path).json()[0]["source"]==payload["source"]

def test_certificate_structured_expiry_and_real_file_conflict_requires_review(monkeypatch):
    with platform_client(monkeypatch) as client:
        def change(c):c["deadline"].update(strategy="CERTIFICATE_EXPIRY_MINUS_DAYS",fixed_date=None,document_type="FCRA",offset_days=30)
        row=configured(client,change=change)
        assert not any(c["code"]==row["code"] for c in client.post("/api/v1/organizations/org-udaan/generate-plan").json())
        assert client.patch("/api/v1/organizations/org-udaan/profile",json={"expected_revision":0,"registrations":[{"kind":"FCRA","status":"ACTIVE","expiry_date":"2027-01-31"}]}).status_code==200
        item=generate(client,row["code"]);assert item["statutory_deadline"]=="2027-01-01"
        upload=upload_original(client,category="FCRA",expiry_at="2028-01-31");assert upload.status_code==201
        assert client.patch("/api/v1/organizations/org-udaan/profile",json={"expected_revision":1,"registrations":[{"kind":"FCRA","status":"ACTIVE","expiry_date":"2027-01-31","document_id":upload.json()["document"]["id"]}]}).status_code==200
        response=client.post(f"/api/v1/compliances/{item['id']}/next-cycle");assert response.status_code==422 and "disagree" in response.text

def test_next_cycle_period_uses_period_end_and_replays_without_skipping(monkeypatch):
    with platform_client(monkeypatch) as client:
        def change(c):c["recurrence"].update(frequency="MONTHLY",anchor_date="2026-01-01");c["deadline"].update(strategy="PERIOD_END_PLUS_DAYS",fixed_date=None,offset_days=90)
        row=configured(client,change=change);source=generate(client,row["code"])
        path=f"/api/v1/compliances/{source['id']}/next-cycle";response=client.post(path);assert response.status_code==200,response.text
        target=response.json()["compliance"];assert target["period"].startswith("2026-10-01:2026-10-31")
        replay=client.post(path).json();assert replay["replayed"] and replay["compliance"]["id"]==target["id"]
        assert client.get(f"/api/v1/compliances/{source['id']}/runtime-detail").json()["compliance"]["status"]=="NOT_STARTED"

def test_complete_frozen_workflow_real_evidence_tasks_filing_history(monkeypatch):
    with platform_client(monkeypatch) as client:
        states=["NOT_STARTED","IN_PROGRESS","UNDER_REVIEW","CHANGES_REQUESTED","READY_TO_FILE","FILED","COMPLETED"]
        def change(c):
            c["workflow"]={"stages":[{"id":str(i),"state":s} for i,s in enumerate(states)],"transitions":[{"from_state":a,"to_state":b,"allowed_roles":["TENANT_ADMIN"],"required_evidence":b in {"UNDER_REVIEW","FILED","COMPLETED"}} for a,b in zip(states,states[1:])]+[{"from_state":"CHANGES_REQUESTED","to_state":"IN_PROGRESS","allowed_roles":["TENANT_ADMIN"]}]}
        row=configured(client,change=change);item=generate(client,row["code"]);path=f"/api/v1/compliances/{item['id']}/transitions"
        assert client.post(path,json={"target_status":"IN_PROGRESS"}).status_code==200
        missing=client.post(path,json={"target_status":"UNDER_REVIEW","proof_document_id":"doc-tax"});assert missing.status_code==422 and "Sample evidence" in missing.text
        proof=upload_original(client,expiry_at="2030-01-01");assert proof.status_code==201;doc=proof.json()["document"];version=proof.json()["file"]["version_id"]
        for status in states[2:-1]:
            response=client.post(path,json={"target_status":status,"proof_document_id":doc["id"],"reason":"Documented review requires correction","submission_reference":"SAMPLE-FILING-17"});assert response.status_code==200,response.text
        assert client.post(path,json={"target_status":"COMPLETED","proof_document_id":doc["id"]}).status_code==422
        task=client.get(f"/api/v1/compliances/{item['id']}/runtime-detail").json()["tasks"][0]
        assert client.patch(f"/api/v1/tasks/{task['id']}",json={"status":"DONE"}).status_code==200
        assert client.post(path,json={"target_status":"COMPLETED","proof_document_id":doc["id"]}).status_code==200
        saved=client.get(f"/api/v1/compliances/{item['id']}/runtime-detail").json();assert len([a for a in saved["audit"] if a["action"]=="STATUS_CHANGED"])==6
        assert saved["submissions"][0]["reference"]=="SAMPLE-FILING-17"
        assert any(l["version_id"]==version and l["submission_id"] for l in saved["evidence_links"])

def test_concurrent_due_and_next_cycle_are_idempotent_in_disposable_sqlite(monkeypatch,tmp_path):
    with platform_client(monkeypatch) as client:
        row=configured(client);database=tmp_path/"runtime-concurrency.db"
        with engine.connect() as source, sqlite3.connect(database) as target:
            source.connection.driver_connection.backup(target)
        scoped=create_engine(f"sqlite:///{database}",connect_args={"timeout":30})
        barrier=Barrier(2)
        def due():
            with Session(scoped) as db:
                org=db.get(Organization,"org-udaan");barrier.wait()
                result=generate_due_instances(db,"tenant-demo",org,as_of=date(2026,9,18));db.commit();return [i.id for i in result[0]]
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:due(),range(2)))
        assert sum(len(r) for r in results)==1
        with Session(scoped) as db:
            assert db.scalar(select(func.count()).select_from(ComplianceSnapshot))==1
            source_id=db.scalar(select(ComplianceSnapshot.compliance_id))
        barrier=Barrier(2)
        def next_one():
            with Session(scoped) as db:
                org=db.get(Organization,"org-udaan");source=db.get(Compliance,source_id);barrier.wait()
                target,replayed=generate_next_cycle(db,"tenant-demo",org,source);db.commit();return target.id,replayed
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:next_one(),range(2)))
        assert results[0][0]==results[1][0] and sum(r[1] for r in results)==1
        scoped.dispose()

def test_runtime_migration_is_additive_and_cross_tenant_reads_are_denied(monkeypatch):
    with platform_client(monkeypatch) as client:
        row=configured(client);item=generate(client,row["code"])
        apply(engine);apply(engine)
        with SessionLocal() as db:
            assert db.get(Compliance,item["id"])
            user=User(tenant_id="other-tenant",name="Other tenant",email="other-runtime@example.test",role="ADMIN");db.add(user);db.flush()
            db.add(AuthSession(token_hash=digest("other-runtime"),user_id=user.id,expires_at=datetime.now(timezone.utc)+timedelta(hours=1)));db.commit()
        client.cookies.set("setu_session","other-runtime")
        for suffix in ["runtime-detail","owner-candidates"]:assert client.get(f"/api/v1/compliances/{item['id']}/{suffix}").status_code==404
        for suffix in ["events","applicability-history"]:assert client.get(f"/api/v1/organizations/org-udaan/{suffix}").status_code==404
        assert client.post(f"/api/v1/compliances/{item['id']}/next-cycle").status_code==404
