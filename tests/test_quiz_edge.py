"""Edge-case tests for the quiz API: validation, session shape, scoring."""

import json
import time as _time
from types import SimpleNamespace

import pytest

import app as app_module
from app import MAX_QUIZ_QUESTIONS


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
        self.calls = []

    def chat(self, model="", messages=None, **kwargs):
        self.calls.append({"model": model, "messages": messages, **kwargs})
        return SimpleNamespace(message=SimpleNamespace(content=self.content))


def _login(client, existing_user):
    client.post(
        "/login",
        data={
            "email": existing_user["email"],
            "password": existing_user["password"],
        },
    )


def _start(client, monkeypatch, n=2, **kw):
    fake = _FakeClient(_quiz_json(kw.pop("_total", n)))
    monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
    monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
    body = {"num_questions": n}
    body.update(kw)
    resp = client.post("/api/quiz/generate", json=body)
    assert resp.status_code == 200, resp.data.decode()[:300]
    return resp.get_json()


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


class TestGenerateMatrix:
    def test_bool_fallback(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(10))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        for val in (True, False):
            resp = client.post("/api/quiz/generate", json={"num_questions": val})
            assert resp.status_code == 200
            assert resp.get_json()["total"] == 10

    def test_zero_empty_use_default(self, client, app, existing_user, monkeypatch):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.default_num_questions = 7
            db.session.commit()
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(7))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        assert client.post("/api/quiz/generate", json={"num_questions": 0}).get_json()[
            "total"
        ] == 7
        assert client.post("/api/quiz/generate", json={"num_questions": ""}).get_json()[
            "total"
        ] == 7

    def test_missing_uses_default(self, client, app, existing_user, monkeypatch):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.default_num_questions = 7
            db.session.commit()
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(7))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        assert client.post("/api/quiz/generate", json={}).get_json()["total"] == 7

    def test_string_int(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(5))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        assert client.post("/api/quiz/generate", json={"num_questions": "5"}).get_json()[
            "total"
        ] == 5

    def test_invalid_string_fallback(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(10))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        for val in ("abc", [1]):
            resp = client.post("/api/quiz/generate", json={"num_questions": val})
            assert resp.get_json()["total"] == 10

    def test_negative_clamped(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(2))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        assert client.post("/api/quiz/generate", json={"num_questions": -5}).get_json()[
            "total"
        ] == 1

    def test_float_truncated(self, client, existing_user, monkeypatch):
        # quiz_generate uses int() without float rejection (unlike game_start).
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(5))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        assert client.post("/api/quiz/generate", json={"num_questions": 3.9}).get_json()[
            "total"
        ] == 3

    def test_difficulty_matrix(self, client, app, existing_user, monkeypatch):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.difficulty_level = "hard"
            db.session.commit()
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(1))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        cases = [
            ({"difficulty": "  EASY  "}, "easy"),
            ({"difficulty": "HARD"}, "hard"),
            ({"difficulty": "nope"}, "medium"),
            ({"difficulty": 123}, "medium"),
            ({}, "hard"),
        ]
        for payload, expected in cases:
            body = {"num_questions": 1}
            body.update(payload)
            assert client.post("/api/quiz/generate", json=body).status_code == 200
            with client.session_transaction() as sess:
                assert sess["quiz"]["difficulty"] == expected

    def test_powerups_nonbool_true(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(1))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        for val in ("yes", 0, None, 1, "true"):
            resp = client.post(
                "/api/quiz/generate",
                json={"num_questions": 1, "powerups_enabled": val},
            )
            assert resp.status_code == 200
            with client.session_transaction() as sess:
                assert sess["quiz"]["powerups_enabled"] is True
        client.post(
            "/api/quiz/generate", json={"num_questions": 1, "powerups_enabled": False}
        )
        with client.session_transaction() as sess:
            assert sess["quiz"]["powerups_enabled"] is False

    def test_no_json_defaults(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(10))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        resp = client.post("/api/quiz/generate", data="not-json",
                           content_type="text/plain")
        assert resp.status_code == 200
        assert resp.get_json()["total"] == 10


