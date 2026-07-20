from __future__ import annotations

from datetime import datetime, timedelta, timezone

from amoscloud_ai.api.routes import auth, billing


def _database(tmp_path):
    auth.DB_PATH = tmp_path / "billing-test.db"
    db = auth._connect()
    cursor = db.execute(
        "INSERT INTO users(name,email,provider,is_admin,created_at) VALUES (?,?,?,0,?)",
        ("Plan Test", "plans@example.com", "password", datetime.now(timezone.utc).isoformat()),
    )
    db.commit()
    return db, int(cursor.lastrowid)


def test_new_user_has_community_plan(tmp_path):
    db, user_id = _database(tmp_path)
    try:
        entitlement = billing._entitlement(db, user_id)
        assert entitlement["plan"] == "community"
        assert entitlement["source"] == "included"
    finally:
        db.close()


def test_active_manual_license_unlocks_full_package(tmp_path):
    db, user_id = _database(tmp_path)
    try:
        billing._ensure_schema(db)
        db.execute(
            """INSERT INTO billing_license_keys
               (key_hash,label,plan,issued_by_user_id,activated_by_user_id,issued_at,activated_at,expires_at)
               VALUES (?,?, 'full',?,?,?,?,?)""",
            (
                billing._license_hash("AMOS-FULL-TEST-LICENSE-123456"),
                "Test license",
                user_id,
                user_id,
                billing._now(),
                billing._now(),
                (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            ),
        )
        db.commit()
        entitlement = billing._entitlement(db, user_id)
        assert entitlement["plan"] == "full"
        assert entitlement["source"] == "license"
    finally:
        db.close()


def test_expired_license_does_not_unlock_full_package(tmp_path):
    db, user_id = _database(tmp_path)
    try:
        billing._ensure_schema(db)
        db.execute(
            """INSERT INTO billing_license_keys
               (key_hash,label,plan,issued_by_user_id,activated_by_user_id,issued_at,activated_at,expires_at)
               VALUES (?,?, 'full',?,?,?,?,?)""",
            (
                billing._license_hash("AMOS-FULL-EXPIRED-123456"),
                "Expired test",
                user_id,
                user_id,
                billing._now(),
                billing._now(),
                (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            ),
        )
        db.commit()
        assert billing._entitlement(db, user_id)["plan"] == "community"
    finally:
        db.close()
