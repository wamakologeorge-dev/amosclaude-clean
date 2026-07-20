from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import jwt  # PyJWT
from passlib.context import CryptContext # For password hashing

# Initialize FastAPI app
app = FastAPI()

# --- Configuration ---
# To generate a new secret key:
# import os
# os.urandom(24).hex()
SECRET_KEY = "your-super-secret-key" # CHANGE THIS IN PRODUCTION!
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2PasswordBearer for token extraction from headers
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# --- Models ---
class User(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: Optional[bool] = None

class UserInDB(User):
    hashed_password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

# --- Mock Database ---
# In a real application, this would be a proper database
users_db = {
    "john.doe": {
        "username": "john.doe",
        "email": "john@example.com",
        "full_name": "John Doe",
        "disabled": False,
        "hashed_password": pwd_context.hash("securepassword"),
    },
    "jane.smith": {
        "username": "jane.smith",
        "email": "jane@example.com",
        "full_name": "Jane Smith",
        "disabled": True,
        "hashed_password": pwd_context.hash("anothersecurepassword"),
    },
}

# --- Utility Functions ---
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_user(username: str) -> Optional[UserInDB]:
    if username in users_db:
        user_dict = users_db[username]
        return UserInDB(**user_dict)
    return None

def authenticate_user(username: str, password: str) -> Optional[UserInDB]:
    user = get_user(username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# --- Dependencies ---
async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
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
        token_data = TokenData(username=username)
    except jwt.PyJWTError:
        raise credentials_exception
    user = get_user(token_data.username)
    if user is None:
        raise credentials_exception
    return User(**user.dict()) # Return a User model without hashed_password

async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.disabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")
    return current_user

# --- Endpoints ---
@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me/", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user

@app.get("/")
async def read_root():
    return {"message": "Welcome to Amosflow API! Authenticate at /token and access /users/me"}

# --- Verification ---
# To run this application:
# 1. Ensure you have FastAPI and Uvicorn installed:
#    pip install fastapi uvicorn "python-jose[cryptography]" "passlib[bcrypt]"
# 2. Save the code above as `amosflow/main.py`.
# 3. Navigate to the directory containing `amosflow` and run:
#    uvicorn amosflow.main:app --reload

# After running, you can access the API at http://127.0.0.1:8000
# - Go to http://127.0.0.1:8000/docs for the interactive API documentation (Swagger UI).
# - Use the `/token` endpoint to get an access token with username "john.doe" and password "securepassword".
# - Use the `/users/me` endpoint with the obtained token in the "Authorize" button (Bearer token) to verify authentication.

# --- Security Considerations ---
# - The `SECRET_KEY` should be a strong, randomly generated string and stored securely (e.g., environment variable)
#   NEVER hardcode it in production.
# - Consider rate limiting for the `/token` endpoint to prevent brute-force attacks.
# - Implement proper logging and error handling.
# - For a real application, integrate with a proper database for user management instead of `users_db` dictionary.
