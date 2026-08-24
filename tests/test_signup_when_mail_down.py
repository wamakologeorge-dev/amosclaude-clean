"""Signup must work even when Amosclaud email delivery is down."""

import pytest
from fastapi import HTTPException, Response

from amoscloud_ai.api.routes import auth


def _mail_down(email, code, purpose):
    raise HTTPException(status_code=503, detail="mail down")


def test_signup_creates_account_when_mail_is_down(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    monkeypatch.setattr(auth, "_send_code", _mail_down)
    response = Response()

    result = auth.request_registration_code(
        auth.RegisterCodeRequest(
            email="new.person@gmail.com", name="New Person", password="Sunny-Meadow-42"
        ),
        response,
    )

    assert result["verification"] == "deferred"
    with auth._connect() as db:
        row = db.execute(
            "SELECT is_admin, email_verified FROM users WHERE email=?",
            ("new.person@gmail.com",),
        ).fetchone()
    assert row is not None
    assert row["is_admin"] == 0, "unverified signups must never receive admin"
    assert row["email_verified"] == 0
    assert "set-cookie" in response.headers, "the new user should be signed in"


def test_signup_still_uses_email_code_when_mail_works(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    sent = {}
    monkeypatch.setattr(auth, "_send_code", lambda e, c, p: sent.update(code=c))

    result = auth.request_registration_code(
        auth.RegisterCodeRequest(
            email="coder@gmail.com", name="Coder", password="Rainy-Valley-Lark-77"
        ),
        Response(),
    )
    assert "Verification code sent" in result["message"]

    verified = auth.verify_registration(
        auth.RegisterVerifyRequest(
            email="coder@gmail.com", password="Rainy-Valley-Lark-77", code=sent["code"]
        ),
        Response(),
    )
    assert verified.email == "coder@gmail.com"


def test_duplicate_email_rejected_even_when_mail_is_down(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    monkeypatch.setattr(auth, "_send_code", _mail_down)
    body = auth.RegisterCodeRequest(
        email="only.once@gmail.com", name="Only Once", password="Quiet-River-Stone-9"
    )
    auth.request_registration_code(body, Response())

    with pytest.raises(HTTPException) as excinfo:
        auth.request_registration_code(body, Response())
    assert excinfo.value.status_code == 409
