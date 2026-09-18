"""Named permissions mapped onto the existing authenticated account roles."""
COMPLIANCE_MASTER_PERMISSIONS = {
    "compliance_master." + action
    for action in ("view", "create", "edit", "review", "publish", "archive", "version", "clone")
}
INTEGRATION_PERMISSIONS = {
    "integrations.platform.view", "integrations.platform.manage", "integrations.tenant.view", "integrations.tenant.manage",
    "integrations.credentials.rotate", "integrations.webhooks.manage", "integrations.logs.view", "integrations.health.view",
    "api_keys.view", "api_keys.create", "api_keys.revoke", "oauth_clients.manage",
}
ROLE_PERMISSIONS = {"ADMIN": {"white_label.manage", *COMPLIANCE_MASTER_PERMISSIONS, *INTEGRATION_PERMISSIONS}, "MEMBER": set(), "VIEWER": set()}


def has_permission(user, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(user.role, set())
