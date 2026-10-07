"""Tests for Ollama quiz generation (POST /api/quiz/generate). All model calls are mocked."""

import json
from types import SimpleNamespace

import app as app_module
from app import MAX_QUIZ_QUESTIONS


def _quiz_json(n=2):
    """
    Build a fake quiz JSON payload with n questions.

    :param n: The n fixture.
    :return: Helper value for tests.
    :rtype: object
    """

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
    """Stands in for ollama.Client; records how it was called."""

    def __init__(self, content, model_ok=True):
        """
        Initialise the fake Ollama client with canned content.

        :param content: The content fixture.
        :param model_ok: The model_ok fixture.
        """

        self.content = content
        self.calls = []
        self.model_ok = model_ok

    def chat(self, model="", messages=None, **kwargs):
        """
        Record the chat call and return canned quiz content.

        :param model: The model fixture.
        :param messages: The messages fixture.
        :return: Fake chat response with canned content.
        """

        self.calls.append({"model": model, "messages": messages, **kwargs})
        return SimpleNamespace(message=SimpleNamespace(content=self.content))


def _login(client, existing_user):
    """
    Log in the fixture user via POST /login.

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


class TestQuizGenerate:
    def test_requires_login(self, client):
        # JSON API requests get 401 (not a browser redirect) when logged out.
        """
        Verify requires login.

        :param client: The client fixture.
        """

        resp = client.post("/api/quiz/generate", json={})
        assert resp.status_code == 401

    def test_missing_key_returns_503(self, client, existing_user, monkeypatch):
        """
        Verify missing key returns 503.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "")
        resp = client.post("/api/quiz/generate", json={})
        assert resp.status_code == 503
        assert "OLLAMA_API_KEY" in resp.get_json()["error"]

    def test_success_returns_questions_without_answers(
        self, client, existing_user, monkeypatch
    ):
        """
        Verify success returns questions without answers.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(2))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        resp = client.post("/api/quiz/generate", json={"num_questions": 2})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["total"] == 2
        assert len(body["questions"]) == 2
        first = body["questions"][0]
        assert first["question"] == "Question 0?"
        assert first["options"] == ["Q0 A", "Q0 B", "Q0 C", "Q0 D"]
        # Answers must stay server-side, never leak to the client.
        assert "answer_index" not in first

    def test_prompt_uses_profile_and_default_model(
        self, client, app, existing_user, monkeypatch
    ):
        """
        Verify prompt uses profile and default model.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        with app.app_context():
            from app import User, db

            user = User.query.filter_by(email=existing_user["email"]).one()
            user.favorite_subject = "Space"
            user.difficulty_level = "easy"
            user.language = "Hindi"
            user.grade_occupation = "Grade 5"
            db.session.commit()

        fake = _FakeClient(_quiz_json(1))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        client.post("/api/quiz/generate", json={"num_questions": 1})
        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call["model"] == app_module.OLLAMA_MODEL
        prompt = " ".join(m["content"] for m in call["messages"])
        for token in ("Space", "easy", "Hindi", "Grade 5"):
            assert token in prompt

    def test_num_questions_is_clamped(self, client, existing_user, monkeypatch):
        """
        Verify num questions is clamped.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        fake = _FakeClient(_quiz_json(MAX_QUIZ_QUESTIONS))
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        resp = client.post("/api/quiz/generate", json={"num_questions": 999})
        assert resp.status_code == 200
        assert resp.get_json()["total"] <= MAX_QUIZ_QUESTIONS

    def test_bad_model_output_returns_502(self, client, existing_user, monkeypatch):
        """
        Verify bad model output returns 502.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        fake = _FakeClient("not json at all {{{")
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        resp = client.post("/api/quiz/generate", json={"num_questions": 2})
        assert resp.status_code == 502

    def test_model_failure_returns_502(self, client, existing_user, monkeypatch):
        """
        Verify model failure returns 502.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)

        class _Boom:
            """Failing stand-in for the Ollama client."""

            def chat(self, *args, **kwargs):
                """
                Simulate a cloud outage.

                :param args: Positional args (ignored).
                :param kwargs: Keyword args (ignored).
                :raises RuntimeError: Always raised to simulate downtime.
                """

                raise RuntimeError("cloud is down")

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _Boom())
        resp = client.post("/api/quiz/generate", json={"num_questions": 2})
        assert resp.status_code == 502


class TestParseQuizContent:
    def test_tolerates_fences_and_text_answer(self):
        """Verify fenced JSON with a text answer is tolerated."""

        # Shape really returned by gpt-oss:20b on Ollama cloud.
        content = (
            '```json\n{"questions": [{"question": "Which planet is '
            'known as the Red Planet?", "options": ["Earth", "Mars", '
            '"Jupiter", "Venus"], "answer": "Mars"}]}\n```'
        )

        questions = app_module.parse_quiz_content(content)
        assert len(questions) == 1
        assert questions[0]["answer_index"] == 1

    def test_tolerates_top_level_array(self):
        """Verify a top-level JSON array is tolerated."""

        # Shape really returned by gemma4:31b on Ollama cloud.
        content = (
            '```json\n[{"question": "Which planet is known as the '
            '\'Red Planet\'?", "options": ["Venus", "Mars", '
            '"Jupiter", "Saturn"], "answer": "Mars", "difficulty": '
            '"easy"}]\n```'
        )

        questions = app_module.parse_quiz_content(content)
        assert len(questions) == 1
        assert questions[0]["answer_index"] == 1

    def test_tolerates_bare_single_object(self):
        """Verify a bare single question object is tolerated."""

        # Shape really returned by nemotron-3-ultra on Ollama cloud.
        content = (
            '{"question": "Which planet is known as the Red Planet?", '
            '"options": ["Mars", "Venus", "Jupiter", "Saturn"], '
            '"answer": "Mars"}'
        )

        questions = app_module.parse_quiz_content(content)
        assert len(questions) == 1
        assert questions[0]["answer_index"] == 0

    def test_rejects_unmatched_text_answer(self):
        """Verify rejects unmatched text answer."""

        content = json.dumps(
            {
                "questions": [
                    {
                        "question": "Q?",
                        "options": ["A", "B", "C", "D"],
                        "answer": "Z",
                    }
                ]
            }
        )

        import pytest

        with pytest.raises(app_module.QuizGenerationError):
            app_module.parse_quiz_content(content)


class TestGameplayData:
    def _login(self, client, existing_user):
        """
        Log in the fixture user via POST /login.

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

    def test_hud_shows_real_player_data(self, client, app, existing_user):
        """
        Verify hud shows real player data.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """

        self._login(client, existing_user)
        with app.app_context():
            from app import User, db

            user = User.query.filter_by(email=existing_user["email"]).one()
            user.display_name = "Ava"
            user.score = 5000
            db.session.commit()

        resp = client.get("/gameplay")
        assert resp.status_code == 200
        assert b"Ava: #1" in resp.data
        assert b"Score: 5,000" in resp.data

        # Quiz content loads via the state/answer API, not placeholders.
        for endpoint in (
            b"/api/quiz/state",
            b"/api/quiz/answer",
            b"/api/quiz/powerup",
            b"/api/quiz/finish",
        ):
            assert endpoint in resp.data

    def test_no_static_placeholders_remain(self, client, existing_user):
        """
        Verify no static placeholders remain.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """

        self._login(client, existing_user)
        resp = client.get("/gameplay")
        assert resp.status_code == 200
        for placeholder in (b"Tom: #2", b"Score: 5,000", b"Option 1", b"Option 4"):
            assert placeholder not in resp.data

    def test_rank_reflects_leaderboard(self, client, app, existing_user):
        """
        Verify rank reflects leaderboard.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """

        from flask_security.utils import hash_password

        with app.app_context():
            from app import User, db, user_datastore

            user_datastore.create_user(
                email="champ@example.com", password=hash_password("x" * 12)
            )
            champ = User.query.filter_by(email="champ@example.com").one()
            champ.display_name = "Champ"
            champ.best_score = 9999
            db.session.commit()
        self._login(client, existing_user)
        resp = client.get("/gameplay")
        assert resp.status_code == 200
        # player@example.com -> "player", now ranked second.
        assert b"player: #2" in resp.data


