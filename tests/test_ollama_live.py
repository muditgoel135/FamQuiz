"""
Live Ollama cloud tests for quiz generation — these spend REAL credits.

Only models covered by the family's free usage credits are used:
gemma4:31b, gpt-oss:120b, gpt-oss:20b, nemotron-3-nano:30b,
nemotron-3-super, nemotron-3-ultra.

Run explicitly::

    pytest tests/test_ollama_live.py -q

Skipped automatically when OLLAMA_API_KEY is missing. The key is read
from the environment (loaded from .env by the app) and is never printed.
"""

import os
import time
from types import SimpleNamespace

import pytest

import app as app_module

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
