"""Authentication and cryptographic helpers for the API-key manager."""
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import crud, schemas
from .database import get_db

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
API_KEY_LENGTH = 32
API_KEY_PREFIX = "ak_"
API_KEY_LOOKUP_LENGTH = 8
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


def _jwt_secret() -> str:
    secret = os.getenv("AGENT_JWT_SECRET_KEY")
    if not secret or len(secret) < 32:
        raise RuntimeError("AGENT_JWT_SECRET_KEY must be set to at least 32 characters")
    return secret


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode = {**data, "exp": expire}
    return jwt.encode(to_encode, _jwt_secret(), algorithm=ALGORITHM)


async def get_current_agent_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        username = jwt.decode(token, _jwt_secret(), algorithms=[ALGORITHM]).get("sub")
        if not username:
            raise credentials_exception
    except (JWTError, RuntimeError):
        raise credentials_exception
    user = crud.get_agent_user_by_username(db, username=username)
    if not user or not user.is_active:
        raise credentials_exception
    return user


def generate_api_key_string() -> str:
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(API_KEY_LENGTH)}"


def api_key_lookup_prefix(api_key: str) -> str:
    if not api_key.startswith(API_KEY_PREFIX):
        raise ValueError("Invalid API key format")
    random_part = api_key[len(API_KEY_PREFIX):]
    if len(random_part) < API_KEY_LOOKUP_LENGTH:
        raise ValueError("Invalid API key format")
    return f"{API_KEY_PREFIX}{random_part[:API_KEY_LOOKUP_LENGTH]}"


def hash_api_key(api_key: str) -> str:
    return pwd_context.hash(api_key)


def verify_api_key_hash(plain_key: str, hashed_key: str) -> bool:
    return pwd_context.verify(plain_key, hashed_key)


async def validate_api_key_dependency(api_key: str, db: Session = Depends(get_db)):
    try:
        key_prefix = api_key_lookup_prefix(api_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    db_api_key = crud.get_api_key_by_prefix(db, key_prefix=key_prefix)
    if not db_api_key or not db_api_key.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key is invalid or inactive")
    if db_api_key.expires_at and db_api_key.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key has expired")
    if not verify_api_key_hash(plain_key=api_key, hashed_key=db_api_key.hashed_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key is invalid")
    return crud.update_api_key_last_used(db, db_api_key.key_prefix)
