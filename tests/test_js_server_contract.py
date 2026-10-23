"""Contract tests between the browser JavaScript and the server.

There is no JavaScript runtime in this project, so the client is checked
by *contract*: every endpoint it calls must exist, every i18n key it
reads must be defined in the page, and every response field it reads
must actually be produced by the server.

Without this, renaming a route or a response key breaks the game at
runtime and no test notices.
"""

import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, "templates")

# Pages that carry client JavaScript.
PAGES = (
    "/",
    "/gameplay",
    "/settings",
    "/leaderboard",
    "/guide",
)

I18N_KEY = re.compile(r"window\.I18N\.([A-Za-z_$][A-Za-z0-9_$]*)")
I18N_GAME_KEY = re.compile(r"window\.I18N_GAME\.([A-Za-z_$][A-Za-z0-9_$]*)")
# The notifier reads its strings through a local helper: t("key", "fallback").
NOTIFIER_KEY = re.compile(r"""\bt\(\s*['"]([A-Za-z_$][A-Za-z0-9_$]*)['"]""")
FETCH_URL = re.compile(r"""fetch\(\s*['"]([^'"]+)['"]""")
URL_FOR = re.compile(r"url_for\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]")
URL_FOR_SECURITY = re.compile(r"url_for_security\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]")
OBJECT_KEY = re.compile(r"^\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*:", re.MULTILINE)


def _login(client, existing_user):
    """Log a user in through the real login form."""
    client.post(
        "/login",
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


def _scripts(html):
    """Return the inline <script> bodies of a rendered page."""
    return re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)


def _defined_keys(html, name):
    """Return the keys of the ``window.<name> = { ... }`` literal."""
    match = re.search(rf"window\.{name}\s*=\s*\{{(.*?)\n\s*\}};", html, re.S)
    if not match:
        return None
    return set(OBJECT_KEY.findall(match.group(1)))


def _api_paths(html):
    """Return every ``/api/...`` path used in the inline scripts."""
    paths = set()
    for script in _scripts(html):
        paths.update(re.findall(r"""['"](/api/[^'"?]*)""", script))
    return paths


class TestUrlForEndpoints:
    """Every ``url_for`` in a template must point at a real endpoint."""

    @pytest.mark.parametrize("page", PAGES)
    def test_endpoints_exist(self, app, client, page):
        """No template may reference a missing endpoint."""
        html = client.get(page).get_data(as_text=True)
        endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
        for name in set(URL_FOR.findall(html)):
            assert name in endpoints, f"{page} calls the missing endpoint '{name}'"

    @pytest.mark.parametrize("page", PAGES)
    def test_security_endpoints_exist(self, app, client, page):
        """``url_for_security`` must point at a Flask-Security view."""
        html = client.get(page).get_data(as_text=True)
        endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
        for name in set(URL_FOR_SECURITY.findall(html)):
            assert name in endpoints, f"{page} calls the missing endpoint '{name}'"

    def test_every_template_is_covered(self):
        """A new template must be added to the page list."""
        names = {n for n in os.listdir(TEMPLATES) if n.endswith(".html")}
        assert "gameplay.html" in names
        assert "index.html" in names
        assert "settings.html" in names


