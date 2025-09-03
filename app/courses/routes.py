import os
import base64
from io import BytesIO
from datetime import datetime as dt
from flask import (
    render_template, request, redirect, url_for, flash, abort,
    current_app, send_from_directory, jsonify, make_response
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from . import bp
from ..extensions import db
from ..models import (
    Subject, SubjectYear, Class, Enrollment,
    ContentNode, Exercise, Document, StarTransaction, gen_id
)

ALLOWED_DOC_EXTS = {"pdf", "png", "jpg", "jpeg", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt"}


# ---------------- Helpers ----------------
def _user_courses():
    if current_user.role == "admin":
        return SubjectYear.query.all()
    class_ids = [e.class_id for e in Enrollment.query.filter_by(user_id=current_user.id).all()]
    return SubjectYear.query.filter(SubjectYear.class_id.in_(class_ids)).all() if class_ids else []


def _current_school_year():
    now = dt.utcnow()
    y = now.year
    a, b = (y, y + 1) if now.month >= 8 else (y - 1, y)
    return f"{a}/{str(b)[-2:]}"


def _get_or_create_subject(name: str) -> Subject:
    name = (name or "Allgemein").strip() or "Allgemein"
    s = Subject.query.filter_by(name=name).first()
    if s:
        return s
    s = Subject(id=gen_id(), name=name)
    db.session.add(s)
    db.session.flush()
    return s


def _star_balance(user_id: str) -> int:
    rows = StarTransaction.query.filter_by(user_id=user_id).all()
    return sum(r.amount for r in rows)


def ensure_course_for_class(class_id: str, subject_name: str = "Allgemein", school_year: str | None = None) -> SubjectYear:
    sy = SubjectYear.query.filter_by(class_id=class_id).first()
    if sy:
        return sy
    subj = _get_or_create_subject(subject_name)
    sy = SubjectYear(
        id=gen_id(),
        class_id=class_id,
        subject_id=subj.id,
        school_year=school_year or _current_school_year(),
    )
    db.session.add(sy)
    db.session.flush()
    return sy


# ---------------- Übersicht ----------------
@bp.route("/")
@login_required
def index():
    courses = _user_courses()
    classes = {c.id: c for c in Class.query.filter(Class.id.in_([c.class_id for c in courses]) if courses else False).all()} if courses else {}
    subjects = {s.id: s for s in Subject.query.filter(Subject.id.in_([c.subject_id for c in courses]) if courses else False).all()} if courses else {}
    stars = _star_balance(current_user.id) if current_user.role == "student" else None
    return render_template("courses/index.html", courses=courses, classes=classes, subjects=subjects, stars=stars)


# ---------------- Kurs-Details / Tabs ----------------
@bp.route("/<course_id>")
@login_required
def detail(course_id):
    course = db.session.get(SubjectYear, course_id)
    if not course:
        abort(404)
    if current_user.role != "admin":
        if not Enrollment.query.filter_by(class_id=course.class_id, user_id=current_user.id).first():
            abort(403)

    nodes = (ContentNode.query
             .filter_by(subject_year_id=course.id)
             .order_by(ContentNode.order_index.asc())
             .all())

    if current_user.role == "student":
        nodes = [n for n in nodes if n.released_at is not None]

    docs = Document.query.filter_by(subject_year_id=course.id).all()
    sections = [n for n in nodes if n.type in ("section", "lesson")]
    exercises = [n for n in nodes if n.type == "exercise"]

    return render_template("courses/detail.html",
                           course=course,
                           sections=sections,
                           exercises=exercises,
                           docs=docs)


# ---------------- Inhalte anlegen / sortieren ----------------
@bp.route("/<course_id>/content/create", methods=["POST"])
@login_required
def create_content(course_id):
    course = db.session.get(SubjectYear, course_id)
    if not course:
        abort(404)
    if current_user.role not in ("teacher", "admin"):
        abort(403)

    ntype = request.form.get("type")          # section|lesson|exercise|media
    title = request.form.get("title", "").strip()
    code = request.form.get("code", "").strip()
    order_index = int(request.form.get("order_index", 0))
    body_md = request.form.get("body_md", "")

    if not ntype or not title:
        flash("Typ und Titel sind Pflicht", "warning")
        return redirect(url_for("courses.detail", course_id=course_id))

    node = ContentNode(
        id=gen_id(),
        subject_year_id=course.id,
        parent_id=None,
        code=code or None,
        type=ntype,
        title=title,
        body_md=body_md,
        order_index=order_index,
        generated_by="teacher",
        approved=True
    )
    db.session.add(node)

    if ntype == "exercise":
        kind = request.form.get("kind", "short_answer")
        prompt_md = request.form.get("prompt_md", "")
        ex = Exercise(id=gen_id(), content_node_id=node.id, kind=kind, prompt_md=prompt_md)
        db.session.add(ex)

    db.session.commit()
    flash("Inhalt angelegt.", "success")
    return redirect(url_for("courses.detail", course_id=course_id))


@bp.route("/<course_id>/reorder", methods=["POST"])
@login_required
def reorder(course_id):
    # Erwartet JSON: {order: [{id: "node_id", index: 0}, ...]}
    if current_user.role not in ("teacher", "admin"):
        abort(403)
    data = request.get_json(silent=True) or {}
    order = data.get("order", [])
    for item in order:
        node = db.session.get(ContentNode, item.get("id"))
        if node and node.subject_year_id == course_id:
            node.order_index = int(item.get("index", 0))
    db.session.commit()
    return jsonify({"ok": True})


# ---------------- Abschnitt: Editor & PDF ----------------
@bp.route("/<course_id>/section/<node_id>/edit")
@login_required
def edit_section(course_id, node_id):
    node = db.session.get(ContentNode, node_id)
    if not node or node.subject_year_id != course_id or node.type not in ("section", "lesson"):
        abort(404)
    if current_user.role not in ("teacher", "admin"):
        abort(403)
    return render_template("courses/section_edit.html", course_id=course_id, node=node)


@bp.route("/<course_id>/section/<node_id>/save", methods=["POST"])
@login_required
def save_section(course_id, node_id):
    node = db.session.get(ContentNode, node_id)
    if not node or node.subject_year_id != course_id or node.type not in ("section", "lesson"):
        abort(404)
    if current_user.role not in ("teacher", "admin"):
        abort(403)

    node.title = request.form.get("title", node.title).strip()
    node.body_html = request.form.get("body_html", "")
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

    node = db.session.get(ContentNode, node_id)
    if not node or node.subject_year_id != course_id or node.type not in ("section", "lesson"):
        abort(404)
    if current_user.role != "admin":
        course = db.session.get(SubjectYear, course_id)
        if not Enrollment.query.filter_by(class_id=course.class_id, user_id=current_user.id).first():
            abort(403)

    html = render_template("courses/section_pdf.html", node=node)
    pdf_io = BytesIO()
    HTML(string=html, base_url=current_app.root_path).write_pdf(
        pdf_io,
        stylesheets=[CSS(string="""
            @page { size: A4; margin: 18mm; }
            body { font-family: Arial, sans-serif; }
            h1, h2, h3 { page-break-after: avoid; }
            img, video { max-width: 100%; }
        """)]
    )
    pdf_io.seek(0)
    resp = make_response(pdf_io.read())
    resp.headers.set("Content-Type", "application/pdf")
    resp.headers.set("Content-Disposition", "attachment", filename=f"{(node.title or 'abschnitt')[:40]}.pdf")
    return resp


# ---------------- Übungen: Ansicht & Abgabe ----------------
@bp.route("/<course_id>/exercise/<node_id>")
@login_required
def exercise_view(course_id, node_id):
    node = db.session.get(ContentNode, node_id)
    if not node or node.subject_year_id != course_id or node.type != "exercise":
        abort(404)
    ex = Exercise.query.filter_by(content_node_id=node.id).first()
    if current_user.role != "admin":
        course = db.session.get(SubjectYear, course_id)
        if not Enrollment.query.filter_by(class_id=course.class_id, user_id=current_user.id).first():
            abort(403)
    return render_template("courses/exercise.html", course_id=course_id, node=node, ex=ex)


@bp.route("/<course_id>/exercise/<node_id>/submit", methods=["POST"])
@login_required
def exercise_submit(course_id, node_id):
    node = db.session.get(ContentNode, node_id)
    if not node or node.subject_year_id != course_id or node.type != "exercise":
        abort(404)
    _ = Exercise.query.filter_by(content_node_id=node.id).first()
    course = db.session.get(SubjectYear, course_id)
    if current_user.role != "admin":
        if not Enrollment.query.filter_by(class_id=course.class_id, user_id=current_user.id).first():
            abort(403)

    # MVP: immer +1 Stern
    db.session.add(StarTransaction(id=gen_id(), user_id=current_user.id, assignment_id=None, amount=1, reason="submission", created_by=None))
    db.session.commit()
    flash("Abgabe gespeichert. +1 Stern", "success")
    return redirect(url_for("courses.detail", course_id=course_id))


# ---------------- Uploads ----------------
@bp.route("/<course_id>/upload", methods=["POST"])
@login_required
def upload_doc(course_id):
    course = db.session.get(SubjectYear, course_id)
    if not course:
        abort(404)
    if current_user.role not in ("teacher", "admin"):
        abort(403)

    f = request.files.get("file")
    if not f or f.filename == "":
        flash("Keine Datei ausgewählt", "warning")
        return redirect(url_for("courses.detail", course_id=course_id))

    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in ALLOWED_DOC_EXTS:
        flash("Dateityp nicht erlaubt", "danger")
        return redirect(url_for("courses.detail", course_id=course_id))

    fname = secure_filename(f.filename)
    upload_root = current_app.config.get("UPLOAD_FOLDER", os.path.join(current_app.root_path, "uploads"))
    course_dir = os.path.join(upload_root, course.id)
    os.makedirs(course_dir, exist_ok=True)

    save_path = os.path.join(course_dir, fname)
    f.save(save_path)

    rel_path = os.path.relpath(save_path, upload_root)
    doc = Document(
        subject_year_id=course.id,
        filename=fname,
        path=rel_path,
        mime_type=f.mimetype,
        uploaded_by=current_user.id
    )
    db.session.add(doc)
    db.session.commit()

    flash("Dokument hochgeladen.", "success")
    return redirect(url_for("courses.detail", course_id=course_id))


@bp.route("/files/<path:relpath>")
@login_required
def serve_file(relpath):
    doc = Document.query.filter_by(path=relpath).first()
    if not doc:
        abort(404)

    if current_user.role != "admin":
        course = db.session.get(SubjectYear, doc.subject_year_id)
        if not Enrollment.query.filter_by(class_id=course.class_id, user_id=current_user.id).first():
            abort(403)

    upload_root = current_app.config.get("UPLOAD_FOLDER", os.path.join(current_app.root_path, "uploads"))
    return send_from_directory(upload_root, relpath, as_attachment=False)


# ---------------- Kurs-Verwaltung (Lehrer/Admin) ----------------
@bp.route("/manage")
@login_required
def manage():
    if current_user.role not in ("teacher", "admin"):
        abort(403)

    if current_user.role == "admin":
        classes = Class.query.all()
    else:
        cls_ids = [e.class_id for e in Enrollment.query.filter_by(user_id=current_user.id, role_in_class="teacher").all()]
        classes = Class.query.filter(Class.id.in_(cls_ids)).all() if cls_ids else []

    class_ids = [c.id for c in classes]
    courses = SubjectYear.query.filter(SubjectYear.class_id.in_(class_ids)).all() if class_ids else []
    subjects = {s.id: s for s in Subject.query.filter(Subject.id.in_([c.subject_id for c in courses]) if courses else False).all()} if courses else {}

    return render_template("courses/manage.html",
                           classes=classes, courses=courses, subjects=subjects,
                           default_school_year=_current_school_year())


@bp.route("/create", methods=["POST"])
@login_required
def create_course():
    if current_user.role not in ("teacher", "admin"):
        abort(403)

    class_id = request.form.get("class_id")
    subject_name = request.form.get("subject_name", "Allgemein").strip()
    school_year = request.form.get("school_year", "").strip() or _current_school_year()

    klass = db.session.get(Class, class_id)
    if not klass:
        flash("Klasse nicht gefunden.", "warning")
        return redirect(url_for("courses.manage"))

    if current_user.role != "admin":
        enrolled = Enrollment.query.filter_by(class_id=klass.id, user_id=current_user.id, role_in_class="teacher").first()
        if not enrolled:
            abort(403)

    subj = _get_or_create_subject(subject_name)
    exists = SubjectYear.query.filter_by(class_id=klass.id, subject_id=subj.id, school_year=school_year).first()
    if exists:
        flash("Für diese Klasse/Fach/Schuljahr existiert bereits ein Kurs.", "info")
        return redirect(url_for("courses.manage"))

    sy = SubjectYear(id=gen_id(), class_id=klass.id, subject_id=subj.id, school_year=school_year)
    db.session.add(sy)
    db.session.commit()
    flash("Kurs angelegt.", "success")
    return redirect(url_for("courses.detail", course_id=sy.id))


# ---------------- Live-Deck ----------------
@bp.route("/<course_id>/live")
@login_required
def live(course_id):
    course = db.session.get(SubjectYear, course_id)
    if not course:
        abort(404)
    if current_user.role != "admin":
        if not Enrollment.query.filter_by(class_id=course.class_id, user_id=current_user.id).first():
            abort(403)

    sections = (ContentNode.query
                .filter_by(subject_year_id=course.id)
                .filter(ContentNode.type.in_(["section", "lesson"]))
                .order_by(ContentNode.order_index.asc())
                .all())
    return render_template("courses/live.html", course=course, sections=sections)


@bp.route("/<course_id>/live/export", methods=["POST"])
@login_required
def live_export(course_id):
    if current_user.role not in ("teacher", "admin"):
        abort(403)
    payload = request.get_json(silent=True) or {}
    images = payload.get("images", [])
    if not images:
        return jsonify({"ok": False, "error": "no images"}), 400

    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
    except Exception:
        return jsonify({"ok": False, "error": "reportlab missing: pip install reportlab"}), 500

    upload_root = current_app.config.get("UPLOAD_FOLDER", os.path.join(current_app.root_path, "uploads"))
    out_dir = os.path.join(upload_root, course_id, "live_exports")
    os.makedirs(out_dir, exist_ok=True)
    ts = dt.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"live_{ts}.pdf")

    c = canvas.Canvas(out_path, pagesize=A4)
    w, h = A4
    for data_url in images:
        if not data_url.startswith("data:image/"):
            continue
        header, b64 = data_url.split(",", 1)
        img_bytes = BytesIO(base64.b64decode(b64))
        img = ImageReader(img_bytes)
        margin = 24
        c.drawImage(img, margin, margin, width=w - 2 * margin, height=h - 2 * margin, preserveAspectRatio=True, anchor='s')
        c.showPage()
    c.save()

    rel_path = os.path.relpath(out_path, upload_root)
    db.session.add(Document(subject_year_id=course_id, filename=os.path.basename(out_path), path=rel_path, mime_type="application/pdf", uploaded_by=current_user.id))
    db.session.commit()

    return jsonify({"ok": True, "pdf": f"/courses/files/{rel_path}"})
