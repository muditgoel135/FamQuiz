"""Tests for the dependency and environment-variable contracts.

``requirements.txt`` and ``.env.example`` are the two files a helper
relies on to install and configure the app. Nothing checked them, so a
dependency could be dropped or an env var renamed without any test
noticing.
"""

import ast
import configparser
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_FILES = ("app.py", "routes.py", "run_famquiz.py")


def _read(name):
    """Read a repository file."""
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


def _requirements(name="requirements.txt"):
    """Return the pinned requirements as a dict."""
    parsed = {}
    for line in _read(name).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        if "==" in line:
            name, version = line.split("==", 1)
            parsed[name.strip()] = version.strip()
        else:
            parsed[line] = None
    return parsed


def _env_example():
    """Return the keys declared in .env.example (active or commented out)."""
    parser = configparser.ConfigParser()
    parser.optionxform = str  # keep the case of the variable names
    parser.read_string("[env]\n" + _read(".env.example"))
    active = {k for k in parser["env"] if k.isupper()}
    commented = set()
    for line in _read(".env.example").splitlines():
        line = line.strip()
        if line.startswith("#") and "=" in line:
            key = line.lstrip("#").split("=", 1)[0].strip()
            if key.isupper():
                commented.add(key)
    return active | commented


def _imports():
    """Return the top-level module names imported by the source files."""
    names = set()
    for rel in SOURCE_FILES:
        tree = ast.parse(_read(rel))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    names.add(node.module.split(".")[0])
    return names


# Standard-library modules that must never be listed as dependencies.
STDLIB = {
    "abc", "argparse", "ast", "base64", "collections", "configparser", "contextlib",
    "copy", "csv", "dataclasses", "datetime", "email", "functools", "glob", "hashlib",
    "http", "importlib", "inspect", "io", "itertools", "json", "logging", "mimetypes",
    "os", "pathlib", "platform", "random", "re", "shutil", "socket", "sqlite3",
    "stat", "string", "subprocess", "sys", "tempfile", "textwrap", "threading",
    "time", "types", "typing", "unicodedata", "unittest", "urllib", "uuid", "warnings",
    "webbrowser", "xml", "zipfile",
}

# The project's own modules.
LOCAL_MODULES = {"app", "routes", "run_famquiz"}


def _distribution_names():
    """Return the normalised distribution names from the requirements."""
    requirements = _requirements()
    names = set()
    for name in requirements:
        names.add(name.lower().replace("_", "-"))
        names.add(name.lower().replace("-", "_"))
    return names


def _module_matches_distribution(module, names):
    """Return True when the module maps onto a declared distribution."""
    normalised = module.lower().replace("_", "-")
    if normalised in names:
        return True
    # Flask-Security-Too is imported as ``flask_security``.
    if normalised == "flask-security" and "flask-security-too" in names:
        return True
    # python-dotenv is imported as ``dotenv``.
    if normalised == "dotenv" and "python-dotenv" in names:
        return True
    return False


