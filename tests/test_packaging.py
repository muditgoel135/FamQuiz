"""
Tests for the packaging entry point and the PyInstaller spec.

``run_famquiz.py`` and ``FamQuiz.spec`` had no coverage at all, which
is why the file was unimportable (no ``__main__`` guard) and the
documented build recipe could drift without anybody noticing.

The build invariants matter: a frozen exe that forgets
``translations.json`` silently serves English only, and one that loses
``templates/`` shows a blank page.
"""

import ast
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    """Read a repository file."""
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class TestEntryPointSource:
    """``run_famquiz.py`` must be importable and guarded."""

    def test_has_a_main_guard(self):
        """Without the guard, importing the module starts a server."""
        source = _read("run_famquiz.py")
        assert 'if __name__ == "__main__":' in source

    def test_app_is_imported_lazily(self):
        """``app`` must be imported *after* the database URI is set.

        ``app.BASE_CONFIG`` reads ``SQLALCHEMY_DATABASE_URI`` once, at
        import time, so an early import would put the database in the
        wrong folder.
        """
        source = _read("run_famquiz.py")
        tree = ast.parse(source)
        import_lines = []
        prepare_lines = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "app":
                        import_lines.append(node.lineno)
            if isinstance(node, ast.FunctionDef) and node.name == "prepare_env":
                prepare_lines.append(node.lineno)
        assert import_lines, "run_famquiz.py does not import app at all"
        assert prepare_lines, "run_famquiz.py has no prepare_env()"
        # The import must be inside main(), not at module level.
        assert min(import_lines) > min(prepare_lines)

    def test_never_enables_debug(self):
        """The Werkzeug debugger on a 0.0.0.0 bind is remote code execution."""
        source = _read("run_famquiz.py")
        assert "debug=False" in source
        assert "debug=True" not in source

    def test_binds_to_the_lan(self):
        """The family plays over the local network."""
        source = _read("run_famquiz.py")
        assert 'host="0.0.0.0"' in source

    def test_database_is_posix_normalised(self):
        """A Windows path breaks the SQLite URI."""
        source = _read("run_famquiz.py")
        assert '.replace("\\\\", "/")' in source


