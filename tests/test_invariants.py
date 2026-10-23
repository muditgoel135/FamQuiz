"""
Regression tests for the invariants the app must never break.

Each test here corresponds to a defect that was found by auditing the
suite: a hole in the tests let the defect ship. They are deliberately
written from the outside (HTTP + database) so they keep working when
the implementation changes.
"""

import json
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import text

import app as app_module
import routes as routes_module
from app import FinishedQuiz, GameSession, User, db


def _login(client, existing_user):
    """Log a user in through the real login form."""
    client.post(
        "/login",
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


def _quiz_json(n=1):
    """Return a canned quiz payload."""
    return json.dumps(
        {
            "questions": [
                {
                    "question": f"Question {i}?",
                    "options": [f"Q{i} A", f"Q{i} B", f"Q{i} C", f"Q{i} D"],
                    "answer_index": 0,
                }
                for i in range(n)
            ]
        }
    )


def _start_quiz(client, monkeypatch, n=1):
    """Generate a quiz with a stubbed model."""
    fake = SimpleNamespace(
        chat=lambda **kwargs: SimpleNamespace(
            message=SimpleNamespace(content=_quiz_json(n))
        )
    )
    monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
    monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
    resp = client.post("/api/quiz/generate", json={"num_questions": n})
    assert resp.status_code == 200, resp.data.decode()[:300]
    return resp.get_json()


def _play_through(client):
    """Answer the only question and finish the quiz."""
    client.get("/api/quiz/state")
    with client.session_transaction() as sess:
        sess["quiz"]["started_at"] = time.time() - 1
        sess.modified = True
    client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
    return client.post("/api/quiz/finish")


class TestFinishIsCountedOnce:
    """A game must be banked exactly once, even with two tabs open."""

    def test_replayed_finish_does_not_count_twice(
        self, client, app, existing_user, monkeypatch
    ):
        """A stale session cookie must not bank the same game twice.

        Two browser tabs hold two copies of the session cookie. When both
        tabs finish the same game, the second one used to increment
        ``total_games_played`` and ``total_wins`` again, corrupting the
        leaderboard.
        """
        _login(client, existing_user)
        _start_quiz(client, monkeypatch, n=1)
        stale_cookie = client._cookies["localhost", "/", "session"].value

        first = _play_through(client)
        assert first.status_code == 200
        summary = first.get_json()
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.total_games_played == 1
            assert user.total_wins == 1

        # The second tab still holds the pre-finish cookie.
        client._cookies["localhost", "/", "session"].value = stale_cookie
        second = _play_through(client)
        assert second.status_code == 200
        assert second.get_json() == summary
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.total_games_played == 1, "the game was counted twice"
            assert user.total_wins == 1, "the win was counted twice"

    def test_each_new_quiz_is_counted_separately(
        self, client, app, existing_user, monkeypatch
    ):
        """Two different games must both count."""
        _login(client, existing_user)
        _start_quiz(client, monkeypatch, n=1)
        assert _play_through(client).status_code == 200
        _start_quiz(client, monkeypatch, n=1)
        assert _play_through(client).status_code == 200
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.total_games_played == 2
            assert user.total_wins == 2

    def test_a_banked_quiz_is_recorded_server_side(
        self, client, app, existing_user, monkeypatch
    ):
        """The idempotency key lives in the database, not in the cookie."""
        _login(client, existing_user)
        _start_quiz(client, monkeypatch, n=1)
        _play_through(client)
        with app.app_context():
            rows = FinishedQuiz.query.all()
            assert len(rows) == 1
            assert rows[0].user_id is not None
            assert rows[0].summary

    def test_erase_data_does_not_unlock_a_replay(
        self, client, app, existing_user, monkeypatch
    ):
        """Erasing the statistics must not allow the same game to count again."""
        _login(client, existing_user)
        _start_quiz(client, monkeypatch, n=1)
        stale_cookie = client._cookies["localhost", "/", "session"].value
        _play_through(client)

        client.post("/api/account/erase-data")
        client._cookies["localhost", "/", "session"].value = stale_cookie
        _play_through(client)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.total_games_played == 0


class TestSingleLiveGame:
    """Only one family-wide lobby may exist at a time."""

    def test_index_is_created(self, app):
        """The database itself enforces the invariant."""
        with app.app_context():
            indexes = db.session.execute(
                text("PRAGMA index_list('game_session')")
            ).fetchall()
            names = {row[1] for row in indexes}
            assert "ix_game_session_single_live" in names

    def test_two_concurrent_starts_create_one_lobby(
        self, client, app, existing_user, monkeypatch
    ):
        """Two devices pressing Start at the same time make one lobby."""
        _login(client, existing_user)
        # Widen the check-then-act window between the two requests.
        monkeypatch.setattr(routes_module, "_get_live_game", lambda: None)
        first = client.post("/api/game/start", json={"lobby_seconds": 60})
        second = client.post("/api/game/start", json={"lobby_seconds": 60})
        assert first.status_code == 201
        assert second.status_code == 409
        assert second.get_json()["error"] == "A game is already live."
        with app.app_context():
            live = GameSession.query.filter(
                GameSession.status.in_(["lobby", "active"])
            ).all()
            assert len(live) == 1

    def test_live_games_are_rejected_by_the_database(self, app):
        """A second live row cannot even be inserted directly."""
        from sqlalchemy.exc import IntegrityError

        now = time.time()
        with app.app_context():
            db.session.add(
                GameSession(
                    status="lobby",
                    num_questions=4,
                    difficulty="easy",
                    powerups_enabled=True,
                    lobby_seconds=60,
                    starts_at=now + 60,
                    expires_at=now + 400,
                    created_at=now,
                )
            )
            db.session.commit()
            db.session.add(
                GameSession(
                    status="active",
                    num_questions=4,
                    difficulty="easy",
                    powerups_enabled=True,
                    lobby_seconds=60,
                    starts_at=now + 60,
                    expires_at=now + 400,
                    created_at=now,
                )
            )
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_finished_games_do_not_block_a_new_lobby(self, client, app, existing_user):
        """Only *live* games are limited to one."""
        _login(client, existing_user)
        started = client.post("/api/game/start", json={"lobby_seconds": 60})
        assert started.status_code == 201
        game_id = started.get_json()["game"]["id"]
        with app.app_context():
            game = db.session.get(GameSession, game_id)
            game.status = "finished"
            db.session.commit()
        again = client.post("/api/game/start", json={"lobby_seconds": 60})
        assert again.status_code == 201


class TestNoDanglingReferences:
    """Deleting an account must not leave rows pointing at nothing."""

    def test_created_by_id_is_cleared(self, client, app, existing_user):
        """The lobby keeps its history but forgets the deleted user."""
        _login(client, existing_user)
        started = client.post("/api/game/start", json={"lobby_seconds": 60})
        game_id = started.get_json()["game"]["id"]
        assert client.delete("/api/account").status_code == 200
        with app.app_context():
            game = db.session.get(GameSession, game_id)
            assert game is not None
            assert game.created_by_id is None
            assert game.status == "cancelled"

    def test_banked_quizzes_survive_the_user(
        self, client, app, existing_user, monkeypatch
    ):
        """The ledger must not block the account deletion."""
        _login(client, existing_user)
        _start_quiz(client, monkeypatch, n=1)
        _play_through(client)
        assert client.delete("/api/account").status_code == 200
        with app.app_context():
            assert FinishedQuiz.query.count() == 1
            assert FinishedQuiz.query.first().user_id is None
            assert (
                User.query.filter_by(email=existing_user["email"]).one_or_none() is None
            )


class TestMailFailureIsSurvivable:
    """A broken SMTP account must not break the password flows."""

    def test_reset_does_not_500_when_smtp_fails(
        self, app, existing_user, monkeypatch, tmp_path
    ):
        """The player sees the generic "email sent" page, not a crash."""
        import smtplib

        from app import create_app

        flask_app = create_app(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'mail.db'}",
                # Flask-Mail snapshots this at init_app, so it must be set
                # here rather than flipped afterwards.
                "MAIL_SUPPRESS_SEND": False,
            }
        )
        with flask_app.app_context():
            from flask_security.utils import hash_password

            from app import user_datastore

            user_datastore.create_user(
                email=existing_user["email"],
                password=hash_password(existing_user["password"]),
            )
            db.session.commit()

        def _boom(self, *args, **kwargs):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

        monkeypatch.setattr("flask_mail.Connection.configure_host", _boom)
        client = flask_app.test_client()
        resp = client.post("/reset", data={"email": existing_user["email"]})
        assert resp.status_code == 200
        assert b"Traceback" not in resp.data

    def test_change_password_does_not_500_when_smtp_fails(
        self, app, existing_user, monkeypatch, tmp_path
    ):
        """The same protection applies to the change-password notice."""
        import smtplib

        from app import create_app

        flask_app = create_app(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'mail2.db'}",
                "MAIL_SUPPRESS_SEND": False,
            }
        )
        with flask_app.app_context():
            from flask_security.utils import hash_password

            from app import user_datastore

            user_datastore.create_user(
                email=existing_user["email"],
                password=hash_password(existing_user["password"]),
            )
            db.session.commit()

        def _boom(self, *args, **kwargs):
            raise smtplib.SMTPConnectError(421, b"cannot connect")

        monkeypatch.setattr("flask_mail.Connection.configure_host", _boom)
        client = flask_app.test_client()
        client.post(
            "/login",
            data={
                "email": existing_user["email"],
                "password": existing_user["password"],
            },
        )
        resp = client.post(
            "/change",
            data={
                "password": existing_user["password"],
                "new_password": "a-brand-new-password",
                "new_password_confirm": "a-brand-new-password",
            },
        )
        assert resp.status_code in (200, 302)
        assert b"Traceback" not in resp.data


