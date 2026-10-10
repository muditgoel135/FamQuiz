"""Residual unit tests for app.py (wave 2, green-only).

Skipped-red registry (need code fixes to enable, NOT tested here;
app.py helpers for OLLAMA blank-key, zh-Hans hyphen and questions
non-list guard are now fixed and covered in test_app_helpers.py):
- started_at="bad" 500, mega-counts KeyError,
  MAX_CONTENT_LENGTH, array-body guard, evil ?next= blocking.
"""

import sys
from types import SimpleNamespace

import pytest

import app as app_module

OPTS = ["Earth", "Mars", "Jupiter", "Venus"]


def _profile(**kw):
    base = {
        "favorite_subject": "Space",
        "difficulty_level": "easy",
        "language": "Hindi",
        "grade_occupation": "Grade 5",
    }
    base.update(kw)
    return SimpleNamespace(**base)


class TestEnvResiduals:
    def test_whitespace_truthy(self, monkeypatch):
        monkeypatch.setenv("FQ_WS", "   ")
        monkeypatch.delenv("FQ_FB", raising=False)
        assert app_module._env("FQ_WS", "FQ_FB", default="dflt") == "   "

    def test_empty_to_dash(self, monkeypatch):
        monkeypatch.setenv("FQ_A", "")
        monkeypatch.setenv("SMTP-SERVER", "smtp.dash")
        assert app_module._env("FQ_A", "SMTP-SERVER", default="x") == "smtp.dash"

    def test_all_empty_default(self, monkeypatch):
        monkeypatch.setenv("FQ_A", "")
        monkeypatch.setenv("FQ_B", "")
        assert app_module._env("FQ_A", "FQ_B", default="fb") == "fb"

    def test_no_names(self):
        assert app_module._env(default="d") == "d"
        assert app_module._env() == ""


class TestEnvBoolResiduals:
    @pytest.mark.parametrize("v", ["y", "Y", "t", "T", " y ", "n", "f", "N", "F"])
    def test_y_t_are_false(self, monkeypatch, v):
        monkeypatch.setenv("FQ_B", v)
        assert app_module._env_bool("FQ_B", default=True) is False

    @pytest.mark.parametrize("v", ["YeS", "oN", "  ON  "])
    def test_yes_on_true(self, monkeypatch, v):
        monkeypatch.setenv("FQ_B", v)
        assert app_module._env_bool("FQ_B", default=False) is True


class TestEnvPortResiduals:
    @pytest.mark.parametrize("v", ["0x10", "0XFF", "0o17", "0b101", "+587.0", "--1"])
    def test_nondecimal_fallback(self, monkeypatch, v):
        monkeypatch.setenv("FQ_P", v)
        assert app_module._env_port("FQ_P", default=587) == 587

    def test_plus_ws_valid(self, monkeypatch):
        monkeypatch.setenv("FQ_P", " +587 ")
        assert app_module._env_port("FQ_P", default=587) == 587
        monkeypatch.setenv("FQ_P", " 2525\n")
        assert app_module._env_port("FQ_P", default=587) == 2525

    def test_none_fallback(self, monkeypatch):
        import os as _os

        monkeypatch.setattr(_os, "getenv", lambda *a, **k: None)
        assert app_module._env_port("X", default=587) == 587


class TestTranslateResiduals:
    def test_none_locale(self, monkeypatch):
        monkeypatch.setattr(app_module, "TRANSLATIONS", {"es": {"Hi": "Hola"}})
        assert app_module.translate("Hi", None) == "Hi"

    def test_empty_locale(self):
        assert app_module.translate("Hi", "") == "Hi"

    def test_hyphen_miss(self, monkeypatch):
        # Hyphen BCP47 form normalizes to the zh_Hans catalog key.
        monkeypatch.setattr(app_module, "TRANSLATIONS", {"zh_Hans": {"Hi": "你好"}})
        assert app_module.translate("Hi", "zh-Hans") == "你好"

    def test_falsy_int(self):
        assert app_module.translate(0, "es") == 0
        assert app_module.translate(False, "es") is False


class TestStripFencesResiduals:
    @pytest.mark.parametrize(
        "s", ["```json\n```", "```\n\n```", "```json ```", "``` ```", "```JSON\n```"]
    )
    def test_empty_fences(self, s):
        assert app_module.strip_code_fences(s) == ""

    def test_only_open(self):
        assert app_module.strip_code_fences("```json\n") == ""

    def test_int_passthrough(self):
        assert app_module.strip_code_fences(123) is 123
        d = {}
        assert app_module.strip_code_fences(d) is d


