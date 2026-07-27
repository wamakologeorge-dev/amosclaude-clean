"""Durable Amosclaud feature flags with deterministic, scoped evaluation.

Flags are evaluated in this order: workspace override, user override, tier
override, global state, deterministic rollout. This service is independent of
any external vendor and can later be backed by Unleash or PostHog through a
plugin without changing callers.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from amoscloud_ai.api.routes import auth, billing

_FLAG_KEY = re.compile(r"^[a-z][a-z0-9_.-]{2,119}$")
_TARGET_TYPES = {"user", "workspace", "tier"}


class FeatureFlagError(RuntimeError):
    pass


@dataclass(frozen=True)
class FlagDefinition:
    key: str
    name: str
    description: str
    default_enabled: bool = False
    rollout_percentage: int = 0
    required_tiers: tuple[str, ...] = ()
    owner_plugin: str = "core"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def connect() -> sqlite3.Connection:
    db = auth._connect()
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def ensure_schema(db: sqlite3.Connection, *, commit: bool = True) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS feature_flags (
            key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
            rollout_percentage INTEGER NOT NULL DEFAULT 0
                CHECK(rollout_percentage BETWEEN 0 AND 100),
            required_tiers_json TEXT NOT NULL DEFAULT '[]',
            owner_plugin TEXT NOT NULL DEFAULT 'core',
            archived_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS feature_flag_targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flag_key TEXT NOT NULL,
            target_type TEXT NOT NULL CHECK(target_type IN ('user','workspace','tier')),
            target_value TEXT NOT NULL,
            enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(flag_key,target_type,target_value),
            FOREIGN KEY(flag_key) REFERENCES feature_flags(key) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_feature_flag_targets_lookup
            ON feature_flag_targets(flag_key,target_type,target_value);

        CREATE TABLE IF NOT EXISTS feature_flag_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_user_id INTEGER,
            action TEXT NOT NULL,
            flag_key TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_feature_flag_audit_flag
            ON feature_flag_audit(flag_key,created_at DESC);
        """
    )
    if commit:
        db.commit()


def validate_key(key: str) -> str:
    cleaned = str(key or "").strip().lower()
    if not _FLAG_KEY.fullmatch(cleaned):
        raise FeatureFlagError(
            "Feature flag keys must start with a letter and contain only lowercase letters, numbers, dots, dashes, or underscores"
        )
    return cleaned


def register_definitions(definitions: Iterable[FlagDefinition]) -> None:
    now = _now()
    with connect() as db:
        ensure_schema(db, commit=False)
        for definition in definitions:
            key = validate_key(definition.key)
            rollout = max(0, min(int(definition.rollout_percentage), 100))
            tiers = sorted({str(item).strip().lower() for item in definition.required_tiers if str(item).strip()})
            db.execute(
                """INSERT INTO feature_flags(
                       key,name,description,enabled,rollout_percentage,
                       required_tiers_json,owner_plugin,created_at,updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                       name=excluded.name,
                       description=excluded.description,
                       owner_plugin=excluded.owner_plugin,
                       updated_at=excluded.updated_at""",
                (
                    key,
                    definition.name.strip()[:160],
                    definition.description.strip()[:2_000],
                    int(definition.default_enabled),
                    rollout,
                    _json(tiers),
                    definition.owner_plugin.strip()[:120] or "core",
                    now,
                    now,
                ),
            )
        db.commit()


def current_tier(db: sqlite3.Connection, user_id: int | None) -> str:
    if user_id is None:
        return "anonymous"
    try:
        entitlement = billing._entitlement(db, int(user_id))
        return str(entitlement.get("plan") or "community").strip().lower()
    except Exception:
        return "community"


