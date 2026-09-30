from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_security import (
    RoleMixin,
    Security,
    SQLAlchemyUserDatastore,
    UserMixin,
    login_required,
)
from dotenv import load_dotenv, get_key
from uuid import uuid4

load_dotenv()

db = SQLAlchemy()


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///site.db"
    app.config["SECRET_KEY"] = (
        get_key(".env", "SECRET_KEY") or "supersecretkeytochangeinwhileusing"
    )

    # Flask-Security configurations
    app.config["SECURITY_PASSWORD_HASH"] = "pbkdf2_sha512"
    app.config["SECURITY_PASSWORD_SALT"] = (
        get_key(".env", "SECURITY_PASSWORD_SALT")
        or "supersecretsalttochangeinwhileusing"
    )
    app.config["SECURITY_REGISTERABLE"] = True
    app.config["SECURITY_SEND_REGISTER_EMAIL"] = False
    app.config["SECURITY_LOGIN_USER_TEMPLATE"] = "login.html"
    app.config["SECURITY_REGISTER_USER_TEMPLATE"] = "signup.html"

    db.init_app(app)
    return app


app = create_app()


# Load other variables from .env file
OLLAMA_API_KEY = get_key(".env", "OLLAMA_API_KEY")


# Association table linking Users and Roles
roles_users = db.Table(
    "roles_users",
    db.Column("user_id", db.Integer(), db.ForeignKey("user.id")),
    db.Column("role_id", db.Integer(), db.ForeignKey("role.id")),
)


class Role(db.Model, RoleMixin):
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(80), unique=True)
    description = db.Column(db.String(255))


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean(), default=True)
    fs_uniquifier = db.Column(
        db.String(64), unique=True, nullable=False, default=lambda: uuid4().hex
    )

    roles = db.relationship(
        "Role", secondary=roles_users, backref=db.backref("users", lazy="dynamic")
    )  # type: ignore


user_datastore = SQLAlchemyUserDatastore(db, User, Role)
security = Security(app, user_datastore)

# Added to ensure tables are created when you start the app
with app.app_context():
    db.create_all()


@app.route("/")
def homepage():
    return render_template("index.html")


@app.route("/guide")
def guide():
    return render_template("guide.html")


@app.route("/leaderboard")
def leaderboard():
    return render_template("leaderboard.html")


@app.route("/gameplay")
@login_required
def gameplay():
    return render_template("gameplay.html")


if __name__ == "__main__":
    app.run(debug=True)
