"""Error handling: 500 hygiene, malformed JSON, oversized, unicode, frozen time."""

import json
import time
from types import SimpleNamespace

import pytest

import app as app_module


def _login(client, existing_user):
    client.post(
        "/login",
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


class Test500NoLeak:
    def test_home_500(self, client, app, monkeypatch):
        import routes as routes_module

        app.config["PROPAGATE_EXCEPTIONS"] = False
        # Plain module-attribute patch (the User.query descriptor cannot be
        # resolved outside an app context).
        monkeypatch.setattr(routes_module, "User", None)
        resp = client.get("/leaderboard")
        assert resp.status_code == 500
        assert b"Traceback" not in resp.data
        assert b"boom-secret" not in resp.data
        assert b"SECRET" not in resp.data
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_api_500_json(self, client, app, existing_user, monkeypatch):
        import routes as routes_module

        _login(client, existing_user)

        def _boom():
            raise RuntimeError("boom-secret")

        app.config["PROPAGATE_EXCEPTIONS"] = False
        monkeypatch.setattr(routes_module, "_get_live_game", _boom)
        resp = client.get("/api/game/status")
        assert resp.status_code == 500
        assert b"boom-secret" not in resp.data


class TestMalformedJson:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/settings/save",
            "/api/quiz/generate",
            "/api/game/start",
            "/api/quiz/answer",
            "/api/quiz/powerup",
            "/api/quiz/finish",
        ],
    )
    def test_truncated(self, client, existing_user, path):
        _login(client, existing_user)
        resp = client.post(path, data='{"a":', content_type="application/json")
        assert resp.status_code in (200, 201, 400, 401, 404, 409, 502, 503)

    @pytest.mark.parametrize(
        "path",
        [
            "/api/settings/save",
            "/api/quiz/generate",
            "/api/game/start",
            "/api/quiz/finish",
        ],
    )
    def test_wrong_type(self, client, existing_user, path):
        _login(client, existing_user)
        resp = client.post(path, data="not-json", content_type="text/plain")
        assert resp.status_code in (200, 201, 400, 401, 404, 409, 502, 503)

    @pytest.mark.parametrize(
        "path", ["/api/settings/save", "/api/game/start", "/api/quiz/finish"]
    )
    def test_empty(self, client, existing_user, path):
        _login(client, existing_user)
        resp = client.post(path, data="", content_type="application/json")
        assert resp.status_code in (200, 201, 400, 401, 404, 409)

    @pytest.mark.parametrize(
        "path",
        [
            "/api/settings/save",
            "/api/quiz/generate",
            "/api/game/start",
            "/api/quiz/answer",
            "/api/quiz/powerup",
            "/api/quiz/finish",
        ],
    )
    def test_array_body_never_500(self, client, existing_user, path):
        # Truthy non-dict JSON has no .get: the isinstance guard degrades
        # it to {} (200-with-defaults) instead of AttributeError 500.
        _login(client, existing_user)
        resp = client.post(path, json=[1, 2, 3])
        assert resp.status_code in (200, 201, 400, 401, 404, 409, 502, 503)

    @pytest.mark.parametrize("body", ['"just a string"', "42", "true"])
    def test_scalar_body_never_500(self, client, existing_user, body):
        _login(client, existing_user)
        resp = client.post(
            "/api/settings/save", data=body, content_type="application/json"
        )
        assert resp.status_code in (200, 400)


class TestOversized:
    def test_display_rejected(self, client, app, existing_user):
        from app import User

        _login(client, existing_user)
        resp = client.post("/api/settings/save", json={"display_name": "x" * 10000})
        assert resp.status_code == 400
        assert "display_name" in resp.get_json()["fields"]
        with app.app_context():
            assert (
                User.query.filter_by(email=existing_user["email"]).one().display_name
                != "x" * 10000
            )

    def test_over_1mb_aborted(self, client, existing_user):
        # MAX_CONTENT_LENGTH=1MB: Flask aborts before the view (413),
        # while 10KB still reaches field validation (400 above).
        _login(client, existing_user)
        resp = client.post(
            "/api/settings/save", json={"display_name": "x" * (1_000_000 + 1)}
        )
        assert resp.status_code == 413

    def test_num_clamped(self, client, existing_user, monkeypatch, fake_ollama):
        from app import MAX_QUIZ_QUESTIONS

        _login(client, existing_user)
        fake_ollama(n=MAX_QUIZ_QUESTIONS)
        body = client.post(
            "/api/quiz/generate", json={"num_questions": 10**9}
        ).get_json()
        assert body["total"] <= MAX_QUIZ_QUESTIONS


