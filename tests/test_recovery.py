"""Password recovery + change tests (Mailjet SMTP, Flask-Security-Too)."""

from app import User, db, mail


def _reset_token(app, email):
    """Generate a valid reset token for an existing user.

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
        """Verify forgot page loads.

        :param client: The client fixture.
        """
        resp = client.get("/reset")
        assert resp.status_code == 200
        assert b'name="forgot_password_form"' in resp.data

    def test_forgot_existing_email_queues_email(self, client, app, existing_user):
        """Verify forgot existing email queues email.

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
        """Verify forgot unknown email sends nothing.

        :param client: The client fixture.
        :param app: The app fixture.
        """
        with mail.record_messages() as outbox:
            resp = client.post("/reset", data={"email": "nobody@example.com"})
        assert resp.status_code == 200
        assert len(outbox) == 0


class TestResetPassword:
    def test_reset_invalid_token_redirects_to_forgot(self, client):
        """Verify reset invalid token redirects to forgot.

        :param client: The client fixture.
        """
        resp = client.get("/reset/not-a-real-token", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/reset")

    def test_reset_valid_token_loads_form(self, client, app, existing_user):
        """Verify reset valid token loads form.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """
        token = _reset_token(app, existing_user["email"])
        resp = client.get(f"/reset/{token}")
        assert resp.status_code == 200
        assert b'name="reset_password_form"' in resp.data

    def test_reset_success_changes_password(self, client, app, existing_user):
        """Verify reset success changes password.

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
        """Verify reset mismatch rejected.

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
            user = User.query.filter_by(email=existing_user["email"]).one()
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
        """Log in the fixture user via POST /login.

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
        """Verify change requires login.

        :param client: The client fixture.
        """
        resp = client.get("/change", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_change_page_loads_when_logged_in(self, client, existing_user):
        """Verify change page loads when logged in.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        self._login(client, existing_user)
        resp = client.get("/change")
        assert resp.status_code == 200
        assert b'name="change_password_form"' in resp.data

    def test_change_wrong_current_rejected(self, client, existing_user):
        """Verify change wrong current rejected.

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
        """Verify change success updates login.

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
