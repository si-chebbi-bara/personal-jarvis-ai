"""One-time helper: turns a password you type into the two lines Jarvis needs in .env.

Run:  python set_password.py
Then paste the printed lines into .env (never commit that file).
"""

import getpass
import secrets

import bcrypt

password = getpass.getpass("Choose a Jarvis password (min 12 chars): ")
if len(password) < 12:
    raise SystemExit("Too short - use at least 12 characters.")
if getpass.getpass("Repeat it: ") != password:
    raise SystemExit("Passwords did not match.")

hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
print("\nAdd these lines to your .env file:\n")
print(f"JARVIS_PASSWORD_HASH={hashed}")
print(f"JARVIS_JWT_SECRET={secrets.token_urlsafe(48)}")
print("JARVIS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173")
