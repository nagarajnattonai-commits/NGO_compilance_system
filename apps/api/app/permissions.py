"""Named permissions mapped onto the existing authenticated account roles."""
COMPLIANCE_MASTER_PERMISSIONS = {
    "compliance_master." + action
    for action in ("view", "create", "edit", "review", "publish", "archive", "version", "clone")
}
ROLE_PERMISSIONS = {"ADMIN": {"white_label.manage", *COMPLIANCE_MASTER_PERMISSIONS}, "MEMBER": set(), "VIEWER": set()}


def has_permission(user, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(user.role, set())
