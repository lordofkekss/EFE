from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_user, logout_user, current_user, login_required
from passlib.hash import bcrypt
from . import bp
from ..extensions import db, login_manager
from ..models import User


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, user_id)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if not user or not bcrypt.verify(password, user.password_hash):
            flash("Ungültige Zugangsdaten", "danger")
            return redirect(url_for("auth.login"))
        login_user(user)
        flash("Willkommen zurück!", "success")
        return redirect(url_for("students.dashboard") if user.role == "student" else url_for("teachers.dashboard"))
    return render_template("auth/login.html")


def _allowed_register_roles():
    """Ermittelt zulässige Rollen für die aktuelle Situation."""
    has_admin = db.session.query(User.id).filter_by(role="admin").first() is not None
    if not has_admin:
        return ["admin"]  # Erstregistrierung: nur Admin
    if current_user.is_authenticated and current_user.role == "admin":
        return ["admin", "teacher", "student"]
    if current_user.is_authenticated and current_user.role == "teacher":
        return ["student"]
    return []  # öffentlich keine Registrierung


@bp.route("/register", methods=["GET", "POST"])
def register():
    allowed = _allowed_register_roles()
    if not allowed:
        abort(404)  # Registrierung nicht öffentlich

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "student")
        if role not in allowed:
            flash("Diese Rolle darfst du nicht anlegen.", "warning")
            return redirect(url_for("auth.register"))
        if not username or not password:
            flash("Bitte Benutzername und Passwort angeben", "warning")
            return redirect(url_for("auth.register"))
        if User.query.filter_by(username=username).first():
            flash("Benutzername bereits vergeben", "warning")
            return redirect(url_for("auth.register"))
        user = User(username=username, role=role, password_hash=bcrypt.hash(password))
        db.session.add(user)
        db.session.commit()
        flash(f"{role.capitalize()} angelegt.", "success")

        has_admin = db.session.query(User.id).filter_by(role="admin").first() is not None
        if not current_user.is_authenticated and has_admin:
            return redirect(url_for("auth.login"))
        return redirect(url_for("auth.register"))

    return render_template("auth/register.html", allowed_roles=allowed)


@bp.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old = request.form.get("old_password", "")
        new = request.form.get("new_password", "")
        if not bcrypt.verify(old, current_user.password_hash):
            flash("Altes Passwort falsch.", "danger")
            return redirect(url_for("auth.change_password"))
        if len(new) < 6:
            flash("Neues Passwort ist zu kurz.", "warning")
            return redirect(url_for("auth.change_password"))
        current_user.password_hash = bcrypt.hash(new)
        db.session.commit()
        flash("Passwort aktualisiert.", "success")
        return redirect(url_for("students.dashboard") if current_user.role == "student" else url_for("teachers.dashboard"))
    return render_template("auth/password.html")


@bp.route("/logout")
def logout():
    logout_user()
    flash("Abgemeldet.", "info")
    return redirect(url_for("auth.login"))
