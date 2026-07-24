"""Database operations for API-key manager records."""
from datetime import datetime

from sqlalchemy.orm import Session

from . import models, schemas


def get_agent_user(db: Session, user_id: int):
    return db.query(models.AgentUser).filter(models.AgentUser.id == user_id).first()


def get_agent_user_by_username(db: Session, username: str):
    return db.query(models.AgentUser).filter(models.AgentUser.username == username).first()


def create_agent_user(db: Session, user: schemas.AgentUserCreate):
    from .auth import get_password_hash

    db_user = models.AgentUser(username=user.username, hashed_password=get_password_hash(user.password))
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_api_key(db: Session, key_id: int):
    return db.query(models.ApiKey).filter(models.ApiKey.id == key_id).first()


def get_api_key_by_prefix(db: Session, key_prefix: str):
    return db.query(models.ApiKey).filter(models.ApiKey.key_prefix == key_prefix).first()


def get_api_keys(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.ApiKey).order_by(models.ApiKey.id).offset(skip).limit(limit).all()


def scopes_for(api_key: models.ApiKey) -> list[str]:
    return sorted({scope.strip() for scope in (api_key.scopes or "").split(",") if scope.strip()})


def create_api_key(
    db: Session,
    key_data: schemas.ApiKeyCreate,
    plain_key: str,
    key_prefix: str,
    *,
    actor: str,
):
    from .auth import hash_api_key

    db_api_key = models.ApiKey(
        key_prefix=key_prefix,
        hashed_key=hash_api_key(plain_key),
        description=key_data.description,
        scopes=",".join(key_data.scopes),
        created_by=actor,
        expires_at=key_data.expires_at,
    )
    db.add(db_api_key)
    db.flush()
    record_audit_event(
        db,
        event="created",
        actor=actor,
        api_key=db_api_key,
        detail=f"scopes={','.join(key_data.scopes)}",
        commit=False,
    )
    db.commit()
    db.refresh(db_api_key)
    return db_api_key


def update_api_key_last_used(db: Session, key_prefix: str):
    db_api_key = get_api_key_by_prefix(db, key_prefix)
    if db_api_key:
        db_api_key.last_used_at = datetime.utcnow()
        db.commit()
        db.refresh(db_api_key)
    return db_api_key


def revoke_api_key(db: Session, key_id: int, *, actor: str):
    db_api_key = get_api_key(db, key_id)
    if db_api_key:
        db_api_key.is_active = False
        db_api_key.revoked_at = datetime.utcnow()
        record_audit_event(
            db,
            event="revoked",
            actor=actor,
            api_key=db_api_key,
            detail="credential revoked by administrator",
            commit=False,
        )
        db.commit()
        db.refresh(db_api_key)
    return db_api_key


def record_audit_event(
    db: Session,
    *,
    event: str,
    actor: str | None,
    api_key: models.ApiKey | None = None,
    key_prefix: str | None = None,
    detail: str | None = None,
    commit: bool = True,
):
    record = models.ApiKeyAuditEvent(
        key_id=api_key.id if api_key is not None else None,
        key_prefix=api_key.key_prefix if api_key is not None else key_prefix,
        event=event,
        actor=actor,
        detail=detail,
    )
    db.add(record)
    if commit:
        db.commit()
        db.refresh(record)
    return record


def list_audit_events(db: Session, *, limit: int = 100):
    return (
        db.query(models.ApiKeyAuditEvent)
        .order_by(models.ApiKeyAuditEvent.id.desc())
        .limit(min(max(limit, 1), 500))
        .all()
    )
