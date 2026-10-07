"""Tests for the shared game lobby (notify all + auto-open)."""

import json
import time

from app import MAX_QUIZ_QUESTIONS, GameSession, db # type: ignore

BANNER_KEYS = [
    "Game starting in",
    "Join game",
    "Dismiss",
    "Waiting for players…",
    "Game live — opening…",
    "Game cancelled",
    "A family game is waiting — tap Join!",
    "Game reminders off — join from homepage",
    "Do not disturb respected",
    "Waiting time:",
    "Wait for the countdown — the game opens automatically.",
]


def _login(client, existing_user):
    """Log in the fixture user via POST /login.

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


def _second_user(app):
    """Create a second user for multi-user lobby tests.

    :param app: The Flask app fixture.
    :return: Dict with the second user's email and password.
    :rtype: dict
    """
    from flask_security.utils import hash_password
    from app import user_datastore

    with app.app_context():
        user_datastore.create_user(
            email="second@example.com", password=hash_password("x" * 12)
        )
        db.session.commit()
    return {"email": "second@example.com", "password": "x" * 12}


class TestLobbyAuth:
    def test_status_requires_login(self, client):
        """Verify status requires login.

        :param client: The client fixture.
        """
        assert client.get("/api/game/status").status_code == 302

    def test_start_requires_login(self, client):
        """Verify start requires login.

        :param client: The client fixture.
        """
        assert client.post("/api/game/start", json={}).status_code == 401

    def test_join_requires_login(self, client):
        """Verify join requires login.

        :param client: The client fixture.
        """
        assert client.post("/api/game/join", json={}).status_code == 401

    def test_events_requires_login(self, client):
        """Verify events requires login.

        :param client: The client fixture.
        """
        assert client.get("/api/game/events?once=1").status_code == 302


class TestGameStart:
    def test_start_creates_lobby(self, client, existing_user):
        """Verify start creates lobby.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        resp = client.post(
            "/api/game/start",
            json={
                "num_questions": 5,
                "difficulty": "easy",
                "powerups_enabled": False,
                "lobby_seconds": 60,
            },
        )
        assert resp.status_code == 201
        game = resp.get_json()["game"]
        assert game["status"] == "lobby"
        assert game["num_questions"] == 5
        assert game["difficulty"] == "easy"
        assert game["powerups_enabled"] is False
        assert game["lobby_seconds"] == 60
        assert 0 < game["starts_in_ms"] <= 60 * 1000
        assert game["join_url"] == "/gameplay"

    def test_start_clamps_values(self, client, existing_user):
        """Verify start clamps values.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        resp = client.post(
            "/api/game/start",
            json={"num_questions": 999, "difficulty": "nope", "lobby_seconds": 9999},
        )
        assert resp.status_code == 201
        game = resp.get_json()["game"]
        assert game["num_questions"] == MAX_QUIZ_QUESTIONS
        assert game["difficulty"] == "medium"
        assert game["lobby_seconds"] == 300
        resp2 = client.post("/api/game/cancel")
        assert resp2.status_code == 200
        resp3 = client.post("/api/game/start", json={"lobby_seconds": 1})
        assert resp3.get_json()["game"]["lobby_seconds"] == 10

    def test_second_start_conflicts(self, client, existing_user):
        """Verify second start conflicts.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        assert client.post("/api/game/start", json={}).status_code == 201
        resp = client.post("/api/game/start", json={})
        assert resp.status_code == 409
        assert resp.get_json()["game"]["status"] == "lobby"


class TestGameStatusJoin:
    def test_empty_status(self, client, existing_user):
        """Verify empty status.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        assert client.get("/api/game/status").get_json() == {"active_game": None}

    def test_status_shows_lobby(self, client, existing_user):
        """Verify status shows lobby.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 120})
        body = client.get("/api/game/status").get_json()
        assert body["active_game"]["status"] == "lobby"
        assert body["active_game"]["starts_in_ms"] > 0

    def test_lobby_goes_live_by_clock(self, client, app, existing_user):
        """Verify lobby goes live by clock.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 10})
        with app.app_context():
            game = GameSession.query.order_by(GameSession.id.desc()).first()
            game.starts_at = time.time() - 1
            db.session.commit()
        body = client.get("/api/game/status").get_json()
        assert body["active_game"]["status"] == "active"
        assert body["active_game"]["starts_in_ms"] == 0

    def test_expiry_finishes_game(self, client, app, existing_user):
        """Verify expiry finishes game.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 10})
        with app.app_context():
            game = GameSession.query.order_by(GameSession.id.desc()).first()
            game.starts_at = time.time() - 1000
            game.expires_at = time.time() - 1
            db.session.commit()
        assert client.get("/api/game/status").get_json() == {"active_game": None}

    def test_join_returns_config(self, client, existing_user):
        """Verify join returns config.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        client.post(
            "/api/game/start",
            json={
                "num_questions": 4,
                "difficulty": "hard",
                "powerups_enabled": False,
                "lobby_seconds": 60,
            },
        )
        body = client.post("/api/game/join").get_json()
        assert body["game"]["num_questions"] == 4
        assert body["game"]["difficulty"] == "hard"
        assert body["game"]["powerups_enabled"] is False

    def test_join_without_game_404(self, client, existing_user):
        """Verify join without game 404.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        assert client.post("/api/game/join").status_code == 404


