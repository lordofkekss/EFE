from functools import wraps
from flask import abort
from flask_login import current_user

def roles_required(*roles):
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return deco