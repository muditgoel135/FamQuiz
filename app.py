import json
import os
import random
import time
from typing import Any
from uuid import uuid4
from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request, session
from flask_mail import Mail
from flask_security import (
    RoleMixin,
    Security,
    SQLAlchemyUserDatastore,
    UserMixin,
    current_user,
    login_required,
)
from flask_sqlalchemy import SQLAlchemy

from translations import (
    LOCALE_TO_HTML,
    LOCALE_TO_LANGUAGE,
    SUPPORTED_LOCALES,
    TRANSLATIONS,
    LANGUAGE_TO_LOCALE,
    translate,
)

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

# Client 1 (E-portfolio): 4 UI languages. DB stores full names,
# locale codes drive template translation (zero-dependency,
# Flask-Security-Too/Flask-User internationalisation equivalent).
LOCALE_CODES = SUPPORTED_LOCALES


def get_locale():
    """Resolve current locale: ?lang= > session > user > Accept-Language > en."""
    try:
        from flask import has_request_context

        if not has_request_context():
            return "en"
        # Explicit override wins and persists for anonymous users.
        arg = request.args.get("lang")
        if arg in SUPPORTED_LOCALES:
            session["locale"] = arg
            return arg
        sess = session.get("locale")
        if sess in SUPPORTED_LOCALES:
            return sess  # type: ignore[return-value]
        try:
            if current_user.is_authenticated:
                mapped = LANGUAGE_TO_LOCALE.get(
                    (current_user.language or "English").strip(), "en"
                )
                if mapped in SUPPORTED_LOCALES:
                    return mapped
        except Exception:
            pass
        best = request.accept_languages.best_match(["en", "es", "hi", "zh-Hans", "zh"])
        if best:
            if best in ("zh-Hans", "zh"):
                return "zh_Hans"
            if best in SUPPORTED_LOCALES:
                return best
    except Exception:
        pass
    return "en"


def _(message):
    """Translate a UI string into the current locale (fallback: English)."""
    try:
        return translate(message, get_locale())
    except Exception:
        return message


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


def display_name_of(user):
    """Best available display name: display_name, nickname, then email user."""
    if user is None:
        return "Player"
    name = (user.display_name or user.nickname or "").strip()
    if name:
        return name
    email = user.email or ""
    return email.split("@")[0] if "@" in email else "Player"


