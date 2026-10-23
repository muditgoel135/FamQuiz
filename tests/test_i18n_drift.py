"""Translation-drift tests.

The UI ships four languages. The strings live in ``translations.json``
and are referenced from templates, from ``app.py``/``routes.py`` and
from the client-side JavaScript. A key that is used but missing falls
back to English *silently*, so a Spanish player sees one English label
and nobody notices.

These tests close the gaps the existing completeness scan left open.
"""

import json
import os
import re

import pytest

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
                assert language not in data[locale], (
                    f"'{locale}' translates the language name '{language}'"
                )


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
        fallbacks = re.findall(r"""t\(\s*['"][A-Za-z_]+['"]\s*,\s*['"]([^'"]+)['"]""", source)
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
            assert not pattern.search(source), (
                f"'{key}' is interpolated without |tojson"
            )


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
