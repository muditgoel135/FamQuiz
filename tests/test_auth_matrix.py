"""Auth validation matrix: signup/login edge cases, redirects, locales."""

from app import User


def _count(app, email):
    with app.app_context():
        return User.query.filter_by(email=email).count()


class TestSignupMatrix:
    def test_empty_email(self, client, app):
        resp = client.post(
            "/register",
            data={"email": "", "password": "correct-horse-123",
                  "password_confirm": "correct-horse-123"},
        )
        assert resp.status_code == 200
        assert _count(app, "") == 0

    def test_empty_password(self, client, app):
        resp = client.post(
            "/register",
            data={"email": "e@example.com", "password": "",
                  "password_confirm": ""},
        )
        assert resp.status_code == 200
        assert _count(app, "e@example.com") == 0

    def test_duplicate_case(self, client, app, existing_user):
        resp = client.post(
            "/register",
            data={
                "email": existing_user["email"].upper(),
                "password": "another-pass-123",
                "password_confirm": "another-pass-123",
            },
        )
        assert resp.status_code == 200
        with app.app_context():
            assert User.query.filter_by(email=existing_user["email"]).count() == 1

    def test_mismatch_error_block(self, client, app):
        resp = client.post(
            "/register",
            data={
                "email": "m2@example.com",
                "password": "correct-horse-123",
                "password_confirm": "different-123",
            },
        )
        assert resp.status_code == 200
        assert _count(app, "m2@example.com") == 0
        assert b"auth-error" in resp.data or b"password" in resp.data.lower()

    def test_success_pins_home(self, client, app):
        resp = client.post(
            "/register",
            data={
                "email": "pin@example.com",
                "password": "correct-horse-123",
                "password_confirm": "correct-horse-123",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"
        with app.app_context():
            user = User.query.filter_by(email="pin@example.com").one()
            assert user.password != "correct-horse-123"
        assert client.get("/gameplay").status_code == 200

    def test_per_locale(self, client):
        assert "Registrarse" in client.get("/register?lang=es").data.decode() or \
            "Regístrate" in client.get("/register?lang=es").data.decode() or \
            "Sign up" in client.get("/register?lang=es").data.decode()
        assert 'lang="es"' in client.get("/register?lang=es").data.decode()
        assert 'lang="hi"' in client.get("/register?lang=hi").data.decode()
        assert 'lang="zh-Hans"' in client.get("/register?lang=zh_Hans").data.decode()


class TestLoginMatrix:
    def test_empty_rejected(self, client):
        assert client.post("/login", data={"email": "", "password": ""}).status_code == 200
        assert client.get("/gameplay").status_code == 302

    def test_invalid_format(self, client):
        assert client.post(
            "/login", data={"email": "not-an-email", "password": "x"}
        ).status_code == 200

    def test_success_home(self, client, existing_user):
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

    def test_next_settings_change(self, client):
        resp = client.get("/settings", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/login?next=")
        assert "settings" in resp.headers["Location"]
        resp = client.get("/change", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_logout_anon(self, client):
        resp = client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"

    def test_per_locale(self, client):
        assert "Iniciar sesi" in client.get("/login?lang=es").data.decode()
        assert 'lang="hi"' in client.get("/login?lang=hi").data.decode()
        assert 'lang="zh-Hans"' in client.get("/login?lang=zh_Hans").data.decode()
