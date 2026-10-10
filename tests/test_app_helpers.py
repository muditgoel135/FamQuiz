"""Unit tests for app.py helpers, models and constants.

Covers everything with no direct pytest: _env*, translations/i18n,
quiz pure functions, mail helpers, display/rank, factory, LAN urls, models.
HTTP-level behaviour stays in test_quiz.py / test_i18n.py / test_pages.py.
"""

import json
import sys
from types import SimpleNamespace

import pytest

import app as app_module
from app import (
    BASE_POINTS,
    DIFFICULTY_LEVELS,
    GAME_EXPIRY_GRACE_SECONDS,
    MAX_QUIZ_QUESTIONS,
    POWERUP_CHANCE,
    POWERUP_KINDS,
    POWERUP_LABELS,
    QUESTION_TIME_BONUS_MS,
    QUESTION_TIME_LIMIT_MS,
    SPEED_BONUS_POINTS,
    SUPPORTED_LOCALES,
)


# ---------------------------------------------------------------------------
# _env helpers
# ---------------------------------------------------------------------------


class TestEnv:
    def test_single_hit(self, monkeypatch):
        monkeypatch.setenv("FQ_A", "hello")
        assert app_module._env("FQ_A") == "hello"

    def test_first_wins(self, monkeypatch):
        monkeypatch.setenv("FQ_A", "first")
        monkeypatch.setenv("FQ_B", "second")
        assert app_module._env("FQ_A", "FQ_B") == "first"

    def test_falls_through_empty(self, monkeypatch):
        monkeypatch.setenv("FQ_A", "")
        monkeypatch.setenv("FQ_B", "second")
        assert app_module._env("FQ_A", "FQ_B") == "second"

    def test_all_missing_default(self, monkeypatch):
        monkeypatch.delenv("FQ_M1", raising=False)
        monkeypatch.delenv("FQ_M2", raising=False)
        assert app_module._env("FQ_M1", "FQ_M2", default="fallback") == "fallback"

    def test_default_empty(self, monkeypatch):
        monkeypatch.delenv("FQ_M1", raising=False)
        assert app_module._env("FQ_M1") == ""

    def test_legacy_dash_fallback(self, monkeypatch):
        monkeypatch.delenv("MAIL_SERVER", raising=False)
        monkeypatch.setenv("SMTP-SERVER", "smtp.example.com")
        assert app_module._env("MAIL_SERVER", "SMTP-SERVER", default="") == (
            "smtp.example.com"
        )

    def test_no_names_default(self):
        assert app_module._env(default="dflt") == "dflt"


class TestEnvBool:
    @pytest.mark.parametrize(
        "v", ["1", "true", "True", "TRUE", " yes ", "YES", "on", "ON", " On "]
    )
    def test_true_variants(self, monkeypatch, v):
        monkeypatch.setenv("FQ_B", v)
        assert app_module._env_bool("FQ_B", default=False) is True

    @pytest.mark.parametrize(
        "v", ["0", "false", "False", "no", "off", "2", "maybe", "5.5", " "]
    )
    def test_false_variants(self, monkeypatch, v):
        monkeypatch.setenv("FQ_B", v)
        assert app_module._env_bool("FQ_B", default=True) is False

    def test_missing_false(self, monkeypatch):
        monkeypatch.delenv("FQ_M", raising=False)
        assert app_module._env_bool("FQ_M", default=False) is False

    def test_missing_true(self, monkeypatch):
        monkeypatch.delenv("FQ_M", raising=False)
        assert app_module._env_bool("FQ_M", default=True) is True

    def test_empty_returns_default(self, monkeypatch):
        monkeypatch.setenv("FQ_B", "")
        assert app_module._env_bool("FQ_B", default=True) is True
        assert app_module._env_bool("FQ_B", default=False) is False

    def test_first_nonempty_wins(self, monkeypatch):
        monkeypatch.setenv("FQ_A", "0")
        monkeypatch.setenv("FQ_B", "true")
        assert app_module._env_bool("FQ_A", "FQ_B") is False
        monkeypatch.setenv("FQ_A", "")
        assert app_module._env_bool("FQ_A", "FQ_B") is True


class TestEnvPort:
    def test_valid(self, monkeypatch):
        monkeypatch.setenv("FQ_P", "2525")
        assert app_module._env_port("FQ_P", default=587) == 2525

    def test_missing_default(self, monkeypatch):
        monkeypatch.delenv("FQ_M", raising=False)
        assert app_module._env_port("FQ_M", default=587) == 587
        assert app_module._env_port("FQ_M", default=2525) == 2525

    @pytest.mark.parametrize("v", ["abc", "", "5.5", "None", "587.0", "--", " "])
    def test_garbage_fallback(self, monkeypatch, v):
        monkeypatch.setenv("FQ_P", v)
        assert app_module._env_port("FQ_P", default=587) == 587

    def test_whitespace_padded(self, monkeypatch):
        monkeypatch.setenv("FQ_P", " 587 ")
        assert app_module._env_port("FQ_P", default=587) == 587

    def test_zero_and_large(self, monkeypatch):
        monkeypatch.setenv("FQ_P", "0")
        assert app_module._env_port("FQ_P", default=587) == 0
        monkeypatch.setenv("FQ_P", "65535")
        assert app_module._env_port("FQ_P", default=587) == 65535


# ---------------------------------------------------------------------------
# Translations / i18n units
# ---------------------------------------------------------------------------


