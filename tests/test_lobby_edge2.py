"""Residual lobby tests: binding types, clocks, multi-user, events exact."""

import time

from app import GameSession, db


def _login(client, existing_user):
    client.post(
        "/login",
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


def _second(app):
    from flask_security.utils import hash_password
    from app import user_datastore

    with app.app_context():
        user_datastore.create_user(
            email="second@example.com", password=hash_password("x" * 12)
        )
        db.session.commit()
    return {"email": "second@example.com", "password": "x" * 12}


def _live(app):
    with app.app_context():
        game = GameSession.query.order_by(GameSession.id.desc()).first()
        game.starts_at = time.time() - 1
        db.session.commit()


class TestQuizMatchesLiveUnit:
    def test_no_live(self, app):
        from routes import _quiz_matches_live

        with app.app_context():
            assert _quiz_matches_live({"game_id": 999}) is True
            # Fixed: session-tampered shapes never count as live even with
            # no live game (previously True, leading to 500s downstream);
            # callers turn False into a clean 404 + session pop.
            assert _quiz_matches_live(None) is False
            assert _quiz_matches_live([1, 2]) is False
            assert _quiz_matches_live("quiz") is False

    def test_match(self, app):
        from types import SimpleNamespace

        import routes as routes_module

        with app.app_context():
            orig = routes_module._get_live_game
            routes_module._get_live_game = lambda: SimpleNamespace(id=5)
            try:
                assert routes_module._quiz_matches_live({"game_id": 5}) is True
                assert routes_module._quiz_matches_live({"game_id": 6}) is False
                assert routes_module._quiz_matches_live({}) is False
                assert routes_module._quiz_matches_live(None) is False
                assert routes_module._quiz_matches_live([1, 2]) is False
                assert routes_module._quiz_matches_live("quiz") is False
            finally:
                routes_module._get_live_game = orig

    def test_raises_true(self, app, monkeypatch):
        import routes as routes_module

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(routes_module, "_get_live_game", _boom)
        with app.app_context():
            assert routes_module._quiz_matches_live({}) is True


class TestGameIdTypes:
    def _setup_live_quiz(self, client, app, existing_user, monkeypatch):
        import json as _json
        from types import SimpleNamespace

        import app as app_module

        class _F:
            def chat(self, model="", messages=None, **kwargs):
                return SimpleNamespace(
                    message=SimpleNamespace(
                        content=_json.dumps(
                            {"questions": [{"question": "Q?",
                                            "options": ["A", "B", "C", "D"],
                                            "answer_index": 0}]}
                        )
                    )
                )

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _F())
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        _live(app)
        assert client.post("/api/quiz/generate", json={"num_questions": 1}).status_code == 200

    def test_string_mismatch(self, client, app, existing_user, monkeypatch):
        self._setup_live_quiz(client, app, existing_user, monkeypatch)
        with app.app_context():
            live_id = GameSession.query.order_by(GameSession.id.desc()).first().id
        with client.session_transaction() as sess:
            sess["quiz"]["game_id"] = str(live_id)
            sess.modified = True
        resp = client.get("/api/quiz/state")
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Quiz expired. Rejoin the live game."}

    def test_missing_key(self, client, app, existing_user, monkeypatch):
        self._setup_live_quiz(client, app, existing_user, monkeypatch)
        with client.session_transaction() as sess:
            sess["quiz"].pop("game_id")
            sess.modified = True
        assert client.get("/api/quiz/state").status_code == 404

    def test_none_vs_live(self, client, existing_user, monkeypatch):
        import json as _json
        from types import SimpleNamespace

        import app as app_module

        class _F:
            def chat(self, model="", messages=None, **kwargs):
                return SimpleNamespace(
                    message=SimpleNamespace(
                        content=_json.dumps(
                            {"questions": [{"question": "Q?",
                                            "options": ["A", "B", "C", "D"],
                                            "answer_index": 0}]}
                        )
                    )
                )

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _F())
        _login(client, existing_user)
        assert client.post("/api/quiz/generate", json={"num_questions": 1}).status_code == 200
        client.post("/api/game/start", json={"lobby_seconds": 60})
        resp = client.get("/api/quiz/state")
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Quiz expired. Rejoin the live game."}


