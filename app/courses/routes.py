import os, re, uuid, base64, random
from io import BytesIO
from datetime import datetime as dt
from bs4 import BeautifulSoup
from flask import (
    render_template, request, redirect, url_for, flash, abort,
    current_app, send_from_directory, jsonify, make_response
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from . import bp
from ..extensions import db, csrf
from ..models import (
    Subject, SubjectYear, Class, Enrollment,
    ContentNode, Exercise, Document, StarTransaction, LiveSession, gen_id
)

ALLOWED_DOC_EXTS = {"pdf","png","jpg","jpeg","doc","docx","ppt","pptx","xls","xlsx","txt"}

def _nodes_for_course_sorted(course_id):
    return ContentNode.query.filter_by(subject_year_id=course_id)\
        .order_by(ContentNode.order_index.asc(), ContentNode.title.asc()).all()

def _gen_code(n=6):
    charset = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(charset) for _ in range(n))

# ---------- Helpers ----------
def _user_courses():
    if current_user.role == "admin":
        return SubjectYear.query.all()
    class_ids = [e.class_id for e in Enrollment.query.filter_by(user_id=current_user.id).all()]
    return SubjectYear.query.filter(SubjectYear.class_id.in_(class_ids)).all() if class_ids else []

def _current_school_year():
    now = dt.utcnow()
    y = now.year
    a, b = (y, y+1) if now.month >= 8 else (y-1, y)
    return f"{a}/{str(b)[-2:]}"

def _get_or_create_subject(name: str) -> Subject:
    name = (name or "Allgemein").strip() or "Allgemein"
    s = Subject.query.filter_by(name=name).first()
    if s: return s
    s = Subject(id=gen_id(), name=name)
    db.session.add(s); db.session.flush()
    return s

def _star_balance(user_id: str) -> int:
    return sum(t.amount for t in StarTransaction.query.filter_by(user_id=user_id).all())

def _save_data_image(course_id: str, data_url: str) -> str:
    m = re.match(r"data:(image/[^;]+);base64,(.*)", data_url, re.DOTALL)
    if not m: return ""
    mime, b64 = m.groups()
    ext = {"image/png":"png", "image/jpeg":"jpg", "image/jpg":"jpg", "image/gif":"gif"}.get(mime, "png")
    upload_root = current_app.config.get("UPLOAD_FOLDER", os.path.join(current_app.root_path, "uploads"))
    asset_dir = os.path.join(upload_root, course_id, "assets")
    os.makedirs(asset_dir, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(asset_dir, fname)
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64))
    return os.path.relpath(path, upload_root).replace("\\", "/")

def _process_body_html(course_id: str, html: str) -> str:
    # wandelt data:-Bilder in Dateien um und ersetzt src
    soup = BeautifulSoup(html or "", "html.parser")
    changed = False
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src.startswith("data:image/"):
            rel = _save_data_image(course_id, src)
            if rel:
                img["src"] = f"/courses/files/{rel}"
                changed = True
    return str(soup) if changed else html

def _sorted_nodes_for_course(course_id: str, *, include_unreleased_for_teacher=False):
    nodes_q = ContentNode.query.filter_by(subject_year_id=course_id)\
        .order_by(ContentNode.order_index.asc(), ContentNode.title.asc())
    nodes = nodes_q.all()
    if current_user.role == "student" and not include_unreleased_for_teacher:
        nodes = [n for n in nodes if getattr(n, "released_at", None)]
    return nodes

# ---------- Übersicht ----------
@bp.route("/")
@login_required
def index():
    courses = _user_courses()
    classes = {c.id: c for c in Class.query.filter(Class.id.in_([c.class_id for c in courses]) if courses else False).all()} if courses else {}
    subjects = {s.id: s for s in Subject.query.filter(Subject.id.in_([c.subject_id for c in courses]) if courses else False).all()} if courses else {}
    stars = _star_balance(current_user.id) if current_user.role == "student" else None
    return render_template("courses/index.html", courses=courses, classes=classes, subjects=subjects, stars=stars)

