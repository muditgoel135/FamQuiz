"""Tests for the settings page (3-card layout + save/erase/delete APIs)."""

from app import User, db


def _login(client, existing_user):
    """Log in the fixture user via POST /login.

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
        """Verify requires login.

        :param client: The client fixture.
        """
        resp = client.get("/settings", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/login?next=")

    def test_loads_three_cards_single_save(self, client, existing_user):
        """Verify loads three cards single save.

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
        """Verify save persists all cards.

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
        """Verify save rejects bad language.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        resp = client.post("/api/settings/save", json={"language": "Klingon"})
        assert resp.status_code == 400

    def test_save_rejects_bad_theme(self, client, existing_user):
        """Verify save rejects bad theme.

        :param client: The client fixture.
        :param existing_user: The existing_user fixture.
        """
        _login(client, existing_user)
        resp = client.post("/api/settings/save", json={"theme_mode": "neon"})
        assert resp.status_code == 400

    def test_save_rejects_bad_game_fields(self, client, app, existing_user):
        """Verify save rejects bad game fields.

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
        """Verify settings values round trip to form.

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
        """Verify erase resets stats keeps account.

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
        """Verify delete removes account.

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
