"""
View functions for FamQuiz (moved out of the app factory).

Registered via :func:`register_routes`, preserving the original endpoint
names so ``url_for('homepage')`` etc. keep working in templates and tests.
"""

import json
import random
import time
from typing import Any

from flask import (
    Response,
    jsonify,
    render_template,
    request,
    session,
    stream_with_context,
)
from flask_security import current_user, login_required

from app import (
    BASE_POINTS,
    DEFAULT_LOBBY_SECONDS,  # type: ignore
    DIFFICULTY_LEVELS,
    GAME_EXPIRY_GRACE_SECONDS,  # type: ignore
    LANGUAGE_TO_LOCALE,
    LOCALE_TO_HTML,
    LOCALE_TO_LANGUAGE,
    MAX_LOBBY_SECONDS,  # type: ignore
    MAX_QUIZ_QUESTIONS,
    MIN_LOBBY_SECONDS,  # pyright: ignore[reportAttributeAccessIssue]
    POWERUP_CHANCE,
    POWERUP_KINDS,
    POWERUP_LABELS,
    QUESTION_TIME_BONUS_MS,
    QUESTION_TIME_LIMIT_MS,
    SPEED_BONUS_POINTS,
    SUPPORTED_LOCALES,
    TRANSLATIONS,
    GameSession,  # type: ignore
    QuizConfigError,
    QuizGenerationError,
    User,
    _,
    _get_quiz,
    _public_state,
    _store_quiz,
    db,
    display_name_of,
    generate_questions,
    get_locale,
    rank_of,
)

SETTINGS_LANGUAGES = ("English", "Mandarin Chinese", "Spanish", "Hindi")
SETTINGS_GRADES = ("K-12", "College", "Job")
SETTINGS_THEMES = ("light", "dark")
SETTINGS_STATUSES = ("Ready to play", "Do not disturb", "offline")

# Lightweight in-memory rate limits for LAN (no extra dependency).
# {key: [timestamps]}. Skipped when TESTING=True so the suite stays fast.
_RATE_BUCKETS: dict[str, list[float]] = {}


def _rate_limited(key: str, limit: int, window_s: int) -> bool:
    """Return True when key exceeded limit in window (and record hit)."""
    try:
        from flask import current_app

        if current_app.config.get("TESTING"):
            return False
    except Exception:
        pass
    now = time.time()
    hits = _RATE_BUCKETS.get(key, [])
    hits = [t for t in hits if now - t < window_s]
    if len(hits) >= limit:
        _RATE_BUCKETS[key] = hits
        return True
    hits.append(now)
    _RATE_BUCKETS[key] = hits
    return False


def _quiz_cooldown_key() -> str:
    try:
        uid = getattr(current_user, "id", "anon")
    except Exception:
        uid = "anon"
    return f"quiz:{uid}:{request.remote_addr}"


def inject_theme():
    """
    Inject the theme CSS class for templates.

    :return: Context dict with ``theme_class`` ("theme-dark" or "").
    :rtype: dict
    """
    try:
        dark = bool(
            current_user.is_authenticated
            and (current_user.theme_mode or "light") == "dark"
        )
    except Exception:
        dark = False
    return {"theme_class": "theme-dark" if dark else ""}


def inject_i18n():
    """
    Inject i18n helpers and locale metadata for templates.

    :return: Context dict with ``_``, ``current_locale``, ``html_lang``,
        ``supported_locales`` and ``locale_to_language``.
    :rtype: dict
    """
    locale = get_locale()
    return {
        "_": _,
        "current_locale": locale,
        "html_lang": LOCALE_TO_HTML.get(locale, "en"),
        "supported_locales": list(SUPPORTED_LOCALES),
        "locale_to_language": dict(LOCALE_TO_LANGUAGE),
    }


def _persist_lang_param():
    """
    Persist a valid ``?lang=`` query param into the session.

    Runs before each request; invalid values are ignored.

    :return: None.
    :rtype: None
    """
    try:
        arg = request.args.get("lang")
        if arg in SUPPORTED_LOCALES:
            session["locale"] = arg
    except Exception:
        pass


