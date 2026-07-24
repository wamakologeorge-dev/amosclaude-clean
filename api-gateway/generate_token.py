# generate_token.py
from jose import jwt
from datetime import datetime, timedelta
from amos_api_gateway.config import settings # Assuming you run this from the parent directory

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

# Example usage:
test_user_data = {"sub": "testuser", "scopes": ["read", "write"]}
test_token = create_access_token(test_user_data)
print(f"Generated Test JWT Token: {test_token}")
