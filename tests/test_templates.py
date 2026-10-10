"""Template, static-asset, notifier and translation-completeness tests."""

import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def _login(client, existing_user):
    client.post(
        "/login",
        data={
            "email": existing_user["email"],
            "password": existing_user["password"],
        },
    )


def _token(app, email):
    from flask_security.recoverable import generate_reset_password_token
    from app import User

    with app.app_context():
        user = User.query.filter_by(email=email).one()
        return generate_reset_password_token(user)


class TestCsrfMeta:
    def test_index_has_meta(self, client):
        html = client.get("/").data.decode()
        assert 'name="csrf-token"' in html
        assert "window.CSRF_TOKEN" in html

    @pytest.mark.parametrize("path", ["/guide", "/leaderboard"])
    def test_anon_pages_have_meta(self, client, path):
        # guide/leaderboard include the meta tag but no window.CSRF_TOKEN
        # assignment (only index/gameplay/settings wire the JS helper).
        html = client.get(path).data.decode()
        assert 'name="csrf-token"' in html

    def test_gameplay_meta(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/gameplay").data.decode()
        assert 'name="csrf-token"' in html

    def test_settings_meta(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/settings").data.decode()
        assert 'name="csrf-token"' in html

    @pytest.mark.parametrize("path", ["/login", "/register", "/reset"])
    def test_auth_uses_hidden_tag(self, client, path):
        # TESTING disables WTF_CSRF, so hidden_tag() renders no token.
        # Pin the wiring in source + the form names in rendered HTML.
        html = client.get(path).data.decode()
        assert 'name="csrf-token"' not in html
        assert "hidden_tag()" in _read(
            "templates/login.html" if path == "/login"
            else "templates/signup.html" if path == "/register"
            else "templates/forgot_password.html"
        )

    def test_reset_token_hidden(self, client, app, existing_user):
        token = _token(app, existing_user["email"])
        html = client.get(f"/reset/{token}").data.decode()
        assert 'name="csrf-token"' not in html
        assert "hidden_tag()" in _read("templates/reset_password.html")

    def test_change_hidden(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/change").data.decode()
        assert 'name="csrf-token"' not in html
        assert "hidden_tag()" in _read("templates/change_password.html")


class TestStaticLinks:
    def test_index_links(self, client):
        html = client.get("/").data.decode()
        assert "/static/favicon.png" in html
        assert "apple-touch-icon.png" in html
        assert "bootstrap-css/bootstrap.min.css" in html
        assert "styles.css" in html
        assert "logo.png" in html

    def test_gameplay_links(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/gameplay").data.decode()
        assert "/static/favicon.png" in html
        assert "Player avatar" in html

    def test_settings_links(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/settings").data.decode()
        assert "favicon.png" in html
        assert "bootstrap.min.css" in html

    def test_auth_versioned(self, client, app, existing_user):
        for path in ("/login", "/register", "/reset"):
            assert "styles.css?v=2" in client.get(path).data.decode()
        token = _token(app, existing_user["email"])
        assert "styles.css?v=2" in client.get(f"/reset/{token}").data.decode()

    def test_notify_js(self, client, existing_user):
        _login(client, existing_user)
        for path in ("/", "/gameplay", "/settings", "/guide", "/leaderboard"):
            assert "game_notify.js?v=2" in client.get(path).data.decode()
        resp = client.get("/static/game_notify.js")
        assert resp.status_code == 200
        assert "shared-game notifier" in resp.data.decode()

    def test_nav_brand(self, client):
        html = client.get("/guide").data.decode()
        assert "nav-brand" in html
        assert "logo.png" in html
        assert "FamQuiz" in html


class TestNotifierPresence:
    @pytest.mark.parametrize(
        "path,auth",
        [("/", False), ("/guide", False), ("/leaderboard", False)],
    )
    def test_anon_app_pages(self, client, path, auth):
        html = client.get(path).data.decode()
        assert 'id="game-notify"' in html
        assert 'id="game-notify-text"' in html
        assert 'id="game-notify-join"' in html
        assert 'id="game-notify-dismiss"' in html
        assert 'data-status-url="/api/game/status"' in html
        assert "/api/game/events" in html
        assert "/api/game/join" in html
        assert 'data-authenticated="0"' in html

    @pytest.mark.parametrize("path", ["/gameplay", "/settings"])
    def test_authed_pages(self, client, existing_user, path):
        _login(client, existing_user)
        html = client.get(path).data.decode()
        assert 'id="game-notify"' in html
        assert 'data-authenticated="1"' in html

    @pytest.mark.parametrize(
        "path", ["/login", "/register", "/reset", "/change"]
    )
    def test_auth_no_notifier(self, client, existing_user, path):
        if path == "/change":
            _login(client, existing_user)
        assert 'id="game-notify"' not in client.get(path).data.decode()

    def test_reset_token_no_notifier(self, client, app, existing_user):
        token = _token(app, existing_user["email"])
        assert 'id="game-notify"' not in client.get(f"/reset/{token}").data.decode()

    def test_reminders_attr(self, client, app, existing_user):
        _login(client, existing_user)
        assert 'data-reminders="1"' in client.get("/").data.decode()
        client.post("/api/settings/save", json={"game_reminders": False})
        assert 'data-reminders="0"' in client.get("/").data.decode()

    def test_dnd_attr(self, client, existing_user):
        _login(client, existing_user)
        client.post("/api/settings/save", json={"status": "Do not disturb"})
        assert 'data-user-status="Do not disturb"' in client.get("/").data.decode()
        client.post("/api/settings/save", json={"status": "Ready to play"})
        assert 'data-user-status="Ready to play"' in client.get("/").data.decode()

    def test_none_status_fallback(self, client, app, existing_user):
        # status=None must not render data-user-status="None"; it falls
        # back to "Ready to play" like the leaderboard (status or ...).
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.status = None
            db.session.commit()
        _login(client, existing_user)
        html = client.get("/").data.decode()
        assert 'data-user-status="None"' not in html
        assert 'data-user-status="Ready to play"' in html

    def test_join_defaults(self, client):
        html = client.get("/?lang=en").data.decode()
        assert "Join game" in html
        assert 'aria-label="Dismiss"' in html


class TestIndexBranches:
    def test_anon_nav(self, client):
        html = client.get("/").data.decode()
        assert "Login" in html
        assert "Logout" not in html
        assert "home-avatar" not in html
        assert "Log in" in html
        assert "to track your stats" in html

    def test_auth_nav(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/").data.decode()
        assert "Logout" in html
        assert "home-avatar" in html
        assert "Your profile" in html
        assert "Games played" in html
        assert "Wins and scoring" in html

    def test_controls(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/").data.decode()
        assert 'id="home-start"' in html
        assert 'data-authenticated="1"' in html
        assert 'id="home-num"' in html
        assert 'min="1"' in html
        assert 'id="home-powerups"' in html
        assert 'id="home-difficulty"' in html
        assert 'id="home-wait"' in html
        assert 'value="300"' in html
        assert 'id="home-error"' in html

    def test_theme(self, client, existing_user):
        _login(client, existing_user)
        client.post("/api/settings/save", json={"theme_mode": "dark"})
        assert "theme-dark" in client.get("/").data.decode()
        client.post("/api/settings/save", json={"theme_mode": "light"})
        assert "theme-dark" not in client.get("/").data.decode()

    def test_inline_i18n(self, client):
        html = client.get("/").data.decode()
        assert "window.I18N" in html
        assert "couldNotStart" in html
        assert "quizFailed" in html
        assert "liveGameExists" in html
        assert "Could not start the game." in html

    def test_start_409_string(self):
        html = _read("templates/index.html")
        assert "resp.status === 409" in html
        assert "window.FamQuizNotify.refresh()" in html
        assert "Notification.requestPermission" in html
        assert "Math.max(10, Math.min(wait, 300))" in html


class TestGameplayBranches:
    def test_hud(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/gameplay").data.decode()
        assert 'id="game-score"' in html
        assert "Loading questions" in html
        assert 'id="game-progress"' in html
        assert 'id="game-hint"' in html
        assert 'id="game-quit"' in html
        assert html.count('class="game-option') == 4
        assert 'data-index="0"' in html
        assert 'aria-label="Question"' in html

    def test_powerups(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/gameplay").data.decode()
        for kind in ("double", "fifty", "calc", "hint"):
            assert f'data-kind="{kind}"' in html
        assert "Double points" in html
        assert "Remove two options" in html
        assert 'role="group"' in html

    def test_inline_i18n(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/gameplay").data.decode()
        for key in (
            "noQuiz", "loadFail", "submitFail", "powerFail", "finishFail",
            "complete", "youScored", "topWin", "best", "done", "question",
            "score", "hintPrefix", "requestFail",
        ):
            assert key in html, key
        assert "No active quiz. Start a game from the homepage." in html
        assert "Quiz complete!" in html

    def test_quit_wiring(self):
        html = _read("templates/gameplay.html")
        start = html.find('getElementById("game-quit")')
        assert start != -1
        assert "X-CSRFToken" in html[start:start + 800]
        assert html.count('window.location.href = "{{ url_for(') >= 2

    def test_entryloop(self):
        html = _read("templates/gameplay.html")
        assert "function entryLoop" in html
        assert "function joinAndGenerate" in html
        assert "function showNoQuizStatic" in html
        assert "function showLeft" in html
        assert "function showWaitingTick" in html
        assert "hasn't started" in html
        assert "cooling down" in html
        assert "Math.min(waitMs" not in html
        assert "starts_at * 1000" in html
        assert "var hasQuiz" in html


class TestSettingsBranches:
    def test_cards(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/settings").data.decode()
        assert "Profile &amp; Preferences" in html or "Profile & Preferences" in html
        assert "Accessibility" in html
        assert "Subscription" in html
        assert "Remove Data" in html
        assert "Ollama API key" not in html
        assert html.count('type="submit"') == 1
        assert 'id="settings-save"' in html
        assert 'id="settings-cancel"' in html
        assert 'id="settings-delete"' in html
        assert 'id="settings-erase"' in html
        assert 'id="settings-error"' in html
        assert 'id="settings-ok"' in html

    def test_profile_controls(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/settings").data.decode()
        assert 'id="settings-display"' in html
        assert 'maxlength="80"' in html
        assert 'id="settings-grade-select"' in html
        assert 'id="settings-grade-text"' in html
        assert 'id="settings-status"' in html
        assert 'id="settings-reminders"' in html
        assert "Change password" in html
        assert "Back to home" in html

    def test_accessibility(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/settings").data.decode()
        assert "Theme Mode" in html
        assert 'id="settings-theme"' in html
        assert "Language" in html
        assert 'name="language"' in html
        assert "English" in html and "Mandarin Chinese" in html

    def test_subscription(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/settings").data.decode()
        assert "Quiz Personalisation" in html
        assert 'id="settings-subject"' in html
        assert 'id="settings-difficulty"' in html
        assert 'id="settings-num"' in html
        assert "Grade is used to tailor quiz questions" in html

    def test_selected(self, client, existing_user):
        _login(client, existing_user)
        client.post(
            "/api/settings/save",
            json={
                "difficulty_level": "easy",
                "default_num_questions": 7,
                "status": "offline",
                "theme_mode": "dark",
                "language": "Hindi",
                "game_reminders": False,
            },
        )
        html = client.get("/settings").data.decode()
        assert '<option value="easy" selected>' in html
        assert 'value="7"' in html
        assert '<option value="offline" selected>' in html
        assert "theme-dark" in html

    def test_inline_i18n(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/settings").data.decode()
        for key in (
            "saved", "saveFail", "erased", "eraseFail", "deleteFail",
            "confirmDelete", "confirmErase",
        ):
            assert key in html, key
        assert "Settings saved." in html

    def test_js_fetch(self):
        html = _read("templates/settings.html")
        assert "X-CSRFToken" in html
        assert "settings_save" in html
        assert 'method: \'DELETE\'' in html or 'method: "DELETE"' in html
        assert "confirm(window.I18N.confirmDelete)" in html
        assert "confirm(window.I18N.confirmErase)" in html
        assert "theme-dark" in html
        assert "gradeSelect" in html


class TestAuthTemplates:
    def test_login(self, client):
        html = client.get("/login").data.decode()
        assert "Welcome!" in html
        assert "Email" in html
        assert "Enter your email address" in html
        assert 'autocomplete="email"' in html
        assert 'autocomplete="current-password"' in html
        assert "Log in" in html
        assert "Sign up!" in html
        assert "Forgot your password?" in html
        assert "auth-error" in _read("templates/login.html")

    def test_signup(self, client):
        html = client.get("/register").data.decode()
        assert "Confirm Password" in html
        assert "Enter your password again" in html
        assert 'autocomplete="new-password"' in html
        assert "Sign up" in html
        assert "Have an account? Log in!" in html

    def test_forgot(self, client):
        html = client.get("/reset").data.decode()
        assert "Reset your password" in html
        assert "Send reset instructions" in html
        assert "Back to log in" in html
        src = _read("templates/forgot_password.html")
        assert "alert alert-info" in src
        assert "get_flashed_messages" in src

    def test_reset(self, client, app, existing_user):
        token = _token(app, existing_user["email"])
        html = client.get(f"/reset/{token}").data.decode()
        assert "Choose a new password" in html
        assert "Reset password" in html
        assert f"/reset/{token}" in html

    def test_change(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/change").data.decode()
        assert "Change password" in html
        assert "Current password" in html
        assert "Back to home" in html

    def test_nav(self, client, existing_user):
        src = _read("templates/nav.html")
        assert "current_user.is_authenticated" in src
        assert "Change password" in src
        anon = client.get("/guide").data.decode()
        assert "How to use" in anon
        assert "Back to home" in anon
        _login(client, existing_user)
        authed = client.get("/guide").data.decode()
        assert "Change password" in authed
        assert "game-notify" not in src
        assert "csrf-token" not in src


class TestGuideLeaderboard:
    def test_guide_port(self, client):
        html = client.get("/guide").data.decode()
        assert html.count("<code>:") == 2
        src = _read("templates/guide.html")
        assert ":{{ port }}" in src
        assert ":5000" not in src

    def test_leaderboard_empty_full(self, client, app, existing_user):
        from app import User, db

        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.best_score = 12345
            user.status = "Do not disturb"
            db.session.commit()
        html = client.get("/leaderboard").data.decode()
        assert "12,345" in html
        assert "pts" in html
        assert "home-dot-busy" in html


class TestJsGuards:
    def test_i18n_game_keys(self, client, existing_user):
        _login(client, existing_user)
        for path in ("/", "/gameplay", "/settings", "/guide", "/leaderboard"):
            html = client.get(path).data.decode()
            assert "window.I18N_GAME" in html, path
            for key in (
                "startingIn", "waiting", "live", "cancelled", "waitingTapJoin",
                "remindersOff", "dndNote", "join", "dismiss", "leftNote", "rejoin",
            ):
                assert key in html, (path, key)

    def test_notify_patterns(self):
        js = _read("static/game_notify.js")
        assert "sessionStorage" in js
        assert "alreadyNotified" in js
        assert "is_starter" in js
        assert "onGameplay" in js
        assert "requestNotifyPermission" in js
        assert js.count("requestPermission()") == 1
        assert "maybeRedirect" in js
        assert "EventSource" in js
        assert "4000" in js
        assert "dismissedFor" in js
        assert "FamQuizNotify" in js
        assert "X-CSRFToken" in js

    def test_home_guards(self):
        html = _read("templates/index.html")
        assert "data-authenticated" in html
        assert "Math.max(10, Math.min(wait, 300))" in html
        assert "X-CSRFToken" in html

    def test_settings_guards(self):
        html = _read("templates/settings.html")
        assert html.count('type="submit"') == 1
        assert "confirmDelete" in html
        assert "account_erase_data" in html or "erase-data" in html or "erase_data" in html


class TestMailParity:
    def test_reset_instructions(self):
        txt = _read("templates/security/email/reset_instructions.txt")
        html = _read("templates/security/email/reset_instructions.html")
        for key in ("Hello,", "Use this link to reset your password:",
                    "This link will expire in:"):
            assert key in txt, key
            assert key in html, key
        assert "reset_link" in txt and "reset_link" in html

    def test_reset_notice(self):
        txt = _read("templates/security/email/reset_notice.txt")
        html = _read("templates/security/email/reset_notice.html")
        assert "Your password has been reset." in txt
        assert "Your password has been reset." in html

    def test_change_notice(self):
        txt = _read("templates/security/email/change_notice.txt")
        html = _read("templates/security/email/change_notice.html")
        assert "Your password has been changed." in txt
        assert "Your password has been changed." in html
        assert "If you did not change your password" in txt
        assert "forgot_password" in txt

    def test_both_parts_per_locale(self, client, app, existing_user):
        from app import User, db, mail

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.language = "Spanish"
            db.session.commit()
        with mail.record_messages() as outbox:
            client.post("/reset", data={"email": existing_user["email"]})
        assert len(outbox) == 1
        assert outbox[0].body
        assert outbox[0].html
        assert "Hola," in outbox[0].body
        assert "Hola," in outbox[0].html


class TestTranslationCompleteness:
    def _data(self):
        with open(os.path.join(ROOT, "translations.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_keysets(self):
        data = self._data()
        assert data["en"] == {}
        assert set(data["es"]) == set(data["hi"]) == set(data["zh_Hans"])
        assert len(data["es"]) > 100
        assert all(isinstance(v, str) and v for v in data["es"].values())

    def test_no_missing(self):
        import re as _re

        data = self._data()
        pattern = _re.compile(r"_\(\s*['\"]([^'\"]+)['\"]\s*\)", _re.DOTALL)
        missing = set()
        for root, _dirs, files in os.walk(os.path.join(ROOT, "templates")):
            for name in files:
                if not name.endswith((".html", ".txt")):
                    continue
                rel = os.path.relpath(os.path.join(root, name),
                                      os.path.join(ROOT, "templates"))
                text = _read(os.path.join("templates", rel))
                for match in pattern.findall(text):
                    # Templates wrap long strings across lines; collapse
                    # internal whitespace but preserve a single leading /
                    # trailing space (catalog keys like ". Best: " have one).
                    inner = " ".join(match.split())
                    candidates = {match, inner}
                    if match.startswith((" ", "\n", "\t")):
                        candidates.add(" " + inner)
                    if match.endswith((" ", "\n", "\t")):
                        candidates.add(inner + " ")
                    norm = inner
                    if norm in ("FamQuiz",):
                        continue
                    for loc in ("es", "hi", "zh_Hans"):
                        if not any(c in data[loc] for c in candidates):
                            missing.add(norm)
        # Allowlist: JS-built or attribute strings covered elsewhere.
        allow = {"points", "pts"}
        missing -= allow
        assert missing == set(), sorted(missing)[:10]

    def test_dict_matches_file(self, client):
        data = self._data()
        for loc in ("es", "hi", "zh_Hans"):
            body = client.get(f"/api/i18n/{loc}.json").get_json()
            assert body["strings"] == data[loc]
            assert body["locale"] == loc

    def test_html_lang(self, client):
        assert 'lang="en"' in client.get("/?lang=en").data.decode()
        assert 'lang="es"' in client.get("/?lang=es").data.decode()
        assert 'lang="hi"' in client.get("/?lang=hi").data.decode()
        assert 'lang="zh-Hans"' in client.get("/?lang=zh_Hans").data.decode()
