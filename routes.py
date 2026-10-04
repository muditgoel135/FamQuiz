"""View functions for FamQuiz (moved out of the app factory).

Registered via :func:`register_routes`, preserving the original endpoint
names so ``url_for('homepage')`` etc. keep working in templates and tests.
"""

import random
import time
from typing import Any

from flask import jsonify, render_template, request, session
from flask_security import current_user, login_required

from app import (
    BASE_POINTS,
    DIFFICULTY_LEVELS,
    LANGUAGE_TO_LOCALE,
    LOCALE_TO_HTML,
    LOCALE_TO_LANGUAGE,
    MAX_QUIZ_QUESTIONS,
    POWERUP_CHANCE,
    POWERUP_KINDS,
    POWERUP_LABELS,
    QUESTION_TIME_BONUS_MS,
    QUESTION_TIME_LIMIT_MS,
    SPEED_BONUS_POINTS,
    SUPPORTED_LOCALES,
    TRANSLATIONS,
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


def inject_theme():
    try:
        dark = bool(
            current_user.is_authenticated
            and (current_user.theme_mode or "light") == "dark"
        )
    except Exception:
        dark = False
    return {"theme_class": "theme-dark" if dark else ""}


def inject_i18n():
    locale = get_locale()
    return {
        "_": _,
        "current_locale": locale,
        "html_lang": LOCALE_TO_HTML.get(locale, "en"),
        "supported_locales": list(SUPPORTED_LOCALES),
        "locale_to_language": dict(LOCALE_TO_LANGUAGE),
    }


def _persist_lang_param():
    try:
        arg = request.args.get("lang")
        if arg in SUPPORTED_LOCALES:
            session["locale"] = arg
    except Exception:
        pass


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


def guide():
    return render_template("guide.html")


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


def register_routes(app):
    """Register all views on the app (keeps the factory slim)."""
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
    app.add_url_rule(
        "/leaderboard", endpoint="leaderboard", view_func=leaderboard
    )
    app.add_url_rule("/gameplay", endpoint="gameplay", view_func=gameplay)
    app.add_url_rule(
        "/api/quiz/generate",
        endpoint="quiz_generate",
        view_func=quiz_generate,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/quiz/state", endpoint="quiz_state", view_func=quiz_state
    )
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
