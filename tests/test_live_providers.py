"""Live provider tests — REAL Ollama/SMTP calls (quota spend).

Merged so every credit-spending test lives in one module (formerly
test_live_mail.py, test_live_mail_extra.py, test_ollama_live.py and
test_ollama_live_extra.py).

Mail tests are skipped automatically when MAIL_SERVER/MAIL_PASSWORD are
missing. Isolated temp DB; recipient == sender so no external spam.
Delivery confirmed via Mailjet Messages API (SMTP acceptance is not
proof). Ollama tests are skipped when the local server is unreachable.
``pytest.ini`` deselects "live" by default.
"""

import base64
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parseaddr
from types import SimpleNamespace

import pytest

import app as app_module

pytestmark = [pytest.mark.live, pytest.mark.slow]


# ==== merged from test_live_mail.py ====
# Module-wide marker: sends a REAL email and polls the Mailjet API for up
# to 120s. ``pytest.ini`` deselects "live" by default; run with ``-m live``.

MJ_MESSAGES_URL = "https://api.mailjet.com/v3/REST/message"
DELIVERED_STATUSES = {"sent", "opened", "clicked"}


def _sender_address(flask_app):
    """
    Return the sender address as the live-mail recipient.

    Recipient = sender, so the test tracks whatever .env configures.

    :param flask_app: The Flask app with mail config.
    :return: The sender email address.
    :rtype: str
    """

    _, address = parseaddr(flask_app.config.get("MAIL_DEFAULT_SENDER", ""))
    assert address and "@" in address, "MAIL_DEFAULT_SENDER not configured"
    return address


def _mailjet_status(api_key, secret, recipient, sent_after, timeout=120):
    """
    Poll Mailjet's Messages API until our message shows up.

    :param api_key: The Mailjet API key.
    :param secret: The Mailjet API secret.
    :param recipient: The recipient address to search for.
    :param sent_after: Only consider messages arriving after this time.
    :param timeout: Maximum seconds to poll.
    :return: Tuple (ok, detail); ok=True only if Mailjet reports a delivered status.
    :rtype: tuple
    """

    token = base64.b64encode(f"{api_key}:{secret}".encode()).decode()
    deadline = time.time() + timeout
    last_detail = "no messages returned yet"
    while time.time() < deadline:
        query = urllib.parse.urlencode({"To": recipient, "Limit": 5, "Sort": "ID DESC"})
        req = urllib.request.Request(
            f"{MJ_MESSAGES_URL}?{query}",
            headers={"Authorization": f"Basic {token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                messages = json.load(resp).get("Data", [])
        except Exception as exc:  # network/API blip: keep polling
            last_detail = f"api error: {exc}"
            time.sleep(10)
            continue
        fresh = [m for m in messages if _arrived_at(m) and _arrived_at(m) >= sent_after]
        if fresh:
            statuses = sorted({m.get("Status") for m in fresh})
            last_detail = f"statuses={statuses} count={len(fresh)}"
            if any(m.get("Status") in DELIVERED_STATUSES for m in fresh):
                return True, last_detail
        else:
            last_detail = f"{len(messages)} message(s) found, none newer than send"
        time.sleep(10)
    return False, last_detail


def _arrived_at(message):
    """
    Parse a Mailjet message ArrivedAt to UTC datetime.

    :param message: The message fixture.
    :return: Helper value for tests.
    :rtype: object
    """

    try:
        return datetime.fromisoformat(
            message.get("ArrivedAt", "").replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def test_forgot_password_sends_real_email_to_user(tmp_path):
    """
    Verify forgot password sends real email to user.

    :param tmp_path: The tmp_path fixture.
    """

    # Check both canonical and legacy dash-names (.env uses SMTP-SERVER etc).
    has_server = bool(os.getenv("MAIL_SERVER") or os.getenv("SMTP-SERVER"))
    has_pass = bool(os.getenv("MAIL_PASSWORD"))
    if not has_server or not has_pass:
        pytest.skip("MAIL_SERVER/MAIL_PASSWORD not configured; live mail skipped.")
    from app import create_app, db, user_datastore

    flask_app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'live.db'}",
            # Explicit overrides beat TESTING_CONFIG in create_app, so this
            # genuinely re-enables sending (Flask-Mail snapshots suppress
            # at init time; flipping config afterwards would NOT work).
            "MAIL_SUPPRESS_SEND": False,
        }
    )
    # Fail loudly if creds are absent.
    assert flask_app.config.get("MAIL_SERVER"), "MAIL_SERVER not configured"
    assert flask_app.config.get("MAIL_PASSWORD"), "MAIL_PASSWORD not configured"
    assert (
        flask_app.extensions["mail"].suppress is False
    ), "mail extension still suppressing sends"

    from flask_security.utils import hash_password

    recipient = _sender_address(flask_app)
    with flask_app.app_context():
        db.create_all()
        user_datastore.create_user(
            email=recipient, password=hash_password("live-mail-probe-123")
        )
        db.session.commit()

    client = flask_app.test_client()
    sent_after = datetime.now(timezone.utc)
    resp = client.post("/reset", data={"email": recipient})
    assert resp.status_code == 200

    # SMTP acceptance isn't delivery: confirm via Mailjet's API that the
    # message exists with a delivered status (else it bounced / went spam).
    ok, detail = _mailjet_status(
        flask_app.config.get("MAIL_USERNAME"),
        flask_app.config.get("MAIL_PASSWORD"),
        recipient,
        sent_after,
    )
    assert ok, f"Mailjet has no delivered message to {recipient}: {detail}"