def homepage():
    """
    Render the homepage with leaderboard and player stats.

    :return: The rendered ``index.html`` response.
    :rtype: flask.Response
    """
    from sqlalchemy import func as _func

    def _display_name(user):
        """
        Return the display name for a homepage user.

        :param user: The User object, or None.
        :return: Display name, email local part, or "".
        :rtype: str
        """
        if user is None:
            return ""
        name = (
            getattr(user, "display_name", None) or getattr(user, "nickname", None) or ""
        ).strip()
        if name:
            return name
        email = getattr(user, "email", "") or ""
        return email.split("@")[0] if "@" in email else (email or "Player")

    def _status_dot(status):
        """
        Map a status string to a homepage dot class.

        :param status: The raw status string.
        :return: "ready", "busy" or "offline".
        :rtype: str
        """
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
        db.session.query(_func.coalesce(_func.sum(User.total_games_played), 0)).scalar()
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
    try:
        default_num = int(default_num or 10)
    except (TypeError, ValueError):
        default_num = 10
    default_num = max(1, min(default_num, MAX_QUIZ_QUESTIONS))

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


def i18n_dict(locale):
    """
    Return translated UI strings for JavaScript.

    :param locale: The locale code requested in the URL.
    :return: JSON response with locale, html_lang and strings, or 404 for unsupported locales.
    :rtype: flask.Response
    """
    if locale not in SUPPORTED_LOCALES:
        return jsonify({"error": "Unsupported language."}), 404
    return jsonify(
        {
            "locale": locale,
            "html_lang": LOCALE_TO_HTML.get(locale, "en"),
            "strings": TRANSLATIONS.get(locale, {}),
        }
    )


@login_required
def settings():
    """
    Render the settings page for the current user.

    :return: The rendered ``settings.html`` response.
    :rtype: flask.Response
    """
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


@login_required
def settings_save():
    """
    Persist the settings form (single Save for all 3 cards).

    Accepts a JSON payload, validates each field and updates the
    current user; also applies the new UI language to the session.

    :return: JSON response with ``ok`` and settings, or 400 with field errors.
    :rtype: flask.Response
    """
    payload = request.get_json(silent=True) or {}

    def _clean_str(value, limit=80):
        """
        Strip and validate an optional string settings field.

        :param value: The raw input value.
        :param limit: Maximum allowed length after stripping.
        :return: Tuple of (cleaned value or None, error message or None).
        :rtype: tuple
        """
        if value is None:
            return None, None
        if not isinstance(value, str):
            return None, "must be a string"
        # Single-line: grade/subject go into the LLM prompt.
        text = " ".join(value.split()).strip()
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
        raw_num = payload.get("default_num_questions")
        # bool is a subclass of int: reject True/False explicitly.
        if isinstance(raw_num, bool):
            errors["default_num_questions"] = "must be a whole number"
            num_questions = None
        else:
            try:
                # Reject floats like 5.5 (int() would truncate).
                if isinstance(raw_num, float):
                    raise ValueError("float")
                num_questions = int(raw_num)  # type: ignore[arg-type] -- None/str handled by except below
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


@login_required
def account_erase_data():
    """
    Reset gameplay stats but keep the account (Erase button).

    Clears scores, wins, power-up stats and any active quiz state.

    :return: JSON response with ``ok`` True.
    :rtype: flask.Response
    """
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


@login_required
def account_delete():
    """
    Delete the current user's account entirely (Delete button).

    Logs out, clears the session and removes the user row.

    :return: JSON response with ``ok`` True.
    :rtype: flask.Response
    """
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
        # Cancel own live lobbies so they don't become un-cancellable
        # orphans (game_cancel requires created_by_id match).
        try:
            for g in GameSession.query.filter_by(created_by_id=user_id).all():
                if g.status in ("lobby", "active"):
                    g.status = "cancelled"
            db.session.delete(user)
            db.session.commit()
        except Exception:
            db.session.rollback()
    return jsonify({"ok": True})


def guide():
    """
    Render the how-to-play guide page.

    :return: The rendered ``guide.html`` response.
    :rtype: flask.Response
    """
    return render_template("guide.html")


def leaderboard():
    """
    Render the full leaderboard ordered by best score.

    :return: The rendered ``leaderboard.html`` response.
    :rtype: flask.Response
    """

    def _status_dot(status):
        """
        Map a status string to a leaderboard dot class.

        :param status: The raw status string.
        :return: "ready", "busy" or "offline".
        :rtype: str
        """
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


@login_required
def gameplay():
    """
    Render the gameplay page with player HUD data.

    :return: The rendered ``gameplay.html`` response.
    :rtype: flask.Response
    """
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


