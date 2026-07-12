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

    db_user = models.AgentUser(
        username=user.username, hashed_password=get_password_hash(user.password)
    )
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


def create_api_key(db: Session, key_data: schemas.ApiKeyCreate, plain_key: str, key_prefix: str):
    from .auth import hash_api_key

    db_api_key = models.ApiKey(
        key_prefix=key_prefix,
        hashed_key=hash_api_key(plain_key),
        description=key_data.description,
        expires_at=key_data.expires_at,
    )
    db.add(db_api_key)
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


def revoke_api_key(db: Session, key_id: int):
    db_api_key = get_api_key(db, key_id)
    if db_api_key:
        db_api_key.is_active = False
        db.commit()
        db.refresh(db_api_key)
    return db_api_key
