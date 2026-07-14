"""Standalone, owner-administered API-key manager service."""
import os
from datetime import timedelta

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from . import auth, crud, models, schemas
from .database import engine, get_db

app = FastAPI(
    title="Amosclaud Autonomous API Key Manager",
    description="Owner-administered API-key creation, validation, and revocation service.",
    version="1.1.0",
)


@app.on_event("startup")
def on_startup():
    auth._jwt_secret()
    models.Base.metadata.create_all(bind=engine)
    db = next(get_db())
    try:
        if not crud.get_agent_user_by_username(db, username=os.getenv("API_KEY_MANAGER_ADMIN_USERNAME", "")):
            username = os.getenv("API_KEY_MANAGER_ADMIN_USERNAME")
            password = os.getenv("API_KEY_MANAGER_ADMIN_PASSWORD")
            if not username or not password:
                raise RuntimeError(
                    "Set API_KEY_MANAGER_ADMIN_USERNAME and API_KEY_MANAGER_ADMIN_PASSWORD before first startup"
                )
            crud.create_agent_user(db, schemas.AgentUserCreate(username=username, password=password))
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok", "service": "api-key-manager"}


@app.post("/token", response_model=schemas.Token, summary="Authenticate an API-key manager administrator")
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
    del current_user
    plain_key = auth.generate_api_key_string()
    db_api_key = crud.create_api_key(db, key_data, plain_key, auth.api_key_lookup_prefix(plain_key))
    return schemas.ApiKeyFullResponse(plain_key=plain_key, **db_api_key.__dict__)


@app.get("/api-keys/", response_model=list[schemas.ApiKeyResponse])
async def list_api_keys(
    skip: int = 0,
    limit: int = 100,
    current_user=Depends(auth.get_current_agent_user),
    db: Session = Depends(get_db),
):
    del current_user
    return crud.get_api_keys(db, skip=skip, limit=min(limit, 100))


@app.delete("/api-keys/{key_id}", response_model=schemas.ApiKeyResponse)
async def revoke_api_key(
    key_id: int,
    current_user=Depends(auth.get_current_agent_user),
    db: Session = Depends(get_db),
):
    del current_user
    db_api_key = crud.revoke_api_key(db, key_id=key_id)
    if not db_api_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return db_api_key


@app.post("/api-keys/validate", response_model=schemas.ApiKeyValidateResponse)
async def validate_api_key(request: schemas.ApiKeyValidateRequest, db: Session = Depends(get_db)):
    try:
        validated_key = await auth.validate_api_key_dependency(request.api_key, db)
    except HTTPException as exc:
        return schemas.ApiKeyValidateResponse(is_valid=False, message=str(exc.detail))
    return schemas.ApiKeyValidateResponse(
        is_valid=True,
        key_id=validated_key.id,
        key_prefix=validated_key.key_prefix,
        description=validated_key.description,
        is_active=validated_key.is_active,
        expires_at=validated_key.expires_at,
        message="API key is valid and active.",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8001")))
