import uuid
from datetime import datetime
from flask_login import UserMixin
from .extensions import db

# Portabler JSON-Typ
JSONType = db.JSON


def gen_id():
    return str(uuid.uuid4())


# ----------------------------
# Basis-Entitäten
# ----------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    email = db.Column(db.String, unique=True, nullable=True)
    username = db.Column(db.String, unique=True, nullable=False)
    password_hash = db.Column(db.String, nullable=False)
    role = db.Column(db.String, nullable=False)  # teacher|student|admin
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Class(db.Model):
    __tablename__ = "classes"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    name = db.Column(db.String, nullable=False)
    grade_level = db.Column(db.String)
    join_code = db.Column(db.String, unique=True, nullable=False)
    created_by = db.Column(db.String, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Subject(db.Model):
    __tablename__ = "subjects"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    name = db.Column(db.String, unique=True, nullable=False)


class SubjectYear(db.Model):
    __tablename__ = "subject_years"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    class_id = db.Column(db.String, db.ForeignKey("classes.id"), nullable=False)
    subject_id = db.Column(db.String, db.ForeignKey("subjects.id"), nullable=False)
    school_year = db.Column(db.String, nullable=False)  # z.B. "2025/26"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ----------------------------
# Inhalte / Struktur
# ----------------------------
class ContentNode(db.Model):
    __tablename__ = "content_nodes"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    subject_year_id = db.Column(db.String, db.ForeignKey("subject_years.id"), nullable=False)
    parent_id = db.Column(db.String, db.ForeignKey("content_nodes.id"), nullable=True)

    code = db.Column(db.String(32))                     # "I", "1", "1.1", …
    type = db.Column(db.String(16), nullable=False)     # section|lesson|exercise|media
    title = db.Column(db.String(255), nullable=False)
    body_md = db.Column(db.Text)
    body_html = db.Column(db.Text)                      # WYSIWYG für A4/PDF & Live
    media = db.Column(JSONType)                         # [{type:"image|video", url, alt}]
    order_index = db.Column(db.Integer, default=0)

    generated_by = db.Column(db.String(16))             # teacher|ai
    approved = db.Column(db.Boolean, default=False)
    approved_by = db.Column(db.String)
    approved_at = db.Column(db.DateTime)

    # Freischaltung (Kurs-Fortschritt)
    released_at = db.Column(db.DateTime, nullable=True)  # null = gesperrt
    release_order = db.Column(db.Integer, default=0)

    __table_args__ = (
        db.CheckConstraint("type in ('section','lesson','exercise','media')", name="ck_content_nodes_type"),
        db.Index("ix_cn_subject_parent_order", "subject_year_id", "parent_id", "order_index"),
        db.Index("ix_cn_subject_release", "subject_year_id", "release_order"),
    )


class Exercise(db.Model):
    __tablename__ = "exercises"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    content_node_id = db.Column(db.String, db.ForeignKey("content_nodes.id"), nullable=False)
    kind = db.Column(db.String, nullable=False)     # mc|short_answer
    prompt_md = db.Column(db.Text, nullable=False)
    options = db.Column(JSONType)                   # bei MC
    answer_schema = db.Column(JSONType)             # richtige Antwort/Regeln
    difficulty = db.Column(db.Integer)              # 1..5
    tags = db.Column(JSONType)


# ----------------------------
# Zuweisung / Abgaben
# ----------------------------
class Enrollment(db.Model):
    __tablename__ = "enrollments"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    class_id = db.Column(db.String, db.ForeignKey("classes.id"), nullable=False)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    role_in_class = db.Column(db.String, nullable=False)  # student|teacher
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("class_id", "user_id", name="uq_enrollment_user_class"),
        db.Index("ix_enrollments_class", "class_id"),
    )


class Assignment(db.Model):
    __tablename__ = "assignments"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    content_node_id = db.Column(db.String, db.ForeignKey("content_nodes.id"), nullable=False)
    class_id = db.Column(db.String, db.ForeignKey("classes.id"), nullable=False)
    due_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)


class Submission(db.Model):
    __tablename__ = "submissions"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    assignment_id = db.Column(db.String, db.ForeignKey("assignments.id"), nullable=False)
    student_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    answer_json = db.Column(JSONType)
    score = db.Column(db.Float, nullable=True)
    status = db.Column(db.String, default="submitted")  # draft|submitted|evaluated
    attempts_count = db.Column(db.Integer, default=1)
    first_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)


# ----------------------------
# Sterne & Belohnungen
# ----------------------------
class StarTransaction(db.Model):
    __tablename__ = "star_transactions"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    assignment_id = db.Column(db.String, db.ForeignKey("assignments.id"), nullable=True)
    amount = db.Column(db.Integer, nullable=False)   # +earn, -spend
    reason = db.Column(db.String, nullable=False)    # submission|bonus|spend|admin
    created_by = db.Column(db.String, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class RewardCatalog(db.Model):
    __tablename__ = "reward_catalog"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    key = db.Column(db.String, unique=True, nullable=False)
    title = db.Column(db.String, nullable=False)
    description = db.Column(db.Text)
    type = db.Column(db.String)      # cosmetic|perk|privilege
    cost_stars = db.Column(db.Integer, nullable=False)
    active_from = db.Column(db.DateTime, nullable=True)
    active_to = db.Column(db.DateTime, nullable=True)
    max_per_student = db.Column(db.Integer, nullable=True)
    meta = db.Column(JSONType)       # statt "metadata" (reserviert)


class UserRewardUnlock(db.Model):
    __tablename__ = "user_reward_unlocks"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    reward_id = db.Column(db.String, db.ForeignKey("reward_catalog.id"), nullable=False)
    unlocked_at = db.Column(db.DateTime, default=datetime.utcnow)
    spent_stars = db.Column(db.Integer, default=0)
    expires_at = db.Column(db.DateTime, nullable=True)


# ----------------------------
# KI-Profile (system-only)
# ----------------------------
class AIProfile(db.Model):
    __tablename__ = "ai_profiles"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), unique=True, nullable=False)
    traits = db.Column(JSONType)  # {learning_style, pace, mastery_by_tag, help_preference}
    visibility = db.Column(db.String, default="system-only")
    retention_days = db.Column(db.Integer, default=90)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)


# ----------------------------
# Dokumente (Uploads)
# ----------------------------
class Document(db.Model):
    __tablename__ = "documents"
    id = db.Column(db.String, primary_key=True, default=gen_id)
    subject_year_id = db.Column(db.String, db.ForeignKey("subject_years.id"), nullable=False)
    content_node_id = db.Column(db.String, db.ForeignKey("content_nodes.id"), nullable=True)
    filename = db.Column(db.String, nullable=False)
    path = db.Column(db.String, nullable=False)  # relativer Pfad unter UPLOAD_FOLDER
    mime_type = db.Column(db.String, nullable=True)
    uploaded_by = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
