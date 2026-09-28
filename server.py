"""FastAPI backend for Jarvis.

Pure JSON API — the user interface is the separate React app in frontend/.
Run with:  uvicorn server:app --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from actions.system import run_shell_command
from core.llm_brain import handle

app = FastAPI(title="Jarvis API")

# Home-network only for now, so any origin is allowed. Tighten this during the
# security step (restrict to the React dev server + the LAN IP).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CommandRequest(BaseModel):
    command: str
    provider: str | None = None  # "auto" / None -> automatic selection


class ShellRequest(BaseModel):
    command: str
    timeout: int = 30


@app.get("/")
def root():
    return {"status": "ok", "service": "jarvis", "endpoint": "POST /api/command"}


@app.post("/api/command")
def run_command(req: CommandRequest):
    result = handle(req.command, forced_provider=req.provider)
    return result


@app.post("/api/shell")
def run_shell(req: ShellRequest):
    """Direct shell access, bypassing the LLM. Same blocklist/timeout/logging as the tool-call path."""
    return run_shell_command(req.command, timeout=req.timeout)
