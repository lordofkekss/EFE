import secrets
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from . import bp
from ..extensions import db
from ..models import Class, Enrollment, RewardCatalog, StarTransaction, gen_id


@bp.route("/dashboard", methods=["GET","POST"])
@login_required
def dashboard():
    # Klassen auflisten
    classes = Class.query.filter_by(created_by=current_user.id).all()
    return render_template("teachers/dashboard.html", classes=classes)


@bp.route("/class/create", methods=["POST"])
@login_required
def create_class():
    name = request.form.get("name", "").strip()
    grade = request.form.get("grade_level", "").strip()
    if not name:
        flash("Klassenname fehlt", "warning")
        return redirect(url_for("teachers.dashboard"))

    join_code = secrets.token_hex(3)
    klass = Class(
        id=gen_id(),  # <— hier explizit setzen
        name=name,
        grade_level=grade,
        join_code=join_code,
        created_by=current_user.id,
    )
    db.session.add(klass)
    db.session.add(Enrollment(class_id=klass.id, user_id=current_user.id, role_in_class="teacher"))
    db.session.commit()
    flash("Klasse angelegt.", "success")
    return redirect(url_for("teachers.dashboard"))


@bp.route("/stars/grant", methods=["POST"])
@login_required
def grant_stars():
    student_id = request.form.get("student_id")
    amount = int(request.form.get("amount", 0))
    if amount == 0:
        flash("Ungültige Anzahl", "warning")
        return redirect(url_for("teachers.dashboard"))
    tx = StarTransaction(user_id=student_id, amount=amount, reason="bonus", created_by=current_user.id)
    db.session.add(tx)
    db.session.commit()
    flash("Sterne vergeben.", "success")
    return redirect(url_for("teachers.dashboard"))