class TestStatusPollIsReadOnly:
    """Polling for the lobby state must not write to the database."""

    def test_poll_does_not_commit_when_nothing_changed(
        self, client, app, existing_user, monkeypatch
    ):
        """A steady-state poll must not touch the database."""
        _login(client, existing_user)
        assert (
            client.post("/api/game/start", json={"lobby_seconds": 60}).status_code
            == 201
        )

        commits = []
        original = db.session.commit

        def _counted():
            commits.append(1)
            return original()

        monkeypatch.setattr(db.session, "commit", _counted)
        client.get("/api/game/status")
        assert commits == []


class TestStartupRepairs:
    """The app must repair a database left behind by an older version."""

    def test_extra_live_games_are_cancelled_at_startup(self, app, tmp_path):
        """Two live lobbies from a race must not survive a restart.

        The index makes the state impossible going forward, but a
        database created by an older version can still hold it, so the
        startup has to repair it.
        """
        from sqlalchemy import text

        from app import create_app

        database = tmp_path / "repair.db"
        first = create_app(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database}",
            }
        )
        now = time.time()
        with first.app_context():
            # Drop the index to recreate the state an older version
            # could leave behind.
            db.session.execute(text("DROP INDEX IF EXISTS ix_game_session_single_live"))
            db.session.commit()
            for _ in range(2):
                db.session.add(
                    GameSession(
                        status="lobby",
                        num_questions=4,
                        difficulty="easy",
                        powerups_enabled=True,
                        lobby_seconds=60,
                        starts_at=now + 60,
                        expires_at=now + 400,
                        created_at=now,
                    )
                )
            db.session.commit()
            assert GameSession.query.count() == 2
        with first.app_context():
            db.session.remove()
            db.engine.dispose()

        # A fresh boot on the same database must keep only the newest.
        second = create_app(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database}",
            }
        )
        with second.app_context():
            live = GameSession.query.filter(
                GameSession.status.in_(["lobby", "active"])
            ).all()
            assert len(live) == 1, "the duplicate lobby was not cleaned up"
            indexes = db.session.execute(
                text("PRAGMA index_list('game_session')")
            ).fetchall()
            assert "ix_game_session_single_live" in {row[1] for row in indexes}


