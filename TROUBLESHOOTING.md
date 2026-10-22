# Jarvis Troubleshooting

Known issues hit during development, and their fixes. If something breaks, check here before debugging from scratch.

## Environment / setup

- **`pip install` fails or a package "not found" after installing it** — the venv isn't activated. Windows: `.\venv\Scripts\Activate.ps1` (prompt should show `(venv)`). Linux: `source venv/bin/activate`. On Ubuntu without a venv, pip refuses with "externally-managed-environment".
- **Windows: `python -m venv` fails with "Python was not found"** — the Microsoft Store Python alias is intercepting the command. Disable "App execution aliases" for python.exe/python3.exe in Windows Settings, or make sure a real python.org install has PATH priority.
- **Linux: `pyaudio` install fails** — needs `sudo apt install portaudio19-dev` first. `pyautogui` may need `sudo apt install python3-tk`.
- **Linux: shared/NTFS-mounted repo breaks after a remount at a different path** — the venv has hardcoded paths baked in. Recreate the venv fresh and reinstall from `requirements-lock.txt` (don't hand-edit `requirements.txt` from memory).
- **Git on an NTFS-mounted repo (dual-boot / shared drive) misbehaves** — run `git config --global --add safe.directory <path>` and `git config core.fileMode false` (local-only, not global) for that repo.

## API token / CORS

- **Every `/api/*` call returns 503 "JARVIS_API_TOKEN is not set"** — the token in `.env` is shorter than 16 characters, or the backend could not write a generated one to `.env`. Set `JARVIS_API_TOKEN=<16+ characters>` (or delete the line to have one generated) and restart the backend (`.env` is only read at startup). Generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- **Works on the computer, "Failed to fetch" / CORS error on the phone** — the phone's page address is not in `JARVIS_ALLOWED_ORIGINS`, or `frontend/.env` still points `VITE_API_BASE` at `localhost`. See README "Securing the API" step 2, then restart both servers.
- **Lost the generated token** — it is in `.env` as `JARVIS_API_TOKEN`; it is only printed on the run that created it.
- **401 "Missing or invalid token"** — the token the client sends doesn't match `.env`. In the web UI it asks again automatically; paste the value from `.env`. For curl, send `-H "Authorization: Bearer <token>"`.
- **Browser console shows a CORS error, but the backend is running** — the page's address isn't in the allowlist. Add it to `JARVIS_ALLOWED_ORIGINS` in `.env` (exactly as shown in the address bar, e.g. `http://192.168.1.20:5173`, no trailing path) and restart the backend.
- **Token prompt appears after every reload** — the browser is blocking localStorage (private mode). Use a normal window.

## Windows PowerShell encoding gotchas

- **`echo "text" >> file` in PowerShell 5.1 writes UTF-16**, which can corrupt a `requirements.txt` or `.gitignore` pip/git expects as UTF-8. Use `Add-Content -Path file -Value "text" -Encoding utf8` instead.
- **`Out-File -Encoding utf8` writes UTF-8 *with a BOM* (byte-order mark)**. A CSV written this way (or by Excel/Notepad) will have its first header glued to a `﻿` prefix if read back with plain `utf-8`. Read such files with `utf-8-sig` instead — it strips the BOM if present and behaves identically to `utf-8` if not.

## Screenshots / clipboard (Linux, Wayland/GNOME)

- **Screenshot fails or falls through unexpectedly** — `flameshot` works via the XDG portal (expect a one-time permission popup); `gnome-screenshot`/`grim` don't work the same way. Falls back to Pillow if none are available.
- **Clipboard doesn't work on Wayland** — needs `wl-clipboard` installed (`sudo apt install wl-clipboard`).

## MCP servers (external tools)

MCP tools are named `<server>__<tool>` and their descriptions start with `[MCP: <server>]`. Config: `mcp_servers.json` in the repo root (copy of `mcp_servers.example.json`). Logs: every MCP tool call (time, server, tool, arguments with secrets redacted, success, duration) and every startup problem is in `logs/mcp.log`; the servers' own error output (stderr) is in `logs/mcp-servers.log`. The live state of each server is at `GET /api/mcp/status`. Config changes need a Jarvis restart.

- **A server shows `failed` with "command '...' not found on PATH"** — the program in `command` isn't installed or isn't on PATH. For `npx` servers, install Node.js (which includes `npx`) and restart the terminal; check with `node --version` and `npx --version`. Jarvis resolves the command itself, so `npx` also works on Windows (where it is `npx.cmd`). `"python"` always means the venv's Python.
- **A server shows `failed` with "Connection closed (the server process exited during startup...)"** — the server started and then crashed. The reason is in `logs/mcp-servers.log`: usually a wrong path in `args` (relative paths are relative to the repo root), a missing package, or a missing API key in `env`.
- **A server shows `failed` with "no response within startup_timeout"** — it took too long to start. `npx -y` downloads the package on the first run, so raise `startup_timeout` (e.g. 120) for that server, or run the `npx` command once by hand so it's cached.
- **A server shows `failed` with "environment variable(s) not set: X"** — the config uses `${X}` but `X` isn't in the environment or `.env`. Add it to `.env` (never to the JSON file itself).
- **A server shows `disabled` or `skipped_platform`** — `"enabled": false`, or its `platforms` list doesn't include this OS (`linux` / `windows` / `darwin`). Both are on purpose: the same `mcp_servers.json` is shared between Linux and Windows on the NTFS drive.
- **A server is missing from the status entirely** — `mcp_servers.json` is missing, or isn't valid JSON (look for "invalid JSON?" in `logs/mcp.log`; a missing comma or a trailing comma is the usual cause), or it has no top-level `"mcpServers"` object.
- **A tool is missing although its server is `connected`** — check `skipped_tools` in `/api/mcp/status` and warnings in `logs/mcp.log`:
  - "is a built-in/skill name": the MCP tool's `<server>__<tool>` name would shadow a built-in tool or skill, so the MCP one is skipped. Rename the server in `mcp_servers.json`.
  - "already used by another MCP tool": two servers produce the same name after sanitizing; rename one server.
  - `allowed_tools` is set for the server and doesn't list that tool ("allowed_tools not offered by the server" means a name in the list doesn't exist on the server; names are the server's own tool names, without the `<server>__` prefix).
- **Gemini: a tool works with Claude/OpenAI but not with Gemini, or Gemini errors with "Unknown field for Schema"** — Gemini only accepts a subset of JSON Schema, so Jarvis rewrites MCP schemas for it (drops `title`, `default`, `additionalProperties`, `$schema`, `examples`; inlines `$ref`; turns `anyOf [X, null]` into a nullable X). A tool whose schema still can't be rewritten (e.g. a required argument that may be one of several different types) is left out for Gemini only, with "not offered to Gemini" in `logs/mcp.log`. Use Claude or OpenAI (pick the provider in the UI) when you need that tool.
- **An MCP tool call fails with "timed out after Ns"** — the tool took longer than the server's `timeout` (default 30 s). Raise `timeout` for that server if the tool is legitimately slow. Jarvis keeps working; only that call failed.
- **An MCP tool call fails with "stopped responding (connection closed)"** and the server is now `failed` — the server process exited or crashed mid-session. See `logs/mcp-servers.log`, then restart Jarvis to reconnect.
- **Leftover MCP server processes after Jarvis exits** — shouldn't happen (the API server's shutdown and an exit hook stop them, and each stdio server also exits when Jarvis's end of its pipe closes). If one survives a hard kill of Jarvis, end it in Task Manager / `pkill -f <server name>`.
- **Run `python scripts/verify_mcp.py`** to check the whole MCP setup with the built-in test server; it never touches `mcp_servers.json`.

## Known limitations

- **Windows**: `actions/system.py` is currently Linux-only in practice (`xdg-open`, `wpctl`/`pactl`/`amixer`, `flameshot`/`gnome-screenshot`/`grim`) — it has no platform checks. Windows compatibility fixes for `open_app`, `open_website`, `take_screenshot`, and `get_system_stats` are drafted (see `Tasks/Windows compatibility fix.md` in the Obsidian vault) but NOT YET applied to `actions/system.py` in this repo. `set_volume` has no Windows implementation drafted at all.
- **Selenium/Chrome browser automation** was tried and abandoned (profile-lock crashes, snap conflicts) — considered out of scope.
- `google.generativeai` (used in `core/llm_brain.py`) is deprecated in favor of `google-genai` — still works, migration not yet done.