class TestResolveCrossField:
    def test_index_str_wins(self):
        assert (
            app_module.resolve_answer_index(
                {"answer_index": "1", "answer": "Venus"}, OPTS
            )
            == 1
        )

    def test_both_none(self):
        assert (
            app_module.resolve_answer_index(
                {"answer_index": None, "answer": None}, OPTS
            )
            is None
        )

    def test_index_empty_no_fallback(self):
        # Only None falls back to "answer"; "" does not (documents asymmetry).
        assert (
            app_module.resolve_answer_index(
                {"answer_index": "", "answer": "Mars"}, OPTS
            )
            is None
        )

    def test_padded_numeric(self):
        assert app_module.resolve_answer_index({"answer": " 2 "}, OPTS) == 2


class TestParseResiduals:
    def test_int_input(self):
        with pytest.raises(app_module.QuizGenerationError, match="unreadable"):
            app_module.parse_quiz_content(123)

    def test_dict_input(self):
        with pytest.raises(app_module.QuizGenerationError, match="unreadable"):
            app_module.parse_quiz_content({"questions": []})

    def test_questions_str(self):
        with pytest.raises(app_module.QuizGenerationError, match="unreadable"):
            app_module.parse_quiz_content('{"questions":"abc"}')

    @pytest.mark.parametrize(
        "p", ['{"questions":123}', '{"questions":null}', '{"questions":{"a":1}}']
    )
    def test_questions_nonlist(self, p):
        with pytest.raises(app_module.QuizGenerationError, match="unreadable"):
            app_module.parse_quiz_content(p)

    def test_empty_string(self):
        with pytest.raises(app_module.QuizGenerationError, match="unreadable"):
            app_module.parse_quiz_content("")

    def test_quoted_str(self):
        with pytest.raises(app_module.QuizGenerationError, match="unreadable"):
            app_module.parse_quiz_content('"str"')

    def test_empty_object(self):
        with pytest.raises(app_module.QuizGenerationError, match="unreadable"):
            app_module.parse_quiz_content("{}")


class TestDisplayResiduals:
    def test_both_blank_email(self):
        assert (
            app_module.display_name_of(
                SimpleNamespace(
                    display_name="   ",
                    nickname="\t \n",
                    email="player@example.com",
                )
            )
            == "player"
        )

    def test_nick_stripped(self):
        # Whitespace display_name falls through to nickname per docstring.
        assert (
            app_module.display_name_of(
                SimpleNamespace(display_name="  ", nickname="  Tommy  ",
                                email="x@y.com")
            )
            == "Tommy"
        )

    def test_empty_email_player(self):
        assert (
            app_module.display_name_of(
                SimpleNamespace(display_name=None, nickname=None, email="")
            )
            == "Player"
        )


class TestRankResiduals:
    def test_none_str_negative(self, app, existing_user):
        with app.app_context():
            assert app_module.rank_of(None) == 1
            assert app_module.rank_of("1") == 1
            assert app_module.rank_of("abc") == 1
            assert app_module.rank_of(-1) == 1