def _bucket(key: str, subject: str) -> int:
    digest = hashlib.sha256(f"{key}:{subject}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 100


def _override(
    db: sqlite3.Connection,
    key: str,
    target_type: str,
    target_value: str | int | None,
) -> bool | None:
    if target_value is None:
        return None
    row = db.execute(
        """SELECT enabled FROM feature_flag_targets
           WHERE flag_key=? AND target_type=? AND target_value=?""",
        (key, target_type, str(target_value)),
    ).fetchone()
    return bool(row["enabled"]) if row else None


def evaluate(
    key: str,
    *,
    user_id: int | None = None,
    workspace_id: str | None = None,
    tier: str | None = None,
    db: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    flag_key = validate_key(key)
    owns_db = db is None
    connection = db or connect()
    try:
        ensure_schema(connection, commit=False)
        row = connection.execute(
            "SELECT * FROM feature_flags WHERE key=? AND archived_at IS NULL",
            (flag_key,),
        ).fetchone()
        if not row:
            return {
                "key": flag_key,
                "enabled": False,
                "reason": "undefined",
                "source": "safe_default",
            }

        resolved_tier = (tier or current_tier(connection, user_id)).strip().lower()
        checks = (
            ("workspace", workspace_id),
            ("user", user_id),
            ("tier", resolved_tier),
        )
        for target_type, target_value in checks:
            value = _override(connection, flag_key, target_type, target_value)
            if value is not None:
                return {
                    "key": flag_key,
                    "enabled": value,
                    "reason": f"explicit_{target_type}_override",
                    "source": target_type,
                    "tier": resolved_tier,
                }

        required_tiers = set(_loads(row["required_tiers_json"], []))
        if required_tiers and resolved_tier not in required_tiers:
            return {
                "key": flag_key,
                "enabled": False,
                "reason": "tier_not_eligible",
                "source": "tier_policy",
                "tier": resolved_tier,
                "required_tiers": sorted(required_tiers),
            }

        if not bool(row["enabled"]):
            return {
                "key": flag_key,
                "enabled": False,
                "reason": "globally_disabled",
                "source": "global",
                "tier": resolved_tier,
            }

        rollout = int(row["rollout_percentage"])
        if rollout >= 100:
            enabled = True
            bucket = None
        elif rollout <= 0:
            enabled = False
            bucket = None
        else:
            subject = workspace_id or (f"user:{user_id}" if user_id is not None else "anonymous")
            bucket = _bucket(flag_key, subject)
            enabled = bucket < rollout
        return {
            "key": flag_key,
            "enabled": enabled,
            "reason": "rollout_match" if enabled else "rollout_excluded",
            "source": "deterministic_rollout",
            "tier": resolved_tier,
            "rollout_percentage": rollout,
            "bucket": bucket,
        }
    finally:
        if owns_db:
            connection.close()


def is_enabled(
    key: str,
    *,
    user_id: int | None = None,
    workspace_id: str | None = None,
    tier: str | None = None,
) -> bool:
    return bool(
        evaluate(
            key,
            user_id=user_id,
            workspace_id=workspace_id,
            tier=tier,
        )["enabled"]
    )


def flag_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["required_tiers"] = _loads(item.pop("required_tiers_json"), [])
    return item


def list_flags(*, include_archived: bool = False) -> list[dict[str, Any]]:
    with connect() as db:
        ensure_schema(db)
        where = "" if include_archived else "WHERE archived_at IS NULL"
        rows = db.execute(
            f"SELECT * FROM feature_flags {where} ORDER BY key"
        ).fetchall()
        results = []
        for row in rows:
            item = flag_dict(row)
            item["targets"] = [
                {
                    "id": target["id"],
                    "target_type": target["target_type"],
                    "target_value": target["target_value"],
                    "enabled": bool(target["enabled"]),
                    "created_at": target["created_at"],
                    "updated_at": target["updated_at"],
                }
                for target in db.execute(
                    """SELECT * FROM feature_flag_targets
                       WHERE flag_key=? ORDER BY target_type,target_value""",
                    (row["key"],),
                ).fetchall()
            ]
            results.append(item)
        return results


def upsert_flag(
    *,
    key: str,
    name: str,
    description: str,
    enabled: bool,
    rollout_percentage: int,
    required_tiers: list[str],
    owner_plugin: str,
    actor_user_id: int,
) -> dict[str, Any]:
    flag_key = validate_key(key)
    now = _now()
    tiers = sorted({item.strip().lower() for item in required_tiers if item.strip()})
    with connect() as db:
        ensure_schema(db, commit=False)
        db.execute(
            """INSERT INTO feature_flags(
                   key,name,description,enabled,rollout_percentage,
                   required_tiers_json,owner_plugin,created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET
                   name=excluded.name,
                   description=excluded.description,
                   enabled=excluded.enabled,
                   rollout_percentage=excluded.rollout_percentage,
                   required_tiers_json=excluded.required_tiers_json,
                   owner_plugin=excluded.owner_plugin,
                   archived_at=NULL,
                   updated_at=excluded.updated_at""",
            (
                flag_key,
                name.strip()[:160],
                description.strip()[:2_000],
                int(enabled),
                max(0, min(int(rollout_percentage), 100)),
                _json(tiers),
                owner_plugin.strip()[:120] or "core",
                now,
                now,
            ),
        )
        db.execute(
            """INSERT INTO feature_flag_audit(
                   actor_user_id,action,flag_key,details_json,created_at
               ) VALUES (?,?,?,?,?)""",
            (
                actor_user_id,
                "upsert_flag",
                flag_key,
                _json(
                    {
                        "enabled": enabled,
                        "rollout_percentage": rollout_percentage,
                        "required_tiers": tiers,
                        "owner_plugin": owner_plugin,
                    }
                ),
                now,
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM feature_flags WHERE key=?", (flag_key,)).fetchone()
    if not row:
        raise RuntimeError("Feature flag was not persisted")
    return flag_dict(row)


def set_target(
    *,
    key: str,
    target_type: str,
    target_value: str,
    enabled: bool,
    actor_user_id: int,
) -> dict[str, Any]:
    flag_key = validate_key(key)
    target = target_type.strip().lower()
    value = target_value.strip()
    if target not in _TARGET_TYPES:
        raise FeatureFlagError("Target type must be user, workspace, or tier")
    if not value or len(value) > 300:
        raise FeatureFlagError("Target value is required and must be at most 300 characters")
    if target == "user" and not value.isdigit():
        raise FeatureFlagError("User targets must use a numeric Amosclaud user ID")
    now = _now()
    with connect() as db:
        ensure_schema(db, commit=False)
        if not db.execute("SELECT 1 FROM feature_flags WHERE key=?", (flag_key,)).fetchone():
            raise FeatureFlagError("Feature flag does not exist")
        db.execute(
            """INSERT INTO feature_flag_targets(
                   flag_key,target_type,target_value,enabled,created_at,updated_at
               ) VALUES (?,?,?,?,?,?)
               ON CONFLICT(flag_key,target_type,target_value) DO UPDATE SET
                   enabled=excluded.enabled,updated_at=excluded.updated_at""",
            (flag_key, target, value, int(enabled), now, now),
        )
        db.execute(
            """INSERT INTO feature_flag_audit(
                   actor_user_id,action,flag_key,details_json,created_at
               ) VALUES (?,?,?,?,?)""",
            (
                actor_user_id,
                "set_target",
                flag_key,
                _json({"target_type": target, "target_value": value, "enabled": enabled}),
                now,
            ),
        )
        db.commit()
        row = db.execute(
            """SELECT * FROM feature_flag_targets
               WHERE flag_key=? AND target_type=? AND target_value=?""",
            (flag_key, target, value),
        ).fetchone()
    return {
        "id": row["id"],
        "flag_key": row["flag_key"],
        "target_type": row["target_type"],
        "target_value": row["target_value"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def delete_target(target_id: int, *, actor_user_id: int) -> None:
    with connect() as db:
        ensure_schema(db, commit=False)
        row = db.execute(
            "SELECT * FROM feature_flag_targets WHERE id=?",
            (target_id,),
        ).fetchone()
        if not row:
            raise FeatureFlagError("Feature flag target not found")
        db.execute("DELETE FROM feature_flag_targets WHERE id=?", (target_id,))
        db.execute(
            """INSERT INTO feature_flag_audit(
                   actor_user_id,action,flag_key,details_json,created_at
               ) VALUES (?,?,?,?,?)""",
            (
                actor_user_id,
                "delete_target",
                row["flag_key"],
                _json(
                    {
                        "target_type": row["target_type"],
                        "target_value": row["target_value"],
                    }
                ),
                _now(),
            ),
        )
        db.commit()
