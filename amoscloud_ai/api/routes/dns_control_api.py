"""Authenticated independent Amosclaud DNS management API."""
from __future__ import annotations

import json
from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import _connect, get_user_from_session
from amoscloud_ai.dns_control_plane import AmosclaudDNSJudge, DNSControlError, DNSRecord, DNSZone

router = APIRouter(prefix="/dns", tags=["amosclaud-dns"])


class RecordRequest(BaseModel):
    name: str = Field(min_length=1, max_length=253)
    type: str
    value: str = Field(min_length=1, max_length=4096)
    ttl: int = Field(default=300, ge=30, le=86400)
    priority: int | None = Field(default=None, ge=0, le=65535)


class ZoneRequest(BaseModel):
    domain: str = Field(min_length=3, max_length=253)


def _user(token: str | None):
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to manage DNS with Amosclaud")
    return user


def _schema() -> None:
    with _connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS amosclaud_dns_zones (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            domain TEXT NOT NULL, serial INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL, UNIQUE(user_id, domain),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)""")
        db.execute("""CREATE TABLE IF NOT EXISTS amosclaud_dns_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, zone_id INTEGER NOT NULL,
            name TEXT NOT NULL, type TEXT NOT NULL, value TEXT NOT NULL,
            ttl INTEGER NOT NULL, priority INTEGER,
            UNIQUE(zone_id,name,type,value),
            FOREIGN KEY(zone_id) REFERENCES amosclaud_dns_zones(id) ON DELETE CASCADE)""")
        db.commit()


def _zone(db, user_id: int, domain: str):
    return db.execute("SELECT * FROM amosclaud_dns_zones WHERE user_id=? AND domain=?", (user_id, domain)).fetchone()


def _read_zone(db, row) -> DNSZone:
    rows = db.execute("SELECT name,type,value,ttl,priority FROM amosclaud_dns_records WHERE zone_id=? ORDER BY id", (row["id"],)).fetchall()
    records = [DNSRecord(r["name"], r["type"], r["value"], r["ttl"], r["priority"]) for r in rows]
    return DNSZone(row["domain"], records, row["serial"])


@router.post("/zones")
def create_zone(body: ZoneRequest, amos_session: str | None = Cookie(default=None)) -> dict:
    user = _user(amos_session); _schema()
    try: zone = DNSZone(body.domain)
    except DNSControlError as exc: raise HTTPException(422, str(exc)) from exc
    with _connect() as db:
        existing = _zone(db, int(user["id"]), zone.domain)
        if existing: return {"zone": _read_zone(db, existing).snapshot(), "created": False}
        now = zone.updated_at.isoformat()
        db.execute("INSERT INTO amosclaud_dns_zones(user_id,domain,serial,updated_at) VALUES(?,?,?,?)", (int(user["id"]), zone.domain, zone.serial, now))
        db.commit()
        row = _zone(db, int(user["id"]), zone.domain)
        return {"zone": _read_zone(db, row).snapshot(), "created": True}


@router.get("/zones")
def list_zones(amos_session: str | None = Cookie(default=None)) -> list[dict]:
    user = _user(amos_session); _schema()
    with _connect() as db:
        rows = db.execute("SELECT * FROM amosclaud_dns_zones WHERE user_id=? ORDER BY domain", (int(user["id"]),)).fetchall()
        return [ _read_zone(db, row).snapshot() for row in rows ]


@router.get("/zones/{domain}")
def get_zone(domain: str, amos_session: str | None = Cookie(default=None)) -> dict:
    user = _user(amos_session); _schema()
    with _connect() as db:
        row = _zone(db, int(user["id"]), domain.strip().lower().rstrip("."))
        if not row: raise HTTPException(404, "DNS zone not found")
        return _read_zone(db, row).snapshot()


@router.post("/zones/{domain}/records")
def upsert_record(domain: str, body: RecordRequest, amos_session: str | None = Cookie(default=None)) -> dict:
    user = _user(amos_session); _schema()
    with _connect() as db:
        row = _zone(db, int(user["id"]), domain.strip().lower().rstrip("."))
        if not row: raise HTTPException(404, "DNS zone not found")
        zone = _read_zone(db, row)
        try: record = zone.upsert(DNSRecord(body.name, body.type, body.value, body.ttl, body.priority))
        except DNSControlError as exc: raise HTTPException(422, str(exc)) from exc
        db.execute("DELETE FROM amosclaud_dns_records WHERE zone_id=? AND name=? AND type=? AND value=?", (row["id"], record.name, record.type, record.value))
        db.execute("INSERT INTO amosclaud_dns_records(zone_id,name,type,value,ttl,priority) VALUES(?,?,?,?,?,?)", (row["id"], record.name, record.type, record.value, record.ttl, record.priority))
        db.execute("UPDATE amosclaud_dns_zones SET serial=?,updated_at=? WHERE id=?", (zone.serial, zone.updated_at.isoformat(), row["id"]))
        db.commit()
        return {"record": record.__dict__, "zone": zone.snapshot(), "pending_external_reconciliation": True}


@router.delete("/zones/{domain}/records")
def delete_record(domain: str, name: str, type: str, value: str | None = None, amos_session: str | None = Cookie(default=None)) -> dict:
    user = _user(amos_session); _schema()
    with _connect() as db:
        row = _zone(db, int(user["id"]), domain.strip().lower().rstrip("."))
        if not row: raise HTTPException(404, "DNS zone not found")
        zone = _read_zone(db, row)
        try: removed = zone.delete(name, type, value)
        except DNSControlError as exc: raise HTTPException(422, str(exc)) from exc
        db.execute("DELETE FROM amosclaud_dns_records WHERE zone_id=? AND name=? AND type=?" + (" AND value=?" if value else ""), ((row["id"], name.strip().lower().rstrip("."), type, value) if value else (row["id"], name.strip().lower().rstrip("."), type)))
        if removed:
            db.execute("UPDATE amosclaud_dns_zones SET serial=?,updated_at=? WHERE id=?", (zone.serial, zone.updated_at.isoformat(), row["id"]))
        db.commit()
        return {"removed": removed, "zone": zone.snapshot(), "pending_external_reconciliation": bool(removed)}


@router.post("/zones/{domain}/judge")
def judge_zone(domain: str, amos_session: str | None = Cookie(default=None)) -> dict:
    user = _user(amos_session); _schema()
    with _connect() as db:
        row = _zone(db, int(user["id"]), domain.strip().lower().rstrip("."))
        if not row: raise HTTPException(404, "DNS zone not found")
        zone = _read_zone(db, row)
    result = AmosclaudDNSJudge().judge(zone)
    return {"judge": {"passed": result.passed, "score": result.score, "reasons": list(result.reasons), "checks": result.checks}, "zone": zone.snapshot(), "authority": "amosclaud-action"}


@router.get("/zones/{domain}/export")
def export_zone(domain: str, amos_session: str | None = Cookie(default=None)) -> dict:
    """Return provider-neutral desired state for an authoritative DNS adapter."""
    return get_zone(domain, amos_session)


__all__ = ["router"]
