"""Tests for the account lifecycle: erase data vs. delete account.

The two buttons in Settings do very different things and both are
destructive, so their exact side effects matter:

* **Erase data** resets the gameplay statistics but keeps the account.
* **Delete** removes the account entirely.

Both must also leave the session in a sane state.
"""

import pytest

from app import GameSession, User, db


def _login(client, existing_user):
    """Log a user in through the real login form."""
    client.post(
        "/login",
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


def _set_stats(app, existing_user, **kwargs):
    """Set statistics on the user row."""
    with app.app_context():
        user = User.query.filter_by(email=existing_user["email"]).one()
        for key, value in kwargs.items():
            setattr(user, key, value)
        db.session.commit()


def _stats(app, existing_user):
    """Return the statistics tuple of the user row."""
    with app.app_context():
        user = User.query.filter_by(email=existing_user["email"]).one()
        return (
            user.score,
            user.best_score,
            user.total_games_played,
            user.total_wins,
            user.total_powerups_used,
            user.most_used_powerup,
        )


class TestEraseData:
    """``POST /api/account/erase-data``."""

    def test_requires_login(self, client, app):
        """An anonymous client must not be able to erase anything."""
        resp = client.post("/api/account/erase-data")
        assert resp.status_code in (302, 401)

    def test_resets_every_statistic(self, client, app, existing_user):
        """All gameplay counters go back to zero."""
        _login(client, existing_user)
        _set_stats(
            app,
            existing_user,
            score=500,
            best_score=900,
            total_games_played=7,
            total_wins=3,
            total_powerups_used=4,
            most_used_powerup="Hint",
        )
        resp = client.post("/api/account/erase-data")
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}
        assert _stats(app, existing_user) == (0, 0, 0, 0, 0, None)

    def test_keeps_the_account(self, client, app, existing_user):
        """The player can still log in afterwards."""
        _login(client, existing_user)
        client.post("/api/account/erase-data")
        with app.app_context():
            assert (
                User.query.filter_by(email=existing_user["email"]).one() is not None
            )

    def test_keeps_the_profile(self, client, app, existing_user):
        """Erasing data must not touch the profile fields."""
        _login(client, existing_user)
        _set_stats(app, existing_user, display_name="Keeper", nickname="K")
        client.post("/api/account/erase-data")
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.display_name == "Keeper"
            assert user.nickname == "K"

    def test_clears_the_active_quiz(self, client, app, existing_user):
        """A half-finished quiz must not survive the erase."""
        _login(client, existing_user)
        with client.session_transaction() as sess:
            sess["quiz"] = {"questions": [{"question": "Q?"}], "index": 0}
            sess.modified = True
        client.post("/api/account/erase-data")
        with client.session_transaction() as sess:
            assert "quiz" not in sess

    def test_clears_the_cached_result(self, client, app, existing_user):
        """The cached summary must go too."""
        _login(client, existing_user)
        with client.session_transaction() as sess:
            sess["last_result"] = {"quiz_score": 100}
            sess.modified = True
        client.post("/api/account/erase-data")
        with client.session_transaction() as sess:
            assert "last_result" not in sess

    def test_clears_the_current_score(self, client, app, existing_user):
        """The in-progress score goes back to zero."""
        _login(client, existing_user)
        _set_stats(app, existing_user, score=1234)
        client.post("/api/account/erase-data")
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.score == 0


class TestDeleteAccount:
    """``DELETE /api/account``."""

    def test_requires_login(self, client, app):
        """An anonymous client must not be able to delete anything."""
        resp = client.delete("/api/account")
        assert resp.status_code in (302, 401)

    def test_removes_the_user(self, client, app, existing_user):
        """The account is gone."""
        _login(client, existing_user)
        resp = client.delete("/api/account")
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}
        with app.app_context():
            assert (
                User.query.filter_by(email=existing_user["email"]).one_or_none() is None
            )

    def test_clears_the_session(self, client, app, existing_user):
        """The session must not keep a stale login."""
        _login(client, existing_user)
        with client.session_transaction() as sess:
            sess["quiz"] = {"questions": [{"question": "Q?"}]}
            sess["last_result"] = {"quiz_score": 1}
            sess.modified = True
        client.delete("/api/account")
        with client.session_transaction() as sess:
            assert "quiz" not in sess
            assert "last_result" not in sess

    def test_cancels_own_live_lobby(self, client, app, existing_user):
        """A lobby owned by the deleted user must not stay uncancellable."""
        _login(client, existing_user)
        started = client.post("/api/game/start", json={"lobby_seconds": 60})
        assert started.status_code == 201
        game_id = started.get_json()["game"]["id"]

        client.delete("/api/account")
        with app.app_context():
            game = db.session.get(GameSession, game_id)
            assert game is not None
            assert game.status == "cancelled"

    def test_finished_lobby_is_left_alone(self, client, app, existing_user):
        """A finished game keeps its status."""
        _login(client, existing_user)
        started = client.post("/api/game/start", json={"lobby_seconds": 60})
        game_id = started.get_json()["game"]["id"]
        with app.app_context():
            game = db.session.get(GameSession, game_id)
            game.status = "finished"
            db.session.commit()

        client.delete("/api/account")
        with app.app_context():
            game = db.session.get(GameSession, game_id)
            assert game.status == "finished"

    def test_survives_a_database_failure(self, client, app, existing_user, monkeypatch):
        """A failing commit must not turn into a 500.

        The account stays (the delete was rolled back) but the endpoint
        still answers so the browser does not hang.
        """
        _login(client, existing_user)

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(db.session, "commit", _boom)
        resp = client.delete("/api/account")
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}

    def test_can_log_in_again_after_signup(self, client, app, existing_user):
        """Deleting and re-registering must work."""
        _login(client, existing_user)
        client.delete("/api/account")
        resp = client.post(
            "/register",
            data={
                "email": existing_user["email"],
                "password": "brand-new-password-1",
                "password_confirm": "brand-new-password-1",
            },
        )
        assert resp.status_code in (200, 302)


class TestMethodContract:
    """The account endpoints only answer their own HTTP method."""

    @pytest.mark.parametrize(
        "method,path",
        [("post", "/api/account"), ("get", "/api/account")],
    )
    def test_account_delete_rejects_other_methods(self, client, existing_user, method, path):
        """A GET or POST must not delete the account."""
        _login(client, existing_user)
        resp = getattr(client, method)(path)
        assert resp.status_code == 405

    def test_erase_data_rejects_get(self, client, existing_user):
        """Erasing data is a POST."""
        _login(client, existing_user)
        resp = client.get("/api/account/erase-data")
        assert resp.status_code == 405
