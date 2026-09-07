"""Route a user command to Gemini / Claude / OpenAI / Ollama / local rules."""

from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

from core.tools import SYSTEM_INSTRUCTION, TOOL_DECLARATIONS

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GEMINI_MODELS = (
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-2.5-flash-lite",
)

COMPLEX_HINTS = (
    "explain",
    "analyze",
    "analyse",
    "plan",
    "why",
    "compare",
    "design",
    "refactor",
    "reason",
    "step by step",
)


def _key(name: str) -> str:
    return (os.getenv(name) or "").strip()


def is_online(timeout: float = 1.5) -> bool:
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=timeout).close()
        return True
    except OSError:
        return False


def ollama_available(timeout: float = 0.6) -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=timeout)
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _is_complex(command: str) -> bool:
    text = (command or "").lower()
    if len(text) > 240:
        return True
    return any(hint in text for hint in COMPLEX_HINTS)


def choose_provider(command: str) -> str:
    """Gemini first, then Claude, then OpenAI. Complex + Claude key -> Claude. Offline -> Ollama."""
    online = is_online()
    gemini = _key("GEMINI_API_KEY")
    anthropic = _key("ANTHROPIC_API_KEY")
    openai = _key("OPENAI_API_KEY")

    if not online:
        if ollama_available():
            return "ollama"
        return "local"

    if _is_complex(command) and anthropic:
        return "claude"
    if gemini:
        return "gemini"
    if anthropic:
        return "claude"
    if openai:
        return "openai"
    if ollama_available():
        return "ollama"
    return "local"


def get_action(command: str) -> dict:
    """Return tool call(s) and/or a chat message. Never raises."""
    text = (command or "").strip()
    if not text:
        return {"success": False, "message": "Empty command."}

    provider = choose_provider(text)
    try:
        if provider == "gemini":
            return _from_gemini(text)
        if provider == "claude":
            return _from_claude(text)
        if provider == "openai":
            return _from_openai(text)
        if provider == "ollama":
            return _from_ollama(text)
        return _from_local(text)
    except Exception as exc:
        local = _from_local(text)
        if local.get("tool") or local.get("calls"):
            local["message"] = f"{provider} failed ({exc}); used local fallback."
            return local
        return {
            "success": False,
            "message": f"{provider} failed: {exc}",
            "provider": provider,
        }


def _openai_style_tools() -> list[dict]:
    tools = []
    for decl in TOOL_DECLARATIONS:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": decl["name"],
                    "description": decl["description"],
                    "parameters": decl.get("parameters") or {"type": "object", "properties": {}},
                },
            }
        )
    return tools


def _from_gemini(command: str) -> dict:
    import google.generativeai as genai

    genai.configure(api_key=_key("GEMINI_API_KEY"))
    last_error = None
    for model_name in GEMINI_MODELS:
        try:
            model = genai.GenerativeModel(
                model_name=model_name,
                tools=[{"function_declarations": TOOL_DECLARATIONS}],
                system_instruction=SYSTEM_INSTRUCTION,
            )
            response = model.generate_content(command)
            return _normalize_gemini(response, model_name)
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(last_error or "No Gemini model worked.")


def _normalize_gemini(response, model_name: str) -> dict:
    calls = []
    texts = []
    try:
        parts = response.candidates[0].content.parts
    except Exception:
        parts = []
    for part in parts:
        fc = getattr(part, "function_call", None)
        if fc and getattr(fc, "name", None):
            args = {}
            raw_args = getattr(fc, "args", None) or {}
            try:
                args = dict(raw_args)
            except Exception:
                args = json.loads(json.dumps(raw_args))
            calls.append({"tool": fc.name, "arguments": args})
        text = getattr(part, "text", None)
        if text:
            texts.append(text)
    if calls:
        return {
            "success": True,
            "provider": "gemini",
            "model": model_name,
            "calls": calls,
            "text": "\n".join(texts).strip(),
        }
    message = "\n".join(texts).strip() or getattr(response, "text", None) or "No response from Gemini."
    return {"success": True, "provider": "gemini", "model": model_name, "text": message}


def _from_claude(command: str) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=_key("ANTHROPIC_API_KEY"))
    tools = []
    for decl in TOOL_DECLARATIONS:
        tools.append(
            {
                "name": decl["name"],
                "description": decl["description"],
                "input_schema": decl.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=SYSTEM_INSTRUCTION,
        tools=tools,
        messages=[{"role": "user", "content": command}],
    )
    calls = []
    texts = []
    for block in message.content:
        btype = getattr(block, "type", None)
        if btype == "tool_use":
            calls.append({"tool": block.name, "arguments": dict(block.input or {})})
        elif btype == "text":
            texts.append(block.text or "")
    if calls:
        return {"success": True, "provider": "claude", "calls": calls, "text": "\n".join(texts).strip()}
    return {
        "success": True,
        "provider": "claude",
        "text": "\n".join(texts).strip() or "No response from Claude.",
    }


def _from_openai(command: str) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=_key("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": command},
        ],
        tools=_openai_style_tools(),
    )
    message = response.choices[0].message
    calls = []
    for tool_call in message.tool_calls or []:
        args = tool_call.function.arguments or "{}"
        parsed = json.loads(args) if isinstance(args, str) else dict(args)
        calls.append({"tool": tool_call.function.name, "arguments": parsed})
    if calls:
        return {
            "success": True,
            "provider": "openai",
            "calls": calls,
            "text": message.content or "",
        }
    return {"success": True, "provider": "openai", "text": message.content or "No response from OpenAI."}