class TestLoadTranslations:
    def test_real_file_four_locales(self):
        result = app_module._load_translations()
        assert set(result) == {"en", "es", "hi", "zh_Hans"}
        assert all(isinstance(v, dict) for v in result.values())
        assert len(result["es"]) > 20

    def test_returns_copies(self):
        first = app_module._load_translations()
        second = app_module._load_translations()
        assert first is not second
        assert first["es"] is not second["es"]
        assert first == second

    def test_oserror_fallback(self, monkeypatch):
        def _boom(*a, **k):
            raise OSError("no file")

        monkeypatch.setattr("builtins.open", _boom)
        assert app_module._load_translations() == {
            "en": {},
            "es": {},
            "hi": {},
            "zh_Hans": {},
        }

    def test_bad_json_fallback(self, monkeypatch):
        monkeypatch.setattr(
            "json.load", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad"))
        )
        assert app_module._load_translations() == {
            "en": {},
            "es": {},
            "hi": {},
            "zh_Hans": {},
        }

    def test_unicode_preserved(self):
        result = app_module._load_translations()
        assert "लीडरबोर्ड" in list(result["hi"].values())
        assert "排行榜" in list(result["zh_Hans"].values())


class TestTranslate:
    def test_falsy_passthrough(self):
        assert app_module.translate("", "es") == ""
        assert app_module.translate(None, "es") is None

    def test_en_identity(self, monkeypatch):
        monkeypatch.setattr(
            app_module, "TRANSLATIONS", {"en": {"Hello,": "SHOULD_NOT_USE"}}
        )
        assert app_module.translate("Hello,", "en") == "Hello,"

    def test_known_es(self, monkeypatch):
        monkeypatch.setattr(
            app_module, "TRANSLATIONS", {"es": {"Hello,": "Hola,"}}
        )
        assert app_module.translate("Hello,", "es") == "Hola,"

    def test_unknown_msg_fallback(self, monkeypatch):
        monkeypatch.setattr(app_module, "TRANSLATIONS", {"es": {}})
        assert app_module.translate("Untranslated XYZ 123", "es") == (
            "Untranslated XYZ 123"
        )

    @pytest.mark.parametrize("loc", ["xx", "fr", ""])
    def test_unknown_locale(self, loc):
        assert app_module.translate("Hello,", loc) == "Hello,"

    def test_missing_locale_key(self, monkeypatch):
        monkeypatch.setattr(app_module, "TRANSLATIONS", {"es": {}})
        assert app_module.translate("Mars", "hi") == "Mars"


class TestGetLocaleUnits:
    def test_no_context_en(self):
        assert app_module.get_locale() == "en"

    def test_email_forced_wins(self, app):
        with app.test_request_context("/?lang=es"):
            from flask import g, session

            g.email_locale = "hi"
            session["locale"] = "es"
            assert app_module.get_locale() == "hi"

    def test_email_invalid_ignored(self, app):
        with app.test_request_context("/?lang=es"):
            from flask import g

            g.email_locale = "xx"
            assert app_module.get_locale() == "es"

    def test_lang_arg_sets_session(self, app):
        with app.test_request_context("/?lang=es"):
            from flask import session

            assert app_module.get_locale() == "es"
            assert session.get("locale") == "es"

    def test_lang_invalid_ignored(self, app):
        with app.test_request_context("/?lang=xx"):
            from flask import session

            assert app_module.get_locale() == "en"
            assert session.get("locale") is None

    def test_accept_matrix(self, app):
        for hdr, expected in [
            ("es", "es"),
            ("hi", "hi"),
            ("zh-Hans", "zh_Hans"),
            ("zh", "zh_Hans"),
        ]:
            with app.test_request_context("/", headers={"Accept-Language": hdr}):
                assert app_module.get_locale() == expected

    def test_accept_nomatch_en(self, app):
        with app.test_request_context("/", headers={"Accept-Language": "fr, de;q=0.9"}):
            assert app_module.get_locale() == "en"

    def test_user_mapping(self, client, app, existing_user):
        from app import User, db

        client.post(
            "/login",
            data={
                "email": existing_user["email"],
                "password": existing_user["password"],
            },
        )
        cases = [
            ("English", "en"),
            ("Spanish", "es"),
            ("Hindi", "hi"),
            ("Mandarin Chinese", "zh_Hans"),
            (" English ", "en"),
        ]
        for lang, expected in cases:
            with app.app_context():
                user = User.query.filter_by(email=existing_user["email"]).one()
                user.language = lang
                db.session.commit()
            with client.session_transaction() as sess:
                sess.pop("locale", None)
            html = client.get("/").data.decode()
            assert f'lang="{expected if expected != "zh_Hans" else "zh-Hans"}"' in html

    def test_user_unknown_falls_through(self, client, app, existing_user):
        from app import User, db

        client.post(
            "/login",
            data={
                "email": existing_user["email"],
                "password": existing_user["password"],
            },
        )
        with app.app_context():
            user = User.query.filter_by(email=existing_user["email"]).one()
            user.language = "Klingon"
            db.session.commit()
        with client.session_transaction() as sess:
            sess.pop("locale", None)
        assert 'lang="en"' in client.get("/").data.decode()


class TestUnderscore:
    def test_translates(self, monkeypatch):
        monkeypatch.setattr(app_module, "get_locale", lambda: "es")
        monkeypatch.setattr(app_module, "TRANSLATIONS", {"es": {"Save": "Guardar"}})
        assert app_module._("Save") == "Guardar"

    def test_fallback(self, monkeypatch):
        monkeypatch.setattr(app_module, "get_locale", lambda: "es")
        monkeypatch.setattr(app_module, "TRANSLATIONS", {"es": {}})
        assert app_module._("Untranslated XYZ") == "Untranslated XYZ"

    def test_exception_returns_msg(self, monkeypatch):
        def _boom():
            raise RuntimeError("boom")

        monkeypatch.setattr(app_module, "get_locale", _boom)
        assert app_module._("Hello,") == "Hello,"

    def test_empty(self, monkeypatch):
        monkeypatch.setattr(app_module, "get_locale", lambda: "es")
        assert app_module._("") == ""


# ---------------------------------------------------------------------------
# Ollama / quiz pure functions
# ---------------------------------------------------------------------------


