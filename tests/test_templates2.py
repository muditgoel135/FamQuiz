"""Residual template/static/i18n pins (wave 2): SRC first, renders after."""

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
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


def _token(app, email):
    from flask_security.recoverable import generate_reset_password_token
    from app import User

    with app.app_context():
        return generate_reset_password_token(
            User.query.filter_by(email=email).one()
        )


class TestSrcIndexJsStrict:
    SRC = None

    @classmethod
    def setup_class(cls):
        cls.SRC = _read("templates/index.html")

    def test_auth_redirect(self):
        assert "btn.dataset.authenticated !== '1'" in self.SRC
        assert "?next=" in self.SRC and "gameplay" in self.SRC

    def test_showerror_disabled(self):
        assert "errBox.hidden = false" in self.SRC
        assert "errBox.hidden = true" in self.SRC
        assert "btn.disabled = true" in self.SRC
        assert "btn.disabled = false" in self.SRC
        assert "Object.keys(fields)" in self.SRC

    def test_409_fork(self):
        assert "resp.status === 409" in self.SRC
        assert self.SRC.count("window.FamQuizNotify.refresh()") == 2
        assert "throw new Error(window.I18N.liveGameExists)" in self.SRC
        assert "err.message === window.I18N.liveGameExists" in self.SRC

    def test_csrf_notify_clamp(self):
        assert "function csrfHeaders()" in self.SRC
        assert "X-CSRFToken" in self.SRC
        assert 'Notification.permission === "default"' in self.SRC
        assert "Math.max(10, Math.min(wait, 300))" in self.SRC
        assert "lobby_seconds" in self.SRC

    def test_boot(self):
        assert "window.I18N = {" in self.SRC
        assert "couldNotStart" in self.SRC
        assert "window.CSRF_TOKEN" in self.SRC


class TestSrcGameplayJsStrict:
    SRC = None

    @classmethod
    def setup_class(cls):
        cls.SRC = _read("templates/gameplay.html")

    def test_hasquiz_urls(self):
        assert "var hasQuiz = {{ 'true' if has_quiz else 'false' }}" in self.SRC
        assert "url_for('game_status')" in self.SRC
        assert "url_for('game_join')" in self.SRC
        assert "url_for('quiz_generate')" in self.SRC
        assert "if (hasQuiz) {" in self.SRC

    def test_entry_timers(self):
        assert "setTimeout(entryLoop, 2000)" in self.SRC
        assert "setTimeout(entryLoop, 11000)" in self.SRC
        assert "setTimeout(entryLoop, 4000)" in self.SRC
        assert "starts_at * 1000" in self.SRC
        assert "function fmtCountdown(ms)" in self.SRC

    def test_fmt(self):
        assert "toLocaleString(document.documentElement.lang" in self.SRC
        assert "function fmt(n)" in self.SRC

    def test_answer_powerup(self):
        assert 'classList.add("correct")' in self.SRC
        assert 'classList.add("wrong")' in self.SRC
        assert 'classList.add("removed")' in self.SRC
        assert 'classList.add("armed")' in self.SRC
        assert ", 900)" in self.SRC

    def test_hint_win(self):
        assert "window.I18N.hintPrefix" in self.SRC
        assert "\\u201c" in self.SRC
        assert "res.is_win" in self.SRC
        assert "window.I18N.topWin" in self.SRC
        assert "finishedQuiz = true" in self.SRC

    def test_endash(self):
        assert "Question –/–" in self.SRC  # U+2013 en-dash
        assert '"—"' in self.SRC or "textContent = \"—\"" in self.SRC
        assert '"You left this game"' in self.SRC

    def test_quit_full(self):
        start = self.SRC.find('getElementById("game-quit")')
        assert start != -1
        assert "quitBtn.disabled = true" in self.SRC[start:start + 900]
        assert 'method: "POST"' in self.SRC
        assert "quiz_quit" in self.SRC
        assert self.SRC.count('window.location.href = "{{ url_for(') >= 2


