"""Durable, verified repair knowledge shared by Amosclaud capabilities."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

MAX_LEVEL = 5
_WORD = re.compile(r"[a-z0-9][a-z0-9_.-]+")
_SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{12,}"),
    re.compile(r"amos_(?:live|svc|agent|auto)_[A-Za-z0-9_-]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s]{12,}"
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def memory_database_path() -> Path:
    configured = (
        os.getenv("AMOSCLAUD_MEMORY_DB_PATH", "").strip()
        or os.getenv("AUTH_DB_PATH", "").strip()
        or "data/auth.db"
    )
    return Path(configured)


def connect_memory(path: Path | None = None) -> sqlite3.Connection:
    database = path or memory_database_path()
    database.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(database)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    ensure_memory_schema(db)
    return db


def ensure_memory_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS amosclaud_repair_techniques (
            fingerprint TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            problem_pattern TEXT NOT NULL,
            root_cause TEXT NOT NULL,
            strategy_json TEXT NOT NULL,
            confidence INTEGER NOT NULL CHECK(confidence BETWEEN 0 AND 100),
            source TEXT NOT NULL,
            first_verified_at TEXT NOT NULL,
            last_verified_at TEXT NOT NULL,
            successful_uses INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1))
        );
        CREATE TABLE IF NOT EXISTS amosclaud_technique_targets (
            fingerprint TEXT NOT NULL,
            target_hash TEXT NOT NULL,
            target_label TEXT NOT NULL,
            first_verified_at TEXT NOT NULL,
            PRIMARY KEY(fingerprint, target_hash),
            FOREIGN KEY(fingerprint)
                REFERENCES amosclaud_repair_techniques(fingerprint)
                ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS amosclaud_repair_learning_events (
            event_key TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            target_hash TEXT NOT NULL,
            proof_id TEXT NOT NULL,
            source TEXT NOT NULL,
            was_novel INTEGER NOT NULL CHECK(was_novel IN (0, 1)),
            was_reuse INTEGER NOT NULL CHECK(was_reuse IN (0, 1)),
            was_combined INTEGER NOT NULL CHECK(was_combined IN (0, 1)),
            created_at TEXT NOT NULL,
            FOREIGN KEY(fingerprint)
                REFERENCES amosclaud_repair_techniques(fingerprint)
                ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS amosclaud_capability_profile (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            level INTEGER NOT NULL DEFAULT 1 CHECK(level BETWEEN 1 AND 5),
            unique_techniques INTEGER NOT NULL DEFAULT 0,
            successful_reuses INTEGER NOT NULL DEFAULT 0,
            combined_repairs INTEGER NOT NULL DEFAULT 0,
            last_level_reason TEXT,
            updated_at TEXT NOT NULL
        );
        INSERT OR IGNORE INTO amosclaud_capability_profile(
            singleton_id, level, unique_techniques, successful_reuses,
            combined_repairs, updated_at
        ) VALUES (1, 1, 0, 0, 0, CURRENT_TIMESTAMP);
        """
    )
    db.commit()


def _redact(value: str, limit: int) -> str:
    text = " ".join(str(value).strip().split())
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text[:limit]


def _normalize(value: str) -> str:
    return " ".join(_WORD.findall(value.lower()))


def _tokens(value: str) -> set[str]:
    return {item for item in _WORD.findall(value.lower()) if len(item) > 2}


def _strategy(strategy: Iterable[str]) -> list[str]:
    cleaned = [_redact(item, 500) for item in strategy if str(item).strip()]
    if not cleaned:
        raise ValueError("A verified technique requires at least one repair step")
    return cleaned[:20]


