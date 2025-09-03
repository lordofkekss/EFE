import os
from flask_migrate import stamp as alembic_stamp, upgrade as alembic_upgrade
from sqlalchemy import inspect as sa_inspect
from ..extensions import db
from ..models import User  # sorgt auch dafür, dass alle Models importiert sind
from passlib.hash import bcrypt


def _schema_tables():
    insp = sa_inspect(db.engine)
    return [t for t in insp.get_table_names() if t != "alembic_version"]


def _schema_exists() -> bool:
    return bool(_schema_tables())


def reset_db(app) -> bool:
    """
    DEV-Reset der DB beim Start.
    - SQLite: IMMER hart zurücksetzen (reflect -> drop_all -> create_all). Optional zusätzlich Datei löschen.
    - Andere DBs: drop_all -> Alembic upgrade (falls vorhanden) -> ggf. create_all + stamp.
    """
    reset_on = bool(app.config.get("DB_RESET_ON_START", False))
    if not reset_on:
        app.logger.info("DB reset: deaktiviert (DB_RESET=0).")
        return False

    is_prod_env = (str(app.config.get("ENV", "production")).lower() == "production") and not (app.debug or app.testing)
    force_prod = bool(app.config.get("DB_RESET_FORCE_PROD", False))
    if is_prod_env and not force_prod:
        app.logger.warning("DB reset: übersprungen (ENV=production, DB_RESET_FORCE=0).")
        return False

    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    app.logger.warning("DB reset: START (URI=%s)", uri)

    # Verbindungen sicher schließen
    try:
        db.session.remove()
        db.engine.dispose()
    except Exception:
        pass

    # ---------- SQLite: immer Tabellen löschen und neu erstellen ----------
    if uri.startswith("sqlite:///"):
        db_path = uri.replace("sqlite:///", "", 1)

        with app.app_context():
            try:
                # hartes Zurücksetzen unabhängig von Dateipfad
                db.reflect()
                db.drop_all()
                db.session.commit()
                app.logger.warning("SQLite: drop_all() ausgeführt (alle Tabellen entfernt).")
            except Exception as e:
                app.logger.exception("SQLite: drop_all() fehlgeschlagen: %s", e)

            # optional zusätzlich Datei löschen (nicht zwingend nötig, schadet aber nicht)
            try:
                if os.path.exists(db_path):
                    os.remove(db_path)
                    app.logger.warning("SQLite: Datei entfernt: %s", db_path)
            except Exception as e:
                app.logger.warning("SQLite: Datei konnte nicht gelöscht werden (ok): %s", e)

            # frisch aufbauen
            db.create_all()
            ok = _schema_exists()
            app.logger.warning("SQLite: create_all() fertig – Tabellen vorhanden: %s (%s)", ok, ", ".join(_schema_tables()))

            # Alembic-Stamp (best effort)
            try:
                alembic_stamp()
                app.logger.warning("SQLite: Alembic stamp(head) gesetzt (best effort).")
            except Exception:
                pass

        app.logger.warning("DB reset: ENDE. OK=%s", ok)
        return ok

    # ---------- Postgres / MySQL etc. ----------
    with app.app_context():
        try:
            db.drop_all()
            db.session.commit()
            app.logger.warning("Alle Tabellen gedroppt.")
        except Exception as e:
            app.logger.exception("drop_all() fehlgeschlagen (ignoriere): %s", e)

        tried_upgrade = False
        try:
            alembic_upgrade()
            tried_upgrade = True
            app.logger.warning("Alembic upgrade ausgeführt.")
        except Exception as e:
            app.logger.exception("Alembic upgrade fehlgeschlagen: %s", e)

        if not _schema_exists():
            app.logger.warning("Keine Tabellen nach Upgrade – create_all() + stamp().")
            db.create_all()
            try:
                alembic_stamp()
                app.logger.warning("Alembic stamp(head) gesetzt.")
            except Exception:
                pass

        ok = _schema_exists()
        app.logger.warning("DB reset: ENDE. OK=%s (%s)", ok, ", ".join(_schema_tables()))
        return ok


def ensure_initial_admin(app) -> str | None:
    """
    Idempotent: legt initialen Admin an (oder korrigiert Rolle).
    ADMIN_USERNAME / ADMIN_EMAIL / ADMIN_PASSWORD aus Config.
    """
    username = app.config.get("ADMIN_USERNAME") or "admin"
    email = app.config.get("ADMIN_EMAIL")
    pwd = app.config.get("ADMIN_PASSWORD") or "admin123"

    with app.app_context():
        u = User.query.filter_by(username=username).first()
        if not u:
            u = User(username=username, email=email, role="admin",
                     password_hash=bcrypt.hash(pwd))
            db.session.add(u)
            db.session.commit()
            app.logger.warning("Initialer Admin '%s' angelegt.", username)
        else:
            if u.role != "admin":
                u.role = "admin"
                db.session.commit()
                app.logger.warning("Nutzer '%s' auf Rolle admin aktualisiert.", username)
        return u.id if u else None