class TestSrcSettingsJsStrict:
    SRC = None

    @classmethod
    def setup_class(cls):
        cls.SRC = _read("templates/settings.html")

    def test_grade_sync(self):
        assert "gradeSelect.addEventListener('change'" in self.SRC
        assert "gradeText.value = gradeSelect.value" in self.SRC
        assert "gradeText.addEventListener('input'" in self.SRC

    def test_trim_parseint(self):
        assert "gradeText.value.trim()" in self.SRC
        assert "parseInt(numInput.value, 10)" in self.SRC

    def test_theme_toggle(self):
        assert "document.body.classList.toggle('theme-dark'" in self.SRC

    def test_cancel_erase(self):
        assert "displayInput.value = initial.display_name" in self.SRC
        assert 'input[name="language"]' in self.SRC
        assert "account_erase_data" in self.SRC
        assert "window.location.reload()" in self.SRC
        assert "account_delete" in self.SRC

    def test_csrf_helpers(self):
        assert "function csrfHeaders()" in self.SRC
        assert "function csrfHeadersNoBody()" in self.SRC
        assert "settings_save" in self.SRC


class TestSrcNotifyJsStrict:
    JS = None

    @classmethod
    def setup_class(cls):
        cls.JS = _read("static/game_notify.js")

    def test_boot(self):
        assert "if (!box) return;" in self.JS
        assert "if (!authenticated) return;" in self.JS
        assert "dataset.authenticated" in self.JS
        assert '"do not disturb"' in self.JS

    def test_show_tick(self):
        assert "function show(game)" in self.JS
        assert "dismissedFor === key(game)" in self.JS
        assert "box.hidden = false" in self.JS
        assert "function tickCountdown()" in self.JS
        assert "countdownTimer = setInterval(tickCountdown, 1000)" in self.JS

    def test_time_helpers(self):
        assert "starts_at * 1000" in self.JS
        assert "starts_in_ms" in self.JS
        assert "Date.now()" in self.JS
        assert "Math.ceil(ms / 1000)" in self.JS

    def test_notify_redirect(self):
        assert "function maybeNotify(game)" in self.JS
        assert "alreadyNotified(game)" in self.JS
        assert 'permission === "granted"' in self.JS
        assert 'new Notification("FamQuiz"' in self.JS
        assert "function maybeRedirect(game)" in self.JS
        assert "window.location.href = gameplayUrl" in self.JS

    def test_sse(self):
        assert "new EventSource(eventsUrl)" in self.JS
        assert 'addEventListener("snapshot"' in self.JS
        assert 'addEventListener("update"' in self.JS
        assert "setInterval(fetchStatus, 4000)" in self.JS
        assert "game-none" in self.JS and "game-live" in self.JS
        assert "game-pending" in self.JS and "game-cancelled" in self.JS

    def test_join_dismiss(self):
        assert 'meta[name="csrf-token"]' in self.JS
        assert 'method: "POST"' in self.JS
        assert "dismissedFor = key(current)" in self.JS
        assert "FamQuizNotify" in self.JS
        assert "famquiz-notified-" in self.JS


class TestSrcCssStrict:
    CSS = None

    @classmethod
    def setup_class(cls):
        cls.CSS = _read("static/styles.css")

    def test_focus(self):
        for sel in (".game-option:focus-visible",
                    ".game-powerups button:focus-visible",
                    ".settings-btn:focus-visible"):
            assert sel in self.CSS, sel
        assert "outline: 3px solid #0b2a4a" in self.CSS

    def test_critical(self):
        assert ".game-option.correct" in self.CSS
        assert ".game-option.wrong" in self.CSS
        assert ".game-option.removed" in self.CSS
        assert ".game-notify[hidden]" in self.CSS
        assert "display: none" in self.CSS
        assert "body.theme-dark" in self.CSS
        assert ".board-score" in self.CSS
        assert ".home-dot-ready" in self.CSS

    def test_nav_guide(self):
        assert "game-notify" not in _read("templates/nav.html")
        assert "csrf-token" not in _read("templates/nav.html")
        src = _read("templates/guide.html")
        assert src.count("aria-label") >= 6
        assert ":{{ port }}" in src
        assert ":5000" not in src


