from flask import Blueprint
from ..extensions import socketio
from flask_login import current_user
from flask_socketio import join_room

bp = Blueprint("live", __name__)  # HTTP-Routen optional; SocketIO unten

@socketio.on("join_session")
def on_join_session(data):
    room = (data or {}).get("session_id")
    if not room:
        return
    join_room(room)

@socketio.on("slide_to")
def on_slide_to(data):
    room = (data or {}).get("room")
    index = (data or {}).get("index")
    if room is None or index is None:
        return
    socketio.emit("slide_changed", {"index": index}, to=room)

@socketio.on("draw")
def on_draw(data):
    room = (data or {}).get("room")
    if not room:
        return
    # Broadcast Zeichnung (x0,y0,x1,y1,color,width,slide)
    socketio.emit("draw", data, to=room)
