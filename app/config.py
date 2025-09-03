import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent  # Projektroot
DEFAULT_DB = f"sqlite:///{(BASE_DIR / 'efe.db').as_posix()}"

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", DEFAULT_DB)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_TIME_LIMIT = None

    AI_PROFILES_RETENTION_DAYS = int(os.getenv("AI_PROFILES_RETENTION_DAYS", 90))
    EVENTS_RETENTION_DAYS = int(os.getenv("EVENTS_RETENTION_DAYS", 180))

    # Uploads
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str((BASE_DIR / "uploads").resolve()))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))  # 16 MB
