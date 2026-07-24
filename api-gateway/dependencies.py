# amos-api-gateway/dependencies.py
from fastapi import Header, HTTPException, status, Request
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Dict
import time

try:
    from .config import settings
except ImportError:  # Docker starts the gateway as top-level `main:app`.
    from config import settings

# --- Authentication Dependency ---
async def get_current_user(authorization: str = Header(...)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token = authorization.split(" ")[1]
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        # You might want to fetch user details from a DB here
        return {"username": username, "scopes": payload.get("scopes", [])}
    except (JWTError, IndexError):
        raise credentials_exception

# --- Rate Limiting Dependency ---
# In-memory store for rate limiting. In a production environment, use Redis.
rate_limit_store: Dict[str, Dict[str, int]] = {} # {ip_address: {timestamp: count}}

async def rate_limiter(request: Request):
    client_ip = request.client.host
    current_time = int(time.time())

    if client_ip not in rate_limit_store:
        rate_limit_store[client_ip] = {"timestamp": current_time, "count": 0}

    # Check if the window has reset
    if current_time - rate_limit_store[client_ip]["timestamp"] >= settings.RATE_LIMIT_WINDOW_SECONDS:
        rate_limit_store[client_ip]["timestamp"] = current_time
        rate_limit_store[client_ip]["count"] = 0

    rate_limit_store[client_ip]["count"] += 1

    if rate_limit_store[client_ip]["count"] > settings.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for {client_ip}. Try again in {settings.RATE_LIMIT_WINDOW_SECONDS - (current_time - rate_limit_store[client_ip]['timestamp'])} seconds."
        )
    return True
