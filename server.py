"""FastAPI backend for Jarvis.

Pure JSON API — the user interface is the separate React app in frontend/.
Run with:  uvicorn server:app --host 0.0.0.0 --port 8000
"""

import json

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from actions.system import run_shell_command
from core.agent_loop import run_auto
from core.llm_brain import handle
from core.security import (
    COOKIE_NAME,
    TOKEN_TTL_SECONDS,
    allowed_origins,
    create_token,
    require_auth,
    verify_password,
)

app = FastAPI(title="Jarvis API")

# Only the origins listed in .env (JARVIS_ALLOWED_ORIGINS) may call the API from
# a browser. allow_credentials=True lets the login cookie travel with requests;
# browsers refuse that combination with a "*" origin, so the list must be explicit.
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


class LoginRequest(BaseModel):
    password: str


class CommandRequest(BaseModel):
    command: str
    provider: str | None = None  # "auto" / None -> automatic selection


class ShellRequest(BaseModel):
    command: str
    timeout: int = 30


@app.get("/")
def root():
    return {"status": "ok", "service": "jarvis", "endpoint": "POST /api/command"}


@app.post("/api/login")
def login(req: LoginRequest, response: Response):
    if not verify_password(req.password):
        raise HTTPException(status_code=401, detail="Wrong password")
    response.set_cookie(
        COOKIE_NAME,
        create_token(),
        max_age=TOKEN_TTL_SECONDS,
        httponly=True,   # page JavaScript can't read it, so XSS can't steal it
        samesite="lax",  # not sent on cross-site requests
        secure=False,    # plain HTTP on the home LAN; set True once HTTPS exists
    )
    return {"success": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"success": True}


@app.get("/api/me")
def me(user: str = Depends(require_auth)):
    return {"user": user}


@app.post("/api/command", dependencies=[Depends(require_auth)])
def run_command(req: CommandRequest):
    result = handle(req.command, forced_provider=req.provider)
    return result


@app.post("/api/command/auto", dependencies=[Depends(require_auth)])
async def run_command_auto(req: CommandRequest, request: Request):
    """Automatic mode: stream the agent loop's progress as Server-Sent Events.

    One `data: {...}` event per step (see core/agent_loop.py for the shapes),
    ending with a `final` event. Closing the connection (the UI's Stop button)
    stops the loop before its next provider or tool call.
    """
    events = run_auto(req.command, forced_provider=req.provider)

    async def stream():
        try:
            while not await request.is_disconnected():
                # Each step blocks on an LLM or tool call, so run it off the
                # event loop; this also lets us check for a disconnect between steps.
                event = await run_in_threadpool(next, events, None)
                if event is None:
                    break
                yield f"data: {json.dumps(event, default=str)}\n\n"
        finally:
            events.close()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/shell", dependencies=[Depends(require_auth)])
def run_shell(req: ShellRequest):
    """Direct shell access, bypassing the LLM. Same blocklist/timeout/logging as the tool-call path."""
    return run_shell_command(req.command, timeout=req.timeout)
