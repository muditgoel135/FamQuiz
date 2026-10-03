import os
from uuid import uuid4
from dotenv import load_dotenv
from flask import Flask, render_template
from flask_mail import Mail
from flask_security import (
    RoleMixin,
    Security,
    SQLAlchemyUserDatastore,
    UserMixin,
    login_required,
)
from flask_sqlalchemy import SQLAlchemy

load_dotenv()


def _env(*names, default=""):
    """Return first non-empty env var, supporting legacy dash-names in .env."""
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def _env_bool(*names, default=False):
    value = _env(*names, default="")
    if not value:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_port(*names, default=587):
    """Return port as int, falling back to default on missing/garbage values."""
    try:
        return int(_env(*names, default=str(default)) or default)
    except (TypeError, ValueError):
        return default


BASE_CONFIG = {
    "SQLALCHEMY_DATABASE_URI": os.getenv(
        "SQLALCHEMY_DATABASE_URI", "sqlite:///site.db"
    ),
    "SQLALCHEMY_TRACK_MODIFICATIONS": False,
    "SECRET_KEY": os.getenv("SECRET_KEY", "supersecretkeytochangeinwhileusing"),
    # Flask-Security configurations
    "SECURITY_PASSWORD_HASH": "pbkdf2_sha512",
    "SECURITY_PASSWORD_SALT": os.getenv(
        "SECURITY_PASSWORD_SALT", "supersecretsalttochangeinwhileusing"
    ),
    "SECURITY_REGISTERABLE": True,
    "SECURITY_SEND_REGISTER_EMAIL": False,
    "SECURITY_SEND_PASSWORD_CHANGE_EMAIL": True,
    "SECURITY_SEND_PASSWORD_RESET_EMAIL": True,
    "SECURITY_SEND_PASSWORD_RESET_NOTICE_EMAIL": True,
    "SECURITY_CONFIRMABLE": False,
    "SECURITY_RECOVERABLE": True,
    "SECURITY_CHANGEABLE": True,
    "SECURITY_TRACKABLE": False,
    "SECURITY_LOGIN_USER_TEMPLATE": "login.html",
    "SECURITY_REGISTER_USER_TEMPLATE": "signup.html",
    "SECURITY_FORGOT_PASSWORD_TEMPLATE": "forgot_password.html",
    "SECURITY_RESET_PASSWORD_TEMPLATE": "reset_password.html",
    "SECURITY_CHANGE_PASSWORD_TEMPLATE": "change_password.html",
    # Mailjet SMTP (or any provider): canonical MAIL_* names first,
    # legacy dash-names from existing .env as fallback.
    "MAIL_SERVER": _env("MAIL_SERVER", "SMTP-SERVER", default=""),
    "MAIL_PORT": _env_port("MAIL_PORT", "SMTP-PORT", default=587),
    "MAIL_USE_TLS": _env_bool("MAIL_USE_TLS", "MAIL_USE_SSL_TLS", default=True),
    "MAIL_USE_SSL": _env_bool("MAIL_USE_SSL", default=False),
    "MAIL_USERNAME": _env("MAIL_USERNAME", "MAIL-USERNAME", "MAIL-API-KEY", default=""),
    "MAIL_PASSWORD": _env("MAIL_PASSWORD", default=""),
    "MAIL_DEFAULT_SENDER": _env(
        "MAIL_DEFAULT_SENDER",
        "MAIL_SENDER",
        "FROM-EMAIL",
        default="FamQuiz <no-reply@localhost>",
    ),
    "SECURITY_EMAIL_SENDER": _env(
        "SECURITY_EMAIL_SENDER",
        "MAIL_DEFAULT_SENDER",
        "MAIL_SENDER",
        "FROM-EMAIL",
        default="FamQuiz <no-reply@localhost>",
    ),
    # After login / logout / register, land back on homepage.
    # ``?next=`` is still honoured (e.g. /gameplay -> /login?next=/gameplay).
    "SECURITY_POST_LOGIN_VIEW": "/",
    "SECURITY_POST_LOGOUT_VIEW": "/",
    "SECURITY_POST_REGISTER_VIEW": "/",
    "SECURITY_POST_RESET_VIEW": "/",
    "SECURITY_POST_CHANGE_VIEW": "/",
    # Allow <a href="/logout"> links as well as POST forms.
    "SECURITY_LOGOUT_METHODS": ["GET", "POST"],
    # Don't require DNS/MX lookup for emails (offline dev + example.com in tests).
    "SECURITY_EMAIL_VALIDATOR_ARGS": {"check_deliverability": False},
}

