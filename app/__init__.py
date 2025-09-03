import os
from sqlalchemy import inspect as sa_inspect
from flask import Flask, render_template, jsonify
from .config import Config
from .extensions import db, migrate, login_manager, csrf, socketio
from .utils.db_tools import reset_db, ensure_initial_admin

def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config())

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*")

    # Nur im Reloader-Child ausführen (damit es genau einmal passiert)
    should_run_startup = (os.environ.get("WERKZEUG_RUN_MAIN") == "true") or (not app.debug)
    if should_run_startup:
        with app.app_context():
            did_reset = reset_db(app)
            ensure_initial_admin(app)
            if did_reset:
                app.logger.warning("DB wurde zurückgesetzt (DB_RESET=1).")

    # Blueprints
    from .auth.routes import bp as auth_bp
    from .students.routes import bp as students_bp
    from .teachers.routes import bp as teachers_bp
    from .rewards.routes import bp as rewards_bp
    from .courses.routes import bp as courses_bp
    from .live.routes import bp as live_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(students_bp, url_prefix="/s")
    app.register_blueprint(teachers_bp, url_prefix="/t")
    app.register_blueprint(rewards_bp, url_prefix="/rewards")
    app.register_blueprint(courses_bp, url_prefix="/courses")
    app.register_blueprint(live_bp, url_prefix="/live")

    @app.route("/")
    def index():
        return render_template("index.html")

    # Debug: Tabellen-Check
    @app.route("/_debug/db")
    def debug_db():
        insp = sa_inspect(db.engine)
        return jsonify({
            "tables": [t for t in insp.get_table_names()],
            "has_app_tables": any(t for t in insp.get_table_names() if t != "alembic_version")
        })

    return app