# ---------------------------------------------------------------------------
# Answering + scoring (Steps 21/23). Model calls stay mocked; timing is
# driven by patching the server-side started_at in the session.
# ---------------------------------------------------------------------------

import time as _time


def _start_mocked_quiz(client, monkeypatch, n=2, **generate_kwargs):
    """
    Start a quiz with a mocked Ollama client.

    :param client: The client fixture.
    :param monkeypatch: The monkeypatch fixture.
    :param n: The number of questions to generate.
    :param generate_kwargs: Extra JSON fields merged into the generate body.
    :return: The parsed JSON response from the generate endpoint.
    :rtype: dict
    """

    fake = _FakeClient(_quiz_json(n))
    monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
    monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
    body = {"num_questions": n}
    body.update(generate_kwargs)
    resp = client.post("/api/quiz/generate", json=body)
    assert resp.status_code == 200
    return resp.get_json()


def _set_started_ago(client, seconds):
    """
    Backdate the session quiz timer by seconds.

    :param client: The client fixture.
    :param seconds: The seconds fixture.
    """

    with client.session_transaction() as sess:
        sess["quiz"]["started_at"] = _time.time() - seconds
        # Nested dict edits don't flag the session as modified on their
        # own; force the test client to persist the cookie.
        sess.modified = True


