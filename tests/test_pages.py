"""Tests for homepage, leaderboard, guide, serving-port and app wiring.

Covers routes.homepage / leaderboard / guide / _serving_port /
inject_theme / inject_i18n / _persist_lang_param / register_routes plus
security headers, cookies and post-auth redirects.
"""

from flask import url_for


def _login(client, existing_user):
    client.post(
        "/login",
        data={
            "email": existing_user["email"],
            "password": existing_user["password"],
        },
    )


def _make_user(app, email, best=0, wins=0, played=0, **kw):
    from flask_security.utils import hash_password
    from app import db, user_datastore

    with app.app_context():
        user_datastore.create_user(email=email, password=hash_password("x" * 12))
        from app import User

        user = User.query.filter_by(email=email).one()
        user.best_score = best
        user.total_wins = wins
        user.total_games_played = played
        for key, value in kw.items():
            setattr(user, key, value)
        db.session.commit()
        return user.id


class TestHomepageAnon:
    def test_200_and_nav(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "<title>FamQuiz</title>" in html
        assert 'lang="en"' in html
        assert "<body" in html
        assert "How to use" in html
        assert "Leaderboard" in html
        assert "Login" in html
        assert "Logout" not in html
        assert 'data-authenticated="0"' in html
        assert 'id="home-start"' in html
        assert "Start game" in html

    def test_empty_board(self, client, app):
        from app import User, db

        with app.app_context():
            assert User.query.count() == 0
        html = client.get("/").data.decode()
        assert "No players yet" in html
        assert "home-rank" not in html
        assert "(You)" not in html

    def test_anon_stats_prompt(self, client):
        html = client.get("/").data.decode()
        assert "Statistics" in html
        assert "Total games played in the family:" in html
        assert "Log in" in html
        assert "to track your stats" in html
        assert "Total games played by you:" not in html
        assert "No. of wins by you:" not in html
        assert "Best score:" not in html

    def test_anon_defaults(self, client):
        html = client.get("/").data.decode()
        assert 'id="home-num"' in html
        assert 'value="10"' in html
        assert 'max="20"' in html
        assert 'id="home-difficulty"' in html
        assert "Choose difficulty level" in html
        assert 'id="home-powerups"' in html
        assert "checked" in html
        assert 'id="home-wait"' in html
        assert 'value="300"' in html
        assert 'id="home-error"' in html
        assert 'id="game-notify"' in html


class TestHomepageAuthed:
    def test_nav(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/").data.decode()
        assert 'data-authenticated="1"' in html
        assert "Logout" in html
        assert "Settings" in html
        assert "home-avatar" in html
        assert 'id="game-notify"' in html

    def test_stats_values(self, client, app, existing_user):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.total_games_played = 7
            user.total_wins = 3
            user.best_score = 12345
            user.total_powerups_used = 9
            user.most_used_powerup = "Double Points"
            db.session.commit()
        _login(client, existing_user)
        html = client.get("/").data.decode()
        assert "Total games played by you:" in html
        assert "No. of wins by you:" in html
        assert "12,345" in html
        assert "Total no. of powerups used:" in html
        assert "Double Points" in html

    def test_family_sums(self, client, app, existing_user):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.total_games_played = 5
            db.session.commit()
        _make_user(app, "s2@example.com", played=8)
        _login(client, existing_user)
        html = client.get("/").data.decode()
        # Family total 13 present; own total 5 present.
        assert "13" in html
        assert "Total games played by you:" in html

    def test_num_clamping(self, client, app, existing_user):
        from app import User, db

        _login(client, existing_user)
        for raw, expected in [(999, 'value="20"'), (0, 'value="10"'), (-5, 'value="1"')]:
            with app.app_context():
                user = User.query.filter_by(email=existing_user["email"]).one()
                user.default_num_questions = raw
                db.session.commit()
            html = client.get("/").data.decode()
            assert expected in html

    def test_difficulty_selected(self, client, app, existing_user):
        from app import User, db

        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.difficulty_level = " HARD "
            db.session.commit()
        html = client.get("/").data.decode()
        assert '<option value="hard" selected>' in html
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.difficulty_level = ""
            db.session.commit()
        html = client.get("/").data.decode()
        assert "Choose difficulty level" in html

    def test_avatar_initial(self, client, app, existing_user):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.display_name = " Alice "
            db.session.commit()
        _login(client, existing_user)
        html = client.get("/").data.decode()
        assert ">A<" in html or '"A"' in html or "Your profile" in html

    def test_em_dash_default(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/").data.decode()
        assert "Most-used powerup:" in html
        assert "—" in html


class TestHomepageLeaderboard:
    def test_top3_ordering(self, client, app, existing_user):
        from app import User, db

        with app.app_context():
            me = User.query.filter_by(email=existing_user["email"]).one()
            me.display_name = "MeD"
            me.best_score = 50
            me.total_wins = 20
            db.session.commit()
        _make_user(app, "a@example.com", best=100, wins=5, display_name="Aaa")
        _make_user(app, "b@example.com", best=200, wins=1, display_name="Bbb")
        _make_user(app, "c@example.com", best=200, wins=10, display_name="Ccc")
        _login(client, existing_user)
        html = client.get("/").data.decode()
        assert "#1" in html and "#2" in html and "#3" in html
        # C (200/10) before B (200/1) before A (100/5).
        assert html.index("Ccc") < html.index("Bbb") < html.index("Aaa")

    def test_is_you(self, client, app, existing_user):
        _make_user(app, "other@example.com", best=1)
        _login(client, existing_user)
        html = client.get("/").data.decode()
        assert "(You)" in html
        assert html.count("(You)") == 1

    def test_anon_no_you(self, client, app):
        _make_user(app, "u1@example.com", best=10, display_name="U1")
        _make_user(app, "u2@example.com", best=5, display_name="U2")
        html = client.get("/").data.decode()
        assert "(You)" not in html

    def test_dot_matrix(self, client, app):
        _make_user(app, "r@example.com", best=300, status="Ready to play",
                   display_name="Rr")
        _make_user(app, "d@example.com", best=200, status="Do not disturb",
                   display_name="Dd")
        _make_user(app, "o@example.com", best=100, status="offline",
                   display_name="Oo")
        html = client.get("/").data.decode()
        assert "home-dot-ready" in html
        assert "home-dot-busy" in html
        assert "home-dot-offline" in html

    def test_name_fallbacks(self, client, app):
        _make_user(app, "n1@example.com", best=300, display_name="Bob")
        _make_user(app, "n2@example.com", best=200, nickname="Bobby")
        _make_user(app, "charlie99@example.com", best=100)
        html = client.get("/").data.decode()
        assert "Bob" in html
        assert "Bobby" in html
        assert "charlie99" in html


class TestLeaderboardPage:
    def test_anon_full(self, client, app):
        _make_user(app, "l1@example.com", best=5000, display_name="Big")
        _make_user(app, "l2@example.com", best=300, display_name="Small")
        resp = client.get("/leaderboard")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Leaderboard" in html
        assert "5,000" in html
        assert "pts" in html
        assert "#1" in html and "#2" in html
        assert "(You)" not in html
        assert 'id="game-notify"' in html

    def test_authed_you(self, client, app, existing_user):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.display_name = "Me"
            user.best_score = 9999
            db.session.commit()
        _make_user(app, "lo@example.com", best=100, display_name="Other")
        _login(client, existing_user)
        html = client.get("/leaderboard").data.decode()
        assert "Me" in html
        assert "(You)" in html
        assert html.count("(You)") == 1
        assert "9,999" in html

    def test_ordering_full_list(self, client, app, existing_user):
        from app import User, db

        with app.app_context():
            me = User.query.filter_by(email=existing_user["email"]).one()
            me.display_name = "MeD"
            me.best_score = 50
            me.total_wins = 20
            db.session.commit()
        _make_user(app, "a@example.com", best=100, wins=5, display_name="Aaa")
        _make_user(app, "b@example.com", best=200, wins=1, display_name="Bbb")
        _make_user(app, "c@example.com", best=200, wins=10, display_name="Ccc")
        html = client.get("/leaderboard").data.decode()
        assert html.index("Ccc") < html.index("Bbb") < html.index("Aaa")
        assert "#4" in html  # full list, unlike homepage top-3

    def test_empty(self, client, app):
        from app import User, db

        with app.app_context():
            assert User.query.count() == 0
        html = client.get("/leaderboard").data.decode()
        assert "No players yet" in html
        assert "board-list" not in html

    def test_dot_status(self, client, app):
        _make_user(app, "r@example.com", best=300, status="Ready to play",
                   display_name="Rr")
        _make_user(app, "d@example.com", best=200, status="Do not disturb",
                   display_name="Dd")
        html = client.get("/leaderboard").data.decode()
        assert "home-dot-ready" in html
        assert "home-dot-busy" in html

    def test_no_login_required(self, client):
        assert client.get("/leaderboard").status_code == 200


class TestGuidePage:
    def test_sections(self, client):
        html = client.get("/guide").data.decode()
        assert "Welcome to FamQuiz!" in html
        assert "Join the family game" in html
        assert "Play and score" in html
        assert "Changing your settings" in html
        assert "Your settings and data" in html
        assert "If it looks wrong" in html
        assert "1500 points" in html
        assert "1 in 3" in html
        assert "tap Join!" in html
        assert html.count("<code>:") == 2
        assert 'id="game-notify"' in html

    def test_port_default(self, client, monkeypatch):
        monkeypatch.delenv("PORT", raising=False)
        html = client.get("/guide", base_url="http://localhost").data.decode()
        assert "<code>:5000</code>" in html

    def test_port_host(self, client, monkeypatch):
        monkeypatch.setenv("PORT", "5000")
        html = client.get(
            "/guide", headers={"Host": "example.com:4321"}
        ).data.decode()
        assert "<code>:4321</code>" in html
        assert "<code>:5000</code>" not in html

    def test_port_env(self, client, monkeypatch):
        monkeypatch.setenv("PORT", "8765")
        html = client.get("/guide", base_url="http://example.com/guide").data.decode()
        assert "<code>:8765</code>" in html

    def test_no_login(self, client):
        assert client.get("/guide").status_code == 200


class TestServingPort:
    def test_host_wins(self, app, monkeypatch):
        from routes import _serving_port

        monkeypatch.setenv("PORT", "5000")
        with app.test_request_context("/", headers={"Host": "example.com:1234"}):
            assert _serving_port() == 1234

    def test_env_fallback(self, app, monkeypatch):
        from routes import _serving_port

        monkeypatch.setenv("PORT", "8765")
        with app.test_request_context("/", base_url="http://example.com/"):
            assert _serving_port() == 8765

    def test_default(self, app, monkeypatch):
        from routes import _serving_port

        monkeypatch.delenv("PORT", raising=False)
        with app.test_request_context("/", base_url="http://localhost/"):
            assert _serving_port() == 5000

    def test_invalid_host(self, app, monkeypatch):
        from routes import _serving_port

        monkeypatch.setenv("PORT", "8765")
        for host in (
            "example.com:notaport",
            "example.com:0",
            "example.com:99999",
            "example.com:",
        ):
            with app.test_request_context("/", headers={"Host": host}):
                assert _serving_port() == 8765

    def test_garbage_env(self, app, monkeypatch):
        from routes import _serving_port

        for val in ("abc", "0", "70000", ""):
            monkeypatch.setenv("PORT", val)
            with app.test_request_context("/", base_url="http://example.com/"):
                assert _serving_port() == 5000

    def test_flask_run_style(self, app, monkeypatch):
        from routes import _serving_port

        monkeypatch.setenv("PORT", "5000")
        with app.test_request_context("/", headers={"Host": "192.168.1.5:1234"}):
            assert _serving_port() == 1234


class TestInjectTheme:
    def test_anon(self, app):
        from routes import inject_theme

        with app.test_request_context("/"):
            assert inject_theme() == {"theme_class": ""}

    def test_light(self, client, app, existing_user):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.theme_mode = "light"
            db.session.commit()
        _login(client, existing_user)
        html = client.get("/").data.decode()
        assert "theme-dark" not in html

    def test_dark(self, client, app, existing_user):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.theme_mode = "dark"
            db.session.commit()
        _login(client, existing_user)
        for path in ("/", "/guide", "/leaderboard"):
            assert "theme-dark" in client.get(path).data.decode()

    def test_none_defaults(self, client, app, existing_user):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.theme_mode = None
            db.session.commit()
        _login(client, existing_user)
        assert "theme-dark" not in client.get("/").data.decode()


class TestInjectI18n:
    def test_keys_en(self, app):
        from routes import inject_i18n

        with app.test_request_context("/?lang=en"):
            data = inject_i18n()
        assert set(data) == {
            "_",
            "current_locale",
            "html_lang",
            "supported_locales",
            "locale_to_language",
        }
        assert data["current_locale"] == "en"
        assert data["html_lang"] == "en"
        assert data["supported_locales"] == ["en", "es", "hi", "zh_Hans"]
        assert data["locale_to_language"]["es"] == "Spanish"
        assert data["_"]("Leaderboard") == "Leaderboard"

    def test_zh_hans(self, app):
        from routes import inject_i18n

        with app.test_request_context("/?lang=zh_Hans"):
            data = inject_i18n()
        assert data["current_locale"] == "zh_Hans"
        assert data["html_lang"] == "zh-Hans"

    def test_es_hi(self, app):
        from routes import inject_i18n

        for loc in ("es", "hi"):
            with app.test_request_context(f"/?lang={loc}"):
                data = inject_i18n()
            assert data["current_locale"] == loc
            assert data["html_lang"] == loc


class TestPersistLang:
    def test_valid(self, client):
        assert client.get("/?lang=es").status_code == 200
        assert 'lang="es"' in client.get("/?lang=es").data.decode()
        with client.session_transaction() as sess:
            assert sess.get("locale") == "es"
        assert 'lang="es"' in client.get("/").data.decode()

    def test_invalid_ignored(self, client):
        with client.session_transaction() as sess:
            sess.pop("locale", None)
        assert 'lang="en"' in client.get("/?lang=xx").data.decode()
        with client.session_transaction() as sess:
            assert sess.get("locale") != "xx"

    def test_invalid_keeps_prior(self, client):
        client.get("/?lang=hi")
        assert 'lang="hi"' in client.get("/?lang=xx").data.decode()

    def test_no_param_keeps(self, client):
        client.get("/?lang=es")
        assert 'lang="es"' in client.get("/").data.decode()


class TestRegisterRoutes:
    def test_endpoints(self, app):
        rules = {}
        for rule in app.url_map.iter_rules():
            methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
            rules[rule.endpoint] = (rule.rule, methods)
        assert rules["homepage"][0] == "/"
        assert rules["guide"][0] == "/guide"
        assert rules["leaderboard"][0] == "/leaderboard"
        assert rules["gameplay"][0] == "/gameplay"
        assert rules["settings_save"] == ("/api/settings/save", ["POST"])
        assert rules["account_erase_data"] == ("/api/account/erase-data", ["POST"])
        assert rules["account_delete"] == ("/api/account", ["DELETE"])
        assert rules["quiz_generate"] == ("/api/quiz/generate", ["POST"])
        assert rules["quiz_state"] == ("/api/quiz/state", ["GET"])
        assert rules["quiz_answer"] == ("/api/quiz/answer", ["POST"])
        assert rules["quiz_powerup"] == ("/api/quiz/powerup", ["POST"])
        assert rules["quiz_finish"] == ("/api/quiz/finish", ["POST"])
        assert rules["quiz_quit"] == ("/api/quiz/quit", ["POST"])
        assert rules["game_start"] == ("/api/game/start", ["POST"])
        assert rules["game_status"] == ("/api/game/status", ["GET"])
        assert rules["game_join"] == ("/api/game/join", ["POST"])
        assert rules["game_cancel"] == ("/api/game/cancel", ["POST"])
        assert rules["game_events"] == ("/api/game/events", ["GET"])

    def test_url_for(self, app):
        with app.test_request_context():
            assert url_for("homepage") == "/"
            assert url_for("guide") == "/guide"
            assert url_for("leaderboard") == "/leaderboard"
            assert url_for("gameplay") == "/gameplay"
            assert url_for("settings") == "/settings"
            assert url_for("i18n_dict", locale="es") == "/api/i18n/es.json"

    def test_processors(self, app):
        names = [
            fn.__name__
            for fns in app.template_context_processors.get(None, [])
            for fn in ([fns] if callable(fns) else [])
        ]
        assert "inject_theme" in names
        assert "inject_i18n" in names
        before = app.before_request_funcs.get(None, [])
        assert any(getattr(fn, "__name__", "") == "_persist_lang_param" for fn in before)

    def test_method_not_allowed(self, client, existing_user):
        _login(client, existing_user)
        assert client.post("/").status_code == 405
        assert client.get("/api/settings/save").status_code == 405
        assert client.get("/api/account/erase-data").status_code == 405
        assert client.get("/api/account").status_code == 405
        assert client.get("/api/quiz/generate").status_code == 405
        assert client.get("/api/quiz/answer").status_code == 405
        assert client.get("/api/game/start").status_code == 405
        assert client.get("/api/game/join").status_code == 405
        assert client.get("/api/game/cancel").status_code == 405


class TestSecurity:
    def test_headers_pages(self, client, existing_user):
        for path in ("/", "/guide", "/leaderboard", "/login", "/register"):
            resp = client.get(path)
            assert resp.headers.get("X-Frame-Options") == "DENY", path
            assert resp.headers.get("X-Content-Type-Options") == "nosniff", path
            assert resp.headers.get("Referrer-Policy") == "same-origin", path
        _login(client, existing_user)
        for path in ("/", "/gameplay", "/settings", "/api/game/status"):
            resp = client.get(path)
            assert resp.headers.get("X-Frame-Options") == "DENY", path

    def test_headers_api_and_404(self, client, existing_user):
        _login(client, existing_user)
        resp = client.post("/api/game/start", json={})
        assert resp.headers.get("X-Frame-Options") == "DENY"
        resp = client.get("/nonexistent-xyz")
        assert resp.status_code == 404
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_cookie_config(self, app):
        assert app.config["SESSION_COOKIE_HTTPONLY"] is True
        assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
        assert app.config["REMEMBER_COOKIE_HTTPONLY"] is True
        assert app.config["REMEMBER_COOKIE_SAMESITE"] == "Lax"

    def test_login_cookie_flags(self, client, existing_user):
        resp = client.post(
            "/login",
            data={
                "email": existing_user["email"],
                "password": existing_user["password"],
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        cookies = resp.headers.getlist("Set-Cookie")
        joined = "; ".join(cookies).lower()
        assert "httponly" in joined
        assert "samesite=lax" in joined

    def test_post_views(self, app):
        assert app.config["SECURITY_POST_LOGIN_VIEW"] == "/"
        assert app.config["SECURITY_POST_LOGOUT_VIEW"] == "/"
        assert app.config["SECURITY_POST_REGISTER_VIEW"] == "/"
        assert app.config["SECURITY_POST_RESET_VIEW"] == "/"
        assert app.config["SECURITY_POST_CHANGE_VIEW"] == "/"
        assert "GET" in app.config["SECURITY_LOGOUT_METHODS"]
        assert "POST" in app.config["SECURITY_LOGOUT_METHODS"]

    def test_login_redirect(self, client, existing_user):
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
        assert client.get("/gameplay").status_code == 200

    def test_logout_both_methods(self, client, existing_user):
        _login(client, existing_user)
        resp = client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"
        _login(client, existing_user)
        resp = client.post("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert client.get("/gameplay").status_code == 302

    def test_next_honoured(self, client):
        resp = client.get("/gameplay", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/login?next=")
        assert "gameplay" in resp.headers["Location"]
