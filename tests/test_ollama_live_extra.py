"""Extended live Ollama tests — spend REAL credits.

Skipped automatically when OLLAMA_API_KEY is missing. Never prints the key.
Run explicitly: pytest tests/test_ollama_live_extra.py -q
"""

import os
import time
from types import SimpleNamespace

import pytest

import app as app_module

requires_key = pytest.mark.skipif(
    not os.getenv("OLLAMA_API_KEY"),
    reason="OLLAMA_API_KEY not configured; live test needs real credits.",
)


def _profile(subject="Space", difficulty="easy", language="English",
             grade="Grade 5"):
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
            for m in app_module.build_quiz_messages(
                _profile(language=lang), 1
            )
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
