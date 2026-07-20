"""Amos Mail: internal @amosclaud.com messaging plus optional internet delivery."""

from __future__ import annotations

import os
import re
import smtplib
import sqlite3
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import get_user_from_session

router = APIRouter(prefix="/mail", tags=["amos-mail"])
DB_PATH = Path(os.getenv("AUTH_DB_PATH", "data/auth.db"))
MAIL_DOMAIN = os.getenv("AMOS_MAIL_DOMAIN", "amosclaud.com").strip().lower()
USERNAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{1,30}[a-z0-9])?$")


class AddressRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)


class ComposeRequest(BaseModel):
    to: str = Field(..., min_length=3, max_length=254)
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=100_000)


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS mailboxes (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            address TEXT NOT NULL UNIQUE COLLATE NOCASE,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS mail_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_user_id INTEGER NOT NULL,
            sender_address TEXT NOT NULL,
            recipient_user_id INTEGER,
            recipient_address TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            folder TEXT NOT NULL CHECK(folder IN ('inbox','sent')),
            delivery TEXT NOT NULL CHECK(delivery IN ('internal','internet')),
            status TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(sender_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(recipient_user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_mail_recipient ON mail_messages(recipient_user_id, folder, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_mail_sender ON mail_messages(sender_user_id, folder, created_at DESC);
        """
    )
    db.commit()
    return db


def _user(session: str | None):
    user = get_user_from_session(session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to Amosclaud first")
    return user


def _normalise_username(value: str) -> str:
    username = value.strip().lower()
    if not USERNAME_PATTERN.fullmatch(username):
        raise HTTPException(status_code=422, detail="Use 3-32 lowercase letters, numbers, dots, dashes, or underscores")
    return username


def _send_internet(sender: str, recipient: str, subject: str, body: str) -> None:
    host = os.getenv("MAIL_SMTP_HOST") or os.getenv("SMTP_HOST")
    if not host:
        raise HTTPException(status_code=503, detail="Internet email delivery is not configured")
    port = int(os.getenv("MAIL_SMTP_PORT") or os.getenv("SMTP_PORT", "587"))
    username = os.getenv("MAIL_SMTP_USERNAME") or os.getenv("SMTP_USERNAME")
    password = os.getenv("MAIL_SMTP_PASSWORD") or os.getenv("SMTP_PASSWORD")
    use_tls = (os.getenv("MAIL_SMTP_TLS") or os.getenv("SMTP_TLS", "true")).lower() == "true"
    envelope_from = os.getenv("MAIL_SMTP_FROM", sender)

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if use_tls:
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message, from_addr=envelope_from, to_addrs=[recipient])
    except (smtplib.SMTPException, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"Internet email delivery failed: {exc}") from exc


@router.get("/me")
def mailbox_me(amos_session: str | None = Cookie(default=None)) -> dict:
    user = _user(amos_session)
    with _connect() as db:
        mailbox = db.execute("SELECT username,address,created_at FROM mailboxes WHERE user_id=?", (user["id"],)).fetchone()
    return {"domain": MAIL_DOMAIN, "mailbox": dict(mailbox) if mailbox else None}


@router.post("/address", status_code=201)
def create_address(body: AddressRequest, amos_session: str | None = Cookie(default=None)) -> dict:
    user = _user(amos_session)
    username = _normalise_username(body.username)
    address = f"{username}@{MAIL_DOMAIN}"
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as db:
        current = db.execute("SELECT address FROM mailboxes WHERE user_id=?", (user["id"],)).fetchone()
        if current:
            raise HTTPException(status_code=409, detail=f"Your Amos Mail address is already {current['address']}")
        try:
            db.execute("INSERT INTO mailboxes(user_id,username,address,created_at) VALUES (?,?,?,?)", (user["id"], username, address, now))
            db.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="That Amos Mail username is already taken") from exc
    return {"address": address}


@router.get("/messages")
def list_messages(folder: str = "inbox", amos_session: str | None = Cookie(default=None)) -> list[dict]:
    user = _user(amos_session)
    if folder not in {"inbox", "sent"}:
        raise HTTPException(status_code=422, detail="Folder must be inbox or sent")
    field = "recipient_user_id" if folder == "inbox" else "sender_user_id"
    with _connect() as db:
        rows = db.execute(
            f"SELECT id,sender_address,recipient_address,subject,body,delivery,status,is_read,created_at FROM mail_messages WHERE {field}=? AND folder=? ORDER BY id DESC LIMIT 200",
            (user["id"], folder),
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/send", status_code=202)
def send_message(body: ComposeRequest, amos_session: str | None = Cookie(default=None)) -> dict:
    user = _user(amos_session)
    recipient = body.to.strip().lower()
    if "@" not in recipient:
        recipient = f"{recipient}@{MAIL_DOMAIN}"
    now = datetime.now(timezone.utc).isoformat()

    with _connect() as db:
        mailbox = db.execute("SELECT address FROM mailboxes WHERE user_id=?", (user["id"],)).fetchone()
        if not mailbox:
            raise HTTPException(status_code=409, detail=f"Create your @{MAIL_DOMAIN} address first")
        sender = mailbox["address"]
        internal = recipient.endswith(f"@{MAIL_DOMAIN}")
        recipient_box = db.execute("SELECT user_id FROM mailboxes WHERE address=?", (recipient,)).fetchone() if internal else None
        if internal and not recipient_box:
            raise HTTPException(status_code=404, detail="That Amos Mail address does not exist")

        delivery = "internal" if internal else "internet"
        status = "delivered" if internal else "queued"
        db.execute(
            "INSERT INTO mail_messages(sender_user_id,sender_address,recipient_user_id,recipient_address,subject,body,folder,delivery,status,is_read,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (user["id"], sender, recipient_box["user_id"] if recipient_box else None, recipient, body.subject.strip(), body.body, "sent", delivery, status, 1, now),
        )
        if internal:
            db.execute(
                "INSERT INTO mail_messages(sender_user_id,sender_address,recipient_user_id,recipient_address,subject,body,folder,delivery,status,is_read,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (user["id"], sender, recipient_box["user_id"], recipient, body.subject.strip(), body.body, "inbox", delivery, "delivered", 0, now),
            )
            db.commit()
            return {"status": "delivered", "delivery": "internal"}
        db.commit()

    _send_internet(sender, recipient, body.subject.strip(), body.body)
    with _connect() as db:
        db.execute("UPDATE mail_messages SET status='sent' WHERE sender_user_id=? AND recipient_address=? AND created_at=? AND folder='sent'", (user["id"], recipient, now))
        db.commit()
    return {"status": "sent", "delivery": "internet"}


@router.post("/messages/{message_id}/read", status_code=204)
def mark_read(message_id: int, amos_session: str | None = Cookie(default=None)) -> None:
    user = _user(amos_session)
    with _connect() as db:
        db.execute("UPDATE mail_messages SET is_read=1 WHERE id=? AND recipient_user_id=? AND folder='inbox'", (message_id, user["id"]))
        db.commit()
