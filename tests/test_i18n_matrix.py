"""i18n matrix: per-locale page renders, negotiation, mail parity."""

import app as app_module


def _login(client, existing_user):
    client.post(
        "/login",
        data={
            "email": existing_user["email"],
            "password": existing_user["password"],
        },
    )


class TestPerLocalePages:
    def test_home(self, client):
        assert "Clasificaci" in client.get("/?lang=es").data.decode()
        assert "लीडरबोर्ड" in client.get("/?lang=hi").data.decode()
        assert "排行榜" in client.get("/?lang=zh_Hans").data.decode()
        assert 'lang="zh-Hans"' in client.get("/?lang=zh_Hans").data.decode()

    def test_guide(self, client):
        assert "Bienvenido" in client.get("/guide?lang=es").data.decode()
        assert 'lang="es"' in client.get("/guide?lang=es").data.decode()

    def test_leaderboard(self, client):
        assert "Clasificaci" in client.get("/leaderboard?lang=es").data.decode()

    def test_settings(self, client, existing_user):
        _login(client, existing_user)
        assert "Ajustes" in client.get("/settings?lang=es").data.decode() or \
            "Guardar" in client.get("/settings?lang=es").data.decode()
        assert 'lang="hi"' in client.get("/settings?lang=hi").data.decode()

    def test_gameplay(self, client, existing_user):
        _login(client, existing_user)
        html = client.get("/gameplay?lang=es").data.decode()
        assert 'lang="es"' in html
        assert "Salir" in html or "Puntos" in html or "Question" in html

    def test_auth(self, client):
        assert "Iniciar sesi" in client.get("/login?lang=es").data.decode()
        assert 'lang="hi"' in client.get("/register?lang=hi").data.decode()

    def test_notifier(self, client):
        html = client.get("/?lang=es").data.decode()
        assert "Unirse" in html or " وخ" in html or "Join" in html


class TestNegotiation:
    def test_accept_header(self, client):
        assert 'lang="es"' in client.get(
            "/", headers={"Accept-Language": "es"}).data.decode()
        assert 'lang="hi"' in client.get(
            "/", headers={"Accept-Language": "hi"}).data.decode()
        assert 'lang="en"' in client.get(
            "/", headers={"Accept-Language": "fr"}).data.decode()

    def test_session_beats_user(self, client, app, existing_user):
        from app import User, db

        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.language = "Hindi"
            db.session.commit()
        with client.session_transaction() as sess:
            sess["locale"] = "es"
        assert 'lang="es"' in client.get("/").data.decode()

    def test_user_beats_header(self, client, app, existing_user):
        from app import User, db

        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.language = "Hindi"
            db.session.commit()
        with client.session_transaction() as sess:
            sess.pop("locale", None)
        html = client.get("/", headers={"Accept-Language": "es"}).data.decode()
        assert "लीडरबोर्ड" in html

    def test_lang_persist_invalid(self, client):
        client.get("/?lang=es")
        assert 'lang="es"' in client.get("/").data.decode()
        # invalid keeps prior valid
        assert 'lang="es"' in client.get("/?lang=xx").data.decode()

    def test_fallbacks(self):
        assert app_module.get_locale() == "en"
        assert app_module.translate("Hello,", "xx") == "Hello,"
        assert app_module.translate("", "es") == ""


class TestMailExtended:
    def _set(self, app, email, lang):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=email).one()
            user.language = lang
            db.session.commit()

    def test_reset_subjects(self, client, app, existing_user):
        from app import mail
        import json as _json
        import os as _os

        with open(_os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
            "translations.json"), encoding="utf-8") as fh:
            strings = _json.load(fh)
        for lang, loc in [("Spanish", "es"), ("English", "en")]:
            self._set(app, existing_user["email"], lang)
            with mail.record_messages() as outbox:
                client.post("/reset", data={"email": existing_user["email"]})
            assert len(outbox) == 1
            assert outbox[0].subject == strings[loc].get(
                "Password reset instructions", "Password reset instructions")
            assert outbox[0].body
            assert outbox[0].html

    def test_en_verbatim(self, client, app, existing_user):
        from app import mail

        self._set(app, existing_user["email"], "English")
        with mail.record_messages() as outbox:
            client.post("/reset", data={"email": existing_user["email"]})
        assert "Hello," in outbox[0].body
        assert "Use this link to reset your password:" in outbox[0].body
