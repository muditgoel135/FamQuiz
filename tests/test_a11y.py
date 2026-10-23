"""Accessibility checks for the rendered pages.

These are structural checks, not a full audit: every page must have a
main landmark and a heading, the dynamic parts of the game must be
announced, and the interactive controls must be reachable by keyboard.

The checks are written against the *rendered* page, so a template
change that drops the markup fails here.
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, "templates")
STATIC = os.path.join(ROOT, "static")

ALL_PAGES = (
    "/",
    "/guide",
    "/leaderboard",
    "/login",
    "/register",
    "/reset",
)

AUTHED_PAGES = ("/settings", "/gameplay")


def _login(client, existing_user):
    """Log a user in through the real login form."""
    client.post(
        "/login",
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


def _headings(html):
    """Return the heading levels used in a page."""
    return [int(level) for level in re.findall(r"<h([1-6])\b", html)]


class TestLandmarks:
    """Every page needs a main landmark and a skip link."""

    @pytest.mark.parametrize("page", ALL_PAGES)
    def test_main_landmark_has_an_id(self, client, page):
        """The skip link needs a target to jump to."""
        html = client.get(page).get_data(as_text=True)
        assert '<main id="main"' in html

    @pytest.mark.parametrize("page", ALL_PAGES)
    def test_skip_link_is_first(self, client, page):
        """Keyboard users must be able to skip the navigation."""
        html = client.get(page).get_data(as_text=True)
        assert 'class="skip-link"' in html
        assert 'href="#main"' in html

    @pytest.mark.parametrize("page", ALL_PAGES)
    def test_navigation_is_labelled(self, client, page):
        """A landmark without a name is not distinguishable."""
        html = client.get(page).get_data(as_text=True)
        assert "aria-label=" in html
        assert 'aria-label="Main navigation"' in html


class TestHeadings:
    """Every page needs exactly one top-level heading."""

    @pytest.mark.parametrize("page", ALL_PAGES)
    def test_exactly_one_h1(self, client, page):
        """Screen readers navigate by heading level."""
        html = client.get(page).get_data(as_text=True)
        assert _headings(html).count(1) == 1, f"{page} has no unique h1"

    @pytest.mark.parametrize("page", ALL_PAGES)
    def test_no_skipped_levels(self, client, page):
        """A heading level must never be skipped."""
        html = client.get(page).get_data(as_text=True)
        levels = _headings(html)
        for previous, current in zip(levels, levels[1:]):
            assert current <= previous + 1, f"{page} skips from h{previous} to h{current}"


class TestGameplayAnnouncements:
    """The game screen must announce what changes."""

    def _gameplay(self, client, existing_user):
        """Return the rendered gameplay page."""
        _login(client, existing_user)
        return client.get("/gameplay").get_data(as_text=True)

    def test_score_is_a_live_region(self, client, existing_user):
        """The score changes after every answer."""
        html = self._gameplay(client, existing_user)
        assert 'id="game-score"' in html
        section = re.search(r'id="game-score"[^>]*', html).group(0)
        assert "aria-live" in section

    def test_question_is_announced(self, client, existing_user):
        """Each new question must be read out."""
        html = self._gameplay(client, existing_user)
        section = re.search(r'id="game-question-text"[^>]*', html).group(0)
        assert "aria-live" in section

    def test_progress_is_announced(self, client, existing_user):
        """The question counter changes constantly."""
        html = self._gameplay(client, existing_user)
        section = re.search(r'id="game-progress"[^>]*', html).group(0)
        assert "aria-live" in section

    def test_hint_is_announced(self, client, existing_user):
        """The hint appears after a power-up."""
        html = self._gameplay(client, existing_user)
        section = re.search(r'id="game-hint"[^>]*', html).group(0)
        assert "aria-live" in section

    def test_powerup_buttons_expose_their_state(self, client, existing_user):
        """The armed power-up must be visible to assistive tech."""
        html = self._gameplay(client, existing_user)
        assert 'aria-pressed="false"' in html

    def test_dynamic_text_uses_textcontent(self, client, existing_user):
        """Setting innerHTML with server text would be an XSS hole."""
        html = self._gameplay(client, existing_user)
        script = "\n".join(
            re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
        )
        for element in ("questionEl", "scoreEl", "progressEl", "hintEl"):
            assert f"{element}.textContent" in script, f"{element} is not set safely"
        assert "innerHTML" not in script, "the gameplay script must not use innerHTML"


class TestNotifierBanner:
    """The game banner must be a polite, non-alarming region."""

    def test_banner_uses_role_status(self, client):
        """``role="alert"`` is assertive and swallows the button clicks."""
        html = client.get("/").get_data(as_text=True)
        banner = re.search(r'id="game-notify"[^>]*', html).group(0)
        assert 'role="status"' in banner
        assert 'role="alert"' not in banner

    def test_banner_is_polite(self, client):
        """A live game must not interrupt the player."""
        html = client.get("/").get_data(as_text=True)
        banner = re.search(r'id="game-notify"[^>]*', html).group(0)
        assert 'aria-live="polite"' in banner

    def test_banner_buttons_are_labelled(self, client):
        """An icon-only button needs an accessible name."""
        html = client.get("/").get_data(as_text=True)
        assert 'id="game-notify-join"' in html
        assert 'aria-label="Dismiss"' in html


class TestFocusStyles:
    """Every interactive control needs a visible focus ring."""

    def _css(self):
        """Return the stylesheet source."""
        with open(os.path.join(STATIC, "styles.css"), encoding="utf-8") as fh:
            return fh.read()

    @pytest.mark.parametrize(
        "selector",
        [
            ".game-notify-join:focus-visible",
            ".game-notify-dismiss:focus-visible",
            ".home-start:focus-visible",
            ".auth-btn:focus-visible",
            ".game-quit:focus-visible",
            ".home-avatar:focus-visible",
        ],
    )
    def test_focus_ring_exists(self, selector):
        """A control without a focus ring is unreachable by keyboard."""
        assert selector in self._css()

    def test_skip_link_is_styled(self):
        """The skip link must be hidden until it is focused."""
        css = self._css()
        assert ".skip-link" in css
        assert ".skip-link:focus" in css


class TestReducedMotion:
    """The pulsing dot must respect the user's motion preference."""

    def test_media_query_exists(self):
        """A pulsing animation with no opt-out is an accessibility issue."""
        with open(os.path.join(STATIC, "styles.css"), encoding="utf-8") as fh:
            css = fh.read()
        assert "@media (prefers-reduced-motion: reduce)" in css

    def test_animation_is_disabled(self):
        """The pulse must actually stop."""
        with open(os.path.join(STATIC, "styles.css"), encoding="utf-8") as fh:
            css = fh.read()
        block = css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
        assert "animation: none" in block


class TestFormAccessibility:
    """Form controls must be associated with their labels."""

    def test_homepage_inputs_have_labels(self, client):
        """A number input without a label is unusable."""
        html = client.get("/").get_data(as_text=True)
        assert 'for="home-num"' in html
        assert 'for="home-difficulty"' in html

    def test_auth_inputs_have_labels(self, client):
        """The login and signup forms must label their fields."""
        for path in ("/login", "/register", "/reset"):
            html = client.get(path).get_data(as_text=True)
            assert "<label" in html

    def test_error_boxes_are_announced(self, client):
        """An error must be reachable by a screen reader."""
        html = client.get("/").get_data(as_text=True)
        assert 'role="alert"' in html
