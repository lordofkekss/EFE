import os
from flask import Flask, render_template
from .config import Config
from .extensions import db, migrate, login_manager, csrf, socketio

def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config())

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    socketio.init_app(app)   # ← wichtig

    # Blueprints
    from .auth.routes import bp as auth_bp
    from .students.routes import bp as students_bp
    from .teachers.routes import bp as teachers_bp
    from .rewards.routes import bp as rewards_bp
    from .live.routes import bp as live_bp
    from .courses.routes import bp as courses_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(students_bp, url_prefix="/s")
    app.register_blueprint(teachers_bp, url_prefix="/t")
    app.register_blueprint(rewards_bp, url_prefix="/rewards")
    app.register_blueprint(live_bp, url_prefix="/live")
    app.register_blueprint(courses_bp, url_prefix="/courses")

    @app.route("/")
    def index():
        return render_template("index.html")

    return app
