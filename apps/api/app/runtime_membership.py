"""Resolve accounts using effective access in the requested workspace."""
from sqlalchemy import select, or_
from .auth_models import WorkspaceAccess
from .models import User, Membership

def workspace_members(db, tenant_id):
    members = {u.id: (u, role) for u, role in db.execute(select(User, User.role).where(User.tenant_id == tenant_id, User.status == "ACTIVE"))}
    for user, role in db.execute(select(User, WorkspaceAccess.role).join(WorkspaceAccess, WorkspaceAccess.user_id == User.id).where(WorkspaceAccess.tenant_id == tenant_id, WorkspaceAccess.active.is_(True), User.status == "ACTIVE")):
        members.setdefault(user.id, (user, role))
    return list(members.values())

def resolve_role(db, organization, role):
    candidates = {u.email.casefold(): u for u, access in workspace_members(db, organization.tenant_id) if access != "VIEWER"}
    assignments = db.scalars(select(Membership).where(Membership.tenant_id == organization.tenant_id, Membership.role == role, Membership.status == "ACTIVE", or_(Membership.organization_id == organization.id, Membership.organization_id.is_(None))).order_by(Membership.organization_id.desc(), Membership.id)).all()
    for assignment in assignments:
        if assignment.email.casefold() in candidates:
            return candidates[assignment.email.casefold()]
    if role == "TENANT_ADMIN":
        return next((u for u, access in sorted(workspace_members(db, organization.tenant_id), key=lambda pair: pair[0].id) if access == "ADMIN"), None)
    return None

def actor_roles(db, tenant_id, organization_id):
    actor = next(((u, role) for u, role in workspace_members(db, tenant_id) if u.id == db.info.get("actor_id")), None)
    if not actor or actor[1] == "VIEWER":
        return set()
    user, role = actor
    roles = {"TENANT_ADMIN"} if role == "ADMIN" else set()
    roles.update(db.scalars(select(Membership.role).where(Membership.tenant_id == tenant_id, Membership.email == user.email, Membership.status == "ACTIVE", or_(Membership.organization_id == organization_id, Membership.organization_id.is_(None)))).all())
    return roles