class TestSessionShape:
    def test_defaults(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=2, difficulty="easy", powerups_enabled=True)
        with client.session_transaction() as sess:
            quiz = sess["quiz"]
            assert quiz["index"] == 0
            assert quiz["score"] == 0
            assert quiz["started_at"] is None
            assert quiz["limit_ms"] == 30000
            assert quiz["powerups_enabled"] is True
            assert quiz["difficulty"] == "easy"
            assert quiz["offered"] is None
            assert quiz["powerup_used"] is False
            assert quiz["powerup_counts"] == {}
            assert quiz["double_armed"] is False
            assert quiz["finished"] is False
            assert quiz["game_id"] is None
            assert len(quiz["questions"]) == 2

    def test_clears_last_result(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        client.post("/api/quiz/finish")
        with client.session_transaction() as sess:
            assert sess.get("last_result") is not None
        _start(client, monkeypatch, n=1)
        with client.session_transaction() as sess:
            assert sess.get("last_result") is None

    def test_public_strips(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        body = _start(client, monkeypatch, n=2)
        assert body["total"] == 2
        for question in body["questions"]:
            assert set(question) == {"question", "options"}
            assert len(question["options"]) == 4


class TestStateEdge:
    def test_finished_409(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        resp = client.get("/api/quiz/state")
        assert resp.status_code == 409
        assert resp.get_json()["error"] == "Quiz already finished."

    @pytest.mark.parametrize("bad", [True, "0", -1, 99, None])
    def test_corrupt_index(self, client, existing_user, monkeypatch, bad):
        _login(client, existing_user)
        _start(client, monkeypatch, n=2)
        client.get("/api/quiz/state")
        with client.session_transaction() as sess:
            sess["quiz"]["index"] = bad
            sess.modified = True
        resp = client.get("/api/quiz/state")
        assert resp.status_code == 409
        assert "corrupted" in resp.get_json()["error"]

    def test_corrupt_keys(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        with client.session_transaction() as sess:
            sess["quiz"]["questions"][0] = {"question": "Q?"}
            sess.modified = True
        resp = client.get("/api/quiz/state")
        assert resp.status_code == 409

    def test_empty_is_404(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        with client.session_transaction() as sess:
            sess["quiz"]["questions"] = []
            sess.modified = True
        resp = client.get("/api/quiz/state")
        assert resp.status_code == 404

    def test_second_call_stable(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        monkeypatch.setattr(app_module.random, "random", lambda: 0.0)
        monkeypatch.setattr(app_module.random, "choice", lambda seq: "fifty")
        first = client.get("/api/quiz/state").get_json()
        with client.session_transaction() as sess:
            started = sess["quiz"]["started_at"]
        second = client.get("/api/quiz/state").get_json()
        assert second["powerup"] == first["powerup"] == "fifty"
        with client.session_transaction() as sess:
            assert sess["quiz"]["started_at"] == started


class TestAnswerEdge:
    def test_no_timer_409(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        resp = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        )
        assert resp.status_code == 409
        assert resp.get_json()["error"] == "Timer not started. Reload the question."

    @pytest.mark.parametrize(
        "payload",
        [{}, {"option_index": 0}, {"question_index": 0}],
    )
    def test_missing_json_409(self, client, existing_user, monkeypatch, payload):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)
        resp = client.post("/api/quiz/answer", json=payload)
        assert resp.status_code == 409

    @pytest.mark.parametrize("bad", [True, "0", None, 1.0, 5, -1])
    def test_qindex_types_409(self, client, existing_user, monkeypatch, bad):
        _login(client, existing_user)
        _start(client, monkeypatch, n=2)
        client.get("/api/quiz/state")
        _ago(client, 1)
        resp = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": bad}
        )
        assert resp.status_code == 409

    @pytest.mark.parametrize("bad", [2.0, "1", None])
    def test_option_types_409(self, client, existing_user, monkeypatch, bad):
        _login(client, existing_user)
        _start(client, monkeypatch, n=2)
        client.get("/api/quiz/state")
        _ago(client, 1)
        resp = client.post(
            "/api/quiz/answer", json={"option_index": bad, "question_index": 0}
        )
        assert resp.status_code == 409

    def test_corrupt_index_409(self, client, existing_user, monkeypatch):
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
        assert "corrupted" in resp.get_json()["error"]

    def test_advance_flags(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=2)
        client.get("/api/quiz/state")
        _ago(client, 1)
        first = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        ).get_json()
        assert first["answered_index"] == 0
        assert first["total"] == 2
        assert first["finished"] is False
        client.get("/api/quiz/state")
        _ago(client, 1)
        second = client.post(
            "/api/quiz/answer", json={"option_index": 1, "question_index": 1}
        ).get_json()
        assert second["finished"] is True
        assert client.post(
            "/api/quiz/answer", json={"option_index": 1, "question_index": 1}
        ).status_code == 409

    def test_exact_math(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 0)
        body = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        ).get_json()
        assert body["points_awarded"] == 1500
        assert body["quiz_score"] == 1500

    def test_double_correct_vs_wrong(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _force(client, "double")
        assert client.post("/api/quiz/powerup", json={"kind": "double"}).status_code == 200
        _ago(client, 0)
        body = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        ).get_json()
        assert body["points_awarded"] == 3000
        # Wrong with double still scores zero.
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _force(client, "double")
        client.post("/api/quiz/powerup", json={"kind": "double"})
        _ago(client, 0)
        body = client.post(
            "/api/quiz/answer", json={"option_index": 3, "question_index": 0}
        ).get_json()
        assert body["correct"] is False
        assert body["points_awarded"] == 0

    def test_resets_after_answer(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _force(client, "calc")
        client.post("/api/quiz/powerup", json={"kind": "calc"})
        _ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        with client.session_transaction() as sess:
            assert sess["quiz"]["limit_ms"] == 30000
            assert sess["quiz"]["double_armed"] is False
            assert sess["quiz"]["offered"] is None
            assert sess["quiz"]["started_at"] is None

    @pytest.mark.parametrize("field,value", [("started_at", "bad"),
                                             ("limit_ms", "bad")])
    def test_tampered_timer_409(self, client, existing_user, monkeypatch,
                                field, value):
        # Fixed: session-tampered timers previously raised unhandled
        # TypeError/500; now a clean 409 corrupted.
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)
        with client.session_transaction() as sess:
            sess["quiz"][field] = value
            sess.modified = True
        resp = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        )
        assert resp.status_code == 409
        assert resp.get_json() == {
            "error": "Quiz state corrupted. Start a new game."}


class TestPowerupEdge:
    def test_finished_409(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        resp = client.post("/api/quiz/powerup", json={"kind": "double"})
        assert resp.status_code == 409

    def test_no_timer_409(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        with client.session_transaction() as sess:
            sess["quiz"]["offered"] = "double"
            sess["quiz"]["started_at"] = None
            sess.modified = True
        resp = client.post("/api/quiz/powerup", json={"kind": "double"})
        assert resp.status_code == 409

    @pytest.mark.parametrize("kind", ["mega", None, "", 123])
    def test_unknown_kind_409(self, client, existing_user, monkeypatch, kind):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _force(client, "fifty")
        resp = client.post("/api/quiz/powerup", json={"kind": kind})
        assert resp.status_code == 409

    def test_calc_math(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _force(client, "calc")
        body = client.post("/api/quiz/powerup", json={"kind": "calc"}).get_json()
        assert body == {"kind": "calc", "limit_ms": 45000}
        with client.session_transaction() as sess:
            assert sess["quiz"]["powerup_counts"] == {"calc": 1}

    def test_fifty_q1(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=2)
        client.get("/api/quiz/state")
        _ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        client.get("/api/quiz/state")
        _force(client, "fifty")
        body = client.post("/api/quiz/powerup", json={"kind": "fifty"}).get_json()
        assert len(body["removed"]) == 2
        assert 1 not in body["removed"]

    def test_counts_accumulate(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=2)
        client.get("/api/quiz/state")
        _force(client, "double")
        client.post("/api/quiz/powerup", json={"kind": "double"})
        _ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        client.get("/api/quiz/state")
        _force(client, "hint")
        body = client.post("/api/quiz/powerup", json={"kind": "hint"}).get_json()
        assert body["hint"] == "Q"
        with client.session_transaction() as sess:
            assert sess["quiz"]["powerup_counts"] == {"double": 1, "hint": 1}

    @pytest.mark.parametrize("kind", ["fifty", "hint"])
    def test_tampered_answer_index_409(self, client, existing_user, monkeypatch,
                                       kind):
        # Fixed: tampered questions lacking answer_index previously raised
        # unhandled KeyError/500 in the fifty/hint branches.
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _force(client, kind)
        with client.session_transaction() as sess:
            sess["quiz"]["questions"][0].pop("answer_index", None)
            sess.modified = True
        resp = client.post("/api/quiz/powerup", json={"kind": kind})
        assert resp.status_code == 409
        assert resp.get_json() == {
            "error": "Quiz state corrupted. Start a new game."}

    def test_tampered_calc_limit_409(self, client, existing_user, monkeypatch):
        # Fixed: tampered limit_ms="bad" previously raised TypeError/500
        # in the calc branch.
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _force(client, "calc")
        with client.session_transaction() as sess:
            sess["quiz"]["limit_ms"] = "bad"
            sess.modified = True
        resp = client.post("/api/quiz/powerup", json={"kind": "calc"})
        assert resp.status_code == 409
        assert resp.get_json() == {
            "error": "Quiz state corrupted. Start a new game."}


class TestFinishEdge:
    def _inject_finished(self, client, score, counts=None):
        with client.session_transaction() as sess:
            sess["quiz"] = {
                "questions": [
                    {
                        "question": "Q?",
                        "options": ["A", "B", "C", "D"],
                        "answer_index": 0,
                    }
                ],
                "index": 1,
                "score": score,
                "started_at": None,
                "limit_ms": 30000,
                "powerups_enabled": True,
                "difficulty": "medium",
                "offered": None,
                "powerup_used": False,
                "powerup_counts": counts or {},
                "double_armed": False,
                "finished": True,
                "game_id": None,
            }
            sess.modified = True

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
        self._inject_finished(client, 2000)
        body = client.post("/api/quiz/finish").get_json()
        assert body["quiz_score"] == 2000
        assert body["is_win"] is False

    def test_win_by_one(self, client, app, existing_user):
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
        self._inject_finished(client, 2001)
        body = client.post("/api/quiz/finish").get_json()
        assert body["is_win"] is True

    def test_best_not_lowered(self, client, app, existing_user):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.best_score = 5000
            user.score = 0
            db.session.commit()
        _login(client, existing_user)
        self._inject_finished(client, 2000)
        body = client.post("/api/quiz/finish").get_json()
        assert body["quiz_score"] == 2000
        assert body["best_score"] == 5000
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.score == 2000
            assert user.best_score == 5000

    def test_idempotent_cached(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _force(client, "double")
        client.post("/api/quiz/powerup", json={"kind": "double"})
        _ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        first = client.post("/api/quiz/finish").get_json()
        second = client.post("/api/quiz/finish").get_json()
        assert first == second
        assert client.get("/api/quiz/state").status_code == 404
        assert client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        ).status_code == 404

    def test_no_quiz_cached(self, client, existing_user):
        _login(client, existing_user)
        cached = {
            "quiz_score": 123,
            "total": 1,
            "best_score": 123,
            "is_win": True,
            "powerups_used": 0,
        }
        with client.session_transaction() as sess:
            sess.pop("quiz", None)
            sess["last_result"] = cached
            sess.modified = True
        assert client.post("/api/quiz/finish").get_json() == cached

    def test_zero_powerups(self, client, app, existing_user):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.most_used_powerup = None
            user.total_powerups_used = 0
            db.session.commit()
        _login(client, existing_user)
        self._inject_finished(client, 1000, {})
        body = client.post("/api/quiz/finish").get_json()
        assert body["powerups_used"] == 0
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.total_powerups_used == 0
            assert user.most_used_powerup is None

    def test_most_used(self, client, app, existing_user):
        _login(client, existing_user)
        self._inject_finished(client, 1000, {"double": 2, "hint": 1})
        body = client.post("/api/quiz/finish").get_json()
        assert body["powerups_used"] == 3
        with app.app_context():
            from app import User

            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.most_used_powerup == "Double Points"

    def test_unknown_powerup_kind_409(self, client, app, existing_user):
        # Fixed: unknown powerup kind in powerup_counts previously raised
        # KeyError/500 via POWERUP_LABELS lookup.
        _login(client, existing_user)
        self._inject_finished(client, 500, {"mega": 1})
        resp = client.post("/api/quiz/finish")
        assert resp.status_code == 409
        assert resp.get_json() == {
            "error": "Quiz state corrupted. Start a new game."}
        with app.app_context():
            from app import User

            assert User.query.filter_by(
                email=existing_user["email"]).one().total_games_played == 0

    def test_missing_questions_409(self, client, existing_user):
        # Fixed: finished quiz missing the questions key previously raised
        # KeyError/500 on len(quiz["questions"]).
        _login(client, existing_user)
        self._inject_finished(client, 500, {})
        with client.session_transaction() as sess:
            sess["quiz"].pop("questions", None)
            sess.modified = True
        resp = client.post("/api/quiz/finish")
        assert resp.status_code == 409
        assert resp.get_json() == {
            "error": "Quiz state corrupted. Start a new game."}

    def test_counts_not_dict_409(self, client, existing_user):
        # Fixed: powerup_counts tampered to a non-dict previously raised
        # AttributeError/500 on .values().
        _login(client, existing_user)
        self._inject_finished(client, 500, {})
        with client.session_transaction() as sess:
            sess["quiz"]["powerup_counts"] = [1, 2]
            sess.modified = True
        resp = client.post("/api/quiz/finish")
        assert resp.status_code == 409
        assert resp.get_json() == {
            "error": "Quiz state corrupted. Start a new game."}

    def test_finish_nondict_404_pops(self, client, existing_user):
        # Fixed: session quiz tampered to a non-dict previously raised
        # AttributeError/500; now a clean 404 + session pop.
        _login(client, existing_user)
        with client.session_transaction() as sess:
            sess["quiz"] = [1, 2]
            sess.modified = True
        resp = client.post("/api/quiz/finish")
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "No active quiz."}
        with client.session_transaction() as sess:
            assert "quiz" not in sess


class TestTruncation:
    def test_oversupply(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(5))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        body = client.post("/api/quiz/generate", json={"num_questions": 2}).get_json()
        assert body["total"] == 2

    def test_huge_to_max(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(25))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        body = client.post("/api/quiz/generate", json={"num_questions": 999}).get_json()
        assert body["total"] == MAX_QUIZ_QUESTIONS
