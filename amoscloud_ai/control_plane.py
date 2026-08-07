"""Cryptographically signed job contracts for the Amosclaud Control Plane.

The Control Plane is intentionally separate from a runner. It authorizes a bounded
piece of work, signs that authorization, and lets a local computer, private server,
or GitHub execution adapter verify the job before touching developer resources.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

CONTROL_PLANE_PROTOCOL = "amosclaud.control-plane.job.v1"
CONTROL_PLANE_ALGORITHM = "Ed25519"
DEFAULT_JOB_TTL_SECONDS = 300
MAX_JOB_TTL_SECONDS = 900
MAX_CLOCK_SKEW_SECONDS = 60


class ExecutionTarget(str, Enum):
    """Execution destinations supported by the native Amosclaud bridge."""

    LOCAL_COMPUTER = "local_computer"
    PRIVATE_SERVER = "private_server"
    GITHUB_REPOSITORY = "github_repository"


SAFE_JOB_PERMISSIONS = frozenset(
    {
        "repository:read",
        "workspace:read",
        "workspace:write",
        "tests:run",
        "patch:create",
        "logs:write",
        "artifacts:write",
        "github:issue:create",
        "github:pull_request:create",
        "deployment:prepare",
        "monitoring:read",
    }
)

SENSITIVE_JOB_PERMISSIONS = frozenset(
    {
        "secrets:read",
        "credentials:rotate",
        "account:admin",
        "billing:write",
        "deployment:execute",
        "repository:delete",
    }
)

KNOWN_JOB_PERMISSIONS = SAFE_JOB_PERMISSIONS | SENSITIVE_JOB_PERMISSIONS


class ControlPlaneError(ValueError):
    """Base error for invalid or untrusted Control Plane contracts."""


class PermissionDeniedError(ControlPlaneError):
    """Raised when a job requests an unauthorized capability."""


class SignatureVerificationError(ControlPlaneError):
    """Raised when a signed job cannot be authenticated."""


class JobExpiredError(ControlPlaneError):
    """Raised when a signed job is outside its allowed execution window."""


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (binascii.Error, TypeError, ValueError) as exc:
        raise SignatureVerificationError("invalid base64 value") from exc


def _format_time(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def _parse_time(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SignatureVerificationError(f"{field_name} must be an ISO-8601 timestamp")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SignatureVerificationError(f"{field_name} is not a valid timestamp") from exc
    if parsed.tzinfo is None:
        raise SignatureVerificationError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _target(value: ExecutionTarget | str) -> ExecutionTarget:
    try:
        return value if isinstance(value, ExecutionTarget) else ExecutionTarget(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ExecutionTarget)
        raise ControlPlaneError(f"execution target must be one of: {allowed}") from exc


def _permissions(
    values: Sequence[str],
    *,
    sensitive_approved: bool,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise PermissionDeniedError("job permissions must be a list of capability names")
    normalized = tuple(sorted({str(value).strip() for value in values if str(value).strip()}))
    unknown = set(normalized).difference(KNOWN_JOB_PERMISSIONS)
    if unknown:
        raise PermissionDeniedError(
            "unknown job permissions: " + ", ".join(sorted(unknown))
        )
    sensitive = set(normalized).intersection(SENSITIVE_JOB_PERMISSIONS)
    if sensitive and not sensitive_approved:
        raise PermissionDeniedError(
            "sensitive permissions require explicit developer approval: "
            + ", ".join(sorted(sensitive))
        )
    return normalized


def _request_digest(request: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(request)).hexdigest()


@dataclass(frozen=True)
class ControlPlaneIdentity:
    """Ed25519 identity used to sign developer-approved jobs."""

    signing_key: SigningKey
    key_id: str

    @classmethod
    def generate(cls) -> "ControlPlaneIdentity":
        """Create a new identity for setup tools and development environments."""

        return cls.from_seed(secrets.token_bytes(32))

    @classmethod
    def from_seed(
        cls,
        seed: bytes,
        *,
        key_id: str | None = None,
    ) -> "ControlPlaneIdentity":
        if len(seed) != 32:
            raise ControlPlaneError("Control Plane signing seeds must contain 32 bytes")
        signing_key = SigningKey(seed)
        derived_id = "cp_" + hashlib.sha256(bytes(signing_key.verify_key)).hexdigest()[:16]
        return cls(signing_key=signing_key, key_id=key_id or derived_id)

    @classmethod
    def from_secret(
        cls,
        secret: str,
        *,
        key_id: str | None = None,
    ) -> "ControlPlaneIdentity":
        """Derive a stable identity from a protected server secret.

        Production should provide a stable secret from Amosclaud-owned secure storage.
        The original secret is never included in a job or public identity response.
        """

        normalized = secret.strip()
        if len(normalized) < 32:
            raise ControlPlaneError("Control Plane secrets must contain at least 32 characters")
        seed = hashlib.sha256(
            f"amosclaud-control-plane:{normalized}".encode("utf-8")
        ).digest()
        return cls.from_seed(seed, key_id=key_id)

    @property
    def verify_key(self) -> VerifyKey:
        return self.signing_key.verify_key

    @property
    def public_key(self) -> str:
        return _encode(bytes(self.verify_key))

    def public_identity(self) -> dict[str, str]:
        return {
            "protocol": CONTROL_PLANE_PROTOCOL,
            "algorithm": CONTROL_PLANE_ALGORITHM,
            "key_id": self.key_id,
            "public_key": self.public_key,
        }

    def authorize_job(
        self,
        *,
        job_id: str,
        account_id: int | str,
        workspace_id: str,
        target: ExecutionTarget | str,
        objective: str,
        permissions: Sequence[str],
        request: Mapping[str, Any] | None = None,
        repository: str | None = None,
        runner_id: str | None = None,
        sensitive_approved: bool = False,
        issued_at: datetime | None = None,
        ttl_seconds: int = DEFAULT_JOB_TTL_SECONDS,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        """Create a short-lived, target-bound job authorization envelope."""

        if not job_id.strip():
            raise ControlPlaneError("job_id is required")
        if not workspace_id.strip():
            raise ControlPlaneError("workspace_id is required")
        normalized_objective = objective.strip()
        if not normalized_objective:
            raise ControlPlaneError("objective is required")
        if ttl_seconds < 1 or ttl_seconds > MAX_JOB_TTL_SECONDS:
            raise ControlPlaneError(
                f"ttl_seconds must be between 1 and {MAX_JOB_TTL_SECONDS}"
            )

        normalized_target = _target(target)
        normalized_permissions = _permissions(
            permissions,
            sensitive_approved=sensitive_approved,
        )
        normalized_request = dict(request or {})
        now = (issued_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)
        authorization_nonce = nonce or secrets.token_urlsafe(18)
        idempotency_material = (
            f"{job_id}:{account_id}:{workspace_id}:{authorization_nonce}"
        ).encode("utf-8")

        authorization: dict[str, Any] = {
            "job_id": job_id.strip(),
            "account_id": str(account_id),
            "workspace_id": workspace_id.strip(),
            "target": normalized_target.value,
            "objective": normalized_objective,
            "permissions": list(normalized_permissions),
            "repository": repository.strip() if repository else None,
            "runner_id": runner_id.strip() if runner_id else None,
            "issued_at": _format_time(now),
            "expires_at": _format_time(expires_at),
            "nonce": authorization_nonce,
            "idempotency_key": hashlib.sha256(idempotency_material).hexdigest(),
            "request_sha256": _request_digest(normalized_request),
            "request": normalized_request,
            "sensitive_approved": bool(sensitive_approved),
        }
        signed_payload = {
            "protocol": CONTROL_PLANE_PROTOCOL,
            "algorithm": CONTROL_PLANE_ALGORITHM,
            "key_id": self.key_id,
            "authorization": authorization,
        }
        signature = self.signing_key.sign(_canonical_json(signed_payload)).signature
        return {**signed_payload, "signature": _encode(signature)}


def verify_authorized_job(
    envelope: Mapping[str, Any],
    *,
    public_key: str,
    expected_key_id: str | None = None,
    expected_target: ExecutionTarget | str | None = None,
    expected_runner_id: str | None = None,
    expected_account_id: int | str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify an Amosclaud job before a runner performs any operation."""

    protocol = envelope.get("protocol")
    algorithm = envelope.get("algorithm")
    key_id = envelope.get("key_id")
    authorization = envelope.get("authorization")
    signature = envelope.get("signature")

    if protocol != CONTROL_PLANE_PROTOCOL:
        raise SignatureVerificationError("unsupported Control Plane protocol")
    if algorithm != CONTROL_PLANE_ALGORITHM:
        raise SignatureVerificationError("unsupported Control Plane signature algorithm")
    if not isinstance(key_id, str) or not key_id:
        raise SignatureVerificationError("key_id is required")
    if expected_key_id is not None and key_id != expected_key_id:
        raise SignatureVerificationError("job was signed by an unexpected key")
    if not isinstance(authorization, Mapping):
        raise SignatureVerificationError("authorization payload is required")
    if not isinstance(signature, str) or not signature:
        raise SignatureVerificationError("signature is required")

    signed_payload = {
        "protocol": protocol,
        "algorithm": algorithm,
        "key_id": key_id,
        "authorization": dict(authorization),
    }
    try:
        VerifyKey(_decode(public_key)).verify(
            _canonical_json(signed_payload),
            _decode(signature),
        )
    except (BadSignatureError, TypeError, ValueError) as exc:
        raise SignatureVerificationError("job signature is invalid") from exc

    issued_at = _parse_time(authorization.get("issued_at"), "issued_at")
    expires_at = _parse_time(authorization.get("expires_at"), "expires_at")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if expires_at <= issued_at:
        raise JobExpiredError("job authorization expires before it becomes valid")
    if issued_at - current > timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
        raise JobExpiredError("job authorization was issued too far in the future")
    if current >= expires_at:
        raise JobExpiredError("job authorization has expired")
    if expires_at - issued_at > timedelta(seconds=MAX_JOB_TTL_SECONDS):
        raise JobExpiredError("job authorization lifetime exceeds the protocol limit")

    target = _target(str(authorization.get("target", "")))
    if expected_target is not None and target != _target(expected_target):
        raise SignatureVerificationError("job is bound to a different execution target")
    if expected_runner_id is not None and authorization.get("runner_id") != expected_runner_id:
        raise SignatureVerificationError("job is bound to a different runner")
    if expected_account_id is not None and authorization.get("account_id") != str(
        expected_account_id
    ):
        raise SignatureVerificationError("job belongs to a different developer account")

    request = authorization.get("request")
    if not isinstance(request, Mapping):
        raise SignatureVerificationError("job request must be an object")
    if authorization.get("request_sha256") != _request_digest(request):
        raise SignatureVerificationError("job request digest does not match its contents")

    permissions = authorization.get("permissions")
    if not isinstance(permissions, Sequence):
        raise SignatureVerificationError("job permissions must be a list")
    _permissions(
        permissions,
        sensitive_approved=bool(authorization.get("sensitive_approved")),
    )
    return dict(authorization)
