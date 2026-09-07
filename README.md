# Better Jarvis

A desktop assistant for Linux that can understand natural-language commands and carry out common actions on your computer.

It includes a terminal interface and a PyQt6 desktop app with an optional microphone and wake-word mode. Commands are routed to Gemini, Claude, OpenAI, or a local Ollama instance when available; simple built-in rules provide a fallback when no provider is configured.

## Features

- Run commands from the terminal or desktop chat window
- Open applications and websites
- Check battery and system statistics
- Create and read text files, find files, copy text, set volume, and take screenshots
- Choose among Gemini, Claude, OpenAI, and Ollama automatically
- Optional one-time voice input and "Jarvis" wake-word listening
- Stays available from the system tray after the window is closed

## Requirements

- Python 3.10 or newer
- Linux desktop environment (the included tools target Linux)
- At least one optional AI provider API key, or [Ollama](https://ollama.com/) running locally

## Installation

```bash
git clone https://github.com/YOUR-USERNAME/better-jarvis.git
cd better-jarvis
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and add the key for any provider you want to use:

```dotenv
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
```

You only need one key. The `.env` file is intentionally ignored by Git, so never commit your keys.

## Run it

Start the terminal assistant:

```bash
python main.py
```

Or start the desktop app:

```bash
python gui.py
```

Try commands such as:

```text
what's my battery
open notepad
system stats
take a screenshot
```

## Voice input (optional)

Voice input requires PortAudio and PyAudio. On Debian/Ubuntu-based systems:

```bash
sudo apt install portaudio19-dev
pip install pyaudio
```

Then use the **Mic** button for a single command, or enable **Wake word** and say “Jarvis” followed by a command.

## Provider selection

Better Jarvis prefers Gemini for ordinary online requests. For more involved requests, it uses Claude when configured. If those are unavailable, it tries OpenAI, then local Ollama, and finally its built-in rules.

## Security note

This project can execute actions on your computer. Review commands before running them and keep API keys only in `.env`.

## License

No license has been selected yet. Add one before distributing or accepting contributions.
