from __future__ import annotations

from datetime import datetime, timezone

from amoscloud_ai import agent_tokens
from amoscloud_ai.api.routes import auth


def _user(tmp_path):
    auth.DB_PATH = tmp_path / "tokens.db"
    db = auth._connect()
    cursor = db.execute(
        "INSERT INTO users(name,email,provider,is_admin,created_at) VALUES (?,?,?,0,?)",
        ("Token User", "tokens@example.com", "password", datetime.now(timezone.utc).isoformat()),
    )
    db.commit()
    return db, int(cursor.lastrowid)


def test_api_key_is_stored_as_hash(tmp_path):
    db, user_id = _user(tmp_path)
    try:
        key_id, raw, prefix = agent_tokens.issue_api_key(db, user_id, "Test")
        row = db.execute("SELECT key_hash,key_prefix FROM agent_api_keys WHERE id=?", (key_id,)).fetchone()
        assert raw.startswith("amos_live_")
        assert row["key_hash"] == agent_tokens.key_hash(raw)
        assert raw not in row["key_hash"]
        assert row["key_prefix"] == prefix
    finally:
        db.close()


def test_credit_and_atomic_debit(tmp_path):
    db, user_id = _user(tmp_path)
    try:
        assert agent_tokens.credit_tokens(db, user_id, 10, reason="test", reference="purchase-1")
        assert not agent_tokens.credit_tokens(db, user_id, 10, reason="test", reference="purchase-1")
        assert agent_tokens.debit_tokens(db, user_id, 3, reference="request-1")
        assert db.execute("SELECT balance FROM agent_token_wallets WHERE user_id=?", (user_id,)).fetchone()[0] == 7
        assert not agent_tokens.debit_tokens(db, user_id, 8, reference="request-2")
    finally:
        db.close()