@login_required
def quiz_generate():
    """
    Generate a personalised quiz via Ollama for the current user.

    Answers stay server-side in the Flask session; the response only
    contains questions and options.

    :return: JSON response with public questions and total, or an error
        with 502/503 when generation fails or is unconfigured.
    :rtype: flask.Response
    """

    # LAN cost guard: one paid cloud call per 10s per user (tests exempt).
    if _rate_limited(_quiz_cooldown_key(), limit=1, window_s=10):
        return jsonify({"error": "Quiz cooling down. Wait a few seconds."}), 429
    payload = request.get_json(silent=True) or {}
    raw_num = payload.get("num_questions")
    if raw_num is None:
        raw_num = current_user.default_num_questions or 10
    # 0 falls back to default (homepage empty input); bool rejected.
    if isinstance(raw_num, bool):
        num = 10
    else:
        try:
            # 0/"" fall back to the saved default like the homepage does.
            if raw_num == 0 or raw_num == "":
                raise ValueError("fallback")
            num = int(raw_num)
        except (TypeError, ValueError):
            try:
                num = int(current_user.default_num_questions or 10)
            except (TypeError, ValueError):
                num = 10
    num = max(1, min(num, MAX_QUIZ_QUESTIONS))
    difficulty = payload.get("difficulty") or current_user.difficulty_level or "medium"
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
        {key: q[key] for key in ("question", "options") if key in q} for q in questions
    ]
    return jsonify({"questions": public, "total": len(public)})


@login_required
def quiz_state():
    """
    Return the current question (answers stay server-side).

    Serving state also starts the server-side timer for the question
    and rolls a random power-up, so speed bonuses need no JS clock.

    :return: JSON public state, or 404 when no quiz is active, 409 when finished.
    :rtype: flask.Response
    """
    quiz = _get_quiz()
    if quiz is None:
        return jsonify({"error": "No active quiz. Start a game first."}), 404
    if quiz.get("finished"):
        return jsonify({"error": "Quiz already finished."}), 409
    try:
        idx = quiz.get("index", 0)
        if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(
            quiz.get("questions", [])
        ):
            raise IndexError("bad index")
    except Exception:
        return jsonify({"error": "Quiz state corrupted. Start a new game."}), 409
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
    try:
        return jsonify(_public_state(quiz))
    except (IndexError, KeyError, TypeError):
        return jsonify({"error": "Quiz state corrupted. Start a new game."}), 409


@login_required
def quiz_answer():
    """
    Grade one answer against the current question and advance.

    Expects JSON ``option_index`` and ``question_index``; awards base
    plus speed-bonus points and advances the session quiz.

    :return: JSON grading result, or 404/409 on missing, finished or stale quizzes.
    :rtype: flask.Response
    """
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
        or isinstance(qindex, bool)
        or not isinstance(qindex, int)
        or qindex != quiz.get("index")
    ):
        return jsonify({"error": "Stale or invalid answer."}), 409
    # Timer must be started via quiz_state; answering blind gets no free max.
    if quiz.get("started_at") is None:
        return jsonify({"error": "Timer not started. Reload the question."}), 409
    try:
        questions = quiz["questions"]
        current = questions[quiz["index"]]
    except (IndexError, KeyError, TypeError):
        return jsonify({"error": "Quiz state corrupted. Start a new game."}), 409
    started = quiz.get("started_at")
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


@login_required
def quiz_powerup():
    """
    Apply the power-up offered for the current question.

    Expects JSON ``kind`` matching the offered power-up; each kind
    mutates the session quiz (double/fifty/calc/hint).

    :return: JSON power-up effect data, or 404/409 when unavailable.
    :rtype: flask.Response
    """
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
    try:
        current = quiz["questions"][quiz["index"]]
    except (IndexError, KeyError, TypeError):
        return jsonify({"error": "Quiz state corrupted. Start a new game."}), 409
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


@login_required
def quiz_finish():
    """
    Persist a finished quiz to the player's stats (idempotent).

    Updates score, best score, games played, wins and power-up usage;
    repeat calls return the cached summary.

    :return: JSON summary with quiz_score, total, best_score, is_win and powerups_used,
        or 404/409 when no quiz is active or it is unfinished.
    :rtype: flask.Response
    """
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
        db.session.query(_func.max(User.best_score)).filter(User.id != me.id).scalar()
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


