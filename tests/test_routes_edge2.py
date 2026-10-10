"""Residual routes tests: ports, theme, dots, ties, auth codes, quiz strings."""

import json
import time as _time
from types import SimpleNamespace

import pytest

import app as app_module
from app import GameSession, db


def _login(client, existing_user):
    client.post(
        "/login",
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


def _make_user(app, email, **kw):
    from flask_security.utils import hash_password
    from app import User, user_datastore

    aliases = {"best": "best_score", "wins": "total_wins",
               "played": "total_games_played"}
    with app.app_context():
        user_datastore.create_user(email=email, password=hash_password("x" * 12))
        user = User.query.filter_by(email=email).one()
        for key, value in kw.items():
            setattr(user, aliases.get(key, key), value)
        db.session.commit()
        return user.id


def _quiz_json(n=2):
    return json.dumps(
        {
            "questions": [
                {
                    "question": f"Question {i}?",
                    "options": [f"Q{i} A", f"Q{i} B", f"Q{i} C", f"Q{i} D"],
                    "answer_index": i % 4,
                }
                for i in range(n)
            ]
        }
    )


class _FakeClient:
    def __init__(self, content):
        self.content = content

    def chat(self, model="", messages=None, **kwargs):
        return SimpleNamespace(message=SimpleNamespace(content=self.content))


def _start(client, monkeypatch, n=2, **kw):
    fake = _FakeClient(_quiz_json(kw.pop("_total", n)))
    monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
    monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
    body = {"num_questions": n}
    body.update(kw)
    resp = client.post("/api/quiz/generate", json=body)
    assert resp.status_code == 200, resp.data.decode()[:300]


def _ago(client, seconds):
    with client.session_transaction() as sess:
        sess["quiz"]["started_at"] = _time.time() - seconds
        sess.modified = True


def _force(client, kind):
    with client.session_transaction() as sess:
        sess["quiz"]["offered"] = kind
        sess["quiz"]["powerup_used"] = False
        if sess["quiz"].get("started_at") is None:
            sess["quiz"]["started_at"] = _time.time()
        sess.modified = True


def _inject_finished(client, score, counts=None):
    with client.session_transaction() as sess:
        sess["quiz"] = {
            "questions": [{"question": "Q?", "options": ["A", "B", "C", "D"],
                           "answer_index": 0}],
            "index": 1, "score": score, "started_at": None,
            "limit_ms": 30000, "powerups_enabled": True,
            "difficulty": "medium", "offered": None, "powerup_used": False,
            "powerup_counts": counts or {}, "double_armed": False,
            "finished": True, "game_id": None,
        }
        sess.modified = True


class TestPortBoundaries:
    def test_edges(self, app, monkeypatch):
        from routes import _serving_port

        monkeypatch.setenv("PORT", "5000")
        with app.test_request_context("/", headers={"Host": "example.com:1"}):
            assert _serving_port() == 1
        with app.test_request_context("/", headers={"Host": "example.com:65535"}):
            assert _serving_port() == 65535
        monkeypatch.setenv("PORT", "8765")
        for host in ("example.com:0", "example.com:65536", "example.com:99999",
                     "example.com:", "example.com:notaport"):
            with app.test_request_context("/", headers={"Host": host}):
                assert _serving_port() == 8765

    def test_env_edges(self, app, monkeypatch):
        from routes import _serving_port

        for val, expected in [("1", 1), ("65535", 65535), ("0", 5000),
                              ("70000", 5000), ("abc", 5000), ("", 5000)]:
            monkeypatch.setenv("PORT", val)
            with app.test_request_context("/", base_url="http://example.com/"):
                assert _serving_port() == expected, val

    def test_guide_renders(self, client):
        assert "<code>:1</code>" in client.get(
            "/guide", headers={"Host": "h:1"}).data.decode()
        assert "<code>:65535</code>" in client.get(
            "/guide", headers={"Host": "h:65535"}).data.decode()


class TestInjectThemeResidual:
    def test_case_not_dark(self, client, app, existing_user):
        from app import User

        _login(client, existing_user)
        for val in ("Dark", "DARK", "", " dark "):
            with app.app_context():
                user = User.query.filter_by(email=existing_user["email"]).one()
                user.theme_mode = val
                db.session.commit()
            # Strict =="dark": anything else renders light.
            assert "theme-dark" not in client.get("/").data.decode(), val

    def test_exception_empty(self, app):
        from unittest import mock

        from routes import inject_theme

        class _Boom:
            @property
            def is_authenticated(self):
                raise RuntimeError("boom")

        with app.test_request_context("/"):
            with mock.patch.object(app_module, "current_user", _Boom()):
                assert inject_theme() == {"theme_class": ""}

    def test_dark_all_pages(self, client, app, existing_user):
        from app import User

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.theme_mode = "dark"
            db.session.commit()
        _login(client, existing_user)
        for path in ("/", "/guide", "/leaderboard", "/gameplay", "/settings"):
            assert "theme-dark" in client.get(path).data.decode(), path


class TestStatusDotMatrix:
    def test_homepage(self, client, app):
        _make_user(app, "s1@example.com", best=900, status="Ready to play",
                   display_name="S1")
        _make_user(app, "s2@example.com", best=800, status="Do not disturb",
                   display_name="S2")
        _make_user(app, "s3@example.com", best=700, status="offline",
                   display_name="S3")
        html = client.get("/").data.decode()
        assert "home-dot-ready" in html
        assert "home-dot-busy" in html
        assert "home-dot-offline" in html

    def test_none_unknown_offline(self, client, app):
        _make_user(app, "n1@example.com", best=900, status=None, display_name="N1")
        _make_user(app, "n2@example.com", best=800, status="away", display_name="N2")
        html = client.get("/").data.decode()
        assert "home-dot-offline" in html
        # None falls back to display text "Ready to play" but dot is offline.
        assert "Ready to play" in html

    def test_whitespace_offline(self, client, app):
        _make_user(app, "w1@example.com", best=9999, status="   ",
                   display_name="W1")
        assert "home-dot-offline" in client.get("/").data.decode()


class TestIdAscTieBreak:
    def test_homepage(self, client, app, existing_user):
        from app import User

        with app.app_context():
            me = User.query.filter_by(email=existing_user["email"]).one()
            me.best_score = 0
            me.total_wins = 0
            db.session.commit()
        _make_user(app, "a@example.com", best=100, wins=5, display_name="Aaa")
        _make_user(app, "b@example.com", best=100, wins=5, display_name="Bbb")
        _make_user(app, "c@example.com", best=100, wins=5, display_name="Ccc")
        html = client.get("/").data.decode()
        assert html.index("Aaa") < html.index("Bbb") < html.index("Ccc")
        assert "#1" in html and "#3" in html

    def test_leaderboard_full(self, client, app, existing_user):
        from app import User

        with app.app_context():
            me = User.query.filter_by(email=existing_user["email"]).one()
            me.best_score = 0
            me.total_wins = 0
            me.display_name = "MeD"
            db.session.commit()
        _make_user(app, "a@example.com", best=100, wins=5, display_name="Aaa")
        _make_user(app, "b@example.com", best=100, wins=5, display_name="Bbb")
        html = client.get("/leaderboard").data.decode()
        assert html.index("Aaa") < html.index("Bbb")

    def test_gameplay_rank(self, client, app):
        _make_user(app, "a@example.com", best=100, wins=5, display_name="Aaa")
        _make_user(app, "b@example.com", best=100, wins=5, display_name="Bbb")
        second = app.test_client()
        second.post("/login", data={"email": "b@example.com", "password": "x" * 12})
        assert "Bbb: #2" in second.get("/gameplay").data.decode()


class TestAuthedAllNone:
    def _nullify(self, app, email):
        from app import User

        with app.app_context():
            user = User.query.filter_by(email=email).one()
            user.score = None
            user.best_score = None
            user.total_games_played = None
            user.total_wins = None
            user.total_powerups_used = None
            user.most_used_powerup = None
            user.default_num_questions = None
            user.difficulty_level = None
            user.status = None
            db.session.commit()

    def test_homepage(self, client, app, existing_user):
        self._nullify(app, existing_user["email"])
        _login(client, existing_user)
        html = client.get("/").data.decode()
        # Stats fall back to zeros; data-user-status renders "None" (quirk).
        assert "Best score: 0" in html
        assert "—" in html
        assert 'value="10"' in html
        assert "Choose difficulty level" in html

    def test_gameplay_zero(self, client, app, existing_user):
        self._nullify(app, existing_user["email"])
        _login(client, existing_user)
        html = client.get("/gameplay").data.decode()
        assert "Score: 0" in html


class TestDefaultNumCoercion:
    def test_string_int(self, client, app, existing_user):
        from app import User

        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.default_num_questions = "7"
            db.session.commit()
        assert 'value="7"' in client.get("/").data.decode()
        assert "Question 1/7" in client.get("/gameplay").data.decode()

    def test_invalid_fallback(self, client, app, existing_user):
        from app import User

        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.default_num_questions = None
            db.session.commit()
        assert 'value="10"' in client.get("/").data.decode()

    def test_clamps(self, client, app, existing_user):
        from app import User

        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.default_num_questions = -5
            db.session.commit()
        assert 'value="1"' in client.get("/").data.decode()


class TestGameplayCorners:
    def test_score_format(self, client, app, existing_user):
        from app import User

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.score = 12345
            db.session.commit()
        _login(client, existing_user)
        assert "12,345" in client.get("/gameplay").data.decode()

    def test_empty_questions_divergence(self, client, existing_user):
        _login(client, existing_user)
        with client.session_transaction() as sess:
            sess["quiz"] = {"questions": [], "index": 0}
            sess.modified = True
        # Fixed: gameplay mirrors _get_quiz (no usable questions -> no
        # preload), so hasQuiz is false and the junk is popped; state 404s.
        assert "var hasQuiz = false" in client.get("/gameplay").data.decode()
        with client.session_transaction() as sess:
            assert "quiz" not in sess
        assert client.get("/api/quiz/state").status_code == 404

    def test_finished_cancelled_hole(self, client, app, existing_user, monkeypatch):
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(1))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        client.post("/api/quiz/generate", json={"num_questions": 1})
        client.get("/api/quiz/state")
        _ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        client.post("/api/game/start", json={"lobby_seconds": 60})
        client.post("/api/game/cancel")
        # Intended solo-finish: with no live game the finished quiz is kept
        # (hasQuiz true) so the client can complete it via finishQuiz();
        # state correctly 409s as already finished.
        assert "var hasQuiz = true" in client.get("/gameplay").data.decode()
        assert client.get("/api/quiz/state").status_code == 409