class TestBaseConfigPins:
    def test_static_keys(self):
        cfg = app_module.BASE_CONFIG
        assert cfg["SQLALCHEMY_TRACK_MODIFICATIONS"] is False
        assert cfg["SECURITY_PASSWORD_HASH"] == "pbkdf2_sha512"
        assert cfg["SECURITY_REGISTERABLE"] is True
        assert cfg["SECURITY_SEND_REGISTER_EMAIL"] is False
        assert cfg["SECURITY_SEND_PASSWORD_CHANGE_EMAIL"] is True
        assert cfg["SECURITY_SEND_PASSWORD_RESET_EMAIL"] is True
        assert cfg["SECURITY_SEND_PASSWORD_RESET_NOTICE_EMAIL"] is True
        assert cfg["SECURITY_CONFIRMABLE"] is False
        assert cfg["SECURITY_RECOVERABLE"] is True
        assert cfg["SECURITY_CHANGEABLE"] is True
        assert cfg["SECURITY_TRACKABLE"] is False
        assert cfg["SECURITY_LOGIN_USER_TEMPLATE"] == "login.html"
        assert cfg["SECURITY_REGISTER_USER_TEMPLATE"] == "signup.html"
        assert cfg["SECURITY_FORGOT_PASSWORD_TEMPLATE"] == "forgot_password.html"
        assert cfg["SECURITY_RESET_PASSWORD_TEMPLATE"] == "reset_password.html"
        assert cfg["SECURITY_CHANGE_PASSWORD_TEMPLATE"] == "change_password.html"
        assert cfg["SECURITY_POST_LOGIN_VIEW"] == "/"
        assert cfg["SECURITY_POST_LOGOUT_VIEW"] == "/"
        assert cfg["SECURITY_POST_REGISTER_VIEW"] == "/"
        assert cfg["SECURITY_LOGOUT_METHODS"] == ["GET", "POST"]
        assert cfg["SECURITY_EMAIL_VALIDATOR_ARGS"] == {"check_deliverability": False}
        assert cfg["SESSION_COOKIE_HTTPONLY"] is True

    def test_mail_types(self):
        cfg = app_module.BASE_CONFIG
        assert isinstance(cfg["MAIL_SERVER"], str)
        assert isinstance(cfg["MAIL_PORT"], int)
        assert isinstance(cfg["MAIL_USE_TLS"], bool)
        assert isinstance(cfg["MAIL_USE_SSL"], bool)
        assert isinstance(cfg["MAIL_USERNAME"], str)


class TestBuildQuizResiduals:
    def test_int_difficulty_raises(self):
        with pytest.raises(AttributeError):
            app_module.build_quiz_messages(_profile(), 1, 1)

    def test_grade_capped(self):
        prompt = app_module.build_quiz_messages(
            _profile(grade_occupation="G" * 200), 1
        )[1]["content"]
        assert "G" * 80 in prompt
        assert "G" * 81 not in prompt

    def test_grade_multiline(self):
        prompt = app_module.build_quiz_messages(
            _profile(grade_occupation="Grade 5\nInject: x"), 1
        )[1]["content"]
        assert "Inject:" in prompt

    def test_grade_blank_general(self):
        prompt = app_module.build_quiz_messages(
            _profile(grade_occupation="   "), 1
        )[1]["content"]
        assert "general" in prompt


class TestGetLocaleResiduals:
    def test_g_get_raises(self, app):
        from flask import g

        def _boom(*a, **k):
            raise RuntimeError("g down")

        with app.test_request_context("/?lang=es"):
            from unittest import mock

            with mock.patch.object(g, "get", side_effect=RuntimeError("g down")):
                assert app_module.get_locale() == "es"

    def test_current_user_raises(self, app):
        class _Boom:
            is_authenticated = property(
                lambda self: (_ for _ in ()).throw(RuntimeError("u down"))
            )

        with app.test_request_context("/", headers={"Accept-Language": "es"}):
            from unittest import mock

            with mock.patch.object(
                app_module, "current_user", _Boom()
            ):
                assert app_module.get_locale() == "es"

    def test_outer_exception_en(self, app):
        with app.test_request_context("/"):
            from unittest import mock

            with mock.patch(
                "flask.request",
                side_effect=RuntimeError("req down"),
            ):
                pass  # request proxy patch is unsafe; use args patch instead
        with app.test_request_context("/"):
            from flask import request
            from unittest import mock

            with mock.patch.object(
                request.args.__class__, "get",
                side_effect=RuntimeError("args down"),
            ):
                assert app_module.get_locale() == "en"

    def test_hyphen_ignored(self, app):
        with app.test_request_context("/?lang=zh-Hans"):
            from flask import session

            assert app_module.get_locale() == "en"
            assert session.get("locale") is None

    def test_accept_en(self, app):
        with app.test_request_context("/", headers={"Accept-Language": "en"}):
            assert app_module.get_locale() == "en"


