from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_socketio import SocketIO

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()

# Wichtig: kein "*" bei CORS, wenn Cookies/Sessions genutzt werden (gleiches Origin → ok)
socketio = SocketIO(async_mode="threading", cors_allowed_origins=None, logger=False, engineio_logger=False)
