"""Map LLM tool calls onto real OS actions."""

from __future__ import annotations

import inspect

from actions.system import (
    close_app,
    copy_to_clipboard,
    create_file,
    find_file,
    get_battery_status,
    get_system_stats,
    open_app,
    open_website,
    read_file,
    run_shell_command,
    set_volume,
    take_screenshot,
)

TOOLS = {
    "open_app": open_app,
    "create_file": create_file,
    "get_battery_status": get_battery_status,
    "open_website": open_website,
    "set_volume": set_volume,
    "take_screenshot": take_screenshot,
    "copy_to_clipboard": copy_to_clipboard,
    "find_file": find_file,
    "close_app": close_app,
    "get_system_stats": get_system_stats,
    "read_file": read_file,
    "run_shell_command": run_shell_command,
}


def _filter_args(func, arguments: dict) -> dict:
    params = inspect.signature(func).parameters
    cleaned = {}
    for key, value in (arguments or {}).items():
        if key in params:
            cleaned[key] = value
    return cleaned


def execute(decision: dict) -> dict:
    """Run tool call(s) from get_action(), or return a chat message."""
    try:
        if decision.get("success") is False and not decision.get("calls") and not decision.get("tool"):
            return {
                "success": False,
                "message": decision.get("message") or "The brain could not handle that command.",
            }

        calls = list(decision.get("calls") or [])
        if decision.get("tool"):
            calls = [
                {
                    "tool": decision["tool"],
                    "arguments": decision.get("arguments") or {},
                }
            ]

        if not calls:
            text = (decision.get("text") or decision.get("message") or "").strip()
            if text:
                return {"success": True, "message": text}
            return {"success": True, "message": "I am not sure what to do with that."}

        messages = []
        all_ok = True
        for call in calls:
            name = call.get("tool") or call.get("name")
            func = TOOLS.get(name)
            if func is None:
                all_ok = False
                messages.append(f"Unknown tool: {name}")
                continue
            result = func(**_filter_args(func, call.get("arguments") or {}))
            if not result.get("success"):
                all_ok = False
            messages.append(result.get("message") or str(result))

        return {"success": all_ok, "message": "\n".join(messages)}
    except Exception as exc:
        return {"success": False, "message": f"Executor failed: {exc}"}