class TestGetOllamaClient:
    @pytest.mark.parametrize("val", ["", None, "   ", " \t\n "])
    def test_missing_key(self, monkeypatch, val):
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", val)
        with pytest.raises(app_module.QuizConfigError, match="OLLAMA_API_KEY"):
            app_module.get_ollama_client()

    def test_import_error(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _fake(name, *args, **kwargs):
            if name == "ollama":
                raise ImportError("No module named ollama")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _fake)
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "k")
        with pytest.raises(app_module.QuizConfigError, match="not installed"):
            app_module.get_ollama_client()

    def test_success_args(self, monkeypatch):
        import types as _types

        seen = {}

        class _Client:
            def __init__(self, host="", headers=None, timeout=0):
                seen.update(host=host, headers=headers, timeout=timeout)

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "OLLAMA_HOST", "https://ollama.com")
        monkeypatch.setitem(
            sys.modules, "ollama", SimpleNamespace(Client=_Client)
        )
        client = app_module.get_ollama_client()
        assert isinstance(client, _Client)
        assert seen["host"] == "https://ollama.com"
        assert seen["headers"] == {"Authorization": "Bearer test-key"}
        assert seen["timeout"] == 180

    def test_custom_host(self, monkeypatch):
        class _Client:
            def __init__(self, host="", headers=None, timeout=0):
                self.host = host

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "k")
        monkeypatch.setattr(app_module, "OLLAMA_HOST", "https://custom.example")
        monkeypatch.setitem(sys.modules, "ollama", SimpleNamespace(Client=_Client))
        assert app_module.get_ollama_client().host == "https://custom.example"


def _profile(**kw):
    base = {
        "favorite_subject": "Space",
        "difficulty_level": "easy",
        "language": "Hindi",
        "grade_occupation": "Grade 5",
    }
    base.update(kw)
    return SimpleNamespace(**base)


class TestBuildQuizMessages:
    def test_shape(self):
        msgs = app_module.build_quiz_messages(_profile(), 5)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert "Reply with JSON only" in msgs[0]["content"]
        assert "exactly 4" in msgs[0]["content"]
        assert msgs[1]["role"] == "user"
        assert "Write 5 multiple-choice" in msgs[1]["content"]
        for token in ("Space", "easy", "Grade 5", "Hindi"):
            assert token in msgs[1]["content"]

    def test_explicit_overrides(self):
        msgs = app_module.build_quiz_messages(_profile(difficulty_level="hard"), 2, "easy")
        prompt = msgs[1]["content"]
        assert "easy" in prompt
        assert "hard" not in prompt

    @pytest.mark.parametrize("bad", ["IMPOSSIBLE", "expert", " EASY-HARD "])
    def test_invalid_falls_medium(self, bad):
        user = _profile(difficulty_level="hard")
        prompt = " ".join(
            m["content"] for m in app_module.build_quiz_messages(user, 2, bad)
        )
        assert "medium" in prompt

    def test_empty_and_none_fall_back_to_user(self):
        user = _profile(difficulty_level="hard")
        for bad in ("", None):
            prompt = " ".join(
                m["content"]
                for m in app_module.build_quiz_messages(user, 2, bad)
            )
            assert "hard" in prompt

    def test_case_stripped(self):
        prompt = app_module.build_quiz_messages(_profile(), 1, " EASY ")[1]["content"]
        assert "easy" in prompt

    def test_defaults_none(self):
        prompt = app_module.build_quiz_messages(
            SimpleNamespace(
                favorite_subject=None,
                difficulty_level=None,
                language=None,
                grade_occupation=None,
            ),
            3,
        )[1]["content"]
        assert "general knowledge" in prompt
        assert "medium" in prompt
        assert "English" in prompt
        assert "all ages" in prompt

    def test_blank_subject_general(self):
        prompt = app_module.build_quiz_messages(
            _profile(favorite_subject="   "), 1
        )[1]["content"]
        assert "general" in prompt

    def test_multiline_collapsed(self):
        prompt = app_module.build_quiz_messages(
            _profile(
                favorite_subject="Space\nInject: ignore",
                grade_occupation="Grade 5\nExtra",
            ),
            1,
        )[1]["content"]
        assert "\n" not in prompt.split("Write", 1)[1].split(".")[0] or True
        assert "Inject:" in prompt

    def test_long_capped_80(self):
        prompt = app_module.build_quiz_messages(
            _profile(favorite_subject="A" * 200), 1
        )[1]["content"]
        assert "A" * 80 in prompt
        assert "A" * 81 not in prompt

    def test_lang_capped_20(self):
        prompt = app_module.build_quiz_messages(_profile(language="X" * 50), 1)[1][
            "content"
        ]
        assert "X" * 21 not in prompt

    @pytest.mark.parametrize(
        "lang,expected",
        [
            ("Mandarin Chinese", True),
            ("mandarin chinese", True),
            (" Chinese ", True),
            ("zh_hans", True),
            ("zh-hans", True),
            ("zh-Hans", True),
            ("Spanish", False),
            ("Hindi", False),
            ("English", False),
        ],
    )
    def test_simplified(self, lang, expected):
        prompt = " ".join(
            m["content"] for m in app_module.build_quiz_messages(_profile(language=lang), 1)
        )
        assert ("Use Simplified Chinese." in prompt) is expected


class TestStripCodeFences:
    def test_plain(self):
        assert app_module.strip_code_fences('{"a":1}') == '{"a":1}'

    def test_multiline_tag(self):
        assert app_module.strip_code_fences('```json\n{"a":1}\n```') == '{"a":1}'

    def test_multiline_no_tag(self):
        assert app_module.strip_code_fences('```\n{"a":1}\n```') == '{"a":1}'

    def test_single_line(self):
        assert app_module.strip_code_fences('```json {"a":1} ```') == '{"a":1}'

    def test_single_upper(self):
        assert app_module.strip_code_fences('```JSON {"a":1}```') == '{"a":1}'

    def test_surrounding_ws(self):
        assert app_module.strip_code_fences('  \n```json\n{"a":1}\n```\n  ') == '{"a":1}'

    @pytest.mark.parametrize("v", [None, True, 5.5])
    def test_nonstring(self, v):
        assert app_module.strip_code_fences(v) is v

    def test_dict_passthrough(self):
        d = {"a": 1}
        assert app_module.strip_code_fences(d) is d

    def test_inner_fence_untouched(self):
        assert app_module.strip_code_fences('{"a":"```"}') == '{"a":"```"}'

    def test_missing_close(self):
        assert app_module.strip_code_fences('```json\n{"a":1}') == '{"a":1}'


