"""Standalone, owner-administered Amosclaud credential authority."""
import os
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from . import auth, crud, schemas
from .database import ensure_schema, get_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    auth._jwt_secret()
    ensure_schema()
    db = next(get_db())
    try:
        username = os.getenv("API_KEY_MANAGER_ADMIN_USERNAME", "").strip()
        password = os.getenv("API_KEY_MANAGER_ADMIN_PASSWORD", "")
        if not username or not password:
            raise RuntimeError(
                "Set API_KEY_MANAGER_ADMIN_USERNAME and API_KEY_MANAGER_ADMIN_PASSWORD before startup"
            )
        if not crud.get_agent_user_by_username(db, username=username):
            crud.create_agent_user(db, schemas.AgentUserCreate(username=username, password=password))
    finally:
        db.close()
    yield


app = FastAPI(
    title="Amosclaud Autonomous API Key Manager",
    description="Owner-administered, scoped credential creation, validation, auditing, and revocation.",
    version="1.2.0",
    lifespan=lifespan,
)


def _username(user) -> str:
    return str(getattr(user, "username", "credential-admin"))


def _response(api_key, *, plain_key: str | None = None):
    data = {
        "id": api_key.id,
        "key_prefix": api_key.key_prefix,
        "description": api_key.description,
        "scopes": crud.scopes_for(api_key),
        "created_by": api_key.created_by,
        "is_active": api_key.is_active,
        "created_at": api_key.created_at,
        "expires_at": api_key.expires_at,
        "last_used_at": api_key.last_used_at,
        "revoked_at": api_key.revoked_at,
    }
    if plain_key is not None:
        data["plain_key"] = plain_key
    return data


@app.get("/health")
def health():
    return {"status": "ok", "service": "api-key-manager"}


@app.post("/token", response_model=schemas.Token, summary="Authenticate a credential administrator")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = crud.get_agent_user_by_username(db, username=form_data.username)
    if not user or not user.is_active or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    return {
        "access_token": auth.create_access_token(
            data={"sub": user.username}, expires_delta=timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
        ),
        "token_type": "bearer",
    }


@app.get("/agent/me", response_model=schemas.AgentUser)
async def read_agent_user_me(current_user=Depends(auth.get_current_agent_user)):
    return current_user


@app.post("/api-keys/", response_model=schemas.ApiKeyFullResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    key_data: schemas.ApiKeyCreate,
    current_user=Depends(auth.get_current_agent_user),
    db: Session = Depends(get_db),
):
    plain_key = auth.generate_api_key_string()
    db_api_key = crud.create_api_key(
        db,
        key_data,
        plain_key,
        auth.api_key_lookup_prefix(plain_key),
        actor=_username(current_user),
    )
    return _response(db_api_key, plain_key=plain_key)


@app.get("/api-keys/", response_model=list[schemas.ApiKeyResponse])
async def list_api_keys(
    skip: int = 0,
    limit: int = 100,
    current_user=Depends(auth.get_current_agent_user),
    db: Session = Depends(get_db),
):
    del current_user
    return [_response(key) for key in crud.get_api_keys(db, skip=skip, limit=min(limit, 100))]


@app.delete("/api-keys/{key_id}", response_model=schemas.ApiKeyResponse)
async def revoke_api_key(
    key_id: int,
    current_user=Depends(auth.get_current_agent_user),
    db: Session = Depends(get_db),
):
    db_api_key = crud.revoke_api_key(db, key_id=key_id, actor=_username(current_user))
    if not db_api_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return _response(db_api_key)


@app.post("/api-keys/validate", response_model=schemas.ApiKeyValidateResponse)
async def validate_api_key(request: schemas.ApiKeyValidateRequest, db: Session = Depends(get_db)):
    """Validate a credential and enforce all requested scopes.

    Deploy this endpoint behind the Amosclaud gateway or on the internal service
    network. It never returns the credential secret or its stored hash.
    """
    try:
        validated_key = await auth.validate_api_key_dependency(
            request.api_key,
            db,
            required_scopes=set(request.required_scopes),
        )
    except HTTPException as exc:
        return schemas.ApiKeyValidateResponse(is_valid=False, message=str(exc.detail))
    return schemas.ApiKeyValidateResponse(
        is_valid=True,
        key_id=validated_key.id,
        key_prefix=validated_key.key_prefix,
        description=validated_key.description,
        scopes=crud.scopes_for(validated_key),
        is_active=validated_key.is_active,
        expires_at=validated_key.expires_at,
        message="API key is valid, active, and authorized for the requested scopes.",
    )


@app.get("/audit-events", response_model=list[schemas.AuditEventResponse])
async def audit_events(
    limit: int = 100,
    current_user=Depends(auth.get_current_agent_user),
    db: Session = Depends(get_db),
):
    del current_user
    return crud.list_audit_events(db, limit=limit)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8001")))
