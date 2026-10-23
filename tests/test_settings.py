"""Tests for the settings page (3-card layout + save/erase/delete APIs)."""

import pytest

from app import MAX_QUIZ_QUESTIONS, GameSession, User, db
from routes import (
    SETTINGS_GRADES,
    SETTINGS_LANGUAGES,
    SETTINGS_STATUSES,
    SETTINGS_THEMES,
)


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


class TestSettingsPage:
    def test_requires_login(self, client):
        """
        Verify requires login.

        :param client: The client fixture.
        """

        resp = client.get("/settings", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/login?next=")

    def test_loads_three_cards_single_save(self, client, existing_user):
        """
        Verify loads three cards single save.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """

        _login(client, existing_user)
        resp = client.get("/settings")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Profile &amp; Preferences" in html or "Profile & Preferences" in html
        assert "Accessibility" in html
        assert "Accessiblity" not in html
        assert "Subscription" in html
        assert "Remove Data" in html
        # No API-key section, no per-card Apply; single Save.
        assert "Ollama API key" not in html
        assert "Enter Ollama API key" not in html
        assert html.count('type="submit"') == 1
        # Quiz-affecting controls live here and are consumed by gameplay.
        assert 'id="settings-difficulty"' in html
        assert 'id="settings-num"' in html
        assert 'id="settings-status"' in html

    def test_save_persists_all_cards(self, client, app, existing_user):
        """
        Verify save persists all cards.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """

        _login(client, existing_user)
        resp = client.post(
            "/api/settings/save",
            json={
                "display_name": "Test Player",
                "nickname": "Tester",
                "grade_occupation": "College",
                "favorite_subject": "Math",
                "language": "Hindi",
                "theme_mode": "dark",
                "game_reminders": False,
                "difficulty_level": "hard",
                "default_num_questions": 5,
                "status": "Do not disturb",
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.display_name == "Test Player"
            assert user.nickname == "Tester"
            assert user.grade_occupation == "College"
            assert user.favorite_subject == "Math"
            assert user.language == "Hindi"
            assert user.theme_mode == "dark"
            assert user.game_reminders is False
            assert user.difficulty_level == "hard"
            assert user.default_num_questions == 5
            assert user.status == "Do not disturb"

    def test_save_rejects_bad_language(self, client, existing_user):
        """
        Verify save rejects bad language.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """

        _login(client, existing_user)
        resp = client.post("/api/settings/save", json={"language": "Klingon"})
        assert resp.status_code == 400

    def test_save_rejects_bad_theme(self, client, existing_user):
        """
        Verify save rejects bad theme.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """

        _login(client, existing_user)
        resp = client.post("/api/settings/save", json={"theme_mode": "neon"})
        assert resp.status_code == 400

    def test_save_rejects_bad_game_fields(self, client, app, existing_user):
        """
        Verify save rejects bad game fields.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """

        _login(client, existing_user)
        for bad in (
            {"difficulty_level": "extreme"},
            {"default_num_questions": 0},
            {"default_num_questions": 999},
            {"default_num_questions": "many"},
            {"status": "invisible"},
        ):
            assert client.post("/api/settings/save", json=bad).status_code == 400

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert (user.difficulty_level or "medium") == "medium"
            assert (user.default_num_questions or 10) == 10

    def test_settings_values_round_trip_to_form(self, client, app, existing_user):
        """
        Verify settings values round trip to form.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """

        _login(client, existing_user)
        resp = client.post(
            "/api/settings/save",
            json={
                "difficulty_level": "easy",
                "default_num_questions": 7,
                "status": "offline",
                "theme_mode": "dark",
            },
        )
        assert resp.status_code == 200
        html = client.get("/settings").data.decode()
        assert '<option value="easy" selected>' in html
        assert 'value="7"' in html
        assert '<option value="offline" selected>' in html
        assert 'class="theme-dark"' in html

    def test_erase_resets_stats_keeps_account(self, client, app, existing_user):
        """
        Verify erase resets stats keeps account.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """

        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.best_score = 1500
            user.total_games_played = 4
            user.total_wins = 2
            user.total_powerups_used = 3
            user.most_used_powerup = "50:50"
            db.session.commit()

        resp = client.post("/api/account/erase-data")
        assert resp.status_code == 200
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user is not None
            assert user.best_score == 0
            assert user.total_games_played == 0
            assert user.total_wins == 0
            assert user.total_powerups_used == 0
            assert user.most_used_powerup is None

    def test_delete_removes_account(self, client, app, existing_user):
        """
        Verify delete removes account.

        :param client: The client fixture.
        :param app: The app fixture.
        :param existing_user: The existing_user fixture.
        """

        _login(client, existing_user)
        assert client.get("/gameplay").status_code == 200
        resp = client.delete("/api/account")
        assert resp.status_code == 200
        with app.app_context():
            assert User.query.filter_by(email=existing_user["email"]).count() == 0
        # Logged out: gated page redirects again.
        assert client.get("/gameplay").status_code == 302


# ==== merged from test_settings_matrix.py ====
def _login(client, existing_user):
    client.post(
        "/login",
        data={
            "email": existing_user["email"],
            "password": existing_user["password"],
        },
    )


def _save(client, payload):
    return client.post("/api/settings/save", json=payload)


class TestSettingsMatrix:
    def test_display_name(self, client, existing_user):
        _login(client, existing_user)
        assert _save(client, {"display_name": 123}).status_code == 400
        assert _save(client, {"display_name": "x" * 81}).status_code == 400
        assert _save(client, {"display_name": "  spaced   out  "}).status_code == 200
        assert _save(client, {"display_name": ""}).status_code == 200

    def test_nickname_grade_subject(self, client, existing_user):
        _login(client, existing_user)
        assert _save(client, {"nickname": 123}).status_code == 400
        assert _save(client, {"grade_occupation": 123}).status_code == 400
        assert _save(client, {"favorite_subject": "x" * 81}).status_code == 400
        assert _save(client, {"grade_occupation": "Grade 5"}).status_code == 200
        assert (
            _save(client, {"favorite_subject": "  Math   Science "}).status_code == 200
        )

    def test_language(self, client, existing_user):
        _login(client, existing_user)
        for lang, loc in [
            ("English", "en"),
            ("Spanish", "es"),
            ("Hindi", "hi"),
            ("Mandarin Chinese", "zh_Hans"),
        ]:
            assert _save(client, {"language": lang}).status_code == 200
            with client.session_transaction() as sess:
                assert sess.get("locale") == loc
        for bad in ("Klingon", "", "spanish", None, 123):
            resp = _save(client, {"language": bad})
            assert resp.status_code == 400
            assert "language" in resp.get_json()["fields"]

    def test_theme(self, client, existing_user):
        _login(client, existing_user)
        assert _save(client, {"theme_mode": "light"}).status_code == 200
        assert _save(client, {"theme_mode": "dark"}).status_code == 200
        for bad in ("neon", "", "Dark", None, 123):
            resp = _save(client, {"theme_mode": bad})
            assert resp.status_code == 400

    def test_reminders(self, client, existing_user):
        _login(client, existing_user)
        assert _save(client, {"game_reminders": True}).status_code == 200
        assert _save(client, {"game_reminders": False}).status_code == 200
        for bad in ("true", 1, 0, None):
            resp = _save(client, {"game_reminders": bad})
            assert resp.status_code == 400
            assert "game_reminders" in resp.get_json()["fields"]

    def test_difficulty(self, client, existing_user):
        _login(client, existing_user)
        for good in ("easy", "Easy", " MEDIUM "):
            assert _save(client, {"difficulty_level": good}).status_code == 200
        for bad in ("extreme", "", None, 123, True):
            resp = _save(client, {"difficulty_level": bad})
            assert resp.status_code == 400

    def test_num(self, client, existing_user):
        _login(client, existing_user)
        assert _save(client, {"default_num_questions": 1}).status_code == 200
        assert _save(client, {"default_num_questions": 20}).status_code == 200
        assert _save(client, {"default_num_questions": "7"}).status_code == 200
        for bad in (0, 21, 999, -1, 5.5, "many", True, False, None, "", []):
            resp = _save(client, {"default_num_questions": bad})
            assert resp.status_code == 400, bad
            assert "default_num_questions" in resp.get_json()["fields"]

    def test_status(self, client, existing_user):
        _login(client, existing_user)
        for good in ("Ready to play", "Do not disturb", "offline"):
            assert _save(client, {"status": good}).status_code == 200
        for bad in ("invisible", "", "ready to play", None, 123):
            resp = _save(client, {"status": bad})
            assert resp.status_code == 400

    def test_multi_error_atomic(self, client, app, existing_user):
        _login(client, existing_user)
        resp = _save(
            client,
            {
                "language": "Klingon",
                "theme_mode": "neon",
                "difficulty_level": "extreme",
                "status": "invisible",
                "default_num_questions": 999,
            },
        )
        assert resp.status_code == 400
        fields = resp.get_json()["fields"]
        assert set(fields) >= {
            "language",
            "theme_mode",
            "difficulty_level",
            "status",
            "default_num_questions",
        }
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert (user.difficulty_level or "medium") == "medium"

    def test_partial_keeps(self, client, app, existing_user):
        from app import db

        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.display_name = "Keep"
            db.session.commit()
        assert _save(client, {"difficulty_level": "easy"}).status_code == 200
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.display_name == "Keep"
            assert user.difficulty_level == "easy"

    def test_requires_login(self, client):
        assert client.post("/api/settings/save", json={}).status_code in (302, 401)
        assert client.post("/api/account/erase-data").status_code in (302, 401)
        assert client.delete("/api/account").status_code in (302, 401)

    def test_locale_immediate(self, client, existing_user):
        _login(client, existing_user)
        _save(client, {"language": "Spanish"})
        with client.session_transaction() as sess:
            assert sess.get("locale") == "es"
        assert (
            "Guardar" in client.get("/settings").data.decode()
            or "Ajustes" in client.get("/settings").data.decode()
        )

    def test_per_locale(self, client, existing_user):
        _login(client, existing_user)
        assert (
            "Ajustes" in client.get("/settings?lang=es").data.decode()
            or "Guardar" in client.get("/settings?lang=es").data.decode()
        )
        assert 'lang="hi"' in client.get("/settings?lang=hi").data.decode()
        assert 'lang="zh-Hans"' in client.get("/settings?lang=zh_Hans").data.decode()

    def test_erase_clears_session(self, client, existing_user, monkeypatch):
        import json as _json
        from types import SimpleNamespace

        import app as app_module

        _login(client, existing_user)

        class _F:
            def chat(self, model="", messages=None, **kwargs):
                content = _json.dumps(
                    {
                        "questions": [
                            {
                                "question": "Q?",
                                "options": ["A", "B", "C", "D"],
                                "answer_index": 0,
                            }
                        ]
                    }
                )
                return SimpleNamespace(message=SimpleNamespace(content=content))

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _F())
        client.post("/api/quiz/generate", json={"num_questions": 1})
        assert client.post("/api/account/erase-data").get_json() == {"ok": True}
        with client.session_transaction() as sess:
            assert "quiz" not in sess
        with client.app_context() if hasattr(client, "app_context") else _noop():
            pass

    def test_redirect_pin(self, client):
        resp = client.get("/settings", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/login?next=")
        assert "settings" in resp.headers["Location"]


def _noop():
    import contextlib

    return contextlib.nullcontext()


# ==== merged from test_settings_contract.py ====
INVALID = "Invalid settings."


def _login(client, existing_user):
    """Log a user in through the real login form."""
    client.post(
        "/login",
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


def _save(client, payload):
    """POST a settings payload and return the response."""
    return client.post("/api/settings/save", json=payload)


class TestFieldErrors:
    """Every field must report a specific, stable error message."""

    def test_envelope_shape(self, client, existing_user):
        """A rejected save returns ``error`` plus a ``fields`` mapping."""
        _login(client, existing_user)
        resp = _save(client, {"display_name": 123})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["error"] == INVALID
        assert isinstance(body["fields"], dict)
        assert "display_name" in body["fields"]

    def test_non_string_field(self, client, existing_user):
        """A number is not a name."""
        _login(client, existing_user)
        body = _save(client, {"display_name": 123}).get_json()
        assert body["fields"]["display_name"] == "must be a string"

    def test_too_long_field(self, client, existing_user):
        """Names are capped at 80 characters."""
        _login(client, existing_user)
        body = _save(client, {"display_name": "x" * 81}).get_json()
        assert body["fields"]["display_name"] == "must be at most 80 characters"

    def test_exactly_80_is_accepted(self, client, existing_user):
        """The cap is inclusive."""
        _login(client, existing_user)
        resp = _save(client, {"display_name": "x" * 80})
        assert resp.status_code == 200
        assert resp.get_json()["settings"]["display_name"] == "x" * 80

    @pytest.mark.parametrize(
        "field", ["display_name", "nickname", "grade_occupation", "favorite_subject"]
    )
    def test_all_string_fields_are_validated(self, client, existing_user, field):
        """Every free-text field has the same rules."""
        _login(client, existing_user)
        body = _save(client, {field: 5}).get_json()
        assert body["fields"][field] == "must be a string"

    def test_bad_language(self, client, existing_user):
        """Only the four supported languages are accepted."""
        _login(client, existing_user)
        body = _save(client, {"language": "Klingon"}).get_json()
        assert body["fields"]["language"] == (
            "must be one of: " + ", ".join(SETTINGS_LANGUAGES)
        )

    def test_bad_theme(self, client, existing_user):
        """Only light and dark are themes."""
        _login(client, existing_user)
        body = _save(client, {"theme_mode": "neon"}).get_json()
        assert body["fields"]["theme_mode"] == "must be 'light' or 'dark'"

    def test_non_boolean_reminder(self, client, existing_user):
        """A reminder toggle is a boolean, not the string "yes"."""
        _login(client, existing_user)
        body = _save(client, {"game_reminders": "yes"}).get_json()
        assert body["fields"]["game_reminders"] == "must be true or false"

    def test_non_string_difficulty(self, client, existing_user):
        """A difficulty is a string."""
        _login(client, existing_user)
        body = _save(client, {"difficulty_level": 123}).get_json()
        assert body["fields"]["difficulty_level"] == "must be a string"

    def test_unknown_difficulty(self, client, existing_user):
        """Only easy, medium and hard are difficulties."""
        _login(client, existing_user)
        body = _save(client, {"difficulty_level": "extreme"}).get_json()
        assert (
            body["fields"]["difficulty_level"] == "must be one of: easy, medium, hard"
        )

    @pytest.mark.parametrize("value", [True, False, 5.5, "abc", None])
    def test_bad_question_count(self, client, existing_user, value):
        """The question count must be a whole number between 1 and 20."""
        _login(client, existing_user)
        body = _save(client, {"default_num_questions": value}).get_json()
        assert body["fields"]["default_num_questions"] == "must be a whole number"

    def test_numeric_string_count_is_accepted(self, client, existing_user):
        """A numeric string is coerced (``int("5")`` works).

        Floats are rejected explicitly because ``int(5.5)`` would
        silently truncate to 5.
        """
        _login(client, existing_user)
        resp = _save(client, {"default_num_questions": "5"})
        assert resp.status_code == 200
        assert resp.get_json()["settings"]["default_num_questions"] == 5

    def test_question_count_out_of_range(self, client, existing_user):
        """The count is bounded by the model maximum."""
        _login(client, existing_user)
        body = _save(
            client, {"default_num_questions": MAX_QUIZ_QUESTIONS + 1}
        ).get_json()
        assert body["fields"]["default_num_questions"] == (
            f"must be between 1 and {MAX_QUIZ_QUESTIONS}"
        )
        body = _save(client, {"default_num_questions": 0}).get_json()
        assert body["fields"]["default_num_questions"] == (
            f"must be between 1 and {MAX_QUIZ_QUESTIONS}"
        )

    def test_bad_status(self, client, existing_user):
        """Only the three known statuses are accepted."""
        _login(client, existing_user)
        body = _save(client, {"status": "invisible"}).get_json()
        assert body["fields"]["status"] == (
            "must be one of: " + ", ".join(SETTINGS_STATUSES)
        )

    def test_multiple_errors_are_reported_together(self, client, existing_user):
        """The player must see every problem at once, not one per attempt."""
        _login(client, existing_user)
        body = _save(
            client,
            {
                "display_name": 1,
                "theme_mode": "neon",
                "language": "Klingon",
                "status": "invisible",
            },
        ).get_json()
        assert set(body["fields"]) == {
            "display_name",
            "theme_mode",
            "language",
            "status",
        }

    def test_nothing_is_written_when_a_field_is_invalid(
        self, client, app, existing_user
    ):
        """A rejected save must not apply the valid half of the payload."""
        _login(client, existing_user)
        _save(client, {"display_name": "Good Name", "theme_mode": "neon"})
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.display_name != "Good Name"


class TestSuccessPayload:
    """A successful save must echo the stored settings back."""

    def test_settings_are_echoed(self, client, existing_user):
        """All ten settings come back in the response."""
        _login(client, existing_user)
        payload = {
            "display_name": "Test Player",
            "nickname": "Tester",
            "grade_occupation": "College",
            "favorite_subject": "Math",
            "language": "Hindi",
            "theme_mode": "dark",
            "game_reminders": False,
            "difficulty_level": "hard",
            "default_num_questions": 5,
            "status": "Do not disturb",
        }
        resp = _save(client, payload)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["settings"] == payload

    def test_settings_keys_are_exact(self, client, existing_user):
        """The payload must not grow or shrink silently."""
        _login(client, existing_user)
        settings = _save(client, {}).get_json()["settings"]
        assert set(settings) == {
            "display_name",
            "nickname",
            "grade_occupation",
            "favorite_subject",
            "language",
            "theme_mode",
            "game_reminders",
            "difficulty_level",
            "default_num_questions",
            "status",
        }

    def test_values_are_persisted(self, client, app, existing_user):
        """The database must match the response."""
        _login(client, existing_user)
        _save(client, {"display_name": "Persisted", "default_num_questions": 7})
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.display_name == "Persisted"
            assert user.default_num_questions == 7

    def test_explicit_null_clears_a_string_field(self, client, app, existing_user):
        """An explicit null clears the field instead of failing."""
        _login(client, existing_user)
        _save(client, {"display_name": "Temp"})
        resp = _save(client, {"display_name": None})
        assert resp.status_code == 200
        assert resp.get_json()["settings"]["display_name"] is None
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.display_name is None

    def test_empty_string_clears_a_string_field(self, client, existing_user):
        """An empty string is treated as "not set"."""
        _login(client, existing_user)
        _save(client, {"nickname": "Temp"})
        body = _save(client, {"nickname": ""}).get_json()
        assert body["settings"]["nickname"] is None

    def test_whitespace_is_collapsed(self, client, existing_user):
        """Free text goes into the LLM prompt, so it must be one line."""
        _login(client, existing_user)
        body = _save(client, {"favorite_subject": "  Space   Physics \n"}).get_json()
        assert body["settings"]["favorite_subject"] == "Space Physics"

    def test_unknown_fields_are_ignored(self, client, existing_user):
        """A stray key must not break the save."""
        _login(client, existing_user)
        resp = _save(client, {"display_name": "Fine", "hacked": "value"})
        assert resp.status_code == 200


class TestSettingsPageContract:
    """The settings page must render a coherent form for any profile."""

    def test_null_profile_falls_back(self, client, app, existing_user):
        """A user with NULL columns still gets a usable form."""
        _login(client, existing_user)
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.nickname = None
            user.grade_occupation = None
            user.favorite_subject = None
            user.language = None
            user.theme_mode = None
            user.game_reminders = None
            user.difficulty_level = None
            user.status = None
            user.default_num_questions = None
            db.session.commit()
        resp = client.get("/settings")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "English" in html
        assert "Ready to play" in html
        assert "medium" in html

    def test_requires_login(self, client, app):
        """The page is behind the login."""
        resp = client.get("/settings")
        assert resp.status_code in (302, 401)

    def test_grade_options_match_the_server(self, client, existing_user):
        """The grade dropdown must offer exactly the accepted values."""
        _login(client, existing_user)
        html = client.get("/settings").get_data(as_text=True)
        for grade in SETTINGS_GRADES:
            assert f'value="{grade}"' in html

    def test_theme_is_rendered_as_a_checkbox(self, client, existing_user):
        """The theme toggle is a checkbox reflecting the stored value."""
        _login(client, existing_user)
        _save(client, {"theme_mode": "dark"})
        html = client.get("/settings").get_data(as_text=True)
        assert 'id="settings-theme"' in html
        assert "checked" in html

    def test_accepted_theme_values(self, client, existing_user):
        """Only light and dark may be stored."""
        _login(client, existing_user)
        for theme in SETTINGS_THEMES:
            resp = _save(client, {"theme_mode": theme})
            assert resp.status_code == 200
            assert resp.get_json()["settings"]["theme_mode"] == theme


# ==== merged from test_account_lifecycle.py ====
def _login(client, existing_user):
    """Log a user in through the real login form."""
    client.post(
        "/login",
        data={"email": existing_user["email"], "password": existing_user["password"]},
    )


def _set_stats(app, existing_user, **kwargs):
    """Set statistics on the user row."""
    with app.app_context():
        user = User.query.filter_by(email=existing_user["email"]).one()
        for key, value in kwargs.items():
            setattr(user, key, value)
        db.session.commit()


def _stats(app, existing_user):
    """Return the statistics tuple of the user row."""
    with app.app_context():
        user = User.query.filter_by(email=existing_user["email"]).one()
        return (
            user.score,
            user.best_score,
            user.total_games_played,
            user.total_wins,
            user.total_powerups_used,
            user.most_used_powerup,
        )


class TestEraseData:
    """``POST /api/account/erase-data``."""

    def test_requires_login(self, client, app):
        """An anonymous client must not be able to erase anything."""
        resp = client.post("/api/account/erase-data")
        assert resp.status_code in (302, 401)

    def test_resets_every_statistic(self, client, app, existing_user):
        """All gameplay counters go back to zero."""
        _login(client, existing_user)
        _set_stats(
            app,
            existing_user,
            score=500,
            best_score=900,
            total_games_played=7,
            total_wins=3,
            total_powerups_used=4,
            most_used_powerup="Hint",
        )
        resp = client.post("/api/account/erase-data")
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}
        assert _stats(app, existing_user) == (0, 0, 0, 0, 0, None)

    def test_keeps_the_account(self, client, app, existing_user):
        """The player can still log in afterwards."""
        _login(client, existing_user)
        client.post("/api/account/erase-data")
        with app.app_context():
            assert User.query.filter_by(email=existing_user["email"]).one() is not None

    def test_keeps_the_profile(self, client, app, existing_user):
        """Erasing data must not touch the profile fields."""
        _login(client, existing_user)
        _set_stats(app, existing_user, display_name="Keeper", nickname="K")
        client.post("/api/account/erase-data")
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.display_name == "Keeper"
            assert user.nickname == "K"

    def test_clears_the_active_quiz(self, client, app, existing_user):
        """A half-finished quiz must not survive the erase."""
        _login(client, existing_user)
        with client.session_transaction() as sess:
            sess["quiz"] = {"questions": [{"question": "Q?"}], "index": 0}
            sess.modified = True
        client.post("/api/account/erase-data")
        with client.session_transaction() as sess:
            assert "quiz" not in sess

    def test_clears_the_cached_result(self, client, app, existing_user):
        """The cached summary must go too."""
        _login(client, existing_user)
        with client.session_transaction() as sess:
            sess["last_result"] = {"quiz_score": 100}
            sess.modified = True
        client.post("/api/account/erase-data")
        with client.session_transaction() as sess:
            assert "last_result" not in sess

    def test_clears_the_current_score(self, client, app, existing_user):
        """The in-progress score goes back to zero."""
        _login(client, existing_user)
        _set_stats(app, existing_user, score=1234)
        client.post("/api/account/erase-data")
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            assert user.score == 0


class TestDeleteAccount:
    """``DELETE /api/account``."""

    def test_requires_login(self, client, app):
        """An anonymous client must not be able to delete anything."""
        resp = client.delete("/api/account")
        assert resp.status_code in (302, 401)

    def test_removes_the_user(self, client, app, existing_user):
        """The account is gone."""
        _login(client, existing_user)
        resp = client.delete("/api/account")
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}
        with app.app_context():
            assert (
                User.query.filter_by(email=existing_user["email"]).one_or_none() is None
            )

    def test_clears_the_session(self, client, app, existing_user):
        """The session must not keep a stale login."""
        _login(client, existing_user)
        with client.session_transaction() as sess:
            sess["quiz"] = {"questions": [{"question": "Q?"}]}
            sess["last_result"] = {"quiz_score": 1}
            sess.modified = True
        client.delete("/api/account")
        with client.session_transaction() as sess:
            assert "quiz" not in sess
            assert "last_result" not in sess

    def test_cancels_own_live_lobby(self, client, app, existing_user):
        """A lobby owned by the deleted user must not stay uncancellable."""
        _login(client, existing_user)
        started = client.post("/api/game/start", json={"lobby_seconds": 60})
        assert started.status_code == 201
        game_id = started.get_json()["game"]["id"]

        client.delete("/api/account")
        with app.app_context():
            game = db.session.get(GameSession, game_id)
            assert game is not None
            assert game.status == "cancelled"

    def test_finished_lobby_is_left_alone(self, client, app, existing_user):
        """A finished game keeps its status."""
        _login(client, existing_user)
        started = client.post("/api/game/start", json={"lobby_seconds": 60})
        game_id = started.get_json()["game"]["id"]
        with app.app_context():
            game = db.session.get(GameSession, game_id)
            game.status = "finished"
            db.session.commit()

        client.delete("/api/account")
        with app.app_context():
            game = db.session.get(GameSession, game_id)
            assert game.status == "finished"

    def test_survives_a_database_failure(self, client, app, existing_user, monkeypatch):
        """A failing commit must not turn into a 500.

        The account stays (the delete was rolled back) but the endpoint
        still answers so the browser does not hang.
        """
        _login(client, existing_user)

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(db.session, "commit", _boom)
        resp = client.delete("/api/account")
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}

    def test_can_log_in_again_after_signup(self, client, app, existing_user):
        """Deleting and re-registering must work."""
        _login(client, existing_user)
        client.delete("/api/account")
        resp = client.post(
            "/register",
            data={
                "email": existing_user["email"],
                "password": "brand-new-password-1",
                "password_confirm": "brand-new-password-1",
            },
        )
        assert resp.status_code in (200, 302)


class TestMethodContract:
    """The account endpoints only answer their own HTTP method."""

    @pytest.mark.parametrize(
        "method,path",
        [("post", "/api/account"), ("get", "/api/account")],
    )
    def test_account_delete_rejects_other_methods(
        self, client, existing_user, method, path
    ):
        """A GET or POST must not delete the account."""
        _login(client, existing_user)
        resp = getattr(client, method)(path)
        assert resp.status_code == 405

    def test_erase_data_rejects_get(self, client, existing_user):
        """Erasing data is a POST."""
        _login(client, existing_user)
        resp = client.get("/api/account/erase-data")
        assert resp.status_code == 405