# ---------- Manage ----------
@bp.route("/manage", methods=["GET", "POST"])
@login_required
def manage():
    if current_user.role not in ("teacher", "admin"):
        abort(403)

    allowed_classes_q = Class.query
    if current_user.role != "admin":
        allowed_classes_q = Class.query.outerjoin(
            Enrollment, Enrollment.class_id == Class.id
        ).filter(
            (Class.created_by == current_user.id) |
            ((Enrollment.user_id == current_user.id) & (Enrollment.role_in_class == "teacher"))
        ).distinct()

    allowed_classes = allowed_classes_q.order_by(Class.created_at.desc()).all()

    if request.method == "POST":
        class_id = request.form.get("class_id")
        subject_name = request.form.get("subject_name", "").strip()
        school_year = request.form.get("school_year", "").strip() or _current_school_year()

        if current_user.role != "admin" and class_id not in [c.id for c in allowed_classes]:
            flash("Keine Berechtigung für diese Klasse.", "danger")
            return redirect(url_for("courses.manage"))

        if not class_id or not subject_name:
            flash("Bitte Klasse und Fach angeben.", "warning")
            return redirect(url_for("courses.manage"))

        subj = _get_or_create_subject(subject_name)
        course = SubjectYear(id=gen_id(), class_id=class_id, subject_id=subj.id, school_year=school_year)
        db.session.add(course)

        if current_user.role == "teacher":
            exists = Enrollment.query.filter_by(class_id=class_id, user_id=current_user.id, role_in_class="teacher").first()
            if not exists:
                db.session.add(Enrollment(id=gen_id(), class_id=class_id, user_id=current_user.id, role_in_class="teacher"))

        db.session.commit()
        flash("Kurs angelegt.", "success")
        return redirect(url_for("courses.detail", course_id=course.id))

    if current_user.role == "admin":
        courses = SubjectYear.query.order_by(SubjectYear.school_year.desc()).all()
    else:
        cids = [c.id for c in allowed_classes]
        courses = SubjectYear.query.filter(SubjectYear.class_id.in_(cids)).order_by(SubjectYear.school_year.desc()).all()

    class_map = {c.id: c for c in (allowed_classes if current_user.role != "admin" else Class.query.all())}
    subj_ids = list({c.subject_id for c in courses})
    subject_map = {s.id: s for s in Subject.query.filter(Subject.id.in_(subj_ids)).all()} if subj_ids else {}

    return render_template("courses/manage.html",
                           classes=allowed_classes if current_user.role != "admin" else Class.query.order_by(Class.created_at.desc()).all(),
                           courses=courses,
                           class_map=class_map,
                           subject_map=subject_map,
                           current_year=_current_school_year())

# ---------- Kurs-Details ----------
@bp.route("/<course_id>")
@login_required
def detail(course_id):
    course = db.session.get(SubjectYear, course_id)
    if not course: abort(404)
    if current_user.role != "admin":
        if not Enrollment.query.filter_by(class_id=course.class_id, user_id=current_user.id).first():
            abort(403)

    nodes = _sorted_nodes_for_course(course.id, include_unreleased_for_teacher=(current_user.role!="student"))
    docs = Document.query.filter_by(subject_year_id=course.id)\
            .order_by(Document.order_index.asc(), Document.uploaded_at.asc()).all()

    items, doc_paths = [], {}
    fallback_counter = 0
    def norm_index(val):
        nonlocal fallback_counter
        try:
            return int(val)
        except (TypeError, ValueError):
            fallback = 1_000_000 + fallback_counter; fallback_counter += 1; return fallback

    for n in nodes:
        items.append({"kind": n.type if n.type!="lesson" else "section",
                      "id": n.id, "title": n.title or "",
                      "order": norm_index(n.order_index), "released": bool(getattr(n, "released_at", None))})
    for d in docs:
        items.append({"kind": "file", "id": d.id, "title": d.filename or "Datei",
                      "order": norm_index(d.order_index), "released": True})
        doc_paths[d.id] = d.path

    items.sort(key=lambda x: (x["order"], x["title"]))
    types = ["section","exercise"]; kinds = ["mc","short_answer"]

    return render_template("courses/detail.html",
                           course=course, items=items, doc_paths=doc_paths,
                           types=types, kinds=kinds)