class TestMailEmpties:
    def test_recipient_empty(self, app, monkeypatch):
        monkeypatch.setattr(app_module, "get_locale", lambda: "hi")
        with app.test_request_context("/"):
            assert app_module._recipient_locale("") == "hi"
            assert app_module._recipient_locale(None) == "hi"
            assert app_module._recipient_locale([]) == "hi"

    def test_render_empty_email(self, app, monkeypatch):
        from flask import g

        monkeypatch.setattr(app_module, "_recipient_locale", lambda *a, **k: "en")
        monkeypatch.setattr("flask.render_template", lambda *a, **k: "ok")
        with app.test_request_context("/"):
            assert (
                app_module.security_render_template("t", email="", user=None)
                == "ok"
            )
            assert g.get("email_locale") is None

    def test_mailutil_empty_recipient(self, app, monkeypatch):
        from flask import g

        captured = {}
        monkeypatch.setattr(
            app_module, "_recipient_locale",
            lambda r, u=None: captured.update(r=r) or "en",
        )
        monkeypatch.setattr(app_module, "translate", lambda s, loc: f"{s}-{loc}")
        monkeypatch.setattr(
            "flask_security.mail_util.MailUtil.send_mail",
            lambda self, *a, **k: "sent",
        )
        util = object.__new__(app_module.TranslatedMailUtil)
        with app.test_request_context("/"):
            assert util.send_mail("t", "Subj", "", "s", "b", "h") == "sent"
            assert captured["r"] == ""
            assert g.get("email_locale") is None


class TestMailGFailures:
    def test_render_g_get_raises(self, app, monkeypatch):
        from flask import g
        from unittest import mock

        monkeypatch.setattr(app_module, "_recipient_locale", lambda *a, **k: "es")
        monkeypatch.setattr("flask.render_template", lambda *a, **k: "rendered")
        with app.test_request_context("/"):
            with mock.patch.object(g, "get", side_effect=RuntimeError("down")):
                assert (
                    app_module.security_render_template("t", email="a@b.com")
                    == "rendered"
                )

    def test_render_g_pop_raises(self, app, monkeypatch):
        from flask import g
        from unittest import mock

        monkeypatch.setattr(app_module, "_recipient_locale", lambda *a, **k: "es")
        monkeypatch.setattr("flask.render_template", lambda *a, **k: "rendered")
        with app.test_request_context("/"):
            with mock.patch.object(g, "pop", side_effect=RuntimeError("down")):
                assert (
                    app_module.security_render_template("t", email="a@b.com")
                    == "rendered"
                )

    def test_mailutil_g_pop_raises(self, app, monkeypatch):
        from flask import g
        from unittest import mock

        monkeypatch.setattr(app_module, "_recipient_locale", lambda *a, **k: "es")
        monkeypatch.setattr(app_module, "translate", lambda s, loc: s)
        monkeypatch.setattr(
            "flask_security.mail_util.MailUtil.send_mail",
            lambda self, *a, **k: "ok",
        )
        util = object.__new__(app_module.TranslatedMailUtil)
        with app.test_request_context("/"):
            with mock.patch.object(g, "pop", side_effect=RuntimeError("down")):
                assert util.send_mail("t", "s", "a@b.com", "x", "b", "h") == "ok"


class TestPublicStateResiduals:
    def test_missing_questions(self, app):
        with app.test_request_context("/"):
            with pytest.raises(IndexError, match="out of range"):
                app_module._public_state({"index": 0})

    def test_missing_question_key(self, app):
        with app.test_request_context("/"):
            with pytest.raises(KeyError):
                app_module._public_state(
                    {"questions": [{"options": ["A", "B", "C", "D"]}], "index": 0}
                )

    def test_missing_options_key(self, app):
        with app.test_request_context("/"):
            with pytest.raises(KeyError):
                app_module._public_state(
                    {"questions": [{"question": "Q?"}], "index": 0}
                )


class TestGenerateResiduals:
    def test_ctor_raises(self, monkeypatch):
        class _C:
            def __init__(self, *a, **k):
                raise RuntimeError("conn")

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "k")
        monkeypatch.setitem(sys.modules, "ollama", SimpleNamespace(Client=_C))
        with pytest.raises(RuntimeError, match="conn"):
            app_module.get_ollama_client()

    def test_factory_passthrough(self, monkeypatch):
        monkeypatch.setattr(
            app_module, "get_ollama_client",
            lambda: (_ for _ in ()).throw(app_module.QuizConfigError("no key")),
        )
        with pytest.raises(app_module.QuizConfigError):
            app_module.generate_questions(_profile(), 1)

    def test_empty_dict_response(self, monkeypatch):
        class _D:
            def chat(self, *a, **k):
                return {}

        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _D())
        with pytest.raises(app_module.QuizGenerationError, match="unreadable"):
            app_module.generate_questions(_profile(), 1)

    def test_empty_string_content(self, monkeypatch):
        from types import SimpleNamespace as _NS

        class _N:
            def chat(self, *a, **k):
                return _NS(message=_NS(content=""))

        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _N())
        with pytest.raises(app_module.QuizGenerationError, match="unreadable"):
            app_module.generate_questions(_profile(), 1)

    def test_empty_object_content(self, monkeypatch):
        from types import SimpleNamespace as _NS

        class _N:
            def chat(self, *a, **k):
                return _NS(message=_NS(content="{}"))

        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _N())
        with pytest.raises(app_module.QuizGenerationError, match="unreadable"):
            app_module.generate_questions(_profile(), 1)