def _force_powerup(client, kind):
    """
    Force-offer a power-up in the session quiz.

    :param client: The client fixture.
    :param kind: The kind fixture.
    """

    with client.session_transaction() as sess:
        sess["quiz"]["offered"] = kind
        sess["quiz"]["powerup_used"] = False
        if sess["quiz"].get("started_at") is None:
            sess["quiz"]["started_at"] = _time.time()
        sess.modified = True


class TestQuizState:
    def test_requires_login(self, client):
        """
        Verify requires login.

        :param client: The client fixture.
        """

        assert client.get("/api/quiz/state").status_code == 302

    def test_no_quiz_returns_404(self, client, existing_user):
        """
        Verify no quiz returns 404.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """

        _login(client, existing_user)
        assert client.get("/api/quiz/state").status_code == 404

    def test_returns_current_question_without_answers(
        self, client, existing_user, monkeypatch
    ):
        """
        Verify returns current question without answers.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=2)
        body = client.get("/api/quiz/state").get_json()
        assert body["question"] == "Question 0?"
        assert body["options"] == ["Q0 A", "Q0 B", "Q0 C", "Q0 D"]
        assert body["index"] == 0
        assert body["total"] == 2
        assert body["quiz_score"] == 0
        assert "answer_index" not in body

    def test_powerup_offer_is_random_but_passes_through(
        self, client, existing_user, monkeypatch
    ):
        """
        Verify powerup offer is random but passes through.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=1)
        monkeypatch.setattr(app_module.random, "random", lambda: 0.0)
        monkeypatch.setattr(app_module.random, "choice", lambda seq: "fifty")
        body = client.get("/api/quiz/state").get_json()
        assert body["powerup"] == "fifty"

    def test_powerups_disabled_offers_nothing(self, client, existing_user, monkeypatch):
        """
        Verify powerups disabled offers nothing.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=1, powerups_enabled=False)
        body = client.get("/api/quiz/state").get_json()
        assert body["powerup"] is None


class TestQuizAnswer:
    def test_requires_login(self, client):
        """
        Verify requires login.

        :param client: The client fixture.
        """

        assert client.post("/api/quiz/answer", json={}).status_code == 401

    def test_no_quiz_returns_404(self, client, existing_user):
        """
        Verify no quiz returns 404.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        resp = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        )
        assert resp.status_code == 404

    def test_correct_fast_answer_earns_bonus(self, client, existing_user, monkeypatch):
        """
        Verify correct fast answer earns bonus.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=2)
        client.get("/api/quiz/state")
        _set_started_ago(client, 2)
        # Q0 correct answer is index 0.
        body = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        ).get_json()
        assert body["correct"] is True
        assert body["correct_index"] == 0
        assert 1400 <= body["points_awarded"] <= 1500
        assert body["quiz_score"] == body["points_awarded"]
        assert body["finished"] is False

    def test_slow_answer_clamps_to_base_points(
        self, client, existing_user, monkeypatch
    ):
        """
        Verify slow answer clamps to base points.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _set_started_ago(client, 120)
        body = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        ).get_json()
        assert body["correct"] is True
        assert body["points_awarded"] == 1000

    def test_wrong_answer_scores_zero(self, client, existing_user, monkeypatch):
        """
        Verify wrong answer scores zero.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _set_started_ago(client, 1)
        body = client.post(
            "/api/quiz/answer", json={"option_index": 3, "question_index": 0}
        ).get_json()
        assert body["correct"] is False
        assert body["correct_index"] == 0
        assert body["points_awarded"] == 0
        assert body["quiz_score"] == 0
        assert body["finished"] is True

    def test_fast_beats_slow_in_one_quiz(self, client, existing_user, monkeypatch):
        """
        Verify fast beats slow in one quiz.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=2)
        client.get("/api/quiz/state")
        _set_started_ago(client, 2)
        fast = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        ).get_json()["points_awarded"]
        _set_started_ago(client, 25)
        # Q1 correct answer is index 1.
        slow = client.post(
            "/api/quiz/answer", json={"option_index": 1, "question_index": 1}
        ).get_json()["points_awarded"]
        assert fast > slow > 1000

    def test_stale_or_invalid_answers_rejected(
        self, client, existing_user, monkeypatch
    ):
        """
        Verify stale or invalid answers rejected.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=2)
        client.get("/api/quiz/state")
        _set_started_ago(client, 1)
        good = {"option_index": 0, "question_index": 0}
        assert client.post("/api/quiz/answer", json=good).status_code == 200
        # Same question again: already advanced.
        assert client.post("/api/quiz/answer", json=good).status_code == 409
        # Non-existent question index.
        assert (
            client.post(
                "/api/quiz/answer", json={"option_index": 1, "question_index": 5}
            ).status_code
            == 409
        )
        # Bad option values.
        for bad_option in (4, -1, "0", True, None):
            resp = client.post(
                "/api/quiz/answer",
                json={"option_index": bad_option, "question_index": 1},
            )
            assert resp.status_code == 409

    def test_answering_finished_quiz_rejected(self, client, existing_user, monkeypatch):
        """
        Verify answering finished quiz rejected.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _set_started_ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        resp = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        )
        assert resp.status_code == 409


