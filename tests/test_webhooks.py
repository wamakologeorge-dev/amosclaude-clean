import json
import sqlite3

from amoscloud_ai import db_migrations
from amoscloud_ai.api.routes import auth, webhooks


def _database(tmp_path, monkeypatch):
    path = tmp_path / "auth.db"
    monkeypatch.setattr(auth, "DB_PATH", path)
    monkeypatch.setenv("AMOSCLAUD_MASTER_KEY", "test-master-key")
    with auth._connect() as db:
        db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) VALUES (?,?,?,?,?,?)",
            ("Test", "test@example.com", None, "password", 0, webhooks._now()),
        )
        db.commit()
    db_migrations.run_migrations(path)
    return path


def test_signature_is_hmac_sha256():
    value = webhooks.signature("secret", "1700000000", b'{"ok":true}')
    assert value == "v1=c1afc7c2df3db0690d7d75954610ed1a1d959ce96355ccb8c0a8bc09fd0cfc27"


def test_dispatch_signs_and_records_delivery(tmp_path, monkeypatch):
    path = _database(tmp_path, monkeypatch)
    secret = "whsec_test"
    with sqlite3.connect(path) as db:
        db.execute(
            """INSERT INTO developer_webhooks
               (id,user_id,url,events_json,secret_ciphertext,status,created_at)
               VALUES (?,?,?,?,?,'active',?)""",
            (
                "wh_test",
                1,
                "https://example.com/hook",
                json.dumps(["task.completed"]),
                webhooks._encrypt(secret),
                webhooks._now(),
            ),
        )
        db.commit()

    captured = {}

    class Response:
        status_code = 204

        def raise_for_status(self):
            return None

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(webhooks.httpx, "post", fake_post)
    webhooks.dispatch_webhook_event(1, "task.completed", {"task_id": "task_1"})

    assert captured["url"] == "https://example.com/hook"
    timestamp = captured["headers"]["X-Amosclaud-Timestamp"]
    assert captured["headers"]["X-Amosclaud-Signature"] == webhooks.signature(
        secret, timestamp, captured["content"]
    )
    with sqlite3.connect(path) as db:
        delivery = db.execute("SELECT status,response_code FROM webhook_deliveries").fetchone()
    assert delivery == ("delivered", 204)