# ---------------------------------------------------------------------------
# Shared game lobby (E-portfolio: notify all + auto-open).
# The lobby shares only the start signal + config; questions stay
# personalised per player via quiz_generate in their own language.
# ---------------------------------------------------------------------------


def _refresh_game_status(game):
    """
    Roll a lobby game forward by wall-clock; persist transitions.

    Moves lobby -> active at starts_at and any game -> finished at
    expires_at.

    :param game: The GameSession row to refresh.
    :return: The same game, possibly with an updated status.
    :rtype: GameSession
    """
    now = time.time()
    if game.status in ("finished", "cancelled"):
        return game
    try:
        expires = float(game.expires_at or 0)
    except (TypeError, ValueError):
        expires = 0
    try:
        starts = float(game.starts_at or 0)
    except (TypeError, ValueError):
        starts = 0
    if now >= expires:
        game.status = "finished"
        db.session.commit()
    elif now >= starts and game.status == "lobby":
        game.status = "active"
        db.session.commit()
    return game


def _expire_stale_games():
    """Expire every stale lobby/active row (prevents ghost lobbies)."""
    now = time.time()
    try:
        stale = GameSession.query.filter(
            GameSession.status.in_(["lobby", "active"])  # type: ignore[attr-defined]
        ).all()
    except Exception:
        return
    dirty = False
    for g in stale:
        try:
            expires = float(g.expires_at or 0)
            starts = float(g.starts_at or 0)
        except (TypeError, ValueError):
            continue
        if now >= expires and g.status != "finished":
            g.status = "finished"
            dirty = True
        elif now >= starts and g.status == "lobby":
            g.status = "active"
            dirty = True
    if dirty:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


def _get_live_game():
    """
    Return the current lobby/active game, or None.

    Refreshes all lobby/active rows by wall-clock before returning the
    latest still-live one (older ghosts stay finished).

    :return: The live GameSession, or None when no lobby is active.
    :rtype: GameSession or None
    """
    _expire_stale_games()
    game = (
        GameSession.query.filter(GameSession.status.in_(["lobby", "active"]))  # type: ignore[attr-defined] -- SQLAlchemy column, Pylance sees str from __init__
        .order_by(GameSession.id.desc())
        .first()
    )
    if game is None:
        return None
    return game


def _game_to_dict(game):
    """
    Serialise a GameSession row for JSON/SSE responses.

    :param game: The GameSession row to serialise.
    :return: Dict with id, status, countdown, config and join_url.
    :rtype: dict
    """
    now = time.time()
    starts_in_ms = max(0, int(((game.starts_at or now) - now) * 1000))
    return {
        "id": game.id,
        "status": game.status,
        "starts_in_ms": starts_in_ms,
        "starts_at": game.starts_at,
        "expires_at": game.expires_at,
        "num_questions": game.num_questions,
        "difficulty": game.difficulty,
        "powerups_enabled": bool(game.powerups_enabled),
        "lobby_seconds": game.lobby_seconds,
        "join_url": "/gameplay",
    }


