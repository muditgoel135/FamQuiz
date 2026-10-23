"""Tests for the Server-Sent Events stream (``/api/game/events``).

The stream is the only live-update channel between the family devices
and the shared lobby. It had a single test that only covered the
"no game -> end" path; every other branch (status change, heartbeat,
expiry, client disconnect, internal error) was unasserted.

The generator polls every 2 seconds, so every test here stubs the sleep
away and scripts the games the generator sees (see the ``sse_driver``
fixture in conftest.py).
"""

import json

import pytest

import routes as routes_module


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

    def test_snapshot_is_always_the_first_event(self, client, app, existing_user, sse_driver, fake_game):
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
            [fake_game("lobby"), fake_game("active"), fake_game("active"), fake_game("active"), None],
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

    def test_events_are_ordered(self, client, app, existing_user, sse_driver, fake_game):
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
