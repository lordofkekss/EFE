from flask import request
from flask_login import current_user
from . import bp
from ..extensions import socketio, db
from ..models import LiveSession, SubjectYear, Enrollment, ContentNode, Exercise
from flask_socketio import join_room, leave_room, emit
from datetime import datetime as dt

def _room(session_id: str) -> str:
    return f"live:{session_id}"

def _can_access_course(user_id: str, course_id: str) -> bool:
    course = db.session.get(SubjectYear, course_id)
    if not course:
        return False
    if current_user.role == "admin":
        return True
    return Enrollment.query.filter_by(class_id=course.class_id, user_id=user_id).first() is not None

def _slide_html_for_node(node: ContentNode, revealed_ids: list) -> str:
    """Erzeuge HTML für Abschnitt/Übung. Lösung nur, wenn ge-revealed."""
    if node.type == "exercise":
        ex = Exercise.query.filter_by(content_node_id=node.id).first()
        if not ex:
            return "<div class='alert alert-warning'>Diese Übung hat noch keinen Inhalt.</div>"
        prompt = (ex.prompt_html or ex.prompt_md or "").strip()
        solution = (ex.solution_html or "").strip()
        show_solution = node.id in (revealed_ids or [])
        # Klasse "d-none" nur setzen, wenn Lösung versteckt bleiben soll
        solution_class = "" if show_solution else "d-none"
        return (
            f"<div class='ex-wrapper' data-node-id='{node.id}'>"
            f"  <div class='ex-prompt'>{prompt}</div>"
            f"  <div class='ex-solution {solution_class}'>"
            f"    <hr><div class='alert alert-success'><strong>Lösung:</strong></div>"
            f"    {solution}"
            f"  </div>"
            f"</div>"
        )
    # Abschnitt
    return (node.body_html or node.body_md or "")

def _current_slide_payload(sess: LiveSession):
    nodes = ContentNode.query.filter_by(subject_year_id=sess.course_id)\
        .order_by(ContentNode.order_index.asc(), ContentNode.title.asc()).all()
    idx = int(sess.current_slide or 0)
    html = ""
    if 0 <= idx < len(nodes):
        html = _slide_html_for_node(nodes[idx], sess.revealed_ids or [])
    return {"index": idx, "html": html}

@socketio.on("join_live")
def on_join_live(data):
    session_id = (data or {}).get("session_id")
    role = (data or {}).get("role", "student")
    if not session_id:
        return
    sess = db.session.get(LiveSession, session_id)
    if not sess or not sess.active:
        return
    if not _can_access_course(current_user.id, sess.course_id):
        return
    join_room(_room(session_id))
    # aktuellen Zustand nur an den neuen Client
    emit("slide_change", _current_slide_payload(sess), room=request.sid)
    emit("user_joined", {"user_id": current_user.id, "role": role}, to=_room(session_id))

@socketio.on("leave_live")
def on_leave_live(data):
    session_id = (data or {}).get("session_id")
    if not session_id:
        return
    leave_room(_room(session_id))
    emit("user_left", {"user_id": current_user.id}, to=_room(session_id))

@socketio.on("slide_change")
def on_slide_change(data):
    session_id = data.get("session_id")
    idx = int(data.get("index", 0))
    sess = db.session.get(LiveSession, session_id)
    if not sess or not sess.active:
        return
    if current_user.id != sess.host_user_id and current_user.role != "admin":
        return
    sess.current_slide = idx
    db.session.commit()

    payload = _current_slide_payload(sess)
    # an alle anderen broadcasten …
    emit("slide_change", payload, to=_room(session_id), include_self=False)
    # … und dem Sender die Antwort für den Emit-Callback zurückgeben
    return payload

@socketio.on("draw")
def on_draw(data):
    session_id = data.get("session_id")
    payload = {
        "slide": int(data.get("slide", 0)),
        "x0": float(data.get("x0", 0)),
        "y0": float(data.get("y0", 0)),
        "x1": float(data.get("x1", 0)),
        "y1": float(data.get("y1", 0)),
        "w": float(data.get("w", 2)),
        "c": data.get("c", None),
    }
    sess = db.session.get(LiveSession, session_id)
    if not sess or not sess.active:
        return
    if current_user.id != sess.host_user_id and current_user.role != "admin":
        return
    emit("draw", payload, to=_room(session_id), include_self=False)

@socketio.on("clear")
def on_clear(data):
    session_id = data.get("session_id")
    slide = int(data.get("slide", 0))
    sess = db.session.get(LiveSession, session_id)
    if not sess or not sess.active:
        return
    if current_user.id != sess.host_user_id and current_user.role != "admin":
        return
    emit("clear", {"slide": slide}, to=_room(session_id), include_self=False)

@socketio.on("reveal_solution")
def on_reveal_solution(data):
    """Lehrer blendet Lösung ein/aus für die aktuelle Übung."""
    session_id = data.get("session_id")
    node_id = data.get("node_id")
    reveal = bool(data.get("reveal", True))
    sess = db.session.get(LiveSession, session_id)
    if not sess or not sess.active:
        return
    if current_user.id != sess.host_user_id and current_user.role != "admin":
        return
    ids = set(sess.revealed_ids or [])
    if reveal:
        ids.add(node_id)
    else:
        ids.discard(node_id)
    sess.revealed_ids = list(ids)
    db.session.commit()
    emit("solution_reveal", {"node_id": node_id, "reveal": reveal}, to=_room(session_id), include_self=True)

@socketio.on("end_session")
def on_end_session(data):
    session_id = data.get("session_id")
    sess = db.session.get(LiveSession, session_id)
    if not sess or not sess.active:
        return
    if current_user.id != sess.host_user_id and current_user.role != "admin":
        return
    sess.active = False
    sess.ended_at = dt.utcnow()
    db.session.commit()
    emit("ended", {}, to=_room(session_id))
