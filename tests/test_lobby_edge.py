"""Edge-case tests for the shared game lobby: clocks, matrices, quit/delete."""

import json
import time
from types import SimpleNamespace

import app as app_module
from app import GameSession, db


def _login(client, existing_user):
    client.post(
        "/login",
        data={
            "email": existing_user["email"],
            "password": existing_user["password"],
        },
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


def _mock1(monkeypatch):
    class _F:
        def chat(self, model="", messages=None, **kwargs):
            content = json.dumps(
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
    monkeypatch.setattr(app_module, "get_ollama_client", lambda: _F())


class TestRefreshDirect:
    def _new(self, app, **kw):
        from app import GameSession

        with app.app_context():
            game = GameSession(**kw)
            db.session.add(game)
            db.session.commit()
            return game.id

    def _status(self, app, gid):
        with app.app_context():
            return db.session.get(GameSession, gid).status

    def test_finished_cancelled_untouched(self, app, monkeypatch):
        now = time.time()
        monkeypatch.setattr("routes.time.time", lambda: now)
        from routes import _refresh_game_status

        for status in ("finished", "cancelled"):
            gid = self._new(
                app, status=status, starts_at=now - 100, expires_at=now - 10
            )
            with app.app_context():
                game = db.session.get(GameSession, gid)
                assert _refresh_game_status(game).status == status

    def test_lobby_to_active(self, app):
        from routes import _refresh_game_status

        now = time.time()
        gid = self._new(
            app, status="lobby", starts_at=now - 1, expires_at=now + 1000
        )
        with app.app_context():
            game = db.session.get(GameSession, gid)
            assert _refresh_game_status(game).status == "active"
        assert self._status(app, gid) == "active"

    def test_future_stays(self, app):
        from routes import _refresh_game_status

        now = time.time()
        gid = self._new(
            app, status="lobby", starts_at=now + 100, expires_at=now + 1000
        )
        with app.app_context():
            game = db.session.get(GameSession, gid)
            assert _refresh_game_status(game).status == "lobby"

    def test_expiry_wins(self, app):
        from routes import _refresh_game_status

        now = time.time()
        for status in ("lobby", "active"):
            gid = self._new(
                app, status=status, starts_at=now - 1000, expires_at=now - 1
            )
            with app.app_context():
                game = db.session.get(GameSession, gid)
                assert _refresh_game_status(game).status == "finished"

    def test_active_expires(self, app):
        from routes import _refresh_game_status

        now = time.time()
        gid = self._new(
            app, status="active", starts_at=now - 1000, expires_at=now - 1
        )
        with app.app_context():
            game = db.session.get(GameSession, gid)
            assert _refresh_game_status(game).status == "finished"

    def test_zero_and_string(self, app):
        from routes import _refresh_game_status

        gid = self._new(app, status="lobby", starts_at=0, expires_at=0)
        with app.app_context():
            game = db.session.get(GameSession, gid)
            assert _refresh_game_status(game).status == "finished"
        # Garbage strings cannot be persisted (Float column rejects them),
        # so exercise the float() fallback with a transient object instead.
        with app.app_context():
            transient = GameSession(status="lobby")
            transient.starts_at = "bad"
            transient.expires_at = "bad"
            assert _refresh_game_status(transient).status == "finished"

    def test_expire_stale_mixed(self, app):
        from routes import _expire_stale_games

        now = time.time()
        g1 = self._new(app, status="lobby", starts_at=now - 1000, expires_at=now - 1)
        g2 = self._new(app, status="lobby", starts_at=now - 1, expires_at=now + 1000)
        g3 = self._new(app, status="finished", starts_at=now - 1000, expires_at=now - 1)
        with app.app_context():
            _expire_stale_games()
        assert self._status(app, g1) == "finished"
        assert self._status(app, g2) == "active"
        assert self._status(app, g3) == "finished"

    def test_expire_skips_invalid(self, app, monkeypatch):
        from routes import _expire_stale_games

        # Float columns reject garbage at INSERT, so the unparsable branch
        # is only reachable in-memory. Verify the sweeper tolerates a
        # transient bad row mixed with a real one without raising.
        now = time.time()
        gid = self._new(
            app, status="lobby", starts_at=now + 100, expires_at=now + 1000
        )
        transient = GameSession(status="lobby")
        transient.starts_at = "bad"
        transient.expires_at = "bad"
        with app.app_context():
            _expire_stale_games()  # must not raise
        with app.app_context():
            assert db.session.get(GameSession, gid).status == "lobby"

    def test_live_latest_and_none(self, app, client, existing_user):
        from routes import _get_live_game

        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        client.post("/api/game/cancel")
        client.post("/api/game/start", json={"lobby_seconds": 60})
        with app.app_context():
            games = GameSession.query.order_by(GameSession.id.desc()).all()
            assert len(games) >= 2
            live = _get_live_game()
            assert live.id == games[0].id
        client.post("/api/game/cancel")
        with app.app_context():
            assert _get_live_game() is None

    def test_live_auto_active(self, client, app, existing_user):
        from routes import _get_live_game

        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        with app.app_context():
            game = GameSession.query.order_by(GameSession.id.desc()).first()
            game.starts_at = time.time() - 1
            db.session.commit()
        with app.app_context():
            assert _get_live_game().status == "active"


class TestStartMatrix:
    def test_bool(self, client, existing_user):
        _login(client, existing_user)
        for val in (True, False):
            resp = client.post("/api/game/start", json={"num_questions": val})
            assert resp.status_code == 201
            assert resp.get_json()["game"]["num_questions"] == 10
            client.post("/api/game/cancel")

    def test_float(self, client, existing_user):
        _login(client, existing_user)
        for val in (3.9, 3.0):
            resp = client.post("/api/game/start", json={"num_questions": val})
            assert resp.get_json()["game"]["num_questions"] == 10
            client.post("/api/game/cancel")

    def test_string_coercion(self, client, existing_user):
        _login(client, existing_user)
        assert client.post(
            "/api/game/start", json={"num_questions": "5"}
        ).get_json()["game"]["num_questions"] == 5
        client.post("/api/game/cancel")
        assert client.post(
            "/api/game/start", json={"num_questions": "abc"}
        ).get_json()["game"]["num_questions"] == 10
        client.post("/api/game/cancel")
        assert client.post(
            "/api/game/start", json={"num_questions": ""}
        ).get_json()["game"]["num_questions"] == 10
        client.post("/api/game/cancel")
        assert client.post(
            "/api/game/start", json={"num_questions": None}
        ).get_json()["game"]["num_questions"] == 10
        client.post("/api/game/cancel")

    def test_user_default(self, client, app, existing_user):
        from app import User

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.default_num_questions = 7
            db.session.commit()
        _login(client, existing_user)
        assert client.post("/api/game/start", json={}).get_json()["game"][
            "num_questions"
        ] == 7

    def test_neg_zero(self, client, existing_user):
        _login(client, existing_user)
        assert client.post(
            "/api/game/start", json={"num_questions": -5}
        ).get_json()["game"]["num_questions"] == 1
        client.post("/api/game/cancel")
        assert client.post(
            "/api/game/start", json={"num_questions": 0}
        ).get_json()["game"]["num_questions"] == 10

    def test_difficulty(self, client, app, existing_user):
        from app import User

        _login(client, existing_user)
        assert client.post(
            "/api/game/start", json={"difficulty": "  EASY  "}
        ).get_json()["game"]["difficulty"] == "easy"
        client.post("/api/game/cancel")
        assert client.post(
            "/api/game/start", json={"difficulty": "nope"}
        ).get_json()["game"]["difficulty"] == "medium"
        client.post("/api/game/cancel")
        assert client.post(
            "/api/game/start", json={"difficulty": 123}
        ).get_json()["game"]["difficulty"] == "medium"
        client.post("/api/game/cancel")
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.difficulty_level = "hard"
            db.session.commit()
        assert client.post("/api/game/start", json={}).get_json()["game"][
            "difficulty"
        ] == "hard"

    def test_powerups(self, client, existing_user):
        _login(client, existing_user)
        for val in ("yes", 0, None):
            assert client.post(
                "/api/game/start", json={"powerups_enabled": val}
            ).get_json()["game"]["powerups_enabled"] is True
            client.post("/api/game/cancel")
        assert client.post(
            "/api/game/start", json={"powerups_enabled": False}
        ).get_json()["game"]["powerups_enabled"] is False

    def test_lobby_seconds(self, client, existing_user):
        _login(client, existing_user)
        cases = [
            (True, 300),
            (3.5, 300),
            ("60", 60),
            ("abc", 300),
            (-5, 10),
            (9999, 300),
            (1, 10),
        ]
        for raw, expected in cases:
            resp = client.post("/api/game/start", json={"lobby_seconds": raw})
            assert resp.get_json()["game"]["lobby_seconds"] == expected, raw
            client.post("/api/game/cancel")
        assert client.post("/api/game/start", json={}).get_json()["game"][
            "lobby_seconds"
        ] == 300

    def test_second_when_active(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 10})
        _live(app)
        resp = client.post("/api/game/start", json={})
        assert resp.status_code == 409
        assert resp.get_json()["game"]["status"] == "active"

    def test_after_cancel_expiry(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={})
        client.post("/api/game/cancel")
        assert client.post("/api/game/start", json={}).status_code == 201
        with app.app_context():
            game = GameSession.query.order_by(GameSession.id.desc()).first()
            game.starts_at = time.time() - 1000
            game.expires_at = time.time() - 1
            db.session.commit()
        assert client.post("/api/game/start", json={}).status_code == 201


class TestGameDict:
    def test_keys(self, client, existing_user):
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
        assert set(game) == {
            "id", "status", "starts_in_ms", "starts_at", "expires_at",
            "num_questions", "difficulty", "powerups_enabled", "lobby_seconds",
            "join_url", "you_left", "is_starter",
        }
        assert game["join_url"] == "/gameplay"
        assert game["difficulty"] == "hard"
        assert game["powerups_enabled"] is False

    def test_starts_in(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        game = client.get("/api/game/status").get_json()["active_game"]
        assert 0 < game["starts_in_ms"] <= 60 * 1000
        _live(app)
        game = client.get("/api/game/status").get_json()["active_game"]
        assert game["starts_in_ms"] == 0
        assert game["status"] == "active"

    def test_you_left(self, client, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        assert client.get("/api/game/status").get_json()["active_game"][
            "you_left"
        ] is False
        assert client.post("/api/quiz/quit").get_json()["left_game_id"] is not None
        assert client.get("/api/game/status").get_json()["active_game"][
            "you_left"
        ] is True
        assert client.post("/api/game/join").status_code == 200
        assert client.get("/api/game/status").get_json()["active_game"][
            "you_left"
        ] is False

    def test_is_starter(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={})
        assert client.get("/api/game/status").get_json()["active_game"][
            "is_starter"
        ] is True
        other = _second(app)
        second = app.test_client()
        second.post(
            "/login", data={"email": other["email"], "password": other["password"]}
        )
        assert second.get("/api/game/status").get_json()["active_game"][
            "is_starter"
        ] is False


class TestQuitDelete:
    def test_quit_clears_quiz_last(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _mock1(monkeypatch)
        client.post("/api/quiz/generate", json={"num_questions": 1})
        client.get("/api/quiz/state")
        with client.session_transaction() as sess:
            sess["last_result"] = {"quiz_score": 1, "total": 1}
            sess.modified = True
        body = client.post("/api/quiz/quit").get_json()
        assert body == {"ok": True, "left_game_id": None}
        with client.session_transaction() as sess:
            assert "quiz" not in sess
            assert "last_result" not in sess
        assert client.get("/api/quiz/state").status_code == 404

    def test_quit_active_sets_left(self, client, app, existing_user, monkeypatch):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        _live(app)
        _mock1(monkeypatch)
        # generate while live is allowed
        client.post("/api/quiz/generate", json={"num_questions": 1})
        body = client.post("/api/quiz/quit").get_json()
        assert body["ok"] is True
        assert body["left_game_id"] is not None
        assert client.get("/api/game/status").get_json()["active_game"][
            "you_left"
        ] is True
        assert client.get("/api/quiz/state").status_code == 404

    def test_quit_clears_stale_left(self, client, existing_user):
        _login(client, existing_user)
        with client.session_transaction() as sess:
            sess["left_game_id"] = 9999
        body = client.post("/api/quiz/quit").get_json()
        assert body == {"ok": True, "left_game_id": None}
        with client.session_transaction() as sess:
            assert "left_game_id" not in sess

    def test_delete_cancels_own(self, client, app, existing_user):
        _login(client, existing_user)
        gid = client.post("/api/game/start", json={"lobby_seconds": 60}).get_json()[
            "game"
        ]["id"]
        other = _second(app)
        assert client.delete("/api/account").get_json() == {"ok": True}
        with app.app_context():
            assert db.session.get(GameSession, gid).status == "cancelled"
        second = app.test_client()
        second.post(
            "/login", data={"email": other["email"], "password": other["password"]}
        )
        assert second.get("/api/game/status").get_json() == {"active_game": None}

    def test_delete_nonstarter_leaves(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        other = _second(app)
        second = app.test_client()
        second.post(
            "/login", data={"email": other["email"], "password": other["password"]}
        )
        assert second.delete("/api/account").get_json() == {"ok": True}
        assert client.get("/api/game/status").get_json()["active_game"][
            "status"
        ] == "lobby"

    def test_erase_not_cancel(self, client, existing_user, monkeypatch):
        _login(client, existing_user)
        _mock1(monkeypatch)
        client.post("/api/quiz/generate", json={"num_questions": 1})
        client.post("/api/game/start", json={"lobby_seconds": 60})
        assert client.post("/api/account/erase-data").get_json() == {"ok": True}
        assert client.get("/api/game/status").get_json()["active_game"][
            "status"
        ] == "lobby"
        assert client.get("/api/quiz/state").status_code == 404


class TestJoinCancel:
    def test_join_cancelled_404(self, client, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        client.post("/api/game/cancel")
        resp = client.post("/api/game/join")
        assert resp.status_code == 404
        assert "No live game" in resp.get_json()["error"]

    def test_join_expired_404(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        with app.app_context():
            game = GameSession.query.order_by(GameSession.id.desc()).first()
            game.starts_at = time.time() - 1000
            game.expires_at = time.time() - 1
            db.session.commit()
        assert client.post("/api/game/join").status_code == 404

    def test_join_active_clears(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        _live(app)
        client.post("/api/quiz/quit")
        body = client.post("/api/game/join").get_json()
        assert body["game"]["status"] == "active"
        assert client.get("/api/game/status").get_json()["active_game"][
            "you_left"
        ] is False

    def test_cancel_active_shape(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        _live(app)
        body = client.post("/api/game/cancel").get_json()
        assert body["ok"] is True
        assert body["game"]["status"] == "cancelled"
        assert client.get("/api/game/status").get_json() == {"active_game": None}

    def test_cancel_twice_404(self, client, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        assert client.post("/api/game/cancel").status_code == 200
        resp = client.post("/api/game/cancel")
        assert resp.status_code == 404
        assert "No live game" in resp.get_json()["error"]

    def test_cancel_expired_404(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        with app.app_context():
            game = GameSession.query.order_by(GameSession.id.desc()).first()
            game.starts_at = time.time() - 1000
            game.expires_at = time.time() - 1
            db.session.commit()
        assert client.post("/api/game/cancel").status_code == 404

    def test_cancel_nonstarter_active_403(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        _live(app)
        other = _second(app)
        second = app.test_client()
        second.post(
            "/login", data={"email": other["email"], "password": other["password"]}
        )
        resp = second.post("/api/game/cancel")
        assert resp.status_code == 403
        assert "Only the starter" in resp.get_json()["error"]
        assert client.get("/api/game/status").get_json()["active_game"][
            "status"
        ] == "active"

    def test_status_after_cancel_expiry(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        assert client.get("/api/game/status").get_json()["active_game"][
            "status"
        ] == "lobby"
        client.post("/api/game/cancel")
        assert client.get("/api/game/status").get_json() == {"active_game": None}
        client.post("/api/game/start", json={"lobby_seconds": 60})
        with app.app_context():
            game = GameSession.query.order_by(GameSession.id.desc()).first()
            game.starts_at = time.time() - 1000
            game.expires_at = time.time() - 1
            db.session.commit()
        assert client.get("/api/game/status").get_json() == {"active_game": None}

    def test_events_once_after_cancel(self, client, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        client.post("/api/game/cancel")
        resp = client.get("/api/game/events?once=1")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type
        assert resp.headers.get("Cache-Control") == "no-cache"
        body = resp.data.decode()
        assert "event: snapshot" in body
        assert "game-none" in body
