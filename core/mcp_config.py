"""Load and validate mcp_servers.json (the MCP client config).

The file uses the standard `mcpServers` shape that MCP server READMEs show,
plus a few Jarvis-only fields per server:

    enabled          bool, default true
    platforms        optional list of "linux" / "windows" / "darwin"
    allowed_tools    optional allowlist of the server's tool names to expose
    timeout          seconds per tool call, default 30
    startup_timeout  seconds to connect + list tools, default 60

load_config() never raises: a missing file means "no MCP servers", invalid
JSON is one log line and also "no MCP servers", and a single bad entry is
reported as a failed server without affecting the others.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "mcp_servers.json"
LOG_PATH = ROOT / "logs" / "mcp.log"

DEFAULT_TIMEOUT = 30.0
DEFAULT_STARTUP_TIMEOUT = 60.0

PLATFORM_NAMES = {"linux": "linux", "win32": "windows", "darwin": "darwin"}
KNOWN_PLATFORMS = set(PLATFORM_NAMES.values())

_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def get_logger() -> logging.Logger:
    """The shared 'jarvis.mcp' logger: everything to logs/mcp.log, warnings also to stderr."""
    logger = logging.getLogger("jarvis.mcp")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S"))
            logger.addHandler(file_handler)
        except OSError:
            pass  # an unwritable log folder must not stop Jarvis
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(logging.WARNING)
        console.setFormatter(logging.Formatter("[mcp] %(message)s"))
        logger.addHandler(console)
    return logger


def current_platform() -> str:
    return PLATFORM_NAMES.get(sys.platform, sys.platform)


@dataclass
class ServerConfig:
    name: str
    transport: str = "stdio"  # "stdio" or "http"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    cwd: str = str(ROOT)
    enabled: bool = True
    platforms: list[str] | None = None
    allowed_tools: list[str] | None = None
    timeout: float = DEFAULT_TIMEOUT
    startup_timeout: float = DEFAULT_STARTUP_TIMEOUT
    # None means "start it"; otherwise "disabled", "skipped_platform" or "failed".
    skip_status: str | None = None
    error: str = ""
    # Values that came out of ${VAR} expansion, so logs can redact them.
    secrets: set[str] = field(default_factory=set)


def _expand(value: str, secrets: set[str], missing: list[str]) -> str:
    def repl(match: re.Match) -> str:
        var = match.group(1)
        found = os.environ.get(var)
        if found is None:
            missing.append(var)
            return ""
        if found:
            secrets.add(found)
        return found

    expanded = _VAR_PATTERN.sub(repl, value)
    if expanded.startswith("~"):
        expanded = os.path.expanduser(expanded)
    return expanded


def _resolve_command(command: str) -> str | None:
    """'python' -> this venv's interpreter; anything else via PATH (npx -> npx.cmd on Windows)."""
    if command in ("python", "python3"):
        return sys.executable
    return shutil.which(command)


def _str_list(value, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"'{label}' must be a list of strings")
    return value


def _str_dict(value, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ValueError(f"'{label}' must be an object of string values")
    return value


def _positive(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"'{label}' must be a positive number of seconds")
    return float(value)


def _parse_server(name: str, raw) -> ServerConfig:
    """Build one ServerConfig. Problems are recorded as skip_status='failed', never raised."""
    cfg = ServerConfig(name=name)
    try:
        if not isinstance(raw, dict):
            raise ValueError("entry must be a JSON object")

        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("'enabled' must be true or false")
        cfg.enabled = enabled
        if "platforms" in raw:
            platforms = [p.lower() for p in _str_list(raw["platforms"], "platforms")]
            unknown = [p for p in platforms if p not in KNOWN_PLATFORMS]
            if unknown:
                raise ValueError(f"unknown platform(s) {unknown}; use linux, windows or darwin")
            cfg.platforms = platforms
        if "allowed_tools" in raw:
            cfg.allowed_tools = _str_list(raw["allowed_tools"], "allowed_tools")
        if "timeout" in raw:
            cfg.timeout = _positive(raw["timeout"], "timeout")
        if "startup_timeout" in raw:
            cfg.startup_timeout = _positive(raw["startup_timeout"], "startup_timeout")

        has_command, has_url = "command" in raw, "url" in raw
        if has_command == has_url:
            raise ValueError("needs exactly one of 'command' (stdio) or 'url' (Streamable HTTP)")
        if has_command and not (isinstance(raw["command"], str) and raw["command"].strip()):
            raise ValueError("'command' must be a non-empty string")
        if has_url and not (isinstance(raw["url"], str) and raw["url"].strip()):
            raise ValueError("'url' must be a non-empty string")
        cfg.transport = "http" if has_url else "stdio"
        args = _str_list(raw.get("args", []), "args")
        env = _str_dict(raw.get("env", {}), "env")
        headers = _str_dict(raw.get("headers", {}), "headers")
    except ValueError as exc:
        cfg.skip_status, cfg.error = "failed", f"invalid config: {exc}"
        return cfg

    # Disabled / other-OS servers are never started, so their ${VAR}s and
    # commands don't need to exist on this machine.
    if not cfg.enabled:
        cfg.skip_status = "disabled"
        return cfg
    if cfg.platforms is not None and current_platform() not in cfg.platforms:
        cfg.skip_status = "skipped_platform"
        return cfg

    missing: list[str] = []
    cfg.args = [_expand(a, cfg.secrets, missing) for a in args]
    cfg.env = {k: _expand(v, cfg.secrets, missing) for k, v in env.items()}
    cfg.headers = {k: _expand(v, cfg.secrets, missing) for k, v in headers.items()}
    target = _expand(raw["url" if has_url else "command"].strip(), cfg.secrets, missing)
    if missing:
        cfg.skip_status = "failed"
        cfg.error = f"environment variable(s) not set: {', '.join(sorted(set(missing)))}"
        return cfg

    if has_url:
        cfg.url = target
    else:
        command = target
        resolved = _resolve_command(command)
        if not resolved:
            cfg.skip_status = "failed"
            cfg.error = f"command '{command}' not found on PATH"
            return cfg
        cfg.command = resolved
    return cfg


def load_config(path: Path | str | None = None) -> list[ServerConfig]:
    """Read the MCP config file. Never raises; see the module docstring."""
    logger = get_logger()
    config_path = Path(path) if path else CONFIG_PATH
    load_dotenv(ROOT / ".env")  # so ${VAR} can come from .env as well as the environment

    if not config_path.exists():
        logger.info("no MCP config at %s; MCP disabled", config_path)
        return []
    try:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.error("could not read %s (invalid JSON?): %s; no MCP servers loaded", config_path.name, exc)
        return []

    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        logger.error("%s has no 'mcpServers' object; no MCP servers loaded", config_path.name)
        return []

    configs = [_parse_server(str(name), raw) for name, raw in servers.items()]
    for cfg in configs:
        if cfg.skip_status == "failed":
            logger.warning("server '%s' not started: %s", cfg.name, cfg.error)
    return configs
