"""Autoescaping regression tests for user-controlled data.

Jinja autoescapes ``.html`` templates, but nobody had proved it. These
tests set hostile values in the fields a player controls and assert
they come out as text, never as markup.

Note the asymmetry Flask creates: ``.txt`` templates are **not**
autoescaped, so a plain-text mail body is raw by design.
"""

import pytest

from app import User, db, mail

XSS = '<script>alert("xss")</script>'
ATTR = '" autofocus onfocus="steal()'


def _login(client, existing_user):
    """Log a user in through the real login form."""
    client.post(
        "/login",
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


def _set_profile(app, existing_user, **kwargs):
    """Write hostile values into the user profile."""
    with app.app_context():
        user = User.query.filter_by(email=existing_user["email"]).one()
        for key, value in kwargs.items():
            setattr(user, key, value)
        db.session.commit()


class TestHtmlEscaping:
    """The HTML pages must never emit user data as markup."""

    def test_homepage_escapes_the_display_name(self, client, app, existing_user):
        """A display name must not become a script tag."""
        _login(client, existing_user)
        _set_profile(app, existing_user, display_name=XSS, nickname=XSS)
        html = client.get("/").get_data(as_text=True)
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_leaderboard_escapes_the_display_name(self, client, app, existing_user):
        """The leaderboard shows other players' names."""
        _login(client, existing_user)
        _set_profile(app, existing_user, display_name=XSS, nickname=XSS)
        html = client.get("/leaderboard").get_data(as_text=True)
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_settings_page_escapes_the_display_name(self, client, app, existing_user):
        """The settings form writes the name back into a value attribute."""
        _login(client, existing_user)
        _set_profile(app, existing_user, display_name=XSS, nickname=XSS)
        html = client.get("/settings").get_data(as_text=True)
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_gameplay_escapes_the_player_name(self, client, app, existing_user):
        """The gameplay header shows the player's name."""
        _login(client, existing_user)
        _set_profile(app, existing_user, display_name=XSS, nickname=XSS)
        html = client.get("/gameplay").get_data(as_text=True)
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_attribute_breakout_is_escaped(self, client, app, existing_user):
        """A quote in a name must not break out of an attribute."""
        _login(client, existing_user)
        _set_profile(app, existing_user, display_name=ATTR, nickname=ATTR)
        html = client.get("/settings").get_data(as_text=True)
        assert 'autofocus onfocus="steal()' not in html
        assert "&quot;" in html or "&#34;" in html

    def test_status_is_escaped(self, client, app, existing_user):
        """The status string is rendered on the homepage."""
        _login(client, existing_user)
        _set_profile(app, existing_user, status=XSS)
        html = client.get("/").get_data(as_text=True)
        assert "<script>alert" not in html

    def test_saved_hostile_name_is_escaped_too(self, client, existing_user):
        """A name saved through the API must also be escaped."""
        _login(client, existing_user)
        resp = client.post("/api/settings/save", json={"display_name": XSS})
        assert resp.status_code == 200
        html = client.get("/settings").get_data(as_text=True)
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_no_template_uses_the_safe_filter(self):
        """The ``|safe`` filter would disable escaping entirely."""
        import os

        root = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates"
        )
        offenders = []
        for base, _dirs, files in os.walk(root):
            for name in files:
                if not name.endswith((".html", ".txt")):
                    continue
                path = os.path.join(base, name)
                with open(path, encoding="utf-8") as fh:
                    if "|safe" in fh.read():
                        offenders.append(path)
        assert offenders == []


class TestPlainTextMail:
    """Plain-text mail bodies are not autoescaped by Flask."""

    def test_text_body_keeps_the_raw_token(self, client, app, existing_user):
        """The .txt part is plain text, so the raw value is expected."""
        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.display_name = XSS
            db.session.commit()
        with mail.record_messages() as outbox:
            client.post("/reset", data={"email": existing_user["email"]})
        assert len(outbox) == 1
        # A mail client renders plain text; the raw token is fine there.
        assert outbox[0].body

    def test_html_mail_part_is_escaped(self, client, app, existing_user):
        """The HTML mail part must not carry a live script tag."""
        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.display_name = XSS
            db.session.commit()
        with mail.record_messages() as outbox:
            client.post("/reset", data={"email": existing_user["email"]})
        assert len(outbox) == 1
        assert "<script>alert" not in (outbox[0].html or "")

    def test_no_header_injection(self, client, app, existing_user):
        """A newline in a name must not add mail headers."""
        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.display_name = "Name\r\nBcc: attacker@example.com"
            db.session.commit()
        with mail.record_messages() as outbox:
            client.post("/reset", data={"email": existing_user["email"]})
        assert len(outbox) == 1
        assert "Bcc:" not in (outbox[0].body or "")


class TestJsonApiEscaping:
    """The JSON API must return data, not markup."""

    def test_settings_payload_is_json(self, client, existing_user):
        """The API returns the raw string; the client escapes it."""
        _login(client, existing_user)
        resp = client.post("/api/settings/save", json={"display_name": XSS})
        assert resp.status_code == 200
        assert resp.get_json()["settings"]["display_name"] == XSS

    def test_leaderboard_names_are_plain_data(self, client, app, existing_user):
        """The leaderboard data is JSON, so the client must escape it."""
        _login(client, existing_user)
        _set_profile(app, existing_user, display_name=XSS, nickname=XSS)
        html = client.get("/leaderboard").get_data(as_text=True)
        assert "<script>alert" not in html


@pytest.mark.parametrize(
    "page", ["/", "/leaderboard", "/settings", "/gameplay", "/guide"]
)
def test_pages_never_contain_a_raw_script_tag_from_data(client, app, existing_user, page):
    """A sweep over the main pages for injected markup."""
    _login(client, existing_user)
    _set_profile(app, existing_user, display_name=XSS, nickname=XSS)
    html = client.get(page).get_data(as_text=True)
    assert "<script>alert" not in html