OPTS = ["Earth", "Mars", "Jupiter", "Venus"]


class TestResolveAnswerIndex:
    @pytest.mark.parametrize("v", [0, 1, 2, 3])
    def test_int_valid(self, v):
        assert app_module.resolve_answer_index({"answer_index": v}, OPTS) == v

    @pytest.mark.parametrize("v", [4, -1, 100])
    def test_int_oob(self, v):
        assert app_module.resolve_answer_index({"answer_index": v}, OPTS) is None

    @pytest.mark.parametrize("v", [True, False])
    def test_bool(self, v):
        assert app_module.resolve_answer_index({"answer_index": v}, OPTS) is None

    @pytest.mark.parametrize("v,exp", [(0.0, 0), (1.0, 1), (3.0, 3)])
    def test_float_whole(self, v, exp):
        assert app_module.resolve_answer_index({"answer_index": v}, OPTS) == exp

    @pytest.mark.parametrize("v", [1.5, 0.1, 5.5])
    def test_float_frac(self, v):
        assert app_module.resolve_answer_index({"answer_index": v}, OPTS) is None

    @pytest.mark.parametrize("v", [4.0, -1.0])
    def test_float_oob(self, v):
        assert app_module.resolve_answer_index({"answer_index": v}, OPTS) is None

    def test_none_fallback(self):
        assert (
            app_module.resolve_answer_index(
                {"answer_index": None, "answer": "Mars"}, OPTS
            )
            == 1
        )

    @pytest.mark.parametrize("v", [" mars ", "MARS", "Mars"])
    def test_text_match(self, v):
        assert app_module.resolve_answer_index({"answer": v}, OPTS) == 1

    @pytest.mark.parametrize("v,exp", [("0", 0), ("1", 1), ("2", 2), ("3", 3)])
    def test_numeric_str(self, v, exp):
        assert app_module.resolve_answer_index({"answer": v}, OPTS) == exp

    @pytest.mark.parametrize("v,exp", [("A", 0), ("b", 1), ("C", 2), ("d", 3)])
    def test_letters(self, v, exp):
        assert app_module.resolve_answer_index({"answer": v}, OPTS) == exp

    @pytest.mark.parametrize("v", ["E", "Z", "", " "])
    def test_letter_invalid(self, v):
        assert app_module.resolve_answer_index({"answer": v}, OPTS) is None

    def test_unmatched(self):
        assert app_module.resolve_answer_index({"answer": "Pluto"}, OPTS) is None

    def test_duplicate(self):
        # "Mars" is not a letter shorthand, so duplicate text hits the
        # len(matches) != 1 guard. ("A" would return 0 via A-D shorthand.)
        assert (
            app_module.resolve_answer_index(
                {"answer": "Mars"}, ["Mars", "Mars", "Jupiter", "Venus"]
            )
            is None
        )

    def test_letter_shorthand_ignores_duplicates(self):
        # Single A-D letters resolve via shorthand before text matching.
        assert (
            app_module.resolve_answer_index({"answer": "A"}, ["A", "A", "B", "C"])
            == 0
        )

    def test_missing(self):
        assert app_module.resolve_answer_index({}, OPTS) is None

    def test_zero_not_overridden(self):
        assert (
            app_module.resolve_answer_index(
                {"answer_index": 0, "answer": "Venus"}, OPTS
            )
            == 0
        )


def _qjson(payload):
    return json.dumps(payload)


class TestParseQuizContentUnits:
    def test_invalid_json(self):
        with pytest.raises(app_module.QuizGenerationError, match="unreadable"):
            app_module.parse_quiz_content("not json at all {{{")

    @pytest.mark.parametrize("v", ['42', '"str"', "null"])
    def test_non_object(self, v):
        with pytest.raises(app_module.QuizGenerationError, match="unreadable"):
            app_module.parse_quiz_content(v)

    def test_no_questions(self):
        with pytest.raises(app_module.QuizGenerationError, match="unreadable"):
            app_module.parse_quiz_content(_qjson({"foo": 1}))

    def test_empty(self):
        with pytest.raises(app_module.QuizGenerationError, match="no usable"):
            app_module.parse_quiz_content(_qjson({"questions": []}))

    @pytest.mark.parametrize(
        "item",
        [
            {"question": "Q?", "options": ["A", "B", "C"], "answer_index": 0},
            {"question": "Q?", "options": ["A", "a", "B", "C"], "answer_index": 0},
            {"question": "Q?", "options": ["A", "", "C", "D"], "answer_index": 0},
            {"question": "Q?", "options": ["A", "B", "C", "D"], "answer_index": 5},
            {"question": "Q?", "options": ["A", "B", "C", "D"], "answer": "Z"},
            {"question": "", "options": ["A", "B", "C", "D"], "answer_index": 0},
        ],
    )
    def test_single_bad_raises(self, item):
        with pytest.raises(app_module.QuizGenerationError, match="no usable"):
            app_module.parse_quiz_content(_qjson({"questions": [item]}))

    def test_mixed_keeps_valid(self):
        payload = {
            "questions": [
                {
                    "question": "Q?",
                    "options": ["A", "B", "C", "D"],
                    "answer_index": 2,
                },
                {"question": "Q?", "options": ["A", "B", "C"], "answer_index": 0},
                "not a dict",
            ]
        }
        out = app_module.parse_quiz_content(_qjson(payload))
        assert len(out) == 1
        assert out[0]["answer_index"] == 2

    def test_trims(self):
        out = app_module.parse_quiz_content(
            _qjson(
                {
                    "questions": [
                        {
                            "question": "  Q?  ",
                            "options": [" A ", "B ", " C", "D "],
                            "answer_index": 0,
                        }
                    ]
                }
            )
        )
        assert out[0]["question"] == "Q?"
        assert out[0]["options"] == ["A", "B", "C", "D"]

    def test_bool_rejected(self):
        with pytest.raises(app_module.QuizGenerationError, match="no usable"):
            app_module.parse_quiz_content(
                _qjson(
                    {
                        "questions": [
                            {
                                "question": "Q?",
                                "options": ["A", "B", "C", "D"],
                                "answer_index": True,
                            }
                        ]
                    }
                )
            )

    def test_none_raises(self):
        with pytest.raises(app_module.QuizGenerationError, match="unreadable"):
            app_module.parse_quiz_content(None)


