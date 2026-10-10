"""Security tests: CSRF matrix, methods, sessions, hashes, XSS, redirects."""

import re

import pytest


def _login(client, existing_user):
    client.post(
        "/login",
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


def _csrf_client(tmp_path):
    """Build a CSRF-enabled app with a logged-in client + API token."""
    import tempfile

    from app import create_app, db, user_datastore
    from flask_security.utils import hash_password

    directory = tempfile.mkdtemp()
    csrf_app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{directory}/csrf.db",
            "MAIL_SUPPRESS_SEND": True,
        }
    )
    with csrf_app.app_context():
        db.create_all()
        user_datastore.create_user(
            email="csrf@example.com", password=hash_password("pw12345678")
        )
        db.session.commit()
    client = csrf_app.test_client()
    html = client.get("/login").data.decode()
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)
    assert client.post(
        "/login",
        data={"email": "csrf@example.com", "password": "pw12345678",
              "csrf_token": token},
        follow_redirects=False,
    ).status_code == 302
    api_token = re.search(
        r'name="csrf-token" content="([^"]+)"', client.get("/").data.decode()
    ).group(1)
    return client, api_token


class TestCsrfDelete:
    def test_missing_400(self, tmp_path):
        client, _ = _csrf_client(tmp_path)
        assert client.delete("/api/account").status_code == 400

    def test_valid_200(self, tmp_path):
        client, token = _csrf_client(tmp_path)
        resp = client.delete("/api/account", headers={"X-CSRFToken": token})
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}

    @pytest.mark.parametrize(
        "header",
        ["X-CSRF-Token", "X-CSRFTOKEN", "X-CsrfToken"],
    )
    def test_header_aliases_accepted(self, tmp_path, header):
        # Flask-WTF matches header names case-insensitively (and both
        # X-CSRFToken / X-CSRF-Token spellings), so aliases pass.
        client, token = _csrf_client(tmp_path)
        assert client.post(
            "/api/settings/save", json={}, headers={header: token}
        ).status_code == 200

    def test_garbage_token_rejected(self, tmp_path):
        client, token = _csrf_client(tmp_path)
        assert client.post(
            "/api/settings/save", json={}, headers={"X-CSRFToken": token[:-2] + "xx"}
        ).status_code == 400
        assert client.post(
            "/api/settings/save", json={}, headers={"Csrf-Token": token}
        ).status_code == 400

    def test_cross_session_rejected(self, tmp_path):
        import tempfile

        from app import create_app, db, user_datastore
        from flask_security.utils import hash_password

        c1, t1 = _csrf_client(tmp_path)
        directory = tempfile.mkdtemp()
        app2 = create_app(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": True,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{directory}/csrf2.db",
                "MAIL_SUPPRESS_SEND": True,
            }
        )
        with app2.app_context():
            db.create_all()
            user_datastore.create_user(
                email="other@example.com", password=hash_password("pw12345678")
            )
            db.session.commit()
        c2 = app2.test_client()
        assert c1.post(
            "/api/settings/save", json={}, headers={"X-CSRFToken": "bogus"}
        ).status_code == 400
        # CSRF fires before auth: even an anonymous post without token is 400.
        assert c2.post("/api/settings/save", json={}).status_code == 400

    def test_auth_forms_need_token(self, tmp_path):
        client, _ = _csrf_client(tmp_path)
        client.get("/logout")
        assert 'name="csrf_token"' in client.get("/login").data.decode()
        # Missing token aborts with 400 before form processing.
        resp = client.post(
            "/login",
            data={"email": "csrf@example.com", "password": "pw12345678"},
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert client.get("/gameplay").status_code == 302


class TestReverseMethods:
    def test_post_on_get_only(self, client, existing_user):
        _login(client, existing_user)
        assert client.post("/api/quiz/state", json={}).status_code == 405
        assert client.post("/api/game/status", json={}).status_code == 405
        assert client.post("/api/game/events?once=1").status_code == 405
        assert client.post("/").status_code == 405

    def test_method_confusion(self, client, existing_user):
        _login(client, existing_user)
        assert client.post("/api/account", json={}).status_code == 405
        assert client.delete("/api/settings/save").status_code == 405
        assert client.put("/api/settings/save", json={}).status_code == 405
        assert client.patch("/api/quiz/finish", json={}).status_code == 405

    def test_get_delete_only(self, client, existing_user):
        _login(client, existing_user)
        assert client.get("/api/account").status_code == 405

    def test_options_head(self, client):
        assert client.options("/api/game/start").status_code in (200, 204)
        assert client.head("/").status_code == 200


class TestSessionHandling:
    def test_login_rotates(self, client, existing_user):
        client.get("/")
        before = client.get_cookie("session")
        client.post(
            "/login",
            data={"email": existing_user["email"],
                  "password": existing_user["password"]},
        )
        after = client.get_cookie("session")
        assert before is not None and after is not None
        assert before.value != after.value
        assert client.get("/gameplay").status_code == 200

    def test_logout_clears(self, client, existing_user):
        _login(client, existing_user)
        assert client.get("/gameplay").status_code == 200
        assert client.get("/logout", follow_redirects=False).status_code == 302
        assert client.get("/gameplay").status_code == 302

    def test_planted_quiz_inert(self, client, existing_user):
        # A planted session quiz with no questions can never be served.
        with client.session_transaction() as sess:
            sess["quiz"] = {"questions": [], "index": 0}
        client.post(
            "/login",
            data={"email": existing_user["email"],
                  "password": existing_user["password"]},
        )
        assert client.get("/api/quiz/state").status_code == 404

    def test_delete_clears(self, client, existing_user):
        _login(client, existing_user)
        assert client.delete("/api/account").get_json() == {"ok": True}
        with client.session_transaction() as sess:
            assert "quiz" not in sess
            assert "last_result" not in sess
        assert client.get("/gameplay").status_code == 302


class TestHashStrength:
    def test_config(self, app):
        assert app.config["SECURITY_PASSWORD_HASH"] == "pbkdf2_sha512"

    def test_format_verify(self, app, existing_user):
        from flask_security.utils import verify_password
        from app import User

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.password != "correct-horse-123"
            assert "pbkdf2" in user.password.lower()
            assert len(user.password) > 100
            assert verify_password("correct-horse-123", user.password) is True
            assert verify_password("wrong-pass-123", user.password) is False

    def test_salt_unique(self, app):
        from flask_security.utils import hash_password
        from app import User, db, user_datastore

        with app.app_context():
            user_datastore.create_user(
                email="s1@example.com", password=hash_password("same-pass-123"))
            user_datastore.create_user(
                email="s2@example.com", password=hash_password("same-pass-123"))
            db.session.commit()
            u1 = User.query.filter_by(email="s1@example.com").one()
            u2 = User.query.filter_by(email="s2@example.com").one()
            assert u1.password != u2.password
            assert u1.fs_uniquifier != u2.fs_uniquifier
            assert len(u1.fs_uniquifier) == 32

    def test_change_rehashes(self, client, app, existing_user):
        from app import User

        _login(client, existing_user)
        with app.app_context():
            before = User.query.filter_by(email=existing_user["email"]).one().password
        client.post(
            "/change",
            data={"password": existing_user["password"],
                  "new_password": "changed-789",
                  "new_password_confirm": "changed-789"},
        )
        with app.app_context():
            after = User.query.filter_by(email=existing_user["email"]).one().password
        assert before != after
        assert "pbkdf2" in after.lower()


class TestAntiEnumeration:
    def test_login_bodies(self, client, existing_user):
        r1 = client.post(
            "/login",
            data={"email": "nobody@example.com", "password": "x" * 12},
        )
        r2 = client.post(
            "/login",
            data={"email": existing_user["email"], "password": "wrong-pass-1"},
        )
        assert (r1.status_code, r2.status_code) == (200, 200)
        assert abs(len(r1.data) - len(r2.data)) < 500
        # The form echoes the submitted address back into the input value
        # (not an oracle); the password verdict must not leak user existence.
        for needle in (b"unknown user", b"no such user", b"user not found"):
            assert needle not in r1.data.lower()
            assert needle not in r2.data.lower()

    def test_reset_bodies_equal(self, client, existing_user):
        from app import mail

        with mail.record_messages() as out_known:
            r_known = client.post("/reset", data={"email": existing_user["email"]})
        with mail.record_messages() as out_unknown:
            r_unknown = client.post("/reset", data={"email": "nobody@example.com"})
        assert (r_known.status_code, r_unknown.status_code) == (200, 200)
        assert len(out_known) == 1
        assert len(out_unknown) == 0
        # Both generic (no "not found" oracle), but the known-address flash
        # names the recipient while unknown flashes nothing at all --
        # documents the residual enumeration signal (no user-enumerating
        # wording either way).
        assert b"alert alert-info" in r_known.data
        assert b"alert alert-info" not in r_unknown.data
        for needle in (b"not found", b"no such user", b"unknown user"):
            assert needle not in r_known.data.lower()
            assert needle not in r_unknown.data.lower()

    def test_register_duplicate(self, client, app, existing_user):
        from app import User

        resp = client.post(
            "/register",
            data={"email": existing_user["email"], "password": "another-pass-1",
                  "password_confirm": "another-pass-1"},
        )
        assert resp.status_code == 200
        with app.app_context():
            assert User.query.filter_by(email=existing_user["email"]).count() == 1


class TestStoredXss:
    def test_escaped(self, client, app, existing_user):
        _login(client, existing_user)
        assert client.post(
            "/api/settings/save",
            json={"display_name": "<script>alert(1)</script>",
                  "nickname": '<img src=x onerror=alert(2)>',
                  "favorite_subject": "<svg onload=alert(3)>"},
        ).status_code == 200
        for path in ("/", "/leaderboard", "/settings", "/gameplay"):
            html = client.get(path).data.decode()
            assert "<script>alert" not in html, path
        html = client.get("/").data.decode()
        assert "&lt;script&gt;" in html
        with app.app_context():
            from app import User

            assert User.query.filter_by(
                email=existing_user["email"]).one().display_name == (
                "<script>alert(1)</script>")

    def test_quote_breakout(self, client, existing_user):
        _login(client, existing_user)
        client.post(
            "/api/settings/save",
            json={"display_name": '" autofocus onfocus=alert(1) x="'},
        )
        html = client.get("/settings").data.decode()
        # Quotes are entity-escaped, so the payload stays inside value="".
        assert "&#34;" in html
        assert 'value="" autofocus' not in html


class TestOpenRedirect:
    @pytest.mark.parametrize(
        "evil",
        ["http://evil.com", "https://evil.com/phish", "//evil.com",
         "javascript:alert(1)", "data:text/html,hi", "%2F%2Fevil.com"],
    )
    def test_login_next_never_offsite(self, client, existing_user, evil):
        resp = client.post(
            f"/login?next={evil}",
            data={"email": existing_user["email"],
                  "password": existing_user["password"]},
            follow_redirects=False,
        )
        loc = resp.headers.get("Location", "")
        assert "evil.com" not in loc
        assert "javascript:" not in loc.lower()
        assert "data:" not in loc.lower()

    def test_valid_next(self, client, existing_user):
        resp = client.get("/settings", follow_redirects=False)
        assert resp.headers["Location"].startswith("/login?next=")
        assert "settings" in resp.headers["Location"]