# ---------- JSON: Live-Status (für Schüler-Button + initialer Slide) ----------
@bp.route("/<course_id>/live/status")
@login_required
def live_status(course_id):
    s = LiveSession.query.filter_by(course_id=course_id, active=True).first()
    if not s:
        return jsonify({"active": False})
    # aktuellen Slide-HTML bereitstellen (Schüler brauchen Startinhalt)
    nodes = _sorted_nodes_for_course(course_id, include_unreleased_for_teacher=True)
    html = ""
    if 0 <= s.current_slide < len(nodes):
        n = nodes[s.current_slide]
        html = (n.body_html or n.body_md or "")
    return jsonify({"active": True, "session_id": s.id, "index": s.current_slide, "html": html})

# ---------- Teacher: Live-Seite (erzeugt/holt Session + Code) ----------
@bp.route("/<course_id>/live")
@login_required
def live(course_id):
    course = db.session.get(SubjectYear, course_id)
    if not course: abort(404)
    if current_user.role not in ("teacher","admin"): abort(403)
    if current_user.role != "admin":
        if not Enrollment.query.filter_by(class_id=course.class_id, user_id=current_user.id, role_in_class="teacher").first():
            abort(403)

    sess = LiveSession.query.filter_by(course_id=course.id, active=True).first()
    if not sess:
        from datetime import datetime as dt
        from .routes import _gen_code  # falls bereits in dieser Datei vorhanden
        sess = LiveSession(id=gen_id(), course_id=course.id, host_user_id=current_user.id,
                           join_code=_gen_code(), started_at=dt.utcnow(), active=True, current_slide=0, revealed_ids=[])
        db.session.add(sess); db.session.commit()

    nodes = _nodes_for_course_sorted(course.id)
    # Für die Seitenliste: reines Meta
    slides = [{"id": n.id, "type": n.type, "title": n.title} for n in nodes]
    return render_template("courses/live.html", course=course, slides=slides, session=sess)


# ---------- Student: Live-Join (nur wenn aktiv) ----------
@bp.route("/<course_id>/live/join")
@login_required
def live_join(course_id):
    course = db.session.get(SubjectYear, course_id)
    if not course: abort(404)
    if current_user.role == "teacher":
        return redirect(url_for("courses.live", course_id=course_id))
    if current_user.role != "admin":
        if not Enrollment.query.filter_by(class_id=course.class_id, user_id=current_user.id).first():
            abort(403)
    sess = LiveSession.query.filter_by(course_id=course.id, active=True).first()
    if not sess:
        flash("Aktuell läuft keine Live-Session.", "info")
        return redirect(url_for("courses.detail", course_id=course_id))
    return render_template("courses/live_student.html", course=course, session=sess)

# ---------- Live-Ende per HTTP (robust) ----------
@bp.route("/<course_id>/live/end", methods=["POST"])
@login_required
def live_end(course_id):
    course = db.session.get(SubjectYear, course_id)
    if not course: abort(404)
    if current_user.role not in ("teacher","admin"): abort(403)
    sess = LiveSession.query.filter_by(course_id=course.id, active=True).first()
    if not sess:
        return jsonify({"ok": True})  # schon beendet
    if current_user.id != sess.host_user_id and current_user.role != "admin":
        abort(403)
    sess.active = False
    sess.ended_at = dt.utcnow()
    db.session.commit()
    from ..extensions import socketio
    socketio.emit("ended", {}, to=f"live:{sess.id}")
    return jsonify({"ok": True})

# ---------- Join per Code ----------
@bp.route("/live/join_by_code")
@login_required
def live_join_by_code():
    code = (request.args.get("code","") or "").strip().upper()
    if not code: abort(400)
    sess = LiveSession.query.filter_by(join_code=code, active=True).first()
    if not sess:
        flash("Ungültiger oder abgelaufener Code.", "warning")
        return redirect(url_for("index"))
    course = db.session.get(SubjectYear, sess.course_id)
    if current_user.role != "admin":
        if not Enrollment.query.filter_by(class_id=course.class_id, user_id=current_user.id).first():
            abort(403)
    return redirect(url_for("courses.live_join", course_id=sess.course_id))

