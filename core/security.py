"""Authentication for the Jarvis API.

Everything secret lives in .env (gitignored):
  JARVIS_PASSWORD_HASH     bcrypt hash of your password (made by set_password.py)
  JARVIS_JWT_SECRET        random string used to sign login tokens
  JARVIS_ALLOWED_ORIGINS   comma-separated list of frontend origins for CORS
"""

import os
import time

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import HTTPException, Request

load_dotenv()

COOKIE_NAME = "jarvis_token"
TOKEN_TTL_SECONDS = 12 * 60 * 60  # 12 hours
_ALGORITHM = "HS256"


def _jwt_secret() -> str:
    secret = os.getenv("JARVIS_JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError(
            "JARVIS_JWT_SECRET is missing or too short. Run: python set_password.py"
        )
    return secret


def allowed_origins() -> list[str]:
    raw = os.getenv(
        "JARVIS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    return [o.strip() for o in raw.split(",") if o.strip()]


def verify_password(plain: str) -> bool:
    stored = os.getenv("JARVIS_PASSWORD_HASH", "")
    if not stored:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
    except ValueError:  # malformed hash in .env
        return False


def create_token() -> str:
    now = int(time.time())
    payload = {"sub": "bara", "iat": now, "exp": now + TOKEN_TTL_SECONDS}
    return jwt.encode(payload, _jwt_secret(), algorithm=_ALGORITHM)


def _token_from_request(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return token
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def require_auth(request: Request) -> str:
    """FastAPI dependency: 401 unless the request carries a valid, unexpired token."""
    token = _token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload["sub"]