class TestEntryPointBehaviour:
    """The helpers must behave, not just look right."""

    def test_base_dir_uses_the_script_folder(self, monkeypatch):
        """Unfrozen: the folder that holds the file."""
        import run_famquiz

        monkeypatch.setattr(run_famquiz.sys, "frozen", False, raising=False)
        assert run_famquiz.base_dir() == os.path.dirname(
            os.path.abspath(run_famquiz.__file__)
        )

    def test_base_dir_uses_the_exe_folder_when_frozen(self, monkeypatch):
        """Frozen: the folder that holds the exe."""
        import run_famquiz

        monkeypatch.setattr(run_famquiz.sys, "frozen", True, raising=False)
        monkeypatch.setattr(run_famquiz.sys, "executable", "C:/Games/FamQuiz.exe")
        assert run_famquiz.base_dir() == "C:/Games"

    def test_prepare_env_points_at_the_instance_folder(self, tmp_path, monkeypatch):
        """The database must land next to the exe, not in the temp folder."""
        import run_famquiz

        monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
        uri = run_famquiz.prepare_env(str(tmp_path))
        assert uri.startswith("sqlite:///")
        assert "\\" not in uri
        assert uri.endswith("/instance/site.db")
        assert os.environ["SQLALCHEMY_DATABASE_URI"] == uri
        assert (tmp_path / "instance").is_dir()

    def test_prepare_env_is_idempotent(self, tmp_path, monkeypatch):
        """Running twice must not fail on the existing folder."""
        import run_famquiz

        monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
        first = run_famquiz.prepare_env(str(tmp_path))
        second = run_famquiz.prepare_env(str(tmp_path))
        assert first == second

    def test_dotenv_does_not_override_the_database_uri(self, tmp_path, monkeypatch):
        """A stray ``.env`` must not move the database."""
        import run_famquiz

        (tmp_path / ".env").write_text(
            "SQLALCHEMY_DATABASE_URI=sqlite:///elsewhere.db\n", encoding="utf-8"
        )
        monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
        uri = run_famquiz.prepare_env(str(tmp_path))
        assert uri.endswith("/instance/site.db")

    def test_database_uri_is_set_before_app_is_imported(self, tmp_path):
        """The frozen-layout invariant, checked in a real subprocess."""
        code = (
            "import os, sys\n"
            f"sys.path.insert(0, {os.path.join(ROOT, 'tests')!r})\n"
            f"sys.path.insert(0, {ROOT!r})\n"
            "import run_famquiz\n"
            f"run_famquiz.prepare_env({str(tmp_path)!r})\n"
            "import app\n"
            "print(app.BASE_CONFIG['SQLALCHEMY_DATABASE_URI'])\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        printed = result.stdout.strip().splitlines()[-1]
        assert printed.endswith("/instance/site.db")
        assert printed.startswith("sqlite:///")

    def test_main_binds_without_debugger(self, tmp_path, monkeypatch):
        """The server must never start in debug mode."""
        import run_famquiz

        calls = {}
        monkeypatch.setattr(run_famquiz, "base_dir", lambda: str(tmp_path))
        monkeypatch.setattr(
            run_famquiz, "prepare_env", lambda base: "sqlite:///:memory:"
        )

        import app as app_module

        monkeypatch.setattr(
            app_module.app, "run", lambda **kwargs: calls.update(kwargs)
        )
        monkeypatch.setattr(app_module, "_print_lan_urls", lambda port: None)
        monkeypatch.setenv("PORT", "5001")
        run_famquiz.main()
        assert calls["debug"] is False
        assert calls["host"] == "0.0.0.0"
        assert calls["port"] == 5001

    def test_port_defaults_to_5000(self, tmp_path, monkeypatch):
        """Without PORT the game runs on the documented port."""
        import run_famquiz

        calls = {}
        monkeypatch.setattr(run_famquiz, "base_dir", lambda: str(tmp_path))
        monkeypatch.setattr(
            run_famquiz, "prepare_env", lambda base: "sqlite:///:memory:"
        )

        import app as app_module

        monkeypatch.setattr(
            app_module.app, "run", lambda **kwargs: calls.update(kwargs)
        )
        monkeypatch.setattr(app_module, "_print_lan_urls", lambda port: None)
        monkeypatch.delenv("PORT", raising=False)
        run_famquiz.main()
        assert calls["port"] == 5000


class TestPyInstallerSpec:
    """The build recipe must stay in step with the app."""

    def test_spec_exists(self):
        """The build recipe is a source file, not a local extra."""
        assert os.path.exists(os.path.join(ROOT, "FamQuiz.spec"))

    def test_entry_script_is_the_entry_point(self):
        """The build must use the packaged entry point."""
        source = _read("FamQuiz.spec")
        assert '"run_famquiz.py"' in source

    def test_bundles_the_runtime_assets(self):
        """Missing data files break the frozen app silently."""
        source = _read("FamQuiz.spec")
        for asset in ('("templates", "templates")', '("static", "static")'):
            assert asset in source
        # translations.json must land next to app.py, or every language
        # silently falls back to English.
        assert '("translations.json", ".")' in source

    def test_bundled_assets_exist(self):
        """The spec must point at files that are really there."""
        assert os.path.isdir(os.path.join(ROOT, "templates"))
        assert os.path.isdir(os.path.join(ROOT, "static"))
        assert os.path.isfile(os.path.join(ROOT, "translations.json"))

    def test_excludes_the_test_suite(self):
        """1050+ tests must not end up inside the exe."""
        source = _read("FamQuiz.spec")
        assert "tests" in source
        assert "pytest" in source

    def test_does_not_bundle_the_secrets(self):
        """``.env`` must stay beside the exe, never inside it."""
        source = _read("FamQuiz.spec")
        assert '".env"' not in source
        assert "'.env'" not in source

    def test_is_a_single_file_build(self):
        """No COLLECT() means a one-file exe."""
        source = _read("FamQuiz.spec")
        # Parse it: the spec mentions COLLECT() in a comment, but there
        # must be no actual call.
        tree = ast.parse(source)
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "COLLECT" not in called
        assert "EXE" in called

    def test_console_is_enabled(self):
        """A windowless exe is a game nobody can stop."""
        source = _read("FamQuiz.spec")
        assert "console=True" in source

    def test_packs_flask_security(self):
        """Plain scanning misses parts of the login library."""
        source = _read("FamQuiz.spec")
        assert 'collect_all("flask_security")' in source


class TestRepoHygiene:
    """The repository must not track local artefacts."""

    def _ignored(self, path):
        """Return True when git ignores the given path."""
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0

    @pytest.mark.parametrize(
        "path",
        [
            "instance/site.db",
            "site.db",
            ".venv/anything",
            "build/anything",
            "dist/anything",
            "__pycache__/x.pyc",
            ".pytest_cache/x",
            ".env",
            ".ruff_cache/x",
            ".mypy_cache/x",
        ],
    )
    def test_local_files_are_ignored(self, path):
        """A committed database or venv would leak local state."""
        assert self._ignored(path), f"{path} should be gitignored"

    @pytest.mark.parametrize(
        "path",
        [".env.example", "requirements.txt", "requirements-dev.txt", "pytest.ini"],
    )
    def test_shared_files_are_tracked(self, path):
        """The example config must stay in the repository."""
        assert not self._ignored(path), f"{path} must not be gitignored"

    def test_packaging_sources_are_not_ignored(self):
        """README §11 needs these two files committed."""
        assert not self._ignored("run_famquiz.py")
        assert not self._ignored("FamQuiz.spec")


class TestRepoLayout:
    """The files the app needs at runtime must be where it looks."""

    def test_core_files_exist(self):
        """A missing file breaks the import or the packaging."""
        for name in (
            "app.py",
            "routes.py",
            "translations.json",
            "pytest.ini",
            "requirements.txt",
            ".env.example",
        ):
            assert os.path.exists(os.path.join(ROOT, name)), f"{name} is missing"

    def test_security_templates_exist(self):
        """Flask-Security points at these by name."""
        for name in (
            "login.html",
            "signup.html",
            "forgot_password.html",
            "reset_password.html",
            "change_password.html",
        ):
            assert os.path.exists(os.path.join(ROOT, "templates", name))

    def test_translations_sit_next_to_the_app(self):
        """``app._load_translations`` looks next to ``app.py``."""
        import app as app_module

        here = os.path.dirname(os.path.abspath(app_module.__file__))
        assert os.path.isfile(os.path.join(here, "translations.json"))

    def test_default_database_lands_in_the_instance_folder(self):
        """Flask-SQLAlchemy resolves a relative SQLite URI there."""
        from app import create_app

        flask_app = create_app(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///site.db",
            }
        )
        assert flask_app.instance_path.endswith("instance")
        assert flask_app.config["SQLALCHEMY_DATABASE_URI"].endswith("site.db")