# ---------- Inhalte anlegen ----------
@bp.route("/<course_id>/content/create", methods=["POST"])
@login_required
def create_content(course_id):
    course = db.session.get(SubjectYear, course_id)
    if not course: abort(404)
    if current_user.role not in ("teacher","admin"): abort(403)

    ntype = request.form.get("type")
    title = request.form.get("title","").strip()
    order_index = request.form.get("order_index", "")
    body_md = request.form.get("body_md","")
    if not ntype or not title:
        flash("Typ und Titel sind Pflicht", "warning"); return redirect(url_for("courses.detail", course_id=course_id))

    try:
        order_index = int(order_index)
    except (TypeError, ValueError):
        max_node = db.session.query(db.func.max(ContentNode.order_index)).filter_by(subject_year_id=course.id).scalar() or 0
        max_doc  = db.session.query(db.func.max(Document.order_index)).filter_by(subject_year_id=course.id).scalar() or 0
        order_index = max(max_node, max_doc) + 1

    node = ContentNode(
        id=gen_id(), subject_year_id=course.id, type=ntype, title=title,
        order_index=order_index, body_md=body_md, generated_by="teacher", approved=True
    )
    db.session.add(node)
    if ntype == "exercise":
        kind = request.form.get("kind","short_answer")
        prompt_md = request.form.get("prompt_md","")
        db.session.add(Exercise(id=gen_id(), content_node_id=node.id, kind=kind, prompt_md=prompt_md))
    db.session.commit()
    flash("Inhalt angelegt.", "success")
    return redirect(url_for("courses.detail", course_id=course_id))

# ---------- Reihenfolge ----------
@csrf.exempt
@bp.route("/<course_id>/reorder_mix", methods=["POST"])
@login_required
def reorder_mix(course_id):
    if current_user.role not in ("teacher","admin"): abort(403)
    data = request.get_json(silent=True) or {}
    order = data.get("order", [])
    for it in order:
        t, _id, idx = it.get("type"), it.get("id"), int(it.get("index",0))
        if t == "node":
            n = db.session.get(ContentNode, _id)
            if n and n.subject_year_id == course_id: n.order_index = idx
        elif t == "doc":
            d = db.session.get(Document, _id)
            if d and d.subject_year_id == course_id: d.order_index = idx
    db.session.commit()
    return jsonify({"ok": True})

# ---------- Abschnitt: Anzeigen / Edit / PDF ----------
@bp.route("/<course_id>/section/<node_id>/view")
@login_required
def section_view(course_id, node_id):
    n = db.session.get(ContentNode, node_id)
    if not n or n.subject_year_id != course_id or n.type not in ("section","lesson"): abort(404)
    if current_user.role != "admin":
        course = db.session.get(SubjectYear, course_id)
        if not Enrollment.query.filter_by(class_id=course.class_id, user_id=current_user.id).first(): abort(403)
    return render_template("courses/section_view.html", node=n, course_id=course_id)

@bp.route("/<course_id>/section/<node_id>/edit")
@login_required
def edit_section(course_id, node_id):
    n = db.session.get(ContentNode, node_id)
    if not n or n.subject_year_id != course_id or n.type not in ("section","lesson"): abort(404)
    if current_user.role not in ("teacher","admin"): abort(403)
    return render_template("courses/section_edit.html", course_id=course_id, node=n)

@bp.route("/<course_id>/section/<node_id>/save", methods=["POST"])
@login_required
def save_section(course_id, node_id):
    n = db.session.get(ContentNode, node_id)
    if not n or n.subject_year_id != course_id or n.type not in ("section","lesson"): abort(404)
    if current_user.role not in ("teacher","admin"): abort(403)
    n.title = request.form.get("title", n.title).strip()
    raw_html = request.form.get("body_html", "")
    n.body_html = _process_body_html(course_id, raw_html)
    db.session.commit()
    flash("Abschnitt gespeichert.", "success")
    return redirect(url_for("courses.detail", course_id=course_id))

