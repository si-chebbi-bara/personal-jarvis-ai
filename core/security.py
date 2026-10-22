"""API security for the Jarvis backend: a shared-secret token and a CORS allowlist.

Both are configured in `.env` (gitignored), so pulling new code never touches
your personal secret:

    JARVIS_API_TOKEN=<long random string>        # required for every /api/* route
    JARVIS_ALLOWED_ORIGINS=http://192.168.1.20:5173   # optional, comma separated

If JARVIS_API_TOKEN is missing, the backend generates one on startup, saves it
to .env and prints it once (see ensure_token).
"""

import datetime as _dt
import hmac
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv, set_key
from fastapi import Header, HTTPException, Request

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
load_dotenv(ENV_PATH)

SECURITY_LOG_PATH = ROOT / "logs" / "security.log"

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


def ensure_token() -> None:
    """On startup: if no JARVIS_API_TOKEN is set at all, create one, save it to .env, print it once.

    A token that is set but too short is left alone (require_auth answers 503),
    so we never overwrite a value you chose yourself.
    """
    if os.getenv("JARVIS_API_TOKEN", "").strip():
        return
    token = secrets.token_urlsafe(32)
    try:
        # Updates an empty "JARVIS_API_TOKEN=" line (as in .env.example) or appends one.
        ENV_PATH.touch(exist_ok=True)
        set_key(ENV_PATH, "JARVIS_API_TOKEN", token, quote_mode="never")
    except OSError as exc:
        print(f"[security] Could not write JARVIS_API_TOKEN to {ENV_PATH}: {exc}")
        print("[security] The API will refuse /api/* requests until you add a token by hand.")
        return
    os.environ["JARVIS_API_TOKEN"] = token
    bar = "=" * 72
    print(f"\n{bar}\nNo JARVIS_API_TOKEN was set, so a new one was generated and saved to .env:\n\n"
          f"    {token}\n\nPaste it into the web UI once per device. It is not shown again.\n{bar}\n")


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


def _log_failed_auth(request: Request, reason: str) -> None:
    """Append one line to logs/security.log. Never logs the token. Never raises."""
    try:
        SECURITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now().isoformat(timespec="seconds")
        ip = request.client.host if request.client else "unknown"
        line = f"[{stamp}] AUTH FAILED | ip={ip} | {request.method} {request.url.path} | {reason}"
        with SECURITY_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


def require_auth(request: Request, authorization: str | None = Header(default=None)) -> None:
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
        if not authorization:
            reason = "no Authorization header"
        elif scheme.lower() != "bearer":
            reason = "not a Bearer token"
        else:
            reason = "wrong token"
        _log_failed_auth(request, reason)
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
