"""Automatic mode: a bounded multi-step tool loop on top of llm_brain + executor.

Manual mode (llm_brain.handle) is one provider call -> run its tool calls -> reply.
Automatic mode keeps a running conversation instead: call the provider, run
any tool calls it asks for, send the results back as the next turn, and repeat
until it answers in plain text or MAX_ITERATIONS provider calls have been made.

run_auto() is a generator of progress events so the web API can stream each
step as it completes (see server.py's POST /api/command/auto):

    {"type": "start",  "provider", "max_iterations"}
    {"type": "notice", "message"}                      provider can't loop
    {"type": "turn",   "iteration", "tools"}           tools about to run
    {"type": "step",   "iteration", "tool", "arguments", "success",
                       "message", "output", "error"}   one per tool call
    {"type": "final",  "success", "message", "provider", "iterations", "calls"}

A step's tool fields are exactly one entry of executor.execute()'s `calls`
list, so the frontend's Activity tab can consume them unchanged. Tools run
through executor.execute(), so run_shell_command's blocklist, timeout and
audit log apply to every step exactly as they do in Manual mode.
"""

from __future__ import annotations

import json
from typing import Iterator

from core.executor import execute
from core.llm_brain import (
    CLAUDE_MODEL,
    GEMINI_MODELS,
    OPENAI_MODEL,
    _claude_tools,
    _key,
    _openai_style_tools,
    choose_provider,
    handle,
)
from core.memory import get_context, log_exchange
from core.tools import SYSTEM_INSTRUCTION, TOOL_DECLARATIONS

MAX_ITERATIONS = 8

# Providers with real multi-turn tool use. Ollama (JSON-in-text) and the local
# keyword router can only produce one decision, so they fall back to Manual.
LOOP_PROVIDERS = ("gemini", "claude", "openai")

# Tool output sent back to the model is capped so one noisy shell command
# can't blow the context window on the next turn.
RESULT_CHAR_LIMIT = 4000

AUTO_INSTRUCTION = (
    SYSTEM_INSTRUCTION
    + " You are in Automatic mode: the user gives you a goal, not a single command. "
    "Work toward it step by step — call a tool, look at its result, then either call "
    "the next tool you need or, once the goal is done (or can't be done), reply with a "
    f"short final answer and no tool call. You have at most {MAX_ITERATIONS} turns, so "
    "don't repeat a call whose result you already have."
)


def _tool_result_payload(entry: dict) -> dict:
    """The part of an executor call record the model gets to see."""
    payload = {"success": entry.get("success"), "message": entry.get("message") or ""}
    if entry.get("output"):
        payload["output"] = entry["output"]
    if entry.get("error"):
        payload["error"] = entry["error"]
    for key in ("message", "output", "error"):
        value = payload.get(key)
        if isinstance(value, str) and len(value) > RESULT_CHAR_LIMIT:
            payload[key] = value[:RESULT_CHAR_LIMIT] + "\n…(truncated)"
    return payload


class _GeminiSession:
    """Multi-turn Gemini conversation: model turns and function responses are
    appended to `contents` and the whole history is resent each turn."""

    def __init__(self, prompt: str):
        import google.generativeai as genai

        genai.configure(api_key=_key("GEMINI_API_KEY"))
        self._genai = genai
        self.contents: list = [{"role": "user", "parts": [{"text": prompt}]}]
        self.model_name: str | None = None

    def next_turn(self) -> tuple[list[dict], str]:
        # Same fallback order as llm_brain._from_gemini, but once a model has
        # answered, stick with it so the conversation stays on one model.
        names = [self.model_name] if self.model_name else list(GEMINI_MODELS)
        last_error = None
        for name in names:
            try:
                model = self._genai.GenerativeModel(
                    model_name=name,
                    tools=[{"function_declarations": TOOL_DECLARATIONS}],
                    system_instruction=AUTO_INSTRUCTION,
                )
                response = model.generate_content(self.contents)
                content = response.candidates[0].content
                self.model_name = name
                break
            except Exception as exc:
                last_error = exc
        else:
            raise RuntimeError(last_error or "No Gemini model worked.")

        self.contents.append(content)
        calls, texts = [], []
        for part in content.parts:
            fc = getattr(part, "function_call", None)
            if fc and getattr(fc, "name", None):
                try:
                    args = dict(fc.args or {})
                except Exception:
                    args = json.loads(json.dumps(fc.args or {}))
                calls.append({"id": None, "tool": fc.name, "arguments": args})
            if getattr(part, "text", None):
                texts.append(part.text)
        return calls, "\n".join(texts).strip()

    def add_results(self, results: list[tuple[dict, dict]]) -> None:
        parts = [
            {"function_response": {"name": call["tool"], "response": _tool_result_payload(entry)}}
            for call, entry in results
        ]
        self.contents.append({"role": "user", "parts": parts})


class _ClaudeSession:
    def __init__(self, prompt: str):
        import anthropic

        self.client = anthropic.Anthropic(api_key=_key("ANTHROPIC_API_KEY"))
        self.messages: list = [{"role": "user", "content": prompt}]

    def next_turn(self) -> tuple[list[dict], str]:
        message = self.client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=AUTO_INSTRUCTION,
            tools=_claude_tools(),
            messages=self.messages,
        )
        self.messages.append({"role": "assistant", "content": message.content})
        calls, texts = [], []
        for block in message.content:
            btype = getattr(block, "type", None)
            if btype == "tool_use":
                calls.append({"id": block.id, "tool": block.name, "arguments": dict(block.input or {})})
            elif btype == "text":
                texts.append(block.text or "")
        return calls, "\n".join(texts).strip()

    def add_results(self, results: list[tuple[dict, dict]]) -> None:
        self.messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "content": json.dumps(_tool_result_payload(entry)),
                        "is_error": not entry.get("success"),
                    }
                    for call, entry in results
                ],
            }
        )


