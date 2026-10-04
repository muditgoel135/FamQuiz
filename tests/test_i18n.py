"""Tests for Full UI multilingual support (Client 1: 4 languages)."""

import json
import os

import app as app_module
from app import get_locale


def _login(client, existing_user):
    client.post(
        "/login",
        data={
            "email": existing_user["email"],
            "password": existing_user["password"],
        },
    )


def _strings():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "translations.json",
    )
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class TestLocaleResolution:
    def test_default_is_english(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert 'lang="en"' in resp.data.decode()

    def test_lang_param_switches_and_persists(self, client):
        resp = client.get("/?lang=es")
        html = resp.data.decode()
        assert 'lang="es"' in html
        assert "Clasificación" in html  # Leaderboard in Spanish
        # Persisted in session for next request.
        resp2 = client.get("/")
        assert 'lang="es"' in resp2.data.decode()

    def test_all_locales_render(self, client):
        expected = {
            "es": "Clasificación",
            "hi": "लीडरबोर्ड",
            "zh_Hans": "排行榜",
        }
        for locale, token in expected.items():
            resp = client.get(f"/?lang={locale}")
            assert resp.status_code == 200
            html = resp.data.decode()
            assert token in html, locale
        # Invalid param is ignored (session keeps last valid); clear session
        # first to verify true fallback to English.
        with client.session_transaction() as sess:
            sess.pop("locale", None)
        resp = client.get("/?lang=xx")
        assert 'lang="en"' in resp.data.decode()

    def test_user_language_drives_ui(self, client, app, existing_user):
        _login(client, existing_user)
        with app.app_context():
            from app import User, db

            user = User.query.filter_by(email=existing_user["email"]).one()
            user.language = "Hindi"
            db.session.commit()
        # Clear session locale so user preference wins.
        with client.session_transaction() as sess:
            sess.pop("locale", None)
        html = client.get("/").data.decode()
        assert "लीडरबोर्ड" in html

    def test_settings_save_sets_session_locale(self, client, existing_user):
        _login(client, existing_user)
        resp = client.post("/api/settings/save", json={"language": "Spanish"})
        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert sess.get("locale") == "es"
        html = client.get("/settings").data.decode()
        assert "Ajustes" in html or "Clasificación" in html or "Guardar" in html


class TestI18nApi:
    def test_dict_endpoint(self, client):
        for locale in ("es", "hi", "zh_Hans"):
            resp = client.get(f"/api/i18n/{locale}.json")
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["locale"] == locale
            assert isinstance(body["strings"], dict)
            assert len(body["strings"]) > 20
        assert client.get("/api/i18n/xx.json").status_code == 404

    def test_html_lang_matches(self, client):
        assert 'lang="zh-Hans"' in client.get("/?lang=zh_Hans").data.decode()
        assert 'lang="hi"' in client.get("/?lang=hi").data.decode()


class TestQuizLanguage:
    def test_mandarin_adds_simplified_clause(self):
        from types import SimpleNamespace

        user = SimpleNamespace(
            favorite_subject="Space",
            difficulty_level="easy",
            language="Mandarin Chinese",
            grade_occupation="Grade 5",
        )
        prompt = " ".join(m["content"] for m in app_module.build_quiz_messages(user, 1))
        assert "Mandarin Chinese" in prompt
        assert "Simplified" in prompt

    def test_all_languages_in_prompt(self):
        from types import SimpleNamespace

        for lang in ("English", "Spanish", "Hindi", "Mandarin Chinese"):
            user = SimpleNamespace(
                favorite_subject="Space",
                difficulty_level="easy",
                language=lang,
                grade_occupation="Grade 5",
            )
            prompt = " ".join(
                m["content"] for m in app_module.build_quiz_messages(user, 1)
            )
            assert lang in prompt

    def test_get_locale_no_request_context(self):
        # Outside a request, must safely fall back to English.
        assert get_locale() == "en"


class TestTranslatedMails:
    def _set_language(self, app, existing_user, language):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.language = language
            db.session.commit()

    def test_reset_mail_per_recipient_language(self, client, app, existing_user):
        from app import mail

        cases = (
            ("Spanish", "es"),
            ("Hindi", "hi"),
            ("Mandarin Chinese", "zh_Hans"),
            ("English", "en"),
        )
        strings = _strings()
        for language, locale in cases:
            self._set_language(app, existing_user, language)
            with mail.record_messages() as outbox:
                resp = client.post(
                    "/reset", data={"email": existing_user["email"]}
                )
            assert resp.status_code == 200
            assert len(outbox) == 1
            msg = outbox[0]
            assert msg.subject == strings[locale].get(
                "Password reset instructions", "Password reset instructions"
            )
            assert (
                strings[locale].get("Hello,", "Hello,") in (msg.body or "")
            )
            assert (
                strings[locale].get(
                    "Use this link to reset your password:",
                    "Use this link to reset your password:",
                )
                in (msg.body or "")
            )
            assert (
                strings[locale].get("Hello,", "Hello,") in (msg.html or "")
            )

    def test_change_notice_translated(self, client, app, existing_user):
        from app import mail

        self._set_language(app, existing_user, "Hindi")
        _login(client, existing_user)
        strings = _strings()
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
        assert len(outbox) == 1
        msg = outbox[0]
        assert (
            msg.subject
            == strings["hi"].get(
                "Your password has been changed", "Your password has been changed"
            )
        )
        assert (
            strings["hi"].get(
                "Your password has been changed.",
                "Your password has been changed.",
            )
            in (msg.body or "")
        )