def technique_fingerprint(
    category: str,
    problem_pattern: str,
    root_cause: str,
    strategy: Iterable[str],
) -> str:
    material = "\n".join(
        (
            _normalize(category),
            _normalize(problem_pattern),
            _normalize(root_cause),
            *(_normalize(item) for item in strategy),
        )
    )
    if len(material.replace("\n", "")) < 12:
        raise ValueError("The repair technique is too vague to store")
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _target_hash(target: str) -> str:
    normalized = _normalize(target)
    if not normalized:
        raise ValueError("A verified repair requires a target")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _proof(evidence: dict[str, Any]) -> tuple[str, list[str]]:
    verdict = str(
        evidence.get("final_verdict")
        or evidence.get("verification_status")
        or ""
    ).upper()
    if verdict not in {"PASS", "PASSED", "SUCCESS", "SUCCEEDED"}:
        raise ValueError("Only successful verification evidence may enter memory")
    if evidence.get("verified") is not True:
        raise ValueError("Memory learning requires verified=true")

    raw_checks = evidence.get("checks") or []
    if not isinstance(raw_checks, list) or not raw_checks:
        raise ValueError("Memory learning requires at least one verification check")
    checks: list[str] = []
    for item in raw_checks:
        if not isinstance(item, dict) or item.get("passed") is not True:
            raise ValueError("Every verification check must pass")
        checks.append(_redact(str(item.get("name") or "verified check"), 200))

    proof_id = _redact(str(evidence.get("proof_id") or ""), 200)
    if len(proof_id) < 4:
        raise ValueError("Memory learning requires a stable proof_id")
    return proof_id, checks


def capability_profile(db: sqlite3.Connection) -> dict[str, Any]:
    ensure_memory_schema(db)
    row = db.execute(
        "SELECT * FROM amosclaud_capability_profile WHERE singleton_id=1"
    ).fetchone()
    assert row is not None
    result = dict(row)
    result["max_level"] = MAX_LEVEL
    return result


def _eligible_level(unique: int, reuses: int, combined: int) -> int:
    eligible = min(MAX_LEVEL, 1 + unique)
    if eligible == MAX_LEVEL and (reuses < 1 or combined < 1):
        return MAX_LEVEL - 1
    return eligible


def record_verified_technique(
    db: sqlite3.Connection,
    *,
    category: str,
    problem_pattern: str,
    root_cause: str,
    strategy: Iterable[str],
    target: str,
    evidence: dict[str, Any],
    source: str,
    confidence: int = 100,
    combined_fingerprints: Iterable[str] = (),
) -> dict[str, Any]:
    """Store one clean technique after every required verification check passes."""

    ensure_memory_schema(db)
    clean_strategy = _strategy(strategy)
    fingerprint = technique_fingerprint(
        category,
        problem_pattern,
        root_cause,
        clean_strategy,
    )
    target_hash = _target_hash(target)
    proof_id, checks = _proof(evidence)
    clean_source = _redact(source or "amosclaud", 120)
    event_key = hashlib.sha256(
        f"{fingerprint}:{target_hash}:{proof_id}:{clean_source}".encode("utf-8")
    ).hexdigest()

    if db.execute(
        "SELECT 1 FROM amosclaud_repair_learning_events WHERE event_key=?",
        (event_key,),
    ).fetchone():
        return {
            "stored": False,
            "duplicate_event": True,
            "fingerprint": fingerprint,
            "profile": capability_profile(db),
        }

    existing = db.execute(
        "SELECT fingerprint FROM amosclaud_repair_techniques WHERE fingerprint=?",
        (fingerprint,),
    ).fetchone()
    novel = existing is None
    timestamp = utc_now()
    confidence = max(0, min(int(confidence), 100))

    if novel:
        db.execute(
            """INSERT INTO amosclaud_repair_techniques(
                   fingerprint,category,problem_pattern,root_cause,strategy_json,
                   confidence,source,first_verified_at,last_verified_at
               ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                fingerprint,
                _redact(category, 120),
                _redact(problem_pattern, 1000),
                _redact(root_cause, 1000),
                json.dumps(clean_strategy),
                confidence,
                clean_source,
                timestamp,
                timestamp,
            ),
        )
    else:
        db.execute(
            """UPDATE amosclaud_repair_techniques
               SET successful_uses=successful_uses+1,
                   confidence=MAX(confidence,?),last_verified_at=?
               WHERE fingerprint=?""",
            (confidence, timestamp, fingerprint),
        )

    new_target = not db.execute(
        """SELECT 1 FROM amosclaud_technique_targets
           WHERE fingerprint=? AND target_hash=?""",
        (fingerprint, target_hash),
    ).fetchone()
    if new_target:
        db.execute(
            """INSERT INTO amosclaud_technique_targets(
                   fingerprint,target_hash,target_label,first_verified_at
               ) VALUES (?,?,?,?)""",
            (fingerprint, target_hash, _redact(target, 500), timestamp),
        )
    reused = not novel and new_target

    combined = sorted(set(combined_fingerprints))
    verified_combination = False
    if len(combined) >= 2:
        placeholders = ",".join("?" for _ in combined)
        count = db.execute(
            f"""SELECT COUNT(*) AS count FROM amosclaud_repair_techniques
                WHERE fingerprint IN ({placeholders}) AND active=1""",
            combined,
        ).fetchone()["count"]
        verified_combination = int(count) == len(combined)

    profile = capability_profile(db)
    unique = int(profile["unique_techniques"]) + int(novel)
    reuses = int(profile["successful_reuses"]) + int(reused)
    combinations = int(profile["combined_repairs"]) + int(verified_combination)
    current_level = int(profile["level"])
    eligible = _eligible_level(unique, reuses, combinations)
    next_level = min(current_level + 1, eligible)
    level_changed = next_level > current_level
    reason = None
    if level_changed:
        reason = (
            f"Verified new capability {fingerprint[:12]}"
            if novel
            else f"Verified memory reuse {fingerprint[:12]}"
        )

    db.execute(
        """UPDATE amosclaud_capability_profile
           SET level=?,unique_techniques=?,successful_reuses=?,
               combined_repairs=?,last_level_reason=COALESCE(?,last_level_reason),
               updated_at=? WHERE singleton_id=1""",
        (next_level, unique, reuses, combinations, reason, timestamp),
    )
    db.execute(
        """INSERT INTO amosclaud_repair_learning_events(
               event_key,fingerprint,target_hash,proof_id,source,was_novel,
               was_reuse,was_combined,created_at
           ) VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            event_key,
            fingerprint,
            target_hash,
            proof_id,
            clean_source,
            int(novel),
            int(reused),
            int(verified_combination),
            timestamp,
        ),
    )
    db.commit()
    return {
        "stored": True,
        "duplicate_event": False,
        "fingerprint": fingerprint,
        "novel": novel,
        "reused": reused,
        "combined": verified_combination,
        "checks": checks,
        "level_changed": level_changed,
        "profile": capability_profile(db),
    }


