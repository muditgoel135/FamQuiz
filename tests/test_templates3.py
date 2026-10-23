"""Template and static-asset checks that the other template tests miss.

* The two templates that had no source-level assertions at all
  (``leaderboard.html`` and ``game_notify.html``).
* Asset cache-busting: the stylesheet was versioned on the five auth
  pages but not on the five main pages, so a CSS change left the main
  pages on a cached stylesheet.
* The notifier script was a render-blocking script in the middle of
  ``<body>``, loaded *before* the ``window.I18N_GAME`` block it reads.
* Missing static files must 404 cleanly.
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, "templates")
STATIC = os.path.join(ROOT, "static")

MAIN_PAGES = ("/", "/guide", "/leaderboard", "/settings", "/gameplay")
AUTH_PAGES = ("/login", "/register", "/reset")


def _read(name):
    """Read a repository file."""
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


def _login(client, existing_user):
    """Log a user in through the real login form."""
    client.post(
        "/login",
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


class TestLeaderboardTemplate:
    """``templates/leaderboard.html`` had no source-level assertions."""

    def test_has_a_heading(self):
        """A page without a heading cannot be navigated by heading."""
        source = _read("templates/leaderboard.html")
        assert "<h1" in source

    def test_uses_an_ordered_list(self):
        """The ranking must be a real list for screen readers."""
        source = _read("templates/leaderboard.html")
        assert "<ol" in source
        assert "</ol>" in source

    def test_translates_the_status(self):
        """The status text must go through the translator."""
        source = _read("templates/leaderboard.html")
        assert "_(entry.status)" in source

    def test_ranks_are_marked_up(self):
        """The rank is read out with its number."""
        source = _read("templates/leaderboard.html")
        assert "entry.rank" in source

    def test_score_uses_the_translated_unit(self):
        """The score unit must be translated."""
        source = _read("templates/leaderboard.html")
        assert "_('pts')" in source

    def test_decorative_avatar_is_hidden(self):
        """The initial letter duplicates the name and must stay silent."""
        source = _read("templates/leaderboard.html")
        assert 'aria-hidden="true"' in source

    def test_main_landmark(self):
        """Every page needs a main landmark."""
        source = _read("templates/leaderboard.html")
        assert '<main id="main"' in source


class TestGameNotifyTemplate:
    """``templates/game_notify.html`` had no source-level assertions."""

    def test_exposes_the_expected_data_attributes(self):
        """The notifier reads exactly these seven attributes."""
        source = _read("templates/game_notify.html")
        for attribute in (
            "data-status-url",
            "data-events-url",
            "data-join-url",
            "data-gameplay-url",
            "data-authenticated",
            "data-reminders",
            "data-user-status",
        ):
            assert attribute in source

    def test_every_data_attribute_is_read_by_the_script(self):
        """An attribute the script ignores is dead weight."""
        source = _read("templates/game_notify.html")
        script = _read("static/game_notify.js")
        for attribute in re.findall(r"data-([a-z-]+)=", source):
            camel = re.sub(r"-([a-z])", lambda m: m.group(1).upper(), attribute)
            assert f"dataset.{camel}" in script, f"data-{attribute} is never read"

    def test_buttons_have_type_button(self):
        """A button without type submits the nearest form."""
        source = _read("templates/game_notify.html")
        assert 'type="button"' in source

    def test_join_button_has_a_label(self):
        """The button text is translated."""
        source = _read("templates/game_notify.html")
        assert "_('Join game')" in source

    def test_dismiss_button_has_an_aria_label(self):
        """An icon-only button needs an accessible name."""
        source = _read("templates/game_notify.html")
        assert 'aria-label="{{ _(\'Dismiss\') }}"' in source

    def test_dot_is_decorative(self):
        """The pulsing dot carries no information."""
        source = _read("templates/game_notify.html")
        assert 'aria-hidden="true"' in source

    def test_countdown_has_no_conflicting_label(self):
        """An aria-label on a bare span hides the text it labels."""
        source = _read("templates/game_notify.html")
        countdown = re.search(r'id="game-notify-countdown"[^>]*', source).group(0)
        assert "aria-label" not in countdown


class TestAssetVersioning:
    """Every page must bust the cache for the assets it loads."""

    def test_stylesheet_is_versioned_on_every_page(self, client, app, existing_user):
        """The auth pages were versioned, the main pages were not."""
        _login(client, existing_user)
        for path in MAIN_PAGES:
            html = client.get(path).get_data(as_text=True)
            assert "styles.css?v=" in html, f"{path} loads an unversioned stylesheet"

    def test_stylesheet_version_is_the_same_everywhere(self, client, app, existing_user):
        """One asset version for the whole app."""
        _login(client, existing_user)
        versions = set()
        for path in MAIN_PAGES:
            html = client.get(path).get_data(as_text=True)
            match = re.search(r"styles\.css\?v=(\d+)", html)
            assert match, f"{path} loads an unversioned stylesheet"
            versions.add(match.group(1))
        # The auth pages redirect to the homepage once logged in, so they
        # are checked with a fresh anonymous client.
        anonymous = app.test_client()
        for path in AUTH_PAGES:
            html = anonymous.get(path).get_data(as_text=True)
            match = re.search(r"styles\.css\?v=(\d+)", html)
            assert match, f"{path} loads an unversioned stylesheet"
            versions.add(match.group(1))
        assert len(versions) == 1, f"mixed asset versions: {versions}"

    def test_notifier_script_is_versioned(self, client, app, existing_user):
        """The notifier must be re-fetched when it changes."""
        _login(client, existing_user)
        for path in MAIN_PAGES:
            html = client.get(path).get_data(as_text=True)
            assert "game_notify.js?v=" in html


class TestScriptLoading:
    """The notifier script must not block the page."""

    def test_notifier_is_loaded_with_defer(self):
        """A mid-body script blocks rendering and the parser."""
        source = _read("templates/game_notify.html")
        assert "defer" in source

    def test_i18n_block_precedes_the_notifier_script(self):
        """The notifier reads window.I18N_GAME when it runs."""
        source = _read("templates/game_notify.html")
        i18n_at = source.find("window.I18N_GAME")
        script_at = source.find("game_notify.js")
        assert i18n_at != -1 and script_at != -1
        assert i18n_at < script_at, "the notifier loads before its translations"

    def test_notifier_is_not_loaded_twice(self):
        """A duplicated script runs the notifier twice."""
        source = _read("templates/game_notify.html")
        assert source.count("game_notify.js") == 1


class TestStaticFiles:
    """Missing static assets must fail cleanly."""

    def test_missing_static_file_is_404(self, client, app):
        """A missing asset must not raise."""
        resp = client.get("/static/does-not-exist.js")
        assert resp.status_code == 404

    def test_missing_static_file_has_no_traceback(self, client, app):
        """The error page must not leak internals."""
        resp = client.get("/static/does-not-exist.js")
        assert b"Traceback" not in resp.data

    def test_missing_static_file_has_security_headers(self, client, app):
        """The after_request hook applies to static 404s too."""
        resp = client.get("/static/does-not-exist.js")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"

    @pytest.mark.parametrize(
        "name",
        [
            "game_notify.js",
            "styles.css",
            "favicon.png",
            "logo.png",
            "apple-touch-icon.png",
            "bootstrap-css/bootstrap.min.css",
        ],
    )
    def test_known_assets_are_served(self, client, app, name):
        """The assets the templates load must exist."""
        assert client.get(f"/static/{name}").status_code == 200


class TestNoscriptFallback:
    """The game needs a message when JavaScript is unavailable."""

    @pytest.mark.parametrize("name", ["gameplay.html", "settings.html", "index.html"])
    def test_noscript_message_exists(self, name):
        """Without JavaScript the buttons do nothing at all."""
        source = _read(os.path.join("templates", name))
        assert "<noscript>" in source
