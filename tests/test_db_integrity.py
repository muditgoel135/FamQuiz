"""DB integrity: unique constraints, delete cascades, forced rollbacks."""

import time

import pytest

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


class TestIntegrityErrors:
    def test_duplicate_email(self, app, existing_user):
        from sqlalchemy.exc import IntegrityError
        from flask_security.utils import hash_password
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
            db.session.add(User(email="dup2@example.com", password="x",
                                fs_uniquifier=existing.fs_uniquifier))
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
        second.post("/login", data={"email": other["email"],
                                    "password": other["password"]})
        assert second.delete("/api/account").get_json() == {"ok": True}
        assert client.get("/api/game/status").get_json()["active_game"][
            "status"] == "lobby"
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
        assert second.post(
            "/login", data={"email": other["email"], "password": other["password"]},
            follow_redirects=False,
        ).status_code == 302
        assert second.get("/gameplay").status_code == 200
        with app.app_context():
            assert User.query.filter_by(email=other["email"]).count() == 1

    def test_erase_preserves(self, client, app, existing_user):
        from app import User

        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        assert client.post("/api/account/erase-data").get_json() == {"ok": True}
        assert client.get("/api/game/status").get_json()["active_game"][
            "status"] == "lobby"
        with app.app_context():
            assert User.query.filter_by(email=existing_user["email"]).count() == 1


class TestSequentialStarter:
    def test_second_conflicts(self, client, app, existing_user):
        _login(client, existing_user)
        other = _second(app)
        second = app.test_client()
        second.post("/login", data={"email": other["email"],
                                    "password": other["password"]})
        r1 = client.post("/api/game/start", json={"lobby_seconds": 60})
        r2 = second.post("/api/game/start", json={"lobby_seconds": 60})
        assert sorted([r1.status_code, r2.status_code]) == [201, 409]
        with app.app_context():
            assert GameSession.query.filter(
                GameSession.status.in_(["lobby", "active"])
            ).count() == 1


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
            assert User.query.filter_by(
                email=existing_user["email"]).one().display_name == "Keep"

    def test_expire_tolerates_boom(self, app, monkeypatch):
        import routes as routes_module

        now = time.time()
        with app.app_context():
            game = GameSession(status="lobby", starts_at=now - 1000,
                               expires_at=now - 1)
            db.session.add(game)
            db.session.commit()

            def _boom():
                raise RuntimeError("db down")

            monkeypatch.setattr(db.session, "commit", _boom)
            routes_module._expire_stale_games()  # must not raise