class TestCreateAppResiduals:
    def test_testing_missing(self, tmp_path):
        flask_app = app_module.create_app(
            {
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'n.db'}",
                "SECRET_KEY": "x",
                "SECURITY_PASSWORD_SALT": "y",
                "MAIL_SUPPRESS_SEND": True,
            }
        )
        assert flask_app.config.get("WTF_CSRF_ENABLED", True) is not False

    def test_header_preservation(self, app):
        @app.route("/_hdr")  # noqa: Flask route in test
        def _hdr():
            from flask import Response

            return Response(
                "ok",
                headers={
                    "X-Frame-Options": "SAMEORIGIN",
                    "X-Content-Type-Options": "custom",
                },
            )

        c = app.test_client()
        assert c.get("/_hdr").headers["X-Frame-Options"] == "SAMEORIGIN"
        assert c.get("/_hdr").headers["X-Content-Type-Options"] == "custom"
        assert c.get("/_hdr").headers["Referrer-Policy"] == "same-origin"

    def test_csrf_failure_warns(self, tmp_path, monkeypatch, caplog):
        import logging

        def _boom(self, app):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "flask_wtf.csrf.CSRFProtect.init_app", _boom
        )
        with caplog.at_level(logging.WARNING):
            flask_app = app_module.create_app(
                {
                    "TESTING": True,
                    "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'c.db'}",
                    "SECRET_KEY": "x",
                    "SECURITY_PASSWORD_SALT": "y",
                }
            )
        assert "CSRFProtect not initialised" in caplog.text
        assert "famquiz_csrf" not in flask_app.extensions
        # Without CSRFProtect the csrf_token() global is missing, so page
        # renders fail loudly (propagated in TESTING) instead of silently
        # posting unprotected.
        import jinja2

        with pytest.raises(jinja2.exceptions.UndefinedError):
            flask_app.test_client().get("/")


class TestModelResiduals:
    def test_duplicate_email(self, app, existing_user):
        from sqlalchemy.exc import IntegrityError
        from flask_security.utils import hash_password
        from app import db, user_datastore

        with app.app_context():
            user_datastore.create_user(
                email=existing_user["email"], password=hash_password("y" * 12)
            )
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
            from app import User

            assert User.query.filter_by(email=existing_user["email"]).count() == 1

    def test_duplicate_role(self, app):
        from sqlalchemy.exc import IntegrityError
        from app import Role, db

        with app.app_context():
            db.session.add(Role(name="dupx", description="a"))
            db.session.commit()
            db.session.add(Role(name="dupx", description="b"))
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_null_email(self, app):
        from sqlalchemy.exc import IntegrityError
        from app import User, db

        with app.app_context():
            db.session.add(User(email=None, password="x"))
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_lobby_unclamped(self):
        from app import GameSession

        assert GameSession(lobby_seconds=9999).lobby_seconds == 9999
        assert GameSession(lobby_seconds=1).lobby_seconds == 1

    def test_multi_role(self, app):
        from flask_security.utils import hash_password
        from app import Role, User, db, user_datastore

        with app.app_context():
            r1 = Role(name="mr1", description="a")
            r2 = Role(name="mr2", description="b")
            db.session.add_all([r1, r2])
            user_datastore.create_user(
                email="mr@example.com", password=hash_password("x" * 12)
            )
            db.session.commit()
            user = User.query.filter_by(email="mr@example.com").one()
            user.roles.extend([r1, r2])
            db.session.commit()
            assert {r.name for r in user.roles} == {"mr1", "mr2"}
            assert user in r1.users

    def test_null_best(self, app, client, existing_user):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.best_score = None
            db.session.commit()
            assert app_module.rank_of(user.id) >= 1
        assert client.get("/leaderboard").status_code == 200


