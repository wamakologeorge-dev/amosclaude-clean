from fastapi import Response

from amoscloud_ai.api.routes import auth


def _create_user(database, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", database)
    with auth._connect() as db:
        db.execute(
            """INSERT INTO users(name,email,password_hash,provider,is_admin,created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                "Owner",
                "owner@gmail.com",
                auth._hash_password("correct-horse-battery-staple"),
                "password",
                1,
                "2026-01-01T00:00:00+00:00",
            ),
        )
        db.commit()


def test_existing_user_can_sign_in_with_emailed_code(monkeypatch, tmp_path):
    _create_user(tmp_path / "auth.db", monkeypatch)
    delivered = {}
    monkeypatch.setattr(
        auth,
        "_send_code",
        lambda email, code, purpose: delivered.update(
            email=email, code=code, purpose=purpose
        ),
    )

    result = auth.request_login_code(auth.EmailRequest(email="OWNER@gmail.com"))

    assert "sent a sign-in code" in result["message"]
    assert delivered["email"] == "owner@gmail.com"
    assert delivered["purpose"] == "login"
    response = Response()
    user = auth.verify_login_code(
        auth.EmailCodeLoginRequest(
            email="owner@gmail.com",
            code=delivered["code"],
        ),
        response,
    )
    assert user.email == "owner@gmail.com"
    assert user.is_admin is True
    assert "amos_session=" in response.headers["set-cookie"]


def test_unknown_email_does_not_reveal_account_or_send_code(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    monkeypatch.setattr(
        auth,
        "_send_code",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("Unknown accounts must not receive login codes")
        ),
    )

    result = auth.request_login_code(auth.EmailRequest(email="unknown@gmail.com"))

    assert "If the account exists" in result["message"]