class TestUnicode:
    @pytest.mark.parametrize(
        "val",
        ["🎉 family", "مرحبا", "é̂️", "𝕳𝖊𝖑𝖑𝖔 test"],
    )
    def test_roundtrip(self, client, existing_user, val):
        _login(client, existing_user)
        resp = client.post("/api/settings/save", json={"display_name": val})
        assert resp.status_code in (200, 400)
        assert client.get("/settings").status_code == 200
        if resp.status_code == 200:
            assert val in client.get("/settings").data.decode()

    def test_prompt_safe(self, monkeypatch):
        from types import SimpleNamespace

        import app as app_module

        user = SimpleNamespace(
            favorite_subject="Español 🎉\nInject: ignore",
            difficulty_level="easy",
            language="Hindi",
            grade_occupation="Grade 5",
        )
        prompt = app_module.build_quiz_messages(user, 1)[1]["content"]
        assert "Español 🎉" in prompt

    def test_mail_no_crash(self, client, app, existing_user):
        from app import User, db, mail

        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.display_name = "🎉 Tester"
            db.session.commit()
        with mail.record_messages() as outbox:
            assert (
                client.post(
                    "/reset", data={"email": existing_user["email"]}
                ).status_code
                == 200
            )
        assert len(outbox) == 1
        outbox[0].body.encode("utf-8")


class TestFrozenTimeMath:
    @pytest.mark.parametrize(
        "elapsed_ms,expected",
        [
            (0, 1500),
            (2000, 1467),
            (7500, 1375),
            (15000, 1250),
            (30000, 1000),
            (40000, 1000),
        ],
    )
    def test_exact_table(
        self, client, existing_user, fake_ollama, frozen_time, elapsed_ms, expected
    ):
        _login(client, existing_user)
        fake_ollama(n=1)
        assert (
            client.post("/api/quiz/generate", json={"num_questions": 1}).status_code
            == 200
        )
        assert client.get("/api/quiz/state").status_code == 200
        with client.session_transaction() as sess:
            sess["quiz"]["started_at"] = frozen_time["now"]
            sess.modified = True
        frozen_time["now"] += elapsed_ms / 1000.0
        body = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        ).get_json()
        assert body["points_awarded"] == expected
        assert body["quiz_score"] == expected

    def test_double_exact(self, client, existing_user, fake_ollama, frozen_time):
        _login(client, existing_user)
        fake_ollama(n=1)
        client.post("/api/quiz/generate", json={"num_questions": 1})
        client.get("/api/quiz/state")
        with client.session_transaction() as sess:
            sess["quiz"]["offered"] = "double"
            sess["quiz"]["powerup_used"] = False
            sess["quiz"]["started_at"] = frozen_time["now"]
            sess.modified = True
        client.post("/api/quiz/powerup", json={"kind": "double"})
        body = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        ).get_json()
        assert body["points_awarded"] == 3000

    def test_lobby_math_frozen(self, client, existing_user, frozen_time):
        _login(client, existing_user)
        game = client.post(
            "/api/game/start", json={"num_questions": 6, "lobby_seconds": 60}
        ).get_json()["game"]
        assert game["starts_at"] == frozen_time["now"] + 60
        assert game["expires_at"] - game["starts_at"] == 6 * 30 + 120
        assert game["starts_in_ms"] == 60 * 1000


# ==== merged from test_session_tamper.py ====
CORRUPTED = {"error": "Quiz state corrupted. Start a new game."}