class TestIndexAnonResidual:
    def test_settings_link(self, client):
        html = client.get("/").data.decode()
        assert 'href="/settings"' in html
        assert "Login" in html
        assert "Logout" not in html
        assert "home-avatar" not in html

    def test_sections_footer(self, client):
        html = client.get("/").data.decode()
        assert 'aria-label="Leaderboard"' in html
        assert 'aria-label="Game options"' in html
        assert 'aria-label="Statistics"' in html
        assert "Copyright" in html and "2026" in html

    def test_controls_full(self, client):
        html = client.get("/").data.decode()
        assert 'name="num_questions"' in html
        assert 'min="1"' in html and 'max="20"' in html
        assert 'name="lobby_seconds"' in html
        assert 'min="10"' in html and 'step="10"' in html
        assert 'aria-label="Waiting time:"' in html
        assert 'id="home-powerups"' in html and "checked" in html
        assert '<option value="easy"' in html
        assert '<option value="hard"' in html
        assert 'id="home-error"' in html and 'role="alert"' in html


class TestAuthFormsAnon:
    @pytest.mark.parametrize(
        "path,form", [("/login", "login_user_form"),
                      ("/register", "register_user_form"),
                      ("/reset", "forgot_password_form")],
    )
    def test_wiring(self, client, path, form):
        html = client.get(path).data.decode()
        assert f'name="{form}"' in html
        assert 'method="POST"' in html
        assert "novalidate" in html
        assert "auth-input" in html

    def test_texts(self, client, app, existing_user):
        assert "Have an account? Log in!" in client.get("/register").data.decode()
        assert "Enter your account email" in client.get("/reset").data.decode()
        token = _token(app, existing_user["email"])
        html = client.get(f"/reset/{token}").data.decode()
        assert "New password" in html and "Confirm new password" in html
        assert html.count('autocomplete="new-password"') >= 2
        assert "Back to log in" in html

    def test_flash_source(self):
        for name in ("forgot_password.html", "reset_password.html",
                     "change_password.html"):
            src = _read(f"templates/{name}")
            assert "get_flashed_messages" in src
            assert "alert alert-info" in src


class TestGuideLeaderboardAnon:
    def test_guide(self, client):
        html = client.get("/guide").data.decode()
        assert "Tailscale" in html
        assert "1500 points" in html
        assert html.count("<code>:") == 2

    def test_leaderboard(self, client, app):
        from flask_security.utils import hash_password
        from app import db, user_datastore

        with app.app_context():
            user_datastore.create_user(
                email="l1@example.com", password=hash_password("x" * 12))
            from app import User

            user = User.query.filter_by(email="l1@example.com").one()
            user.best_score = 5000
            user.display_name = "Big"
            db.session.commit()
        html = client.get("/leaderboard").data.decode()
        assert 'aria-label="Leaderboard"' in html
        assert "board-score" in html
        assert "pts" in html
        assert "(You)" not in html

    def test_notify_anon(self, client):
        for path in ("/", "/guide", "/leaderboard"):
            html = client.get(path).data.decode()
            assert 'role="alert"' in html
            assert 'data-gameplay-url="/gameplay"' in html
            assert 'data-events-url="/api/game/events"' in html
            assert 'data-join-url="/api/game/join"' in html
            assert 'data-authenticated="0"' in html
            assert 'data-reminders="0"' in html
            assert "✕" in html


class TestIndexAuthedStrict:
    def test_avatar_strict(self, client, app, existing_user):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.display_name = " Alice "
            db.session.commit()
        _login(client, existing_user)
        html = client.get("/").data.decode()
        assert ">A</a>" in html
        assert 'aria-label="Your profile"' in html

    def test_row_aria(self, client, app, existing_user):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.display_name = "Rr"
            user.status = "Ready to play"
            user.best_score = 999
            db.session.commit()
        _login(client, existing_user)
        html = client.get("/").data.decode()
        assert 'aria-hidden="true"' in html
        assert 'class="home-player-status"' in html
        assert 'aria-label="Ready to play"' in html


