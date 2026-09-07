"""OS-level actions for Jarvis. Every function returns {"success": bool, "message": str}."""

from __future__ import annotations

import datetime as _dt
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import psutil

TEXT_EDITOR_ALIASES = {
    "notepad",
    "editor",
    "text editor",
    "textedit",
    "default editor",
    "gedit",
    "gnome text editor",
    "kate",
    "mousepad",
}

SKIP_DIR_NAMES = {
    ".git",
    ".cache",
    ".local",
    "node_modules",
    "venv",
    "venv-linux",
    "__pycache__",
    ".venv",
}

MAX_FILE_BYTES = 200_000


def _ok(message: str) -> dict:
    return {"success": True, "message": message}


def _fail(message: str) -> dict:
    return {"success": False, "message": message}


def _run(command: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _default_text_editor_id() -> str:
    try:
        result = _run(["xdg-mime", "query", "default", "text/plain"], timeout=10)
        name = (result.stdout or "").strip()
        if result.returncode == 0 and name:
            return name
    except Exception:
        pass
    return "unknown (xdg-mime query failed)"


def open_app(app_name: str) -> dict:
    """Open an app. Text-editor aliases use xdg-open on a temp .txt file (system default)."""
    try:
        name = (app_name or "").strip()
        if not name:
            return _fail("No app name was given.")

        lowered = name.lower()
        if lowered in TEXT_EDITOR_ALIASES:
            return _open_default_text_editor()

        path = Path(name).expanduser()
        if path.exists():
            return _xdg_open(str(path), f"Opened {path}")

        desktop_id = _find_desktop_id(name)
        if desktop_id:
            result = _run(["gtk-launch", desktop_id], timeout=15)
            if result.returncode == 0:
                return _ok(f"Launched {desktop_id} for '{name}'.")
            gio = _run(
                ["gio", "launch", str(_desktop_file_for_id(desktop_id))],
                timeout=15,
            )
            if gio.returncode == 0:
                return _ok(f"Launched {desktop_id} for '{name}'.")
            err = (result.stderr or gio.stderr or "").strip()
            return _fail(f"Found {desktop_id} but could not launch it: {err or 'unknown error'}")

        return _fail(
            f"Could not find an app matching '{name}'. "
            "Try a .desktop name, a file path, or 'notepad' for the default text editor."
        )
    except Exception as exc:
        return _fail(f"open_app failed: {exc}")


def _open_default_text_editor() -> dict:
    editor = _default_text_editor_id()
    handle = tempfile.NamedTemporaryFile(
        prefix="jarvis-",
        suffix=".txt",
        delete=False,
        mode="w",
        encoding="utf-8",
    )
    try:
        handle.write("Opened by Jarvis using your default text editor.\n")
        handle.close()
        return _xdg_open(
            handle.name,
            f"Opened default text editor ({editor}) with {handle.name}",
        )
    except Exception as exc:
        return _fail(f"Could not open the default text editor ({editor}): {exc}")


def _xdg_open(target: str, success_message: str) -> dict:
    result = _run(["xdg-open", target], timeout=15)
    if result.returncode == 0:
        return _ok(success_message)
    err = (result.stderr or result.stdout or "").strip()
    return _fail(f"xdg-open failed for {target}: {err or f'exit code {result.returncode}'}")


def _desktop_dirs() -> list[Path]:
    return [
        Path.home() / ".local/share/applications",
        Path("/usr/local/share/applications"),
        Path("/usr/share/applications"),
    ]


def _desktop_file_for_id(desktop_id: str) -> Path:
    for folder in _desktop_dirs():
        candidate = folder / desktop_id
        if candidate.is_file():
            return candidate
    return Path("/usr/share/applications") / desktop_id


def _find_desktop_id(app_name: str) -> str | None:
    needle = app_name.lower().replace(" ", "")
    if needle.endswith(".desktop"):
        needle = needle[: -len(".desktop")]

    matches: list[str] = []
    for folder in _desktop_dirs():
        if not folder.is_dir():
            continue
        for desktop in folder.glob("*.desktop"):
            stem = desktop.stem.lower()
            if needle == stem or needle in stem:
                matches.append(desktop.name)

    if not matches:
        return None
    exact = [m for m in matches if Path(m).stem.lower() == needle]
    return exact[0] if exact else matches[0]


def create_file(path: str, content: str = "") -> dict:
    """Create (or overwrite) a text file. Parent folders are created if needed."""
    try:
        if not (path or "").strip():
            return _fail("No file path was given.")

        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        target.write_text(content, encoding="utf-8")
        action = "Overwrote" if existed else "Created"
        return _ok(f"{action} file: {target}")
    except Exception as exc:
        return _fail(f"Could not create file '{path}': {exc}")


def get_battery_status() -> dict:
    """Read battery percent and charging state via psutil."""
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return _fail("No battery was detected (this machine may be a desktop, or the battery is hidden).")

        plugged = "plugged in" if battery.power_plugged else "on battery"
        percent = battery.percent
        secs = battery.secsleft
        extra = ""
        if secs is not None and secs > 0 and secs != psutil.POWER_TIME_UNLIMITED:
            hours, rem = divmod(int(secs), 3600)
            minutes = rem // 60
            extra = f" (~{hours}h {minutes}m remaining)"
        return _ok(f"Battery is at {percent:.0f}% ({plugged}){extra}.")
    except Exception as exc:
        return _fail(f"Could not read battery status: {exc}")


def open_website(url: str) -> dict:
    """Open a URL in the default browser via xdg-open."""
    try:
        raw = (url or "").strip()
        if not raw:
            return _fail("No URL was given.")
        if " " in raw and not raw.startswith("http"):
            query = raw.replace(" ", "+")
            raw = f"https://www.google.com/search?q={query}"
        if not raw.startswith(("http://", "https://")):
            raw = "https://" + raw
        parsed = urlparse(raw)
        if not parsed.netloc:
            return _fail(f"'{url}' does not look like a valid website.")
        return _xdg_open(raw, f"Opened {raw} in your default browser.")
    except Exception as exc:
        return _fail(f"Could not open website: {exc}")


def set_volume(level: int) -> dict:
    """Set system output volume to 0–100 using PipeWire/PulseAudio."""
    try:
        value = int(level)
        if value < 0 or value > 100:
            return _fail("Volume must be a number from 0 to 100.")

        if shutil.which("wpctl"):
            result = _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{value}%"])
            if result.returncode == 0:
                return _ok(f"Volume set to {value}%.")
        if shutil.which("pactl"):
            result = _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"])
            if result.returncode == 0:
                return _ok(f"Volume set to {value}%.")
        if shutil.which("amixer"):
            result = _run(["amixer", "sset", "Master", f"{value}%"])
            if result.returncode == 0:
                return _ok(f"Volume set to {value}%.")
        return _fail("No volume tool found (tried wpctl, pactl, amixer).")
    except Exception as exc:
        return _fail(f"Could not set volume: {exc}")


def take_screenshot(path: str = "") -> dict:
    """Save a PNG screenshot. Uses gnome-screenshot, grim, or Pillow."""
    try:
        if (path or "").strip():
            target = Path(path).expanduser()
        else:
            pictures = Path.home() / "Pictures"
            pictures.mkdir(parents=True, exist_ok=True)
            stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            target = pictures / f"jarvis-screenshot-{stamp}.png"
        target.parent.mkdir(parents=True, exist_ok=True)

        if shutil.which("flameshot"):
            result = _run(["flameshot", "full", "-p", str(target)], timeout=30)
        if result.returncode == 0 and target.exists(): 
            return _ok(f"Screenshot saved to {target}")
        if shutil.which("gnome-screenshot"):
            result = _run(["gnome-screenshot", "-f", str(target)], timeout=30)
            if result.returncode == 0 and target.exists():
                return _ok(f"Screenshot saved to {target}")
        if shutil.which("grim"):
            result = _run(["grim", str(target)], timeout=30)
            if result.returncode == 0 and target.exists():
                return _ok(f"Screenshot saved to {target}")
        try:
            from PIL import ImageGrab

            image = ImageGrab.grab()
            image.save(str(target))
            return _ok(f"Screenshot saved to {target}")
        except Exception as grab_exc:
            return _fail(
                "Could not take a screenshot. Install gnome-screenshot, or grim on Wayland. "
                f"Details: {grab_exc}"
            )
    except Exception as exc:
        return _fail(f"Could not take screenshot: {exc}")


def copy_to_clipboard(text: str) -> dict:
    """Copy text to the clipboard (pyperclip, wl-copy, or xclip)."""
    try:
        if text is None:
            return _fail("No text was given to copy.")
        payload = str(text)
        try:
            import pyperclip

            pyperclip.copy(payload)
            return _ok("Copied text to the clipboard.")
        except Exception:
            pass
        if shutil.which("wl-copy"):
            result = subprocess.run(
                ["wl-copy"],
                input=payload,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                return _ok("Copied text to the clipboard (wl-copy).")
        if shutil.which("xclip"):
            result = subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=payload,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                return _ok("Copied text to the clipboard (xclip).")
        return _fail(
            "Could not copy to clipboard. Install xclip (X11) or wl-clipboard (Wayland), "
            "then: pip install pyperclip"
        )
    except Exception as exc:
        return _fail(f"Could not copy to clipboard: {exc}")


def find_file(name: str, search_dir: str = "") -> dict:
    """Find files whose names contain `name`. Skips heavy folders; limits results."""
    try:
        needle = (name or "").strip()
        if not needle:
            return _fail("No file name was given to search for.")
        root = Path(search_dir).expanduser() if (search_dir or "").strip() else Path.home()
        if not root.exists():
            return _fail(f"Search folder does not exist: {root}")

        hits: list[str] = []
        scanned = 0
        lowered = needle.lower()
        for item in root.rglob("*"):
            scanned += 1
            if scanned > 25_000:
                break
            if item.is_dir() and item.name in SKIP_DIR_NAMES:
                continue
            try:
                if item.is_file() and lowered in item.name.lower():
                    hits.append(str(item))
            except OSError:
                continue
            if len(hits) >= 15:
                break

        if not hits:
            return _fail(f"No files matching '{needle}' under {root} (scanned {scanned} paths).")
        listing = "\n".join(hits)
        return _ok(f"Found {len(hits)} file(s) matching '{needle}':\n{listing}")
    except Exception as exc:
        return _fail(f"Could not search for files: {exc}")


def close_app(app_name: str) -> dict:
    """Close processes whose name contains app_name. Will not kill Jarvis itself."""
    try:
        needle = (app_name or "").strip().lower()
        if not needle:
            return _fail("No app name was given to close.")
        if needle in {"python", "python3", "jarvis"}:
            return _fail("Refusing to close Python/Jarvis from this command (too easy to kill the assistant).")

        me = Path(__file__).resolve()
        closed = []
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if proc.pid == psutil.Process().pid:
                    continue
                pname = (proc.info.get("name") or "").lower()
                cmd = " ".join(proc.info.get("cmdline") or []).lower()
                if me.name.lower() in cmd and "better-jarvis" in cmd:
                    continue
                if needle in pname or needle in Path(pname).stem.lower():
                    proc.terminate()
                    closed.append(f"{pname} (pid {proc.pid})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not closed:
            return _fail(f"No running process matched '{app_name}'.")
        return _ok("Asked to close: " + ", ".join(closed[:8]))
    except Exception as exc:
        return _fail(f"Could not close app: {exc}")


def get_system_stats() -> dict:
    """CPU, RAM, disk, and battery summary."""
    try:
        cpu = psutil.cpu_percent(interval=0.4)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        parts = [
            f"CPU {cpu:.0f}%",
            f"RAM {ram.percent:.0f}% ({ram.used // (1024**3)} GB used of {ram.total // (1024**3)} GB)",
            f"Disk {disk.percent:.0f}% ({disk.used // (1024**3)} GB used of {disk.total // (1024**3)} GB)",
        ]
        battery = psutil.sensors_battery()
        if battery is not None:
            plug = "charging" if battery.power_plugged else "on battery"
            parts.append(f"Battery {battery.percent:.0f}% ({plug})")
        return _ok("System stats: " + " | ".join(parts))
    except Exception as exc:
        return _fail(f"Could not read system stats: {exc}")


def read_file(path: str) -> dict:
    """Read a text file (size-capped)."""
    try:
        if not (path or "").strip():
            return _fail("No file path was given.")
        target = Path(path).expanduser()
        if not target.exists():
            return _fail(f"File does not exist: {target}")
        if not target.is_file():
            return _fail(f"Not a file: {target}")
        size = target.stat().st_size
        if size > MAX_FILE_BYTES:
            return _fail(f"File is too large to read here ({size} bytes). Limit is {MAX_FILE_BYTES} bytes.")
        text = target.read_text(encoding="utf-8", errors="replace")
        return _ok(f"Contents of {target}:\n{text}")
    except Exception as exc:
        return _fail(f"Could not read file '{path}': {exc}")


if __name__ == "__main__":
    print("=== get_battery_status ===")
    print(get_battery_status())
    print("=== get_system_stats ===")
    print(get_system_stats())
    print("=== create_file / read_file ===")
    test_path = "/tmp/jarvis-create-file-test.txt"
    print(create_file(test_path, "hello from Jarvis\n"))
    print(read_file(test_path))
    print("=== copy_to_clipboard ===")
    print(copy_to_clipboard("jarvis clipboard test"))
    print("=== take_screenshot ===")
    print(take_screenshot("/tmp/jarvis-screenshot-test.png"))
