"""Persistent onboarding orchestrates the existing profile, rules and generation services."""
import json
from datetime import date
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from .organization_profile import DB, Tenant, Strict, ProfileInput, completeness, owned_org, profile_data, save_profile
from .auth import CurrentUser, aware
from .models import AuditEvent, Organization, utcnow
from .onboarding_models import OrganizationOnboarding
from .compliance_engine import evaluate_rules, generate_master_plan, organization_facts, published_templates
from .compliance_template_schema import TemplateConfiguration

STEPS=("welcome","basics","registration","compliance","financial","documents","team","review","evaluation","complete")
Step=Literal["welcome","basics","registration","compliance","financial","documents","team","review","evaluation","complete"]
router=APIRouter(prefix="/api/v1",tags=["Onboarding"])
class ProgressInput(Strict):
    expected_revision:int=Field(ge=0)
    current_step:Step
    complete_step:bool=False
    profile:ProfileInput|None=None
class RevisionInput(Strict):
    expected_revision:int=Field(ge=0)

def admin(actor):
    if actor.role!="ADMIN":raise HTTPException(403,"Administrator access is required")
def state_data(row):
    return {"organization_id":row.organization_id,"tenant_id":row.tenant_id,"current_step":row.current_step,"completed_steps":json.loads(row.completed_steps),"status":row.status,"revision":row.revision,"started_at":aware(row.started_at),"updated_at":aware(row.updated_at),"completed_at":aware(row.completed_at) if row.completed_at else None}
def owned_state(db,tenant,id):
    row=db.scalar(select(OrganizationOnboarding).where(OrganizationOnboarding.organization_id==id,OrganizationOnboarding.tenant_id==tenant))
    if not row:raise HTTPException(404,"Onboarding has not been started for this organization")
    return row
def evaluate(db,org):
    return [{"id":master.id,"code":master.code,"name":TemplateConfiguration.model_validate_json(version.configuration).name,"version":version.version,**evaluate_rules(TemplateConfiguration.model_validate_json(version.configuration),org,organization_facts(db,org))} for master,version in published_templates(db)]

@router.get("/onboarding")
def list_progress(db:DB,tenant:Tenant):
    return [state_data(row) for row in db.scalars(select(OrganizationOnboarding).where(OrganizationOnboarding.tenant_id==tenant).order_by(OrganizationOnboarding.updated_at.desc())).all()]
@router.post("/organizations/{organization_id}/onboarding/start")
def start(organization_id:str,db:DB,tenant:Tenant,actor:CurrentUser):
    admin(actor);owned_org(db,tenant,organization_id)
    row=db.get(OrganizationOnboarding,organization_id)
    if row and row.tenant_id!=tenant:raise HTTPException(404,"Onboarding not found")
    if not row:
        row=OrganizationOnboarding(organization_id=organization_id,tenant_id=tenant,current_step="basics",completed_steps='["welcome"]',updated_by=actor.id)
        db.add(row)
        try:db.flush()
        except IntegrityError:
            db.rollback();row=owned_state(db,tenant,organization_id);return state_data(row)
        db.add(AuditEvent(tenant_id=tenant,actor_name=actor.name,action="ONBOARDING_STARTED",entity_type="Organization",entity_id=organization_id,summary="Started organization onboarding"));db.commit()
    return state_data(row)
@router.get("/organizations/{organization_id}/onboarding")
def get_progress(organization_id:str,db:DB,tenant:Tenant):
    org=owned_org(db,tenant,organization_id)
    return {"state":state_data(owned_state(db,tenant,organization_id)),"profile":{**profile_data(db,org),"completeness":completeness(db,org)}}