@bp.route("/<course_id>/section/<node_id>/pdf")
@login_required
def section_pdf(course_id, node_id):
    try:
        from weasyprint import HTML, CSS
    except Exception:
        flash("PDF-Export benötigt WeasyPrint (pip install weasyprint)", "warning")
        return redirect(url_for("courses.detail", course_id=course_id))
    n = db.session.get(ContentNode, node_id)
    if not n or n.subject_year_id != course_id or n.type not in ("section","lesson"): abort(404)
    if current_user.role != "admin":
        course = db.session.get(SubjectYear, course_id)
        if not Enrollment.query.filter_by(class_id=course.class_id, user_id=current_user.id).first(): abort(403)

    upload_root = current_app.config.get("UPLOAD_FOLDER", os.path.join(current_app.root_path, "uploads"))
    soup = BeautifulSoup(n.body_html or "", "html.parser")
    for img in soup.find_all("img"):
        src = img.get("src","")
        if src.startswith("/courses/files/"):
            rel = src.replace("/courses/files/","").replace("%5C","/")
            img["src"] = os.path.join(upload_root, rel).replace("\\","/")
    html = render_template("courses/section_pdf.html", node=type("Obj",(),{"title":n.title, "body_html":str(soup)})())
    pdf_io = BytesIO()
    HTML(string=html, base_url=upload_root).write_pdf(pdf_io, stylesheets=[CSS(string="""
        @page { size: A4; margin: 18mm; }
        body { font-family: Arial, sans-serif; }
        h1, h2, h3 { page-break-after: avoid; }
        img, video { max-width: 100%; }
    """)])
    pdf_io.seek(0)
    resp = make_response(pdf_io.read())
    resp.headers.set("Content-Type", "application/pdf")
    resp.headers.set("Content-Disposition", "attachment", filename=f"{(n.title or 'abschnitt')[:40]}.pdf")
    return resp

# ---------- Übungen ----------
@bp.route("/<course_id>/exercise/<node_id>")
@login_required
def exercise_view(course_id, node_id):
    n = db.session.get(ContentNode, node_id)
    if not n or n.subject_year_id != course_id or n.type != "exercise": abort(404)
    ex = Exercise.query.filter_by(content_node_id=n.id).first()
    if current_user.role != "admin":
        course = db.session.get(SubjectYear, course_id)
        if not Enrollment.query.filter_by(class_id=course.class_id, user_id=current_user.id).first(): abort(403)
    return render_template("courses/exercise.html", course_id=course_id, node=n, ex=ex)

@bp.route("/<course_id>/exercise/<node_id>/submit", methods=["POST"])
@login_required
def exercise_submit(course_id, node_id):
    n = db.session.get(ContentNode, node_id)
    if not n or n.subject_year_id != course_id or n.type != "exercise": abort(404)
    course = db.session.get(SubjectYear, course_id)
    if current_user.role != "admin":
        if not Enrollment.query.filter_by(class_id=course.class_id, user_id=current_user.id).first(): abort(403)
    db.session.add(StarTransaction(id=gen_id(), user_id=current_user.id, assignment_id=None, amount=1, reason="submission", created_by=None))
    db.session.commit()
    flash("Abgabe gespeichert. +1 Stern", "success")
    return redirect(url_for("courses.detail", course_id=course_id))

@bp.route("/<course_id>/exercise/<node_id>/edit")
@login_required
def exercise_edit(course_id, node_id):
    n = db.session.get(ContentNode, node_id)
    if not n or n.subject_year_id != course_id or n.type != "exercise": abort(404)
    if current_user.role not in ("teacher","admin"): abort(403)
    ex = Exercise.query.filter_by(content_node_id=n.id).first()
    if not ex:
        ex = Exercise(id=gen_id(), content_node_id=n.id, kind="rich")
        db.session.add(ex); db.session.commit()
    return render_template("courses/exercise_edit.html", node=n, ex=ex, course_id=course_id)

@bp.route("/<course_id>/exercise/<node_id>/save", methods=["POST"])
@login_required
def exercise_save(course_id, node_id):
    n = db.session.get(ContentNode, node_id)
    if not n or n.subject_year_id != course_id or n.type != "exercise": abort(404)
    if current_user.role not in ("teacher","admin"): abort(403)
    ex = Exercise.query.filter_by(content_node_id=n.id).first()
    if not ex:
        ex = Exercise(id=gen_id(), content_node_id=n.id, kind="rich")
        db.session.add(ex)
    ex.prompt_html = request.form.get("prompt_html", "")
    ex.solution_html = request.form.get("solution_html", "")
    db.session.commit()
    flash("Übung gespeichert.", "success")
    return redirect(url_for("courses.detail", course_id=course_id))

