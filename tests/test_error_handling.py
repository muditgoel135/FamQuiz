"""Error handling: 500 hygiene, malformed JSON, oversized, unicode, frozen time."""

import pytest


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
        ["/api/settings/save", "/api/quiz/generate", "/api/game/start",
         "/api/quiz/answer", "/api/quiz/powerup", "/api/quiz/finish"],
    )
    def test_truncated(self, client, existing_user, path):
        _login(client, existing_user)
        resp = client.post(path, data='{"a":', content_type="application/json")
        assert resp.status_code in (200, 201, 400, 401, 404, 409, 502, 503)

    @pytest.mark.parametrize(
        "path",
        ["/api/settings/save", "/api/quiz/generate", "/api/game/start",
         "/api/quiz/finish"],
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
        ["/api/settings/save", "/api/quiz/generate", "/api/game/start",
         "/api/quiz/answer", "/api/quiz/powerup", "/api/quiz/finish"],
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
            assert User.query.filter_by(
                email=existing_user["email"]).one().display_name != "x" * 10000

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
            "/api/quiz/generate", json={"num_questions": 10 ** 9}
        ).get_json()
        assert body["total"] <= MAX_QUIZ_QUESTIONS


class TestUnicode:
    @pytest.mark.parametrize(
        "val", ["🎉 family", "مرحبا", "é̂️", "𝕳𝖊𝖑𝖑𝖔 test"],
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
            assert client.post("/reset", data={"email": existing_user["email"]}).status_code == 200
        assert len(outbox) == 1
        outbox[0].body.encode("utf-8")


class TestFrozenTimeMath:
    @pytest.mark.parametrize(
        "elapsed_ms,expected",
        [(0, 1500), (2000, 1467), (7500, 1375), (15000, 1250),
         (30000, 1000), (40000, 1000)],
    )
    def test_exact_table(self, client, existing_user, fake_ollama, frozen_time,
                         elapsed_ms, expected):
        _login(client, existing_user)
        fake_ollama(n=1)
        assert client.post("/api/quiz/generate", json={"num_questions": 1}).status_code == 200
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