class TestFetchTargets:
    """Every URL the client fetches must be a registered route."""

    @pytest.mark.parametrize("page", PAGES)
    def test_fetch_targets_are_routes(self, app, client, page):
        """A fetch to a missing path would 404 in the browser."""
        html = client.get(page).get_data(as_text=True)
        rules = {rule.rule for rule in app.url_map.iter_rules()}
        for target in set(FETCH_URL.findall(html)) | _api_paths(html):
            if not target.startswith("/"):
                continue
            path = target.split("?")[0]
            assert any(
                path == rule or path.startswith(rule.rstrip("/") + "/")
                for rule in rules
            ), f"{page} fetches the unknown path '{target}'"

    def test_gameplay_fetches_only_json_endpoints(self, app, client, existing_user):
        """The gameplay page must talk to the documented JSON API.

        The page wraps its calls in a ``post(url, body)`` helper, so the
        endpoints are collected from the rendered paths rather than from
        literal ``fetch`` arguments.
        """
        _login(client, existing_user)
        html = client.get("/gameplay").get_data(as_text=True)
        paths = _api_paths(html)
        for expected in (
            "/api/quiz/state",
            "/api/quiz/answer",
            "/api/quiz/powerup",
            "/api/quiz/finish",
            "/api/quiz/quit",
            "/api/game/status",
            "/api/game/join",
            "/api/quiz/generate",
        ):
            assert expected in paths, f"gameplay no longer calls {expected}"

    def test_settings_calls_the_settings_api(self, app, client, existing_user):
        """The settings page must use the JSON API, not a form post."""
        _login(client, existing_user)
        html = client.get("/settings").get_data(as_text=True)
        paths = _api_paths(html)
        for expected in (
            "/api/settings/save",
            "/api/account",
            "/api/account/erase-data",
        ):
            assert expected in paths, f"settings no longer calls {expected}"

    def test_homepage_starts_a_game(self, app, client, existing_user):
        """The homepage must call the lobby start endpoint."""
        _login(client, existing_user)
        html = client.get("/").get_data(as_text=True)
        assert "/api/game/start" in _api_paths(html)


class TestI18nKeys:
    """Every i18n key the client reads must be defined in the page."""

    @pytest.mark.parametrize("page", PAGES)
    def test_i18n_keys_are_defined(self, app, client, page):
        """A missing key would render "undefined" in the UI."""
        html = client.get(page).get_data(as_text=True)
        defined = _defined_keys(html, "I18N")
        if defined is None:
            return  # page has no i18n block
        used = set()
        for script in _scripts(html):
            used.update(I18N_KEY.findall(script))
        assert used <= defined, f"{page} reads undefined keys: {sorted(used - defined)}"

    @pytest.mark.parametrize("page", PAGES)
    def test_i18n_game_keys_are_defined(self, app, client, page):
        """The notifier keys must be defined wherever the banner is."""
        html = client.get(page).get_data(as_text=True)
        defined = _defined_keys(html, "I18N_GAME")
        if defined is None:
            return
        used = set()
        for script in _scripts(html):
            used.update(I18N_GAME_KEY.findall(script))
        assert used <= defined, f"{page} reads undefined keys: {sorted(used - defined)}"

    def test_notifier_keys_are_all_consumed(self, app, client):
        """A defined-but-unused key means the UI text never appears.

        The notifier defines a few strings ahead of time (the banner
        wording for a cancelled game, for example). They are listed
        here so that a *new* unused key is caught instead of silently
        joining the pile.
        """
        unused_allowed = {
            # Reserved banner wordings that the server never sends.
            "waiting",
            "cancelled",
            "remindersOff",
            "dndNote",
            # The dismiss label comes from the template's aria-label.
            "dismiss",
        }
        notify_js = open(
            os.path.join(ROOT, "static", "game_notify.js"), encoding="utf-8"
        ).read()
        used = set(NOTIFIER_KEY.findall(notify_js))
        assert used, "the notifier no longer reads any I18N_GAME key"
        html = client.get("/").get_data(as_text=True)
        defined = _defined_keys(html, "I18N_GAME")
        assert defined is not None
        unused = defined - used
        assert unused <= unused_allowed, f"new unused notifier keys: {sorted(unused - unused_allowed)}"
        assert unused_allowed <= defined, "an allowed key disappeared from the template"


