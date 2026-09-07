"""Microphone listen-once and a simple 'jarvis' wake-word loop."""

from __future__ import annotations

import threading


WAKE_WORDS = ("jarvis", "hey jarvis", "ok jarvis")


def _fail(message: str) -> dict:
    return {"success": False, "message": message, "text": ""}


def listen_once(timeout: int = 5, phrase_time_limit: int = 8) -> dict:
    """Record a short phrase and transcribe it (Google Web Speech by default)."""
    try:
        import speech_recognition as sr
    except ImportError:
        return _fail(
            "Voice is not installed yet. In a terminal: "
            "sudo apt install portaudio19-dev && source venv-linux/bin/activate "
            "&& pip install pyaudio SpeechRecognition"
        )

    recognizer = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.4)
            audio = recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=phrase_time_limit,
            )
        text = recognizer.recognize_google(audio)
        return {"success": True, "message": f"Heard: {text}", "text": text}
    except Exception as exc:
        name = type(exc).__name__
        if name == "WaitTimeoutError":
            return _fail("I did not hear anything.")
        if name == "UnknownValueError":
            return _fail("I heard audio but could not understand it.")
        if "PyAudio" in str(exc) or name == "AttributeError":
            return _fail(
                "Microphone backend missing. Run: sudo apt install portaudio19-dev "
                "then pip install pyaudio SpeechRecognition"
            )
        return _fail(f"Voice listen failed: {exc}")


def strip_wake_word(text: str) -> str:
    lowered = (text or "").strip()
    for wake in sorted(WAKE_WORDS, key=len, reverse=True):
        if lowered.lower().startswith(wake):
            return lowered[len(wake) :].strip(" ,.")
        if wake in lowered.lower():
            idx = lowered.lower().find(wake)
            return (lowered[:idx] + lowered[idx + len(wake) :]).strip(" ,.")
    return lowered


def contains_wake_word(text: str) -> bool:
    lowered = (text or "").lower()
    return any(wake in lowered for wake in WAKE_WORDS)


class WakeWordListener:
    """Background thread: listen, and fire callback(command) after hearing 'jarvis'."""

    def __init__(self, on_command):
        self.on_command = on_command
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            heard = listen_once(timeout=4, phrase_time_limit=6)
            if self._stop.is_set():
                return
            if not heard.get("success"):
                continue
            text = heard.get("text") or ""
            if not contains_wake_word(text):
                continue
            command = strip_wake_word(text)
            if command:
                self.on_command(command)