class _OpenAISession:
    def __init__(self, prompt: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=_key("OPENAI_API_KEY"))
        self.messages: list = [
            {"role": "system", "content": AUTO_INSTRUCTION},
            {"role": "user", "content": prompt},
        ]

    def next_turn(self) -> tuple[list[dict], str]:
        response = self.client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=self.messages,
            tools=_openai_style_tools(),
        )
        message = response.choices[0].message
        calls = []
        for tool_call in message.tool_calls or []:
            args = tool_call.function.arguments or "{}"
            parsed = json.loads(args) if isinstance(args, str) else dict(args)
            calls.append({"id": tool_call.id, "tool": tool_call.function.name, "arguments": parsed})
        turn = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            turn["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
                }
                for tc in message.tool_calls
            ]
        self.messages.append(turn)
        return calls, (message.content or "").strip()

    def add_results(self, results: list[tuple[dict, dict]]) -> None:
        for call, entry in results:
            self.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(_tool_result_payload(entry)),
                }
            )


SESSIONS = {"gemini": _GeminiSession, "claude": _ClaudeSession, "openai": _OpenAISession}


def _run_one(call: dict) -> dict:
    """Run a single tool call through the normal executor and return its call record."""
    result = execute({"calls": [{"tool": call["tool"], "arguments": call["arguments"]}]})
    if result.get("calls"):
        return result["calls"][0]
    # execute() only omits `calls` when it hit an internal exception.
    return {
        "tool": call["tool"],
        "arguments": call["arguments"],
        "success": False,
        "message": result.get("message") or "Executor failed.",
        "output": None,
        "error": None,
    }


def _final(success: bool, message: str, provider: str, iterations: int, steps: list[dict]) -> dict:
    return {
        "type": "final",
        "success": success,
        "message": message,
        "provider": provider,
        "iterations": iterations,
        "calls": steps,
    }


def run_auto(command: str, forced_provider: str | None = None) -> Iterator[dict]:
    """Run `command` as a goal and yield progress events. Never raises.

    Closing the generator early (the web client pressed Stop) ends the loop
    before the next provider call or tool call starts — every provider call
    and every tool call is followed by a yield.
    """
    text = (command or "").strip()
    if not text:
        yield _final(False, "Empty command.", "unknown", 0, [])
        return

    provider = choose_provider(text, forced_provider)

    if provider not in LOOP_PROVIDERS:
        yield {
            "type": "notice",
            "provider": provider,
            "message": (
                f"Automatic mode needs Gemini, Claude, or OpenAI — {provider} can't do "
                "multi-step tool use, so this ran once as a normal Manual command."
            ),
        }
        result = handle(text, forced_provider)  # logs the exchange itself
        steps = list(result.get("calls") or [])
        for entry in steps:
            yield {"type": "step", "iteration": 1, **entry}
        yield _final(
            bool(result.get("success")),
            result.get("message") or "",
            result.get("provider") or provider,
            1,
            steps,
        )
        return

    yield {"type": "start", "provider": provider, "max_iterations": MAX_ITERATIONS}

    try:
        context = get_context()
    except Exception:
        context = ""  # a broken memory file shouldn't block the loop
    prompt = f"{context}\n\nUser: {text}" if context else text
    steps: list[dict] = []
    final_message = ""
    try:
        try:
            session = SESSIONS[provider](prompt)
        except Exception as exc:
            final_message = f"{provider} failed: {exc}"
            yield _final(False, final_message, provider, 0, steps)
            return

        last_text = ""
        for iteration in range(1, MAX_ITERATIONS + 1):
            try:
                calls, reply = session.next_turn()
            except Exception as exc:
                final_message = f"{provider} failed on step {iteration}: {exc}"
                yield _final(False, final_message, provider, iteration, steps)
                return

            if reply:
                last_text = reply
            if not calls:
                final_message = reply or "Done."
                yield _final(True, final_message, provider, iteration, steps)
                return

            # Yield before running anything, so a Stop that arrived during the
            # provider call cancels the loop before this turn's tools run.
            yield {"type": "turn", "iteration": iteration, "tools": [c["tool"] for c in calls]}

            results = []
            for call in calls:
                entry = _run_one(call)
                steps.append(entry)
                results.append((call, entry))
                yield {"type": "step", "iteration": iteration, **entry}
            session.add_results(results)

        final_message = (
            f"Stopped after the {MAX_ITERATIONS}-step limit before Jarvis gave a final answer."
            + (f"\n\nLast note from the model: {last_text}" if last_text else "")
        )
        yield _final(False, final_message, provider, MAX_ITERATIONS, steps)
    except GeneratorExit:
        final_message = f"(stopped by user after {len(steps)} tool call(s))"
        raise
    finally:
        try:
            # memory.md's log is one line per turn, so flatten any newlines.
            log_exchange(text, " ".join(final_message.split()))
        except Exception:
            pass