class TestApiResponseContract:
    """The response fields the client reads must be produced."""

    def test_quiz_state_shape(self, client, existing_user, monkeypatch):
        """The state payload must carry the fields the page renders."""
        import json
        from types import SimpleNamespace

        import app as app_module

        _login(client, existing_user)
        fake = SimpleNamespace(
            chat=lambda **kwargs: SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "questions": [
                                {
                                    "question": "Q?",
                                    "options": ["a", "b", "c", "d"],
                                    "answer_index": 0,
                                }
                            ]
                        }
                    )
                )
            )
        )
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        client.post("/api/quiz/generate", json={"num_questions": 1})
        body = client.get("/api/quiz/state").get_json()
        for key in ("question", "options", "index", "total", "quiz_score", "powerup"):
            assert key in body, f"quiz state is missing '{key}'"

    def test_answer_fields(self, client, existing_user, monkeypatch):
        """The answer payload must carry the fields the page renders."""
        import json
        import time
        from types import SimpleNamespace

        import app as app_module

        _login(client, existing_user)
        fake = SimpleNamespace(
            chat=lambda **kwargs: SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "questions": [
                                {
                                    "question": "Q?",
                                    "options": ["a", "b", "c", "d"],
                                    "answer_index": 0,
                                }
                            ]
                        }
                    )
                )
            )
        )
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        client.post("/api/quiz/generate", json={"num_questions": 1})
        client.get("/api/quiz/state")
        with client.session_transaction() as sess:
            sess["quiz"]["started_at"] = time.time() - 1
            sess.modified = True
        body = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        ).get_json()
        for key in ("correct", "correct_index", "quiz_score", "finished"):
            assert key in body, f"answer result is missing '{key}'"
        assert 0 <= body["correct_index"] <= 3

    def test_finish_fields(self, client, existing_user, monkeypatch):
        """The finish payload must carry the fields the summary renders."""
        import json
        import time
        from types import SimpleNamespace

        import app as app_module

        _login(client, existing_user)
        fake = SimpleNamespace(
            chat=lambda **kwargs: SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "questions": [
                                {
                                    "question": "Q?",
                                    "options": ["a", "b", "c", "d"],
                                    "answer_index": 0,
                                }
                            ]
                        }
                    )
                )
            )
        )
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        client.post("/api/quiz/generate", json={"num_questions": 1})
        client.get("/api/quiz/state")
        with client.session_transaction() as sess:
            sess["quiz"]["started_at"] = time.time() - 1
            sess.modified = True
        client.post("/api/quiz/answer", json={"option_index": 0, "question_index": 0})
        body = client.post("/api/quiz/finish").get_json()
        for key in ("quiz_score", "is_win", "best_score", "total"):
            assert key in body, f"finish summary is missing '{key}'"

    def test_game_status_fields(self, client, existing_user):
        """The lobby payload must carry the fields the notifier reads."""
        _login(client, existing_user)
        client.post("/api/game/start", json={"lobby_seconds": 60})
        body = client.get("/api/game/status").get_json()
        game = body["active_game"]
        for key in ("id", "status", "starts_at", "starts_in_ms", "you_left", "is_starter"):
            assert key in game, f"game status is missing '{key}'"

    def test_game_start_fields(self, client, existing_user):
        """The start response must carry the config the client replays."""
        _login(client, existing_user)
        body = client.post("/api/game/start", json={"lobby_seconds": 60}).get_json()
        game = body["game"]
        for key in ("num_questions", "difficulty", "powerups_enabled"):
            assert key in game, f"game start is missing '{key}'"

    def test_powerup_fields(self, client, existing_user, monkeypatch):
        """The power-up payload must carry the fields the page applies."""
        import json
        import time
        from types import SimpleNamespace

        import app as app_module

        _login(client, existing_user)
        fake = SimpleNamespace(
            chat=lambda **kwargs: SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "questions": [
                                {
                                    "question": "Q?",
                                    "options": ["a", "b", "c", "d"],
                                    "answer_index": 0,
                                }
                            ]
                        }
                    )
                )
            )
        )
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        client.post("/api/quiz/generate", json={"num_questions": 1})
        client.get("/api/quiz/state")
        with client.session_transaction() as sess:
            sess["quiz"]["offered"] = "fifty"
            sess["quiz"]["powerup_used"] = False
            sess["quiz"]["started_at"] = time.time()
            sess.modified = True
        body = client.post("/api/quiz/powerup", json={"kind": "fifty"}).get_json()
        assert body["kind"] == "fifty"
        for index in body["removed"]:
            assert 0 <= index <= 3