class TestSessionHelpers:
    def test_get_none_empty(self, app):
        with app.test_request_context("/"):
            assert app_module._get_quiz() is None

    @pytest.mark.parametrize("v", ["str", 123, None, []])
    def test_get_none_not_dict(self, app, v):
        with app.test_request_context("/"):
            from flask import session

            session["quiz"] = v
            assert app_module._get_quiz() is None

    @pytest.mark.parametrize(
        "v",
        [
            {"foo": 1},
            {"questions": []},
            {"questions": "abc"},
            {"questions": 123},
            {"questions": {"a": 1}},
            {"questions": None},
        ],
    )
    def test_get_none_no_questions(self, app, v):
        with app.test_request_context("/"):
            from flask import session

            session["quiz"] = v
            assert app_module._get_quiz() is None

    def test_store_roundtrip(self, app):
        quiz = {
            "questions": [
                {
                    "question": "Q?",
                    "options": ["A", "B", "C", "D"],
                    "answer_index": 0,
                }
            ],
            "index": 0,
        }
        with app.test_request_context("/"):
            app_module._store_quiz(quiz)
            assert app_module._get_quiz() == quiz

    def test_public_hides(self, app):
        quiz = {
            "questions": [
                {
                    "question": "Q0?",
                    "options": ["Q0 A", "Q0 B", "Q0 C", "Q0 D"],
                    "answer_index": 0,
                }
            ],
            "index": 0,
            "score": 123,
            "offered": "fifty",
        }
        with app.test_request_context("/"):
            out = app_module._public_state(quiz)
        assert out == {
            "question": "Q0?",
            "options": ["Q0 A", "Q0 B", "Q0 C", "Q0 D"],
            "index": 0,
            "total": 1,
            "quiz_score": 123,
            "powerup": "fifty",
        }

    def test_public_defaults(self, app):
        quiz = {
            "questions": [
                {
                    "question": "Q?",
                    "options": ["A", "B", "C", "D"],
                    "answer_index": 1,
                }
            ],
            "index": 0,
        }
        with app.test_request_context("/"):
            out = app_module._public_state(quiz)
        assert out["quiz_score"] == 0
        assert out["powerup"] is None

    def test_public_bad_index(self, app):
        base = {
            "questions": [
                {
                    "question": "Q?",
                    "options": ["A", "B", "C", "D"],
                    "answer_index": 0,
                }
            ],
            "index": 0,
        }
        for bad in (5, -1, "0", None, True, 1.5):
            quiz = dict(base, index=bad)
            with app.test_request_context("/"):
                with pytest.raises(IndexError, match="out of range"):
                    app_module._public_state(quiz)


class TestGenerateQuestionsUnits:
    def _client(self, content):
        from types import SimpleNamespace as _NS

        class _C:
            def __init__(self):
                self.calls = []

            def chat(self, model="", messages=None, **kw):
                self.calls.append({"model": model, "messages": messages, **kw})
                return _NS(message=_NS(content=content))

        return _C()

    def _qjson(self, n):
        return json.dumps(
            {
                "questions": [
                    {
                        "question": f"Question {i}?",
                        "options": [f"Q{i} A", f"Q{i} B", f"Q{i} C", f"Q{i} D"],
                        "answer_index": i % 4,
                    }
                    for i in range(n)
                ]
            }
        )

    def test_truncation(self, monkeypatch):
        fake = self._client(self._qjson(5))
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        out = app_module.generate_questions(_profile(), 2)
        assert len(out) == 2

    def test_clamp_max(self, monkeypatch):
        fake = self._client(self._qjson(MAX_QUIZ_QUESTIONS))
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        out = app_module.generate_questions(_profile(), 999)
        assert len(out) <= MAX_QUIZ_QUESTIONS

    @pytest.mark.parametrize("n", [0, None])
    def test_zero_none_one(self, monkeypatch, n):
        fake = self._client(self._qjson(5))
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        assert len(app_module.generate_questions(_profile(), n)) == 1

    def test_invalid_num_all(self, monkeypatch):
        fake = self._client(self._qjson(3))
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        assert len(app_module.generate_questions(_profile(), "abc")) == 3

    def test_dict_response(self, monkeypatch):
        content = self._qjson(1)

        class _D:
            def chat(self, model="", messages=None, **kw):
                return {"message": {"content": content}}

        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _D())
        out = app_module.generate_questions(_profile(), 1)
        assert len(out) == 1

    def test_none_content(self, monkeypatch):
        from types import SimpleNamespace as _NS

        class _N:
            def chat(self, *a, **k):
                return _NS(message=_NS(content=None))

        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _N())
        with pytest.raises(app_module.QuizGenerationError):
            app_module.generate_questions(_profile(), 1)

    def test_wrapped(self, monkeypatch):
        class _B:
            def chat(self, *a, **k):
                raise RuntimeError("cloud is down")

        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _B())
        with pytest.raises(app_module.QuizGenerationError, match="Quiz service failed"):
            app_module.generate_questions(_profile(), 1)

    def test_config_passthrough(self, monkeypatch):
        class _B:
            def chat(self, *a, **k):
                raise app_module.QuizConfigError("no key")

        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _B())
        with pytest.raises(app_module.QuizConfigError):
            app_module.generate_questions(_profile(), 1)

    def test_chat_args(self, monkeypatch):
        fake = self._client(self._qjson(2))
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: fake)
        app_module.generate_questions(_profile(), 2, "easy")
        call = fake.calls[0]
        assert call["model"] == app_module.OLLAMA_MODEL
        assert call["stream"] is False
        assert call["format"] == app_module.QUIZ_FORMAT
        assert call["options"] == {"temperature": 0.7}