@login_required
def game_start():
    """
    Create a family-wide lobby counting down to a shared start.

    Accepts optional JSON ``num_questions``, ``difficulty``,
    ``powerups_enabled`` and ``lobby_seconds``; rejects when a game
    is already live.

    :return: JSON response with the new game (201) or an error (409).
    :rtype: flask.Response
    """
    payload = request.get_json(silent=True) or {}
    raw_num = payload.get("num_questions")
    if raw_num is None:
        raw_num = getattr(current_user, "default_num_questions", None)
    if raw_num is None or raw_num == "" or raw_num == 0:
        num = 10
    elif isinstance(raw_num, bool):
        num = 10
    else:
        try:
            if isinstance(raw_num, float):
                raise ValueError("float")
            num = int(raw_num)
        except (TypeError, ValueError):
            num = 10
    num = max(1, min(num, MAX_QUIZ_QUESTIONS))
    difficulty = (
        payload.get("difficulty")
        or getattr(current_user, "difficulty_level", None)
        or "medium"
    )
    if not isinstance(difficulty, str):
        difficulty = "medium"
    difficulty = difficulty.strip().lower()
    if difficulty not in DIFFICULTY_LEVELS:
        difficulty = "medium"
    powerups_enabled = payload.get("powerups_enabled", True)
    if not isinstance(powerups_enabled, bool):
        powerups_enabled = True
    raw_lobby = payload.get("lobby_seconds", DEFAULT_LOBBY_SECONDS)
    if isinstance(raw_lobby, bool):
        lobby_seconds = DEFAULT_LOBBY_SECONDS
    else:
        try:
            if isinstance(raw_lobby, float):
                raise ValueError("float")
            lobby_seconds = int(raw_lobby)
        except (TypeError, ValueError):
            lobby_seconds = DEFAULT_LOBBY_SECONDS
    lobby_seconds = max(MIN_LOBBY_SECONDS, min(lobby_seconds, MAX_LOBBY_SECONDS))

    # LAN spam guard: one lobby per 5s per user (tests exempt).
    try:
        from flask import current_app as _ca

        _testing = bool(_ca.config.get("TESTING"))
    except Exception:
        _testing = False
    if not _testing and _rate_limited(f"start:{current_user.id}", limit=1, window_s=5):
        return jsonify({"error": "Slow down. Wait a few seconds."}), 429

    existing = _get_live_game()
    if existing is not None and existing.status in ("lobby", "active"):
        return (
            jsonify(
                {"error": "A game is already live.", "game": _game_to_dict(existing)}
            ),
            409,
        )

    now = time.time()
    starts_at = now + lobby_seconds
    duration = num * (QUESTION_TIME_LIMIT_MS / 1000.0) + GAME_EXPIRY_GRACE_SECONDS
    game = GameSession(
        status="lobby",
        created_by_id=current_user.id,
        num_questions=num,
        difficulty=difficulty,
        powerups_enabled=powerups_enabled,
        lobby_seconds=lobby_seconds,
        starts_at=starts_at,
        expires_at=starts_at + duration,
        created_at=now,
    )
    db.session.add(game)
    db.session.commit()
    return jsonify({"game": _game_to_dict(game)}), 201


@login_required
def game_status():
    """
    Return the current lobby/live game for polling.

    :return: JSON response with ``active_game`` (dict or None).
    :rtype: flask.Response
    """
    game = _get_live_game()
    if game is None or game.status not in ("lobby", "active"):
        return jsonify({"active_game": None})
    return jsonify({"active_game": _game_to_dict(game)})


@login_required
def game_join():
    """
    Return lobby config so the joiner can generate own-language questions.

    :return: JSON response with the live game, or 404 when none exists.
    :rtype: flask.Response
    """
    game = _get_live_game()
    if game is None or game.status not in ("lobby", "active"):
        return jsonify({"error": "No live game. Start one from the homepage."}), 404
    return jsonify({"game": _game_to_dict(game)})


@login_required
def game_cancel():
    """
    Cancel the live lobby (starter only).

    :return: JSON response with ``ok`` and the cancelled game,
        or 403/404 when not permitted or no game is live.
    :rtype: flask.Response
    """
    game = _get_live_game()
    if game is None or game.status not in ("lobby", "active"):
        return jsonify({"error": "No live game to cancel."}), 404
    if game.created_by_id != current_user.id:
        return jsonify({"error": "Only the starter can cancel this game."}), 403
    game.status = "cancelled"
    db.session.commit()
    return jsonify({"ok": True, "game": _game_to_dict(game)})