# ==== merged from test_first_run.py ====
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    """Read a repository file."""
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class TestDefaultEnvCreation:
    """``run_famquiz.write_default_env`` creates and never clobbers."""

    def test_creates_env_with_random_secrets(self, tmp_path, monkeypatch):
        """A fresh folder gets .env with empty keys and real secrets."""
        import run_famquiz

        monkeypatch.delenv("SECRET_KEY", raising=False)
        created = run_famquiz.write_default_env(str(tmp_path))
        assert created is True
        env_path = tmp_path / ".env"
        assert env_path.is_file()
        text = env_path.read_text(encoding="utf-8")
        # The keys a parent must fill stay empty...
        assert "OLLAMA_API_KEY=\n" in text
        assert "MAIL_PASSWORD=\n" in text
        # ...and no template placeholder survives: secrets are real.
        assert "{SECRET_KEY}" not in text
        assert "{PASSWORD_SALT}" not in text
        secret_line = next(
            line for line in text.splitlines() if line.startswith("SECRET_KEY=")
        )
        assert len(secret_line.split("=", 1)[1]) >= 32
        # Boot defaults that the funnel depends on.
        assert "PORT=5000" in text
        assert "OLLAMA_HOST=https://ollama.com" in text

    def test_existing_env_is_never_overwritten(self, tmp_path):
        """A host's real .env must not be regenerated or reset."""
        import run_famquiz

        env_path = tmp_path / ".env"
        env_path.write_text(
            "SECRET_KEY=my-hand-written-value\nOLLAMA_API_KEY=k\n",
            encoding="utf-8",
        )
        before = env_path.stat().st_mtime_ns
        created = run_famquiz.write_default_env(str(tmp_path))
        assert created is False
        assert "my-hand-written-value" in env_path.read_text(encoding="utf-8")
        assert env_path.stat().st_mtime_ns == before

    def test_creation_failure_should_not_break_the_boot(self, tmp_path, monkeypatch):
        """A locked folder means: start anyway, skip the banner."""

        def boom(*args, **kwargs):
            raise OSError("folder is locked")

        import run_famquiz

        monkeypatch.setattr("builtins.open", boom)
        assert run_famquiz.write_default_env(str(tmp_path)) is False


