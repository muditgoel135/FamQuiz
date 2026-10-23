"""Tests for the packaging entry point and the PyInstaller spec.

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
        monkeypatch.setattr(run_famquiz, "prepare_env", lambda base: "sqlite:///:memory:")

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
        monkeypatch.setattr(run_famquiz, "prepare_env", lambda base: "sqlite:///:memory:")

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