def _from_ollama(command: str) -> dict:
    payload = {
        "model": os.getenv("OLLAMA_MODEL") or "llama3.2",
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION + " " + _ollama_json_hint()},
            {"role": "user", "content": command},
        ],
    }
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    content = ((body.get("message") or {}).get("content") or "").strip()
    parsed = _extract_json(content)
    if parsed and (parsed.get("tool") or parsed.get("calls")):
        parsed["success"] = True
        parsed["provider"] = "ollama"
        return parsed
    local = _from_local(command)
    if local.get("tool") or local.get("calls"):
        local["provider"] = "ollama+local"
        return local
    return {"success": True, "provider": "ollama", "text": content or "Ollama returned an empty reply."}


def _ollama_json_hint() -> str:
    names = ", ".join(d["name"] for d in TOOL_DECLARATIONS)
    return (
        "If you need a PC action, reply with ONLY JSON like "
        '{"tool":"open_app","arguments":{"app_name":"firefox"}} '
        f"Tools: {names}. If chatting, JSON {{\"tool\": null, \"message\": \"...\"}}."
    )


def _extract_json(text: str) -> dict | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _from_local(command: str) -> dict:
    """Tiny keyword router so Jarvis still works with no API keys."""
    text = command.strip()
    lower = text.lower()

    if any(w in lower for w in ("battery", "charge")):
        return _local_call("get_battery_status")
    if re.search(r"\b(system stats|cpu|ram|memory usage)\b", lower):
        return _local_call("get_system_stats")
    if "screenshot" in lower:
        return _local_call("take_screenshot")
    if lower.startswith("volume ") or "set volume" in lower or "volume to" in lower:
        number = _first_int(lower)
        if number is None:
            return {"success": False, "message": "Say a volume from 0 to 100.", "provider": "local"}
        return _local_call("set_volume", {"level": number})
    if lower.startswith("copy "):
        return _local_call("copy_to_clipboard", {"text": text[5:].strip()})
    if lower.startswith("find ") or lower.startswith("search for "):
        name = re.sub(r"^(find|search for)\s+", "", text, flags=re.I).strip()
        return _local_call("find_file", {"name": name})
    if lower.startswith("read "):
        path = text.split(" ", 1)[1].strip()
        return _local_call("read_file", {"path": path})
    if lower.startswith("create file ") or lower.startswith("make file "):
        rest = re.sub(r"^(create file|make file)\s+", "", text, flags=re.I)
        path, _, content = rest.partition(" ")
        return _local_call("create_file", {"path": path, "content": content})
    if lower.startswith("close "):
        return _local_call("close_app", {"app_name": text.split(" ", 1)[1]})
    if lower.startswith("open "):
        target = text.split(" ", 1)[1].strip()
        if _looks_like_url(target):
            return _local_call("open_website", {"url": target})
        return _local_call("open_app", {"app_name": target})
    if any(w in lower for w in ("hello", "hi jarvis", "hey jarvis")):
        return {
            "success": True,
            "provider": "local",
            "text": "Hello. I am running on local rules until you add an API key in .env.",
        }
    return {
        "success": False,
        "provider": "local",
        "message": (
            "No cloud API key is set (and Ollama is not running), so I only understand simple "
            "phrases like 'what's my battery', 'open notepad', 'open github.com', "
            "'screenshot', or 'system stats'. Add GEMINI_API_KEY to .env for full language."
        ),
    }


def _looks_like_url(text: str) -> bool:
    t = text.lower()
    return t.startswith("http://") or t.startswith("https://") or "." in t.split(" ")[0]


def _first_int(text: str) -> int | None:
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else None


def _local_call(tool: str, arguments: dict | None = None) -> dict:
    return {
        "success": True,
        "provider": "local",
        "calls": [{"tool": tool, "arguments": arguments or {}}],
    }


def handle(command: str) -> dict:
    """Brain + executor in one call (used by CLI, GUI, and voice)."""
    from core.executor import execute

    decision = get_action(command)
    result = execute(decision)
    provider = decision.get("provider") or "unknown"
    result["provider"] = provider
    return result
