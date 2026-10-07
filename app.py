import json
import os
import random  # re-exported: tests patch app.random for quiz power-ups
import time  # re-exported alongside random
from uuid import uuid4
from dotenv import load_dotenv
from flask import Flask, g, request, session
from flask_mail import Mail
from flask_security import (
    RoleMixin,
    Security,
    SQLAlchemyUserDatastore,
    UserMixin,
    current_user,
)
from flask_security.mail_util import MailUtil
from flask_sqlalchemy import SQLAlchemy

load_dotenv()


def _env(*names, default=""):
    """
    Return first non-empty env var, supporting legacy dash-names in .env.

    :param names: Environment variable names to check in order.
    :param default: Default value if none of the names are set.
    :return: The value of the first set environment variable, or the default.
    :rtype: str
    """

    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def _env_bool(*names, default=False):
    """
    Return a boolean value based on the first non-empty environment variable.

    :param names: Environment variable names to check in order.
    :param default: Default value if none of the names are set.
    :return: The boolean value of the first set environment variable, or the default.
    :rtype: bool
    """

    value = _env(*names, default="")
    if not value:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_port(*names, default=587):
    """
    Return port as int, falling back to default on missing/garbage values.
    If the value is not a valid integer, it will fall back to the default.

    :param names: Environment variable names to check in order.
    :param default: Default port number if none of the names are set or valid.
    :return: The port number as an integer.
    :rtype: int
    """

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
    # Local LAN hardening (keeps 0.0.0.0 sharing, no production TLS).
    "SESSION_COOKIE_HTTPONLY": True,
    "SESSION_COOKIE_SAMESITE": "Lax",
    "REMEMBER_COOKIE_HTTPONLY": True,
    "REMEMBER_COOKIE_SAMESITE": "Lax",
}

# Applied when TESTING is enabled so test_client POSTs don't need tokens.
TESTING_CONFIG = {
    "WTF_CSRF_ENABLED": False,
    "MAIL_SUPPRESS_SEND": True,
}

# Client 1 (E-portfolio): 4 UI languages. DB stores full names,
# locale codes drive template translation (zero-dependency,
# Flask-Security-Too/Flask-User internationalisation equivalent).
# UI strings live in translations.json (previously translations.py).
SUPPORTED_LOCALES = ("en", "es", "hi", "zh_Hans")

LANGUAGE_TO_LOCALE = {
    "English": "en",
    "Spanish": "es",
    "Hindi": "hi",
    "Mandarin Chinese": "zh_Hans",
}

LOCALE_TO_LANGUAGE = {v: k for k, v in LANGUAGE_TO_LOCALE.items()}

LOCALE_TO_HTML = {
    "en": "en",
    "es": "es",
    "hi": "hi",
    "zh_Hans": "zh-Hans",
}


def _load_translations():
    """
    Load UI strings from translations.json (fallback: empty catalogs).

    :return: Dictionary mapping locale codes to string translation dictionaries.
    :rtype: dict
    """

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translations.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return {locale: dict(strings) for locale, strings in data.items()}
    except (OSError, ValueError):
        return {"en": {}, "es": {}, "hi": {}, "zh_Hans": {}}


TRANSLATIONS = _load_translations()


def translate(message, locale):
    """
    Return translated message, falling back to English source.

    :param message: The original English string to translate.
    :param locale: The target locale code (e.g., 'es', 'hi', 'zh_Hans').
    :return: The translated string if available; otherwise, the original message.
    :rtype: str
    """

    if not message:
        return message
    if locale == "en":
        return message
    return TRANSLATIONS.get(locale, {}).get(message, message)


