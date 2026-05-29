from datetime import UTC, datetime, timedelta

from backend.app.config import settings
from fastapi import APIRouter, HTTPException
from jose import jwt

router = APIRouter()
ACCESS_TOKEN_EXPIRE_MINUTES = 480


@router.post("/auth/login")
def login(email: str, password: str):
    if email != settings.default_admin_email:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if password != settings.default_admin_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    expires_at = datetime.now(UTC) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    token = jwt.encode(
        {"sub": email, "role": "admin", "exp": expires_at},
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {"access_token": token, "token_type": "bearer"}
