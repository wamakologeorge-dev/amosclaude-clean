from dataclasses import dataclass
from fastapi import Header, HTTPException, status

from app.settings import get_settings


@dataclass(frozen=True)
class AuthContext:
    tenant_id: str
    is_admin: bool = False


def _extract_key(authorization: str | None, x_amosclaud_key: str | None) -> str:
    if x_amosclaud_key:
        return x_amosclaud_key.strip()
    if authorization:
        scheme, separator, value = authorization.partition(" ")
        if separator and scheme.lower() == "bearer":
            return value.strip()
    return ""


async def require_log_key(
    authorization: str | None = Header(default=None),
    x_amosclaud_key: str | None = Header(default=None),
) -> AuthContext:
    settings = get_settings()
    key = _extract_key(authorization, x_amosclaud_key)
    if settings.admin_api_key and key == settings.admin_api_key:
        return AuthContext(tenant_id="*", is_admin=True)
    tenant = settings.tenant_keys().get(key)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Amosclaud logging key",
        )
    return AuthContext(tenant_id=tenant)


def authenticate_websocket_key(key: str) -> AuthContext | None:
    settings = get_settings()
    if settings.admin_api_key and key == settings.admin_api_key:
        return AuthContext(tenant_id="*", is_admin=True)
    tenant = settings.tenant_keys().get(key)
    return AuthContext(tenant_id=tenant) if tenant else None