class TestGameCancel:
    def test_only_starter_can_cancel(self, client, app, existing_user):
        """Verify only starter can cancel.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        client.post("/api/game/start", json={})
        other = _second_user(app)
        second = app.test_client()
        second.post(
            "/login", data={"email": other["email"], "password": other["password"]}
        )
        assert second.post("/api/game/cancel").status_code == 403
        assert client.post("/api/game/cancel").status_code == 200
        assert client.get("/api/game/status").get_json() == {"active_game": None}

    def test_cancel_without_game_404(self, client, existing_user):
        """Verify cancel without game 404.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        assert client.post("/api/game/cancel").status_code == 404


class TestGameEvents:
    def test_snapshot_once(self, client, existing_user):
        """Verify snapshot once.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        resp = client.get("/api/game/events?once=1")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type
        payload = resp.data.decode()
        assert "event: snapshot" in payload
        assert "game-pending" in payload

    def test_snapshot_empty(self, client, existing_user):
        """Verify snapshot empty.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        resp = client.get("/api/game/events?once=1")
        assert resp.status_code == 200
        assert "game-none" in resp.data.decode()


class TestLobbyI18n:
    def test_banner_keys_in_catalogs(self, app):
        """Verify banner keys in catalogs.

        :param app: The app fixture.
        """
        from app import TRANSLATIONS

        for locale in ("es", "hi", "zh_Hans"):
            for key in BANNER_KEYS:
                assert key in TRANSLATIONS[locale], (locale, key)

    def test_banner_keys_served_to_js(self, client):
        """Verify banner keys served to js.

        :param client: The client fixture.
        """
        body = client.get("/api/i18n/es.json").get_json()
        for key in BANNER_KEYS:
            assert key in body["strings"], key

    def test_homepage_has_wait_and_notifier(self, client, existing_user):
        """Verify homepage has wait and notifier.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        html = client.get("/").data.decode()
        assert 'id="home-wait"' in html
        assert 'id="game-notify"' in html
        assert "game_notify.js" in html

    def test_homepage_wait_translated(self, client):
        """Verify homepage wait translated.

        :param client: The client fixture.
        """
        html = client.get("/?lang=es").data.decode()
        assert "Tiempo de espera:" in html

    def test_guide_has_countdown_step(self, client):
        """Verify guide has countdown step.

        :param client: The client fixture.
        """
        html = client.get("/guide").data.decode()
        assert "countdown" in html.lower() or "cuenta atr" in html.lower()

    def test_notifier_on_all_pages(self, client, existing_user):
        """Verify notifier on all pages.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        for path in ("/guide", "/leaderboard"):
            assert 'id="game-notify"' in client.get(path).data.decode(), path
        _login(client, existing_user)
        for path in ("/", "/settings", "/gameplay"):
            assert 'id="game-notify"' in client.get(path).data.decode(), path


class TestGameStartDefaults:
    def test_empty_body_uses_defaults(self, client, existing_user):
        """Verify empty body uses defaults.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        game = client.post("/api/game/start", json={}).get_json()["game"]
        assert game["num_questions"] == 10
        assert game["difficulty"] == "medium"
        assert game["powerups_enabled"] is True
        assert game["lobby_seconds"] == 300

    def test_non_json_body_uses_defaults(self, client, existing_user):
        """Verify non json body uses defaults.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        resp = client.post(
            "/api/game/start", data="not-json", content_type="text/plain"
        )
        assert resp.status_code == 201
        assert resp.get_json()["game"]["lobby_seconds"] == 300

    def test_zero_questions_falls_back_to_default(self, client, existing_user):
        """Verify zero questions falls back to default.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        game = client.post("/api/game/start", json={"num_questions": 0}).get_json()[
            "game"
        ]
        assert game["num_questions"] == 10

    def test_non_bool_powerups_falls_back_to_true(self, client, existing_user):
        """Verify non bool powerups falls back to true.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        game = client.post(
            "/api/game/start", json={"powerups_enabled": "yes"}
        ).get_json()["game"]
        assert game["powerups_enabled"] is True


