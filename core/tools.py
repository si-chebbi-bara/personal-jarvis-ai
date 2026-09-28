"""Shared tool schema for LLM function calling."""

from __future__ import annotations

TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": "Open a desktop application. Use 'notepad' or 'editor' for the default text editor.",
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "App name, .desktop id, or file path.",
                }
            },
            "required": ["app_name"],
        },
    },
    {
        "name": "create_file",
        "description": "Create or overwrite a text file on disk.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Full file path."},
                "content": {"type": "string", "description": "File contents."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "get_battery_status",
        "description": "Get laptop battery percent and charging state.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "open_website",
        "description": "Open a website in the default browser.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL or search query."}
            },
            "required": ["url"],
        },
    },
    {
        "name": "set_volume",
        "description": "Set speaker volume from 0 to 100.",
        "parameters": {
            "type": "object",
            "properties": {
                "level": {"type": "integer", "description": "Volume 0-100."}
            },
            "required": ["level"],
        },
    },
    {
        "name": "take_screenshot",
        "description": "Capture the screen to a PNG file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Optional save path."}
            },
        },
    },
    {
        "name": "copy_to_clipboard",
        "description": "Copy text to the system clipboard.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to copy."}
            },
            "required": ["text"],
        },
    },
    {
        "name": "find_file",
        "description": "Search for files by name under a folder (home by default).",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Filename fragment."},
                "search_dir": {"type": "string", "description": "Folder to search."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "close_app",
        "description": "Close a running application by process name.",
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "Process/app name."}
            },
            "required": ["app_name"],
        },
    },
    {
        "name": "get_system_stats",
        "description": "Get CPU, RAM, disk, and battery usage.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "read_file",
        "description": "Read a small text file and return its contents.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read."}
            },
            "required": ["path"],
        },
    },
    {
        "name": "run_shell_command",
        "description": (
            "Run a general, non-destructive shell/terminal command on the user's machine and return its "
            "output — e.g. checking disk space, listing processes, viewing system info. A safety blocklist "
            "rejects destructive commands (rm -rf, sudo, mkfs, dd, shutdown/reboot, piping curl/wget into a "
            "shell, writes to /etc /boot /sys) automatically, so do not use this for anything that sounds "
            "destructive — it will be refused."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run."},
                "timeout": {"type": "integer", "description": "Max seconds to wait (default 30)."},
            },
            "required": ["command"],
        },
    },
]

SYSTEM_INSTRUCTION = (
    "You are Jarvis, a local PC assistant. When the user wants a real computer action, "
    "you MUST call the matching tool instead of only describing it. "
    "Use open_app with app_name 'notepad' when they want a text editor. "
    "If they are just chatting, reply briefly with no tool."
)