class TestStaleAB:
    def test_all_rejected(self, client, app, existing_user, monkeypatch):
        import json as _json
        from types import SimpleNamespace

        import app as app_module

        class _F:
            def chat(self, model="", messages=None, **kwargs):
                return SimpleNamespace(
                    message=SimpleNamespace(
                        content=_json.dumps(
                            {"questions": [{"question": "Q?",
                                            "options": ["A", "B", "C", "D"],
                                            "answer_index": 0}]}
                        )
                    )
                )

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _F())
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 10})
        _live(app)
        client.post("/api/quiz/generate", json={"num_questions": 1})
        client.post("/api/game/cancel")
        client.post("/api/game/start", json={"lobby_seconds": 60})
        assert client.get("/api/quiz/state").status_code == 404
        assert client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        ).status_code == 404
        assert client.post("/api/quiz/powerup", json={"kind": "double"}).status_code == 404
        assert client.post("/api/quiz/finish").status_code == 404
        with app.app_context():
            from app import User

            assert User.query.filter_by(email=existing_user["email"]).one().total_games_played == 0

    def test_matching_works(self, client, app, existing_user, monkeypatch):
        import json as _json
        from types import SimpleNamespace

        import app as app_module

        class _F:
            def chat(self, model="", messages=None, **kwargs):
                return SimpleNamespace(
                    message=SimpleNamespace(
                        content=_json.dumps(
                            {"questions": [{"question": "Q?",
                                            "options": ["A", "B", "C", "D"],
                                            "answer_index": 0}]}
                        )
                    )
                )

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _F())
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 10})
        _live(app)
        client.post("/api/quiz/generate", json={"num_questions": 1})
        assert client.get("/api/quiz/state").status_code == 200


class TestClockResidual:
    def _new(self, app, **kw):
        with app.app_context():
            game = GameSession(**kw)
            db.session.add(game)
            db.session.commit()
            return game.id

    def test_active_future(self, app):
        from routes import _refresh_game_status

        now = time.time()
        gid = self._new(app, status="active", starts_at=now + 100,
                        expires_at=now + 1000)
        with app.app_context():
            assert _refresh_game_status(db.session.get(GameSession, gid)).status == "active"

    def test_none_timestamps(self, app):
        from routes import _refresh_game_status

        with app.app_context():
            transient = GameSession(status="lobby")
            transient.starts_at = None
            transient.expires_at = None
            assert _refresh_game_status(transient).status == "finished"

    def test_active_expired_sweep(self, app):
        from routes import _expire_stale_games

        now = time.time()
        gid = self._new(app, status="active", starts_at=now - 1000,
                        expires_at=now - 1)
        gid2 = self._new(app, status="lobby", starts_at=now + 100,
                         expires_at=now + 1000)
        with app.app_context():
            _expire_stale_games()
        with app.app_context():
            assert db.session.get(GameSession, gid).status == "finished"
            assert db.session.get(GameSession, gid2).status == "lobby"

    def test_rollback_no_raise(self, app, monkeypatch):
        from routes import _expire_stale_games

        now = time.time()
        gid = self._new(app, status="lobby", starts_at=now - 1000,
                        expires_at=now - 1)
        rolled = {}

        def _boom():
            raise RuntimeError("db down")

        orig_commit = db.session.commit
        monkeypatch.setattr(db.session, "commit", _boom)
        monkeypatch.setattr(
            db.session, "rollback", lambda: rolled.update(called=True)
        )
        with app.app_context():
            _expire_stale_games()  # must not raise
        assert rolled.get("called") is True
        monkeypatch.setattr(db.session, "commit", orig_commit)


class TestGameDictNones:
    def test_transient(self, app):
        from routes import _game_to_dict

        with app.test_request_context("/"):
            game = GameSession(status="lobby")
            game.id = 7
            game.starts_at = None
            game.expires_at = None
            game.num_questions = 4
            game.difficulty = "hard"
            game.powerups_enabled = None
            game.lobby_seconds = 45
            game.created_by_id = None
            out = _game_to_dict(game)
        assert out["starts_in_ms"] == 0
        assert out["powerups_enabled"] is False
        assert out["is_starter"] is False
        assert out["you_left"] is False
        assert set(out) == {"id", "status", "starts_in_ms", "starts_at",
                            "expires_at", "num_questions", "difficulty",
                            "powerups_enabled", "lobby_seconds", "join_url",
                            "you_left", "is_starter"}

    def test_is_starter_exception(self, app):
        from unittest import mock

        import app as app_module
        from routes import _game_to_dict

        class _Boom:
            @property
            def is_authenticated(self):
                raise RuntimeError("boom")

        with app.test_request_context("/"):
            game = GameSession(status="lobby")
            game.id = 1
            with mock.patch.object(app_module, "current_user", _Boom()):
                assert _game_to_dict(game)["is_starter"] is False