class TestFenceStripping:
    """The model sometimes wraps its JSON in Markdown fences."""

    def test_closing_fence_on_the_content_line(self):
        """A fence that shares the line with the content is stripped."""
        from app import strip_code_fences

        content = '```\n{"questions": []}```'
        assert strip_code_fences(content) == '{"questions": []}'

    def test_plain_fence(self):
        """The ordinary case still works."""
        from app import strip_code_fences

        content = '```json\n{"questions": []}\n```'
        assert strip_code_fences(content) == '{"questions": []}'


class TestStatusDotFallback:
    """An unknown status must not break the leaderboard."""

    def test_unknown_status_is_offline(self, client, app, existing_user):
        """A custom status falls back to the offline dot."""
        from app import User

        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.status = "Some custom status"
            db.session.commit()
        html = client.get("/").get_data(as_text=True)
        assert "home-dot-offline" in html


# ==== merged from test_db_integrity.py ====
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


class TestIntegrityErrors:
    def test_duplicate_email(self, app, existing_user):
        from flask_security.utils import hash_password
        from sqlalchemy.exc import IntegrityError

        from app import User, user_datastore

        with app.app_context():
            user_datastore.create_user(
                email=existing_user["email"], password=hash_password("y" * 12)
            )
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
            assert User.query.filter_by(email=existing_user["email"]).count() == 1
            assert db.session.is_active

    def test_duplicate_uniquifier(self, app, existing_user):
        from sqlalchemy.exc import IntegrityError

        from app import User

        with app.app_context():
            existing = User.query.filter_by(email=existing_user["email"]).one()
            db.session.add(
                User(
                    email="dup2@example.com",
                    password="x",
                    fs_uniquifier=existing.fs_uniquifier,
                )
            )
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_duplicate_role(self, app):
        from sqlalchemy.exc import IntegrityError

        from app import Role

        with app.app_context():
            db.session.add(Role(name="dupr", description="a"))
            db.session.commit()
            db.session.add(Role(name="dupr", description="b"))
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
            assert Role.query.filter_by(name="dupr").count() == 1

    def test_null_email(self, app):
        from sqlalchemy.exc import IntegrityError

        from app import User

        with app.app_context():
            db.session.add(User(email=None, password="x"))
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()


