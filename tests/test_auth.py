"""Happy-path + form-validation tests for login and signup (Flask-Security-Too)."""

from app import User, db, mail

# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------


class TestSignup:
    def test_register_page_loads(self, client):
        """
        Verify register page loads.

        :param client: The client fixture.
        """

        resp = client.get("/register")
        assert resp.status_code == 200
        assert b'name="register_user_form"' in resp.data
        assert b"Sign up" in resp.data

    def test_signup_success_redirects_home_and_creates_user(self, client, app):
        """
        Verify signup success redirects home and creates user.

        :param client: The client fixture.
        :param app: The app fixture.
        """

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
        """
        Verify signup logs user in.

        :param client: The client fixture.
        """

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
        """
        Verify signup duplicate email rejected.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """

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
        """
        Verify signup password mismatch rejected.

        :param client: The client fixture.
        :param app: The app fixture.
        """

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
        """
        Verify signup invalid email rejected.

        :param client: The client fixture.
        :param app: The app fixture.
        """

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
        """
        Verify login page loads.

        :param client: The client fixture.
        """

        resp = client.get("/login")
        assert resp.status_code == 200
        assert b'name="login_user_form"' in resp.data
        assert b"Log in" in resp.data

    def test_login_success_redirects_home(self, client, existing_user):
        """
        Verify login success redirects home.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """

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
        """
        Verify login wrong password rejected.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """

        resp = client.post(
            "/login",
            data={"email": existing_user["email"], "password": "wrong-pass-123"},
        )
        assert resp.status_code == 200
        assert client.get("/gameplay").status_code == 302

    def test_login_unknown_email_rejected(self, client):
        """
        Verify login unknown email rejected.

        :param client: The client fixture.
        """

        resp = client.post(
            "/login",
            data={"email": "nobody@example.com", "password": "correct-horse-123"},
        )
        assert resp.status_code == 200
        assert client.get("/gameplay").status_code == 302

    def test_gameplay_requires_login_and_honours_next(self, client):
        """
        Verify gameplay requires login and honours next.

        :param client: The client fixture.
        """

        resp = client.get("/gameplay", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/login?next=")

    def test_logout_clears_session(self, client, existing_user):
        """
        Verify logout clears session.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """

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


# ==== merged from test_auth_matrix.py ====
def _count(app, email):
    with app.app_context():
        return User.query.filter_by(email=email).count()


class TestSignupMatrix:
    def test_empty_email(self, client, app):
        resp = client.post(
            "/register",
            data={
                "email": "",
                "password": "correct-horse-123",
                "password_confirm": "correct-horse-123",
            },
        )
        assert resp.status_code == 200
        assert _count(app, "") == 0

    def test_empty_password(self, client, app):
        resp = client.post(
            "/register",
            data={"email": "e@example.com", "password": "", "password_confirm": ""},
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
        assert (
            "Registrarse" in client.get("/register?lang=es").data.decode()
            or "Regístrate" in client.get("/register?lang=es").data.decode()
            or "Sign up" in client.get("/register?lang=es").data.decode()
        )
        assert 'lang="es"' in client.get("/register?lang=es").data.decode()
        assert 'lang="hi"' in client.get("/register?lang=hi").data.decode()
        assert 'lang="zh-Hans"' in client.get("/register?lang=zh_Hans").data.decode()


class TestLoginMatrix:
    def test_empty_rejected(self, client):
        assert (
            client.post("/login", data={"email": "", "password": ""}).status_code == 200
        )
        assert client.get("/gameplay").status_code == 302

    def test_invalid_format(self, client):
        assert (
            client.post(
                "/login", data={"email": "not-an-email", "password": "x"}
            ).status_code
            == 200
        )

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


# ==== merged from test_recovery.py ====
def _reset_token(app, email):
    """
    Generate a valid reset token for an existing user.

    :param app: The Flask app fixture.
    :param email: The email of the existing user.
    :return: The reset password token string.
    :rtype: str
    """

    from flask_security.recoverable import generate_reset_password_token

    with app.app_context():
        user = User.query.filter_by(email=email).one()
        return generate_reset_password_token(user)


class TestForgotPassword:
    def test_forgot_page_loads(self, client):
        """
        Verify forgot page loads.

        :param client: The client fixture.
        """

        resp = client.get("/reset")
        assert resp.status_code == 200
        assert b'name="forgot_password_form"' in resp.data

    def test_forgot_existing_email_queues_email(self, client, app, existing_user):
        """
        Verify forgot existing email queues email.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """

        with mail.record_messages() as outbox:
            resp = client.post(
                "/reset", data={"email": existing_user["email"]}, follow_redirects=False
            )

        assert resp.status_code == 200  # re-rendered with flash, no redirect
        assert len(outbox) == 1
        assert existing_user["email"] in outbox[0].recipients

    def test_forgot_unknown_email_sends_nothing(self, client, app):
        """
        Verify forgot unknown email sends nothing.

        :param client: The client fixture.
        :param app: The app fixture.
        """

        with mail.record_messages() as outbox:
            resp = client.post("/reset", data={"email": "nobody@example.com"})
        assert resp.status_code == 200
        assert len(outbox) == 0


class TestResetPassword:
    def test_reset_invalid_token_redirects_to_forgot(self, client):
        """
        Verify reset invalid token redirects to forgot.

        :param client: The client fixture.
        """

        resp = client.get("/reset/not-a-real-token", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/reset")

    def test_reset_valid_token_loads_form(self, client, app, existing_user):
        """
        Verify reset valid token loads form.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """

        token = _reset_token(app, existing_user["email"])
        resp = client.get(f"/reset/{token}")
        assert resp.status_code == 200
        assert b'name="reset_password_form"' in resp.data

    def test_reset_success_changes_password(self, client, app, existing_user):
        """
        Verify reset success changes password.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """

        token = _reset_token(app, existing_user["email"])
        new_password = "brand-new-pass-456"
        with mail.record_messages() as outbox:
            resp = client.post(
                f"/reset/{token}",
                data={"password": new_password, "password_confirm": new_password},
                follow_redirects=False,
            )

        # POST_RESET_VIEW is "/".
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"
        # Reset notice email queued.
        assert len(outbox) == 1

        # Old password rejected, new password works.
        client.get("/logout")
        assert (
            client.post(
                "/login",
                data={
                    "email": existing_user["email"],
                    "password": existing_user["password"],
                },
            ).status_code
            == 200
        )

        assert client.get("/gameplay").status_code == 302
        resp = client.post(
            "/login",
            data={"email": existing_user["email"], "password": new_password},
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert client.get("/gameplay").status_code == 200

    def test_reset_mismatch_rejected(self, client, app, existing_user):
        """
        Verify reset mismatch rejected.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """

        token = _reset_token(app, existing_user["email"])
        resp = client.post(
            f"/reset/{token}",
            data={"password": "new-pass-123", "password_confirm": "other-pass-123"},
        )
        assert resp.status_code == 200
        with app.app_context():
            User.query.filter_by(email=existing_user["email"]).one()
            # Password unchanged: old still verifies via login.

        assert (
            client.post(
                "/login",
                data={
                    "email": existing_user["email"],
                    "password": existing_user["password"],
                },
            ).status_code
            == 302
        )


class TestChangePassword:
    def _login(self, client, existing_user):
        """
        Log in the fixture user via POST /login.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """

        client.post(
            "/login",
            data={
                "email": existing_user["email"],
                "password": existing_user["password"],
            },
        )

    def test_change_requires_login(self, client):
        """
        Verify change requires login.

        :param client: The client fixture.
        """

        resp = client.get("/change", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_change_page_loads_when_logged_in(self, client, existing_user):
        """
        Verify change page loads when logged in.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """

        self._login(client, existing_user)
        resp = client.get("/change")
        assert resp.status_code == 200
        assert b'name="change_password_form"' in resp.data

    def test_change_wrong_current_rejected(self, client, existing_user):
        """
        Verify change wrong current rejected.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """

        self._login(client, existing_user)
        resp = client.post(
            "/change",
            data={
                "password": "wrong-current-123",
                "new_password": "new-pass-123",
                "new_password_confirm": "new-pass-123",
            },
        )
        assert resp.status_code == 200

    def test_change_success_updates_login(self, client, app, existing_user):
        """
        Verify change success updates login.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """

        self._login(client, existing_user)
        with mail.record_messages() as outbox:
            resp = client.post(
                "/change",
                data={
                    "password": existing_user["password"],
                    "new_password": "changed-pass-789",
                    "new_password_confirm": "changed-pass-789",
                },
                follow_redirects=False,
            )

        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"
        assert len(outbox) == 1  # change notice

        client.get("/logout")
        resp = client.post(
            "/login",
            data={
                "email": existing_user["email"],
                "password": "changed-pass-789",
            },
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert client.get("/gameplay").status_code == 200


# ==== merged from test_recovery_matrix.py ====
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
                "/reset",
                data={"email": existing_user["email"]},
                follow_redirects=False,
            )
        assert resp.status_code == 200
        assert len(outbox) == 1
        assert existing_user["email"] in outbox[0].recipients

    def test_per_locale(self, client):
        assert (
            "Restablece" in client.get("/reset?lang=es").data.decode()
            or "Enviar" in client.get("/reset?lang=es").data.decode()
        )
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
        assert (
            client.post(
                "/login",
                data={
                    "email": existing_user["email"],
                    "password": existing_user["password"],
                },
            ).status_code
            == 302
        )

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
        assert (
            client.post(
                "/login",
                data={"email": existing_user["email"], "password": "one-time-123"},
                follow_redirects=False,
            ).status_code
            == 302
        )

    def test_per_locale(self, client, app, existing_user):
        token = _token(app, existing_user["email"])
        assert (
            "nueva" in client.get(f"/reset/{token}?lang=es").data.decode()
            or "Restablecer" in client.get(f"/reset/{token}?lang=es").data.decode()
        )


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
            data={
                "password": existing_user["password"],
                "new_password": "",
                "new_password_confirm": "",
            },
        )
        assert resp.status_code == 200

    def test_mismatch_rejected(self, client, existing_user):
        _login(client, existing_user)
        resp = client.post(
            "/change",
            data={
                "password": existing_user["password"],
                "new_password": "a12345678",
                "new_password_confirm": "b12345678",
            },
        )
        assert resp.status_code == 200

    def test_wrong_no_mail(self, client, existing_user):
        _login(client, existing_user)
        with mail.record_messages() as outbox:
            resp = client.post(
                "/change",
                data={
                    "password": "wrong-123",
                    "new_password": "n12345678",
                    "new_password_confirm": "n12345678",
                },
            )
        assert resp.status_code == 200
        assert len(outbox) == 0

    def test_success_home_notice(self, client, existing_user):
        _login(client, existing_user)
        with mail.record_messages() as outbox:
            resp = client.post(
                "/change",
                data={
                    "password": existing_user["password"],
                    "new_password": "changed-789",
                    "new_password_confirm": "changed-789",
                },
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"
        assert len(outbox) == 1
        client.get("/logout")
        assert (
            client.post(
                "/login",
                data={"email": existing_user["email"], "password": "changed-789"},
                follow_redirects=False,
            ).status_code
            == 302
        )

    def test_per_locale(self, client, existing_user):
        _login(client, existing_user)
        assert (
            "Cambiar" in client.get("/change?lang=es").data.decode()
            or "contrase" in client.get("/change?lang=es").data.decode()
        )


# ==== merged from test_mail_bodies.py ====
def test_txt_html_smoke_no_spend(client, app, existing_user):
    """No-spend link: live delivery proves acceptance, this proves bodies."""
    with app.app_context():
        user = User.query.filter_by(email=existing_user["email"]).one()
        user.language = "Spanish"
        db.session.commit()
    with mail.record_messages() as outbox:
        client.post("/reset", data={"email": existing_user["email"]})
    assert len(outbox) == 1
    assert outbox[0].body and outbox[0].html
    assert "Hola," in outbox[0].body
    assert "Hola," in outbox[0].html