def get_locale():
    """
    Resolve current locale.

    Priority: per-email override (translated mails) > ?lang= >
    session > user setting > Accept-Language > en.

    :return: The resolved locale code.
    :rtype: str
    """

    try:
        from flask import has_request_context

        if not has_request_context():
            return "en"

        try:
            forced = g.get("email_locale")
        except Exception:
            forced = None

        if forced in SUPPORTED_LOCALES:
            return forced

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
    """
    Translate a UI string into the current locale (fallback: English).

    :param message: The original English string to translate.
    :return: The translated string if available; otherwise, the original message.
    :rtype: str
    """

    try:
        return translate(message, get_locale())
    except Exception:
        return message


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
    """
    Build an Ollama cloud client using the family-wide API key.

    :return: An Ollama client instance.
    :rtype: ollama.Client
    :raises QuizConfigError: If the Ollama client library is not installed or the API key is missing.
    """

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
    """
    Build the chat messages personalising the quiz for ``user``.

    :param user: The User object for whom the quiz is generated.
    :param num_questions: The number of quiz questions to generate.
    :param difficulty: Optional difficulty level ('easy', 'medium', 'hard').
    :return: A list of messages formatted for the Ollama chat API.
    :rtype: list
    """

    subject = (user.favorite_subject or "general knowledge").strip()
    difficulty = (difficulty or user.difficulty_level or "medium").strip().lower()
    if difficulty not in DIFFICULTY_LEVELS:
        difficulty = "medium"
    language = (user.language or "English").strip()
    grade = (user.grade_occupation or "all ages").strip()
    # Sanitize free-text grade/subject for prompt injection: single line, capped.
    def _one_line(text, limit=80):
        return " ".join(str(text).split())[:limit] or "general"

    subject = _one_line(subject)
    grade = _one_line(grade)
    language = _one_line(language, 20)
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
    """
    Remove Markdown ``` fences some models add around JSON output.

    :param content: The string content potentially wrapped in code fences.
    :return: The content with code fences removed, if present.
    :rtype: str
    """

    if not isinstance(content, str):
        return content
    text = content.strip()
    if text.startswith("```"):
        # Single-line fence: ```json {...} ``` -> extract inner JSON.
        if "\n" not in text:
            inner = text[3:].strip()
            # Drop optional language tag (e.g. json).
            if inner.lower().startswith("json"):
                inner = inner[4:].strip()
            if inner.endswith("```"):
                inner = inner[:-3].strip()
            return inner
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().rstrip() == "```":
            lines = lines[:-1]
        elif lines and lines[-1].strip().endswith("```"):
            stripped = lines[-1].strip()
            lines[-1] = stripped[: -len("```")].strip()
        text = "\n".join(lines).strip()
    return text


def resolve_answer_index(item, options):
    """
    Resolve the answer index from either an index (0-3) or the answer text.
    Accept ``answer_index`` (0-3) or ``answer`` (option text).

    :param item: The question dictionary containing 'answer_index' or 'answer'.
    :param options: The list of option strings for the question.
    :return: The resolved answer index (0-3) if valid; otherwise, None.
    :rtype: int or None
    """

    answer = item.get("answer_index")
    # Explicit None falls back to 'answer' text (some models send both).
    if answer is None:
        answer = item.get("answer")
    if isinstance(answer, bool):
        return None

    if isinstance(answer, int):
        return answer if 0 <= answer <= 3 else None

    # Float like 1.0 from sloppy models: accept whole values only.
    if isinstance(answer, float):
        if answer.is_integer() and 0 <= int(answer) <= 3:
            return int(answer)
        return None

    if isinstance(answer, str) and answer.strip():
        text = answer.strip()
        # Numeric "1" / letter "B"/"b" shorthands.
        if text in ("0", "1", "2", "3"):
            return int(text)
        if len(text) == 1 and text.upper() in ("A", "B", "C", "D"):
            return "ABCD".index(text.upper())
        matches = [
            i
            for i, o in enumerate(options)
            if o.strip().lower() == text.lower()
        ]

        if len(matches) == 1:
            return matches[0]

    return None


def parse_quiz_content(content):
    """
    Validate model JSON into a list of question dicts.

    :param content: The raw JSON string returned by the quiz model.
    :return: A list of validated question dictionaries.
    :rtype: list
    :raises QuizGenerationError: If the content is unreadable or contains no usable questions.
    """

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
        cleaned = [o.strip() for o in options]
        # Duplicate options make 50:50 / grading ambiguous — drop them.
        if len({o.lower() for o in cleaned}) != 4:
            continue

        entry = {
            "question": question.strip(),
            "options": cleaned,
            "answer_index": answer_index,
        }
        questions.append(entry)

    if not questions:
        raise QuizGenerationError("Quiz service returned no usable questions.")

    return questions


def _get_quiz():
    """
    Return the in-progress session quiz, or None.
    :return: The in-progress session quiz, or None if no quiz is in progress.
    :rtype: dict or None
    """

    quiz = session.get("quiz")
    if not isinstance(quiz, dict) or not quiz.get("questions"):
        return None
    return quiz


def _store_quiz(quiz):
    """
    Persist the quiz dict in the Flask session.

    :param quiz: The quiz state dict (questions, index, score, timers).
    :return: None.
    :rtype: None
    """
    session["quiz"] = quiz


def _public_state(quiz):
    """
    Current question without answers, plus progress and score.

    :param quiz: The in-progress quiz dictionary.
    :return: A dictionary containing the current question, options, index, total questions, quiz score, and any offered power-up.
    :rtype: dict
    """

    index = quiz.get("index", 0)
    questions = quiz.get("questions") or []
    if not isinstance(index, int) or not 0 <= index < len(questions):
        raise IndexError("Quiz index out of range.")
    question = questions[index]
    return {
        "question": question["question"],
        "options": question["options"],
        "index": index,
        "total": len(quiz["questions"]),
        "quiz_score": quiz.get("score", 0),
        "powerup": quiz.get("offered"),
    }


