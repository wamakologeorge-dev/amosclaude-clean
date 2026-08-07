"""OAuth 2.1 routes for the Amosclaud account MCP connector."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes import auth

from .oauth_config import (
    ADMIN_SCOPE,
    ALL_SCOPES,
    BASE_SCOPES,
    CONSENT_SECONDS,
    MCP_PATH,
    OAUTH_PATH,
    authorization_server_metadata_path,
    connector_resource_url,
    now,
    oauth_issuer_url,
    protected_resource_metadata_path,
    redirect_with_params,
    requested_scopes,
    token_hash,
    valid_pkce_value,
    valid_redirect_uri,
)
from .oauth_pages import consent_html, login_html
from .oauth_store import (
    AmosclaudConnectorTokenVerifier,
    cleanup,
    client,
    connect,
    create_authorization_code,
    issue_tokens,
    registered_redirect,
)

router = APIRouter(tags=["amosclaud-account-connector"])

# Compatibility exports used by tests and existing imports.
_valid_redirect_uri = valid_redirect_uri
_requested_scopes = requested_scopes


class ClientRegistrationRequest(BaseModel):
    redirect_uris: list[str] = Field(min_length=1, max_length=20)
    client_name: str = Field(default="MCP client", min_length=1, max_length=120)
    grant_types: list[str] = Field(
        default_factory=lambda: ["authorization_code", "refresh_token"]
    )
    response_types: list[str] = Field(default_factory=lambda: ["code"])
    token_endpoint_auth_method: str = "none"


def _oauth_error(error: str, description: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description},
        status_code=status_code,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _pkce_matches(verifier: str, expected_challenge: str) -> bool:
    try:
        cleaned = valid_pkce_value(verifier, name="code_verifier")
    except HTTPException:
        return False
    digest = hashlib.sha256(cleaned.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(challenge, expected_challenge)


@router.get(authorization_server_metadata_path())
def authorization_server_metadata() -> dict[str, Any]:
    issuer = oauth_issuer_url()
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "registration_endpoint": f"{issuer}/register",
        "revocation_endpoint": f"{issuer}/revoke",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": sorted(ALL_SCOPES),
        "resource_indicators_supported": True,
    }


@router.get(protected_resource_metadata_path())
def protected_resource_metadata() -> dict[str, Any]:
    return {
        "resource": connector_resource_url(),
        "authorization_servers": [oauth_issuer_url()],
        "scopes_supported": sorted(ALL_SCOPES),
        "bearer_methods_supported": ["header"],
    }


@router.post(f"{OAUTH_PATH}/register", status_code=201)
def register_client(body: ClientRegistrationRequest) -> dict[str, Any]:
    if body.token_endpoint_auth_method != "none":
        raise HTTPException(status_code=400, detail="Only public PKCE clients are supported")
    if set(body.grant_types) - {"authorization_code", "refresh_token"}:
        raise HTTPException(status_code=400, detail="Unsupported OAuth grant type")
    if set(body.response_types) != {"code"}:
        raise HTTPException(status_code=400, detail="Only response_type=code is supported")
    if "authorization_code" not in body.grant_types:
        raise HTTPException(status_code=400, detail="Authorization-code flow is required")

    redirect_uris = sorted({valid_redirect_uri(uri) for uri in body.redirect_uris})
    client_id = "amos_mcp_client_" + secrets.token_urlsafe(24)
    created_at = now()
    with connect() as db:
        cleanup(db)
        db.execute(
            """INSERT INTO connector_oauth_clients(
                 client_id,client_name,redirect_uris_json,created_at
               ) VALUES (?,?,?,?)""",
            (client_id, body.client_name.strip(), json.dumps(redirect_uris), created_at),
        )
        db.commit()
    return {
        "client_id": client_id,
        "client_id_issued_at": created_at,
        "client_name": body.client_name.strip(),
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }


@router.get(f"{OAUTH_PATH}/authorize", response_class=HTMLResponse)
def authorize(
    response_type: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
    state: str | None = None,
    scope: str | None = None,
    resource: str | None = None,
    amos_session: str | None = Cookie(default=None),
) -> HTMLResponse:
    if response_type != "code":
        raise HTTPException(status_code=400, detail="Only response_type=code is supported")
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="OAuth PKCE S256 is required")
    code_challenge = valid_pkce_value(code_challenge, name="code_challenge")
    if scope is not None and len(scope) > 1_000:
        raise HTTPException(status_code=400, detail="OAuth scope request is too large")
    requested_resource = (resource or connector_resource_url()).rstrip("/")
    if requested_resource != connector_resource_url().rstrip("/"):
        raise HTTPException(status_code=400, detail="OAuth resource does not match this connector")

    user = auth.get_user_from_session(amos_session)
    if not user:
        return HTMLResponse(login_html(), status_code=401)

    scopes = requested_scopes(scope, is_admin=bool(user["is_admin"]))
    request_id = secrets.token_urlsafe(32)
    current = now()
    with connect() as db:
        cleanup(db)
        client_row = client(db, client_id)
        redirect = registered_redirect(client_row, redirect_uri)
        db.execute(
            """INSERT INTO connector_oauth_consents(
                 request_id_hash,client_id,user_id,redirect_uri,state,scope,
                 code_challenge,resource,expires_at,created_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                token_hash(request_id),
                client_id,
                int(user["id"]),
                redirect,
                state,
                " ".join(scopes),
                code_challenge,
                connector_resource_url(),
                current + CONSENT_SECONDS,
                current,
            ),
        )
        db.commit()
        client_name = str(client_row["client_name"])
    return HTMLResponse(
        consent_html(
            user=user,
            request_id=request_id,
            client_name=client_name,
            scopes=scopes,
        )
    )