def search_verified_techniques(
    db: sqlite3.Connection,
    query: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    ensure_memory_schema(db)
    query_terms = _tokens(query)
    if not query_terms:
        return []
    rows = db.execute(
        """SELECT * FROM amosclaud_repair_techniques
           WHERE active=1 ORDER BY successful_uses DESC,last_verified_at DESC"""
    ).fetchall()
    matches: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        item = dict(row)
        strategy = json.loads(item["strategy_json"])
        material = " ".join(
            (
                item["category"],
                item["problem_pattern"],
                item["root_cause"],
                " ".join(strategy),
            )
        )
        candidate_terms = _tokens(material)
        overlap = query_terms & candidate_terms
        if not overlap:
            continue
        score = len(overlap) / max(1, len(query_terms | candidate_terms))
        score += min(int(item["successful_uses"]), 10) / 100
        matches.append(
            (
                score,
                {
                    "fingerprint": item["fingerprint"],
                    "category": item["category"],
                    "problem_pattern": item["problem_pattern"],
                    "root_cause": item["root_cause"],
                    "strategy": strategy,
                    "confidence": int(item["confidence"]),
                    "successful_uses": int(item["successful_uses"]),
                    "score": round(score, 4),
                },
            )
        )
    matches.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in matches[: max(1, min(limit, 10))]]


def memory_injection(matches: Iterable[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, item in enumerate(matches, 1):
        steps = "\n".join(f"  {number}. {step}" for number, step in enumerate(item["strategy"], 1))
        blocks.append(
            f"Technique {index} ({item['fingerprint'][:12]}, "
            f"confidence {item['confidence']}%):\n"
            f"Problem pattern: {item['problem_pattern']}\n"
            f"Root cause: {item['root_cause']}\n"
            f"Verified strategy:\n{steps}"
        )
    if not blocks:
        return "No verified memory technique matched this failure."
    return (
        "Use these as repair guidance only. Re-diagnose the current repository, "
        "apply clean code, and run all current verification checks.\n\n"
        + "\n\n".join(blocks)
    )