class TestFirstRunBanner:
    """main() greets a fresh folder, and only a fresh folder."""

    @staticmethod
    def _patch_server(monkeypatch, run_famquiz, tmp_path):
        """Make main() runnable without really serving."""
        calls = {}
        monkeypatch.setattr(run_famquiz, "base_dir", lambda: str(tmp_path))
        monkeypatch.setattr(
            run_famquiz, "prepare_env", lambda base: "sqlite:///:memory:"
        )

        import app as app_module

        monkeypatch.setattr(
            app_module.app, "run", lambda **kwargs: calls.update(kwargs)
        )
        monkeypatch.setattr(app_module, "_print_lan_urls", lambda port: None)
        return calls

    def test_banner_prints_first_run(self, tmp_path, monkeypatch, capsys):
        """Fresh folder: .env is created and the banner tells the host."""
        import run_famquiz

        self._patch_server(monkeypatch, run_famquiz, tmp_path)
        monkeypatch.setenv("PORT", "5003")
        assert not (tmp_path / ".env").exists()

        run_famquiz.main()

        out = capsys.readouterr().out
        assert (tmp_path / ".env").exists()
        assert "First-run setup" in out
        assert "http://127.0.0.1:5003/guide" in out

    def test_no_banner_when_env_exists(self, tmp_path, monkeypatch, capsys):
        """Second launch: no banner, nothing rewritten."""
        import run_famquiz

        (tmp_path / ".env").write_text("PORT=5000\n", encoding="utf-8")
        before = (tmp_path / ".env").read_text(encoding="utf-8")
        self._patch_server(monkeypatch, run_famquiz, tmp_path)

        run_famquiz.main()

        out = capsys.readouterr().out
        assert "First-run setup" not in out
        assert (tmp_path / ".env").read_text(encoding="utf-8") == before