class TestDeleteWithLobby:
    def test_starter_active_cancels(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 10})
        with app.app_context():
            game = GameSession.query.order_by(GameSession.id.desc()).first()
            game.starts_at = time.time() - 1
            db.session.commit()
            gid = game.id
        assert client.delete("/api/account").get_json() == {"ok": True}
        with app.app_context():
            assert db.session.get(GameSession, gid).status == "cancelled"

    def test_nonstarter_leaves_live(self, client, app, existing_user):
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        other = _second(app)
        second = app.test_client()
        second.post(
            "/login", data={"email": other["email"], "password": other["password"]}
        )
        assert second.delete("/api/account").get_json() == {"ok": True}
        assert (
            client.get("/api/game/status").get_json()["active_game"]["status"]
            == "lobby"
        )
        assert client.post("/api/game/cancel").status_code == 200

    def test_roles_cleanup(self, client, app, existing_user):
        from sqlalchemy import text

        from app import Role, User

        with app.app_context():
            role = Role(name="playerx", description="p")
            db.session.add(role)
            user = User.query.filter_by(email=existing_user["email"]).one()
            uid = user.id
            user.roles.append(role)
            db.session.commit()
        _login(client, existing_user)
        assert client.delete("/api/account").get_json() == {"ok": True}
        with app.app_context():
            assert User.query.filter_by(email=existing_user["email"]).count() == 0
            assert Role.query.filter_by(name="playerx").count() == 1
            rows = db.session.execute(
                text("SELECT * FROM roles_users WHERE user_id = :uid"),
                {"uid": uid},
            ).all()
            assert rows == []

    def test_other_survives(self, client, app, existing_user):
        from app import User

        other = _second(app)
        _login(client, existing_user)
        assert client.delete("/api/account").get_json() == {"ok": True}
        second = app.test_client()
        assert (
            second.post(
                "/login",
                data={"email": other["email"], "password": other["password"]},
                follow_redirects=False,
            ).status_code
            == 302
        )
        assert second.get("/gameplay").status_code == 200
        with app.app_context():
            assert User.query.filter_by(email=other["email"]).count() == 1

    def test_erase_preserves(self, client, app, existing_user):
        from app import User

        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        assert client.post("/api/account/erase-data").get_json() == {"ok": True}
        assert (
            client.get("/api/game/status").get_json()["active_game"]["status"]
            == "lobby"
        )
        with app.app_context():
            assert User.query.filter_by(email=existing_user["email"]).count() == 1


class TestSequentialStarter:
    def test_second_conflicts(self, client, app, existing_user):
        _login(client, existing_user)
        other = _second(app)
        second = app.test_client()
        second.post(
            "/login", data={"email": other["email"], "password": other["password"]}
        )
        r1 = client.post("/api/game/start", json={"lobby_seconds": 60})
        r2 = second.post("/api/game/start", json={"lobby_seconds": 60})
        assert sorted([r1.status_code, r2.status_code]) == [201, 409]
        with app.app_context():
            assert (
                GameSession.query.filter(
                    GameSession.status.in_(["lobby", "active"])
                ).count()
                == 1
            )


class TestForcedRollback:
    def test_start_boom(self, client, app, existing_user, monkeypatch):
        import pytest as _pytest

        _login(client, existing_user)

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(db.session, "commit", _boom)
        # TESTING propagates view exceptions: assert the raise, then that
        # the session recovers and the next request succeeds.
        with _pytest.raises(RuntimeError, match="db down"):
            client.post("/api/game/start", json={})
        monkeypatch.undo()
        with app.app_context():
            db.session.rollback()
            assert GameSession.query.count() == 0
        assert client.post("/api/game/start", json={}).status_code == 201

    def test_settings_boom_no_partial(self, client, app, existing_user, monkeypatch):
        import pytest as _pytest

        from app import User

        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.display_name = "Keep"
            db.session.commit()

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(db.session, "commit", _boom)
        with _pytest.raises(RuntimeError, match="db down"):
            client.post("/api/settings/save", json={"display_name": "New"})
        monkeypatch.undo()
        with app.app_context():
            db.session.rollback()
            assert (
                User.query.filter_by(email=existing_user["email"]).one().display_name
                == "Keep"
            )

    def test_expire_tolerates_boom(self, app, monkeypatch):
        import routes as routes_module

        now = time.time()
        with app.app_context():
            game = GameSession(status="lobby", starts_at=now - 1000, expires_at=now - 1)
            db.session.add(game)
            db.session.commit()

            def _boom():
                raise RuntimeError("db down")

            monkeypatch.setattr(db.session, "commit", _boom)
            routes_module._expire_stale_games()  # must not raise
