"""Terminal loop: type a command, Jarvis runs it on this PC."""

from __future__ import annotations

from core.llm_brain import choose_provider, handle, is_online, ollama_available


def main() -> None:
    online = "online" if is_online() else "offline"
    ollama = "yes" if ollama_available() else "no"
    print("Jarvis CLI. Type a command, or 'quit' to exit.")
    print(f"Network: {online} | Ollama: {ollama} | Default provider for 'hi': {choose_provider('hi')}")
    print("Examples: what's my battery | open notepad | system stats | screenshot")
    while True:
        try:
            command = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return
        if not command:
            continue
        if command.lower() in {"quit", "exit", "q"}:
            print("Bye.")
            return
        result = handle(command)
        tag = "OK" if result.get("success") else "FAIL"
        provider = result.get("provider") or "?"
        print(f"Jarvis [{tag}/{provider}]: {result.get('message')}")


if __name__ == "__main__":
    main()
