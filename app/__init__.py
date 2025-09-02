from flask import Flask, render_template
from flask_wtf.csrf import generate_csrf
import os
from .config import Config
from .extensions import db, migrate, login_manager, csrf, socketio


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config())

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"
    csrf.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*")

    # Jinja: CSRF-Funktion überall verfügbar
    @app.context_processor
    def inject_csrf_token():
        return dict(csrf_token=generate_csrf)

    # Blueprints
    from .auth.routes import bp as auth_bp
    from .students.routes import bp as students_bp
    from .teachers.routes import bp as teachers_bp
    from .rewards.routes import bp as rewards_bp
    from .live.routes import bp as live_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(students_bp, url_prefix="/s")
    app.register_blueprint(teachers_bp, url_prefix="/t")
    app.register_blueprint(rewards_bp, url_prefix="/rewards")
    app.register_blueprint(live_bp, url_prefix="/live")

    # Navbar-Flag: Registrieren nur wenn sinnvoll
    from .models import User
    from flask_login import current_user

    @app.context_processor
    def inject_nav_flags():
        no_admin = db.session.query(User.id).filter_by(role="admin").first() is None
        can_register = False
        if no_admin:
            can_register = True
        elif current_user.is_authenticated and current_user.role in ("admin", "teacher"):
            can_register = True
        return dict(registration_open=can_register)

    # Admin-Bootstrap aus ENV (nur wenn noch keiner existiert)
    with app.app_context():
        from .models import User
        from passlib.hash import bcrypt
        has_admin = db.session.query(User.id).filter_by(role="admin").first() is not None
        env_admin_user = os.getenv("ADMIN_USERNAME")
        env_admin_pass = os.getenv("ADMIN_PASSWORD")
        if not has_admin and env_admin_user and env_admin_pass:
            db.session.add(User(
                username=env_admin_user,
                role="admin",
                password_hash=bcrypt.hash(env_admin_pass)
            ))
            db.session.commit()

    @app.route("/")
    def index():
        return render_template("index.html")

    return app