"""Native repository permission policy."""

ROLE_PERMISSIONS = {
    "owner": {"read", "write", "admin", "approve"},
    "developer": {"read", "write"},
    "viewer": {"read"},
}


def allows(role: str | None, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role or "viewer", {"read"})
