"""Central server-side organization authorization.

Login membership grants workspace access. OrganizationAccess grants access to a
specific organization. Responsibility records in Membership never grant login
or organization access.
"""
from fastapi import HTTPException
from sqlalchemy import select

from .auth_models import WorkspaceAccess
from .models import User
from .phase8_models import OrganizationAccess

ACCESS_ROLES = {"VIEWER", "CONTRIBUTOR", "MANAGER"}
WRITE_ROLES = {"CONTRIBUTOR", "MANAGER"}


def workspace_role(db, tenant_id: str, user_id: str) -> str | None:
    user = db.get(User, user_id)
    if not user or user.status != "ACTIVE":
        return None
    if user.tenant_id == tenant_id:
        return user.role
    return db.scalar(select(WorkspaceAccess.role).where(
        WorkspaceAccess.user_id == user_id,
        WorkspaceAccess.tenant_id == tenant_id,
        WorkspaceAccess.active.is_(True),
    ))


def accessible_organization_ids(db, tenant_id: str, user_id: str | None = None) -> set[str] | None:
    """Return None for unrestricted workspace admins/system workers, else IDs."""
    user_id = user_id if user_id is not None else db.info.get("actor_id")
    if not user_id:  # trusted worker/service context; handlers still predicate tenant_id
        return None
    role = workspace_role(db, tenant_id, user_id)
    if role == "ADMIN":
        return None
    if not role:
        return set()
    # Existing workspaces retain their historical workspace-wide access until
    # an administrator creates the first explicit organization grant.
    if not db.scalar(select(OrganizationAccess.id).where(
        OrganizationAccess.tenant_id == tenant_id,
    ).limit(1)):
        return None
    return set(db.scalars(select(OrganizationAccess.organization_id).where(
        OrganizationAccess.tenant_id == tenant_id,
        OrganizationAccess.user_id == user_id,
        OrganizationAccess.status == "ACTIVE",
    )).all())


def organization_access_role(db, tenant_id: str, organization_id: str, user_id: str | None = None) -> str | None:
    user_id = user_id if user_id is not None else db.info.get("actor_id")
    if not user_id:
        return "MANAGER"
    role = workspace_role(db, tenant_id, user_id)
    if role == "ADMIN":
        return "MANAGER"
    if not role:
        return None
    if not db.scalar(select(OrganizationAccess.id).where(
        OrganizationAccess.tenant_id == tenant_id,
    ).limit(1)):
        return "VIEWER" if role == "VIEWER" else "CONTRIBUTOR"
    return db.scalar(select(OrganizationAccess.access_role).where(
        OrganizationAccess.tenant_id == tenant_id,
        OrganizationAccess.organization_id == organization_id,
        OrganizationAccess.user_id == user_id,
        OrganizationAccess.status == "ACTIVE",
    ))


def require_organization_access(db, tenant_id: str, organization_id: str, *, write: bool = False,
                                user_id: str | None = None) -> str:
    role = organization_access_role(db, tenant_id, organization_id, user_id)
    if not role or write and role not in WRITE_ROLES:
        raise HTTPException(403, "ORGANIZATION_ACCESS_DENIED")
    return role


def can_access_organization(db, tenant_id: str, organization_id: str, user_id: str | None = None) -> bool:
    return organization_access_role(db, tenant_id, organization_id, user_id) is not None
