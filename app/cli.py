import click
from app.extensions import db
from app.models import User
from passlib.hash import bcrypt

def register_cli(app):
    @app.cli.command("create-admin")
    @click.argument("username")
    @click.argument("password")
    def create_admin(username, password):
        if User.query.filter_by(username=username).first():
            click.echo("User existiert bereits"); return
        u = User(username=username, role="admin", password_hash=bcrypt.hash(password))
        db.session.add(u); db.session.commit()
        click.echo("Admin angelegt")