def rank_of(user_id):
    """1-based leaderboard rank ordered like the homepage leaderboard."""
    ordered_ids = [
        u.id
        for u in User.query.order_by(
            User.best_score.desc(), User.total_wins.desc(), User.id.asc()  # type: ignore[attr-defined]
        ).all()
    ]
    return ordered_ids.index(user_id) + 1 if user_id in ordered_ids else 1


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
    # Explicit overrides win over TESTING_CONFIG, so a caller can opt
    # back into real sending (MAIL_SUPPRESS_SEND=False) when needed.
    if app.config.get("TESTING"):
        app.config.update(TESTING_CONFIG)
        if config_overrides:
            app.config.update(config_overrides)

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
        from sqlalchemy import func as _func

        def _display_name(user):
            if user is None:
                return ""
            name = (
                getattr(user, "display_name", None)
                or getattr(user, "nickname", None)
                or ""
            ).strip()
            if name:
                return name
            email = getattr(user, "email", "") or ""
            return email.split("@")[0] if "@" in email else (email or "Player")

        def _status_dot(status):
            value = (status or "").strip().lower()
            if value == "ready to play":
                return "ready"
            if value == "do not disturb":
                return "busy"
            return "offline"

        top_users = (
            User.query.order_by(
                User.best_score.desc(), User.total_wins.desc(), User.id.asc()  # type: ignore[attr-defined]
            )
            .limit(3)
            .all()
        )
        current_id = current_user.id if current_user.is_authenticated else None
        leaderboard = []
        for rank, user in enumerate(top_users, start=1):
            name = _display_name(user)
            leaderboard.append(
                {
                    "rank": rank,
                    "name": name,
                    "is_you": user.id == current_id,
                    "status": user.status or "Ready to play",
                    "dot": _status_dot(user.status),
                    "initial": (name[:1] or "P").upper(),
                }
            )

        family_games = (
            db.session.query(
                _func.coalesce(_func.sum(User.total_games_played), 0)
            ).scalar()
            or 0
        )
        if current_user.is_authenticated:
            you_games = current_user.total_games_played or 0
            you_wins = current_user.total_wins or 0
            best_score = current_user.best_score or 0
            powerups_used = current_user.total_powerups_used or 0
            most_used = current_user.most_used_powerup or "—"
            default_num = current_user.default_num_questions or 10
            difficulty = (current_user.difficulty_level or "").strip().lower()
            avatar_initial = (_display_name(current_user)[:1] or "A").upper()
        else:
            you_games = 0
            you_wins = 0
            best_score = 0
            powerups_used = 0
            most_used = "—"
            default_num = 10
            difficulty = ""
            avatar_initial = "A"
        default_num = max(1, min(int(default_num or 10), MAX_QUIZ_QUESTIONS))

        return render_template(
            "index.html",
            leaderboard=leaderboard,
            family_games=family_games,
            you_games=you_games,
            you_wins=you_wins,
            best_score=best_score,
            powerups_used=powerups_used,
            most_used_powerup=most_used,
            default_num_questions=default_num,
            difficulty_level=difficulty,
            difficulty_options=["easy", "medium", "hard"],
            avatar_initial=avatar_initial,
            max_questions=MAX_QUIZ_QUESTIONS,
        )

    SETTINGS_LANGUAGES = ("English", "Mandarin Chinese", "Spanish", "Hindi")
    SETTINGS_GRADES = ("K-12", "College", "Job")
    SETTINGS_THEMES = ("light", "dark")
    SETTINGS_STATUSES = ("Ready to play", "Do not disturb", "offline")

    @app.context_processor
    def inject_theme():
        try:
            dark = bool(
                current_user.is_authenticated
                and (current_user.theme_mode or "light") == "dark"
            )
        except Exception:
            dark = False
        return {"theme_class": "theme-dark" if dark else ""}

    @app.context_processor
    def inject_i18n():
        locale = get_locale()
        return {
            "_": _,
            "current_locale": locale,
            "html_lang": LOCALE_TO_HTML.get(locale, "en"),
            "supported_locales": list(SUPPORTED_LOCALES),
            "locale_to_language": dict(LOCALE_TO_LANGUAGE),
        }

    @app.before_request
    def _persist_lang_param():
        try:
            arg = request.args.get("lang")
            if arg in SUPPORTED_LOCALES:
                session["locale"] = arg
        except Exception:
            pass

    @app.route("/api/i18n/<locale>.json")
    def i18n_dict(locale):
        """Translated UI strings for JavaScript (Full UI plan)."""
        if locale not in SUPPORTED_LOCALES:
            return jsonify({"error": "Unsupported language."}), 404
        return jsonify(
            {
                "locale": locale,
                "html_lang": LOCALE_TO_HTML.get(locale, "en"),
                "strings": TRANSLATIONS.get(locale, {}),
            }
        )

    @app.route("/settings")
    @login_required
    def settings():
        try:
            num_questions = int(current_user.default_num_questions or 10)
        except (TypeError, ValueError):
            num_questions = 10
        num_questions = max(1, min(num_questions, MAX_QUIZ_QUESTIONS))
        return render_template(
            "settings.html",
            display_name=current_user.display_name or "",
            nickname=current_user.nickname or "",
            grade_occupation=current_user.grade_occupation or "",
            grade_options=list(SETTINGS_GRADES),
            language=current_user.language or "English",
            language_options=list(SETTINGS_LANGUAGES),
            theme_mode=current_user.theme_mode or "light",
            game_reminders=bool(current_user.game_reminders),
            favorite_subject=current_user.favorite_subject or "",
            difficulty_level=current_user.difficulty_level or "medium",
            difficulty_options=list(DIFFICULTY_LEVELS),
            num_questions=num_questions,
            max_questions=MAX_QUIZ_QUESTIONS,
            status=current_user.status or "Ready to play",
            status_options=list(SETTINGS_STATUSES),
        )

    @app.route("/api/settings/save", methods=["POST"])
    @login_required
    def settings_save():
        """Persist settings form (single Save for all 3 cards)."""
        payload = request.get_json(silent=True) or {}

        def _clean_str(value, limit=80):
            if value is None:
                return None, None
            if not isinstance(value, str):
                return None, "must be a string"
            text = value.strip()
            if len(text) > limit:
                return None, f"must be at most {limit} characters"
            return (text or None), None

        errors = {}

        if "display_name" in payload:
            display_name, err = _clean_str(payload.get("display_name"), 80)
            if err:
                errors["display_name"] = err
        else:
            display_name = current_user.display_name
        if "nickname" in payload:
            nickname, err = _clean_str(payload.get("nickname"), 80)
            if err:
                errors["nickname"] = err
        else:
            nickname = current_user.nickname
        if "grade_occupation" in payload:
            grade, err = _clean_str(payload.get("grade_occupation"), 80)
            if err:
                errors["grade_occupation"] = err
        else:
            grade = current_user.grade_occupation
            err = None
        if "favorite_subject" in payload:
            favorite_subject, err = _clean_str(payload.get("favorite_subject"), 80)
            if err:
                errors["favorite_subject"] = err
        else:
            favorite_subject = current_user.favorite_subject

        language = payload.get("language", current_user.language or "English")
        if language not in SETTINGS_LANGUAGES:
            errors["language"] = f"must be one of: {', '.join(SETTINGS_LANGUAGES)}"

        theme_mode = payload.get("theme_mode", current_user.theme_mode or "light")
        if theme_mode not in SETTINGS_THEMES:
            errors["theme_mode"] = "must be 'light' or 'dark'"

        game_reminders = payload.get(
            "game_reminders",
            bool(current_user.game_reminders),
        )
        if not isinstance(game_reminders, bool):
            errors["game_reminders"] = "must be true or false"

        difficulty_level = payload.get(
            "difficulty_level", current_user.difficulty_level or "medium"
        )
        if not isinstance(difficulty_level, str):
            errors["difficulty_level"] = "must be a string"
        else:
            difficulty_level = difficulty_level.strip().lower()
            if difficulty_level not in DIFFICULTY_LEVELS:
                errors["difficulty_level"] = (
                    f"must be one of: {', '.join(DIFFICULTY_LEVELS)}"
                )

        if "default_num_questions" in payload:
            try:
                num_questions = int(payload.get("default_num_questions"))  # type: ignore[arg-type] -- None/str handled by except below
            except (TypeError, ValueError):
                errors["default_num_questions"] = "must be a whole number"
                num_questions = None
            else:
                if not 1 <= num_questions <= MAX_QUIZ_QUESTIONS:
                    errors["default_num_questions"] = (
                        f"must be between 1 and {MAX_QUIZ_QUESTIONS}"
                    )
        else:
            try:
                num_questions = int(current_user.default_num_questions or 10)
            except (TypeError, ValueError):
                num_questions = 10

        status = payload.get("status", current_user.status or "Ready to play")
        if not isinstance(status, str) or status not in SETTINGS_STATUSES:
            errors["status"] = f"must be one of: {', '.join(SETTINGS_STATUSES)}"

        if errors:
            return jsonify({"error": "Invalid settings.", "fields": errors}), 400

        current_user.display_name = display_name
        current_user.nickname = nickname
        current_user.grade_occupation = grade
        current_user.favorite_subject = favorite_subject
        current_user.language = language
        current_user.theme_mode = theme_mode
        current_user.game_reminders = game_reminders
        current_user.difficulty_level = difficulty_level
        current_user.default_num_questions = num_questions
        current_user.status = status
        db.session.commit()
        # Full UI plan: apply new UI language immediately.
        try:
            session["locale"] = LANGUAGE_TO_LOCALE.get(language, "en")
        except Exception:
            pass
        return jsonify(
            {
                "ok": True,
                "settings": {
                    "display_name": current_user.display_name,
                    "nickname": current_user.nickname,
                    "grade_occupation": current_user.grade_occupation,
                    "favorite_subject": current_user.favorite_subject,
                    "language": current_user.language,
                    "theme_mode": current_user.theme_mode,
                    "game_reminders": bool(current_user.game_reminders),
                    "difficulty_level": current_user.difficulty_level,
                    "default_num_questions": current_user.default_num_questions,
                    "status": current_user.status,
                },
            }
        )

    @app.route("/api/account/erase-data", methods=["POST"])
    @login_required
    def account_erase_data():
        """Reset gameplay stats but keep the account (Erase button)."""
        current_user.score = 0
        current_user.best_score = 0
        current_user.total_games_played = 0
        current_user.total_wins = 0
        current_user.total_powerups_used = 0
        current_user.most_used_powerup = None
        db.session.commit()
        session.pop("quiz", None)
        session.pop("last_result", None)
        return jsonify({"ok": True})

    @app.route("/api/account", methods=["DELETE"])
    @login_required
    def account_delete():
        """Delete the account entirely (Delete button)."""
        user_id = current_user.id
        try:
            from flask_login import logout_user as _logout_user

            _logout_user()
        except Exception:
            pass
        session.pop("quiz", None)
        session.pop("last_result", None)
        session.clear()
        user = db.session.get(User, user_id)
        if user is not None:
            db.session.delete(user)
            db.session.commit()
        return jsonify({"ok": True})

    @app.route("/guide")
    def guide():
        return render_template("guide.html")

    @app.route("/leaderboard")
    def leaderboard():
        def _status_dot(status):
            value = (status or "").strip().lower()
            if value == "ready to play":
                return "ready"
            if value == "do not disturb":
                return "busy"
            return "offline"

        users = User.query.order_by(
            User.best_score.desc(), User.total_wins.desc(), User.id.asc()  # type: ignore[attr-defined]
        ).all()
        current_id = current_user.id if current_user.is_authenticated else None
        board = []
        for rank, user in enumerate(users, start=1):
            name = display_name_of(user)
            best = user.best_score or 0
            board.append(
                {
                    "rank": rank,
                    "name": name,
                    "is_you": user.id == current_id,
                    "status": user.status or "Ready to play",
                    "dot": _status_dot(user.status),
                    "initial": (name[:1] or "P").upper(),
                    "best_score": best,
                }
            )
        return render_template("leaderboard.html", leaderboard=board)

    @app.route("/gameplay")
    @login_required
    def gameplay():
        try:
            num = int(current_user.default_num_questions or 10)
        except (TypeError, ValueError):
            num = 10
        num = max(1, min(num, MAX_QUIZ_QUESTIONS))
        return render_template(
            "gameplay.html",
            player_name=display_name_of(current_user),
            player_rank=rank_of(current_user.id),
            player_score=f"{current_user.score or 0:,}",
            num_questions=num,
        )

    @app.route("/api/quiz/generate", methods=["POST"])
    @login_required
    def quiz_generate():
        """
        Generate a personalised quiz via Ollama for the current user.

        Answers stay server-side in the Flask session; the response only
        contains questions and options.
        """

        payload = request.get_json(silent=True) or {}
        try:
            num = int(
                payload.get("num_questions") or current_user.default_num_questions or 10
            )
        except (TypeError, ValueError):
            num = 10
        num = max(1, min(num, MAX_QUIZ_QUESTIONS))
        difficulty = (
            payload.get("difficulty") or current_user.difficulty_level or "medium"
        )
        if not isinstance(difficulty, str):
            difficulty = "medium"
        difficulty = difficulty.strip().lower()
        if difficulty not in DIFFICULTY_LEVELS:
            difficulty = "medium"
        powerups_enabled = payload.get("powerups_enabled", True)
        if not isinstance(powerups_enabled, bool):
            powerups_enabled = True
        try:
            questions = generate_questions(current_user, num, difficulty)
        except QuizConfigError as exc:
            return jsonify({"error": str(exc)}), 503
        except QuizGenerationError as exc:
            return jsonify({"error": str(exc)}), 502
        session["quiz"] = {
            "questions": questions,
            "index": 0,
            "score": 0,
            "started_at": None,
            "limit_ms": QUESTION_TIME_LIMIT_MS,
            "powerups_enabled": powerups_enabled,
            "difficulty": difficulty,
            "offered": None,
            "powerup_used": False,
            "powerup_counts": {},
            "double_armed": False,
            "finished": False,
        }
        session.pop("last_result", None)
        public = [
            {key: q[key] for key in ("question", "options") if key in q}
            for q in questions
        ]
        return jsonify({"questions": public, "total": len(public)})

    @app.route("/api/quiz/state")
    @login_required
    def quiz_state():
        """Return the current question (answers stay server-side).

        Serving state also starts the server-side timer for the question
        and rolls a random power-up, so speed bonuses need no JS clock.
        """
        quiz = _get_quiz()
        if quiz is None:
            return jsonify({"error": "No active quiz. Start a game first."}), 404
        if quiz.get("finished"):
            return jsonify({"error": "Quiz already finished."}), 409
        if quiz.get("started_at") is None:
            quiz["started_at"] = time.time()
            if quiz.get("powerups_enabled") and quiz.get("offered") is None:
                quiz["offered"] = (
                    random.choice(POWERUP_KINDS)
                    if random.random() < POWERUP_CHANCE
                    else None
                )
            quiz["powerup_used"] = False
            _store_quiz(quiz)
        return jsonify(_public_state(quiz))

    @app.route("/api/quiz/answer", methods=["POST"])
    @login_required
    def quiz_answer():
        """Grade one answer against the current question and advance."""
        quiz = _get_quiz()
        if quiz is None:
            return jsonify({"error": "No active quiz."}), 404
        if quiz.get("finished"):
            return jsonify({"error": "Quiz already finished."}), 409
        payload = request.get_json(silent=True) or {}
        option = payload.get("option_index")
        qindex = payload.get("question_index")
        if (
            isinstance(option, bool)
            or not isinstance(option, int)
            or not 0 <= option <= 3
            or not isinstance(qindex, int)
            or qindex != quiz.get("index")
        ):
            return jsonify({"error": "Stale or invalid answer."}), 409
        questions = quiz["questions"]
        current = questions[quiz["index"]]
        started = quiz.get("started_at") or time.time()
        limit = quiz.get("limit_ms") or QUESTION_TIME_LIMIT_MS
        elapsed = max(0, min(int((time.time() - started) * 1000), limit))
        correct = option == current["answer_index"]
        points = 0
        if correct:
            points = BASE_POINTS + round(SPEED_BONUS_POINTS * (1 - elapsed / limit))
            if quiz.get("double_armed"):
                points *= 2
        quiz["score"] = quiz.get("score", 0) + points
        quiz["index"] += 1
        quiz["started_at"] = None
        quiz["offered"] = None
        quiz["powerup_used"] = False
        quiz["double_armed"] = False
        quiz["limit_ms"] = QUESTION_TIME_LIMIT_MS
        finished = quiz["index"] >= len(questions)
        if finished:
            quiz["finished"] = True
        _store_quiz(quiz)
        return jsonify(
            {
                "correct": correct,
                "correct_index": current["answer_index"],
                "points_awarded": points,
                "quiz_score": quiz["score"],
                "answered_index": qindex,
                "total": len(questions),
                "finished": finished,
            }
        )

    @app.route("/api/quiz/powerup", methods=["POST"])
    @login_required
    def quiz_powerup():
        """Apply the power-up offered for the current question."""
        quiz = _get_quiz()
        if quiz is None:
            return jsonify({"error": "No active quiz."}), 404
        if quiz.get("finished"):
            return jsonify({"error": "Quiz already finished."}), 409
        if not quiz.get("powerups_enabled"):
            return jsonify({"error": "Power-ups are disabled."}), 409
        payload = request.get_json(silent=True) or {}
        kind = payload.get("kind")
        if (
            kind not in POWERUP_KINDS
            or kind != quiz.get("offered")
            or quiz.get("powerup_used")
            or quiz.get("started_at") is None
        ):
            return jsonify({"error": "Power-up not available."}), 409
        current = quiz["questions"][quiz["index"]]
        counts = quiz.get("powerup_counts", {})
        counts[kind] = counts.get(kind, 0) + 1
        quiz["powerup_counts"] = counts
        quiz["powerup_used"] = True
        data: dict[str, Any] = {"kind": kind}
        if kind == "double":
            quiz["double_armed"] = True
        elif kind == "fifty":
            wrong = [i for i in range(4) if i != current["answer_index"]]
            data["removed"] = sorted(random.sample(wrong, 2))
        elif kind == "calc":
            quiz["limit_ms"] = (
                quiz.get("limit_ms") or QUESTION_TIME_LIMIT_MS
            ) + QUESTION_TIME_BONUS_MS
            data["limit_ms"] = quiz["limit_ms"]
        elif kind == "hint":
            data["hint"] = current["options"][current["answer_index"]][:1]
        _store_quiz(quiz)
        return jsonify(data)

    @app.route("/api/quiz/finish", methods=["POST"])
    @login_required
    def quiz_finish():
        """Persist a finished quiz to the player's stats (idempotent)."""
        from sqlalchemy import func as _func

        quiz = session.get("quiz")
        if quiz is None:
            last = session.get("last_result")
            if last:
                return jsonify(last)
            return jsonify({"error": "No active quiz."}), 404
        if not quiz.get("finished"):
            return jsonify({"error": "Answer all questions first."}), 409
        total = quiz.get("score", 0)
        me = current_user
        others_best = (
            db.session.query(_func.max(User.best_score))
            .filter(User.id != me.id)
            .scalar()
            or 0
        )
        is_win = total > others_best
        me.score = total
        if total > (me.best_score or 0):
            me.best_score = total
        me.total_games_played = (me.total_games_played or 0) + 1
        if is_win:
            me.total_wins = (me.total_wins or 0) + 1
        counts = quiz.get("powerup_counts", {})
        used = sum(counts.values())
        if used:
            me.total_powerups_used = (me.total_powerups_used or 0) + used
            me.most_used_powerup = POWERUP_LABELS[max(counts, key=counts.get)]
        db.session.commit()
        summary = {
            "quiz_score": total,
            "total": len(quiz["questions"]),
            "best_score": me.best_score or 0,
            "is_win": is_win,
            "powerups_used": used,
        }
        session.pop("quiz", None)
        session["last_result"] = summary
        return jsonify(summary)

    with app.app_context():
        db.create_all()

    return app