def generate_questions(user, num_questions, difficulty=None):
    """
    Generate personalised quiz questions via the Ollama cloud model.

    :param user: The User object the quiz is personalised for.
    :param num_questions: The number of questions to generate.
    :param difficulty: Optional difficulty level ('easy', 'medium', 'hard').
    :return: A list of validated question dicts.
    :rtype: list
    :raises QuizConfigError: If the client library or API key is missing.
    :raises QuizGenerationError: If the model call fails or returns unusable output.
    """
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
    questions = parse_quiz_content(content)
    # Truncate to what was asked: prevents 50-question cookie bloat when
    # the model ignores the count. Cookie stays small for family LAN.
    try:
        want = max(1, min(int(num_questions or 1), MAX_QUIZ_QUESTIONS))
    except (TypeError, ValueError):
        want = len(questions)
    return questions[:want]


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


class GameSession(db.Model):
    """Family-wide game lobby: one pending/live game notifies all devices.

    Questions stay personalised per player (each client calls
    quiz_generate with the lobby config in their own language);
    this row shares only the start signal + config.
    """

    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default="lobby", nullable=False)
    # lobby -> counting down, active -> live, finished/cancelled -> terminal
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    num_questions = db.Column(db.Integer, default=10, nullable=False)
    difficulty = db.Column(db.String(20), default="medium", nullable=False)
    powerups_enabled = db.Column(db.Boolean, default=True, nullable=False)
    lobby_seconds = db.Column(db.Integer, default=300, nullable=False)
    starts_at = db.Column(db.Float, nullable=False, default=0.0)
    expires_at = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.Float, nullable=False, default=0.0)

    def __init__(
        self,
        status: str = "lobby",
        created_by_id: int | None = None,
        num_questions: int = 10,
        difficulty: str = "medium",
        powerups_enabled: bool = True,
        lobby_seconds: int = 300,
        starts_at: float = 0.0,
        expires_at: float = 0.0,
        created_at: float = 0.0,
    ):
        """
        Initialise a game lobby row.

        Explicit so type checkers see the SQLAlchemy column kwargs.

        :param status: Lobby status ("lobby", "active", "finished", "cancelled").
        :param created_by_id: Id of the user who started the lobby.
        :param num_questions: Number of quiz questions for the game.
        :param difficulty: Difficulty level ('easy', 'medium', 'hard').
        :param powerups_enabled: Whether power-ups are enabled.
        :param lobby_seconds: Countdown seconds before the game goes live.
        :param starts_at: Epoch seconds when the game starts.
        :param expires_at: Epoch seconds when the game expires.
        :param created_at: Epoch seconds when the row was created.
        """
        self.status = status
        self.created_by_id = created_by_id
        self.num_questions = num_questions
        self.difficulty = difficulty
        self.powerups_enabled = powerups_enabled
        self.lobby_seconds = lobby_seconds
        self.starts_at = starts_at
        self.expires_at = expires_at
        self.created_at = created_at


GAME_STATUSES = ("lobby", "active", "finished", "cancelled")
DEFAULT_LOBBY_SECONDS = 300
MIN_LOBBY_SECONDS = 10
MAX_LOBBY_SECONDS = 300
GAME_EXPIRY_GRACE_SECONDS = 120


user_datastore = SQLAlchemyUserDatastore(db, User, Role)


def _recipient_locale(recipient, context_user=None):
    """
    Resolve the email recipient's locale from their stored language.

    Falls back to the request locale and finally to English when the
    recipient or their language preference cannot be determined.

    :param recipient: Email address string or (name, address) list/tuple.
    :param context_user: Optional User object with a ``language`` attribute.
    :return: The resolved locale code.
    :rtype: str
    """
    lang = getattr(context_user, "language", None)
    if lang:
        locale = LANGUAGE_TO_LOCALE.get(lang.strip())
        if locale in SUPPORTED_LOCALES:
            return locale
    try:
        from email.utils import parseaddr as _parseaddr

        addr = recipient[0] if isinstance(recipient, (list, tuple)) else recipient
        if isinstance(addr, str) and "@" in addr:
            # Handle "Name <a@b>" as well as bare addresses.
            _, parsed = _parseaddr(addr)
            lookup = parsed or addr
            found = User.query.filter_by(email=lookup).one_or_none()
            if found is not None:
                locale = LANGUAGE_TO_LOCALE.get((found.language or "").strip())
                if locale in SUPPORTED_LOCALES:
                    return locale
    except Exception:
        pass
    try:
        return get_locale()
    except Exception:
        return "en"


