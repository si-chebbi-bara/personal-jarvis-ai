"""Auth + CORS checks for the API. Run with:  python -m pytest tests/test_security.py"""

import pytest
from fastapi.testclient import TestClient

import server

TOKEN = "test-token-0123456789abcdef"
PROTECTED = [
    ("post", "/api/command", {"command": "hi"}),
    ("post", "/api/command/auto", {"command": "hi"}),
    ("post", "/api/shell", {"command": "echo hi"}),
    ("get", "/api/mcp/status", None),
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("JARVIS_API_TOKEN", TOKEN)
    # Never run real commands or call a model from a security test.
    monkeypatch.setattr(server, "run_shell_command", lambda c, timeout=30: {"success": True, "message": "ok"})
    monkeypatch.setattr(server, "handle", lambda c, forced_provider=None: {"success": True, "message": "ok"})
    monkeypatch.setattr(server, "run_auto", lambda c, forced_provider=None: (e for e in [{"type": "final"}]))
    monkeypatch.setattr(server.mcp_manager, "status", lambda: [])
    return TestClient(server.app)


def call(client, method, path, body, headers=None):
    return getattr(client, method)(path, json=body, headers=headers) if body else getattr(client, method)(path, headers=headers)


BAD_AUTH = {
    "missing": None,
    "wrong": {"Authorization": "Bearer nope-nope-nope-nope"},
    "non_bearer": {"Authorization": f"Basic {TOKEN}"},
}


@pytest.mark.parametrize("auth", BAD_AUTH.values(), ids=BAD_AUTH.keys())
@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_bad_token_is_401(client, method, path, body, auth):
    r = call(client, method, path, body, auth)
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"


@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_right_token_is_200(client, method, path, body):
    r = call(client, method, path, body, {"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200


@pytest.mark.parametrize("value", ["", "short"])
@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_no_usable_token_fails_closed(monkeypatch, client, method, path, body, value):
    monkeypatch.setenv("JARVIS_API_TOKEN", value)
    r = call(client, method, path, body, {"Authorization": f"Bearer {value}"})
    assert r.status_code == 503


def test_root_stays_open_and_reports_auth_state(monkeypatch, client):
    r = client.get("/")
    assert r.status_code == 200 and r.json()["auth_configured"] is True
    monkeypatch.setenv("JARVIS_API_TOKEN", "")
    r = client.get("/")
    assert r.status_code == 200 and r.json()["auth_configured"] is False


def test_cors_allows_listed_origin_only(client):
    ok = client.options("/api/shell", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/api/shell", headers={
        "Origin": "http://evil.example",
        "Access-Control-Request-Method": "POST",
    })
    assert "access-control-allow-origin" not in bad.headers


@pytest.mark.parametrize("value", ["*, http://192.168.1.20:5173/", "*,*,http://192.168.1.20:5173"])
def test_wildcard_origin_is_ignored(monkeypatch, value):
    from core import security
    monkeypatch.setenv("JARVIS_ALLOWED_ORIGINS", value)
    assert security.allowed_origins() == security.DEFAULT_ORIGINS + ["http://192.168.1.20:5173"]
