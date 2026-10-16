"""FastAPI backend for Jarvis.

Pure JSON API — the user interface is the separate React app in frontend/.
Run with:  uvicorn server:app --host 0.0.0.0 --port 8000
"""

import json
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from actions.system import run_shell_command
from core.agent_loop import run_auto
from core.llm_brain import handle
from core.mcp_client import manager as mcp_manager
from core.security import allowed_origins, get_token, require_auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect to MCP servers in the background so the API is up immediately;
    # a request that needs MCP tools before this finishes just waits for it.
    threading.Thread(target=mcp_manager.ensure_started, name="mcp-warmup", daemon=True).start()
    yield
    # Stop MCP server processes (also on `uvicorn --reload`); atexit is the backstop.
    await run_in_threadpool(mcp_manager.shutdown)


app = FastAPI(title="Jarvis API", lifespan=lifespan)

# Only the listed browser origins may call the API (see core/security.py).
# Every /api/* route additionally requires the Bearer token.
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


class CommandRequest(BaseModel):
    command: str
    provider: str | None = None  # "auto" / None -> automatic selection


class ShellRequest(BaseModel):
    command: str
    timeout: int = 30


@app.get("/")
def root():
    # Deliberately open: the UI's connectivity banner polls this. It reveals nothing
    # beyond "the backend is up" and whether a token has been configured.
    return {
        "status": "ok",
        "service": "jarvis",
        "endpoint": "POST /api/command",
        "auth_configured": bool(get_token()),
    }


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


@app.get("/api/mcp/status", dependencies=[Depends(require_auth)])
def mcp_status():
    """Per MCP server: name, status, transport, tool names and a short error. Never env/headers/args."""
    return {"servers": mcp_manager.status()}