class TestLoggedOutExact:
    def test_cancel_401(self, client):
        assert client.post("/api/game/cancel", json={}).status_code == 401
        assert client.get("/api/game/cancel").status_code == 405

    def test_state_302(self, client):
        resp = client.get("/api/quiz/state", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/login?next=")

    def test_erase_delete_save_quit_401(self, client):
        # JSON POSTs get 401 (browser-form posts without JSON get 302).
        assert client.post("/api/account/erase-data", json={}).status_code == 401
        assert client.delete("/api/account", json={}).status_code == 401
        assert client.post("/api/settings/save", json={}).status_code == 401
        assert client.post("/api/quiz/quit", json={}).status_code == 401

    def test_form_posts_redirect(self, client):
        # Same endpoints without a JSON body behave as browser navigation.
        assert client.post("/api/account/erase-data").status_code == 302

    def test_status_events_302(self, client):
        for path in ("/api/game/status", "/api/game/events?once=1"):
            resp = client.get(path, follow_redirects=False)
            assert resp.status_code == 302, path
            assert resp.headers["Location"].startswith("/login?next="), path


class TestGenerateResidual:
    def test_num_none_default(self, client, app, existing_user, monkeypatch):
        from app import User

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.default_num_questions = 7
            db.session.commit()
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(7))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        assert client.post(
            "/api/quiz/generate", json={"num_questions": None}
        ).get_json()["total"] == 7

    def test_num_string_minus5(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(5))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        assert client.post(
            "/api/quiz/generate", json={"num_questions": "-5"}
        ).get_json()["total"] == 1

    def test_boundaries(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(25))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        assert client.post(
            "/api/quiz/generate", json={"num_questions": 1}
        ).get_json()["total"] == 1
        assert client.post(
            "/api/quiz/generate", json={"num_questions": 20}
        ).get_json()["total"] == 20
        assert client.post(
            "/api/quiz/generate", json={"num_questions": 21}
        ).get_json()["total"] == 20

    def test_difficulty_empty(self, client, app, existing_user, monkeypatch):
        from app import User

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.difficulty_level = "hard"
            db.session.commit()
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(1))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        client.post("/api/quiz/generate", json={"num_questions": 1, "difficulty": None})
        with client.session_transaction() as sess:
            assert sess["quiz"]["difficulty"] == "hard"
        client.post("/api/quiz/generate", json={"num_questions": 1, "difficulty": ""})
        with client.session_transaction() as sess:
            assert sess["quiz"]["difficulty"] == "hard"
        client.post("/api/quiz/generate", json={"num_questions": 1, "difficulty": "   "})
        with client.session_transaction() as sess:
            assert sess["quiz"]["difficulty"] == "medium"

    def test_gate_exact(self, client, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 120})
        body = client.post("/api/quiz/generate", json={"num_questions": 2}).get_json()
        resp = client.post("/api/quiz/generate", json={"num_questions": 2})
        assert resp.status_code == 409
        assert body["error"] == "Game hasn't started yet."
        assert 0 < body["starts_in_ms"] <= 120 * 1000

    def test_cancelled_allows(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        client.post("/api/game/cancel")
        fake = _FakeClient(_quiz_json(1))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        assert client.post(
            "/api/quiz/generate", json={"num_questions": 1}
        ).status_code == 200


class TestStateExact:
    def test_no_quiz(self, client, existing_user):
        _login(client, existing_user)
        resp = client.get("/api/quiz/state")
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "No active quiz. Start a game first."}

    def test_finished(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        resp = client.get("/api/quiz/state")
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Quiz already finished."}

    def test_corrupt(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=2)
        client.get("/api/quiz/state")
        with client.session_transaction() as sess:
            sess["quiz"]["index"] = 99
            sess.modified = True
        resp = client.get("/api/quiz/state")
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Quiz state corrupted. Start a new game."}

    def test_stale_pops(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        resp = client.get("/api/quiz/state")
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Quiz expired. Rejoin the live game."}
        with client.session_transaction() as sess:
            assert "quiz" not in sess


class TestAnswerExact:
    def test_no_quiz(self, client, existing_user):
        _login(client, existing_user)
        resp = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        )
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "No active quiz."}

    def test_finished(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        resp = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        )
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Quiz already finished."}

    def test_stale_pops(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        resp = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        )
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Quiz expired. Rejoin the live game."}
        with client.session_transaction() as sess:
            assert "quiz" not in sess

    def test_no_timer(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        resp = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        )
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Timer not started. Reload the question."}

    @pytest.mark.parametrize("payload", [{}, {"option_index": 0},
                                         {"option_index": True, "question_index": 0},
                                         {"option_index": 0, "question_index": 5}])
    def test_stale_invalid(self, client, existing_user, monkeypatch, payload):
        _login(client, existing_user)
        _start(client, monkeypatch, n=2)
        client.get("/api/quiz/state")
        _ago(client, 1)
        resp = client.post("/api/quiz/answer", json=payload)
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Stale or invalid answer."}

    def test_corrupt(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)
        with client.session_transaction() as sess:
            sess["quiz"]["index"] = 5
            sess.modified = True
        resp = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 5}
        )
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Quiz state corrupted. Start a new game."}

    def test_future_max_bonus(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        with client.session_transaction() as sess:
            sess["quiz"]["started_at"] = _time.time() + 100
            sess.modified = True
        body = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        ).get_json()
        assert body["points_awarded"] == 1500

    def test_limit_none(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        with client.session_transaction() as sess:
            sess["quiz"]["limit_ms"] = None
            sess.modified = True
        _ago(client, 1)
        assert client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        ).status_code == 200


