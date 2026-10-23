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

        with app.test_request_context(
            "/", environ_base={"REMOTE_ADDR": "10.0.0.5"}
        ):
            login_user(user)
            key = routes_module._quiz_cooldown_key()
            assert key == f"quiz:{user_id}:10.0.0.5"

    def test_key_uses_anonymous_for_a_missing_user(self, app, limiter):
        """Without a logged-in user the key falls back to ``anon``."""
        with app.test_request_context("/", environ_base={"REMOTE_ADDR": "10.0.0.5"}):
            assert routes_module._quiz_cooldown_key() == "quiz:anon:10.0.0.5"

    def test_key_outside_a_request_context_raises(self, app, limiter):
        """Reading ``request.remote_addr`` without a request is a RuntimeError."""
        with app.app_context():
            with pytest.raises(RuntimeError):
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
        assert second.get_json() == {
            "error": "Quiz cooling down. Wait a few seconds."
        }

    def test_rate_limit_does_not_spend_ollama_credits(
        self, client, app, existing_user, limiter, fake_ollama
    ):
        """A rate-limited call must never reach the model."""
        calls = fake_ollama(n=1)
        _login(client, existing_user)
        assert client.post("/api/quiz/generate", json={"num_questions": 1}).status_code == 200
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

    def test_second_start_inside_window_is_429(self, client, app, existing_user, limiter):
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
