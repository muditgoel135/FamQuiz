"""Tests for Full UI multilingual support (Client 1: 4 languages)."""

import json
import os
import re

import pytest

import app as app_module
from app import get_locale


def _login(client, existing_user):
    """
    Log in the fixture user via POST /login.

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


def _strings():
    """
    Load translations.json for assertions.

    :return: Helper value for tests.
    :rtype: object
    """

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "translations.json",
    )
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class TestLocaleResolution:
    def test_default_is_english(self, client):
        """
        Verify default is english.

        :param client: The client fixture.
        """

        resp = client.get("/")
        assert resp.status_code == 200
        assert 'lang="en"' in resp.data.decode()

    def test_lang_param_switches_and_persists(self, client):
        """
        Verify lang param switches and persists.

        :param client: The client fixture.
        """

        resp = client.get("/?lang=es")
        html = resp.data.decode()
        assert 'lang="es"' in html
        assert "Clasificación" in html  # Leaderboard in Spanish
        # Persisted in session for next request.
        resp2 = client.get("/")
        assert 'lang="es"' in resp2.data.decode()

    def test_all_locales_render(self, client):
        """
        Verify all locales render.

        :param client: The client fixture.
        """

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
        """
        Verify user language drives ui.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """

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
        """
        Verify settings save sets session locale.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """

        _login(client, existing_user)
        resp = client.post("/api/settings/save", json={"language": "Spanish"})
        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert sess.get("locale") == "es"
        html = client.get("/settings").data.decode()
        assert "Ajustes" in html or "Clasificación" in html or "Guardar" in html


class TestI18nApi:
    def test_dict_endpoint(self, client):
        """
        Verify dict endpoint.

        :param client: The client fixture.
        """

        for locale in ("es", "hi", "zh_Hans"):
            resp = client.get(f"/api/i18n/{locale}.json")
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["locale"] == locale
            assert isinstance(body["strings"], dict)
            assert len(body["strings"]) > 20
        assert client.get("/api/i18n/xx.json").status_code == 404

    def test_html_lang_matches(self, client):
        """
        Verify html lang matches.

        :param client: The client fixture.
        """

        assert 'lang="zh-Hans"' in client.get("/?lang=zh_Hans").data.decode()
        assert 'lang="hi"' in client.get("/?lang=hi").data.decode()


class TestQuizLanguage:
    def test_mandarin_adds_simplified_clause(self):
        """
        Verify mandarin adds simplified clause.
        """

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
        """
        Verify all languages in prompt.
        """

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
        """
        Verify get locale no request context.
        """

        assert get_locale() == "en"


class TestTranslatedMails:
    def _set_language(self, app, existing_user, language):
        """
        Set a user's language in the test database.

        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        :param language: The language fixture.
        """

        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.language = language
            db.session.commit()

    def test_reset_mail_per_recipient_language(self, client, app, existing_user):
        """
        Verify reset mail per recipient language.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """
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
                resp = client.post("/reset", data={"email": existing_user["email"]})
            assert resp.status_code == 200
            assert len(outbox) == 1
            msg = outbox[0]
            assert msg.subject == strings[locale].get(
                "Password reset instructions", "Password reset instructions"
            )
            assert strings[locale].get("Hello,", "Hello,") in (msg.body or "")
            assert strings[locale].get(
                "Use this link to reset your password:",
                "Use this link to reset your password:",
            ) in (msg.body or "")
            assert strings[locale].get("Hello,", "Hello,") in (msg.html or "")

    def test_change_notice_translated(self, client, app, existing_user):
        """
        Verify change notice translated.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """

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
        assert msg.subject == strings["hi"].get(
            "Your password has been changed", "Your password has been changed"
        )
        assert strings["hi"].get(
            "Your password has been changed.",
            "Your password has been changed.",
        ) in (msg.body or "")


# ==== merged from test_i18n_matrix.py ====
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
        assert (
            "Ajustes" in client.get("/settings?lang=es").data.decode()
            or "Guardar" in client.get("/settings?lang=es").data.decode()
        )
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
        assert (
            'lang="es"'
            in client.get("/", headers={"Accept-Language": "es"}).data.decode()
        )
        assert (
            'lang="hi"'
            in client.get("/", headers={"Accept-Language": "hi"}).data.decode()
        )
        assert (
            'lang="en"'
            in client.get("/", headers={"Accept-Language": "fr"}).data.decode()
        )

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
        import json as _json
        import os as _os

        from app import mail

        with open(
            _os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                "translations.json",
            ),
            encoding="utf-8",
        ) as fh:
            strings = _json.load(fh)
        for lang, loc in [("Spanish", "es"), ("English", "en")]:
            self._set(app, existing_user["email"], lang)
            with mail.record_messages() as outbox:
                client.post("/reset", data={"email": existing_user["email"]})
            assert len(outbox) == 1
            assert outbox[0].subject == strings[loc].get(
                "Password reset instructions", "Password reset instructions"
            )
            assert outbox[0].body
            assert outbox[0].html

    def test_en_verbatim(self, client, app, existing_user):
        from app import mail

        self._set(app, existing_user["email"], "English")
        with mail.record_messages() as outbox:
            client.post("/reset", data={"email": existing_user["email"]})
        assert "Hello," in outbox[0].body
        assert "Use this link to reset your password:" in outbox[0].body


# ==== merged from test_i18n_drift.py ====
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, "templates")
STATIC = os.path.join(ROOT, "static")

LOCALES = ("en", "es", "hi", "zh_Hans")
TRANSLATED_LOCALES = ("es", "hi", "zh_Hans")

# The two point strings that are inserted into a JS string literal.
POINT_KEYS = {"points", "pts"}


def _catalog():
    """Return the parsed translations.json."""
    with open(os.path.join(ROOT, "translations.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _template_files():
    """Return every template file path."""
    found = []
    for base, _dirs, files in os.walk(TEMPLATES):
        for name in files:
            if name.endswith((".html", ".txt")):
                found.append(os.path.join(base, name))
    return found


def _static_js_files():
    """Return every first-party JavaScript file."""
    return [
        os.path.join(STATIC, name)
        for name in sorted(os.listdir(STATIC))
        if name.endswith(".js")
    ]


class TestCatalogShape:
    """The catalog itself must be well formed."""

    def test_all_locales_present(self):
        """Every supported locale needs a catalog."""
        data = _catalog()
        for locale in LOCALES:
            assert locale in data, f"translations.json has no '{locale}'"

    def test_english_catalog_is_empty(self):
        """English is the source language, so it needs no catalog."""
        assert _catalog()["en"] == {}

    def test_catalogs_have_the_same_keys(self):
        """A key missing in one language falls back to English."""
        data = _catalog()
        reference = set(data["es"])
        for locale in ("hi", "zh_Hans"):
            missing = reference - set(data[locale])
            assert not missing, f"'{locale}' is missing {sorted(missing)[:5]}"

    def test_values_are_non_empty(self):
        """An empty translation renders as nothing at all."""
        data = _catalog()
        for locale in TRANSLATED_LOCALES:
            empty = [k for k, v in data[locale].items() if not str(v).strip()]
            assert not empty, f"'{locale}' has empty values: {empty[:5]}"

    def test_file_is_valid_utf8(self):
        """The catalog holds Hindi and Chinese text."""
        with open(os.path.join(ROOT, "translations.json"), "rb") as fh:
            raw = fh.read()
        raw.decode("utf-8")


class TestDynamicKeys:
    """Keys built at runtime are invisible to a literal scan."""

    def test_statuses_are_translated(self):
        """The status dropdown values are translated by value."""
        from routes import SETTINGS_STATUSES

        data = _catalog()
        for locale in TRANSLATED_LOCALES:
            for status in SETTINGS_STATUSES:
                assert status in data[locale], f"'{locale}' has no '{status}'"

    def test_difficulties_are_translated(self):
        """The difficulty dropdown values are translated by value."""
        from app import DIFFICULTY_LEVELS

        data = _catalog()
        for locale in TRANSLATED_LOCALES:
            for level in DIFFICULTY_LEVELS:
                assert level in data[locale], f"'{locale}' has no '{level}'"

    def test_languages_are_rendered_in_their_own_language(self):
        """A language name is never translated into another language."""
        from routes import SETTINGS_LANGUAGES

        # The settings page renders the language names verbatim, so they
        # must *not* be translated: "Hindi" stays "Hindi" in every UI.
        data = _catalog()
        for locale in TRANSLATED_LOCALES:
            for language in SETTINGS_LANGUAGES:
                assert (
                    language not in data[locale]
                ), f"'{locale}' translates the language name '{language}'"


class TestStaticJavaScript:
    """The client-side fallbacks are English literals."""

    def test_notifier_fallbacks_are_translated(self):
        """Every English fallback in the notifier needs a translation.

        ``static/game_notify.js`` calls ``t(key, "English fallback")``.
        When the key is missing the fallback is shown *in English* in a
        Hindi or Chinese UI, and nothing else notices.
        """
        data = _catalog()
        path = os.path.join(STATIC, "game_notify.js")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        fallbacks = re.findall(
            r"""t\(\s*['"][A-Za-z_]+['"]\s*,\s*['"]([^'"]+)['"]""", source
        )
        assert fallbacks, "the notifier no longer has any fallback text"
        missing = []
        for locale in TRANSLATED_LOCALES:
            for text in fallbacks:
                if text not in data[locale]:
                    missing.append((locale, text))
        assert not missing, f"untranslated notifier text: {missing[:5]}"

    def test_static_js_has_no_untranslated_literals(self):
        """No first-party JS file may hard-code user-facing English."""
        data = _catalog()
        pattern = re.compile(r"""t\(\s*['"][A-Za-z_]+['"]\s*,\s*['"]([^'"]+)['"]""")
        for path in _static_js_files():
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            for text in pattern.findall(source):
                for locale in TRANSLATED_LOCALES:
                    assert text in data[locale], f"{os.path.basename(path)}: '{text}'"


class TestTemplateCompleteness:
    """Every ``_("...")`` in a template must exist in every catalog."""

    def test_all_template_keys_are_translated(self):
        """The literal scan covers every template.

        The lookup uses the *raw* string, exactly like
        ``app.translate()`` does at runtime, so a key with trailing
        whitespace must be stored with it.
        """
        data = _catalog()
        pattern = re.compile(r"_\(\s*['\"]([^'\"]+)['\"]\s*\)")
        missing = []
        for path in _template_files():
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            for key in pattern.findall(source):
                for locale in TRANSLATED_LOCALES:
                    if key not in data[locale]:
                        missing.append((os.path.basename(path), locale, key))
        assert not missing, f"untranslated template keys: {missing[:5]}"

    def test_point_keys_are_translated(self):
        """The two point strings must not stay English-only.

        ``templates/gameplay.html`` interpolates the score unit into a
        JavaScript string, so it must go through ``|tojson`` as well.
        """
        data = _catalog()
        for locale in TRANSLATED_LOCALES:
            for key in POINT_KEYS:
                assert key in data[locale], f"'{locale}' has no '{key}'"


class TestPointStringInjection:
    """The score unit is interpolated into a JavaScript literal."""

    def test_points_use_tojson(self):
        """A translated string must never be pasted raw into <script>."""
        path = os.path.join(TEMPLATES, "gameplay.html")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        for key in POINT_KEYS:
            pattern = re.compile(
                r"_\(\s*['\"]" + re.escape(key) + r"['\"]\s*\)(?!\s*\|\s*tojson)"
            )
            assert not pattern.search(
                source
            ), f"'{key}' is interpolated without |tojson"


class TestLocaleRendering:
    """Every locale must render every page."""

    @pytest.mark.parametrize("locale", LOCALES)
    @pytest.mark.parametrize("path", ["/", "/guide", "/leaderboard"])
    def test_public_pages_render_in_every_locale(self, client, locale, path):
        """A missing translation must not break the page."""
        resp = client.get(f"{path}?lang={locale}")
        assert resp.status_code == 200

    @pytest.mark.parametrize("locale", LOCALES)
    def test_the_ui_actually_changes_language(self, client, locale):
        """The language switch must reach the templates."""
        html = client.get(f"/?lang={locale}").get_data(as_text=True)
        expected = {
            "en": "Leaderboard",
            "es": "Clasificación",
            "hi": "लीडरबोर्ड",
            "zh_Hans": "排行榜",
        }[locale]
        assert expected in html

    def test_i18n_endpoint_matches_the_catalog(self, client):
        """The JSON catalog endpoint must serve the same strings."""
        data = _catalog()
        for locale in LOCALES:
            body = client.get(f"/api/i18n/{locale}.json").get_json()
            assert body["locale"] == locale
            assert set(body["strings"]) == set(data[locale])

    def test_unsupported_locale_is_rejected(self, client):
        """An unknown locale must 404 instead of serving English."""
        resp = client.get("/api/i18n/kl.json")
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Unsupported language."}
