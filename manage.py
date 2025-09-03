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

def maybe_reset_db(app):
    """
    DEV-Reset: Wenn DB_RESET=1 (oder true/yes/on), wird
    - bei SQLite: die DB-Datei gelöscht
    - bei PG/MySQL: alle Tabellen gedroppt
    Danach: Alembic upgrade + optional Admin-Seed.
    """
    flag = os.getenv("DB_RESET", "0").lower() in {"1","true","yes","on"}
    if not flag:
        return

    from flask_migrate import upgrade
    from app.extensions import db
    from sqlalchemy import text

    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    print("━"*40)
    print(f"DB reset: START (URI={uri})")

    with app.app_context():
        if uri.startswith("sqlite:///"):
            db_path = uri.replace("sqlite:///", "")
            try:
                os.remove(db_path)
                print(f"DB reset: SQLite-Datei gelöscht: {db_path}")
            except FileNotFoundError:
                print(f"DB reset: SQLite-Datei nicht vorhanden: {db_path}")
        else:
            # hart droppen (nur DEV!)
            print("DB reset: versuche drop_all()")
            db.reflect()
            db.drop_all()
            db.session.commit()
            # evtl. verbleibende Migrations-Tabellen entfernen
            try:
                db.session.execute(text("DROP TABLE IF EXISTS alembic_version"))
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print("DB reset: alembic_version drop fehlgeschlagen:", e)

        # frische Migrationen anwenden
        upgrade()
        print("DB reset: Alembic upgrade done.")

        # Admin-Seed (optional)
        if os.getenv("SEED_ADMIN", "1").lower() in {"1","true","yes","on"}:
            from app.models import User
            from passlib.hash import bcrypt
            if not User.query.filter_by(username="admin").first():
                admin_pw = os.getenv("ADMIN_PASSWORD", "admin")
                admin = User(username="admin", email="admin@example.com",
                             role="admin", password_hash=bcrypt.hash(admin_pw))
                db.session.add(admin); db.session.commit()
                print("DB reset: Admin angelegt (user=admin)")
    print("DB reset: DONE")
    print("━"*40)


app = create_app()
maybe_reset_db(app)

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