def _login(client, existing_user):
    """Log a user in through the real login form."""
    client.post(
        "/login",
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


def _quiz_json(n=2):
    """Return a canned quiz payload."""
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


def _start(client, monkeypatch, n=2):
    """Generate a quiz with a stubbed model."""
    fake = SimpleNamespace(
        chat=lambda **kwargs: SimpleNamespace(
            message=SimpleNamespace(content=_quiz_json(n))
        )
    )
    monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
    monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
    resp = client.post("/api/quiz/generate", json={"num_questions": n})
    assert resp.status_code == 200, resp.data.decode()[:300]
    return resp.get_json()


def _tamper(client, mutate):
    """Apply ``mutate`` to the stored quiz and mark the session dirty."""
    with client.session_transaction() as sess:
        mutate(sess["quiz"])
        sess.modified = True


def _ago(client, seconds):
    """Pretend the current question started ``seconds`` ago."""
    with client.session_transaction() as sess:
        sess["quiz"]["started_at"] = time.time() - seconds
        sess.modified = True


class TestAnswerTamper:
    """``POST /api/quiz/answer`` must reject a corrupted session."""

    def test_tampered_score_409(self, client, existing_user, monkeypatch):
        """A non-numeric score is corruption, not zero points."""
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)
        _tamper(client, lambda quiz: quiz.update({"score": "bad"}))
        resp = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        )
        assert resp.status_code == 409
        assert resp.get_json() == CORRUPTED

    def test_boolean_score_409(self, client, existing_user, monkeypatch):
        """``True`` is an int subclass but not a score."""
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)
        _tamper(client, lambda quiz: quiz.update({"score": True}))
        resp = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        )
        assert resp.status_code == 409
        assert resp.get_json() == CORRUPTED

    def test_negative_limit_ms_409(self, client, existing_user, monkeypatch):
        """A non-positive time limit is corruption.

        Note: zero is *not* enough to trigger this — the route replaces a
        falsy limit with the default, so only a negative value reaches
        the guard.
        """
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)
        _tamper(client, lambda quiz: quiz.update({"limit_ms": -1}))
        resp = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        )
        assert resp.status_code == 409
        assert resp.get_json() == CORRUPTED

    def test_missing_answer_index_409(self, client, existing_user, monkeypatch):
        """A question without the right answer is corruption."""
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _ago(client, 1)

        def _drop(quiz):
            quiz["questions"][0].pop("answer_index", None)

        _tamper(client, _drop)
        resp = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        )
        assert resp.status_code == 409
        assert resp.get_json() == CORRUPTED


class TestPowerupTamper:
    """``POST /api/quiz/powerup`` must reject a corrupted session."""

    def _arm(self, client, monkeypatch, kind="double"):
        """Start a quiz with a specific power-up on offer."""
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        with client.session_transaction() as sess:
            sess["quiz"]["offered"] = kind
            sess["quiz"]["powerup_used"] = False
            if sess["quiz"].get("started_at") is None:
                sess["quiz"]["started_at"] = time.time()
            sess.modified = True

    def test_non_dict_powerup_counts_409(self, client, existing_user, monkeypatch):
        """``powerup_counts`` must be a mapping."""
        _login(client, existing_user)
        self._arm(client, monkeypatch)
        _tamper(client, lambda quiz: quiz.update({"powerup_counts": [1, 2]}))
        resp = client.post("/api/quiz/powerup", json={"kind": "double"})
        assert resp.status_code == 409
        assert resp.get_json() == CORRUPTED

    def test_non_numeric_count_409(self, client, existing_user, monkeypatch):
        """A count that is not a number is corruption."""
        _login(client, existing_user)
        self._arm(client, monkeypatch)
        _tamper(client, lambda quiz: quiz.update({"powerup_counts": {"double": "x"}}))
        resp = client.post("/api/quiz/powerup", json={"kind": "double"})
        assert resp.status_code == 409
        assert resp.get_json() == CORRUPTED

    def test_unknown_count_kind_is_caught_at_finish(
        self, client, existing_user, monkeypatch
    ):
        """A count for a power-up that does not exist is corruption.

        The power-up endpoint only counts the kind it just applied, so a
        poisoned entry survives until the quiz is finished. The finish
        must then refuse to bank the game.
        """
        _login(client, existing_user)
        self._arm(client, monkeypatch)
        _tamper(client, lambda quiz: quiz.update({"powerup_counts": {"mega": 1}}))
        assert (
            client.post("/api/quiz/powerup", json={"kind": "double"}).status_code == 200
        )

        _ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        resp = client.post("/api/quiz/finish")
        assert resp.status_code == 409
        assert resp.get_json() == CORRUPTED

    def test_hint_powerup_without_options_409(self, client, existing_user, monkeypatch):
        """The hint power-up reads the options, so a broken question fails."""
        _login(client, existing_user)
        self._arm(client, monkeypatch, kind="hint")

        def _drop(quiz):
            quiz["questions"][0].pop("options", None)

        _tamper(client, _drop)
        resp = client.post("/api/quiz/powerup", json={"kind": "hint"})
        assert resp.status_code == 409
        assert resp.get_json() == CORRUPTED

    def test_fifty_powerup_without_answer_index_409(
        self, client, existing_user, monkeypatch
    ):
        """The 50:50 power-up needs the answer index to pick the wrong ones."""
        _login(client, existing_user)
        self._arm(client, monkeypatch, kind="fifty")

        def _drop(quiz):
            quiz["questions"][0].pop("answer_index", None)

        _tamper(client, _drop)
        resp = client.post("/api/quiz/powerup", json={"kind": "fifty"})
        assert resp.status_code == 409
        assert resp.get_json() == CORRUPTED