@router.patch("/organizations/{organization_id}/onboarding")
def update_progress(organization_id:str,payload:ProgressInput,db:DB,tenant:Tenant,actor:CurrentUser):
    admin(actor);org=owned_org(db,tenant,organization_id);row=owned_state(db,tenant,organization_id)
    if row.status=="COMPLETED":raise HTTPException(409,"Onboarding is already complete; edit the organization profile instead")
    if payload.current_step=="complete":raise HTTPException(422,"Use the evaluated completion action")
    if STEPS.index(payload.current_step)>STEPS.index(row.current_step)+1:raise HTTPException(422,"Save the preceding onboarding steps first")
    completed=json.loads(row.completed_steps)
    if payload.complete_step and row.current_step not in completed:completed.append(row.current_step)
    claimed=db.execute(update(OrganizationOnboarding).where(OrganizationOnboarding.organization_id==org.id,OrganizationOnboarding.tenant_id==tenant,OrganizationOnboarding.revision==payload.expected_revision).values(revision=OrganizationOnboarding.revision+1,current_step=payload.current_step,completed_steps=json.dumps(completed),updated_by=actor.id,updated_at=utcnow()).execution_options(synchronize_session=False))
    if claimed.rowcount!=1:db.rollback();raise HTTPException(409,"Onboarding changed; reload before saving")
    if payload.profile:save_profile(org.id,payload.profile,db,tenant,actor,commit=False)
    if payload.complete_step and row.current_step=="basics" and completeness(db,org)["missing_required_facts"]:
        raise HTTPException(422,"Required organization setup facts are missing")
    db.add(AuditEvent(tenant_id=tenant,actor_name=actor.name,action="ONBOARDING_PROGRESS_SAVED",entity_type="Organization",entity_id=org.id,summary="Saved onboarding step "+row.current_step))
    db.commit();db.expire(row)
    return {"state":state_data(row),"profile":{**profile_data(db,org),"completeness":completeness(db,org)}}
@router.post("/organizations/{organization_id}/onboarding/evaluate")
def evaluation(organization_id:str,db:DB,tenant:Tenant,actor:CurrentUser):
    admin(actor);org=owned_org(db,tenant,organization_id);owned_state(db,tenant,organization_id)
    return {"results":evaluate(db,org)}
@router.post("/organizations/{organization_id}/onboarding/complete")
def complete(organization_id:str,payload:RevisionInput,db:DB,tenant:Tenant,actor:CurrentUser):
    admin(actor);org=owned_org(db,tenant,organization_id);row=owned_state(db,tenant,organization_id)
    if row.status=="COMPLETED":return {"state":state_data(row),"generated_ids":[],"already_completed":True}
    if row.current_step!="evaluation" or org.status!="ACTIVE" or completeness(db,org)["missing_required_facts"]:
        raise HTTPException(422,"Save and review an active organization before completion")
    results=evaluate(db,org)
    if any(r.get("requires_review") for r in results):raise HTTPException(409,"ONBOARDING_REQUIRES_REVIEW")
    claimed=db.execute(update(OrganizationOnboarding).where(OrganizationOnboarding.organization_id==org.id,OrganizationOnboarding.tenant_id==tenant,OrganizationOnboarding.revision==payload.expected_revision,OrganizationOnboarding.status=="IN_PROGRESS").values(revision=OrganizationOnboarding.revision+1,current_step="complete",status="COMPLETED",completed_steps=json.dumps(list(STEPS)),completed_at=utcnow(),updated_at=utcnow(),updated_by=actor.id).execution_options(synchronize_session=False))
    if claimed.rowcount!=1:db.rollback();raise HTTPException(409,"Onboarding changed; reload before completion")
    generated,review=generate_master_plan(db,tenant,org,as_of=date.today())
    if review:db.rollback();raise HTTPException(409,"ONBOARDING_DEADLINE_FACTS_REQUIRED")
    db.add(AuditEvent(tenant_id=tenant,actor_name=actor.name,action="ONBOARDING_COMPLETED",entity_type="Organization",entity_id=org.id,summary=f"Completed onboarding; generated {len(generated)} compliance instances"))
    db.commit();db.expire(row)
    return {"state":state_data(row),"generated_ids":[c.id for c in generated],"evaluated_count":len(results)}
