"""Happy-path + form-validation tests for login and signup (Flask-Security-Too)."""

from app import User, db

# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------


class TestSignup:
    def test_register_page_loads(self, client):
        resp = client.get("/register")
        assert resp.status_code == 200
        assert b'name="register_user_form"' in resp.data
        assert b"Sign up" in resp.data

    def test_signup_success_redirects_home_and_creates_user(self, client, app):
        resp = client.post(
            "/register",
            data={
                "email": "newplayer@example.com",
                "password": "correct-horse-123",
                "password_confirm": "correct-horse-123",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"

        with app.app_context():
            user = User.query.filter_by(email="newplayer@example.com").one_or_none()
            assert user is not None
            # Password must be stored hashed, never plaintext.
            assert user.password != "correct-horse-123"

    def test_signup_logs_user_in(self, client):
        client.post(
            "/register",
            data={
                "email": "auto-login@example.com",
                "password": "correct-horse-123",
                "password_confirm": "correct-horse-123",
            },
        )
        # Newly registered user can reach the login-gated page.
        assert client.get("/gameplay").status_code == 200

    def test_signup_duplicate_email_rejected(self, client, app, existing_user):
        resp = client.post(
            "/register",
            data={
                "email": existing_user["email"],
                "password": "another-pass-123",
                "password_confirm": "another-pass-123",
            },
        )
        assert resp.status_code == 200  # re-rendered, not redirected
        with app.app_context():
            assert User.query.filter_by(email=existing_user["email"]).count() == 1

    def test_signup_password_mismatch_rejected(self, client, app):
        resp = client.post(
            "/register",
            data={
                "email": "mismatch@example.com",
                "password": "correct-horse-123",
                "password_confirm": "different-pass-123",
            },
        )
        assert resp.status_code == 200
        with app.app_context():
            assert User.query.filter_by(email="mismatch@example.com").count() == 0

    def test_signup_invalid_email_rejected(self, client, app):
        resp = client.post(
            "/register",
            data={
                "email": "not-an-email",
                "password": "correct-horse-123",
                "password_confirm": "correct-horse-123",
            },
        )
        assert resp.status_code == 200
        with app.app_context():
            assert User.query.filter_by(email="not-an-email").count() == 0


# ---------------------------------------------------------------------------
# Login / logout / access control
# ---------------------------------------------------------------------------


class TestLogin:
    def test_login_page_loads(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200
        assert b'name="login_user_form"' in resp.data
        assert b"Log in" in resp.data

    def test_login_success_redirects_home(self, client, existing_user):
        resp = client.post(
            "/login",
            data={
                "email": existing_user["email"],
                "password": existing_user["password"],
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"
        # Session is authenticated: gated page now reachable.
        assert client.get("/gameplay").status_code == 200

    def test_login_wrong_password_rejected(self, client, existing_user):
        resp = client.post(
            "/login",
            data={"email": existing_user["email"], "password": "wrong-pass-123"},
        )
        assert resp.status_code == 200
        assert client.get("/gameplay").status_code == 302

    def test_login_unknown_email_rejected(self, client):
        resp = client.post(
            "/login",
            data={"email": "nobody@example.com", "password": "correct-horse-123"},
        )
        assert resp.status_code == 200
        assert client.get("/gameplay").status_code == 302

    def test_gameplay_requires_login_and_honours_next(self, client):
        resp = client.get("/gameplay", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/login?next=")

    def test_logout_clears_session(self, client, existing_user):
        client.post(
            "/login",
            data={
                "email": existing_user["email"],
                "password": existing_user["password"],
            },
        )
        assert client.get("/gameplay").status_code == 200

        resp = client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"
        # Logged out again: gated page redirects to login.
        assert client.get("/gameplay").status_code == 302
