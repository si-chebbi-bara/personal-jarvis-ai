"""A tiny stdio MCP server used to test Jarvis's MCP client.

Run by Jarvis (see mcp_servers.example.json, server name "jarvis_test"), or
by scripts/verify_mcp.py with its own temporary config. Not meant to be run
by hand: it speaks JSON-RPC over stdin/stdout.
"""

from __future__ import annotations

import sys
import time
from typing import Literal

from mcp.server.mcpserver import MCPServer

server = MCPServer("jarvis_test")


@server.tool()
def add(a: int, b: int) -> str:
    """Add two integers and return the sum."""
    return str(a + b)


@server.tool()
def echo(text: str) -> str:
    """Return the given text unchanged."""
    return text


@server.tool()
def slow(seconds: float) -> str:
    """Sleep for the given number of seconds, then return (used for timeout tests)."""
    time.sleep(seconds)
    return f"slept {seconds}s"


@server.tool()
def fail() -> str:
    """Always raise an error (used to test the error path)."""
    raise RuntimeError("intentional failure from the jarvis_test server")


@server.tool()
def complex_args(mode: Literal["fast", "safe"] = "fast", note: str | None = None) -> str:
    """Echo back an enum + nullable argument (exercises the Gemini schema sanitizer)."""
    return f"mode={mode} note={note}"


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--http":
        # Streamable HTTP on http://127.0.0.1:<port>/mcp (scripts/verify_mcp.py uses this).
        server.run("streamable-http", host="127.0.0.1", port=int(sys.argv[2]))
    else:
        server.run()  # stdio transport
