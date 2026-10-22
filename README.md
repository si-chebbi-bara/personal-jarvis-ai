# Better Jarvis

A desktop assistant for Linux that can understand natural-language commands and carry out common actions on your computer.

It includes a terminal interface and a PyQt6 desktop app with an optional microphone and wake-word mode. Commands are routed to Gemini, Claude, OpenAI, or a local Ollama instance when available; simple built-in rules provide a fallback when no provider is configured.

> **Project status: under development.** The current version is an early desktop prototype and its capabilities will continue to change.

## Features

- Run commands from the terminal or desktop chat window
- Open applications and websites
- Check battery and system statistics
- Create and read text files, find files, copy text, set volume, and take screenshots
- Choose among Gemini, Claude, OpenAI, and Ollama automatically
- Optional one-time voice input and "Jarvis" wake-word listening
- Stays available from the system tray after the window is closed

## Requirements

- Python 3.10 or newer
- Linux desktop environment (the included tools target Linux)
- At least one optional AI provider API key, or [Ollama](https://ollama.com/) running locally

## Installation

```bash
git clone https://github.com/YOUR-USERNAME/better-jarvis.git
cd better-jarvis
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and add the key for any provider you want to use:

```dotenv
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
```

You only need one key. The `.env` file is intentionally ignored by Git, so never commit your keys.

## Run it

Start the terminal assistant:

```bash
python main.py
```

Or start the desktop app:

```bash
python gui.py
```

Try commands such as:

```text
what's my battery
open notepad
system stats
take a screenshot
```

## Voice input (optional)

Voice input requires PortAudio and PyAudio. On Debian/Ubuntu-based systems:

```bash
sudo apt install portaudio19-dev
pip install pyaudio
```

Then use the **Mic** button for a single command, or enable **Wake word** and say “Jarvis” followed by a command.

## Provider selection

Better Jarvis prefers Gemini for ordinary online requests. For more involved requests, it uses Claude when configured. If those are unavailable, it tries OpenAI, then local Ollama, and finally its built-in rules.

## Adding an MCP server

Jarvis is an [MCP](https://modelcontextprotocol.io/) client: it can use the tools of external MCP servers the same way it uses its built-in tools and skills, with every provider and in both Manual and Automatic mode. Each MCP tool appears as `<server>__<tool>` (for example `jarvis_test__add`).

1. Copy the example config (your copy is gitignored, so pulling new code never overwrites it):

   ```bash
   cp mcp_servers.example.json mcp_servers.json
   ```

   On Windows PowerShell: `Copy-Item mcp_servers.example.json mcp_servers.json`

2. Edit `mcp_servers.json`. It uses the standard `mcpServers` shape, so a config block copied from an MCP server's README works as-is. Jarvis also understands these optional fields per server:

   | Field | Meaning |
   |---|---|
   | `enabled` | `false` to keep a server in the file without starting it (default `true`) |
   | `platforms` | Only start on these OSes: `["linux"]`, `["windows"]`, `["darwin"]` |
   | `allowed_tools` | Only expose these tool names from the server |
   | `timeout` | Seconds per tool call (default 30) |
   | `startup_timeout` | Seconds to connect (default 60; `npx -y` downloads on first run) |

   Use `command` + `args` (+ `env`) for a local stdio server, or `url` (+ `headers`) for a Streamable HTTP server. `${VAR}` is filled in from your environment or `.env`, `~` means your home folder, and `"python"` always means the Python of the active venv.

3. Restart Jarvis (`python main.py`, `python gui.py`, or the API server below). Config changes are only read at startup.

4. Check what connected. With the API server running:

   ```bash
   uvicorn server:app --host 127.0.0.1 --port 8000
   curl -H "Authorization: Bearer $JARVIS_API_TOKEN" http://127.0.0.1:8000/api/mcp/status
   ```

   Each server shows `connected`, `failed` (with a short error), `disabled` or `skipped_platform`, plus its tool names.

To check the whole MCP setup without touching your own config, run `python scripts/verify_mcp.py`. It uses a built-in test server and prints PASS/FAIL per check. Calls are logged to `logs/mcp.log`; see `TROUBLESHOOTING.md` if a server or tool is missing.

**Security:** MCP servers run with your user permissions, and the `run_shell_command` blocklist does **not** apply to MCP tools. Only add servers you trust, and prefer `allowed_tools` and narrow paths (for example, point the filesystem server at one folder).

## Securing the API

The web API can run shell commands, so every `/api/*` route needs a token, and only listed browser origins may call it.

1. Start the API server once. If `.env` has no `JARVIS_API_TOKEN`, the server generates one, saves it to `.env` (this file is gitignored) and prints it once in the terminal. To pick your own instead, set it before starting:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   ```text
   JARVIS_API_TOKEN=<paste the generated value>
   ```

2. Using Jarvis from your phone on the same Wi-Fi? Four small steps:

   1. Find the computer's LAN address: `hostname -I` (Linux) or `ipconfig` (Windows, "IPv4 Address"). Say it is `192.168.1.20`.
   2. In the backend `.env`, allow the page address your phone will open (comma separated if you have several):

      ```text
      JARVIS_ALLOWED_ORIGINS=http://192.168.1.20:5173
      ```

   3. In `frontend/.env`, point the UI at the backend's LAN address:

      ```text
      VITE_API_BASE=http://192.168.1.20:8000
      ```

   4. Start both so they listen on the network, not just this computer:

      ```bash
      uvicorn server:app --host 0.0.0.0 --port 8000
      cd frontend && npm run dev -- --host
      ```

   Then open `http://192.168.1.20:5173` on the phone and paste the token once. The origin must match exactly (scheme, IP and port, no trailing path). `http://localhost:5173` and `http://127.0.0.1:5173` are always allowed. `*` is ignored on purpose. If your router gives the computer a new IP, update both `.env` files.

3. Restart the API server. The web UI asks for the token the first time (paste it once per device).

If the token is shorter than 16 characters (or `.env` could not be written), the API refuses every `/api/*` request instead of running open. `GET /` stays open so the UI can tell whether the backend is up. For command-line calls, send `Authorization: Bearer <token>`:

```bash
curl -H "Authorization: Bearer $JARVIS_API_TOKEN" http://127.0.0.1:8000/api/mcp/status
```

Every rejected request (401) is recorded in `logs/security.log` with the time, client IP, method, path and why it failed (no header, not Bearer, wrong token). The token itself is never written. Repeated lines from an IP you don't recognise mean something on your network is probing the API.

For a quick yes/no on all of this, run `python scripts/verify_security.py` (no server, no API keys needed; prints PASS/FAIL per check and also confirms the shell blocklist still refuses `rm -rf /`). For the full test suite, run `python -m pytest tests/test_security.py` (install pytest first with `pip install pytest`; it is not in `requirements.txt`).

## Security note

This project can execute actions on your computer. Review commands before running them and keep API keys and `JARVIS_API_TOKEN` only in `.env`.

## Roadmap

Planned improvements include:

1. Better Ollama integration, including clear detection and status reporting when Ollama is installed and running.
2. A web version that can be used from any device, including a phone, with a choice of local Ollama, Gemini, OpenAI/ChatGPT, Claude, or other available providers.
3. Account security and suspicious-activity detection so only the owner can access the assistant.
4. Training or personalization capabilities.
5. Built-in web search.
6. A switchable DeepSeek provider option.

## License

No license has been selected yet. Add one before distributing or accepting contributions.
