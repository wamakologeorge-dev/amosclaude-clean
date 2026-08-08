import os
from dataclasses import dataclass
from fastapi import Header, HTTPException


@dataclass(frozen=True)
class QueryIdentity:
    tenant_id: str
    is_admin: bool = False


def _key_map() -> dict[str, str]:
    result = {}
    for pair in os.getenv("AMOSCLAUD_LOGGING_API_KEYS", "local-dev-key:local").split(","):
        key, sep, tenant = pair.strip().partition(":")
        if sep and key and tenant:
            result[key] = tenant
    return result


async def require_query_identity(
    authorization: str | None = Header(default=None),
    x_amosclaud_key: str | None = Header(default=None),
) -> QueryIdentity:
    key = (x_amosclaud_key or "").strip()
    if not key and authorization:
        scheme, sep, value = authorization.partition(" ")
        key = value.strip() if sep and scheme.lower() == "bearer" else ""
    admin = os.getenv("AMOSCLAUD_LOGGING_ADMIN_API_KEY", "")
    if admin and key == admin:
        return QueryIdentity("*", True)
    tenant = _key_map().get(key)
    if not tenant:
        raise HTTPException(401, "Invalid Amosclaud logging key")
    return QueryIdentity(tenant)
