"""API security for the Jarvis backend: a shared-secret token and a CORS allowlist.

Both are configured in `.env` (gitignored), so pulling new code never touches
your personal secret:

    JARVIS_API_TOKEN=<long random string>        # required for every /api/* route
    JARVIS_ALLOWED_ORIGINS=http://192.168.1.20:5173   # optional, comma separated

Generate a token with:  python -c "import secrets; print(secrets.token_urlsafe(32))"
"""

import hmac
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Header, HTTPException

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MIN_TOKEN_LENGTH = 16

# The Vite dev server, reached via localhost or 127.0.0.1. Add your LAN address
# (for the phone) through JARVIS_ALLOWED_ORIGINS.
DEFAULT_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def get_token() -> str:
    """The configured token, or "" when it is missing or too short to be safe.

    Read on every request (not at import) so a change to the environment, or a
    test, takes effect without re-importing the module.
    """
    token = os.getenv("JARVIS_API_TOKEN", "").strip()
    return token if len(token) >= MIN_TOKEN_LENGTH else ""


def allowed_origins() -> list[str]:
    """Browser origins allowed to call the API: the defaults plus any from the env."""
    extra = os.getenv("JARVIS_ALLOWED_ORIGINS", "")
    result = list(DEFAULT_ORIGINS)
    for origin in extra.split(","):
        origin = origin.strip().rstrip("/")
        # Drop every "*": Starlette treats a single "*" anywhere in the list as
        # "allow all origins", which would undo the whole point of this step.
        if origin and origin != "*" and origin not in result:
            result.append(origin)
    return result


def require_auth(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency: reject the request unless it carries the right Bearer token.

    Fails closed: with no usable token configured the API refuses everything
    instead of silently running open.
    """
    expected = get_token()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "JARVIS_API_TOKEN is not set (or shorter than "
                f"{MIN_TOKEN_LENGTH} characters). Add it to .env and restart the backend."
            ),
        )

    scheme, _, supplied = (authorization or "").partition(" ")
    # compare_digest takes constant time, so response timing can't leak the token.
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        supplied.strip().encode(), expected.encode()
    ):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
