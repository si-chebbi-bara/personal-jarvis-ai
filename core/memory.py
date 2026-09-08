import re
from datetime import datetime
from pathlib import Path

MEMORY_FILE = Path(__file__).resolve().parent.parent / "memory.md"
MAX_LOG_ENTRIES = 20  # keep last N exchanges (each exchange = 1 you + 1 jarvis line)

DEFAULT_CONTENT = """# Jarvis Memory

## Facts about Bara

## Recent conversation
"""


def _ensure_file():
    if not MEMORY_FILE.exists():
        MEMORY_FILE.write_text(DEFAULT_CONTENT)


def _read_sections():
    _ensure_file()
    text = MEMORY_FILE.read_text()

    facts_match = re.search(r"## Facts about Bara\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    log_match = re.search(r"## Recent conversation\n(.*?)\Z", text, re.DOTALL)

    facts = facts_match.group(1).strip() if facts_match else ""
    log = log_match.group(1).strip() if log_match else ""

    return facts, log


def get_context() -> str:
    """Returns a short text block to prepend to the LLM prompt for context."""
    facts, log = _read_sections()

    parts = []
    if facts:
        parts.append(f"Known facts about the user:\n{facts}")
    if log:
        parts.append(f"Recent conversation history:\n{log}")

    if not parts:
        return ""

    return "\n\n".join(parts)


def add_fact(fact: str):
    """Appends a new durable fact about the user."""
    facts, log = _read_sections()
    new_facts = (facts + f"\n- {fact}").strip() if facts else f"- {fact}"
    _write(new_facts, log)


def log_exchange(user_text: str, jarvis_text: str):
    """Adds a new You/Jarvis exchange to the rolling log, trimming old entries."""
    facts, log = _read_sections()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    new_lines = [
        f"- [{timestamp}] You: {user_text}",
        f"- [{timestamp}] Jarvis: {jarvis_text}",
    ]

    existing_lines = [l for l in log.split("\n") if l.strip()]
    all_lines = existing_lines + new_lines

    # Keep only the last MAX_LOG_ENTRIES exchanges (2 lines per exchange)
    max_lines = MAX_LOG_ENTRIES * 2
    trimmed = all_lines[-max_lines:]

    _write(facts, "\n".join(trimmed))


def _write(facts: str, log: str):
    content = f"""# Jarvis Memory

## Facts about Bara
{facts}

## Recent conversation
{log}
"""
    MEMORY_FILE.write_text(content)