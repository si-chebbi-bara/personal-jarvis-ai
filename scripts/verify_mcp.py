"""Re-runnable end-to-end checks for Jarvis's MCP client support.

    python scripts/verify_mcp.py

Uses its own temporary config files (never your mcp_servers.json) and the
test server in tests/fixtures/mcp_test_server.py. Prints one PASS/FAIL line
per check plus a summary, and exits non-zero if anything failed. Works on
Linux and Windows. Needs no API keys: the Claude/OpenAI checks use stub
clients, and nothing here calls a real LLM.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import warnings
from pathlib import Path
from types import SimpleNamespace

warnings.filterwarnings("ignore")  # google.generativeai's deprecation banner

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import psutil  # noqa: E402

from core import mcp_client  # noqa: E402
from core.mcp_client import manager  # noqa: E402
from core.mcp_config import LOG_PATH, current_platform, get_logger  # noqa: E402

FIXTURE = "tests/fixtures/mcp_test_server.py"
SERVER_STDERR_LOG = mcp_client.SERVER_STDERR_LOG
START_TIME = time.time()
TMP = Path(tempfile.mkdtemp(prefix="jarvis-verify-mcp-"))
SECRET = "jv-" + secrets.token_hex(8)  # must never show up in the logs
os.environ["JARVIS_VERIFY_TOKEN"] = SECRET

# MCP warnings normally also go to the console; here they'd just be noise
# (several checks break servers on purpose). They still go to logs/mcp.log.
for handler in get_logger().handlers:
    if type(handler) is logging.StreamHandler:
        handler.setLevel(logging.CRITICAL + 1)

results: list[tuple[str, bool, str]] = []


def check(label: str):
    """Decorator: run a check function, record PASS/FAIL, never let it crash the script."""

    def wrap(fn):
        try:
            ok, evidence = fn()
        except Exception as exc:
            ok, evidence = False, f"exception: {exc!r}\n{traceback.format_exc(limit=3)}"
        results.append((label, bool(ok), evidence))
        print(f"{'PASS' if ok else 'FAIL'}  {label}  -- {evidence}", flush=True)
        return fn

    return wrap


def write_config(name: str, servers: dict) -> Path:
    path = TMP / name
    path.write_text(json.dumps({"mcpServers": servers}, indent=2), encoding="utf-8")
    return path


def use_config(path: Path | None) -> None:
    manager.configure(path)
    manager.ensure_started()


def good_server(**extra) -> dict:
    return {"command": "python", "args": [FIXTURE], **extra}


def fixture_processes() -> list[int]:
    """PIDs of test-server processes started by this run (other Jarvis instances are ignored)."""
    pids = []
    for proc in psutil.process_iter(["cmdline", "create_time"]):
        try:
            cmd = proc.info["cmdline"] or []
            if (proc.info["create_time"] or 0) >= START_TIME - 1 and any(Path(a).name == "mcp_test_server.py" for a in cmd):
                pids.append(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


def status_of(name: str) -> dict:
    return next((s for s in manager.status() if s["name"] == name), {})


def log_since(offset: int, path: Path = LOG_PATH) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read().decode("utf-8", errors="replace")


LOG_OFFSET = LOG_PATH.stat().st_size if LOG_PATH.exists() else 0
STDERR_OFFSET = SERVER_STDERR_LOG.stat().st_size if SERVER_STDERR_LOG.exists() else 0

from core.executor import TOOLS, execute  # noqa: E402
from core.tools import TOOL_DECLARATIONS, get_all_tool_declarations, get_gemini_tool_declarations  # noqa: E402

print(f"Jarvis MCP verification  (python {sys.version.split()[0]}, {current_platform()}, temp dir {TMP})\n")

# ----------------------------------------------------------------- main config
MAIN = write_config(
    "main.json",
    {
        "jarvis_test": good_server(timeout=3, env={"JARVIS_VERIFY_SECRET": "${JARVIS_VERIFY_TOKEN}"}),
        "broken_cmd": {"command": "definitely-not-a-real-command-xyz"},
        "crashes": {"command": "python", "args": ["-c", "import sys; sys.exit(3)"]},
    },
)
use_config(MAIN)


@check("1. test server connects; tools listed as jarvis_test__*")
def _():
    st = status_of("jarvis_test")
    expected = {f"jarvis_test__{t}" for t in ("add", "echo", "slow", "fail", "complex_args")}
    return st.get("status") == "connected" and set(st.get("tools", [])) == expected, f"status={st.get('status')} tools={st.get('tools')}"


@check("2. add(2, 3) through core/executor.py")
def _():
    r = execute({"calls": [{"tool": "jarvis_test__add", "arguments": {"a": 2, "b": 3}}]})
    call = r["calls"][0]
    return call["success"] is True and "5" in (call["output"] or ""), f"success={call['success']} output={call['output']!r}"


@check("3. echo('pineapple')")
def _():
    call = execute({"calls": [{"tool": "jarvis_test__echo", "arguments": {"text": "pineapple"}}]})["calls"][0]
    # Also send the config's ${VAR} secret as an argument: check 14 confirms the log redacts it.
    secret_call = execute({"calls": [{"tool": "jarvis_test__echo", "arguments": {"text": SECRET}}]})["calls"][0]
    ok = call["success"] and call["output"] == "pineapple" and secret_call["output"] == SECRET
    return ok, f"success={call['success']} output={call['output']!r}"


@check("4. fail() -> success false, no exception")
def _():
    call = execute({"calls": [{"tool": "jarvis_test__fail", "arguments": {}}]})["calls"][0]
    return call["success"] is False, f"success={call['success']} message={call['message']!r}"


@check("5. slow(10s) with timeout=3s -> timeout, Jarvis still responsive")
def _():
    t0 = time.monotonic()
    call = execute({"calls": [{"tool": "jarvis_test__slow", "arguments": {"seconds": 10}}]})["calls"][0]
    took = time.monotonic() - t0
    after = execute({"calls": [{"tool": "jarvis_test__echo", "arguments": {"text": "still here"}}]})["calls"][0]
    ok = call["success"] is False and "timed out" in call["message"] and took < 8 and after["output"] == "still here"
    return ok, f"message={call['message']!r} took={took:.1f}s then echo -> {after['output']!r}"


@check("6. unknown tool name -> clean success false")
def _():
    r = execute({"calls": [{"tool": "jarvis_test__nope", "arguments": {}}]})
    call = r["calls"][0]
    return r["success"] is False and call["success"] is False and "Unknown tool" in call["message"], f"message={call['message']!r}"


@check("7. broken servers next to a good one: broken = failed, good still works")
def _():
    a, b = status_of("broken_cmd"), status_of("crashes")
    call = execute({"calls": [{"tool": "jarvis_test__add", "arguments": {"a": 1, "b": 1}}]})["calls"][0]
    ok = a.get("status") == "failed" and b.get("status") == "failed" and call["output"] == "2"
    return ok, f"broken_cmd={a.get('status')} ({a.get('error')}); crashes={b.get('status')} ({b.get('error')}); add(1,1)={call['output']!r}"


@check("7b. server process dies mid-session -> success false, status failed")
def _():
    victims = fixture_processes()
    for pid in victims:
        psutil.Process(pid).kill()
    time.sleep(0.5)
    call = execute({"calls": [{"tool": "jarvis_test__echo", "arguments": {"text": "hello?"}}]})["calls"][0]
    st = status_of("jarvis_test")
    ok = bool(victims) and call["success"] is False and st.get("status") == "failed"
    return ok, f"killed={victims} call.success={call['success']} message={call['message']!r} status={st.get('status')}"


@check("7c. Streamable HTTP transport (+ ${VAR} in url)")
def _():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    os.environ["JARVIS_VERIFY_PORT"] = str(port)
    proc = subprocess.Popen([sys.executable, FIXTURE, "--http", str(port)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.2)
        use_config(write_config("http.json", {"jarvis_http": {"url": "http://127.0.0.1:${JARVIS_VERIFY_PORT}/mcp", "headers": {"X-Test": "${JARVIS_VERIFY_TOKEN}"}}}))
        st = status_of("jarvis_http")
        call = execute({"calls": [{"tool": "jarvis_http__add", "arguments": {"a": 40, "b": 2}}]})["calls"][0]
        manager.shutdown()
        return st.get("status") == "connected" and call["output"] == "42", f"status={st.get('status')} error={st.get('error')} add(40,2)={call['output']!r}"
    finally:
        proc.kill()
        proc.wait(timeout=10)


@check("8. no config file -> 0 MCP tools, no error")
def _():
    use_config(TMP / "does-not-exist.json")
    n_all = len(get_all_tool_declarations())
    return manager.list_tools() == [] and manager.status() == [] and n_all == len(TOOL_DECLARATIONS), f"mcp tools=0, total declarations={n_all}"


@check("8b. invalid JSON -> 0 MCP tools, exactly one log line")
def _():
    bad = TMP / "invalid.json"
    bad.write_text('{"mcpServers": {"x": ', encoding="utf-8")
    before = log_since(LOG_OFFSET).count("invalid.json")
    use_config(bad)
    lines = [line for line in log_since(LOG_OFFSET).splitlines() if "invalid.json" in line]
    new = len(lines) - before
    return manager.list_tools() == [] and new == 1, f"mcp tools={len(manager.list_tools())} new log lines={new}: {lines[-1] if lines else ''}"


@check("9. enabled:false and non-matching platforms -> not started")
def _():
    marker_off, marker_os = TMP / "ran-disabled", TMP / "ran-platform"
    other_os = "darwin" if current_platform() != "darwin" else "linux"
    use_config(
        write_config(
            "skip.json",
            {
                "off": {"command": "python", "args": ["-c", f"open(r'{marker_off}', 'w')"], "enabled": False},
                "elsewhere": {"command": "python", "args": ["-c", f"open(r'{marker_os}', 'w')"], "platforms": [other_os]},
            },
        )
    )
    time.sleep(0.5)
    a, b = status_of("off"), status_of("elsewhere")
    ok = a.get("status") == "disabled" and b.get("status") == "skipped_platform" and not marker_off.exists() and not marker_os.exists()
    return ok, f"off={a.get('status')} elsewhere={b.get('status')} (platforms=[{other_os}]) processes ran={marker_off.exists() or marker_os.exists()}"


@check("10. name collision with a built-in/skill -> MCP tool skipped, built-in still works")
def _():
    # Pretend a skill named exactly like an MCP tool exists.
    TOOLS["jarvis_test__echo"] = lambda text="": {"success": True, "message": f"BUILTIN:{text}"}
    try:
        use_config(write_config("collide.json", {"jarvis_test": good_server()}))
        st = status_of("jarvis_test")
        call = execute({"calls": [{"tool": "jarvis_test__echo", "arguments": {"text": "hi"}}]})["calls"][0]
        warned = "is a built-in/skill name" in log_since(LOG_OFFSET)
        ok = "jarvis_test__echo" not in st.get("tools", []) and "echo" in st.get("skipped_tools", []) and call["message"] == "BUILTIN:hi" and warned
        return ok, f"skipped={st.get('skipped_tools')} executor -> {call['message']!r} warning logged={warned}"
    finally:
        del TOOLS["jarvis_test__echo"]


@check("11. allowed_tools filters")
def _():
    use_config(write_config("allow.json", {"jarvis_test": good_server(allowed_tools=["add", "echo"])}))
    tools = status_of("jarvis_test").get("tools")
    return tools == ["jarvis_test__add", "jarvis_test__echo"], f"tools={tools}"


@check("12. Gemini sanitizer: complex_args converts to a Gemini-valid shape")
def _():
    from google.generativeai.types import content_types

    use_config(write_config("gemini.json", {"jarvis_test": good_server()}))
    gemini = {d["name"]: d for d in get_gemini_tool_declarations()}
    expected = {
        "type": "object",
        "properties": {"mode": {"type": "string", "enum": ["fast", "safe"]}, "note": {"type": "string", "nullable": True}},
    }
    got = gemini["jarvis_test__complex_args"].get("parameters")
    no_params = "parameters" not in gemini["jarvis_test__fail"]
    content_types.to_function_library([{"function_declarations": list(gemini.values())}])  # raises if invalid
    raw = next(d for d in get_all_tool_declarations() if d["name"] == "jarvis_test__complex_args")
    try:
        content_types.to_function_library([{"function_declarations": [raw]}])
        raw_rejected = False
    except Exception:
        raw_rejected = True
    ok = got == expected and no_params and raw_rejected
    return ok, f"parameters={json.dumps(got)} | fail() has no parameters={no_params} | all {len(gemini)} accepted by google.generativeai | unsanitized rejected={raw_rejected}"


@check("12b. Gemini sanitizer edge cases ($ref, type lists, unsupported optional arg)")
def _():
    from core.mcp_schema import SchemaError, to_gemini_parameters

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "$defs": {"Point": {"type": "object", "title": "P", "properties": {"x": {"type": "number", "default": 0}}}},
        "properties": {
            "where": {"$ref": "#/$defs/Point", "description": "a point"},
            "tag": {"type": ["string", "null"], "examples": ["a"], "format": "uri"},
            "level": {"enum": [1, 2, 3], "type": "integer"},
            "extra": {"type": "object", "additionalProperties": True},  # free-form, optional -> dropped
        },
        "required": ["where"],
    }
    out = to_gemini_parameters(schema)
    expected = {
        "type": "object",
        "properties": {
            "where": {"type": "object", "description": "a point", "properties": {"x": {"type": "number"}}},
            "tag": {"type": "string", "nullable": True},
            "level": {"type": "integer", "description": "Allowed values: 1, 2, 3."},
        },
        "required": ["where"],
    }
    try:
        to_gemini_parameters({"type": "object", "properties": {"x": {"anyOf": [{"type": "string"}, {"type": "integer"}]}}, "required": ["x"]})
        unconvertible_raises = False
    except SchemaError:
        unconvertible_raises = True
    return out == expected and unconvertible_raises, f"converted ok={out == expected}, unconvertible required arg raises={unconvertible_raises}"


@check("12c. Claude + OpenAI declaration conversion and tool round-trip (stub clients)")
def _():
    import anthropic
    import openai

    from core import llm_brain

    seen = {}

    class FakeAnthropic:
        def __init__(self, **_):
            self.messages = SimpleNamespace(create=self._create)

        def _create(self, **kwargs):
            seen["claude"] = kwargs["tools"]
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", id="t1", name="jarvis_test__add", input={"a": 20, "b": 22})])

    class FakeOpenAI:
        def __init__(self, **_):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            seen["openai"] = kwargs["tools"]
            call = SimpleNamespace(id="c1", function=SimpleNamespace(name="jarvis_test__echo", arguments='{"text": "pineapple"}'))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=""))])

    real = anthropic.Anthropic, openai.OpenAI
    anthropic.Anthropic, openai.OpenAI = FakeAnthropic, FakeOpenAI
    try:
        claude_out = execute(llm_brain._from_claude("add 20 and 22"))["calls"][0]
        openai_out = execute(llm_brain._from_openai("echo pineapple"))["calls"][0]
    finally:
        anthropic.Anthropic, openai.OpenAI = real
    c_tool = next(t for t in seen["claude"] if t["name"] == "jarvis_test__complex_args")
    o_tool = next(t for t in seen["openai"] if t["function"]["name"] == "jarvis_test__complex_args")
    ok = (
        claude_out["output"] == "42"
        and openai_out["output"] == "pineapple"
        and c_tool["input_schema"]["type"] == "object"
        and "enum" in c_tool["input_schema"]["properties"]["mode"]
        and o_tool["function"]["parameters"]["type"] == "object"
        and len(seen["claude"]) == len(seen["openai"]) == len(TOOL_DECLARATIONS) + 5
    )
    return ok, f"claude add -> {claude_out['output']!r}, openai echo -> {openai_out['output']!r}, {len(seen['claude'])} tools sent to each"


@check("12d. Automatic mode loop sees and runs MCP tools (stub Claude)")
def _():
    import anthropic

    from core import agent_loop

    turns = iter(
        [
            [SimpleNamespace(type="tool_use", id="t1", name="jarvis_test__echo", input={"text": "pineapple"})],
            [SimpleNamespace(type="text", text="You said pineapple.")],
        ]
    )

    class FakeAnthropic:
        def __init__(self, **_):
            self.messages = SimpleNamespace(create=lambda **kw: SimpleNamespace(content=next(turns)))

    real = anthropic.Anthropic, agent_loop.get_context, agent_loop.log_exchange
    anthropic.Anthropic = FakeAnthropic
    agent_loop.get_context = lambda: ""  # keep memory.md untouched
    agent_loop.log_exchange = lambda *a, **k: None
    try:
        events = list(agent_loop.run_auto("echo pineapple then summarise", forced_provider="claude"))
    finally:
        anthropic.Anthropic, agent_loop.get_context, agent_loop.log_exchange = real
    steps = [e for e in events if e["type"] == "step"]
    final = events[-1]
    ok = steps and steps[0]["tool"] == "jarvis_test__echo" and steps[0]["output"] == "pineapple" and final["type"] == "final" and final["success"]
    return ok, f"events={[e['type'] for e in events]} step={steps[0]['tool'] if steps else None} final={final.get('message')!r}"


@check("13. after shutdown: no leftover mcp_test_server.py processes")
def _():
    manager.shutdown()
    time.sleep(0.5)
    left = fixture_processes()
    return left == [], f"leftover pids={left} (checked with psutil, same on Linux and Windows)"


@check("14. logs/mcp.log has the calls above and no secrets")
def _():
    text = log_since(LOG_OFFSET)
    calls = [line for line in text.splitlines() if " CALL " in line]
    tools = {t for t in ("add", "echo", "fail", "slow") if any(f"tool={t} " in line for line in calls)}
    leaked = SECRET in text or SECRET in log_since(STDERR_OFFSET, SERVER_STDERR_LOG)
    redacted = any('tool=echo' in line and '"text": "***"' in line for line in calls)
    ok = tools == {"add", "echo", "fail", "slow"} and not leaked and redacted
    return ok, f"{len(calls)} CALL lines, tools seen={sorted(tools)}, secret leaked={leaked}, secret arg logged as ***={redacted}; e.g. {calls[0].split('] ', 1)[-1] if calls else ''}"


@check("15. regression: 14 built-ins/skills, get_weather loads, shell blocklist still rejects rm -rf /")
def _():
    from actions.system import run_shell_command

    names = [d["name"] for d in TOOL_DECLARATIONS]
    blocked = run_shell_command("rm -rf /")  # rejected by the blocklist before anything runs
    ok = len(names) == 14 and "get_weather" in names and "get_weather" in TOOLS and blocked["success"] is False and "blocked" in (blocked.get("error") or "")
    return ok, f"{len(names)} built-ins/skills, get_weather loaded={'get_weather' in TOOLS}, rm -rf / -> {blocked['message']!r}"


# ------------------------------------------------------------------- summary
manager.shutdown()
failed = [label for label, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
if failed:
    print("FAILED: " + "; ".join(failed))
sys.exit(1 if failed else 0)
