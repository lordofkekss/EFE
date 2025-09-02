# manage.py
import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
import logging

from app import create_app
from app.extensions import socketio

# .env früh laden – funktioniert für flask CLI und direkten Start
BASE_DIR = Path(__file__).resolve().parent
# bevorzugt: automatisch finden (falls du mal woanders startest)
load_dotenv(find_dotenv()) or load_dotenv(BASE_DIR / ".env")
#Platzhalter für Konsole
pl = 40*"━"
app = create_app()

if __name__ == "__main__":
    host = os.getenv("HOST")
    port = int(os.getenv("PORT"))
    # Debug Modus und Logging
    debug = os.getenv("FLASK_DEBUG")
    if debug:
        logging.basicConfig(level=logging.DEBUG)
        print(f"{pl}\nDebug-Logger aktiviert")
    else:
        logging.basicConfig(level=logging.INFO)
        print(f"{pl}\nInfo-Logger aktiviert")

    # SocketIO-Server starten (eventlet empfohlen, wenn installiert)
    print(f"{pl}\nStarte EFE auf {host}:{port} – {'DEBUG AN' if debug else 'DEBUG AUS'}\n{pl}")
    socketio.run(app, host=host, port=port, debug=debug)