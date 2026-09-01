from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from amoscloud_ai.book_license import (
    BOOK_LICENSE_ID,
    BookLicenseError,
    authorization_status,
    authorize_and_sign,
    issue_grant,
    verify_receipt,
)


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    return db


def test_root_mit_stays_while_book_has_explicit_proprietary_scope() -> None:
    root = Path(__file__).resolve().parents[1]
    root_license = (root / "LICENSE").read_text(encoding="utf-8")
    scope = (root / "LICENSE-SCOPE.md").read_text(encoding="utf-8")
    manifest = json.loads((root / ".Amosclaud" / "book" / "book.manifest.json").read_text(encoding="utf-8"))

    assert root_license.startswith("MIT License")
    assert "root `LICENSE` remains the MIT License" in scope
    assert manifest["license_contract"]["license_id"] == BOOK_LICENSE_ID
    assert manifest["license_contract"]["repository_root_license_remains_mit"] is True
    assert manifest["license_contract"]["prospective_scope_only"] is True
    assert any(chapter["id"] == "12" for chapter in manifest["chapters"])


def test_account_grant_creates_trusted_signed_receipt_and_tampering_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AMOSCLAUD_BOOK_LICENSE_IDENTITY_DIR", str(tmp_path / "identity"))
    db = _db()
    grant = issue_grant(
        db,
        issued_by_user_id=1,
        subject_type="account",
        subject_id=22,
        permissions=["copy", "export"],
    )

    receipt = authorize_and_sign(
        db,
        account_id=22,
        is_platform_admin=False,
        action="export",
        organization_id=None,
        repository_id=None,
        book_version="book-version-1",
        chapter_id="12",
        content_sha256="a" * 64,
    )

    verified = verify_receipt(receipt)
    assert verified["valid"] is True
    assert verified["license_id"] == grant["license_id"]
    assert receipt["signature_algorithm"] == "Ed25519"
    assert "private" not in json.dumps(receipt).lower()

    tampered = {**receipt, "content_sha256": "b" * 64}
    assert verify_receipt(tampered)["valid"] is False

    fake_signer = {**receipt, "signer_public_key": "AAAA"}
    result = verify_receipt(fake_signer)
    assert result == {"valid": False, "reason": "untrusted_signer"}


def test_unlicensed_export_is_blocked_and_never_auto_invoiced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AMOSCLAUD_BOOK_LICENSE_IDENTITY_DIR", str(tmp_path / "identity"))
    db = _db()

    with pytest.raises(BookLicenseError, match="license required"):
        authorize_and_sign(
            db,
            account_id=44,
            is_platform_admin=False,
            action="export",
            organization_id=None,
            repository_id=None,
            book_version="book-version-2",
            chapter_id="01",
            content_sha256="c" * 64,
        )

    row = db.execute(
        "SELECT decision,invoice_eligible,account_id,action FROM book_license_events ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["decision"] == "blocked_unlicensed"
    assert row["invoice_eligible"] == 0
    assert row["account_id"] == 44
    assert row["action"] == "export"


def test_organization_grant_requires_active_membership() -> None:
    db = _db()
    db.execute(
        """CREATE TABLE organization_members (
               organization_id INTEGER NOT NULL,
               user_id INTEGER NOT NULL,
               status TEXT NOT NULL
           )"""
    )
    issue_grant(
        db,
        issued_by_user_id=1,
        subject_type="organization",
        subject_id=9,
        permissions=["export"],
    )

    denied = authorization_status(
        db,
        account_id=55,
        is_platform_admin=False,
        action="export",
        organization_id=9,
        repository_id=None,
    )
    assert denied["allowed"] is False

    db.execute(
        "INSERT INTO organization_members(organization_id,user_id,status) VALUES (9,55,'active')"
    )
    db.commit()
    allowed = authorization_status(
        db,
        account_id=55,
        is_platform_admin=False,
        action="export",
        organization_id=9,
        repository_id=None,
    )
    assert allowed["allowed"] is True
    assert allowed["source"] == "book-license-grant"


def test_platform_owner_can_authorize_without_customer_license_key() -> None:
    db = _db()
    status = authorization_status(
        db,
        account_id=1,
        is_platform_admin=True,
        action="redistribute",
        organization_id=None,
        repository_id=None,
    )
    assert status["allowed"] is True
    assert status["license_id"] == "AMOSCLAUD-OWNER"
