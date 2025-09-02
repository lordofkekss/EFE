# app/rewards/routes.py
from flask import Blueprint, request, redirect, url_for, flash
from flask_login import login_required, current_user
from ..extensions import db
from ..models import RewardCatalog, UserRewardUnlock, StarTransaction

bp = Blueprint("rewards", __name__)  # <— HIER den Blueprint definieren

@bp.route("/catalog", methods=["POST"])   # Lehrer: Reward anlegen/ändern
@login_required
def upsert_catalog():
    key = request.form.get("key")
    title = request.form.get("title")
    cost = int(request.form.get("cost", 0))
    r = RewardCatalog.query.filter_by(key=key).first()
    if not r:
        r = RewardCatalog(key=key, title=title, cost_stars=cost)
        db.session.add(r)
    else:
        r.title = title
        r.cost_stars = cost
    db.session.commit()
    flash("Reward gespeichert.", "success")
    return redirect(url_for("teachers.dashboard"))

@bp.route("/unlock", methods=["POST"])    # Schüler: Reward kaufen
@login_required
def unlock():
    reward_id = request.form.get("reward_id")
    balance = db.session.query(db.func.coalesce(db.func.sum(StarTransaction.amount), 0))\
                        .filter_by(user_id=current_user.id).scalar()
    reward = db.session.get(RewardCatalog, reward_id)  # SQLAlchemy 2.0 Kompatibilität
    if not reward:
        flash("Reward nicht gefunden", "warning")
