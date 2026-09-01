# SPDX-License-Identifier: LicenseRef-Amosclaud-Book-Proprietary-1.0
"""License enforcement and signed provenance for Amosclaud Book.

The repository root may remain MIT licensed. This module belongs to the
separately scoped Amosclaud Book product and enforces official Book copy/export
operations without storing private signing keys in Book data.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

BOOK_LICENSE_ID = "LicenseRef-Amosclaud-Book-Proprietary-1.0"
BOOK_LICENSE_VERSION = "1.0"
BOOK_LICENSE_TERMS_PATH = "LICENSES/Amosclaud-Book-Proprietary-1.0.txt"
_ALLOWED_PERMISSIONS = {"copy", "export", "redistribute"}


class BookLicenseError(ValueError):
    """Raised when an official Book licensed action is not authorized."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    text = str(value or "")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _identity_dir() -> Path:
    return Path(os.getenv("AMOSCLAUD_BOOK_LICENSE_IDENTITY_DIR", "data/book-license-identity")).expanduser().resolve()


def _signing_file() -> Path:
    return _identity_dir() / "ed25519-signing.key"


def _write_private_key(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False, prefix="book-license-", suffix=".tmp") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _private_key() -> Ed25519PrivateKey:
    path = _signing_file()
    if not path.exists():
        key = Ed25519PrivateKey.generate()
        raw = key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        _write_private_key(path, raw)
        return key
    try:
        return Ed25519PrivateKey.from_private_bytes(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise BookLicenseError("Amosclaud Book signing identity is unavailable") from exc


def public_signer() -> dict[str, str]:
    public = _private_key().public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return {
        "algorithm": "Ed25519",
        "key_id": f"amosclaud_book_{hashlib.sha256(public).hexdigest()[:32]}",
        "public_key": _b64(public),
    }


def ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS book_license_grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            license_id TEXT NOT NULL UNIQUE,
            subject_type TEXT NOT NULL CHECK(subject_type IN ('account','organization')),
            subject_id INTEGER NOT NULL,
            permissions_json TEXT NOT NULL,
            repository_id INTEGER,
            issued_by_user_id INTEGER NOT NULL,
            issued_at TEXT NOT NULL,
            expires_at TEXT,
            revoked_at TEXT,
            terms_version TEXT NOT NULL,
            billing_terms_accepted INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_book_license_subject
            ON book_license_grants(subject_type,subject_id,revoked_at,expires_at);
        CREATE TABLE IF NOT EXISTS book_license_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            account_id INTEGER,
            organization_id INTEGER,
            repository_id INTEGER,
            license_id TEXT,
            action TEXT NOT NULL,
            decision TEXT NOT NULL,
            book_version TEXT NOT NULL,
            chapter_id TEXT,
            content_sha256 TEXT,
            occurred_at TEXT NOT NULL,
            reason TEXT,
            invoice_eligible INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    db.commit()


def issue_grant(
    db: sqlite3.Connection,
    *,
    issued_by_user_id: int,
    subject_type: str,
    subject_id: int,
    permissions: Iterable[str],
    repository_id: int | None = None,
    expires_at: str | None = None,
    billing_terms_accepted: bool = False,
) -> dict[str, Any]:
    ensure_schema(db)
    normalized = sorted({str(item).strip().lower() for item in permissions if str(item).strip()})
    if not normalized or any(item not in _ALLOWED_PERMISSIONS for item in normalized):
        raise BookLicenseError("Book license permissions must be copy, export, or redistribute")
    if subject_type not in {"account", "organization"}:
        raise BookLicenseError("Book license subject must be account or organization")
    license_id = "ABK-" + secrets.token_hex(12).upper()
    db.execute(
        """INSERT INTO book_license_grants(
               license_id,subject_type,subject_id,permissions_json,repository_id,
               issued_by_user_id,issued_at,expires_at,terms_version,billing_terms_accepted
           ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            license_id,
            subject_type,
            int(subject_id),
            json.dumps(normalized, separators=(",", ":")),
            repository_id,
            int(issued_by_user_id),
            _now(),
            expires_at,
            BOOK_LICENSE_VERSION,
            1 if billing_terms_accepted else 0,
        ),
    )
    db.commit()
    return {
        "license_id": license_id,
        "license": BOOK_LICENSE_ID,
        "subject_type": subject_type,
        "subject_id": int(subject_id),
        "permissions": normalized,
        "repository_id": repository_id,
        "expires_at": expires_at,
        "billing_terms_accepted": bool(billing_terms_accepted),
    }


def _active_grants(
    db: sqlite3.Connection,
    *,
    account_id: int,
    organization_id: int | None,
    repository_id: int | None,
) -> list[sqlite3.Row]:
    ensure_schema(db)
    now = _now()
    clauses = ["(subject_type='account' AND subject_id=?)"]
    params: list[Any] = [int(account_id)]
    if organization_id is not None:
        membership = db.execute(
            """SELECT 1 FROM organization_members
               WHERE organization_id=? AND user_id=? AND status='active'""",
            (int(organization_id), int(account_id)),
        ).fetchone()
        if membership:
            clauses.append("(subject_type='organization' AND subject_id=?)")
            params.append(int(organization_id))
    query = f"""SELECT * FROM book_license_grants
                WHERE ({' OR '.join(clauses)})
                  AND revoked_at IS NULL
                  AND (expires_at IS NULL OR expires_at>?)
                  AND (repository_id IS NULL OR repository_id=?)
                ORDER BY id DESC"""
    params.extend([now, repository_id])
    return list(db.execute(query, tuple(params)).fetchall())


def authorization_status(
    db: sqlite3.Connection,
    *,
    account_id: int,
    is_platform_admin: bool,
    action: str,
    organization_id: int | None,
    repository_id: int | None,
) -> dict[str, Any]:
    normalized = str(action).strip().lower()
    if normalized not in _ALLOWED_PERMISSIONS:
        raise BookLicenseError("Unknown Book licensed action")
    if is_platform_admin:
        return {
            "allowed": True,
            "source": "amosclaud-owner",
            "license_id": "AMOSCLAUD-OWNER",
            "permissions": sorted(_ALLOWED_PERMISSIONS),
            "billing_terms_accepted": False,
        }
    for row in _active_grants(
        db,
        account_id=account_id,
        organization_id=organization_id,
        repository_id=repository_id,
    ):
        permissions = set(json.loads(row["permissions_json"] or "[]"))
        if normalized in permissions:
            return {
                "allowed": True,
                "source": "book-license-grant",
                "license_id": row["license_id"],
                "permissions": sorted(permissions),
                "billing_terms_accepted": bool(row["billing_terms_accepted"]),
            }
    return {
        "allowed": False,
        "source": "none",
        "license_id": None,
        "permissions": [],
        "billing_terms_accepted": False,
    }


def _record_event(
    db: sqlite3.Connection,
    *,
    account_id: int | None,
    organization_id: int | None,
    repository_id: int | None,
    license_id: str | None,
    action: str,
    decision: str,
    book_version: str,
    chapter_id: str | None,
    content_sha256: str | None,
    reason: str | None,
    invoice_eligible: bool,
) -> str:
    ensure_schema(db)
    event_id = "bookevt_" + secrets.token_hex(12)
    db.execute(
        """INSERT INTO book_license_events(
               event_id,account_id,organization_id,repository_id,license_id,action,
               decision,book_version,chapter_id,content_sha256,occurred_at,reason,invoice_eligible
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            event_id,
            account_id,
            organization_id,
            repository_id,
            license_id,
            action,
            decision,
            book_version,
            chapter_id,
            content_sha256,
            _now(),
            reason,
            1 if invoice_eligible else 0,
        ),
    )
    db.commit()
    return event_id


def authorize_and_sign(
    db: sqlite3.Connection,
    *,
    account_id: int,
    is_platform_admin: bool,
    action: str,
    organization_id: int | None,
    repository_id: int | None,
    book_version: str,
    chapter_id: str | None,
    content_sha256: str,
) -> dict[str, Any]:
    status = authorization_status(
        db,
        account_id=account_id,
        is_platform_admin=is_platform_admin,
        action=action,
        organization_id=organization_id,
        repository_id=repository_id,
    )
    if not status["allowed"]:
        event_id = _record_event(
            db,
            account_id=account_id,
            organization_id=organization_id,
            repository_id=repository_id,
            license_id=None,
            action=action,
            decision="blocked_unlicensed",
            book_version=book_version,
            chapter_id=chapter_id,
            content_sha256=content_sha256,
            reason="No active Amosclaud Book grant covers this official action.",
            invoice_eligible=False,
        )
        raise BookLicenseError(f"Amosclaud Book license required; audit event {event_id}")

    signer = public_signer()
    payload = {
        "schema_version": 1,
        "receipt_type": "amosclaud-book-license-receipt",
        "license": BOOK_LICENSE_ID,
        "terms_version": BOOK_LICENSE_VERSION,
        "license_id": status["license_id"],
        "action": str(action).lower(),
        "account_id": int(account_id),
        "organization_id": organization_id,
        "repository_id": repository_id,
        "chapter_id": chapter_id,
        "book_version": book_version,
        "content_sha256": content_sha256,
        "issued_at": _now(),
        "signer_key_id": signer["key_id"],
        "signer_public_key": signer["public_key"],
        "signature_algorithm": signer["algorithm"],
    }
    signature = _b64(_private_key().sign(b"amosclaud-book-license-v1\0" + _canonical(payload)))
    receipt = {**payload, "signature": signature}
    event_id = _record_event(
        db,
        account_id=account_id,
        organization_id=organization_id,
        repository_id=repository_id,
        license_id=status["license_id"],
        action=action,
        decision="allowed",
        book_version=book_version,
        chapter_id=chapter_id,
        content_sha256=content_sha256,
        reason=None,
        invoice_eligible=False,
    )
    receipt["audit_event_id"] = event_id
    return receipt


def verify_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    value = dict(receipt)
    signature = str(value.pop("signature", ""))
    value.pop("audit_event_id", None)
    if value.get("receipt_type") != "amosclaud-book-license-receipt":
        return {"valid": False, "reason": "wrong_receipt_type"}

    trusted = public_signer()
    if (
        value.get("signature_algorithm") != trusted["algorithm"]
        or value.get("signer_key_id") != trusted["key_id"]
        or value.get("signer_public_key") != trusted["public_key"]
    ):
        return {"valid": False, "reason": "untrusted_signer"}

    try:
        public = Ed25519PublicKey.from_public_bytes(_unb64(trusted["public_key"]))
        public.verify(_unb64(signature), b"amosclaud-book-license-v1\0" + _canonical(value))
    except Exception:
        return {"valid": False, "reason": "signature_verification_failed"}
    return {
        "valid": True,
        "license": value.get("license"),
        "license_id": value.get("license_id"),
        "action": value.get("action"),
        "book_version": value.get("book_version"),
        "content_sha256": value.get("content_sha256"),
        "signer_key_id": value.get("signer_key_id"),
    }