app = create_app()


# Single family-wide Ollama key loaded from .env
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", os.getenv("OLLAMA-API-KEY"))
# Cloud text model used for quiz generation. Must be one of the models
# covered by the family's free usage credits (e.g. gpt-oss:20b).
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "https://ollama.com")

MAX_QUIZ_QUESTIONS = 20

DIFFICULTY_LEVELS = ("easy", "medium", "hard")

# Scoring: correct answers earn BASE_POINTS plus a speed bonus of up to
# SPEED_BONUS_POINTS scaling linearly to zero at the per-question time cap.
BASE_POINTS = 1000
SPEED_BONUS_POINTS = 500
QUESTION_TIME_LIMIT_MS = 30000
QUESTION_TIME_BONUS_MS = 15000

# Power-ups: randomly offered on ~1 in 3 questions when enabled.
POWERUP_CHANCE = 1 / 3
POWERUP_KINDS = ("double", "fifty", "calc", "hint")
POWERUP_LABELS = {
    "double": "Double Points",
    "fifty": "50:50",
    "calc": "Extra Time",
    "hint": "Hint",
}

# JSON schema passed as `format=` to Ollama so the model must reply with
# structured quiz JSON.
QUIZ_FORMAT = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "answer_index": {"type": "integer"},
                },
                "required": ["question", "options", "answer_index"],
            },
        }
    },
    "required": ["questions"],
}