# ---------- Dateien & Assets SERVEN (fix für Bilder aus dem Editor) ----------
@bp.route("/files/<path:relpath>")
@login_required
def serve_file(relpath):
    upload_root = current_app.config.get("UPLOAD_FOLDER", os.path.join(current_app.root_path, "uploads"))
    safe_rel = os.path.normpath(relpath).replace("\\", "/")
    if safe_rel.startswith("../") or safe_rel.startswith("/"):
        abort(400)
    parts = safe_rel.split("/", 1)
    course_id = parts[0] if parts else None
    course = db.session.get(SubjectYear, course_id) if course_id else None
    if not course: abort(404)
    if current_user.role != "admin":
        if not Enrollment.query.filter_by(class_id=course.class_id, user_id=current_user.id).first():
            abort(403)
    abs_path = os.path.abspath(os.path.join(upload_root, safe_rel))
    if not abs_path.startswith(os.path.abspath(upload_root)):
        abort(403)
    if os.path.exists(abs_path) and os.path.isfile(abs_path):
        return send_from_directory(os.path.dirname(abs_path), os.path.basename(abs_path), as_attachment=False)
    from ..models import Document
    doc = Document.query.filter_by(path=safe_rel).first()
    if doc:
        abs_path = os.path.abspath(os.path.join(upload_root, doc.path.replace("\\","/")))
        if os.path.exists(abs_path):
            return send_from_directory(os.path.dirname(abs_path), os.path.basename(abs_path), as_attachment=False)
    abort(404)

# ---------- Freigeben/Sperren ----------
@bp.route("/<course_id>/content/<node_id>/release", methods=["POST"])
@login_required
def toggle_release(course_id, node_id):
    if current_user.role not in ("teacher","admin"):
        abort(403)
    n = db.session.get(ContentNode, node_id)
    if not n or n.subject_year_id != course_id:
        abort(404)
    action = (request.form.get("action") or "").strip().lower()
    now = dt.utcnow()
    if action == "release":
        if hasattr(n, "released_at"): n.released_at = now
        else:
            n.approved = True; n.approved_at = now
    elif action == "unrelease":
        if hasattr(n, "released_at"): n.released_at = None
        else:
            n.approved = False; n.approved_at = now
    else:
        abort(400)
    db.session.commit()
    flash(("Freigegeben" if action == "release" else "Gesperrt") + f": {n.title}", "success")
    return redirect(url_for("courses.detail", course_id=course_id))

# ---------- Live-Export (Canvas → PDF/PNG) ----------
@csrf.exempt
@bp.route("/<course_id>/live/export", methods=["POST"])
@login_required
def live_export(course_id):
    course = db.session.get(SubjectYear, course_id)
    if not course: abort(404)
    if current_user.role not in ("teacher","admin"): abort(403)
    data = request.get_json(silent=True) or {}
    images = data.get("images", [])
    if not images:
        return jsonify({"ok": False, "error": "no images"}), 400
    upload_root = current_app.config.get("UPLOAD_FOLDER", os.path.join(current_app.root_path, "uploads"))
    export_dir = os.path.join(upload_root, course.id, "exports")
    os.makedirs(export_dir, exist_ok=True)
    saved_pngs = []
    for i, data_url in enumerate(images):
        m = re.match(r"data:image/[^;]+;base64,(.*)", data_url)
        if not m: continue
        img_bytes = base64.b64decode(m.group(1))
        fname = f"live_page_{i+1:03d}.png"
        fpath = os.path.join(export_dir, fname)
        with open(fpath, "wb") as f:
            f.write(img_bytes)
        saved_pngs.append(fpath)
    pdf_rel = None
    try:
        from PIL import Image
        pdf_name = f"live_{dt.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = os.path.join(export_dir, pdf_name)
        imgs = [Image.open(p).convert("RGB") for p in saved_pngs]
        if imgs:
            first, rest = imgs[0], imgs[1:]
            first.save(pdf_path, save_all=True, append_images=rest)
            pdf_rel = os.path.relpath(pdf_path, upload_root).replace("\\", "/")
    except Exception as e:
        current_app.logger.warning("Live-Export PDF: Pillow nicht verfügbar oder Fehler: %s", e)
    if pdf_rel:
        return jsonify({"ok": True, "pdf_url": f"/courses/files/{pdf_rel}"})
    else:
        rels = [os.path.relpath(p, upload_root).replace("\\", "/") for p in saved_pngs]
        return jsonify({"ok": True, "images": [f"/courses/files/{r}" for r in rels]})