class TestFinishTamper:
    """``POST /api/quiz/finish`` must reject a corrupted session."""

    def _finished_quiz(self, client, monkeypatch, n=1):
        """Answer every question so the quiz is finished."""
        _start(client, monkeypatch, n=n)
        client.get("/api/quiz/state")
        for index in range(n):
            _ago(client, 1)
            client.post(
                "/api/quiz/answer",
                json={"option_index": 0, "question_index": index},
            )

    def test_non_numeric_score_409(self, client, existing_user, monkeypatch):
        """A non-numeric total score is corruption."""
        _login(client, existing_user)
        self._finished_quiz(client, monkeypatch, n=1)
        _tamper(client, lambda quiz: quiz.update({"score": "bad"}))
        resp = client.post("/api/quiz/finish")
        assert resp.status_code == 409
        assert resp.get_json() == CORRUPTED

    def test_boolean_score_409(self, client, existing_user, monkeypatch):
        """``True`` is an int subclass but not a score."""
        _login(client, existing_user)
        self._finished_quiz(client, monkeypatch, n=1)
        _tamper(client, lambda quiz: quiz.update({"score": True}))
        resp = client.post("/api/quiz/finish")
        assert resp.status_code == 409
        assert resp.get_json() == CORRUPTED

    def test_empty_questions_409(self, client, existing_user, monkeypatch):
        """An empty question list is corruption."""
        _login(client, existing_user)
        self._finished_quiz(client, monkeypatch, n=1)
        _tamper(client, lambda quiz: quiz.update({"questions": []}))
        resp = client.post("/api/quiz/finish")
        assert resp.status_code == 409
        assert resp.get_json() == CORRUPTED

    def test_questions_not_a_list_409(self, client, existing_user, monkeypatch):
        """Questions must be a list."""
        _login(client, existing_user)
        self._finished_quiz(client, monkeypatch, n=1)
        _tamper(client, lambda quiz: quiz.update({"questions": {"a": 1}}))
        resp = client.post("/api/quiz/finish")
        assert resp.status_code == 409
        assert resp.get_json() == CORRUPTED

    def test_falsy_last_result_404(self, client, existing_user, monkeypatch):
        """An empty cached result falls through to "no active quiz"."""
        _login(client, existing_user)
        with client.session_transaction() as sess:
            sess.pop("quiz", None)
            sess["last_result"] = {}
            sess.modified = True
        resp = client.post("/api/quiz/finish")
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "No active quiz."}

    def test_tampered_finish_does_not_count_the_game(
        self, client, app, existing_user, monkeypatch
    ):
        """A rejected finish must not change the player's statistics."""
        from app import User

        _login(client, existing_user)
        self._finished_quiz(client, monkeypatch, n=1)
        _tamper(client, lambda quiz: quiz.update({"score": "bad"}))
        assert client.post("/api/quiz/finish").status_code == 409
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.total_games_played == 0
            assert user.total_wins == 0