# ==== merged from test_live_mail_extra.py ====
def _needs_creds():
    has_server = bool(os.getenv("MAIL_SERVER") or os.getenv("SMTP-SERVER"))
    return not (has_server and os.getenv("MAIL_PASSWORD"))


needs_mail = pytest.mark.skipif(
    _needs_creds(), reason="MAIL_SERVER/MAIL_PASSWORD not configured."
)

# Module-wide marker: sends REAL emails and polls the Mailjet API for up
# to 120s each. ``pytest.ini`` deselects "live" by default.
# The no-spend body smoke test lives in tests/test_mail_bodies.py.


def _live_app(tmp_path, name):
    from app import create_app

    flask_app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / name}",
            "MAIL_SUPPRESS_SEND": False,
        }
    )
    assert flask_app.config.get("MAIL_SERVER")
    assert flask_app.config.get("MAIL_PASSWORD")
    assert flask_app.extensions["mail"].suppress is False
    return flask_app


@needs_mail
def test_change_notice_live(tmp_path):
    from flask_security.utils import hash_password

    from app import db, user_datastore

    flask_app = _live_app(tmp_path, "change.db")
    recipient = _sender_address(flask_app)
    with flask_app.app_context():
        db.create_all()
        user_datastore.create_user(
            email=recipient, password=hash_password("live-mail-probe-123")
        )
        db.session.commit()
    client = flask_app.test_client()
    client.post("/login", data={"email": recipient, "password": "live-mail-probe-123"})
    sent_after = datetime.now(timezone.utc)
    resp = client.post(
        "/change",
        data={
            "password": "live-mail-probe-123",
            "new_password": "live-changed-456",
            "new_password_confirm": "live-changed-456",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    ok, detail = _mailjet_status(
        flask_app.config.get("MAIL_USERNAME"),
        flask_app.config.get("MAIL_PASSWORD"),
        recipient,
        sent_after,
    )
    assert ok, f"no delivered change notice to {recipient}: {detail}"


@needs_mail
def test_reset_notice_live(tmp_path):
    from flask_security.recoverable import generate_reset_password_token
    from flask_security.utils import hash_password

    from app import User, db, user_datastore

    flask_app = _live_app(tmp_path, "notice.db")
    recipient = _sender_address(flask_app)
    with flask_app.app_context():
        db.create_all()
        user_datastore.create_user(
            email=recipient, password=hash_password("live-mail-probe-123")
        )
        db.session.commit()
        user = User.query.filter_by(email=recipient).one()
        token = generate_reset_password_token(user)
    client = flask_app.test_client()
    sent_after = datetime.now(timezone.utc)
    resp = client.post(
        f"/reset/{token}",
        data={"password": "live-new-789", "password_confirm": "live-new-789"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    ok, detail = _mailjet_status(
        flask_app.config.get("MAIL_USERNAME"),
        flask_app.config.get("MAIL_PASSWORD"),
        recipient,
        sent_after,
    )
    assert ok, f"no delivered reset notice to {recipient}: {detail}"


@needs_mail
def test_forgot_spanish_live(tmp_path):
    from flask_security.utils import hash_password

    from app import User, db, user_datastore

    flask_app = _live_app(tmp_path, "es.db")
    recipient = _sender_address(flask_app)
    with flask_app.app_context():
        db.create_all()
        user_datastore.create_user(
            email=recipient, password=hash_password("live-mail-probe-123")
        )
        db.session.commit()
        user = User.query.filter_by(email=recipient).one()
        user.language = "Spanish"
        db.session.commit()
    client = flask_app.test_client()
    sent_after = datetime.now(timezone.utc)
    assert client.post("/reset", data={"email": recipient}).status_code == 200
    ok, detail = _mailjet_status(
        flask_app.config.get("MAIL_USERNAME"),
        flask_app.config.get("MAIL_PASSWORD"),
        recipient,
        sent_after,
    )
    assert ok, f"no delivered Spanish reset to {recipient}: {detail}"


# ==== merged from test_ollama_live.py ====
# Exact cloud model names eligible for free usage credits.
LIVE_MODELS = (
    "gemma4:31b",
    "gpt-oss:120b",
    "gpt-oss:20b",
    "nemotron-3-nano:30b",
    "nemotron-3-super",
    "nemotron-3-ultra",
)

requires_key = pytest.mark.skipif(
    not os.getenv("OLLAMA_API_KEY"),
    reason="OLLAMA_API_KEY not configured; live test needs real credits.",
)

# Module-wide marker: every test here spends REAL cloud credits and waits
# on wall-clock retries. ``pytest.ini`` deselects "live" by default, so a
# plain run is always free; run them with ``pytest -m live``.


def _profile(subject="Space", difficulty="easy", language="English"):
    """
    Build a fake user profile for quiz generation.

    :param subject: The subject fixture.
    :param difficulty: The difficulty fixture.
    :param language: The language fixture.
    :return: Helper value for tests.
    :rtype: object
    """

    return SimpleNamespace(
        favorite_subject=subject,
        difficulty_level=difficulty,
        language=language,
        grade_occupation="Grade 5",
    )


def _generate_with_retry(user, count, attempts=4):
    """
    Generate quiz questions, retrying transient cloud failures.

    Free-tier cloud capacity is flaky (rate limits); retry transients.
    A wrong model name fails every attempt, so genuine failures still fail.

    :param user: The fake user profile to personalise for.
    :param count: The number of questions to generate.
    :param attempts: Maximum generation attempts.
    :return: A list of validated question dicts.
    :rtype: list
    """

    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return app_module.generate_questions(user, count)
        except app_module.QuizGenerationError as exc:
            last = exc
            time.sleep(10 * (attempt + 1))

    if last is not None:
        raise last
    raise RuntimeError("Quiz generation failed with no captured error")


def _assert_valid_quiz(questions, count=1):
    """
    Assert a quiz list has valid shape.

    :param questions: The questions fixture.
    :param count: The count fixture.
    """

    assert len(questions) == count
    for q in questions:
        assert isinstance(q["question"], str) and q["question"].strip()
        assert (
            isinstance(q["options"], list)
            and len(q["options"]) == 4
            and all(isinstance(o, str) and o.strip() for o in q["options"])
        )
        assert q["answer_index"] in (0, 1, 2, 3)
        assert len(set(q["options"])) == 4  # no duplicate options


@requires_key
class TestLiveModels:
    @pytest.mark.parametrize("model", LIVE_MODELS)
    def test_model_generates_valid_quiz(self, model, monkeypatch):
        """
        Verify model generates valid quiz.

        :param model: The model fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        monkeypatch.setattr(app_module, "OLLAMA_MODEL", model)
        questions = _generate_with_retry(_profile(), 1)
        _assert_valid_quiz(questions, 1)

    def test_personalised_subject_and_language(self, monkeypatch):
        """
        Verify personalised subject and language.

        :param monkeypatch: The monkeypatch fixture.
        """

        monkeypatch.setattr(app_module, "OLLAMA_MODEL", "gpt-oss:20b")
        questions = _generate_with_retry(
            _profile(subject="Oceans", difficulty="easy", language="Hindi"), 1
        )
        _assert_valid_quiz(questions, 1)


@requires_key
class TestLiveRouteEndToEnd:
    def test_generate_state_answer_finish(self, client, existing_user):
        """
        Verify generate state answer finish.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """

        client.post(
            "/login",
            data={
                "email": existing_user["email"],
                "password": existing_user["password"],
            },
        )

        gen = None
        for attempt in range(4):
            gen = client.post("/api/quiz/generate", json={"num_questions": 1})
            if gen.status_code == 200:
                break
            time.sleep(10 * (attempt + 1))
        assert gen is not None
        assert gen.status_code == 200
        assert gen.get_json()["total"] == 1

        state = client.get("/api/quiz/state").get_json()
        assert state["question"].strip()
        assert len(state["options"]) == 4
        assert "answer_index" not in state

        answered = client.post(
            "/api/quiz/answer",
            json={"option_index": 0, "question_index": 0},
        ).get_json()

        assert answered["finished"] is True
        assert answered["correct"] in (True, False)
        assert answered["points_awarded"] >= 0
        assert answered["quiz_score"] == answered["points_awarded"]

        summary = client.post("/api/quiz/finish").get_json()
        assert summary["quiz_score"] == answered["quiz_score"]
        assert summary["total"] == 1


# ==== merged from test_ollama_live_extra.py ====
requires_key = pytest.mark.skipif(
    not os.getenv("OLLAMA_API_KEY"),
    reason="OLLAMA_API_KEY not configured; live test needs real credits.",
)

# Module-wide marker: real cloud credits + wall-clock retries.
# See tests/test_ollama_live.py for why this exists.


def _profile(subject="Space", difficulty="easy", language="English", grade="Grade 5"):
    return SimpleNamespace(
        favorite_subject=subject,
        difficulty_level=difficulty,
        language=language,
        grade_occupation=grade,
    )


def _retry(user, count, attempts=4):
    last = None
    for attempt in range(attempts):
        try:
            return app_module.generate_questions(user, count)
        except app_module.QuizGenerationError as exc:
            last = exc
            time.sleep(10 * (attempt + 1))
    raise last


def _valid(questions, count):
    assert len(questions) == count
    for q in questions:
        assert isinstance(q["question"], str) and q["question"].strip()
        assert isinstance(q["options"], list) and len(q["options"]) == 4
        assert all(isinstance(o, str) and o.strip() for o in q["options"])
        assert q["answer_index"] in (0, 1, 2, 3)
        assert len(set(q["options"])) == 4


@requires_key
class TestLiveLanguages:
    @pytest.mark.parametrize(
        "lang", ["English", "Spanish", "Hindi", "Mandarin Chinese"]
    )
    def test_language_valid(self, lang, monkeypatch):
        monkeypatch.setattr(app_module, "OLLAMA_MODEL", "gpt-oss:20b")
        prompt = " ".join(
            m["content"]
            for m in app_module.build_quiz_messages(_profile(language=lang), 1)
        )
        assert lang in prompt
        _valid(_retry(_profile(subject="Oceans", language=lang), 1), 1)

    @pytest.mark.parametrize("level", ["easy", "medium", "hard"])
    def test_difficulty_valid(self, level, monkeypatch):
        monkeypatch.setattr(app_module, "OLLAMA_MODEL", "gpt-oss:20b")
        _valid(_retry(_profile(difficulty=level), 1), 1)

    @pytest.mark.parametrize("subject", ["Oceans", "Photosynthesis", "Math"])
    def test_subject_valid(self, subject, monkeypatch):
        monkeypatch.setattr(app_module, "OLLAMA_MODEL", "gpt-oss:20b")
        _valid(_retry(_profile(subject=subject), 1), 1)

    @pytest.mark.parametrize("grade", ["Grade 5", "College", "Job"])
    def test_grade_valid(self, grade, monkeypatch):
        monkeypatch.setattr(app_module, "OLLAMA_MODEL", "gpt-oss:20b")
        _valid(_retry(_profile(grade=grade), 1), 1)

    def test_batch_three(self, monkeypatch):
        monkeypatch.setattr(app_module, "OLLAMA_MODEL", "gpt-oss:20b")
        questions = _retry(_profile(), 3)
        _valid(questions, 3)
        assert len({q["question"] for q in questions}) == 3


@requires_key
class TestLiveHindiModels:
    @pytest.mark.parametrize(
        "model",
        ["gpt-oss:20b", "gemma4:31b", "nemotron-3-nano:30b"],
    )
    def test_hindi_personalised(self, model, monkeypatch):
        monkeypatch.setattr(app_module, "OLLAMA_MODEL", model)
        _valid(
            _retry(_profile(subject="Oceans", language="Hindi"), 1),
            1,
        )


@requires_key
class TestLiveRouteExtra:
    def _login(self, client, existing_user):
        client.post(
            "/login",
            data={
                "email": existing_user["email"],
                "password": existing_user["password"],
            },
        )

    def test_spanish_e2e(self, client, existing_user, monkeypatch):
        import time as _t

        self._login(client, existing_user)
        client.post("/api/settings/save", json={"language": "Spanish"})
        client.post("/api/game/start", json={"num_questions": 1, "lobby_seconds": 10})
        with client.application.app_context():
            from app import GameSession, db

            game = GameSession.query.order_by(GameSession.id.desc()).first()
            game.starts_at = _t.time() - 1
            db.session.commit()
        gen = None
        for _ in range(4):
            gen = client.post("/api/quiz/generate", json={"num_questions": 1})
            if gen.status_code == 200:
                break
            _t.sleep(10)
        assert gen.status_code == 200
        state = client.get("/api/quiz/state").get_json()
        assert state["question"].strip()
        assert len(state["options"]) == 4
        assert "answer_index" not in state

    def test_powerup_offered_live(self, client, existing_user):
        import time as _t

        self._login(client, existing_user)
        client.post("/api/game/start", json={"num_questions": 1, "lobby_seconds": 10})
        with client.application.app_context():
            from app import GameSession, db

            game = GameSession.query.order_by(GameSession.id.desc()).first()
            game.starts_at = _t.time() - 1
            db.session.commit()
        gen = None
        for _ in range(4):
            gen = client.post("/api/quiz/generate", json={"num_questions": 1})
            if gen.status_code == 200:
                break
            _t.sleep(10)
        assert gen.status_code == 200
        state = client.get("/api/quiz/state").get_json()
        assert state["powerup"] in (None, "double", "fifty", "calc", "hint")
