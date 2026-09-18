from sqlalchemy import select
from app.database import SessionLocal
from app.models import AuditEvent, Compliance, ComplianceSnapshot, User
from app.onboarding import STEPS
from app.onboarding_models import OrganizationOnboarding
from app.auth import digest
from app.auth_models import SessionContext
from test_compliance_master import create, platform_client, publish

ROOT="/api/v1/organizations/org-udaan/onboarding"
def advance(client,state):
    for step in STEPS[STEPS.index(state["current_step"])+1:-1]:
        response=client.patch(ROOT,json={"expected_revision":state["revision"],"current_step":step,"complete_step":True})
        assert response.status_code==200,response.text
        state=response.json()["state"]
    return state

def test_progress_resume_atomic_profile_save_revision_and_completion(monkeypatch):
    with platform_client(monkeypatch) as client:
        publish(client,create(client))
        state=client.post(ROOT+"/start").json();assert state["current_step"]=="basics"
        assert client.post(ROOT+"/start").json()["revision"]==0
        response=client.patch(ROOT,json={"expected_revision":0,"current_step":"registration","complete_step":True,"profile":{"expected_revision":0,"details":{"notes":"Saved for later","contact_email":"onboard@example.test"}}})
        assert response.status_code==200,response.text
        state=response.json()["state"]
        assert client.get(ROOT).json()["profile"]["details"]["notes"]=="Saved for later"
        assert client.get("/api/v1/onboarding").json()[0]["current_step"]=="registration"
        assert client.patch(ROOT,json={"expected_revision":0,"current_step":"registration","profile":{"expected_revision":1,"details":{"notes":"Do not persist"}}}).status_code==409
        assert client.get(ROOT).json()["profile"]["details"]["notes"]=="Saved for later"
        assert client.patch(ROOT,json={"expected_revision":1,"current_step":"compliance","profile":{"expected_revision":0,"details":{"notes":"Conflict rolls back state"}}}).status_code==409
        assert client.get(ROOT).json()["state"]["revision"]==1
        state=advance(client,state)
        assert client.post(ROOT+"/evaluate").json()["results"][0]["applicable"] is True
        result=client.post(ROOT+"/complete",json={"expected_revision":state["revision"]})
        assert result.status_code==200,result.text
        assert result.json()["state"]["completed_at"] and len(result.json()["generated_ids"])==1
        assert client.post(ROOT+"/complete",json={"expected_revision":state["revision"]}).json()["already_completed"]
        with SessionLocal() as db:
            assert len(db.scalars(select(ComplianceSnapshot)).all())==1
            assert db.scalar(select(AuditEvent).where(AuditEvent.action=="ONBOARDING_COMPLETED"))

def test_missing_applicability_and_deadline_facts_block_completion_without_partial_instances(monkeypatch):
    with platform_client(monkeypatch) as client:
        row=create(client);cfg=row["configuration"];cfg["applicability"]={"groups":[{"id":"g","conditions":[{"id":"c","field":"organization.12ab.status","operator":"EQUALS","value":"ACTIVE"}]}]}
        row=client.patch(f"/api/v1/admin/compliance-templates/{row['id']}",json={"expected_revision":0,"configuration":cfg,"change_summary":"Require declared registration"}).json();publish(client,row)
        state=advance(client,client.post(ROOT+"/start").json())
        assert client.post(ROOT+"/evaluate").json()["results"][0]["requires_review"]
        assert client.post(ROOT+"/complete",json={"expected_revision":state["revision"]}).status_code==409
        assert client.get(ROOT).json()["state"]["status"]=="IN_PROGRESS"
        with SessionLocal() as db:assert len(db.scalars(select(ComplianceSnapshot)).all())==0

def test_onboarding_cannot_jump_to_complete_or_write_as_viewer(monkeypatch):
    with platform_client(monkeypatch) as client:
        client.post(ROOT+"/start")
        assert client.patch(ROOT,json={"expected_revision":0,"current_step":"complete"}).status_code==422
        assert client.patch(ROOT,json={"expected_revision":0,"current_step":"evaluation"}).status_code==422
        assert client.get("/api/v1/organizations/org-other/onboarding").status_code==404
        with SessionLocal() as db:
            user=db.scalar(select(User).where(User.email=="master@example.test"));user.role="VIEWER";db.get(SessionContext,digest("master-test")).audience="user";db.commit()
        assert client.get(ROOT).status_code==200
        assert client.post(ROOT+"/start").status_code==403
        assert client.patch(ROOT,json={"expected_revision":0,"current_step":"registration"}).status_code==403

def test_onboarding_migration_preserves_existing_rows(monkeypatch):
    from app.migrate_onboarding import apply
    from app.database import engine
    with platform_client(monkeypatch) as client:
        state=client.post(ROOT+"/start").json()
        assert apply()==apply()
        assert client.get(ROOT).json()["state"]["started_at"]==state["started_at"]


def test_missing_event_deadline_rolls_back_generation_and_completion(monkeypatch):
    with platform_client(monkeypatch) as client:
        first=publish(client,create(client,"READY-SAMPLE"))
        row=client.post("/api/v1/admin/compliance-templates",json={"code":"EVENT-SAMPLE","configuration":first["configuration"]}).json();cfg=row["configuration"]
        cfg["recurrence"]["frequency"]="EVENT_BASED";cfg["deadline"]["strategy"]="EVENT_DATE_PLUS_DAYS"
        response=client.patch(f"/api/v1/admin/compliance-templates/{row['id']}",json={"expected_revision":0,"configuration":cfg,"change_summary":"Require supplied event date"})
        assert response.status_code==200,response.text
        publish(client,response.json());state=advance(client,client.post(ROOT+"/start").json())
        response=client.post(ROOT+"/complete",json={"expected_revision":state["revision"]})
        assert response.status_code==409 and response.json()["detail"]=="ONBOARDING_DEADLINE_FACTS_REQUIRED"
        assert client.get(ROOT).json()["state"]["status"]=="IN_PROGRESS"
        with SessionLocal() as db:assert db.scalars(select(ComplianceSnapshot)).all()==[]
