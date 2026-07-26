"""Signed, one-time capability grants for the Amosclaud execution chain.

The public command path is intentionally narrow:

    trusted user -> Amosclaud Bot -> Autonomous -> Fixer -> Verifier -> Publisher

Each hop receives only the capability it needs. Grants are repository-, revision-,
objective-, recipient-, and expiry-bound. Write grants are one-time consumable and
every decision is written to a hash-chained SQLite audit ledger.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


class SecurityError(RuntimeError):
    """Base error for denied or invalid Amosclaud security operations."""


class GrantInvalid(SecurityError):
    pass


class GrantExpired(SecurityError):
    pass


class GrantReplay(SecurityError):
    pass


class CapabilityDenied(SecurityError):
    pass


class TransitionDenied(SecurityError):
    pass


class Principal(str, Enum):
    HUMAN = "human"
    BOT = "amosclaud-bot"
    AUTONOMOUS = "amosclaud-autonomous"
    FIXER = "amosclaud-fixer"
    VERIFIER = "amosclaud-verifier"
    PUBLISHER = "amosclaud-publisher"
    GITHUB = "github"


class Capability(str, Enum):
    REPOSITORY_READ = "repository.read"
    REPOSITORY_INSPECT = "repository.inspect"
    REPOSITORY_VERIFY = "repository.verify"
    REPAIR_PLAN = "repair.plan"
    REPAIR_APPLY = "repair.apply"
    REPAIR_VERIFY = "repair.verify"
    BRANCH_CREATE = "repository.branch.create"
    PULL_REQUEST_CREATE = "pull_request.create"
    AUTO_MERGE_REQUEST = "pull_request.auto_merge.request"
    DEPLOY_REQUEST = "deployment.request"
    WORKFLOW_MODIFY = "workflow.modify"
    DEFAULT_BRANCH_WRITE = "repository.default_branch.write"
    DEPLOY_EXECUTE = "deployment.execute"
    SECRETS_READ = "secrets.read"


class CommandState(str, Enum):
    RECEIVED = "received"
    AUTHORIZED = "authorized"
    BLOCKED = "blocked"
    PLANNED = "planned"
    FIXER_AUTHORIZED = "fixer_authorized"
    PATCH_PROPOSED = "patch_proposed"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    PUBLISH_AUTHORIZED = "publish_authorized"
    PUBLISHED = "published"
    MERGE_PENDING = "merge_pending"
    MERGED = "merged"
    FAILED = "failed"


WRITE_CAPABILITIES = frozenset(
    {
        Capability.REPAIR_APPLY,
        Capability.BRANCH_CREATE,
        Capability.PULL_REQUEST_CREATE,
        Capability.AUTO_MERGE_REQUEST,
        Capability.DEPLOY_REQUEST,
        Capability.WORKFLOW_MODIFY,
        Capability.DEFAULT_BRANCH_WRITE,
        Capability.DEPLOY_EXECUTE,
        Capability.SECRETS_READ,
    }
)

NEVER_AUTONOMOUS = frozenset(
    {
        Capability.DEFAULT_BRANCH_WRITE,
        Capability.DEPLOY_EXECUTE,
        Capability.SECRETS_READ,
    }
)

_TRANSITION_CAPABILITIES: dict[tuple[Principal, Principal], frozenset[Capability]] = {
    (Principal.BOT, Principal.AUTONOMOUS): frozenset(
        {
            Capability.REPOSITORY_READ,
            Capability.REPOSITORY_INSPECT,
            Capability.REPOSITORY_VERIFY,
            Capability.REPAIR_PLAN,
        }
    ),
    (Principal.AUTONOMOUS, Principal.FIXER): frozenset({Capability.REPAIR_APPLY}),
    (Principal.FIXER, Principal.VERIFIER): frozenset({Capability.REPAIR_VERIFY}),
    (Principal.VERIFIER, Principal.PUBLISHER): frozenset(
        {
            Capability.BRANCH_CREATE,
            Capability.PULL_REQUEST_CREATE,
            Capability.AUTO_MERGE_REQUEST,
        }
    ),
    (Principal.PUBLISHER, Principal.GITHUB): frozenset(
        {
            Capability.PULL_REQUEST_CREATE,
            Capability.AUTO_MERGE_REQUEST,
        }
    ),
    (Principal.HUMAN, Principal.AUTONOMOUS): frozenset(
        {
            Capability.REPOSITORY_READ,
            Capability.REPOSITORY_INSPECT,
            Capability.REPOSITORY_VERIFY,
            Capability.REPAIR_PLAN,
            Capability.DEPLOY_REQUEST,
            Capability.WORKFLOW_MODIFY,
        }
    ),
}

_STATE_TRANSITIONS: dict[CommandState | None, frozenset[CommandState]] = {
    None: frozenset({CommandState.RECEIVED}),
    CommandState.RECEIVED: frozenset(
        {CommandState.AUTHORIZED, CommandState.BLOCKED, CommandState.FAILED}
    ),
    CommandState.AUTHORIZED: frozenset(
        {CommandState.PLANNED, CommandState.BLOCKED, CommandState.FAILED}
    ),
    CommandState.PLANNED: frozenset(
        {
            CommandState.FIXER_AUTHORIZED,
            CommandState.VERIFYING,
            CommandState.BLOCKED,
            CommandState.FAILED,
        }
    ),
    CommandState.FIXER_AUTHORIZED: frozenset(
        {CommandState.PATCH_PROPOSED, CommandState.BLOCKED, CommandState.FAILED}
    ),
    CommandState.PATCH_PROPOSED: frozenset(
        {CommandState.VERIFYING, CommandState.BLOCKED, CommandState.FAILED}
    ),
    CommandState.VERIFYING: frozenset(
        {CommandState.VERIFIED, CommandState.BLOCKED, CommandState.FAILED}
    ),
    CommandState.VERIFIED: frozenset(
        {
            CommandState.PUBLISH_AUTHORIZED,
            CommandState.MERGED,
            CommandState.BLOCKED,
            CommandState.FAILED,
        }
    ),
    CommandState.PUBLISH_AUTHORIZED: frozenset(
        {CommandState.PUBLISHED, CommandState.BLOCKED, CommandState.FAILED}
    ),
    CommandState.PUBLISHED: frozenset(
        {CommandState.MERGE_PENDING, CommandState.FAILED}
    ),
    CommandState.MERGE_PENDING: frozenset(
        {CommandState.MERGED, CommandState.FAILED}
    ),
    CommandState.BLOCKED: frozenset(),
    CommandState.MERGED: frozenset(),
    CommandState.FAILED: frozenset(),
}

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.:-]+/[A-Za-z0-9_.:-]+$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def objective_digest(objective: str) -> str:
    normalized = " ".join((objective or "").strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def bounded_repair_constraints(
    *,
    max_changed_files: int = 25,
    protected_prefixes: Iterable[str] = (),
    protected_paths: Iterable[str] = (),
    approval_profile: str = "verified-ci-bounded-repair",
) -> dict[str, Any]:
    return {
        "profile": "bounded-repair",
        "approval_profile": approval_profile,
        "max_changed_files": max_changed_files,
        "protected_prefixes": sorted(set(protected_prefixes)),
        "protected_paths": sorted(set(protected_paths)),
        "allow_symlinks": False,
        "allow_submodules": False,
        "allow_workflows": False,
        "allow_secrets": False,
        "allow_default_branch_write": False,
        "require_fresh_verification": True,
    }


@dataclass(frozen=True)
class CommandGrant:
    version: int
    command_id: str
    correlation_id: str
    parent_command_id: str | None
    issuer: str
    subject: str
    repository: str
    target_sha: str
    objective_digest: str
    capabilities: tuple[str, ...]
    constraints: dict[str, Any]
    source: dict[str, Any]
    approval: dict[str, Any]
    issued_at: int
    expires_at: int
    nonce: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CommandGrant":
        required = {
            "version",
            "command_id",
            "correlation_id",
            "issuer",
            "subject",
            "repository",
            "target_sha",
            "objective_digest",
            "capabilities",
            "constraints",
            "source",
            "approval",
            "issued_at",
            "expires_at",
            "nonce",
        }
        missing = required - set(payload)
        if missing:
            raise GrantInvalid(f"grant is missing required claims: {sorted(missing)}")
        capabilities = payload.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            raise GrantInvalid("grant capabilities must be a non-empty list")
        for name in ("constraints", "source", "approval"):
            if not isinstance(payload.get(name), dict):
                raise GrantInvalid(f"grant {name} must be an object")
        return cls(
            version=int(payload["version"]),
            command_id=str(payload["command_id"]),
            correlation_id=str(payload["correlation_id"]),
            parent_command_id=(
                str(payload["parent_command_id"])
                if payload.get("parent_command_id")
                else None
            ),
            issuer=str(payload["issuer"]),
            subject=str(payload["subject"]),
            repository=str(payload["repository"]),
            target_sha=str(payload["target_sha"]),
            objective_digest=str(payload["objective_digest"]),
            capabilities=tuple(str(item) for item in capabilities),
            constraints=dict(payload["constraints"]),
            source=dict(payload["source"]),
            approval=dict(payload["approval"]),
            issued_at=int(payload["issued_at"]),
            expires_at=int(payload["expires_at"]),
            nonce=str(payload["nonce"]),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["capabilities"] = list(self.capabilities)
        return payload


@dataclass(frozen=True)
class SecurityDecision:
    allowed: bool
    reason: str
    command_id: str | None = None
    correlation_id: str | None = None
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    grant: CommandGrant | None = None


class SecurityAuthority:
    """Issue and validate constrained command grants.

    The signing secret is an authority credential. It must not be exposed to the
    model, user repository, browser, generated patch, or a project container.
    """

    SECRET_ENV = "AMOSCLAUD_COMMAND_BUS_SECRET"
    STATE_ENV = "AMOSCLAUD_SECURITY_STATE_DB"

    def __init__(
        self,
        secret: str | bytes,
        state_path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
        if len(secret_bytes) < 32:
            raise SecurityError("command-bus secret must contain at least 32 bytes")
        self._secret = secret_bytes
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._initialize()

    @classmethod
    def from_environment(
        cls,
        *,
        state_path: str | Path | None = None,
        required: bool = True,
    ) -> "SecurityAuthority | None":
        secret = os.getenv(cls.SECRET_ENV, "").strip()
        if not secret:
            if required:
                raise SecurityError(f"{cls.SECRET_ENV} is required")
            return None
        configured_path = os.getenv(cls.STATE_ENV, "").strip()
        path = state_path or configured_path or "./data/security/command-bus.db"
        return cls(secret, path)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.state_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS command_grant_consumptions (
                    nonce TEXT PRIMARY KEY,
                    command_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    repository TEXT NOT NULL,
                    consumed_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS command_state (
                    command_id TEXT PRIMARY KEY,
                    correlation_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS command_audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    command_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    state TEXT,
                    detail_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_command_audit_command
                    ON command_audit(command_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_command_audit_correlation
                    ON command_audit(correlation_id, sequence);
                """
            )

    @staticmethod
    def _principal(value: Principal | str) -> Principal:
        try:
            return value if isinstance(value, Principal) else Principal(str(value))
        except ValueError as exc:
            raise GrantInvalid(f"unknown principal: {value}") from exc

    @staticmethod
    def _capabilities(
        values: Iterable[Capability | str],
    ) -> tuple[Capability, ...]:
        result: list[Capability] = []
        for value in values:
            try:
                capability = (
                    value if isinstance(value, Capability) else Capability(str(value))
                )
            except ValueError as exc:
                raise GrantInvalid(f"unknown capability: {value}") from exc
            if capability not in result:
                result.append(capability)
        if not result:
            raise GrantInvalid("at least one capability is required")
        return tuple(result)

    @staticmethod
    def _validate_repository(repository: str) -> str:
        value = repository.strip()
        if not _REPOSITORY_RE.fullmatch(value):
            raise GrantInvalid("repository must use owner/name or local/id form")
        return value

    @staticmethod
    def _validate_sha(target_sha: str) -> str:
        value = target_sha.strip()
        if not _SHA_RE.fullmatch(value):
            raise GrantInvalid("target_sha must be a Git commit SHA")
        return value.lower()

    @staticmethod
    def _validate_source(source: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(source)
        kind = str(value.get("kind") or "").strip()
        identifier = str(value.get("id") or "").strip()
        if not kind or not identifier:
            raise GrantInvalid("source.kind and source.id are required")
        serialized = json.dumps(value, sort_keys=True)
        if len(serialized) > 4000:
            raise GrantInvalid("source metadata is too large")
        return value

    @staticmethod
    def _validate_approval(approval: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(approval)
        kind = str(value.get("kind") or "none").strip().lower()
        decision = str(value.get("decision") or "none").strip().lower()
        if kind not in {"none", "human", "verified-ci-failure"}:
            raise GrantInvalid("unsupported approval kind")
        if decision not in {"none", "approved", "denied"}:
            raise GrantInvalid("unsupported approval decision")
        value["kind"] = kind
        value["decision"] = decision
        return value

    @staticmethod
    def _validate_constraints(
        capabilities: tuple[Capability, ...],
        constraints: Mapping[str, Any],
        approval: Mapping[str, Any],
    ) -> dict[str, Any]:
        value = dict(constraints)
        if any(capability in NEVER_AUTONOMOUS for capability in capabilities):
            raise CapabilityDenied(
                "default-branch writes, deployment execution, and secret reads are "
                "never autonomous capabilities"
            )

        if Capability.REPAIR_APPLY in capabilities:
            if value.get("profile") != "bounded-repair":
                raise CapabilityDenied("repair.apply requires the bounded-repair profile")
            max_files = int(value.get("max_changed_files", 0))
            if not 1 <= max_files <= 25:
                raise CapabilityDenied("bounded repair may change only 1-25 files")
            for flag in (
                "allow_symlinks",
                "allow_submodules",
                "allow_workflows",
                "allow_secrets",
                "allow_default_branch_write",
            ):
                if value.get(flag) is not False:
                    raise CapabilityDenied(f"bounded repair requires {flag}=false")
            if approval.get("kind") not in {"human", "verified-ci-failure"}:
                raise CapabilityDenied(
                    "repair.apply requires human approval or verified CI failure evidence"
                )
            if approval.get("decision") != "approved":
                raise CapabilityDenied("repair.apply approval is not approved")

        if Capability.WORKFLOW_MODIFY in capabilities:
            if approval.get("kind") != "human" or approval.get("decision") != "approved":
                raise CapabilityDenied("workflow changes require explicit human approval")
            if value.get("profile") != "human-approved-sensitive":
                raise CapabilityDenied(
                    "workflow changes require human-approved-sensitive profile"
                )

        publishing = {
            Capability.BRANCH_CREATE,
            Capability.PULL_REQUEST_CREATE,
            Capability.AUTO_MERGE_REQUEST,
        }
        if publishing.intersection(capabilities):
            if value.get("allow_default_branch_write") is not False:
                raise CapabilityDenied("publisher grants must prohibit default-branch writes")
            receipt = str(value.get("verification_receipt") or "")
            if not receipt or len(receipt) > 256:
                raise CapabilityDenied(
                    "publisher grants require a bounded verification receipt"
                )

        serialized = json.dumps(value, sort_keys=True)
        if len(serialized) > 12_000:
            raise GrantInvalid("grant constraints are too large")
        return value

    @staticmethod
    def _validate_transition_capabilities(
        issuer: Principal,
        subject: Principal,
        capabilities: tuple[Capability, ...],
    ) -> None:
        allowed = _TRANSITION_CAPABILITIES.get((issuer, subject), frozenset())
        denied = [item.value for item in capabilities if item not in allowed]
        if denied:
            raise CapabilityDenied(
                f"{issuer.value} cannot grant {denied} to {subject.value}"
            )
        if issuer == subject:
            raise CapabilityDenied("components may not self-authorize")

    @staticmethod
    def _ttl_limit(capabilities: tuple[Capability, ...]) -> int:
        return 900 if WRITE_CAPABILITIES.intersection(capabilities) else 3600

    def issue(
        self,
        *,
        issuer: Principal | str,
        subject: Principal | str,
        repository: str,
        target_sha: str,
        objective: str,
        capabilities: Iterable[Capability | str],
        constraints: Mapping[str, Any] | None = None,
        source: Mapping[str, Any],
        approval: Mapping[str, Any] | None = None,
        ttl_seconds: int = 300,
        command_id: str | None = None,
        correlation_id: str | None = None,
        parent_command_id: str | None = None,
    ) -> str:
        issuer_value = self._principal(issuer)
        subject_value = self._principal(subject)
        capability_values = self._capabilities(capabilities)
        self._validate_transition_capabilities(
            issuer_value,
            subject_value,
            capability_values,
        )
        repository_value = self._validate_repository(repository)
        sha_value = self._validate_sha(target_sha)
        if not objective.strip():
            raise GrantInvalid("objective is required")
        approval_value = self._validate_approval(approval or {})
        constraints_value = self._validate_constraints(
            capability_values,
            constraints or {},
            approval_value,
        )
        source_value = self._validate_source(source)
        ttl_limit = self._ttl_limit(capability_values)
        ttl = int(ttl_seconds)
        if not 1 <= ttl <= ttl_limit:
            raise GrantInvalid(f"grant TTL must be between 1 and {ttl_limit} seconds")
        now = int(self._clock())
        grant = CommandGrant(
            version=1,
            command_id=command_id or f"cmd_{uuid.uuid4().hex}",
            correlation_id=correlation_id or f"corr_{uuid.uuid4().hex}",
            parent_command_id=parent_command_id,
            issuer=issuer_value.value,
            subject=subject_value.value,
            repository=repository_value,
            target_sha=sha_value,
            objective_digest=objective_digest(objective),
            capabilities=tuple(item.value for item in capability_values),
            constraints=constraints_value,
            source=source_value,
            approval=approval_value,
            issued_at=now,
            expires_at=now + ttl,
            nonce=secrets.token_urlsafe(24),
        )
        payload = _canonical_json(grant.to_dict())
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        token = f"{_b64encode(payload)}.{_b64encode(signature)}"
        self.audit(
            command_id=grant.command_id,
            correlation_id=grant.correlation_id,
            event_type="grant_issued",
            actor=grant.issuer,
            detail={
                "subject": grant.subject,
                "capabilities": list(grant.capabilities),
                "repository": grant.repository,
                "target_sha": grant.target_sha,
                "expires_at": grant.expires_at,
                "parent_command_id": grant.parent_command_id,
            },
        )
        return token

    def decode(self, token: str) -> CommandGrant:
        try:
            encoded_payload, encoded_signature = token.split(".", 1)
            payload = _b64decode(encoded_payload)
            signature = _b64decode(encoded_signature)
        except (ValueError, TypeError, base64.binascii.Error) as exc:
            raise GrantInvalid("grant token is malformed") from exc
        expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, signature):
            raise GrantInvalid("grant signature is invalid")
        try:
            decoded = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise GrantInvalid("grant payload is invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise GrantInvalid("grant payload must be an object")
        grant = CommandGrant.from_dict(decoded)
        self._validate_claims(grant)
        return grant

    def _validate_claims(self, grant: CommandGrant) -> None:
        if grant.version != 1:
            raise GrantInvalid("unsupported grant version")
        issuer = self._principal(grant.issuer)
        subject = self._principal(grant.subject)
        capabilities = self._capabilities(grant.capabilities)
        self._validate_transition_capabilities(issuer, subject, capabilities)
        self._validate_repository(grant.repository)
        self._validate_sha(grant.target_sha)
        if not re.fullmatch(r"[0-9a-f]{64}", grant.objective_digest):
            raise GrantInvalid("objective digest is invalid")
        self._validate_source(grant.source)
        approval = self._validate_approval(grant.approval)
        self._validate_constraints(capabilities, grant.constraints, approval)
        now = int(self._clock())
        if grant.issued_at > now + 30:
            raise GrantInvalid("grant was issued in the future")
        if grant.expires_at <= now:
            raise GrantExpired("grant has expired")
        max_ttl = self._ttl_limit(capabilities)
        if grant.expires_at - grant.issued_at > max_ttl:
            raise GrantInvalid("grant TTL exceeds the capability limit")
        if not grant.command_id.startswith("cmd_"):
            raise GrantInvalid("command_id is invalid")
        if not grant.correlation_id.startswith("corr_"):
            raise GrantInvalid("correlation_id is invalid")
        if len(grant.nonce) < 20:
            raise GrantInvalid("grant nonce is too short")

    def verify(
        self,
        token: str,
        *,
        expected_subject: Principal | str,
        repository: str,
        target_sha: str,
        objective: str,
        required_capabilities: Iterable[Capability | str],
        consume: bool = False,
        expected_parent_command_id: str | None = None,
    ) -> SecurityDecision:
        grant = self.decode(token)
        subject = self._principal(expected_subject)
        required = self._capabilities(required_capabilities)
        if grant.subject != subject.value:
            raise CapabilityDenied("grant recipient does not match the executing component")
        if grant.repository != self._validate_repository(repository):
            raise CapabilityDenied("grant repository does not match the execution target")
        if grant.target_sha != self._validate_sha(target_sha):
            raise CapabilityDenied("grant target commit does not match the execution target")
        if grant.objective_digest != objective_digest(objective):
            raise CapabilityDenied("grant objective does not match the requested operation")
        if expected_parent_command_id is not None and (
            grant.parent_command_id != expected_parent_command_id
        ):
            raise CapabilityDenied("grant parent command does not match the security chain")
        granted = {Capability(item) for item in grant.capabilities}
        missing = [item.value for item in required if item not in granted]
        if missing:
            raise CapabilityDenied(f"grant is missing required capabilities: {missing}")
        if consume:
            self.consume(grant)
        self.audit(
            command_id=grant.command_id,
            correlation_id=grant.correlation_id,
            event_type="grant_verified",
            actor=grant.subject,
            detail={
                "issuer": grant.issuer,
                "capabilities": list(grant.capabilities),
                "consumed": consume,
            },
        )
        return SecurityDecision(
            allowed=True,
            reason="signed capability grant verified",
            command_id=grant.command_id,
            correlation_id=grant.correlation_id,
            capabilities=grant.capabilities,
            grant=grant,
        )

    def consume(self, grant: CommandGrant) -> None:
        now = int(self._clock())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """INSERT INTO command_grant_consumptions
                       (nonce,command_id,correlation_id,subject,repository,consumed_at)
                       VALUES (?,?,?,?,?,?)""",
                    (
                        grant.nonce,
                        grant.command_id,
                        grant.correlation_id,
                        grant.subject,
                        grant.repository,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise GrantReplay("grant has already been consumed") from exc
            db.commit()

    def transition(
        self,
        *,
        command_id: str,
        correlation_id: str,
        state: CommandState | str,
        actor: Principal | str,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        state_value = state if isinstance(state, CommandState) else CommandState(str(state))
        actor_value = self._principal(actor)
        now = int(self._clock())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state,correlation_id FROM command_state WHERE command_id=?",
                (command_id,),
            ).fetchone()
            current = CommandState(row["state"]) if row else None
            if row and row["correlation_id"] != correlation_id:
                db.rollback()
                raise TransitionDenied("command correlation identifier changed")
            if state_value not in _STATE_TRANSITIONS[current]:
                db.rollback()
                current_name = current.value if current else "none"
                raise TransitionDenied(
                    f"invalid command transition: {current_name} -> {state_value.value}"
                )
            db.execute(
                """INSERT INTO command_state(command_id,correlation_id,state,updated_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(command_id) DO UPDATE SET
                     state=excluded.state,updated_at=excluded.updated_at""",
                (command_id, correlation_id, state_value.value, now),
            )
            db.commit()
        self.audit(
            command_id=command_id,
            correlation_id=correlation_id,
            event_type="state_transition",
            actor=actor_value.value,
            state=state_value.value,
            detail=dict(detail or {}),
        )

    def audit(
        self,
        *,
        command_id: str,
        correlation_id: str,
        event_type: str,
        actor: Principal | str,
        detail: Mapping[str, Any] | None = None,
        state: str | None = None,
    ) -> str:
        actor_value = actor.value if isinstance(actor, Principal) else str(actor)
        now = int(self._clock())
        event_id = f"evt_{uuid.uuid4().hex}"
        detail_json = json.dumps(
            dict(detail or {}),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous_row = db.execute(
                "SELECT event_hash FROM command_audit ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = previous_row["event_hash"] if previous_row else "0" * 64
            material = _canonical_json(
                {
                    "event_id": event_id,
                    "command_id": command_id,
                    "correlation_id": correlation_id,
                    "event_type": event_type,
                    "actor": actor_value,
                    "state": state,
                    "detail_json": detail_json,
                    "previous_hash": previous_hash,
                    "created_at": now,
                }
            )
            event_hash = hashlib.sha256(material).hexdigest()
            db.execute(
                """INSERT INTO command_audit
                   (event_id,command_id,correlation_id,event_type,actor,state,
                    detail_json,previous_hash,event_hash,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_id,
                    command_id,
                    correlation_id,
                    event_type,
                    actor_value,
                    state,
                    detail_json,
                    previous_hash,
                    event_hash,
                    now,
                ),
            )
            db.commit()
        return event_hash

    def audit_events(
        self,
        *,
        command_id: str | None = None,
        correlation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM command_audit"
        values: list[Any] = []
        clauses: list[str] = []
        if command_id:
            clauses.append("command_id=?")
            values.append(command_id)
        if correlation_id:
            clauses.append("correlation_id=?")
            values.append(correlation_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY sequence"
        with self._connect() as db:
            rows = db.execute(query, values).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["detail"] = json.loads(item.pop("detail_json"))
            result.append(item)
        return result

    def verify_audit_chain(self) -> bool:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM command_audit ORDER BY sequence"
            ).fetchall()
        previous_hash = "0" * 64
        for row in rows:
            if row["previous_hash"] != previous_hash:
                return False
            material = _canonical_json(
                {
                    "event_id": row["event_id"],
                    "command_id": row["command_id"],
                    "correlation_id": row["correlation_id"],
                    "event_type": row["event_type"],
                    "actor": row["actor"],
                    "state": row["state"],
                    "detail_json": row["detail_json"],
                    "previous_hash": row["previous_hash"],
                    "created_at": row["created_at"],
                }
            )
            expected = hashlib.sha256(material).hexdigest()
            if not hmac.compare_digest(expected, row["event_hash"]):
                return False
            previous_hash = row["event_hash"]
        return True


def security_enforced() -> bool:
    configured = os.getenv("AMOSCLAUD_SECURITY_ENFORCE", "").strip().lower()
    if configured:
        return configured in {"1", "true", "yes", "on"}
    environment = (
        os.getenv("AMOSCLAUD_ENV")
        or os.getenv("ENVIRONMENT")
        or "development"
    ).strip().lower()
    return environment in {"production", "prod"}