@router.post(f"{OAUTH_PATH}/authorize")
async def authorize_decision(
    request: Request,
    amos_session: str | None = Cookie(default=None),
) -> RedirectResponse:
    user = auth.get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to approve this connector")
    form = await request.form()
    request_id = str(form.get("request_id") or "")
    decision = str(form.get("decision") or "")
    if not request_id:
        raise HTTPException(status_code=400, detail="Missing OAuth consent request")

    with connect() as db:
        cleanup(db)
        consent = db.execute(
            "SELECT * FROM connector_oauth_consents WHERE request_id_hash=?",
            (token_hash(request_id),),
        ).fetchone()
        if not consent or int(consent["user_id"]) != int(user["id"]):
            raise HTTPException(status_code=400, detail="OAuth consent request is invalid or expired")
        db.execute(
            "DELETE FROM connector_oauth_consents WHERE request_id_hash=?",
            (token_hash(request_id),),
        )
        if decision != "approve":
            db.commit()
            return RedirectResponse(
                redirect_with_params(
                    str(consent["redirect_uri"]),
                    error="access_denied",
                    error_description="The Amosclaud user denied connector access",
                    state=consent["state"],
                ),
                status_code=302,
            )
        code = create_authorization_code(db, consent)
        db.commit()

    return RedirectResponse(
        redirect_with_params(
            str(consent["redirect_uri"]),
            code=code,
            state=consent["state"],
        ),
        status_code=302,
    )


@router.post(f"{OAUTH_PATH}/token")
async def exchange_token(request: Request) -> JSONResponse:
    form = await request.form()
    grant_type = str(form.get("grant_type") or "")
    client_id = str(form.get("client_id") or "")
    if not client_id:
        return _oauth_error("invalid_client", "client_id is required", 401)

    with connect() as db:
        cleanup(db)
        try:
            client(db, client_id)
        except HTTPException:
            return _oauth_error("invalid_client", "Unknown OAuth client", 401)

        if grant_type == "authorization_code":
            code = str(form.get("code") or "")
            redirect_uri = str(form.get("redirect_uri") or "")
            code_verifier = str(form.get("code_verifier") or "")
            row = db.execute(
                "SELECT * FROM connector_oauth_codes WHERE code_hash=? AND client_id=?",
                (token_hash(code), client_id),
            ).fetchone()
            if not row:
                return _oauth_error("invalid_grant", "Authorization code is invalid or expired")
            if redirect_uri != str(row["redirect_uri"]):
                return _oauth_error("invalid_grant", "redirect_uri does not match the authorization")
            if not code_verifier or not _pkce_matches(code_verifier, str(row["code_challenge"])):
                return _oauth_error("invalid_grant", "PKCE verification failed")
            db.execute(
                "DELETE FROM connector_oauth_codes WHERE code_hash=?",
                (token_hash(code),),
            )
            result = issue_tokens(
                db,
                client_id=client_id,
                user_id=int(row["user_id"]),
                scope=str(row["scope"]),
                resource=str(row["resource"]),
            )
            db.commit()
            return JSONResponse(
                result,
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )

        if grant_type == "refresh_token":
            refresh_token = str(form.get("refresh_token") or "")
            row = db.execute(
                """SELECT * FROM connector_oauth_tokens
                   WHERE refresh_token_hash=? AND client_id=? AND revoked_at IS NULL
                     AND refresh_expires_at>?""",
                (token_hash(refresh_token), client_id, now()),
            ).fetchone()
            if not row:
                return _oauth_error("invalid_grant", "Refresh token is invalid or expired")
            requested = str(form.get("scope") or "").strip()
            current_scopes = set(str(row["scope"]).split())
            if requested:
                narrowed = {item for item in requested.split() if item}
                if not narrowed.issubset(current_scopes):
                    return _oauth_error("invalid_scope", "Refresh scope cannot be expanded")
                scope = " ".join(sorted(narrowed))
            else:
                scope = str(row["scope"])
            db.execute(
                "UPDATE connector_oauth_tokens SET revoked_at=? WHERE access_token_hash=?",
                (now(), row["access_token_hash"]),
            )
            result = issue_tokens(
                db,
                client_id=client_id,
                user_id=int(row["user_id"]),
                scope=scope,
                resource=str(row["resource"]),
            )
            db.commit()
            return JSONResponse(
                result,
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )

    return _oauth_error("unsupported_grant_type", "Use authorization_code or refresh_token")


@router.post(f"{OAUTH_PATH}/revoke", status_code=200)
async def revoke_token(request: Request) -> dict[str, bool]:
    form = await request.form()
    token = str(form.get("token") or "")
    client_id = str(form.get("client_id") or "")
    if not token or not client_id:
        return {"revoked": True}
    hashed = token_hash(token)
    with connect() as db:
        db.execute(
            """UPDATE connector_oauth_tokens SET revoked_at=?
               WHERE client_id=? AND revoked_at IS NULL
                 AND (access_token_hash=? OR refresh_token_hash=?)""",
            (now(), client_id, hashed, hashed),
        )
        db.commit()
    return {"revoked": True}


__all__ = [
    "ADMIN_SCOPE",
    "ALL_SCOPES",
    "AmosclaudConnectorTokenVerifier",
    "BASE_SCOPES",
    "MCP_PATH",
    "OAUTH_PATH",
    "authorization_server_metadata_path",
    "connector_resource_url",
    "oauth_issuer_url",
    "protected_resource_metadata_path",
    "router",
]