class QuizConfigError(Exception):
    """Raised when quiz generation is not configured (e.g. missing key)."""


class QuizGenerationError(Exception):
    """Raised when the model call fails or returns unusable output."""


def get_ollama_client():
    """Build an Ollama cloud client using the family-wide API key."""
    try:
        import ollama
    except ImportError as exc:
        raise QuizConfigError("Quiz service is not installed.") from exc
    if not OLLAMA_API_KEY:
        raise QuizConfigError(
            "Quiz generation is not configured yet (missing OLLAMA_API_KEY). "
            "Add it to .env to enable quizzes."
        )
    return ollama.Client(
        host=OLLAMA_HOST,
        headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"},
        timeout=180,
    )


def build_quiz_messages(user, num_questions, difficulty=None):
    """Build the chat messages personalising the quiz for ``user``."""
    subject = user.favorite_subject or "general knowledge"
    difficulty = (difficulty or user.difficulty_level or "medium").strip().lower()
    if difficulty not in DIFFICULTY_LEVELS:
        difficulty = "medium"
    language = user.language or "English"
    grade = user.grade_occupation or "all ages"
    # Finalised plan: Mandarin Chinese means Simplified (zh_Hans).
    extra = (
        " Use Simplified Chinese."
        if language.strip().lower() in ("mandarin chinese", "chinese", "zh_hans")
        else ""
    )
    return [
        {
            "role": "system",
            "content": (
                "You write fun family quiz questions. Reply with JSON only, "
                "matching the requested schema. Each question has exactly 4 "
                "options with exactly one correct answer."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Write {num_questions} multiple-choice quiz questions about "
                f"{subject} at {difficulty} difficulty, suitable for {grade}. "
                f"Write everything in {language}.{extra}"
            ),
        },
    ]


