from flask_socketio import join_room, emit
from flask import request
from . import bp
from ..extensions import socketio


@socketio.on("join_session")
def join_session(data):
    room = f"session:{data['session_id']}"
    join_room(room)
    emit("joined", {"room": room})


@socketio.on("slide_changed")
def slide_changed(data):
    room = f"session:{data['session_id']}"
    emit("slide_changed", {"index": data["index"]}, room=room)