class TestBootStatusLines:
    """The window must say what is configured before anybody plays."""

    def test_ready_lines(self, monkeypatch, capsys):
        """With keys present the window says READY, no warning."""
        import app as app_module

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setenv("MAIL_SERVER", "smtp.example.org")
        monkeypatch.setenv("MAIL_PASSWORD", "pw")
        monkeypatch.setenv("SECRET_KEY", "x" * 40)
        app_module._print_lan_urls(5000)
        out = capsys.readouterr().out
        assert "Quiz questions:  READY" in out
        assert "Password emails: READY" in out
        assert "WARNING" not in out

    def test_missing_quiz_key_points_at_the_guide(self, monkeypatch, capsys):
        """A missing quiz key prints READY-nothing and the fix pointer."""
        import app as app_module

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "")
        monkeypatch.setenv("MAIL_SERVER", "smtp.example.org")
        monkeypatch.setenv("MAIL_PASSWORD", "pw")
        monkeypatch.setenv("SECRET_KEY", "x" * 40)
        app_module._print_lan_urls(5000)
        out = capsys.readouterr().out
        assert "Quiz questions:  NOT READY" in out
        assert "/guide" in out
        assert "Password emails: READY" in out
        assert "WARNING" not in out

    def test_missing_mail_key_is_off_not_broken(self, monkeypatch, capsys):
        """Emails are optional: the window says off, not error."""
        import app as app_module

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.delenv("MAIL_SERVER", raising=False)
        monkeypatch.delenv("MAIL_PASSWORD", raising=False)
        monkeypatch.setenv("SECRET_KEY", "x" * 40)
        app_module._print_lan_urls(5000)
        out = capsys.readouterr().out
        assert "Quiz questions:  READY" in out
        assert "Password emails: off" in out
        assert "WARNING" not in out

    def test_default_secret_gets_a_warning(self, monkeypatch, capsys):
        """The known repo-secret value must never pass silently."""
        import app as app_module

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "k")
        monkeypatch.setenv("MAIL_SERVER", "s")
        monkeypatch.setenv("MAIL_PASSWORD", "p")
        monkeypatch.delenv("SECRET_KEY", raising=False)
        app_module._print_lan_urls(5000)
        out = capsys.readouterr().out
        assert "SECRET_KEY is the default value" in out


class TestSetupStatusOnPages:
    """/guide and / show the live setup flags."""

    def test_guide_status_card_not_ready(self, client, monkeypatch):
        """No keys at all: card says so, with next steps."""
        import app as app_module

        flask_app = client.application
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "")
        # BASE_CONFIG froze the developer's real MAIL_* at import, so a
        # missing-pair test must blank them on the app config itself.
        monkeypatch.setitem(flask_app.config, "MAIL_SERVER", "")
        monkeypatch.setitem(flask_app.config, "MAIL_PASSWORD", "")
        resp = client.get("/guide")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Setup status" in html
        assert "Quiz questions: not ready" in html
        assert "Password emails: off" in html
        assert "Players can still play" in html

    def test_guide_status_card_ready(self, client, monkeypatch):
        """Keys present: the card flips to ready."""
        import app as app_module

        flask_app = getattr(client, "application", None)
        assert flask_app is not None
        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setitem(flask_app.config, "MAIL_SERVER", "smtp.example.org")
        monkeypatch.setitem(flask_app.config, "MAIL_PASSWORD", "pw")
        resp = client.get("/guide")
        html = resp.get_data(as_text=True)
        assert "Quiz questions: ready" in html
        assert "Password emails: ready" in html

    def test_home_banner_when_quiz_unset(self, client):
        """Homepage warns while the quiz key is missing."""
        resp = client.get("/")
        html = resp.get_data(as_text=True)
        assert "Quiz questions are not set up yet." in html

    def test_home_banner_gone_when_ready(self, client, monkeypatch):
        """Homepage is clean once the quiz key exists."""
        import app as app_module

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        resp = client.get("/")
        html = resp.get_data(as_text=True)
        assert "Quiz questions are not set up yet." not in html

    def test_setup_sentences_ship_in_all_locales(self):
        """Every new setup string is translated in es/hi/zh_Hans."""
        import json

        catalog = json.loads(_read("translations.json"))
        for key in (
            "Setup status",
            "Quiz questions: ready — quizzes work.",
            "Quiz questions: not ready — quizzes start after the host adds the free quiz key.",
            "Password emails: ready — forgot-password works.",
            "Password emails: off — they are skipped until the host adds the free mail key. Players can still play.",
            "Quiz questions are not set up yet.",
            "You can still make an account and look around — quizzes start after the host adds the free quiz key. The host opens",
            "First-time setup: the host adds two free keys — quiz and mail. The game window says which are missing and prints the guide address.",
        ):
            for lang in ("es", "hi", "zh_Hans"):
                assert key in catalog[lang], (key, lang)
