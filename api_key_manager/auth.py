# api_key_manager/auth.py
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import crud, models, schemas
from .database import get_db

# --- AgentUser Authentication (for managing API keys) ---
SECRET_KEY = os.getenv("AGENT_JWT_SECRET_KEY", "your-super-secret-agent-jwt-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_agent_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = schemas.TokenData(username=username)
    except JWTError:
        raise credentials_exception
    user = crud.get_agent_user_by_username(db, username=token_data.username)
    if user is None:
        raise credentials_exception
    return user

# --- API Key Generation and Hashing (for the actual API keys) ---
API_KEY_LENGTH = 32 # Length of the random part of the API key
API_KEY_PREFIX = "ak_" # Prefix for generated API keys

def generate_api_key_string() -> str:
    """Generates a random, cryptographically secure API key string."""
    random_part = secrets.token_urlsafe(API_KEY_LENGTH)
    return f"{API_KEY_PREFIX}{random_part}"

def hash_api_key(api_key: str) -> str:
    """Hashes an API key for secure storage."""
    return pwd_context.hash(api_key)

def verify_api_key_hash(plain_key: str, hashed_key: str) -> bool:
    """Verifies a plain API key against its hash."""
    return pwd_context.verify(plain_key, hashed_key)

async def validate_api_key_dependency(api_key: str, db: Session = Depends(get_db)):
    """Dependency to validate an incoming API key."""
    if not api_key.startswith(API_KEY_PREFIX):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key format")

    key_prefix_part = api_key.split('_')[1] if '_' in api_key else api_key # Extract prefix for lookup
    db_api_key = crud.get_api_key_by_prefix(db, key_prefix=f"{API_KEY_PREFIX}{key_prefix_part}")

    if not db_api_key or not db_api_key.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API Key is invalid or inactive")

    if db_api_key.expires_at and db_api_key.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API Key has expired")

    if not verify_api_key_hash(plain_key=api_key, hashed_key=db_api_key.hashed_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API Key is invalid")

    # Update last used timestamp
    crud.update_api_key_last_used(db, db_api_key.key_prefix)
    return db_api_key