class TestRequirements:
    """The dependency list must match the code."""

    def test_requirements_file_exists(self):
        """The install instructions point at this file."""
        assert os.path.exists(os.path.join(ROOT, "requirements.txt"))

    def test_every_version_is_pinned(self):
        """An unpinned dependency makes a build unreproducible."""
        for name, version in _requirements().items():
            assert version is not None, f"{name} is not pinned with =="

    def test_runtime_imports_are_declared(self):
        """A missing dependency breaks the install."""
        names = _distribution_names()
        missing = []
        for module in sorted(_imports()):
            if module in STDLIB or module in LOCAL_MODULES:
                continue
            if module.startswith("_"):
                continue
            if not _module_matches_distribution(module, names):
                missing.append(module)
        assert not missing, f"undeclared imports: {missing}"

    def test_pytest_is_not_a_runtime_dependency(self):
        """Test tooling belongs in the dev requirements."""
        assert "pytest" not in _requirements()

    def test_dev_requirements_declare_the_test_tooling(self):
        """The dev file must carry the test tools."""
        dev = _requirements("requirements-dev.txt")
        assert "pytest" in dev
        assert "pytest-cov" in dev
        assert "pytest-timeout" in dev

    def test_pyinstaller_is_declared_for_the_build(self):
        """The documented build needs PyInstaller.

        README §11 used to say ``pip install "pyinstaller>=6.15"``, an
        unpinned line that contradicted the pinned files.
        """
        dev = _requirements("requirements-dev.txt")
        assert "pyinstaller" in dev
        assert dev["pyinstaller"] is not None, "pyinstaller must be pinned"

    def test_ruff_is_declared(self):
        """The lint tool must be pinned like everything else."""
        dev = _requirements("requirements-dev.txt")
        assert "ruff" in dev
        assert dev["ruff"] is not None, "ruff must be pinned"

    def test_ci_uses_the_pinned_requirements(self):
        """The workflow must not hard-code a tool version."""
        import os

        workflow = os.path.join(ROOT, ".github", "workflows", "test.yml")
        if not os.path.exists(workflow):
            pytest.skip("no CI workflow in this checkout")
        with open(workflow, encoding="utf-8") as fh:
            source = fh.read()
        assert "requirements-dev.txt" in source
        assert "pip install ruff==" not in source

    def test_core_dependencies_are_present(self):
        """The app's own imports must be listed."""
        requirements = {name.lower() for name in _requirements()}
        for expected in ("flask", "flask-mail", "flask-security-too", "flask-sqlalchemy"):
            assert expected in requirements


class TestEnvExample:
    """``.env.example`` must document the real environment surface."""

    def test_example_file_exists(self):
        """The setup instructions copy this file."""
        assert os.path.exists(os.path.join(ROOT, ".env.example"))

    def test_canonical_env_vars_are_documented(self):
        """Every env var the code reads must be in the example."""
        source = _read("app.py") + _read("routes.py") + _read("run_famquiz.py")
        pattern = re.compile(r"_env(?:_bool|_port)?\(\s*\"([A-Z0-9_\-]+)\"")
        pattern2 = re.compile(r"os\.getenv\(\s*\"([A-Z0-9_\-]+)\"")
        canonical = set(pattern.findall(source)) | set(pattern2.findall(source))
        documented = _env_example()
        missing = {
            name
            for name in canonical
            if name not in documented
            and name not in ("SQLALCHEMY_DATABASE_URI",)
        }
        assert not missing, f"undocumented env vars: {sorted(missing)}"

    def test_legacy_aliases_are_documented(self):
        """The repo's own .env uses the dash-names, so the example must too."""
        source = _read("app.py")
        pattern = re.compile(r"_env(?:_bool|_port)?\(\s*\"[A-Z0-9_\-]+\"\s*,\s*\"([A-Z0-9\-]+)\"")
        aliases = set(pattern.findall(source))
        documented = _env_example()
        missing = {name for name in aliases if name not in documented}
        assert not missing, f"undocumented legacy aliases: {sorted(missing)}"

    def test_no_unknown_variables(self):
        """A variable the code never reads is a typo."""
        source = _read("app.py") + _read("routes.py") + _read("run_famquiz.py")
        # Every name that appears inside an _env*() call, whatever its
        # position, is a name the app reads.
        env_calls = re.findall(r"_env(?:_bool|_port)?\(([^)]*)\)", source)
        known = set()
        for call in env_calls:
            known.update(re.findall(r"\"([A-Z0-9_\-]+)\"", call))
        known.update(
            re.findall(r"os\.getenv\(\s*\"([A-Z0-9_\-]+)\"", source)
        )
        known |= {"SQLALCHEMY_DATABASE_URI", "SECRET_KEY", "SECURITY_PASSWORD_SALT"}
        # Flask CLI variables are read by Flask, not by the app.
        cli_only = {"FLASK_APP", "FLASK_RUN_HOST", "FLASK_RUN_PORT", "FLASK_DEBUG"}
        unknown = {
            name
            for name in _env_example()
            if name not in known and name not in cli_only
        }
        assert not unknown, f"unknown env vars: {sorted(unknown)}"

    def test_port_and_flask_run_port_agree(self):
        """Two different ports would confuse the helper."""
        parser = configparser.ConfigParser()
        parser.read_string("[env]\n" + _read(".env.example"))
        assert parser["env"]["PORT"] == parser["env"]["FLASK_RUN_PORT"]

    def test_the_secrets_are_placeholders(self):
        """The example must not ship a usable secret."""
        parser = configparser.ConfigParser()
        parser.read_string("[env]\n" + _read(".env.example"))
        for key in ("SECRET_KEY", "SECURITY_PASSWORD_SALT"):
            value = parser["env"][key]
            assert "change-me" in value, f"{key} must be a placeholder"
            assert len(value) > 20