class TestQuizPowerup:
    def test_requires_login(self, client):
        """
        Verify requires login.

        :param client: The client fixture.
        """

        assert client.post("/api/quiz/powerup", json={}).status_code == 401

    def test_unoffered_or_disabled_rejected(self, client, existing_user, monkeypatch):
        """
        Verify unoffered or disabled rejected.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=1, powerups_enabled=False)
        client.get("/api/quiz/state")
        _force_powerup(client, "double")
        resp = client.post("/api/quiz/powerup", json={"kind": "double"})
        assert resp.status_code == 409

        _start_mocked_quiz(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        # Nothing offered -> any kind rejected; wrong kind rejected.
        assert (
            client.post("/api/quiz/powerup", json={"kind": "double"}).status_code == 409
        )
        _force_powerup(client, "fifty")
        assert (
            client.post("/api/quiz/powerup", json={"kind": "hint"}).status_code == 409
        )

    def test_double_doubles_fast_points(self, client, existing_user, monkeypatch):
        """
        Verify double doubles fast points.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _force_powerup(client, "double")
        assert (
            client.post("/api/quiz/powerup", json={"kind": "double"}).status_code == 200
        )
        # Reuse on the same question is rejected.
        assert (
            client.post("/api/quiz/powerup", json={"kind": "double"}).status_code == 409
        )
        _set_started_ago(client, 2)
        body = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        ).get_json()
        assert 2800 <= body["points_awarded"] <= 3000

    def test_fifty_removes_two_wrong_options(self, client, existing_user, monkeypatch):
        """
        Verify fifty removes two wrong options.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _force_powerup(client, "fifty")
        body = client.post("/api/quiz/powerup", json={"kind": "fifty"}).get_json()
        assert sorted(body["removed"]) == body["removed"]
        assert len(body["removed"]) == 2
        assert 0 not in body["removed"]  # 0 is correct for Q0

    def test_calc_extends_time_cap(self, client, existing_user, monkeypatch):
        """
        Verify calc extends time cap.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _force_powerup(client, "calc")
        body = client.post("/api/quiz/powerup", json={"kind": "calc"}).get_json()
        assert body["limit_ms"] == 45000
        _set_started_ago(client, 40)
        body = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        ).get_json()
        # 40s of 45s still earns a small bonus instead of base points.
        assert body["points_awarded"] > 1000

    def test_hint_reveals_first_letter(self, client, existing_user, monkeypatch):
        """
        Verify hint reveals first letter.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _force_powerup(client, "hint")
        body = client.post("/api/quiz/powerup", json={"kind": "hint"}).get_json()
        assert body["hint"] == "Q"  # correct option is "Q0 A"


class TestQuizFinish:
    def _finish_quiz(self, client, monkeypatch, n=2):
        """
        Play through and finish a mocked quiz via the API.

        :param client: The client fixture.
        :param monkeypatch: The monkeypatch fixture.
        :param n: The n fixture.
        """

        _start_mocked_quiz(client, monkeypatch, n=n)
        client.get("/api/quiz/state")
        for i in range(n):
            _set_started_ago(client, 1)
            client.post(
                "/api/quiz/answer",
                json={"option_index": i % 4, "question_index": i},
            )

    def test_requires_login(self, client):
        """
        Verify requires login.

        :param client: The client fixture.
        """

        assert client.post("/api/quiz/finish", json={}).status_code == 401

    def test_no_quiz_returns_404(self, client, existing_user):
        """
        Verify no quiz returns 404.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """

        _login(client, existing_user)
        assert client.post("/api/quiz/finish").status_code == 404

    def test_unfinished_quiz_rejected(self, client, existing_user, monkeypatch):
        """
        Verify unfinished quiz rejected.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=2)
        assert client.post("/api/quiz/finish").status_code == 409

    def test_finish_persists_stats_and_win(
        self, client, app, existing_user, monkeypatch
    ):
        """
        Verify finish persists stats and win.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        from flask_security.utils import hash_password

        with app.app_context():
            from app import User, db, user_datastore

            user_datastore.create_user(
                email="rival@example.com", password=hash_password("x" * 12)
            )
            rival = User.query.filter_by(email="rival@example.com").one()
            rival.best_score = 1000
            db.session.commit()
        _login(client, existing_user)
        self._finish_quiz(client, monkeypatch, n=2)
        body = client.post("/api/quiz/finish").get_json()
        assert body["total"] == 2
        assert body["quiz_score"] > 1000
        assert body["is_win"] is True
        with app.app_context():
            from app import User

            me = User.query.filter_by(email=existing_user["email"]).one()
            assert me.score == body["quiz_score"]
            assert me.best_score == body["quiz_score"]
            assert me.total_games_played == 1
            assert me.total_wins == 1

    def test_no_win_when_not_top(self, client, app, existing_user, monkeypatch):
        """
        Verify no win when not top.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        from flask_security.utils import hash_password

        with app.app_context():
            from app import User, db, user_datastore

            user_datastore.create_user(
                email="champ@example.com", password=hash_password("x" * 12)
            )
            champ = User.query.filter_by(email="champ@example.com").one()
            champ.best_score = 99999
            db.session.commit()
        _login(client, existing_user)
        self._finish_quiz(client, monkeypatch, n=2)
        body = client.post("/api/quiz/finish").get_json()
        assert body["is_win"] is False
        with app.app_context():
            from app import User

            me = User.query.filter_by(email=existing_user["email"]).one()
            assert me.total_wins == 0
            assert me.total_games_played == 1

    def test_finish_is_idempotent(self, client, app, existing_user, monkeypatch):
        """
        Verify finish is idempotent.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        self._finish_quiz(client, monkeypatch, n=1)
        first = client.post("/api/quiz/finish").get_json()
        second = client.post("/api/quiz/finish").get_json()
        assert first == second
        with app.app_context():
            from app import User

            me = User.query.filter_by(email=existing_user["email"]).one()
            assert me.total_games_played == 1

    def test_powerups_counted_at_finish(self, client, app, existing_user, monkeypatch):
        """
        Verify powerups counted at finish.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """

        _login(client, existing_user)
        _start_mocked_quiz(client, monkeypatch, n=1)
        client.get("/api/quiz/state")
        _force_powerup(client, "double")
        client.post("/api/quiz/powerup", json={"kind": "double"})
        _set_started_ago(client, 1)
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        body = client.post("/api/quiz/finish").get_json()
        assert body["powerups_used"] == 1
        with app.app_context():
            from app import User

            me = User.query.filter_by(email=existing_user["email"]).one()
            assert me.total_powerups_used == 1
            assert me.most_used_powerup == "Double Points"