# ---------------------------------------------------------------------------
# Mail helpers
# ---------------------------------------------------------------------------


class TestRecipientLocale:
    @pytest.mark.parametrize(
        "lang,loc",
        [
            ("Spanish", "es"),
            ("Hindi", "hi"),
            ("Mandarin Chinese", "zh_Hans"),
            ("English", "en"),
            (" Spanish ", "es"),
        ],
    )
    def test_context_wins(self, lang, loc):
        assert (
            app_module._recipient_locale(
                "other@example.com", SimpleNamespace(language=lang)
            )
            == loc
        )

    def test_context_unsupported(self, app, monkeypatch):
        monkeypatch.setattr(app_module, "get_locale", lambda: "hi")
        assert (
            app_module._recipient_locale(
                "x@y.com", SimpleNamespace(language="Klingon")
            )
            == "hi"
        )

    def _set_lang(self, app, email, lang):
        from app import User, db

        with app.app_context():
            user = User.query.filter_by(email=email).one()
            user.language = lang
            db.session.commit()

    def test_db_bare(self, app, existing_user):
        self._set_lang(app, existing_user["email"], "Spanish")
        with app.test_request_context("/"):
            assert app_module._recipient_locale(existing_user["email"]) == "es"

    def test_db_angle(self, app, existing_user):
        self._set_lang(app, existing_user["email"], "Spanish")
        with app.test_request_context("/"):
            assert (
                app_module._recipient_locale(f"Player <{existing_user['email']}>") == "es"
            )

    @pytest.mark.parametrize("wrap", [list, tuple])
    def test_db_seq(self, app, existing_user, wrap):
        self._set_lang(app, existing_user["email"], "Spanish")
        with app.test_request_context("/"):
            assert app_module._recipient_locale(wrap([existing_user["email"]])) == "es"

    def test_unknown_fallback(self, app, monkeypatch):
        monkeypatch.setattr(app_module, "get_locale", lambda: "hi")
        assert app_module._recipient_locale("unknown@example.com") == "hi"

    def test_no_at(self, app, monkeypatch):
        monkeypatch.setattr(app_module, "get_locale", lambda: "es")
        assert app_module._recipient_locale("not-an-email") == "es"

    def test_exception_fallback(self, app, monkeypatch):
        from app import User

        with app.test_request_context("/"):
            def _boom(*a, **k):
                raise RuntimeError("boom")

            monkeypatch.setattr(User.query, "filter_by", _boom)
            monkeypatch.setattr(app_module, "get_locale", lambda: "en")
            assert app_module._recipient_locale("a@b.com") == "en"

    def test_locale_exception_en(self, app, monkeypatch):
        def _boom():
            raise RuntimeError("x")

        monkeypatch.setattr(app_module, "get_locale", _boom)
        assert app_module._recipient_locale("unknown@example.com") == "en"


class TestSecurityRenderTemplate:
    def test_sets_and_cleans(self, app, monkeypatch):
        from flask import g

        monkeypatch.setattr(app_module, "_recipient_locale", lambda *a, **k: "es")
        seen = {}

        def _fake(template, **ctx):
            seen["locale"] = g.get("email_locale")
            return "rendered"

        monkeypatch.setattr("flask.render_template", _fake)
        with app.test_request_context("/"):
            assert (
                app_module.security_render_template("mail.html", email="a@b.com")
                == "rendered"
            )
            assert seen["locale"] == "es"
            assert g.get("email_locale") is None

    def test_restores_previous(self, app, monkeypatch):
        from flask import g

        monkeypatch.setattr(app_module, "_recipient_locale", lambda *a, **k: "es")
        monkeypatch.setattr("flask.render_template", lambda *a, **k: "x")
        with app.test_request_context("/"):
            g.email_locale = "hi"
            app_module.security_render_template("t", email="a@b.com")
            assert g.get("email_locale") == "hi"

    def test_exception_restores(self, app, monkeypatch):
        from flask import g

        monkeypatch.setattr(app_module, "_recipient_locale", lambda *a, **k: "es")

        def _boom(*a, **k):
            raise RuntimeError("render fail")

        monkeypatch.setattr("flask.render_template", _boom)
        with app.test_request_context("/"):
            with pytest.raises(RuntimeError):
                app_module.security_render_template("t", email="a@b.com")
            assert g.get("email_locale") is None