def security_render_template(template, **context):
    """
    Render Flask-Security templates (incl. mails) in recipient locale.

    Sets ``g.email_locale`` for the render so :func:`_` picks the
    recipient's language, then restores the previous value.

    :param template: The template name to render.
    :param context: Template context; may include ``email`` or ``user``.
    :return: The rendered template string.
    :rtype: str
    """
    sentinel = object()
    try:
        previous = g.get("email_locale", sentinel)
    except Exception:
        previous = sentinel
    try:
        locale = _recipient_locale(
            context.get("email") or getattr(context.get("user"), "email", ""),
            context.get("user"),
        )
        g.email_locale = locale
        from flask import render_template as _render

        return _render(template, **context)
    finally:
        try:
            if previous is sentinel:
                g.pop("email_locale", None)
            else:
                g.email_locale = previous
        except Exception:
            pass


class TranslatedMailUtil(MailUtil):
    """Send Flask-Security mails with per-recipient translated subjects."""

    def send_mail(self, template, subject, recipient, sender, body, html, **kwargs):
        """
        Send a Flask-Security mail with a per-recipient translated subject.

        :param template: The mail template name.
        :param subject: The English source subject to translate.
        :param recipient: Email recipient address or list.
        :param sender: The sender address.
        :param body: The plain-text body.
        :param html: The HTML body.
        :param kwargs: Extra context; may include ``user`` for locale lookup.
        :return: The result of the parent ``send_mail`` call.
        """
        from flask import g as _g

        sentinel = object()
        try:
            previous = _g.get("email_locale", sentinel)
        except Exception:
            previous = sentinel
        try:
            locale = _recipient_locale(recipient, kwargs.get("user"))
            subject = translate(subject, locale)
            try:
                _g.email_locale = locale
            except Exception:
                pass
            return super().send_mail(
                template, subject, recipient, sender, body, html, **kwargs
            )
        finally:
            try:
                if previous is sentinel:
                    _g.pop("email_locale", None)
                else:
                    _g.email_locale = previous
            except Exception:
                pass


security = Security(
    mail_util_cls=TranslatedMailUtil, render_template=security_render_template
)


def display_name_of(user):
    """
    Return the best available display name for a user.

    Prefers ``display_name``, then ``nickname``, then the email local part.

    :param user: The User object, or None.
    :return: The display name, or "Player" when unavailable.
    :rtype: str
    """
    if user is None:
        return "Player"
    name = (user.display_name or user.nickname or "").strip()
    if name:
        return name
    email = user.email or ""
    return email.split("@")[0] if "@" in email else "Player"


def rank_of(user_id):
    """
    Return the 1-based leaderboard rank for a user.

    Ordering matches the homepage leaderboard (best_score desc,
    total_wins desc, id asc).

    :param user_id: The primary key of the user to rank.
    :return: The 1-based rank, or 1 when the user is not ranked.
    :rtype: int
    """
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

    View functions live in routes.py and are registered here so the
    factory stays slim.

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

    # Warn on default secrets (local LAN shares the repo publicly).
    # Tests use TESTING=True and are exempt from the fail-fast.
    _secret = app.config.get("SECRET_KEY", "")
    _salt = app.config.get("SECURITY_PASSWORD_SALT", "")
    if (str(_secret).startswith("supersecret") or str(_salt).startswith("supersecret")) and not app.config.get(
        "TESTING"
    ):
        app.logger.warning(
            "SECRET_KEY/SECURITY_PASSWORD_SALT are defaults; "
            "set long random values in .env for LAN use."
        )

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

    # CSRF for JSON fetch (tests disable via WTF_CSRF_ENABLED=False).
    try:
        from flask_wtf.csrf import CSRFProtect

        _csrf = CSRFProtect()
        _csrf.init_app(app)
        # Flask-Security forms already carry hidden_tag(); exempt only
        # the SSE stream (GET) is automatic. JSON POSTs must send
        # X-CSRFToken (see base templates). Exempt nothing here so
        # production is protected; tests bypass via disabled flag.
        app.extensions["famquiz_csrf"] = _csrf
    except Exception as exc:  # pragma: no cover - missing optional wiring
        app.logger.warning("CSRFProtect not initialised: %s", exc)

    @app.after_request
    def _security_headers(resp):
        # Local LAN: no HSTS (http), but deny framing + nosniff.
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        return resp

    from routes import register_routes

    register_routes(app)

    with app.app_context():
        db.create_all()

    return app


app = create_app()


if __name__ == "__main__":
    # Keep 0.0.0.0 for LAN + Tailscale sharing; never debug on LAN (RCE).
    app.run(debug=False, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
