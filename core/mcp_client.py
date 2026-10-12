"""MCP client: connect to the servers in mcp_servers.json and expose their tools.

The MCP Python SDK is async, while Jarvis's executor is sync and gets called
from FastAPI worker threads, the CLI and PyQt. So MCPManager runs one asyncio
event loop on a dedicated daemon thread and exposes plain sync methods
(list_tools, call_tool, status, shutdown) that hand coroutines to that loop
with asyncio.run_coroutine_threadsafe(...).result(timeout).

Each server gets one long-lived task that enters the SDK's transport and
ClientSession context managers, initializes, lists tools, signals "ready",
waits for shutdown, then exits those same contexts. Entering and exiting in
one task is required: anyio raises "Attempted to exit cancel scope in a
different task" otherwise.

Startup is lazy: the first call to any public method loads the config and
connects to every enabled server in parallel, each bounded by its own
startup_timeout, so one slow or broken server never blocks the others.
Importing this module starts nothing.
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import hashlib
import json
import re
import threading
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path

from core.mcp_config import ROOT, ServerConfig, get_logger, load_config
from core.mcp_schema import SchemaError, to_gemini_parameters, to_parameters

RESULT_CHAR_LIMIT = 4000
MAX_TOOL_NAME = 64
SERVER_STDERR_LOG = ROOT / "logs" / "mcp-servers.log"

# Argument keys whose values are never written to logs/mcp.log.
_SECRET_KEY = re.compile(r"token|secret|password|passwd|api[_-]?key|auth|credential|cookie|session", re.IGNORECASE)
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_-]")

log = get_logger()


def exposed_name(server: str, tool: str) -> str:
    """'<server>__<tool>', sanitized to [A-Za-z0-9_-] and at most 64 chars (valid for Gemini/Claude/OpenAI)."""
    name = _UNSAFE_CHARS.sub("_", f"{server}__{tool}")
    if len(name) > MAX_TOOL_NAME:
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        name = f"{name[:MAX_TOOL_NAME - 9]}_{digest}"
    return name


def _reserved_names() -> set[str]:
    """Built-in + skill tool names; an MCP tool may never shadow these."""
    from core.executor import TOOLS  # lazy: executor imports this module

    return set(TOOLS)


@dataclass
class _Tool:
    server: str
    remote_name: str  # the tool's name on its own server
    declaration: dict  # Claude/OpenAI/Ollama format
    gemini_declaration: dict | None  # None -> not offered to Gemini


@dataclass
class _Server:
    cfg: ServerConfig
    status: str = "pending"
    error: str = ""
    tools: list[str] = field(default_factory=list)  # exposed names
    skipped_tools: list[str] = field(default_factory=list)
    raw_tools: list = field(default_factory=list)  # mcp Tool objects from tools/list
    session: object | None = None
    ready: asyncio.Event | None = None
    stop: asyncio.Event | None = None
    task: asyncio.Task | None = None


class MCPManager:
    def __init__(self, config_path: Path | str | None = None):
        self._config_path = config_path
        self._lock = threading.RLock()
        self._started = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._servers: dict[str, _Server] = {}
        self._tools: dict[str, _Tool] = {}
        self._errlog = None
        self._atexit_registered = False

    # ------------------------------------------------------------------ setup

    def configure(self, config_path: Path | str | None) -> None:
        """Point at a different config file (used by scripts/verify_mcp.py). Restarts if running."""
        with self._lock:
            self.shutdown()
            self._config_path = config_path

    def ensure_started(self) -> None:
        """Load the config and connect to all enabled servers, once. Thread-safe, never raises."""
        if self._in_loop_thread():
            return  # a sync wrapper called from the MCP thread itself would deadlock
        with self._lock:
            if self._started:
                return
            self._started = True
            try:
                self._start()
            except Exception as exc:  # pragma: no cover - defensive
                log.error("MCP startup failed: %s", exc)

    def _start(self) -> None:
        configs = load_config(self._config_path)
        self._servers = {}
        self._tools = {}
        for cfg in configs:
            srv = _Server(cfg=cfg)
            if cfg.skip_status:
                srv.status, srv.error = cfg.skip_status, cfg.error
            self._servers[cfg.name] = srv
        to_start = [s for s in self._servers.values() if s.status == "pending"]
        if not to_start:
            return

        if not self._atexit_registered:
            atexit.register(self.shutdown)
            self._atexit_registered = True
        try:
            SERVER_STDERR_LOG.parent.mkdir(parents=True, exist_ok=True)
            self._errlog = open(SERVER_STDERR_LOG, "a", encoding="utf-8")
        except OSError:
            self._errlog = None

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="jarvis-mcp", daemon=True)
        self._thread.start()

        budget = max(s.cfg.startup_timeout for s in to_start) + 10
        future = asyncio.run_coroutine_threadsafe(self._start_all(to_start), self._loop)
        try:
            future.result(timeout=budget)
        except Exception as exc:
            future.cancel()
            log.error("MCP startup did not finish in %.0fs: %s", budget, exc)
        for srv in to_start:
            if srv.status == "pending":
                srv.status, srv.error = "failed", "did not finish starting"

        reserved = _reserved_names()
        for srv in to_start:
            if srv.status == "connected":
                self._register_tools(srv, reserved)
        connected = [s.cfg.name for s in to_start if s.status == "connected"]
        log.info("MCP ready: %d server(s) connected %s, %d tool(s)", len(connected), connected, len(self._tools))

    def _in_loop_thread(self) -> bool:
        return self._thread is not None and threading.current_thread() is self._thread

    # ------------------------------------------------------- async (MCP thread)

    async def _start_all(self, servers: list[_Server]) -> None:
        for srv in servers:
            srv.ready, srv.stop = asyncio.Event(), asyncio.Event()
            srv.task = asyncio.create_task(self._run_server(srv), name=f"mcp:{srv.cfg.name}")
        await asyncio.gather(*(srv.ready.wait() for srv in servers))

    async def _run_server(self, srv: _Server) -> None:
        """One server's whole life, in one task (see the module docstring)."""
        from mcp import ClientSession, StdioServerParameters, stdio_client
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client

        import anyio

        cfg = srv.cfg
        try:
            async with AsyncExitStack() as stack:
                if cfg.transport == "http":
                    http = await stack.enter_async_context(create_mcp_http_client(headers=cfg.headers or None))
                    read, write = await stack.enter_async_context(streamable_http_client(cfg.url, http_client=http))
                else:
                    params = StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env or None, cwd=cfg.cwd)
                    kwargs = {"errlog": self._errlog} if self._errlog else {}
                    read, write = await stack.enter_async_context(stdio_client(params, **kwargs))
                session = await stack.enter_async_context(ClientSession(read, write))
                # The deadline wraps only these awaits, never a context entry, so
                # cancel scopes still close innermost-first.
                with anyio.move_on_after(cfg.startup_timeout) as scope:
                    await session.initialize()
                    srv.raw_tools = await _list_all_tools(session)
                if scope.cancelled_caught:
                    raise TimeoutError(f"no response within startup_timeout ({cfg.startup_timeout:.0f}s)")
                srv.session = session
                srv.status = "connected"
                srv.ready.set()
                await srv.stop.wait()
        except BaseException as exc:  # includes ExceptionGroup from anyio task groups
            if srv.status == "pending":
                srv.status, srv.error = "failed", _startup_error(exc, cfg)
                log.warning("server '%s' failed to start: %s", cfg.name, srv.error)
            elif srv.status == "connected" and not srv.stop.is_set():
                self._mark_dead(srv, f"connection lost: {_short_error(exc)}")
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
        finally:
            srv.session = None
            srv.ready.set()

    async def _stop_all(self) -> None:
        tasks = []
        for srv in self._servers.values():
            if srv.stop is not None:
                srv.stop.set()
            if srv.task is not None:
                tasks.append(srv.task)
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=15)
            for task in pending:
                task.cancel()

    # ---------------------------------------------------------- registration

    def _register_tools(self, srv: _Server, reserved: set[str]) -> None:
        cfg = srv.cfg
        allowed = set(cfg.allowed_tools) if cfg.allowed_tools is not None else None
        for tool in srv.raw_tools:
            if allowed is not None and tool.name not in allowed:
                continue
            name = exposed_name(cfg.name, tool.name)
            if name in reserved:
                srv.skipped_tools.append(tool.name)
                log.warning("tool '%s' from server '%s' skipped: '%s' is a built-in/skill name", tool.name, cfg.name, name)
                continue
            if name in self._tools:
                srv.skipped_tools.append(tool.name)
                log.warning("tool '%s' from server '%s' skipped: '%s' is already used by another MCP tool", tool.name, cfg.name, name)
                continue
            description = f"[MCP: {cfg.name}] {(tool.description or tool.name).strip()}"
            declaration = {"name": name, "description": description, "parameters": to_parameters(tool.input_schema)}
            try:
                gemini_params = to_gemini_parameters(tool.input_schema)
                gemini = {"name": name, "description": description}
                if gemini_params is not None:
                    gemini["parameters"] = gemini_params
            except SchemaError as exc:
                gemini = None
                log.warning("tool '%s' not offered to Gemini (schema can't be converted): %s", name, exc)
            self._tools[name] = _Tool(cfg.name, tool.name, declaration, gemini)
            srv.tools.append(name)
        if allowed is not None:
            missing = allowed - {t.name for t in srv.raw_tools}
            if missing:
                log.warning("server '%s': allowed_tools not offered by the server: %s", cfg.name, sorted(missing))

    # ------------------------------------------------------------- public API

    def list_tools(self) -> list[dict]:
        """Declarations for Claude / OpenAI / Ollama (and the internal format)."""
        self.ensure_started()
        return [t.declaration for t in self._tools.values()]

    def gemini_declarations(self) -> list[dict]:
        """Declarations sanitized for Gemini; tools Gemini can't describe are left out."""
        self.ensure_started()
        return [t.gemini_declaration for t in self._tools.values() if t.gemini_declaration is not None]

    def has_tool(self, name: str) -> bool:
        self.ensure_started()
        return name in self._tools

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """Run an MCP tool. Returns {success, message, output, error}; never raises."""
        self.ensure_started()
        arguments = dict(arguments or {})
        tool = self._tools.get(name)
        if tool is None:
            return _fail(f"Unknown MCP tool: {name}")
        srv = self._servers.get(tool.server)
        started = time.monotonic()
        result = self._call(srv, tool, arguments)
        self._log_call(srv, tool, arguments, result, time.monotonic() - started)
        return result

    def _call(self, srv: _Server, tool: _Tool, arguments: dict) -> dict:
        if self._in_loop_thread():
            return _fail("MCP tools can't be called from inside the MCP thread.")
        if srv is None or srv.status != "connected" or srv.session is None or self._loop is None:
            reason = f" ({srv.error})" if srv is not None and srv.error else ""
            return _fail(f"MCP server '{tool.server}' is not connected{reason}.")

        from mcp.shared.exceptions import MCPError
        from mcp_types import CONNECTION_CLOSED, REQUEST_TIMEOUT

        timeout = srv.cfg.timeout
        coro = srv.session.call_tool(tool.remote_name, arguments, read_timeout_seconds=timeout)
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            # The SDK enforces `timeout` itself; this outer guard only catches a wedged loop.
            raw = future.result(timeout=timeout + 5)
        except (concurrent.futures.TimeoutError, TimeoutError):
            future.cancel()
            return _fail(f"MCP tool '{tool.server}__{tool.remote_name}' timed out after {timeout:.0f}s.", error="timeout")
        except MCPError as exc:
            if exc.code == REQUEST_TIMEOUT:
                return _fail(f"MCP tool '{tool.server}__{tool.remote_name}' timed out after {timeout:.0f}s.", error="timeout")
            if exc.code == CONNECTION_CLOSED:
                self._mark_dead(srv, "connection closed (server process exited?)")
                return _fail(f"MCP server '{tool.server}' stopped responding (connection closed).", error="connection closed")
            return _fail(f"MCP tool '{tool.server}__{tool.remote_name}' failed: {exc}", error=str(exc))
        except Exception as exc:
            if _looks_disconnected(exc):
                self._mark_dead(srv, _short_error(exc))
                return _fail(f"MCP server '{tool.server}' stopped responding: {_short_error(exc)}", error=_short_error(exc))
            return _fail(f"MCP tool '{tool.server}__{tool.remote_name}' failed: {_short_error(exc)}", error=_short_error(exc))
        return _map_result(raw)

    def _mark_dead(self, srv: _Server, reason: str) -> None:
        srv.status, srv.error = "failed", reason
        log.warning("server '%s' marked failed: %s", srv.cfg.name, reason)

    def status(self) -> list[dict]:
        """Per server: name, status, tool names, short error. Never env/headers/args."""
        self.ensure_started()
        return [
            {
                "name": srv.cfg.name,
                "status": srv.status,
                "transport": srv.cfg.transport,
                "tools": list(srv.tools),
                "skipped_tools": list(srv.skipped_tools),
                "error": srv.error or None,
            }
            for srv in self._servers.values()
        ]

    def shutdown(self) -> None:
        """Stop every server and the MCP thread. Idempotent; safe from atexit and FastAPI lifespan."""
        if self._in_loop_thread():
            return
        with self._lock:
            loop, thread = self._loop, self._thread
            if loop is not None and thread is not None and thread.is_alive():
                try:
                    asyncio.run_coroutine_threadsafe(self._stop_all(), loop).result(timeout=20)
                except Exception as exc:
                    log.warning("MCP shutdown was not clean: %s", exc)
                loop.call_soon_threadsafe(loop.stop)
                thread.join(timeout=5)
            if loop is not None and not loop.is_running():
                loop.close()
            if self._errlog is not None:
                try:
                    self._errlog.close()
                except OSError:
                    pass
            if self._started and self._servers:
                log.info("MCP shut down")
            self._loop = self._thread = self._errlog = None
            self._servers, self._tools = {}, {}
            self._started = False

    # ---------------------------------------------------------------- logging

    def _log_call(self, srv: _Server | None, tool: _Tool, arguments: dict, result: dict, duration: float) -> None:
        secrets = srv.cfg.secrets if srv is not None else set()
        try:
            args_text = json.dumps(_redact(arguments, secrets), ensure_ascii=False, default=str)
        except Exception:
            args_text = "<unserializable>"
        if len(args_text) > 500:
            args_text = args_text[:500] + "…"
        log.info(
            "CALL server=%s tool=%s success=%s duration=%.2fs args=%s%s",
            tool.server,
            tool.remote_name,
            bool(result.get("success")),
            duration,
            args_text,
            "" if result.get("success") else f" error={_scrub(str(result.get('error') or result.get('message'))[:200], secrets)}",
        )