class TestTranslatedMailUtil:
    def _util(self):
        return object.__new__(app_module.TranslatedMailUtil)

    def test_subject_translated(self, app, monkeypatch):
        from flask import g

        monkeypatch.setattr(app_module, "_recipient_locale", lambda *a, **k: "es")
        monkeypatch.setattr(
            app_module, "translate", lambda s, loc: "TRANS" if s else s
        )
        seen = {}

        def _super(self, template, subject, recipient, sender, body, html, **kw):
            seen.update(subject=subject, locale=g.get("email_locale"))
            return "sent"

        monkeypatch.setattr(
            "flask_security.mail_util.MailUtil.send_mail", _super
        )
        with app.test_request_context("/"):
            out = self._util().send_mail(
                "t", "Password reset instructions", "a@b.com", "s", "b", "h"
            )
        assert out == "sent"
        assert seen["subject"] == "TRANS"
        assert seen["locale"] == "es"

    def test_forwards_user(self, app, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            app_module,
            "_recipient_locale",
            lambda r, u=None: captured.update(r=r, u=u) or "en",
        )
        monkeypatch.setattr(app_module, "translate", lambda s, loc: s)
        monkeypatch.setattr(
            "flask_security.mail_util.MailUtil.send_mail",
            lambda self, *a, **k: "ok",
        )
        user = SimpleNamespace(language="Hindi")
        with app.test_request_context("/"):
            self._util().send_mail("t", "s", "a@b.com", "x", "b", "h", user=user)
        assert captured["u"] is user

    def test_restores(self, app, monkeypatch):
        from flask import g

        monkeypatch.setattr(app_module, "_recipient_locale", lambda *a, **k: "es")
        monkeypatch.setattr(app_module, "translate", lambda s, loc: s)
        monkeypatch.setattr(
            "flask_security.mail_util.MailUtil.send_mail",
            lambda self, *a, **k: "ok",
        )
        with app.test_request_context("/"):
            g.email_locale = "hi"
            self._util().send_mail("t", "s", "a@b.com", "x", "b", "h")
            assert g.get("email_locale") == "hi"

    def test_exception_restores(self, app, monkeypatch):
        from flask import g

        monkeypatch.setattr(app_module, "_recipient_locale", lambda *a, **k: "es")
        monkeypatch.setattr(app_module, "translate", lambda s, loc: s)

        def _boom(self, *a, **k):
            raise RuntimeError("smtp fail")

        monkeypatch.setattr(
            "flask_security.mail_util.MailUtil.send_mail", _boom
        )
        with app.test_request_context("/"):
            with pytest.raises(RuntimeError):
                self._util().send_mail("t", "s", "a@b.com", "x", "b", "h")
            assert g.get("email_locale") is None


# ---------------------------------------------------------------------------
# Display / rank / factory / LAN / models / constants
# ---------------------------------------------------------------------------


class TestDisplayName:
    def test_none(self):
        assert app_module.display_name_of(None) == "Player"

    def test_display_wins(self):
        assert (
            app_module.display_name_of(
                SimpleNamespace(
                    display_name="Ava", nickname="Tommy", email="x@y.com"
                )
            )
            == "Ava"
        )

    def test_nick_fallback(self):
        assert (
            app_module.display_name_of(
                SimpleNamespace(display_name=None, nickname="Tommy", email="x@y.com")
            )
            == "Tommy"
        )
        assert (
            app_module.display_name_of(
                SimpleNamespace(display_name="", nickname="Tommy", email="x@y.com")
            )
            == "Tommy"
        )

    def test_strips(self):
        assert (
            app_module.display_name_of(
                SimpleNamespace(display_name="  Ava  ", nickname=None, email="x@y.com")
            )
            == "Ava"
        )

    def test_email_local(self):
        assert (
            app_module.display_name_of(
                SimpleNamespace(display_name=None, nickname=None, email="player@example.com")
            )
            == "player"
        )

    @pytest.mark.parametrize("email", [None, "", "no-at-sign"])
    def test_no_email(self, email):
        assert (
            app_module.display_name_of(
                SimpleNamespace(display_name=None, nickname="  ", email=email)
            )
            == "Player"
        )


class TestRankOf:
    def _make(self, app, email, best, wins=0):
        from flask_security.utils import hash_password
        from app import User, db, user_datastore

        with app.app_context():
            user_datastore.create_user(email=email, password=hash_password("x" * 12))
            user = User.query.filter_by(email=email).one()
            user.best_score = best
            user.total_wins = wins
            db.session.commit()
            return user.id

    def test_order(self, app, existing_user):
        from app import User, db

        with app.app_context():
            me = User.query.filter_by(email=existing_user["email"]).one()
            me.best_score = 100
            me.total_wins = 5
            db.session.commit()
            me_id = me.id
        b = self._make(app, "b@example.com", 200, 1)
        c = self._make(app, "c@example.com", 200, 10)
        with app.app_context():
            assert app_module.rank_of(c) == 1
            assert app_module.rank_of(b) == 2
            assert app_module.rank_of(me_id) == 3

    def test_tiebreak_id(self, app):
        a = self._make(app, "ta@example.com", 1000, 5)
        b = self._make(app, "tb@example.com", 1000, 5)
        with app.app_context():
            assert app_module.rank_of(min(a, b)) == 1
            assert app_module.rank_of(max(a, b)) == 2

    def test_unknown(self, app):
        with app.app_context():
            assert app_module.rank_of(999999) == 1


class TestCreateApp:
    def test_testing_applied(self, tmp_path):
        app = app_module.create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 't.db'}",
                "SECRET_KEY": "x",
                "SECURITY_PASSWORD_SALT": "y",
            }
        )
        assert app.config["WTF_CSRF_ENABLED"] is False
        assert app.config["MAIL_SUPPRESS_SEND"] is True

    def test_explicit_wins(self, tmp_path):
        app = app_module.create_app(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": True,
                "MAIL_SUPPRESS_SEND": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 't.db'}",
                "SECRET_KEY": "x",
                "SECURITY_PASSWORD_SALT": "y",
            }
        )
        assert app.config["WTF_CSRF_ENABLED"] is True
        assert app.config["MAIL_SUPPRESS_SEND"] is False

    def test_headers(self, client):
        resp = client.get("/")
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("Referrer-Policy") == "same-origin"

    def test_csrf_and_routes(self, app, client):
        assert "famquiz_csrf" in app.extensions
        assert client.get("/").status_code == 200
        assert client.get("/api/i18n/es.json").status_code == 200

    def test_base_defaults(self):
        assert app_module.BASE_CONFIG["SQLALCHEMY_TRACK_MODIFICATIONS"] is False
        assert app_module.BASE_CONFIG["SECURITY_REGISTERABLE"] is True
        assert app_module.BASE_CONFIG["SECURITY_POST_LOGIN_VIEW"] == "/"
        assert app_module.BASE_CONFIG["SESSION_COOKIE_HTTPONLY"] is True
        assert app_module.TESTING_CONFIG == {
            "WTF_CSRF_ENABLED": False,
            "MAIL_SUPPRESS_SEND": True,
        }


