"""Authenticated Git smart-HTTP transport for native Amosclaud repositories."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, Response

from amoscloud_ai.api.routes import auth
from amoscloud_ai.api.routes.service_keys import authenticate_service_key
from repository.connector import RepositoryConnector, RepositoryConnectorError, RepositoryRecord

router = APIRouter(prefix="/git", tags=["native-git"])
_CONNECTOR = RepositoryConnector()
_ALLOWED_SERVICES = {"git-upload-pack", "git-receive-pack"}
_MAX_PUSH_BYTES = int(os.getenv("AMOSCLAUD_MAX_GIT_REQUEST_BYTES", str(64 * 1024 * 1024)))
_GIT_TIMEOUT = int(os.getenv("AMOSCLAUD_GIT_TIMEOUT_SECONDS", "120"))


@dataclass(frozen=True, slots=True)
class GitPrincipal:
    kind: str
    identity: str
    scopes: frozenset[str]
    is_admin: bool = False


def _bearer(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def authenticate_git_principal(
    authorization: str | None = Header(default=None),
    amos_session: str | None = Cookie(default=None),
) -> GitPrincipal:
    """Authenticate either an Amosclaud session or a scoped service key."""
    raw = _bearer(authorization)
    if raw:
        key = authenticate_service_key(raw)
        return GitPrincipal(
            kind="service-key",
            identity=str(key.get("service") or key.get("name") or "service"),
            scopes=frozenset(str(item) for item in key.get("scopes", [])),
        )
    user = auth.get_user_from_session(amos_session)
    if user:
        return GitPrincipal(
            kind="user",
            identity=str(user["email"] or user["name"] or user["id"]).lower(),
            scopes=frozenset({"repositories:read", "repositories:write"}),
            is_admin=bool(user["is_admin"]),
        )
    raise HTTPException(status_code=401, detail="Authenticate with an Amosclaud session or service key")


def _authorize(record: RepositoryRecord, principal: GitPrincipal, *, write: bool) -> None:
    required = "repositories:write" if write else "repositories:read"
    compatibility = "tasks:write" if write else "tasks:read"
    if principal.kind == "user":
        identities = {record.owner.lower(), record.owner_email.lower()}
        if principal.is_admin or principal.identity in identities:
            return
        raise HTTPException(status_code=403, detail="Repository access denied")
    if required in principal.scopes or compatibility in principal.scopes:
        return
    raise HTTPException(status_code=403, detail=f"Service key requires scope: {required}")


def _repository(owner: str, name: str) -> RepositoryRecord:
    try:
        return _CONNECTOR.require_existing(owner, name)
    except RepositoryConnectorError as exc:
        message = str(exc)
        status = 404 if "not found" in message or "not initialized" in message else 400
        raise HTTPException(status_code=status, detail=message) from exc


def _service(value: str) -> str:
    if value not in _ALLOWED_SERVICES:
        raise HTTPException(status_code=400, detail="Unsupported Git service")
    return value


def _git_command(record: RepositoryRecord, service: str, *, advertise: bool = False) -> list[str]:
    command = ["git", service, "--stateless-rpc"]
    if advertise:
        command.append("--advertise-refs")
    command.append(".")
    return command


@router.get("/{username}/{repo_name}/info/refs")
async def git_info_refs(
    username: str,
    repo_name: str,
    service: str = Query(...),
    principal: GitPrincipal = Depends(authenticate_git_principal),
) -> Response:
    service = _service(service)
    record = _repository(username, repo_name)
    _authorize(record, principal, write=service == "git-receive-pack")
    try:
        result = subprocess.run(
            _git_command(record, service, advertise=True),
            cwd=record.storage_path,
            capture_output=True,
            check=True,
            timeout=_GIT_TIMEOUT,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise HTTPException(status_code=502, detail="Native Git advertisement failed") from exc
    banner = f"# service={service}\n".encode("utf-8")
    payload = f"{len(banner) + 4:04x}".encode("ascii") + banner + b"0000" + result.stdout
    return Response(
        content=payload,
        media_type=f"application/x-{service}-advertisement",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{username}/{repo_name}/{service}")
async def git_service_rpc(
    username: str,
    repo_name: str,
    service: str,
    request: Request,
    principal: GitPrincipal = Depends(authenticate_git_principal),
) -> Response:
    service = _service(service)
    record = _repository(username, repo_name)
    write = service == "git-receive-pack"
    _authorize(record, principal, write=write)

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_PUSH_BYTES:
                raise HTTPException(status_code=413, detail="Git request exceeds platform limit")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
    body = await request.body()
    if len(body) > _MAX_PUSH_BYTES:
        raise HTTPException(status_code=413, detail="Git request exceeds platform limit")

    process = subprocess.Popen(
        _git_command(record, service),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        cwd=record.storage_path,
    )
    try:
        stdout, _stderr = process.communicate(input=body, timeout=_GIT_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise HTTPException(status_code=504, detail="Native Git operation timed out") from exc
    if process.returncode != 0:
        raise HTTPException(status_code=502, detail="Native Git operation failed")
    return Response(
        content=stdout,
        media_type=f"application/x-{service}-result",
        headers={"Cache-Control": "no-store"},
    )