class TestEnvWiring:
    """The environment must reach the configuration.

    ``BASE_CONFIG`` is evaluated once, at import time, so the only way
    to test the mapping is to re-import the module in a subprocess with
    a controlled environment.

    The subprocess runs outside the repository folder on purpose:
    ``app.py`` calls ``load_dotenv()`` at import time, which would
    otherwise pull the developer's real ``.env`` into the test and
    override the variable under test.
    """

    # Every variable the app reads; they are stripped from the
    # subprocess environment so the developer's .env cannot interfere.
    APP_ENV_VARS = (
        "OLLAMA_API_KEY",
        "OLLAMA-API-KEY",
        "OLLAMA_MODEL",
        "OLLAMA_HOST",
        "MAIL_SERVER",
        "SMTP-SERVER",
        "MAIL_PORT",
        "SMTP-PORT",
        "MAIL_USE_TLS",
        "MAIL_USE_SSL_TLS",
        "MAIL_USE_SSL",
        "MAIL_USERNAME",
        "MAIL-USERNAME",
        "MAIL-API-KEY",
        "MAIL_PASSWORD",
        "MAIL_DEFAULT_SENDER",
        "MAIL_SENDER",
        "FROM-EMAIL",
        "SECURITY_EMAIL_SENDER",
        "SECRET_KEY",
        "SECURITY_PASSWORD_SALT",
        "SQLALCHEMY_DATABASE_URI",
        "PORT",
    )

    def _clean_env(self, env):
        """Return a copy of the environment without the app variables."""
        cleaned = {k: v for k, v in os.environ.items() if k not in self.APP_ENV_VARS}
        cleaned.update(env)
        return cleaned

    def _base_config(self, env, tmp_path):
        """Return BASE_CONFIG from a fresh import with the given env."""
        code = (
            "import json, sys\n"
            f"sys.path.insert(0, {ROOT!r})\n"
            "import app\n"
            "cfg = dict(app.BASE_CONFIG)\n"
            "cfg.pop('SECRET_KEY', None)\n"
            "cfg.pop('SECURITY_PASSWORD_SALT', None)\n"
            "print(json.dumps(cfg))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(tmp_path),
            env=self._clean_env(env),
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        import json

        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_mail_port_is_read(self, tmp_path):
        """MAIL_PORT must reach the mail configuration."""
        config = self._base_config({"MAIL_PORT": "2525"}, tmp_path)
        assert config["MAIL_PORT"] == 2525

    def test_garbage_port_falls_back(self, tmp_path):
        """A broken port must not crash the boot."""
        config = self._base_config({"MAIL_PORT": "not-a-port"}, tmp_path)
        assert config["MAIL_PORT"] == 587

    def test_legacy_port_name_is_read(self, tmp_path):
        """The dash-name still works for old .env files."""
        config = self._base_config({"SMTP-PORT": "2526"}, tmp_path)
        assert config["MAIL_PORT"] == 2526

    def test_tls_flag_is_read(self, tmp_path):
        """MAIL_USE_TLS=false must be honoured."""
        config = self._base_config({"MAIL_USE_TLS": "false"}, tmp_path)
        assert config["MAIL_USE_TLS"] is False
        config = self._base_config({"MAIL_USE_TLS": "1"}, tmp_path)
        assert config["MAIL_USE_TLS"] is True

    def test_legacy_tls_alias_is_read(self, tmp_path):
        """MAIL_USE_SSL_TLS is the old name."""
        config = self._base_config({"MAIL_USE_SSL_TLS": "off"}, tmp_path)
        assert config["MAIL_USE_TLS"] is False

    def test_mail_server_is_read(self, tmp_path):
        """MAIL_SERVER must reach the configuration."""
        config = self._base_config({"MAIL_SERVER": "smtp.example.com"}, tmp_path)
        assert config["MAIL_SERVER"] == "smtp.example.com"

    def test_legacy_mail_server_is_read(self, tmp_path):
        """SMTP-SERVER is the old name."""
        config = self._base_config({"SMTP-SERVER": "smtp.legacy.com"}, tmp_path)
        assert config["MAIL_SERVER"] == "smtp.legacy.com"

    def test_username_falls_back_to_the_api_key(self, tmp_path):
        """The Mailjet key is read from MAIL_USERNAME or MAIL-API-KEY."""
        config = self._base_config({"MAIL-API-KEY": "legacy-key"}, tmp_path)
        assert config["MAIL_USERNAME"] == "legacy-key"

    def test_sender_falls_back_to_the_mail_sender(self, tmp_path):
        """SECURITY_EMAIL_SENDER inherits MAIL_DEFAULT_SENDER."""
        config = self._base_config({"MAIL_SENDER": "FamQuiz <a@b.com>"}, tmp_path)
        assert config["SECURITY_EMAIL_SENDER"] == "FamQuiz <a@b.com>"
        assert config["MAIL_DEFAULT_SENDER"] == "FamQuiz <a@b.com>"

    def test_database_uri_is_read(self, tmp_path):
        """The database location must be configurable."""
        config = self._base_config(
            {"SQLALCHEMY_DATABASE_URI": "sqlite:///x.db"}, tmp_path
        )
        assert config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///x.db"

    def test_secrets_are_read(self, tmp_path):
        """The secret and the salt must come from the environment."""
        code = (
            "import sys\n"
            f"sys.path.insert(0, {ROOT!r})\n"
            "import app\n"
            "print(app.BASE_CONFIG['SECRET_KEY'])\n"
            "print(app.BASE_CONFIG['SECURITY_PASSWORD_SALT'])\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(tmp_path),
            env=self._clean_env(
                {
                    "SECRET_KEY": "a-real-secret-value",
                    "SECURITY_PASSWORD_SALT": "a-real-salt-value",
                }
            ),
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        lines = result.stdout.strip().splitlines()
        assert "a-real-secret-value" in lines
        assert "a-real-salt-value" in lines

    def test_ollama_settings_are_read(self, tmp_path):
        """The model and the host must be configurable."""
        code = (
            "import sys\n"
            f"sys.path.insert(0, {ROOT!r})\n"
            "import app\n"
            "print(app.OLLAMA_MODEL)\n"
            "print(app.OLLAMA_HOST)\n"
            "print(bool(app.OLLAMA_API_KEY))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(tmp_path),
            env=self._clean_env(
                {
                    "OLLAMA_MODEL": "custom:model",
                    "OLLAMA_HOST": "https://example.test",
                    "OLLAMA-API-KEY": "legacy-key",
                }
            ),
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        lines = result.stdout.strip().splitlines()
        assert "custom:model" in lines
        assert "https://example.test" in lines
        assert "True" in lines
