"""Recovery matrix: forgot/reset/change edge cases, redirects, locales."""

from app import User, db, mail


def _token(app, email):
    from flask_security.recoverable import generate_reset_password_token

    with app.app_context():
        user = User.query.filter_by(email=email).one()
        return generate_reset_password_token(user)


def _login(client, existing_user):
    client.post(
        "/login",
        data={
            "email": existing_user["email"],
            "password": existing_user["password"],
        },
    )


class TestForgotMatrix:
    def test_empty_invalid_nothing(self, client):
        for email in ("", "not-an-email"):
            with mail.record_messages() as outbox:
                resp = client.post("/reset", data={"email": email})
            assert resp.status_code == 200
            assert len(outbox) == 0

    def test_unknown_same_200(self, client):
        with mail.record_messages() as outbox:
            resp = client.post("/reset", data={"email": "nobody@example.com"})
        assert resp.status_code == 200
        assert len(outbox) == 0

    def test_existing_no_redirect(self, client, existing_user):
        with mail.record_messages() as outbox:
            resp = client.post(
                "/reset", data={"email": existing_user["email"]},
                follow_redirects=False,
            )
        assert resp.status_code == 200
        assert len(outbox) == 1
        assert existing_user["email"] in outbox[0].recipients

    def test_per_locale(self, client):
        assert "Restablece" in client.get("/reset?lang=es").data.decode() or \
            "Enviar" in client.get("/reset?lang=es").data.decode()
        assert 'lang="hi"' in client.get("/reset?lang=hi").data.decode()
        assert 'lang="zh-Hans"' in client.get("/reset?lang=zh_Hans").data.decode()


class TestResetMatrix:
    def test_invalid_pins_forgot(self, client):
        resp = client.get("/reset/not-a-real-token", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/reset")

    def test_tampered_redirects(self, client, app, existing_user):
        token = _token(app, existing_user["email"]) + "x"
        resp = client.get(f"/reset/{token}", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/reset")

    def test_empty_rejected(self, client, app, existing_user):
        token = _token(app, existing_user["email"])
        resp = client.post(
            f"/reset/{token}", data={"password": "", "password_confirm": ""}
        )
        assert resp.status_code == 200
        # old password still works
        assert client.post(
            "/login",
            data={
                "email": existing_user["email"],
                "password": existing_user["password"],
            },
        ).status_code == 302

    def test_mismatch_rejected(self, client, app, existing_user):
        token = _token(app, existing_user["email"])
        resp = client.post(
            f"/reset/{token}",
            data={"password": "a12345678", "password_confirm": "b12345678"},
        )
        assert resp.status_code == 200

    def test_success_home_notice(self, client, app, existing_user):
        token = _token(app, existing_user["email"])
        with mail.record_messages() as outbox:
            resp = client.post(
                f"/reset/{token}",
                data={"password": "brand-new-456", "password_confirm": "brand-new-456"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"
        assert len(outbox) == 1

    def test_token_single_use(self, client, app, existing_user):
        token = _token(app, existing_user["email"])
        client.post(
            f"/reset/{token}",
            data={"password": "one-time-123", "password_confirm": "one-time-123"},
        )
        resp = client.post(
            f"/reset/{token}",
            data={"password": "second-12345", "password_confirm": "second-12345"},
            follow_redirects=False,
        )
        # Reuse must not succeed a second time.
        assert resp.status_code in (200, 302)
        client.get("/logout")
        # First new password works.
        assert client.post(
            "/login",
            data={"email": existing_user["email"], "password": "one-time-123"},
            follow_redirects=False,
        ).status_code == 302

    def test_per_locale(self, client, app, existing_user):
        token = _token(app, existing_user["email"])
        assert "nueva" in client.get(f"/reset/{token}?lang=es").data.decode() or \
            "Restablecer" in client.get(f"/reset/{token}?lang=es").data.decode()


class TestChangeMatrix:
    def test_requires_login(self, client):
        resp = client.get("/change", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
        assert client.post("/change", data={}).status_code == 302

    def test_empty_rejected(self, client, existing_user):
        _login(client, existing_user)
        resp = client.post(
            "/change",
            data={"password": existing_user["password"], "new_password": "",
                  "new_password_confirm": ""},
        )
        assert resp.status_code == 200

    def test_mismatch_rejected(self, client, existing_user):
        _login(client, existing_user)
        resp = client.post(
            "/change",
            data={"password": existing_user["password"], "new_password": "a12345678",
                  "new_password_confirm": "b12345678"},
        )
        assert resp.status_code == 200

    def test_wrong_no_mail(self, client, existing_user):
        _login(client, existing_user)
        with mail.record_messages() as outbox:
            resp = client.post(
                "/change",
                data={"password": "wrong-123", "new_password": "n12345678",
                      "new_password_confirm": "n12345678"},
            )
        assert resp.status_code == 200
        assert len(outbox) == 0

    def test_success_home_notice(self, client, existing_user):
        _login(client, existing_user)
        with mail.record_messages() as outbox:
            resp = client.post(
                "/change",
                data={"password": existing_user["password"],
                      "new_password": "changed-789",
                      "new_password_confirm": "changed-789"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"
        assert len(outbox) == 1
        client.get("/logout")
        assert client.post(
            "/login",
            data={"email": existing_user["email"], "password": "changed-789"},
            follow_redirects=False,
        ).status_code == 302

    def test_per_locale(self, client, existing_user):
        _login(client, existing_user)
        assert "Cambiar" in client.get("/change?lang=es").data.decode() or \
            "contrase" in client.get("/change?lang=es").data.decode()