class TestSecondUserConflict:
    def test_exact(self, client, app, existing_user):
        _login(client, existing_user)
        gid = client.post("/api/game/start", json={"lobby_seconds": 60}).get_json()[
            "game"]["id"]
        other = _second(app)
        second = app.test_client()
        second.post("/login", data={"email": other["email"],
                                    "password": other["password"]})
        resp = second.post("/api/game/start", json={})
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["error"] == "A game is already live."
        assert body["game"]["id"] == gid
        assert set(body["game"]) == {"id", "status", "starts_in_ms", "starts_at",
                                     "expires_at", "num_questions", "difficulty",
                                     "powerups_enabled", "lobby_seconds",
                                     "join_url", "you_left", "is_starter"}


class TestCancelVisibilityQuiz:
    def test_visible_to_both(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        other = _second(app)
        second = app.test_client()
        second.post("/login", data={"email": other["email"],
                                    "password": other["password"]})
        assert second.get("/api/game/status").get_json()["active_game"][
            "status"] == "lobby"
        body = client.post("/api/game/cancel").get_json()
        assert body["ok"] is True
        assert body["game"]["status"] == "cancelled"
        assert client.get("/api/game/status").get_json() == {"active_game": None}
        assert second.get("/api/game/status").get_json() == {"active_game": None}
        resp = second.post("/api/game/join")
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "No live game. Start one from the homepage."}

    def test_quiz_survives_cancel(self, client, app, existing_user, monkeypatch):
        import json as _json
        from types import SimpleNamespace

        import app as app_module

        class _F:
            def chat(self, model="", messages=None, **kwargs):
                return SimpleNamespace(
                    message=SimpleNamespace(
                        content=_json.dumps(
                            {"questions": [{"question": "Q?",
                                            "options": ["A", "B", "C", "D"],
                                            "answer_index": 0}]}
                        )
                    )
                )

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _F())
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 10})
        _live(app)
        client.post("/api/quiz/generate", json={"num_questions": 1})
        client.post("/api/game/cancel")
        # Intended solo-continuation: cancel does not pop the quiz; with no
        # live game the binding is vacuous so the in-progress quiz still
        # serves (solo play continues). Under a NEW countdown the older
        # quiz is stale and 404s (see TestStaleAB).
        assert client.get("/api/quiz/state").status_code == 200

    def test_cancel_twice_exact(self, client, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        client.post("/api/game/cancel")
        resp = client.post("/api/game/cancel")
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "No live game to cancel."}

    def test_nonstarter_403_active(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        _live(app)
        other = _second(app)
        second = app.test_client()
        second.post("/login", data={"email": other["email"],
                                    "password": other["password"]})
        resp = second.post("/api/game/cancel")
        assert resp.status_code == 403
        assert resp.get_json() == {"error": "Only the starter can cancel this game."}
        assert client.get("/api/game/status").get_json()["active_game"][
            "status"] == "active"


class TestSequentialFinish:
    def test_cached_once(self, client, existing_user, monkeypatch):
        import json as _json
        from types import SimpleNamespace

        import app as app_module

        class _F:
            def chat(self, model="", messages=None, **kwargs):
                return SimpleNamespace(
                    message=SimpleNamespace(
                        content=_json.dumps(
                            {"questions": [{"question": "Q?",
                                            "options": ["A", "B", "C", "D"],
                                            "answer_index": 0}]}
                        )
                    )
                )

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _F())
        _login(client, existing_user)
        client.post("/api/quiz/generate", json={"num_questions": 1})
        client.get("/api/quiz/state")
        import time as _t

        with client.session_transaction() as sess:
            sess["quiz"]["started_at"] = _t.time() - 1
            sess.modified = True
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        first = client.post("/api/quiz/finish").get_json()
        second = client.post("/api/quiz/finish").get_json()
        assert first == second
        assert set(first) == {"quiz_score", "total", "best_score", "is_win",
                              "powerups_used"}
        with client.application.app_context():
            from app import User

            assert User.query.filter_by(email=existing_user["email"]).one().total_games_played == 1

    def test_two_games_twice(self, client, app, existing_user, monkeypatch):
        import json as _json
        import time as _t
        from types import SimpleNamespace

        import app as app_module

        class _F:
            def chat(self, model="", messages=None, **kwargs):
                return SimpleNamespace(
                    message=SimpleNamespace(
                        content=_json.dumps(
                            {"questions": [{"question": "Q?",
                                            "options": ["A", "B", "C", "D"],
                                            "answer_index": 0}]}
                        )
                    )
                )

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _F())
        _login(client, existing_user)
        for _ in range(2):
            client.post("/api/quiz/generate", json={"num_questions": 1})
            client.get("/api/quiz/state")
            with client.session_transaction() as sess:
                sess["quiz"]["started_at"] = _t.time() - 1
                sess.modified = True
            client.post("/api/quiz/answer",
                        json={"option_index": 0, "question_index": 0})
            assert client.post("/api/quiz/finish").status_code == 200
        with app.app_context():
            from app import User

            assert User.query.filter_by(email=existing_user["email"]).one().total_games_played == 2