# Applied when TESTING is enabled so test_client POSTs don't need tokens.
TESTING_CONFIG = {
    "WTF_CSRF_ENABLED": False,
    "MAIL_SUPPRESS_SEND": True,
}

db = SQLAlchemy()
mail = Mail()


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
    confirmed_at = db.Column(db.DateTime(), default=None)

    roles = db.relationship(
        "Role", secondary=roles_users, backref=db.backref("users", lazy="dynamic")
    )  # type: ignore

    # Profile & Preferences (Settings page, Leaderboard display)
    display_name = db.Column(db.String(80), nullable=True)
    nickname = db.Column(db.String(80), nullable=True)
    grade_occupation = db.Column(db.String(80), nullable=True)  # K-12 / College / Job
    language = db.Column(
        db.String(20), default="English"
    )  # English, Mandarin Chinese, Hindi, Spanish
    theme_mode = db.Column(db.String(10), default="light")  # light / dark
    status = db.Column(
        db.String(20), default="Ready to play"
    )  # Ready to play / Do not disturb / offline

    # Notification preferences
    game_reminders = db.Column(db.Boolean(), default=True)
    challenge_invites = db.Column(db.Boolean(), default=True)
    daily_quiz_notifications = db.Column(db.Boolean(), default=True)

    # Gameplay stats (Homepage Statistics, Functionality 1 scoring)
    score = db.Column(db.Integer, default=0)  # current score
    best_score = db.Column(db.Integer, default=0)
    total_games_played = db.Column(db.Integer, default=0)
    total_wins = db.Column(db.Integer, default=0)
    total_powerups_used = db.Column(db.Integer, default=0)
    most_used_powerup = db.Column(db.String(80), nullable=True)

    # Quiz personalisation + game options (no per-user API key:
    # single family-wide OLLAMA_API_KEY is loaded from .env)
    favorite_subject = db.Column(db.String(80), nullable=True)
    difficulty_level = db.Column(db.String(20), nullable=True)
    default_num_questions = db.Column(db.Integer, default=10)


user_datastore = SQLAlchemyUserDatastore(db, User, Role)
security = Security()


def create_app(config_overrides=None):
    """
    Application factory for login/signup backend (Flask-Security-Too).

    :param config_overrides: Optional dictionary of config overrides.
    :return: Flask application instance.
    """
    app = Flask(__name__)

    app.config.update(BASE_CONFIG)

    if config_overrides:
        app.config.update(config_overrides)

    # Disable CSRF in tests so test_client POSTs don't need tokens.
    if app.config.get("TESTING"):
        app.config.update(TESTING_CONFIG)

    # Don't crash when SMTP creds are missing (local dev): suppress sending
    # and log a warning. Flask-Security will still flash the generic
    # "email sent if account exists" message.
    if not app.config.get("MAIL_SERVER") or not app.config.get("MAIL_PASSWORD"):
        if "MAIL_SUPPRESS_SEND" not in (config_overrides or {}):
            app.config["MAIL_SUPPRESS_SEND"] = True
        app.logger.warning(
            "MAIL_SERVER/MAIL_PASSWORD not configured; "
            "password emails are suppressed (console fallback)."
        )

    db.init_app(app)
    security.init_app(app, user_datastore)
    mail.init_app(app)

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

    with app.app_context():
        db.create_all()

    return app


app = create_app()


# Single family-wide Ollama key loaded from .env
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", os.getenv("OLLAMA-API-KEY"))


if __name__ == "__main__":
    app.run(debug=True)