def strip_code_fences(content):
    """Remove Markdown ``` fences some models add around JSON output."""
    if not isinstance(content, str):
        return content
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().rstrip() == "```":
            lines = lines[:-1]
        elif lines and lines[-1].strip().endswith("```"):
            lines[-1] = lines[-1].strip()[: -len("```")]
        text = "\n".join(lines).strip()
    return text


def resolve_answer_index(item, options):
    """Accept ``answer_index`` (0-3) or ``answer`` (option text)."""
    answer = item.get("answer_index", item.get("answer"))
    if isinstance(answer, bool):
        return None
    if isinstance(answer, int):
        return answer if 0 <= answer <= 3 else None
    if isinstance(answer, str) and answer.strip():
        matches = [
            i
            for i, o in enumerate(options)
            if o.strip().lower() == answer.strip().lower()
        ]
        if len(matches) == 1:
            return matches[0]
    return None


def parse_quiz_content(content):
    """Validate model JSON into a list of question dicts."""
    try:
        data = json.loads(strip_code_fences(content))
    except (TypeError, ValueError) as exc:
        raise QuizGenerationError(
            "Quiz service returned an unreadable response."
        ) from exc
    if isinstance(data, dict):
        raw = data.get("questions")
        if raw is None and isinstance(data.get("question"), str):
            # Some models return one bare question object despite the schema.
            raw = [data]
    elif isinstance(data, list):
        # Some models return a bare array despite the schema.
        raw = data
    else:
        raw = None
    if not isinstance(raw, list):
        raise QuizGenerationError("Quiz service returned an unreadable response.")
    questions = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        options = item.get("options")
        if (
            not isinstance(question, str)
            or not question.strip()
            or not isinstance(options, list)
            or len(options) != 4
            or any(not isinstance(o, str) or not o.strip() for o in options)
        ):
            continue
        answer_index = resolve_answer_index(item, options)
        if answer_index is None:
            continue
        entry = {
            "question": question.strip(),
            "options": [o.strip() for o in options],
            "answer_index": answer_index,
        }
        questions.append(entry)
    if not questions:
        raise QuizGenerationError("Quiz service returned no usable questions.")
    return questions