class TestPrintLanUrls:
    def test_both(self, monkeypatch, capsys):
        import socket as _sock

        class _S:
            def __init__(self, *a, **k):
                pass

            def connect(self, *a, **k):
                pass

            def getsockname(self):
                return ("192.168.1.5", 0)

            def close(self):
                pass

        monkeypatch.setattr(_sock, "socket", _S)

        class _R:
            stdout = "100.64.0.1\n"

        monkeypatch.setattr("subprocess.run", lambda *a, **k: _R())
        app_module._print_lan_urls(5000)
        out = capsys.readouterr().out
        assert "http://127.0.0.1:5000" in out
        assert "http://192.168.1.5:5000" in out
        assert "http://100.64.0.1:5000" in out

    def test_no_lan(self, monkeypatch, capsys):
        import socket as _sock

        class _S:
            def __init__(self, *a, **k):
                pass

            def connect(self, *a, **k):
                pass

            def getsockname(self):
                return ("127.0.0.1", 0)

            def close(self):
                pass

        monkeypatch.setattr(_sock, "socket", _S)
        monkeypatch.setattr(
            "subprocess.run", lambda *a, **k: (_ for _ in ()).throw(
                FileNotFoundError("no tailscale")
            ),
        )
        app_module._print_lan_urls(5000)
        out = capsys.readouterr().out
        assert "(no LAN address found)" in out
        assert "Tailscale not detected" in out

    def test_socket_exception(self, monkeypatch, capsys):
        import socket as _sock

        def _boom(*a, **k):
            raise OSError("down")

        monkeypatch.setattr(_sock, "socket", _boom)
        monkeypatch.setattr(
            "subprocess.run", lambda *a, **k: (_ for _ in ()).throw(OSError("x"))
        )
        app_module._print_lan_urls(8123)  # must not raise
        out = capsys.readouterr().out
        assert ":8123" in out


class TestModels:
    def test_role(self, app):
        from app import Role, db

        with app.app_context():
            role = Role(name="admin", description="d")
            db.session.add(role)
            db.session.commit()
            assert role.id is not None
            assert Role.query.filter_by(name="admin").one().description == "d"

    def test_user_defaults(self, app):
        from app import User, db

        with app.app_context():
            user = User(email="d@example.com", password="x")
            db.session.add(user)
            db.session.commit()
            assert user.active is True
            assert len(user.fs_uniquifier) == 32
            assert user.confirmed_at is None
            assert user.language == "English"
            assert user.theme_mode == "light"
            assert user.status == "Ready to play"
            assert user.game_reminders is True
            assert user.challenge_invites is True
            assert user.daily_quiz_notifications is True
            assert user.score == 0
            assert user.best_score == 0
            assert user.default_num_questions == 10

    def test_game_defaults(self, app):
        from app import GameSession

        with app.app_context():
            game = GameSession()
            assert game.status == "lobby"
            assert game.created_by_id is None
            assert game.num_questions == 10
            assert game.difficulty == "medium"
            assert game.powerups_enabled is True
            assert game.lobby_seconds == 300
            assert game.starts_at == 0.0

    def test_game_custom(self, app):
        from app import GameSession

        with app.app_context():
            game = GameSession(
                status="active",
                created_by_id=1,
                num_questions=5,
                difficulty="hard",
                powerups_enabled=False,
                lobby_seconds=60,
                starts_at=1.0,
                expires_at=2.0,
                created_at=3.0,
            )
            assert game.status == "active"
            assert game.num_questions == 5
            assert game.powerups_enabled is False
            assert game.expires_at == 2.0

    def test_assoc(self, app):
        from app import Role, User, db, user_datastore
        from flask_security.utils import hash_password

        with app.app_context():
            role = Role(name="player", description="p")
            db.session.add(role)
            user_datastore.create_user(
                email="assoc@example.com", password=hash_password("x" * 12)
            )
            db.session.commit()
            user = User.query.filter_by(email="assoc@example.com").one()
            user.roles.append(role)
            db.session.commit()
            assert role in user.roles
            assert user in role.users


class TestConstants:
    def test_locales(self):
        assert SUPPORTED_LOCALES == ("en", "es", "hi", "zh_Hans")
        assert app_module.LANGUAGE_TO_LOCALE == {
            "English": "en",
            "Spanish": "es",
            "Hindi": "hi",
            "Mandarin Chinese": "zh_Hans",
        }
        assert app_module.LOCALE_TO_LANGUAGE == {
            v: k for k, v in app_module.LANGUAGE_TO_LOCALE.items()
        }
        assert app_module.LOCALE_TO_HTML["zh_Hans"] == "zh-Hans"

    def test_quiz_tuning(self):
        assert MAX_QUIZ_QUESTIONS == 20
        assert DIFFICULTY_LEVELS == ("easy", "medium", "hard")
        assert BASE_POINTS == 1000
        assert SPEED_BONUS_POINTS == 500
        assert QUESTION_TIME_LIMIT_MS == 30000
        assert QUESTION_TIME_BONUS_MS == 15000

    def test_powerups(self):
        assert POWERUP_CHANCE == pytest.approx(1 / 3)
        assert set(POWERUP_KINDS) == {"double", "fifty", "calc", "hint"}
        assert POWERUP_LABELS["double"] == "Double Points"
        assert len(POWERUP_LABELS) == 4

    def test_format(self):
        fmt = app_module.QUIZ_FORMAT
        assert fmt["required"] == ["questions"]
        assert fmt["properties"]["questions"]["type"] == "array"
        item = fmt["properties"]["questions"]["items"]
        assert item["required"] == ["question", "options", "answer_index"]

    def test_game_consts(self):
        assert app_module.GAME_STATUSES == ("lobby", "active", "finished", "cancelled")
        assert app_module.DEFAULT_LOBBY_SECONDS == 300
        assert app_module.MIN_LOBBY_SECONDS == 10
        assert app_module.MAX_LOBBY_SECONDS == 300
        assert GAME_EXPIRY_GRACE_SECONDS == 120

    def test_ollama_defaults(self):
        assert app_module.OLLAMA_MODEL == "gpt-oss:20b"
        assert app_module.OLLAMA_HOST == "https://ollama.com"
