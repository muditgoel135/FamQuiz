"""Factory/config matrix: empty env, secrets warnings, SMTP, CSRF defaults."""

import logging

import pytest

import app as app_module
from app import create_app

BASE_KEYS = [
    "SECRET_KEY",
    "SECURITY_PASSWORD_SALT",
    "MAIL_SERVER",
    "MAIL_PASSWORD",
    "OLLAMA_API_KEY",
    "OLLAMA_MODEL",
    "OLLAMA_HOST",
    "PORT",
]


def _db(tmp_path, name="cfg.db"):
    return f"sqlite:///{tmp_path / name}"


class TestEmptyEnvBoot:
    def test_empty_env_boots(self, tmp_path, monkeypatch):
        # BASE_CONFIG is frozen at import, so empty env is simulated via
        # explicit overrides (the supported way to reconfigure).
        flask_app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": _db(tmp_path, "e.db"),
                "SECRET_KEY": "x",
                "SECURITY_PASSWORD_SALT": "y",
                "MAIL_SERVER": "",
                "MAIL_PASSWORD": "",
            }
        )
        assert flask_app.config["MAIL_SERVER"] == ""
        assert flask_app.config["MAIL_SUPPRESS_SEND"] is True
        assert flask_app.test_client().get("/").status_code == 200
        assert flask_app.test_client().get("/guide").status_code == 200

    def test_port_precedence(self, monkeypatch):
        monkeypatch.setenv("MAIL_PORT", "2525")
        monkeypatch.delenv("SMTP-PORT", raising=False)
        assert app_module._env_port("MAIL_PORT", "SMTP-PORT", default=587) == 2525
        monkeypatch.delenv("MAIL_PORT")
        monkeypatch.setenv("SMTP-PORT", "2526")
        assert app_module._env_port("MAIL_PORT", "SMTP-PORT", default=587) == 2526


class TestDefaultSecretsCaplog:
    def test_warns_when_not_testing(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            create_app(
                {
                    "TESTING": False,
                    "SQLALCHEMY_DATABASE_URI": _db(tmp_path, "w.db"),
                    "SECRET_KEY": "supersecretkeytochangeinwhileusing",
                    "SECURITY_PASSWORD_SALT": "supersecretsalttochangeinwhileusing",
                    "MAIL_SERVER": "smtp.example.com",
                    "MAIL_PASSWORD": "p",
                }
            )
        assert any("defaults" in m.lower() for m in caplog.messages)

    def test_testing_exempt(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            create_app(
                {
                    "TESTING": True,
                    "SQLALCHEMY_DATABASE_URI": _db(tmp_path, "w2.db"),
                    "SECRET_KEY": "supersecretkeytochangeinwhileusing",
                    "SECURITY_PASSWORD_SALT": "supersecretsalttochangeinwhileusing",
                }
            )
        assert not any("are defaults" in m for m in caplog.messages)

    def test_custom_no_warn(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            create_app(
                {
                    "TESTING": False,
                    "SQLALCHEMY_DATABASE_URI": _db(tmp_path, "w3.db"),
                    "SECRET_KEY": "x" * 32,
                    "SECURITY_PASSWORD_SALT": "y" * 32,
                    "MAIL_SERVER": "smtp.example.com",
                    "MAIL_PASSWORD": "p",
                }
            )
        assert not any("are defaults" in m for m in caplog.messages)


class TestSmtpSuppress:
    def test_missing_server(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            flask_app = create_app(
                {
                    "TESTING": False,
                    "SQLALCHEMY_DATABASE_URI": _db(tmp_path, "s.db"),
                    "SECRET_KEY": "x" * 16,
                    "SECURITY_PASSWORD_SALT": "y" * 16,
                    "MAIL_SERVER": "",
                    "MAIL_PASSWORD": "",
                }
            )
        assert flask_app.config["MAIL_SUPPRESS_SEND"] is True
        assert any("suppressed" in m.lower() for m in caplog.messages)

    def test_missing_password(self, tmp_path):
        flask_app = create_app(
            {
                "TESTING": False,
                "SQLALCHEMY_DATABASE_URI": _db(tmp_path, "s2.db"),
                "SECRET_KEY": "x" * 16,
                "SECURITY_PASSWORD_SALT": "y" * 16,
                "MAIL_SERVER": "smtp.example.com",
                "MAIL_PASSWORD": "",
            }
        )
        assert flask_app.config["MAIL_SUPPRESS_SEND"] is True

    def test_explicit_wins(self, tmp_path):
        flask_app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": _db(tmp_path, "s3.db"),
                "SECRET_KEY": "x",
                "SECURITY_PASSWORD_SALT": "y",
                "MAIL_SERVER": "",
                "MAIL_PASSWORD": "",
                "MAIL_SUPPRESS_SEND": False,
            }
        )
        assert flask_app.config["MAIL_SUPPRESS_SEND"] is False


class TestCsrfDefaults:
    def test_production_enabled(self, tmp_path):
        flask_app = create_app(
            {
                "TESTING": False,
                "SQLALCHEMY_DATABASE_URI": _db(tmp_path, "p.db"),
                "SECRET_KEY": "x",
                "SECURITY_PASSWORD_SALT": "y",
                "MAIL_SUPPRESS_SEND": True,
            }
        )
        assert flask_app.config.get("WTF_CSRF_ENABLED", True) is not False
        assert "famquiz_csrf" in flask_app.extensions

    def test_testing_disables(self, tmp_path):
        flask_app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": _db(tmp_path, "p2.db"),
                "SECRET_KEY": "x",
                "SECURITY_PASSWORD_SALT": "y",
            }
        )
        assert flask_app.config["WTF_CSRF_ENABLED"] is False


class TestMaxContentLength:
    def test_pinned(self):
        assert app_module.BASE_CONFIG["MAX_CONTENT_LENGTH"] == 1_000_000

    def test_applied(self, tmp_path):
        flask_app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": _db(tmp_path, "mcl.db"),
                "SECRET_KEY": "x",
                "SECURITY_PASSWORD_SALT": "y",
            }
        )
        assert flask_app.config["MAX_CONTENT_LENGTH"] == 1_000_000


class TestPermutationTable:
    @pytest.mark.parametrize(
        "testing,suppress",
        [(True, True), (True, False), (False, True)],
    )
    def test_permutations(self, tmp_path, testing, suppress):
        flask_app = create_app(
            {
                "TESTING": testing,
                "SQLALCHEMY_DATABASE_URI": _db(tmp_path, f"m{testing}{suppress}.db"),
                "SECRET_KEY": "x",
                "SECURITY_PASSWORD_SALT": "y",
                "MAIL_SUPPRESS_SEND": suppress,
                "WTF_CSRF_ENABLED": False,
            }
        )
        assert flask_app.config["MAIL_SUPPRESS_SEND"] is suppress
        assert flask_app.test_client().get("/").status_code == 200
