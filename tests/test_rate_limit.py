"""Tests for the in-memory rate limiter (routes._rate_limited).

The limiter is the only thing standing between a stuck browser tab and a
run of paid Ollama calls, yet it had no coverage at all. It is also
short-circuited while ``TESTING`` is true, so every test here flips the
flag (or calls the helper directly).

Covered contract:

* ``_rate_limited(key, limit, window_s)`` keeps a sliding window of hits.
* A rejected call is *not* recorded, so a blocked client does not extend
  its own penalty indefinitely.
* ``quiz_generate`` is limited to 1 call / 10 s per (user, IP).
* ``game_start`` is limited to 1 call / 5 s per user.
* The 429 check runs *before* the "a game is already live" check.
"""

import json
import time

import pytest

import routes as routes_module


@pytest.fixture()
def limiter(app, monkeypatch):
    """Arm the rate limiter: TESTING off and an empty bucket table."""
    routes_module._RATE_BUCKETS.clear()
    monkeypatch.setitem(app.config, "TESTING", False)
    yield routes_module._RATE_BUCKETS
    routes_module._RATE_BUCKETS.clear()


def _login(client, existing_user):
    """Log a user in through the real login form."""
    client.post(
        "/login",
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


class TestRateLimitedHelper:
    """Unit-level behaviour of the sliding-window limiter."""

    def test_first_hit_is_allowed(self, app, limiter):
        """The first call inside a window is never limited."""
        with app.app_context():
            assert routes_module._rate_limited("k", limit=1, window_s=10) is False

    def test_second_hit_inside_window_is_limited(self, app, limiter):
        """Exceeding the limit inside the window returns True."""
        with app.app_context():
            routes_module._rate_limited("k", limit=1, window_s=10)
            assert routes_module._rate_limited("k", limit=1, window_s=10) is True

    def test_rejected_call_is_not_recorded(self, app, limiter, monkeypatch):
        """A blocked call must not extend its own penalty."""
        clock = {"now": 1000.0}
        monkeypatch.setattr(routes_module.time, "time", lambda: clock["now"])
        with app.app_context():
            routes_module._rate_limited("k", limit=1, window_s=10)
            routes_module._rate_limited("k", limit=1, window_s=10)
            assert limiter["k"] == [1000.0]

    def test_window_expiry_allows_again(self, app, limiter, monkeypatch):
        """Once the window elapses the key is allowed again."""
        clock = {"now": 1000.0}
        monkeypatch.setattr(routes_module.time, "time", lambda: clock["now"])
        with app.app_context():
            assert routes_module._rate_limited("k", limit=1, window_s=10) is False
            clock["now"] += 9.9
            assert routes_module._rate_limited("k", limit=1, window_s=10) is True
            clock["now"] += 0.2
            assert routes_module._rate_limited("k", limit=1, window_s=10) is False

    def test_stale_hits_are_trimmed_from_the_window(self, app, limiter, monkeypatch):
        """Hits older than the window are dropped before counting."""
        clock = {"now": 1000.0}
        monkeypatch.setattr(routes_module.time, "time", lambda: clock["now"])
        with app.app_context():
            routes_module._rate_limited("k", limit=2, window_s=10)
            clock["now"] += 20.0
            routes_module._rate_limited("k", limit=2, window_s=10)
            assert len(limiter["k"]) == 1

    def test_limit_of_two_allows_two_hits(self, app, limiter):
        """The limit is honoured exactly."""
        with app.app_context():
            assert routes_module._rate_limited("k", limit=2, window_s=10) is False
            assert routes_module._rate_limited("k", limit=2, window_s=10) is False
            assert routes_module._rate_limited("k", limit=2, window_s=10) is True

    def test_testing_mode_short_circuits(self, app, limiter):
        """Under TESTING the limiter never fires (the suite stays fast)."""
        app.config["TESTING"] = True
        with app.app_context():
            assert routes_module._rate_limited("k", limit=1, window_s=10) is False
            assert routes_module._rate_limited("k", limit=1, window_s=10) is False

    def test_buckets_are_never_pruned(self, app, limiter):
        """Documents the (intentional) unbounded growth of the bucket table.

        Each distinct key is kept forever. On a family LAN the number of
        keys is tiny, but the leak is real and worth pinning.
        """
        with app.app_context():
            for index in range(50):
                routes_module._rate_limited(f"k{index}", limit=1, window_s=1)
            assert len(limiter) == 50


class TestQuizCooldownKey:
    """The quiz cooldown key must identify the user *and* the client IP."""

    def test_key_contains_user_id_and_remote_addr(
        self, client, app, existing_user, limiter
    ):
        """The key shape is ``quiz:<user id>:<ip>``."""
        from flask_login import login_user

        from app import User

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user_id = user.id

        with app.test_request_context("/", environ_base={"REMOTE_ADDR": "10.0.0.5"}):
            login_user(user)
            key = routes_module._quiz_cooldown_key()
            assert key == f"quiz:{user_id}:10.0.0.5"

    def test_key_uses_anonymous_for_a_missing_user(self, app, limiter):
        """Without a logged-in user the key falls back to ``anon``."""
        with app.test_request_context("/", environ_base={"REMOTE_ADDR": "10.0.0.5"}):
            assert routes_module._quiz_cooldown_key() == "quiz:anon:10.0.0.5"

    def test_key_outside_a_request_context_raises(self, app, limiter):
        """Reading ``request.remote_addr`` without a request is a RuntimeError."""
        with app.app_context(), pytest.raises(RuntimeError):
            routes_module._quiz_cooldown_key()


class TestQuizGenerateRateLimit:
    """``POST /api/quiz/generate`` must be limited to 1 call / 10 s."""

    def test_second_generate_inside_window_is_429(
        self, client, app, existing_user, limiter, fake_ollama
    ):
        """The second generate call is rejected with 429."""
        fake_ollama(n=1)
        _login(client, existing_user)
        first = client.post("/api/quiz/generate", json={"num_questions": 1})
        assert first.status_code == 200

        second = client.post("/api/quiz/generate", json={"num_questions": 1})
        assert second.status_code == 429
        assert second.get_json() == {"error": "Quiz cooling down. Wait a few seconds."}

    def test_rate_limit_does_not_spend_ollama_credits(
        self, client, app, existing_user, limiter, fake_ollama
    ):
        """A rate-limited call must never reach the model."""
        calls = fake_ollama(n=1)
        _login(client, existing_user)
        assert (
            client.post("/api/quiz/generate", json={"num_questions": 1}).status_code
            == 200
        )
        assert len(calls) == 1

        blocked = client.post("/api/quiz/generate", json={"num_questions": 1})
        assert blocked.status_code == 429
        assert len(calls) == 1, "a blocked call must not spend credits"

    def test_different_ip_gets_its_own_bucket(
        self, client, app, existing_user, limiter, fake_ollama
    ):
        """The IP is part of the key, so another device is not blocked."""
        fake_ollama(n=1)
        _login(client, existing_user)
        first = client.post(
            "/api/quiz/generate",
            json={"num_questions": 1},
            environ_base={"REMOTE_ADDR": "10.0.0.5"},
        )
        assert first.status_code == 200

        other_ip = client.post(
            "/api/quiz/generate",
            json={"num_questions": 1},
            environ_base={"REMOTE_ADDR": "10.0.0.6"},
        )
        assert other_ip.status_code == 200

        same_ip = client.post(
            "/api/quiz/generate",
            json={"num_questions": 1},
            environ_base={"REMOTE_ADDR": "10.0.0.5"},
        )
        assert same_ip.status_code == 429

    def test_rate_limit_uses_the_user_and_ip_key(
        self, client, app, existing_user, limiter
    ):
        """The bucket key must be the documented ``quiz:<uid>:<ip>``."""
        _login(client, existing_user)
        client.post(
            "/api/quiz/generate",
            json={"num_questions": 1},
            environ_base={"REMOTE_ADDR": "10.0.0.9"},
        )
        with app.app_context():
            from app import User

            uid = User.query.filter_by(email=existing_user["email"]).one().id
        assert f"quiz:{uid}:10.0.0.9" in limiter


class TestGameStartRateLimit:
    """``POST /api/game/start`` must be limited to 1 call / 5 s."""

    def test_second_start_inside_window_is_429(
        self, client, app, existing_user, limiter
    ):
        """The second start call is rejected with 429."""
        _login(client, existing_user)
        first = client.post("/api/game/start", json={"lobby_seconds": 60})
        assert first.status_code == 201

        second = client.post("/api/game/start", json={"lobby_seconds": 60})
        assert second.status_code == 429
        assert second.get_json() == {"error": "Slow down. Wait a few seconds."}

    def test_rate_limit_precedes_the_already_live_conflict(
        self, client, app, existing_user, limiter
    ):
        """429 wins over 409 while the limiter is armed."""
        _login(client, existing_user)
        assert client.post("/api/game/start", json={}).status_code == 201
        # A live game already exists, but the limiter answers first.
        assert client.post("/api/game/start", json={}).status_code == 429

    def test_conflict_is_returned_once_the_window_expired(
        self, client, app, existing_user, limiter, monkeypatch
    ):
        """After the window the "already live" check reports 409 again."""
        _login(client, existing_user)
        assert client.post("/api/game/start", json={}).status_code == 201

        clock = {"now": time.time()}
        monkeypatch.setattr(routes_module.time, "time", lambda: clock["now"])
        client.post("/api/game/start", json={})  # consumes a slot
        clock["now"] += 5.1
        resp = client.post("/api/game/start", json={})
        assert resp.status_code == 409

    def test_rate_limit_key_is_user_only(self, client, app, existing_user, limiter):
        """The start bucket is keyed by user id, without the IP."""
        _login(client, existing_user)
        client.post("/api/game/start", json={})
        with app.app_context():
            from app import User

            uid = User.query.filter_by(email=existing_user["email"]).one().id
        assert f"start:{uid}" in limiter
        assert not any(key.startswith("start:") and ":" in key[6:] for key in limiter)


# ==== merged from test_sse_stream.py ====
def _login(client, existing_user):
    """Log a user in through the real login form."""
    client.post(
        "/login",
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


def _events(body):
    """Return the SSE event names present in a raw stream body."""
    names = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("event:"):
            names.append(line.split(":", 1)[1].strip())
        elif line.startswith(":"):
            names.append("comment")
    return names


def _data(body, event):
    """Return the parsed JSON payload of the first ``event`` in a body."""
    current = None
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("event:"):
            current = line.split(":", 1)[1].strip()
            continue
        if line.startswith("data:") and current == event:
            raw = line.split(":", 1)[1].strip()
            return json.loads(raw) if raw else {}
    return None


class TestSnapshot:
    """``?once=1`` returns a single snapshot and closes."""

    def test_once_returns_one_snapshot(self, client, app, existing_user):
        """The snapshot mode must not stream."""
        _login(client, existing_user)
        resp = client.get("/api/game/events?once=1")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/event-stream")
        body = resp.get_data(as_text=True)
        assert _events(body) == ["snapshot"]

    def test_once_snapshot_reports_no_game(self, client, app, existing_user):
        """With no live game the snapshot type is ``game-none``."""
        _login(client, existing_user)
        body = client.get("/api/game/events?once=1").get_data(as_text=True)
        assert _data(body, "snapshot") == {"type": "game-none", "active_game": None}

    def test_once_snapshot_reports_pending_game(self, client, app, existing_user):
        """A lobby game is reported as ``game-pending``."""
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        body = client.get("/api/game/events?once=1").get_data(as_text=True)
        payload = _data(body, "snapshot")
        assert payload["type"] == "game-pending"
        assert payload["status"] == "lobby"


class TestStreamTransitions:
    """The streaming generator's status-change branches."""

    def test_snapshot_is_always_the_first_event(
        self, client, app, existing_user, sse_driver, fake_game
    ):
        """The client needs an immediate state before any update."""
        _login(client, existing_user)
        body = sse_driver(client, [fake_game("lobby")])
        assert _events(body)[0] == "snapshot"

    def test_status_change_emits_an_update(
        self, client, app, existing_user, sse_driver, fake_game
    ):
        """A lobby that goes live must push an ``update`` event."""
        _login(client, existing_user)
        body = sse_driver(
            client, [fake_game("lobby"), fake_game("active"), fake_game("active"), None]
        )
        assert "event: update" in body
        payload = _data(body, "update")
        assert payload["type"] == "game-live"
        assert payload["status"] == "active"

    def test_update_is_emitted_exactly_once_per_change(
        self, client, app, existing_user, sse_driver, fake_game
    ):
        """An unchanged snapshot must not produce repeated updates."""
        _login(client, existing_user)
        body = sse_driver(
            client,
            [
                fake_game("lobby"),
                fake_game("active"),
                fake_game("active"),
                fake_game("active"),
                None,
            ],
        )
        assert _events(body).count("update") == 1

    def test_countdown_churn_does_not_emit_updates(
        self, client, app, existing_user, sse_driver, fake_game
    ):
        """``starts_in_ms`` changes every second and must be deduped out."""
        _login(client, existing_user)
        body = sse_driver(client, [fake_game("lobby")] * 6 + [None])
        assert "event: update" not in body

    def test_game_disappearing_ends_the_stream(
        self, client, app, existing_user, sse_driver, fake_game
    ):
        """When the game vanishes the client must be told the stream ended.

        ``static/game_notify.js`` closes its EventSource *only* on
        ``event: end``; without it the browser reconnects every few
        seconds forever.
        """
        _login(client, existing_user)
        body = sse_driver(client, [fake_game("lobby"), None])
        assert "event: end" in body
        assert _data(body, "update")["type"] == "game-none"

    def test_events_are_ordered(
        self, client, app, existing_user, sse_driver, fake_game
    ):
        """The client must see snapshot, then update, then end."""
        _login(client, existing_user)
        body = sse_driver(client, [fake_game("lobby"), None])
        events = _events(body)
        assert events[0] == "snapshot"
        assert events.index("update") < events.index("end")

    def test_race_between_snapshot_and_poll_ends_the_stream(
        self, client, app, existing_user, sse_driver, fake_game
    ):
        """The stream must end even if the game vanishes mid-iteration.

        The generator takes a snapshot and then re-reads the game to
        check the expiry. If another device finished the game in between,
        the second read returns ``None`` while the snapshot still said
        "pending". The client must still receive ``event: end``:
        ``static/game_notify.js`` closes its EventSource *only* on that
        event, so a silent exit makes the browser reconnect forever.
        """
        _login(client, existing_user)
        body = sse_driver(client, [fake_game("lobby"), fake_game("lobby"), None])
        assert "event: snapshot" in body
        assert "event: end" in body, "the client must be told the stream ended"


class TestHeartbeat:
    """The idle heartbeat keeps proxies from closing the connection."""

    def test_heartbeat_after_seven_idle_polls(
        self, client, app, existing_user, sse_driver, fake_game
    ):
        """Seven unchanged polls produce one heartbeat comment."""
        _login(client, existing_user)
        body = sse_driver(client, [fake_game("lobby")] * 16 + [None])
        assert ": heartbeat" in body
        assert body.count(": heartbeat") == 1

    def test_status_change_resets_the_idle_counter(
        self, client, app, existing_user, sse_driver, fake_game
    ):
        """An update resets the idle counter, so no heartbeat is due."""
        _login(client, existing_user)
        body = sse_driver(
            client,
            [
                fake_game("lobby"),
                fake_game("lobby"),
                fake_game("active"),
            ]
            + [fake_game("active")] * 8
            + [None],
        )
        assert "event: update" in body
        assert ": heartbeat" not in body


class TestStreamTermination:
    """Every way the stream can end."""

    def test_no_game_ends_immediately(
        self, client, app, existing_user, sse_driver, fake_game
    ):
        """With no game the stream sends a snapshot then end."""
        _login(client, existing_user)
        body = sse_driver(client, [None])
        assert _events(body) == ["snapshot", "end"]
        assert _data(body, "end") == {}

    def test_expiry_grace_ends_the_stream(
        self, client, app, existing_user, sse_driver, fake_game
    ):
        """A game whose expiry is more than 30s past ends the stream."""
        _login(client, existing_user)
        body = sse_driver(client, [fake_game("lobby", expires_at=1.0)] * 3 + [None])
        assert "event: end" in body

    def test_client_disconnect_does_not_raise(
        self, client, app, existing_user, monkeypatch
    ):
        """Closing the response early must not leak an exception."""
        _login(client, existing_user)
        monkeypatch.setattr(routes_module.time, "sleep", lambda _s: None)
        response = client.get("/api/game/events", buffered=False)
        stream = response.response
        next(stream)
        assert stream.close() is None
        with pytest.raises(StopIteration):
            next(stream)

    def test_internal_error_ends_the_stream(
        self, client, app, existing_user, monkeypatch
    ):
        """A database failure must end the stream, not hang the worker."""
        _login(client, existing_user)

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(routes_module, "_get_live_game", _boom)
        monkeypatch.setattr(routes_module.time, "sleep", lambda _s: None)
        response = client.get("/api/game/events", buffered=False)
        chunks = []
        stream = response.response
        for _ in range(50):
            try:
                chunks.append(next(stream))
            except StopIteration:
                break
        body = b"".join(chunks).decode("utf-8", "replace")
        assert "event: end" in body

    def test_stream_never_raises_to_the_client(
        self, client, app, existing_user, monkeypatch
    ):
        """Even an exploding stream returns a 200 SSE response."""
        _login(client, existing_user)

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(routes_module, "_get_live_game", _boom)
        response = client.get("/api/game/events", buffered=False)
        assert response.status_code == 200
        assert response.content_type.startswith("text/event-stream")


class TestStreamHeaders:
    """The stream must be cache-free and proxy-friendly."""

    def test_no_cache_headers(self, client, app, existing_user):
        """Proxies must not buffer the stream."""
        _login(client, existing_user)
        resp = client.get("/api/game/events?once=1")
        assert resp.headers.get("Cache-Control") == "no-cache"
        assert resp.headers.get("X-Accel-Buffering") == "no"

    def test_requires_login(self, client, app):
        """An anonymous client must not open a stream."""
        resp = client.get("/api/game/events")
        assert resp.status_code in (302, 401)
