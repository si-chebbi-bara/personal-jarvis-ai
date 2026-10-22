"""Re-runnable checks for the API's token auth, CORS allowlist and shell blocklist.

    python scripts/verify_security.py

Runs the real FastAPI app in-process with a throwaway token (never the one in
your .env) and a temporary security log (never your logs/security.log). The
LLM, agent loop and MCP calls are stubbed, so it needs no API keys and no
running server. Prints one PASS/FAIL line per check plus a summary, and exits
non-zero if anything failed.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import tempfile
import traceback
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")  # google.generativeai's deprecation banner

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

TOKEN = "verify-" + secrets.token_urlsafe(24)
os.environ["JARVIS_API_TOKEN"] = TOKEN
os.environ["JARVIS_ALLOWED_ORIGINS"] = ""

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from actions import system  # noqa: E402
from core import security  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="jarvis-verify-security-"))
security.SECURITY_LOG_PATH = TMP / "security.log"

# Stubs: a security check must never call a model or run a real command.
server.handle = lambda c, forced_provider=None: {"success": True, "message": "stub"}
server.run_auto = lambda c, forced_provider=None: (e for e in [{"type": "final", "message": "stub"}])
server.mcp_manager.status = lambda: []
server.run_shell_command = lambda c, timeout=30: {"success": True, "message": "stub"}

PROTECTED = [
    ("POST", "/api/command", {"command": "hi"}),
    ("POST", "/api/command/auto", {"command": "hi"}),
    ("POST", "/api/shell", {"command": "echo hi"}),
    ("GET", "/api/mcp/status", None),
]
GOOD = {"Authorization": f"Bearer {TOKEN}"}
WRONG = {"Authorization": "Bearer " + secrets.token_urlsafe(24)}

client = TestClient(server.app)
results: list[tuple[str, bool, str]] = []


def check(label: str, fn) -> None:
    """Run one check, record PASS/FAIL, never let it crash the script."""
    try:
        detail = fn() or ""
        results.append((label, True, detail))
    except AssertionError as exc:
        results.append((label, False, str(exc)))
    except Exception:
        results.append((label, False, traceback.format_exc(limit=2).strip()))


def call(method: str, path: str, body, headers=None):
    return client.request(method, path, json=body, headers=headers)


def expect_status(method, path, body, headers, status):
    def fn():
        r = call(method, path, body, headers)
        assert r.status_code == status, f"got {r.status_code}, expected {status}: {r.text[:120]}"
        return f"{r.status_code}"
    return fn


for method, path, body in PROTECTED:
    check(f"{method} {path} without token -> 401", expect_status(method, path, body, None, 401))
    check(f"{method} {path} with wrong token -> 401", expect_status(method, path, body, WRONG, 401))
    check(f"{method} {path} with correct token -> 200", expect_status(method, path, body, GOOD, 200))

check("GET / (health) is open without token -> 200", expect_status("GET", "/", None, None, 200))


def cors_rejects_unlisted_origin():
    r = client.options("/api/shell", headers={
        "Origin": "http://evil.example",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert "access-control-allow-origin" not in r.headers, f"allowed: {r.headers.get('access-control-allow-origin')}"
    return f"preflight {r.status_code}, no Access-Control-Allow-Origin"


def cors_allows_default_origin():
    r = client.options("/api/shell", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173", dict(r.headers)
    return "Access-Control-Allow-Origin: http://localhost:5173"


check("CORS rejects an unlisted origin (http://evil.example)", cors_rejects_unlisted_origin)
check("CORS allows the default origin (http://localhost:5173)", cors_allows_default_origin)


def failed_auth_logged_without_token():
    text = security.SECURITY_LOG_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert len(lines) == 2 * len(PROTECTED), f"expected {2 * len(PROTECTED)} lines, got {len(lines)}"
    assert all("AUTH FAILED" in line and "ip=" in line for line in lines), lines[:2]
    assert TOKEN not in text and WRONG["Authorization"].split()[1] not in text, "a token was logged"
    return f"{len(lines)} lines, e.g. {lines[0]}"


check("Failed attempts are in security.log, tokens are not", failed_auth_logged_without_token)


def blocklist_blocks_rm_rf():
    # The real run_shell_command, but with subprocess.run replaced by a tripwire:
    # if the blocklist ever failed, nothing would actually be executed.
    def tripwire(*args, **kwargs):
        raise AssertionError("blocklist let the command through to subprocess.run")

    original = subprocess.run
    system.subprocess.run = tripwire
    try:
        result = system.run_shell_command("rm -rf /")
    finally:
        system.subprocess.run = original
    assert result["success"] is False, result
    return result["message"].splitlines()[0]


check("Shell blocklist still blocks `rm -rf /`", blocklist_blocks_rm_rf)

width = max(len(label) for label, _, _ in results)
for label, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {label.ljust(width)}  {detail}")
failed = sum(not ok for _, ok, _ in results)
print(f"\n{len(results) - failed}/{len(results)} checks passed.")
sys.exit(1 if failed else 0)
