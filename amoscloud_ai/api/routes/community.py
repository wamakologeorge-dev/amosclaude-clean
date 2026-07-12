"""Amosclaud developer community APIs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session

router = APIRouter(prefix="/community", tags=["community"])


class CommunityPostCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class CommunityCommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS community_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS community_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(post_id) REFERENCES community_posts(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS community_follows (
            follower_id INTEGER NOT NULL,
            followed_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(follower_id, followed_id),
            CHECK(follower_id != followed_id),
            FOREIGN KEY(follower_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(followed_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS community_blocks (
            blocker_id INTEGER NOT NULL,
            blocked_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(blocker_id, blocked_id),
            CHECK(blocker_id != blocked_id),
            FOREIGN KEY(blocker_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(blocked_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()
    return db


def _current_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _user_or_404(db: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = db.execute("SELECT id,name,email FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row


def _blocked(db: sqlite3.Connection, a: int, b: int) -> bool:
    return bool(
        db.execute(
            "SELECT 1 FROM community_blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)",
            (a, b, b, a),
        ).fetchone()
    )


@router.get("/feed")
def community_feed(
    following_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    user: sqlite3.Row = Depends(_current_user),
) -> list[dict]:
    with _db() as db:
        follow_clause = "AND EXISTS (SELECT 1 FROM community_follows f WHERE f.follower_id=? AND f.followed_id=p.user_id)" if following_only else ""
        params = [user["id"], user["id"], user["id"]]
        if following_only:
            params.append(user["id"])
        params.append(limit)
        rows = db.execute(
            f"""SELECT p.id,p.content,p.created_at,p.updated_at,u.id AS user_id,u.name,u.email,
                       EXISTS(SELECT 1 FROM community_follows f WHERE f.follower_id=? AND f.followed_id=u.id) AS following,
                       (SELECT COUNT(*) FROM community_follows f2 WHERE f2.followed_id=u.id) AS followers,
                       (SELECT COUNT(*) FROM community_comments c WHERE c.post_id=p.id) AS comments
                FROM community_posts p JOIN users u ON u.id=p.user_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM community_blocks b
                    WHERE (b.blocker_id=? AND b.blocked_id=p.user_id)
                       OR (b.blocker_id=p.user_id AND b.blocked_id=?)
                )
                {follow_clause}
                ORDER BY p.created_at DESC LIMIT ?""",
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/posts", status_code=201)
def create_post(body: CommunityPostCreate, user: sqlite3.Row = Depends(_current_user)) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        cursor = db.execute(
            "INSERT INTO community_posts(user_id,content,created_at,updated_at) VALUES (?,?,?,?)",
            (user["id"], body.content.strip(), now, now),
        )
        db.commit()
    return {"id": cursor.lastrowid, "content": body.content.strip(), "created_at": now}


@router.get("/posts/{post_id}/comments")
def list_comments(post_id: int, user: sqlite3.Row = Depends(_current_user)) -> list[dict]:
    with _db() as db:
        post = db.execute("SELECT user_id FROM community_posts WHERE id=?", (post_id,)).fetchone()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if _blocked(db, user["id"], post["user_id"]):
            raise HTTPException(status_code=404, detail="Post not found")
        rows = db.execute(
            """SELECT c.id,c.content,c.created_at,u.id AS user_id,u.name,u.email
               FROM community_comments c JOIN users u ON u.id=c.user_id
               WHERE c.post_id=?
                 AND NOT EXISTS (
                     SELECT 1 FROM community_blocks b
                     WHERE (b.blocker_id=? AND b.blocked_id=c.user_id)
                        OR (b.blocker_id=c.user_id AND b.blocked_id=?)
                 )
               ORDER BY c.created_at ASC""",
            (post_id, user["id"], user["id"]),
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/posts/{post_id}/comments", status_code=201)
def create_comment(post_id: int, body: CommunityCommentCreate, user: sqlite3.Row = Depends(_current_user)) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        post = db.execute("SELECT user_id FROM community_posts WHERE id=?", (post_id,)).fetchone()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if _blocked(db, user["id"], post["user_id"]):
            raise HTTPException(status_code=403, detail="You cannot comment on this post")
        cursor = db.execute(
            "INSERT INTO community_comments(post_id,user_id,content,created_at) VALUES (?,?,?,?)",
            (post_id, user["id"], body.content.strip(), now),
        )
        db.commit()
    return {"id": cursor.lastrowid, "post_id": post_id, "content": body.content.strip(), "created_at": now}


@router.post("/users/{user_id}/follow", status_code=204)
def follow_user(user_id: int, user: sqlite3.Row = Depends(_current_user)) -> None:
    if user_id == user["id"]:
        raise HTTPException(status_code=422, detail="You cannot follow yourself")
    with _db() as db:
        _user_or_404(db, user_id)
        if _blocked(db, user["id"], user_id):
            raise HTTPException(status_code=403, detail="Following is unavailable")
        db.execute(
            "INSERT OR IGNORE INTO community_follows(follower_id,followed_id,created_at) VALUES (?,?,?)",
            (user["id"], user_id, datetime.now(timezone.utc).isoformat()),
        )
        db.commit()


@router.delete("/users/{user_id}/follow", status_code=204)
def unfollow_user(user_id: int, user: sqlite3.Row = Depends(_current_user)) -> None:
    with _db() as db:
        db.execute("DELETE FROM community_follows WHERE follower_id=? AND followed_id=?", (user["id"], user_id))
        db.commit()


@router.post("/users/{user_id}/block", status_code=204)
def block_user(user_id: int, user: sqlite3.Row = Depends(_current_user)) -> None:
    if user_id == user["id"]:
        raise HTTPException(status_code=422, detail="You cannot block yourself")
    with _db() as db:
        _user_or_404(db, user_id)
        db.execute(
            "INSERT OR IGNORE INTO community_blocks(blocker_id,blocked_id,created_at) VALUES (?,?,?)",
            (user["id"], user_id, datetime.now(timezone.utc).isoformat()),
        )
        db.execute(
            "DELETE FROM community_follows WHERE (follower_id=? AND followed_id=?) OR (follower_id=? AND followed_id=?)",
            (user["id"], user_id, user_id, user["id"]),
        )
        db.commit()


@router.delete("/users/{user_id}/block", status_code=204)
def unblock_user(user_id: int, user: sqlite3.Row = Depends(_current_user)) -> None:
    with _db() as db:
        db.execute("DELETE FROM community_blocks WHERE blocker_id=? AND blocked_id=?", (user["id"], user_id))
        db.commit()


@router.get("/blocked")
def blocked_users(user: sqlite3.Row = Depends(_current_user)) -> list[dict]:
    with _db() as db:
        rows = db.execute(
            """SELECT u.id,u.name,u.email,b.created_at
               FROM community_blocks b JOIN users u ON u.id=b.blocked_id
               WHERE b.blocker_id=? ORDER BY b.created_at DESC""",
            (user["id"],),
        ).fetchall()
    return [dict(row) for row in rows]