class TestStateTamper:
    """``GET /api/quiz/state`` must reject a corrupted session."""

    def test_question_without_options_409(self, client, existing_user, monkeypatch):
        """A broken question is corruption, not an empty screen."""
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")

        def _drop(quiz):
            quiz["questions"][0] = {"question": "Q?"}

        _tamper(client, _drop)
        resp = client.get("/api/quiz/state")
        assert resp.status_code == 409
        assert resp.get_json() == CORRUPTED

    def test_offer_is_not_re_rolled(self, client, existing_user, monkeypatch):
        """An existing power-up offer must survive a state refresh."""
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        with client.session_transaction() as sess:
            sess["quiz"]["offered"] = "double"
            sess["quiz"]["started_at"] = None
            sess.modified = True
        body = client.get("/api/quiz/state").get_json()
        assert body["powerup"] == "double"

    def test_no_offer_is_offered(self, client, existing_user, monkeypatch):
        """With power-ups enabled but no roll, no offer is made."""
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        monkeypatch.setattr(app_module.random, "random", lambda: 1.0)
        with client.session_transaction() as sess:
            sess["quiz"]["powerups_enabled"] = True
            sess["quiz"]["offered"] = None
            sess["quiz"]["started_at"] = None
            sess.modified = True
        body = client.get("/api/quiz/state").get_json()
        assert body["powerup"] is None


class TestGameplayTamper:
    """``GET /gameplay`` must survive a junk session quiz."""

    def test_non_dict_quiz_is_discarded(self, client, existing_user, monkeypatch):
        """A junk session quiz is dropped instead of crashing the page."""
        _login(client, existing_user)
        with client.session_transaction() as sess:
            sess["quiz"] = [1, 2]
            sess.modified = True
        resp = client.get("/gameplay")
        assert resp.status_code == 200
        assert "var hasQuiz = false" in resp.get_data(as_text=True)
        with client.session_transaction() as sess:
            assert "quiz" not in sess

    def test_empty_questions_quiz_is_discarded(self, client, existing_user):
        """A quiz without questions is dropped too."""
        _login(client, existing_user)
        with client.session_transaction() as sess:
            sess["quiz"] = {"questions": [], "index": 0}
            sess.modified = True
        resp = client.get("/gameplay")
        assert resp.status_code == 200
        assert "var hasQuiz = false" in resp.get_data(as_text=True)


class TestGameStartTamper:
    """``POST /api/game/start`` must coerce odd input safely."""

    @pytest.mark.parametrize("value", [0.0, 0, "", None])
    def test_falsy_num_questions_falls_back(self, client, existing_user, value):
        """A falsy count falls back to the default of 10."""
        _login(client, existing_user)
        resp = client.post("/api/game/start", json={"num_questions": value})
        assert resp.status_code == 201
        assert resp.get_json()["game"]["num_questions"] == 10


class TestNonDictJsonBody:
    """A JSON body that is not an object must not crash the route."""

    @pytest.mark.parametrize("body", [[1, 2], "text", 42, True])
    def test_answer_ignores_a_non_object_body(
        self, client, existing_user, monkeypatch, body
    ):
        """The payload is treated as empty, so the answer is rejected."""
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        resp = client.post("/api/quiz/answer", json=body)
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Stale or invalid answer."}

    @pytest.mark.parametrize("body", [[1, 2], "text", 42])
    def test_powerup_ignores_a_non_object_body(
        self, client, existing_user, monkeypatch, body
    ):
        """Without a kind the power-up is simply not available."""
        _login(client, existing_user)
        _start(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        resp = client.post("/api/quiz/powerup", json=body)
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Power-up not available."}

    @pytest.mark.parametrize("body", [[1, 2], "text", 42])
    def test_settings_save_ignores_a_non_object_body(self, client, existing_user, body):
        """The settings payload is empty, so the defaults are kept."""
        _login(client, existing_user)
        resp = client.post("/api/settings/save", json=body)
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