class TestPowerupExact:
    def test_no_quiz(self, client, existing_user):
        _login(client, existing_user)
        resp = client.post("/api/quiz/powerup", json={"kind": "double"})
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "No active quiz."}

    def test_finished(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        resp = client.post("/api/quiz/powerup", json={"kind": "double"})
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Quiz already finished."}

    def test_disabled(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1, powerups_enabled=False)
        client.get("/api/quiz/state")
        _force(client, "double")
        resp = client.post("/api/quiz/powerup", json={"kind": "double"})
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Power-ups are disabled."}

    @pytest.mark.parametrize("kind", ["mega", None, "", 123])
    def test_unavailable(self, client, existing_user, monkeypatch, kind):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _force(client, "fifty")
        resp = client.post("/api/quiz/powerup", json={"kind": kind})
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Power-up not available."}

    def test_corrupt(self, client, existing_user, monkeypatch):
        # Out-of-range index is caught -> 409. Tampered questions missing
        # answer_index are also caught -> 409 (fixed: fifty/hint branches
        # previously raised unhandled KeyError/500).
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        with client.session_transaction() as sess:
            sess["quiz"]["offered"] = "fifty"
            sess["quiz"]["index"] = 5
            sess.modified = True
        resp = client.post("/api/quiz/powerup", json={"kind": "fifty"})
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Quiz state corrupted. Start a new game."}
        # Fifty with tampered question lacking answer_index -> clean 409.
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        with client.session_transaction() as sess:
            sess["quiz"]["questions"][0].pop("answer_index", None)
            sess["quiz"]["offered"] = "fifty"
            sess["quiz"]["powerup_used"] = False
            sess["quiz"]["started_at"] = _time.time()
            sess.modified = True
        resp = client.post("/api/quiz/powerup", json={"kind": "fifty"})
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Quiz state corrupted. Start a new game."}
        # Hint with tampered question lacking answer_index -> clean 409.
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        with client.session_transaction() as sess:
            sess["quiz"]["questions"][0].pop("answer_index", None)
            sess["quiz"]["offered"] = "hint"
            sess["quiz"]["powerup_used"] = False
            sess["quiz"]["started_at"] = _time.time()
            sess.modified = True
        resp = client.post("/api/quiz/powerup", json={"kind": "hint"})
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Quiz state corrupted. Start a new game."}

    def test_stale_pops(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        resp = client.post("/api/quiz/powerup", json={"kind": "double"})
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Quiz expired. Rejoin the live game."}

    def test_double_body(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _force(client, "double")
        assert client.post(
            "/api/quiz/powerup", json={"kind": "double"}
        ).get_json() == {"kind": "double"}


class TestFinishExact:
    def test_no_quiz(self, client, existing_user):
        _login(client, existing_user)
        resp = client.post("/api/quiz/finish")
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "No active quiz."}

    def test_unfinished(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=2)
        resp = client.post("/api/quiz/finish")
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Answer all questions first."}

    def test_stale_pops(self, client, app, existing_user):
        from app import User

        _login(client, existing_user)
        _inject_finished(client, 500)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        resp = client.post("/api/quiz/finish")
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Quiz expired. Rejoin the live game."}
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.total_games_played == 0

    def test_zero_zero(self, client, existing_user):
        _login(client, existing_user)
        _inject_finished(client, 0, {})
        body = client.post("/api/quiz/finish").get_json()
        assert body["quiz_score"] == 0
        assert body["is_win"] is False
        assert body["powerups_used"] == 0

    def test_tie_not_win(self, client, app, existing_user):
        from flask_security.utils import hash_password
        from app import User, db, user_datastore

        with app.app_context():
            user_datastore.create_user(
                email="rival@example.com", password=hash_password("x" * 12)
            )
            rival = User.query.filter_by(email="rival@example.com").one()
            rival.best_score = 2000
            db.session.commit()
        _login(client, existing_user)
        _inject_finished(client, 2000)
        assert client.post("/api/quiz/finish").get_json()["is_win"] is False

    def test_second_game_counts_twice(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        client.post("/api/quiz/finish")
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        client.post("/api/quiz/finish")
        with client.application.app_context():
            from app import User

            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.total_games_played == 2

    def test_tie_counts_deterministic(self, client, app, existing_user):
        _login(client, existing_user)
        _inject_finished(client, 1000, {"double": 1, "hint": 1})
        body = client.post("/api/quiz/finish").get_json()
        assert body["powerups_used"] == 2
        with app.app_context():
            from app import User

            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.most_used_powerup == "Double Points"

    def test_summary_keys(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        body = client.post("/api/quiz/finish").get_json()
        assert set(body) == {"quiz_score", "total", "best_score", "is_win",
                             "powerups_used"}
