# api_key_manager/main.py
import os
from datetime import timedelta

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from . import crud, models, schemas, auth
from .database import engine, get_db

app = FastAPI(
    title="Amosclaud Autonomous API Key Manager",
    description="Service for autonomous agents to generate, manage, and validate API keys.",
    version="1.0.0"
)

# --- Database Initialization ---
@app.on_event("startup")
def on_startup():
    models.Base.metadata.create_all(bind=engine)
    # Create a default agent user if none exists for initial access
    db = next(get_db())
    if not crud.get_agent_user_by_username(db, username="amos_agent"):
        print("Creating default 'amos_agent' user with password 'amos_password'")
        crud.create_agent_user(db, schemas.AgentUserCreate(username="amos_agent", password="amos_password"))
    db.close()

# --- Agent User Authentication Endpoints ---
@app.post("/token", response_model=schemas.Token, summary="Authenticate agent user to get JWT token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = crud.get_agent_user_by_username(db, username=form_data.username)
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/agent/me", response_model=schemas.AgentUser, summary="Get current authenticated agent user")
async def read_agent_user_me(current_user: schemas.AgentUser = Depends(auth.get_current_agent_user)):
    return current_user

# --- API Key Management Endpoints (Protected by Agent User Auth) ---
@app.post("/api-keys/", response_model=schemas.ApiKeyFullResponse, status_code=status.HTTP_201_CREATED, summary="Generate a new API key")
async def create_api_key(
    key_data: schemas.ApiKeyCreate,
    current_user: schemas.AgentUser = Depends(auth.get_current_agent_user),
    db: Session = Depends(get_db)
):
    plain_key = auth.generate_api_key_string()
    key_prefix = plain_key.split('_')[0] + "_" + plain_key.split('_')[1][:8] # Store a shorter prefix for lookup
    db_api_key = crud.create_api_key(db, key_data, plain_key, key_prefix)
    return schemas.ApiKeyFullResponse(plain_key=plain_key, **db_api_key.dict())

@app.get("/api-keys/", response_model=list[schemas.ApiKeyResponse], summary="List all API keys")
async def list_api_keys(
    skip: int = 0, limit: int = 100,
    current_user: schemas.AgentUser = Depends(auth.get_current_agent_user),
    db: Session = Depends(get_db)
):
    api_keys = crud.get_api_keys(db, skip=skip, limit=limit)
    return api_keys

@app.delete("/api-keys/{key_id}", response_model=schemas.ApiKeyResponse, summary="Revoke an API key")
async def revoke_api_key(
    key_id: int,
    current_user: schemas.AgentUser = Depends(auth.get_current_agent_user),
    db: Session = Depends(get_db)
):
    db_api_key = crud.revoke_api_key(db, key_id=key_id)
    if not db_api_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API Key not found")
    return db_api_key

# --- API Key Validation Endpoint (Public/Service-to-Service) ---
@app.post("/api-keys/validate", response_model=schemas.ApiKeyValidateResponse, summary="Validate an API key for external services")
async def validate_api_key(
    request: schemas.ApiKeyValidateRequest,
    db: Session = Depends(get_db)
):
    try:
        validated_key = await auth.validate_api_key_dependency(request.api_key, db)
        return schemas.ApiKeyValidateResponse(
            is_valid=True,
            key_id=validated_key.id,
            key_prefix=validated_key.key_prefix,
            description=validated_key.description,
            is_active=validated_key.is_active,
            expires_at=validated_key.expires_at,
            message="API Key is valid and active."
        )
    except HTTPException as e:
        return schemas.ApiKeyValidateResponse(is_valid=False, message=e.detail)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001) # Using 8001 to avoid conflict with cmood
