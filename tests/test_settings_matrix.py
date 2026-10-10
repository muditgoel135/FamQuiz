"""Settings validation matrix: per-field rejects, atomicity, locale, auth."""

from app import User


def _login(client, existing_user):
    client.post(
        "/login",
        data={
            "email": existing_user["email"],
            "password": existing_user["password"],
        },
    )


def _save(client, payload):
    return client.post("/api/settings/save", json=payload)


class TestSettingsMatrix:
    def test_display_name(self, client, existing_user):
        _login(client, existing_user)
        assert _save(client, {"display_name": 123}).status_code == 400
        assert _save(client, {"display_name": "x" * 81}).status_code == 400
        assert _save(client, {"display_name": "  spaced   out  "}).status_code == 200
        assert _save(client, {"display_name": ""}).status_code == 200

    def test_nickname_grade_subject(self, client, existing_user):
        _login(client, existing_user)
        assert _save(client, {"nickname": 123}).status_code == 400
        assert _save(client, {"grade_occupation": 123}).status_code == 400
        assert _save(client, {"favorite_subject": "x" * 81}).status_code == 400
        assert _save(client, {"grade_occupation": "Grade 5"}).status_code == 200
        assert _save(client, {"favorite_subject": "  Math   Science "}).status_code == 200

    def test_language(self, client, existing_user):
        _login(client, existing_user)
        for lang, loc in [
            ("English", "en"), ("Spanish", "es"),
            ("Hindi", "hi"), ("Mandarin Chinese", "zh_Hans"),
        ]:
            assert _save(client, {"language": lang}).status_code == 200
            with client.session_transaction() as sess:
                assert sess.get("locale") == loc
        for bad in ("Klingon", "", "spanish", None, 123):
            resp = _save(client, {"language": bad})
            assert resp.status_code == 400
            assert "language" in resp.get_json()["fields"]

    def test_theme(self, client, existing_user):
        _login(client, existing_user)
        assert _save(client, {"theme_mode": "light"}).status_code == 200
        assert _save(client, {"theme_mode": "dark"}).status_code == 200
        for bad in ("neon", "", "Dark", None, 123):
            resp = _save(client, {"theme_mode": bad})
            assert resp.status_code == 400

    def test_reminders(self, client, existing_user):
        _login(client, existing_user)
        assert _save(client, {"game_reminders": True}).status_code == 200
        assert _save(client, {"game_reminders": False}).status_code == 200
        for bad in ("true", 1, 0, None):
            resp = _save(client, {"game_reminders": bad})
            assert resp.status_code == 400
            assert "game_reminders" in resp.get_json()["fields"]

    def test_difficulty(self, client, existing_user):
        _login(client, existing_user)
        for good in ("easy", "Easy", " MEDIUM "):
            assert _save(client, {"difficulty_level": good}).status_code == 200
        for bad in ("extreme", "", None, 123, True):
            resp = _save(client, {"difficulty_level": bad})
            assert resp.status_code == 400

    def test_num(self, client, existing_user):
        _login(client, existing_user)
        assert _save(client, {"default_num_questions": 1}).status_code == 200
        assert _save(client, {"default_num_questions": 20}).status_code == 200
        assert _save(client, {"default_num_questions": "7"}).status_code == 200
        for bad in (0, 21, 999, -1, 5.5, "many", True, False, None, "", []):
            resp = _save(client, {"default_num_questions": bad})
            assert resp.status_code == 400, bad
            assert "default_num_questions" in resp.get_json()["fields"]

    def test_status(self, client, existing_user):
        _login(client, existing_user)
        for good in ("Ready to play", "Do not disturb", "offline"):
            assert _save(client, {"status": good}).status_code == 200
        for bad in ("invisible", "", "ready to play", None, 123):
            resp = _save(client, {"status": bad})
            assert resp.status_code == 400

    def test_multi_error_atomic(self, client, app, existing_user):
        _login(client, existing_user)
        resp = _save(
            client,
            {
                "language": "Klingon",
                "theme_mode": "neon",
                "difficulty_level": "extreme",
                "status": "invisible",
                "default_num_questions": 999,
            },
        )
        assert resp.status_code == 400
        fields = resp.get_json()["fields"]
        assert set(fields) >= {
            "language", "theme_mode", "difficulty_level",
            "status", "default_num_questions",
        }
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert (user.difficulty_level or "medium") == "medium"

    def test_partial_keeps(self, client, app, existing_user):
        from app import db

        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.display_name = "Keep"
            db.session.commit()
        assert _save(client, {"difficulty_level": "easy"}).status_code == 200
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.display_name == "Keep"
            assert user.difficulty_level == "easy"

    def test_requires_login(self, client):
        assert client.post("/api/settings/save", json={}).status_code in (302, 401)
        assert client.post("/api/account/erase-data").status_code in (302, 401)
        assert client.delete("/api/account").status_code in (302, 401)

    def test_locale_immediate(self, client, existing_user):
        _login(client, existing_user)
        _save(client, {"language": "Spanish"})
        with client.session_transaction() as sess:
            assert sess.get("locale") == "es"
        assert "Guardar" in client.get("/settings").data.decode() or \
            "Ajustes" in client.get("/settings").data.decode()

    def test_per_locale(self, client, existing_user):
        _login(client, existing_user)
        assert "Ajustes" in client.get("/settings?lang=es").data.decode() or \
            "Guardar" in client.get("/settings?lang=es").data.decode()
        assert 'lang="hi"' in client.get("/settings?lang=hi").data.decode()
        assert 'lang="zh-Hans"' in client.get("/settings?lang=zh_Hans").data.decode()

    def test_erase_clears_session(self, client, existing_user, monkeypatch):
        import json as _json
        from types import SimpleNamespace

        import app as app_module

        _login(client, existing_user)

        class _F:
            def chat(self, model="", messages=None, **kwargs):
                content = _json.dumps(
                    {"questions": [{"question": "Q?", "options": ["A", "B", "C", "D"],
                                    "answer_index": 0}]}
                )
                return SimpleNamespace(message=SimpleNamespace(content=content))

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _F())
        client.post("/api/quiz/generate", json={"num_questions": 1})
        assert client.post("/api/account/erase-data").get_json() == {"ok": True}
        with client.session_transaction() as sess:
            assert "quiz" not in sess
        with client.app_context() if hasattr(client, "app_context") else _noop():
            pass

    def test_redirect_pin(self, client):
        resp = client.get("/settings", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/login?next=")
        assert "settings" in resp.headers["Location"]


def _noop():
    import contextlib

    return contextlib.nullcontext()