class TestQuitLeftVsNew:
    def test_stale_not_applied(self, client, existing_user):
        _login(client, existing_user)
        with client.session_transaction() as sess:
            sess["left_game_id"] = 9999
        client.post("/api/game/start", json={"lobby_seconds": 60})
        assert client.get("/api/game/status").get_json()["active_game"][
            "you_left"] is False
        assert client.post("/api/quiz/quit").get_json()["left_game_id"] is not None

    def test_quit_then_new_clears(self, client, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        client.post("/api/quiz/quit")
        client.post("/api/game/cancel")
        client.post("/api/game/start", json={"lobby_seconds": 60})
        assert client.get("/api/game/status").get_json()["active_game"][
            "you_left"] is False

    def test_join_clears(self, client, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        client.post("/api/quiz/quit")
        assert client.post("/api/game/join").status_code == 200
        assert client.get("/api/game/status").get_json()["active_game"][
            "you_left"] is False


class TestEventsOnceExact:
    def _payload(self, resp):
        import json as _json

        body = resp.data.decode()
        assert "event: snapshot" in body
        data = body.split("data: ", 1)[1].strip()
        return _json.loads(data)

    def test_none(self, client, existing_user):
        _login(client, existing_user)
        resp = client.get("/api/game/events?once=1")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type
        assert resp.headers.get("Cache-Control") == "no-cache"
        assert self._payload(resp) == {"type": "game-none", "active_game": None}

    def test_pending(self, client, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        payload = self._payload(client.get("/api/game/events?once=1"))
        assert payload["type"] == "game-pending"
        assert payload["status"] == "lobby"
        assert payload["starts_in_ms"] > 0
        assert payload["join_url"] == "/gameplay"
        assert payload["you_left"] is False
        assert payload["is_starter"] is True
        assert set(payload) == {"type", "id", "status", "starts_in_ms",
                                "starts_at", "expires_at", "num_questions",
                                "difficulty", "powerups_enabled",
                                "lobby_seconds", "join_url", "you_left",
                                "is_starter"}

    def test_live(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        _live(app)
        payload = self._payload(client.get("/api/game/events?once=1"))
        assert payload["type"] == "game-live"
        assert payload["status"] == "active"
        assert payload["starts_in_ms"] == 0

    def test_after_cancel(self, client, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        client.post("/api/game/cancel")
        assert self._payload(client.get("/api/game/events?once=1")) == {
            "type": "game-none", "active_game": None}


class TestSettingsI18nReverse:
    def test_settings_pins(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/settings").data.decode()
        assert "Profile" in html and "Accessibility" in html
        assert 'id="settings-difficulty"' in html

    def test_i18n_all(self, client):
        for loc, html_lang in [("en", "en"), ("es", "es"), ("hi", "hi"),
                               ("zh_Hans", "zh-Hans")]:
            body = client.get(f"/api/i18n/{loc}.json").get_json()
            assert body["locale"] == loc
            assert body["html_lang"] == html_lang
        assert len(client.get("/api/i18n/es.json").get_json()["strings"]) > 20

    def test_i18n_404(self, client):
        for loc in ("xx", "fr", "EN"):
            resp = client.get(f"/api/i18n/{loc}.json")
            assert resp.status_code == 404
            assert resp.get_json() == {"error": "Unsupported language."}

    def test_reverse_405(self, client, existing_user):
        _login(client, existing_user)
        assert client.post("/").status_code == 405
        assert client.get("/api/account").status_code == 405
        assert client.post("/api/account").status_code == 405
        assert client.post("/api/quiz/state", json={}).status_code == 405
        assert client.post("/api/game/status", json={}).status_code == 405
        assert client.post("/api/game/events?once=1").status_code == 405
        assert client.get("/api/quiz/finish").status_code == 405
        assert client.get("/api/quiz/quit").status_code == 405
        assert client.get("/api/game/start").status_code == 405
        assert client.post("/api/account", json={}).status_code == 405
