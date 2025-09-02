from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from . import bp
from ..extensions import db
from ..models import Class, Enrollment, StarTransaction, UserRewardUnlock, RewardCatalog


@bp.route("/dashboard", methods=["GET","POST"])
@login_required
def dashboard():
    # Balance berechnen
    balance = db.session.query(db.func.coalesce(db.func.sum(StarTransaction.amount), 0)).filter_by(user_id=current_user.id).scalar()
    rewards = RewardCatalog.query.all()
    unlocks = UserRewardUnlock.query.filter_by(user_id=current_user.id).all()
    return render_template("students/dashboard.html", balance=balance, rewards=rewards, unlocks=unlocks)


@bp.route("/join", methods=["POST"])
@login_required
def join_class():
    code = request.form.get("join_code", "").strip()
    klass = Class.query.filter_by(join_code=code).first()
    if not klass:
        flash("Klasse nicht gefunden", "warning")
        return redirect(url_for("students.dashboard"))
    # bereits Mitglied?
    exists = Enrollment.query.filter_by(class_id=klass.id, user_id=current_user.id).first()
    if not exists:
        db.session.add(Enrollment(class_id=klass.id, user_id=current_user.id, role_in_class="student"))
        db.session.commit()
        flash(f"Klasse {klass.name} beigetreten", "success")
    return redirect(url_for("students.dashboard"))