@login_required
def game_events():
    """Server-Sent Events: game-pending/game-live/game-cancelled + heartbeats.

    Query ?once=1 returns a single snapshot event and closes (for tests
    and restrictive proxies); otherwise streams until the game ends.

    :return: SSE response with snapshot/update/end events.
    :rtype: flask.Response
    """
    once = request.args.get("once") == "1"

    def _snapshot():
        """
        Build a single SSE snapshot of the current game state.

        :return: Dict with ``type`` (game-pending/game-live/game-none)
            plus game fields when live.
        :rtype: dict
        """
        game = _get_live_game()
        if game is None or game.status not in ("lobby", "active"):
            return {"type": "game-none", "active_game": None}
        data = _game_to_dict(game)
        kind = "game-live" if game.status == "active" else "game-pending"
        return {"type": kind, **data}

    if once:
        body = "event: snapshot\ndata: %s\n\n" % json.dumps(_snapshot())
        return Response(
            body,
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def generate():
        """
        Stream game snapshots and heartbeats until the game ends.

        Wrapped with ``stream_with_context`` at the call site so the
        request context stays alive while streaming.

        :return: Generator yielding SSE-formatted snapshot/update/end events.
        :rtype: collections.abc.Generator
        """
        def _dedup_key(snap):
            # Countdown ms changes every second: exclude it from dedup so
            # we don't spam updates; the 1s JS ticker recomputes locally.
            return json.dumps(
                {k: v for k, v in snap.items() if k != "starts_in_ms"},
                sort_keys=True,
            )

        try:
            first = _snapshot()
            yield "event: snapshot\ndata: %s\n\n" % json.dumps(first)
            last = _dedup_key(first)
            idle = 0
            # Initial terminal snapshot ends immediately (finished test).
            if first.get("type") == "game-none":
                yield "event: end\ndata: {}\n\n"
                return
            while True:
                time.sleep(2)
                snap = _snapshot()
                encoded = _dedup_key(snap)
                if encoded != last:
                    last = encoded
                    yield "event: update\ndata: %s\n\n" % json.dumps(snap)
                    idle = 0
                    if snap.get("type") in ("game-none",):
                        yield "event: end\ndata: {}\n\n"
                        break
                else:
                    idle += 1
                    if idle % 7 == 0:
                        yield ": heartbeat\n\n"
                game = _get_live_game()
                if game is None:
                    # Already emitted end via game-none above; avoid double.
                    break
                try:
                    exp = float(game.expires_at or 0)
                except (TypeError, ValueError):
                    exp = 0
                if time.time() > exp + 30:
                    yield "event: end\ndata: {}\n\n"
                    break
        except GeneratorExit:
            # Browser disconnected: stop DB polling, free the worker.
            return
        except Exception:
            try:
                yield "event: end\ndata: {}\n\n"
            except Exception:
                pass
            return

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def register_routes(app):
    """
    Register all views on the app (keeps the factory slim).

    :param app: The Flask application to register routes on.
    :return: None.
    :rtype: None
    """

    app.context_processor(inject_theme)
    app.context_processor(inject_i18n)
    app.before_request(_persist_lang_param)

    app.add_url_rule("/", endpoint="homepage", view_func=homepage)
    app.add_url_rule(
        "/api/i18n/<locale>.json", endpoint="i18n_dict", view_func=i18n_dict
    )

    app.add_url_rule("/settings", endpoint="settings", view_func=settings)
    app.add_url_rule(
        "/api/settings/save",
        endpoint="settings_save",
        view_func=settings_save,
        methods=["POST"],
    )

    app.add_url_rule(
        "/api/account/erase-data",
        endpoint="account_erase_data",
        view_func=account_erase_data,
        methods=["POST"],
    )

    app.add_url_rule(
        "/api/account",
        endpoint="account_delete",
        view_func=account_delete,
        methods=["DELETE"],
    )
    app.add_url_rule("/guide", endpoint="guide", view_func=guide)
    app.add_url_rule("/leaderboard", endpoint="leaderboard", view_func=leaderboard)
    app.add_url_rule("/gameplay", endpoint="gameplay", view_func=gameplay)
    app.add_url_rule(
        "/api/quiz/generate",
        endpoint="quiz_generate",
        view_func=quiz_generate,
        methods=["POST"],
    )

    app.add_url_rule("/api/quiz/state", endpoint="quiz_state", view_func=quiz_state)
    app.add_url_rule(
        "/api/quiz/answer",
        endpoint="quiz_answer",
        view_func=quiz_answer,
        methods=["POST"],
    )

    app.add_url_rule(
        "/api/quiz/powerup",
        endpoint="quiz_powerup",
        view_func=quiz_powerup,
        methods=["POST"],
    )

    app.add_url_rule(
        "/api/quiz/finish",
        endpoint="quiz_finish",
        view_func=quiz_finish,
        methods=["POST"],
    )

    app.add_url_rule(
        "/api/game/start",
        endpoint="game_start",
        view_func=game_start,
        methods=["POST"],
    )

    app.add_url_rule("/api/game/status", endpoint="game_status", view_func=game_status)
    app.add_url_rule(
        "/api/game/join",
        endpoint="game_join",
        view_func=game_join,
        methods=["POST"],
    )

    app.add_url_rule(
        "/api/game/cancel",
        endpoint="game_cancel",
        view_func=game_cancel,
        methods=["POST"],
    )

    app.add_url_rule("/api/game/events", endpoint="game_events", view_func=game_events)