class TestSharedVisibility:
    def test_all_users_see_same_game(self, client, app, existing_user):
        """Verify all users see same game.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        started = client.post("/api/game/start", json={"lobby_seconds": 60}).get_json()[
            "game"
        ]
        other = _second_user(app)
        second = app.test_client()
        second.post(
            "/login", data={"email": other["email"], "password": other["password"]}
        )
        seen = second.get("/api/game/status").get_json()["active_game"]
        assert seen["id"] == started["id"]
        assert seen["status"] == "lobby"

    def test_status_payload_shape(self, client, existing_user):
        """Verify status payload shape.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        client.post(
            "/api/game/start",
            json={
                "num_questions": 4,
                "difficulty": "hard",
                "powerups_enabled": False,
                "lobby_seconds": 45,
            },
        )
        game = client.get("/api/game/status").get_json()["active_game"]
        for key in (
            "id",
            "status",
            "starts_in_ms",
            "starts_at",
            "expires_at",
            "num_questions",
            "difficulty",
            "powerups_enabled",
            "lobby_seconds",
            "join_url",
        ):
            assert key in game, key
        assert game["difficulty"] == "hard"
        assert game["powerups_enabled"] is False

    def test_expiry_matches_duration_math(self, client, existing_user):
        """Verify expiry matches duration math.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        game = client.post(
            "/api/game/start", json={"num_questions": 6, "lobby_seconds": 60}
        ).get_json()["game"]
        # expires_at = starts_at + num*30s + 120s grace.
        assert game["expires_at"] - game["starts_at"] == 6 * 30 + 120


class TestLiveGame:
    def _force_live(self, app):
        """Force the latest lobby game into the live state.

        :param app: The Flask app fixture.
        :return: None.
        :rtype: None
        """
        with app.app_context():
            game = GameSession.query.order_by(GameSession.id.desc()).first()
            game.starts_at = time.time() - 1
            db.session.commit()

    def test_join_when_live(self, client, app, existing_user):
        """Verify join when live.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        self._force_live(app)
        body = client.post("/api/game/join").get_json()
        assert body["game"]["status"] == "active"

    def test_once_snapshot_when_live(self, client, app, existing_user):
        """Verify once snapshot when live.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        self._force_live(app)
        payload = client.get("/api/game/events?once=1").data.decode()
        assert "game-live" in payload

    def test_cancel_when_live(self, client, app, existing_user):
        """Verify cancel when live.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        self._force_live(app)
        assert client.post("/api/game/cancel").status_code == 200
        assert client.get("/api/game/status").get_json() == {"active_game": None}


class TestGameEventsStream:
    def test_once_has_no_cache_headers(self, client, existing_user):
        """Verify once has no cache headers.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        resp = client.get("/api/game/events?once=1")
        assert "text/event-stream" in resp.content_type
        assert resp.headers.get("Cache-Control") == "no-cache"
        assert resp.headers.get("X-Accel-Buffering") == "no"

    def test_stream_terminates_when_game_ends(self, client, app, existing_user):
        """Verify stream terminates when game ends.

        A finished game ends the SSE generator after one heartbeat
        cycle, so the response completes instead of hanging.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 10})
        with app.app_context():
            game = GameSession.query.order_by(GameSession.id.desc()).first()
            game.starts_at = time.time() - 1000
            game.expires_at = time.time() - 1
            db.session.commit()
        resp = client.get("/api/game/events", buffered=False)
        assert "text/event-stream" in resp.content_type
        body = b"".join(resp.response).decode()
        assert "event: snapshot" in body
        assert "game-none" in body
        assert "event: end" in body


class TestPersonalisedJoin:
    def test_join_config_uses_own_language(
        self, client, app, existing_user, monkeypatch
    ):
        """Verify join config uses own language.

        The lobby shares config; question generation stays personalised
        per player language.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        :param monkeypatch: The monkeypatch fixture.
        """
        import json as _json
        from types import SimpleNamespace

        import app as app_module

        _login(client, existing_user)
        client.post(
            "/api/game/start",
            json={"num_questions": 1, "difficulty": "easy", "lobby_seconds": 60},
        )
        other = _second_user(app)
        second = app.test_client()
        second.post(
            "/login", data={"email": other["email"], "password": other["password"]}
        )
        with app.app_context():
            user = app_module.User.query.filter_by(email=other["email"]).one()
            user.language = "Hindi"
            db.session.commit()

        seen = []

        class _FakeClient:
            """Canned Ollama client capturing the quiz prompt."""

            def chat(self, model="", messages=None, **kwargs):
                """Record the chat call and return a canned question.

                :param model: The model name requested.
                :param messages: The chat messages sent to the model.
                :return: Fake chat response with canned content.
                """
                seen.append({"model": model, "messages": messages})
                content = _json.dumps(
                    {
                        "questions": [
                            {
                                "question": "Q?",
                                "options": ["A", "B", "C", "D"],
                                "answer_index": 0,
                            }
                        ]
                    }
                )
                return SimpleNamespace(message=SimpleNamespace(content=content))

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _FakeClient())
        lobby = second.post("/api/game/join").get_json()["game"]
        resp = second.post(
            "/api/quiz/generate",
            json={
                "num_questions": lobby["num_questions"],
                "difficulty": lobby["difficulty"],
                "powerups_enabled": lobby["powerups_enabled"],
            },
        )
        assert resp.status_code == 200
        prompt = " ".join(m["content"] for m in seen[0]["messages"])
        assert "Hindi" in prompt