class TestGameplayRenderStrict:
    def test_hud(self, client, app, existing_user):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.display_name = "Me"
            user.score = 1234
            db.session.commit()
        _login(client, existing_user)
        html = client.get("/gameplay").data.decode()
        assert "Me: #1" in html
        assert "1,234" in html
        assert "Player avatar" in html
        assert "Question 1/10" in html
        assert "Loading questions…" in html

    def test_options(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/gameplay").data.decode()
        assert html.count('class="game-option') == 4
        for i in ("0", "1", "2", "3"):
            assert f'data-index="{i}"' in html
        assert "…" in html
        assert 'aria-label="Answer options"' in html

    def test_powerups(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/gameplay").data.decode()
        assert 'aria-label="Power-ups"' in html
        for label in ("Double points", "Remove two options", "Calculator", "Hint"):
            assert f'aria-label="{label}"' in html
        assert 'id="game-hint"' in html
        assert html.count('aria-hidden="true"') >= 4


class TestSettingsRenderStrict:
    def test_subs_alerts(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/settings").data.decode()
        assert "Update your profile" in html
        assert "Automate quizzes" in html
        assert "Manage family plan" in html
        assert 'id="settings-form"' in html and "novalidate" in html
        assert 'role="alert"' in html and 'role="status"' in html
        assert "settings-alert-error" in html and "settings-alert-ok" in html

    def test_inputs(self, client, app, existing_user):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.display_name = "Di"
            user.favorite_subject = "Math"
            db.session.commit()
        _login(client, existing_user)
        html = client.get("/settings").data.decode()
        assert 'autocomplete="nickname"' in html
        assert 'maxlength="80"' in html
        assert 'value="Di"' in html
        assert 'value="Math"' in html
        assert 'aria-label="Questions per game"' in html
        assert 'min="1"' in html

    def test_buttons(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/settings").data.decode()
        assert ">Delete<" in html and ">Erase<" in html
        assert ">Save<" in html and ">Cancel<" in html
        assert html.count('type="submit"') == 1
        assert "/change" in html

    def test_persistence(self, client, existing_user):
        _login(client, existing_user)
        client.post(
            "/api/settings/save",
            json={"language": "Hindi", "game_reminders": False,
                  "theme_mode": "dark"},
        )
        html = client.get("/settings").data.decode()
        assert "checked" in html
        assert 'id="settings-reminders"' in html
        assert 'id="settings-theme"' in html
        assert 'id="settings-num"' in html


class TestNotifyAuthedStrict:
    def test_all_pages(self, client, existing_user):
        _login(client, existing_user)
        for path in ("/", "/gameplay", "/settings", "/guide", "/leaderboard"):
            html = client.get(path).data.decode()
            assert 'data-authenticated="1"' in html, path
            assert 'id="game-notify-text"' in html, path

    def test_i18n_keys(self, client, existing_user):
        _login(client, existing_user)
        for path in ("/", "/gameplay", "/settings"):
            html = client.get(path).data.decode()
            assert "window.I18N_GAME" in html, path
            for key in ("startingIn", "waiting", "live", "cancelled",
                        "waitingTapJoin", "remindersOff", "dndNote", "join",
                        "dismiss", "leftNote", "rejoin"):
                assert key in html, (path, key)

    def test_es_values(self, client):
        html = client.get("/?lang=es").data.decode()
        assert "El juego empieza en" in html
        assert "Descartar" in html


class TestTranslationsStrict:
    def _data(self):
        with open(os.path.join(ROOT, "translations.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_py_scan(self):
        data = self._data()
        pattern = re.compile(r"_\(\s*['\"]([^'\"]+)['\"]\s*\)", re.DOTALL)
        missing = set()
        for rel in ["app.py", "routes.py"]:
            text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
            for match in pattern.findall(text):
                norm = " ".join(match.split())
                if norm in ("FamQuiz", "points", "pts"):
                    continue
                # app.py validation strings are English sources; allow if in
                # catalog OR clearly a code-internal string (contains paren).
                if "(" in norm:
                    continue
                if norm not in data["es"]:
                    missing.add(norm)
        assert missing == set(), sorted(missing)[:10]

    def test_orphan(self):
        data = self._data()
        assert "Welcome Back!" in data["es"]
        combined = ""
        for rel in ["app.py", "routes.py"]:
            combined += open(os.path.join(ROOT, rel), encoding="utf-8").read()
        for root, _d, files in os.walk(os.path.join(ROOT, "templates")):
            for name in files:
                if name.endswith((".html", ".txt")):
                    combined += open(os.path.join(root, name),
                                     encoding="utf-8", errors="ignore").read()
        assert "Welcome Back!" not in combined  # documents orphan key
        assert "Welcome!" in combined

    def test_strict_renders(self, client, existing_user):
        assert "Clasificación" in client.get("/?lang=es").data.decode()
        assert "लीडरबोर्ड" in client.get("/?lang=hi").data.decode()
        assert "排行榜" in client.get("/?lang=zh_Hans").data.decode()
        assert "Bienvenido" in client.get("/guide?lang=es").data.decode()
        assert "Clasificación" in client.get("/leaderboard?lang=es").data.decode()
        # Anonymous pages first: /login redirects once authenticated.
        assert "Iniciar sesi" in client.get("/login?lang=es").data.decode()
        _login(client, existing_user)
        html = client.get("/gameplay?lang=es").data.decode()
        assert "Salir" in html

    def test_i18n_values(self, client, existing_user):
        assert "Could not start the game." in client.get("/").data.decode()
        assert "A family game is waiting" in client.get("/").data.decode()
        _login(client, existing_user)
        html = client.get("/gameplay").data.decode()
        assert "No active quiz. Start a game from the homepage." in html
        assert "Quiz complete!" in html
        assert "Hint: the answer starts with" in html
        html = client.get("/settings").data.decode()
        assert "Settings saved." in html
        assert "Delete your account permanently?" in html


class TestMailParityStrict:
    def test_reset_hello(self):
        for name in ("reset_notice.txt", "reset_notice.html"):
            assert "Hello," in _read(f"templates/security/email/{name}")

    def test_change_html(self):
        html = _read("templates/security/email/change_notice.html")
        txt = _read("templates/security/email/change_notice.txt")
        assert "Hello," in html and "Hello," in txt
        assert "If you did not change your password" in html
        assert "forgot_password" in html and "forgot_password" in txt
        assert "<a href=" in html

    def test_within_href(self):
        for name in ("reset_instructions.txt", "reset_instructions.html"):
            assert "within" in _read(f"templates/security/email/{name}")
        assert '<a href="{{ reset_link }}">' in _read(
            "templates/security/email/reset_instructions.html")

    def test_hi_subjects(self, client, app, existing_user):
        from app import User, db, mail

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.language = "Hindi"
            db.session.commit()
        with mail.record_messages() as outbox:
            client.post("/reset", data={"email": existing_user["email"]})
        assert len(outbox) == 1
        assert outbox[0].subject == "पासवर्ड रीसेट निर्देश"
        assert "नमस्ते," in outbox[0].body
        assert "नमस्ते," in outbox[0].html

    def test_en_within(self, client, app, existing_user):
        from app import User, db, mail

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.language = "English"
            db.session.commit()
        with mail.record_messages() as outbox:
            client.post("/reset", data={"email": existing_user["email"]})
        assert "Hello," in outbox[0].body
        assert "Use this link to reset your password:" in outbox[0].body
        assert "This link will expire in:" in outbox[0].body


class TestStaticA11ySweep:
    def test_versioning(self, client, app, existing_user):
        for path in ("/login", "/register", "/reset"):
            assert "styles.css?v=2" in client.get(path).data.decode()
        token = _token(app, existing_user["email"])
        assert "styles.css?v=2" in client.get(f"/reset/{token}").data.decode()
        _login(client, existing_user)
        for path in ("/", "/gameplay", "/settings"):
            assert "game_notify.js?v=2" in client.get(path).data.decode()
        assert client.get("/static/game_notify.js").status_code == 200
        assert client.get("/static/styles.css").status_code == 200

    def test_a11y(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/").data.decode()
        assert 'for="home-num"' in html
        assert 'aria-labelledby="home-powerups-label"' in html
        html = client.get("/settings").data.decode()
        assert "visually-hidden" in html
        assert "<legend" in html
        assert "aria-labelledby=" in html
        html = client.get("/gameplay").data.decode()
        assert 'aria-label="Double points"' in html

    def test_nav_branches(self, client, existing_user):
        anon = client.get("/guide").data.decode()
        assert "Change password" not in anon
        assert "Back to home" in anon and "→" in anon
        assert 'alt="FamQuiz logo"' in anon
        _login(client, existing_user)
        assert "Change password" in client.get("/guide").data.decode()