def _get_quiz():
    """Return the in-progress session quiz, or None."""
    quiz = session.get("quiz")
    if not isinstance(quiz, dict) or not quiz.get("questions"):
        return None
    return quiz


def _store_quiz(quiz):
    session["quiz"] = quiz


def _public_state(quiz):
    """Current question without answers, plus progress and score."""
    index = quiz.get("index", 0)
    question = quiz["questions"][index]
    return {
        "question": question["question"],
        "options": question["options"],
        "index": index,
        "total": len(quiz["questions"]),
        "quiz_score": quiz.get("score", 0),
        "powerup": quiz.get("offered"),
    }


def generate_questions(user, num_questions, difficulty=None):
    """Generate personalised quiz questions via the Ollama cloud model."""
    client = get_ollama_client()
    messages = build_quiz_messages(user, num_questions, difficulty)
    try:
        response = client.chat(
            model=OLLAMA_MODEL,
            messages=messages,
            stream=False,
            format=QUIZ_FORMAT,
            options={"temperature": 0.7},
        )
    except QuizConfigError:
        raise
    except Exception as exc:
        raise QuizGenerationError(f"Quiz service failed: {exc}") from exc
    message = getattr(response, "message", None)
    content = getattr(message, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("message", {}).get("content")
    return parse_quiz_content(content)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