# ---------------------------------------------------------------- helpers


def _startup_error(exc: BaseException, cfg: ServerConfig) -> str:
    text = _short_error(exc)
    if cfg.transport == "stdio" and "connection closed" in text.lower():
        text += " (the server process exited during startup; see logs/mcp-servers.log)"
    return text


async def _list_all_tools(session) -> list:
    from mcp_types import PaginatedRequestParams

    result = await session.list_tools()
    tools = list(result.tools)
    pages = 0
    while result.next_cursor and pages < 50:
        result = await session.list_tools(params=PaginatedRequestParams(cursor=result.next_cursor))
        tools.extend(result.tools)
        pages += 1
    return tools


def _map_result(raw) -> dict:
    """CallToolResult -> Jarvis's {success, message, output, error}."""
    parts = []
    for block in getattr(raw, "content", None) or []:
        kind = getattr(block, "type", "")
        if kind == "text":
            parts.append(block.text)
        elif kind == "resource" and hasattr(getattr(block, "resource", None), "text"):
            parts.append(block.resource.text)
        elif kind == "resource_link":
            parts.append(f"[resource link: {getattr(block, 'uri', '')}]")
        else:
            parts.append(f"[{kind or 'binary'} omitted]")
    structured = getattr(raw, "structured_content", None)
    if not parts and structured is not None:
        parts.append(json.dumps(structured, ensure_ascii=False, default=str))
    text = "\n".join(parts).strip()
    if len(text) > RESULT_CHAR_LIMIT:
        text = text[:RESULT_CHAR_LIMIT] + "\n[truncated]"
    is_error = bool(getattr(raw, "is_error", False))
    if not text:
        text = "The MCP tool reported an error." if is_error else "The MCP tool returned no content."
    return {"success": not is_error, "message": text, "output": text, "error": text if is_error else None}


def _fail(message: str, error: str | None = None) -> dict:
    return {"success": False, "message": message, "output": None, "error": error or message}


def _short_error(exc: BaseException) -> str:
    # anyio wraps failures in ExceptionGroups; report the first real cause.
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    text = str(exc) or type(exc).__name__
    if isinstance(exc, FileNotFoundError):
        text = f"command not found or not executable: {exc.filename or text}"
    text = " ".join(text.split())
    return text[:200]


def _looks_disconnected(exc: BaseException) -> bool:
    import anyio

    return isinstance(exc, (anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream, ConnectionError, BrokenPipeError))


def _redact(value, secrets: set[str], key: str = ""):
    if key and _SECRET_KEY.search(key):
        return "***"
    if isinstance(value, dict):
        return {k: _redact(v, secrets, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, str):
        return _scrub(value, secrets)
    return value


def _scrub(text: str, secrets: set[str]) -> str:
    for secret in secrets:
        if len(secret) >= 4:
            text = text.replace(secret, "***")
    return text


# The single shared instance used by core/tools.py, core/executor.py and server.py.
manager = MCPManager()
