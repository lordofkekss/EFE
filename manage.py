# manage.py
import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
import logging

from app import create_app
from app.extensions import socketio

# .env früh laden – funktioniert für flask CLI und direkten Start
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(find_dotenv()) or load_dotenv(BASE_DIR / ".env")

# Deko für Konsole
pl = "━" * 40

def as_bool(val: str, default=False) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}

app = create_app()

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    debug = as_bool(os.getenv("FLASK_DEBUG", "1"))  # default: an im DEV

    # Logging
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    print(f"{pl}\n{'Debug' if debug else 'Info'}-Logger aktiviert")

    # Startinfo
    print(f"{pl}\nStarte EFE auf {host}:{port} – {'DEBUG AN' if debug else 'DEBUG AUS'}\n{pl}")

    # WICHTIG: SocketIO starten (nicht flask run / app.run)
    # allow_unsafe_werkzeug=True erlaubt den Werkzeug-Server im DEV mit Flask-SocketIO
    socketio.run(
        app,
        host=host,
        port=port,
        debug=debug,
        use_reloader=debug,
        allow_unsafe_werkzeug=True,
    )
