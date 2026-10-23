"""Contract tests for ``/api/settings/save`` and the settings page.

The settings form is the only place where a player edits their profile,
so the API contract matters: every rejection must say *which* field is
wrong and *why*, and a successful save must echo back exactly what was
stored. The previous tests only asserted ``status_code == 400`` and that
a field name appeared somewhere in the body.
"""

import pytest

from app import MAX_QUIZ_QUESTIONS, User, db
from routes import SETTINGS_GRADES, SETTINGS_LANGUAGES, SETTINGS_STATUSES, SETTINGS_THEMES

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
        assert body["fields"]["difficulty_level"] == "must be one of: easy, medium, hard"

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
        body = _save(client, {"default_num_questions": MAX_QUIZ_QUESTIONS + 1}).get_json()
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

    def test_nothing_is_written_when_a_field_is_invalid(self, client, app, existing_user):
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


class TestSettingsPage:
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