class TestLanResiduals:
    def _sock(self, monkeypatch, ip="192.168.1.5", connect_boom=False):
        import socket as _sock

        class _S:
            def __init__(self, *a, **k):
                pass

            def connect(self, *a, **k):
                if connect_boom:
                    raise OSError("net down")

            def getsockname(self):
                return (ip, 0)

            def close(self):
                pass

        monkeypatch.setattr(_sock, "socket", _S)

    def test_zero_ip(self, monkeypatch, capsys):
        self._sock(monkeypatch, "0.0.0.0")
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("x")),
        )
        app_module._print_lan_urls(5000)
        out = capsys.readouterr().out
        assert "(no LAN address found)" in out
        assert "http://0.0.0.0" not in out

    def test_connect_raises(self, monkeypatch, capsys):
        self._sock(monkeypatch, connect_boom=True)
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **k: (_ for _ in ()).throw(OSError("x")),
        )
        app_module._print_lan_urls(5000)  # must not raise
        assert ":5000" in capsys.readouterr().out

    def test_tailscale_multi_first(self, monkeypatch, capsys):
        import socket as _sock

        self._sock(monkeypatch)

        class _R:
            stdout = "100.64.0.1\n100.64.0.2\n"

        monkeypatch.setattr("subprocess.run", lambda *a, **k: _R())
        app_module._print_lan_urls(5000)
        assert "http://100.64.0.1:5000" in capsys.readouterr().out

    def test_tailscale_loopback_empty(self, monkeypatch, capsys):
        self._sock(monkeypatch)

        class _R:
            stdout = "127.0.0.5\n"

        monkeypatch.setattr("subprocess.run", lambda *a, **k: _R())
        app_module._print_lan_urls(5000)
        assert "Tailscale not detected" in capsys.readouterr().out

        class _R2:
            stdout = ""

        monkeypatch.setattr("subprocess.run", lambda *a, **k: _R2())
        app_module._print_lan_urls(5000)
        assert "Tailscale not detected" in capsys.readouterr().out


class TestGlobalAppMain:
    def test_global_app(self):
        from flask import Flask

        assert isinstance(app_module.app, Flask)
        assert app_module.app.config["SECURITY_REGISTERABLE"] is True

    def test_main_source(self):
        src = open("app.py", encoding="utf-8").read()
        assert 'app.run(debug=False, host="0.0.0.0"' in src
        assert '_port = int(os.getenv("PORT", 5000))' in src
        assert '_sys.modules.setdefault("app"' in src


class TestSequentialRaces:
    """Single-threaded equivalents of race conditions (no threads)."""

    def test_double_answer_counts_once(self, client, existing_user, monkeypatch):
        import json as _json
        from types import SimpleNamespace as _NS

        class _F:
            def chat(self, model="", messages=None, **kwargs):
                return _NS(
                    message=_NS(
                        content=_json.dumps(
                            {"questions": [{"question": "Q?",
                                            "options": ["A", "B", "C", "D"],
                                            "answer_index": 0}]}
                        )
                    )
                )

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _F())
        client.post(
            "/login",
            data={"email": existing_user["email"],
                  "password": existing_user["password"]},
        )
        assert client.post("/api/quiz/generate", json={"num_questions": 1}).status_code == 200
        assert client.get("/api/quiz/state").status_code == 200
        import time as _t

        with client.session_transaction() as sess:
            sess["quiz"]["started_at"] = _t.time() - 1
            sess.modified = True
        first = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        )
        second = client.post(
            "/api/quiz/answer", json={"option_index": 0, "question_index": 0}
        )
        assert sorted([first.status_code, second.status_code]) == [200, 409]
        with client.session_transaction() as sess:
            assert sess["quiz"]["index"] == 1

    def test_sequential_duplicate_email(self, app, existing_user):
        from sqlalchemy.exc import IntegrityError
        from flask_security.utils import hash_password
        from app import User, db, user_datastore

        with app.app_context():
            user_datastore.create_user(
                email=existing_user["email"], password=hash_password("z" * 12)
            )
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
            assert User.query.filter_by(email=existing_user["email"]).count() == 1

    def test_rank_stable(self, app, existing_user):
        from app import User, db

        with app.app_context():
            base = User.query.filter_by(email=existing_user["email"]).one()
            base.best_score = 100
            db.session.commit()
            for i in range(5):
                u = User(email=f"rk{i}@example.com", password="x")
                u.best_score = 100 + i
                db.session.add(u)
            db.session.commit()
            for _ in range(20):
                assert 1 <= app_module.rank_of(base.id) <= 6
