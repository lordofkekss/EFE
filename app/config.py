import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = f"sqlite:///{(BASE_DIR / 'efe.db').as_posix()}"

def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "y", "on")

class Config:
    #Übung Schwellwert für bestanden
    EXERCISE_PASS_THRESHOLD = float(os.getenv("EXERCISE_PASS_THRESHOLD", "0.9"))
    #DB
    SECRET_KEY = os.getenv("SECRET_KEY", "dev")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", DEFAULT_DB)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_TIME_LIMIT = None

    # DSGVO / Retention
    AI_PROFILES_RETENTION_DAYS = int(os.getenv("AI_PROFILES_RETENTION_DAYS", 90))
    EVENTS_RETENTION_DAYS = int(os.getenv("EVENTS_RETENTION_DAYS", 180))


    # Uploads (für Editor-Bilder & Exporte)
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str((BASE_DIR / "app" / "uploads").resolve()))

    # --- DB Reset-Schalter (.env) ---
    DB_RESET_ON_START = _env_bool("DB_RESET", False)          # "1"/"true" → Reset beim Start
    DB_RESET_FORCE_PROD = _env_bool("DB_RESET_FORCE", False)  # erlaubt Reset trotz ENV=production

    # Initialer Admin
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", None)
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")  # in Prod ändern!
