# Jarvis Troubleshooting

Known issues hit during development, and their fixes. If something breaks, check here before debugging from scratch.

## Environment / setup

- **`pip install` fails or a package "not found" after installing it** — the venv isn't activated. Windows: `.\venv\Scripts\Activate.ps1` (prompt should show `(venv)`). Linux: `source venv/bin/activate`. On Ubuntu without a venv, pip refuses with "externally-managed-environment".
- **Windows: `python -m venv` fails with "Python was not found"** — the Microsoft Store Python alias is intercepting the command. Disable "App execution aliases" for python.exe/python3.exe in Windows Settings, or make sure a real python.org install has PATH priority.
- **Linux: `pyaudio` install fails** — needs `sudo apt install portaudio19-dev` first. `pyautogui` may need `sudo apt install python3-tk`.
- **Linux: shared/NTFS-mounted repo breaks after a remount at a different path** — the venv has hardcoded paths baked in. Recreate the venv fresh and reinstall from `requirements-lock.txt` (don't hand-edit `requirements.txt` from memory).
- **Git on an NTFS-mounted repo (dual-boot / shared drive) misbehaves** — run `git config --global --add safe.directory <path>` and `git config core.fileMode false` (local-only, not global) for that repo.

## Windows PowerShell encoding gotchas

- **`echo "text" >> file` in PowerShell 5.1 writes UTF-16**, which can corrupt a `requirements.txt` or `.gitignore` pip/git expects as UTF-8. Use `Add-Content -Path file -Value "text" -Encoding utf8` instead.
- **`Out-File -Encoding utf8` writes UTF-8 *with a BOM* (byte-order mark)**. A CSV written this way (or by Excel/Notepad) will have its first header glued to a `﻿` prefix if read back with plain `utf-8`. Read such files with `utf-8-sig` instead — it strips the BOM if present and behaves identically to `utf-8` if not.

## Screenshots / clipboard (Linux, Wayland/GNOME)

- **Screenshot fails or falls through unexpectedly** — `flameshot` works via the XDG portal (expect a one-time permission popup); `gnome-screenshot`/`grim` don't work the same way. Falls back to Pillow if none are available.
- **Clipboard doesn't work on Wayland** — needs `wl-clipboard` installed (`sudo apt install wl-clipboard`).

## Known limitations

- **Windows**: `actions/system.py` was originally Linux-only (`xdg-open`, `wpctl`/`pactl`/`amixer`, `flameshot`/`gnome-screenshot`/`grim`). A cross-platform fix for `open_app`, `open_website`, `take_screenshot`, and `get_system_stats` has been written — check `Tasks/Windows compatibility fix.md` in the Obsidian vault for current status. `set_volume` has no Windows implementation yet.
- **Selenium/Chrome browser automation** was tried and abandoned (profile-lock crashes, snap conflicts) — considered out of scope.
- `google.generativeai` (used in `core/llm_brain.py`) is deprecated in favor of `google-genai` — still works, migration not yet done.
