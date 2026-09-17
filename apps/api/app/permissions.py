"""Named permissions mapped onto the existing authenticated account roles."""
ROLE_PERMISSIONS = {"ADMIN": {"white_label.manage"}, "MEMBER": set(), "VIEWER": set()}


def has_permission(user, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(user.role, set())
