"""Tests for the pytest configuration itself (pytest.ini, markers).

These guard the plumbing that keeps the suite honest: the declared
markers must actually be used, the live-credit tests must never run by
default, and the repo root must be importable from the ``pytest``
console script.
"""

import configparser
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(ROOT, "tests")

# Markers pytest itself provides; they never need declaring in pytest.ini.
BUILTIN_MARKERS = frozenset(
    {
        "filterwarnings",
        "parametrize",
        "skip",
        "skipif",
        "tryfirst",
        "trylast",
        "usefixtures",
        "xfail",
    }
)


def _ini():
    """
    Return the parsed pytest.ini.

    ``getini()`` cannot be used for most of these: pytest *consumes* the
    ``pythonpath``/``addopts`` values at startup and rewrites them, so the
    ini file is the only honest source of truth.

    :return: The parsed configuration.
    :rtype: configparser.ConfigParser
    """

    parser = configparser.ConfigParser()
    parser.read(os.path.join(ROOT, "pytest.ini"), encoding="utf-8")
    return parser


def _declared_markers():
    """
    Return the marker names declared in pytest.ini.

    :return: Set of declared marker names.
    :rtype: set
    """

    raw = _ini().get("pytest", "markers", fallback="")
    names = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.add(line.split(":", 1)[0].strip())
    return names


def _markers_used_in_tests():
    """
    Return every non-builtin ``pytest.mark.<name>`` used in the suite.

    The scan is AST-based so markers mentioned in docstrings or comments
    do not count as usage.

    :return: Set of marker names used in tests/.
    :rtype: set
    """

    used = set()
    for name in sorted(os.listdir(TESTS_DIR)):
        if not name.startswith("test_") or not name.endswith(".py"):
            continue
        path = os.path.join(TESTS_DIR, name)
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        used.update(_applied_markers(source))
    return used - BUILTIN_MARKERS


def _applied_markers(source):
    """
    Return the marker names actually *applied* in a Python source string.

    Uses the AST so docstrings and comments are ignored.

    :param source: The Python source to scan.
    :type source: str
    :return: Set of applied marker names.
    :rtype: set
    """

    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover - defensive
        return set()

    found = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "mark"
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "pytest"
        ):
            found.add(node.attr)
    return found


def _run_collect(*args):
    """
    Collect the suite in a subprocess and return the output.

    :param args: Extra pytest arguments.
    :return: The combined stdout/stderr of the collection run.
    :rtype: str
    """

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    return result.stdout + result.stderr


class TestPytestIni:
    """The ini file must configure the suite correctly."""

    def test_pythonpath_puts_repo_root_on_sys_path(self):
        """The console script must be able to ``import app``."""
        assert _ini().get("pytest", "pythonpath", fallback="").strip() == "."

    def test_repo_root_is_importable(self):
        """``import app`` must work from a plain ``pytest`` invocation."""
        assert "app" in sys.modules or _importable("app")

    def test_testpaths_points_at_tests(self):
        """A bare ``pytest`` must not wander into build/ or .venv/."""
        assert _ini().get("pytest", "testpaths", fallback="").strip() == "tests"

    def test_strict_markers_is_enabled(self):
        """A typo'd marker must fail loudly instead of silently doing nothing."""
        assert "--strict-markers" in _ini().get("pytest", "addopts", fallback="")

    def test_live_tests_are_deselected_by_default(self):
        """A plain ``pytest`` must never spend Ollama/SMTP credits."""
        assert '"not live"' in _ini().get("pytest", "addopts", fallback="")

    def test_norecursedirs_excludes_build_artifacts(self):
        """A PyInstaller build tree must not be collected."""
        raw = _ini().get("pytest", "norecursedirs", fallback="")
        excluded = {part for part in re.split(r"[,\s]+", raw) if part}
        for name in ("build", "dist", ".venv", "instance"):
            assert name in excluded

    def test_timeout_is_configured(self):
        """A hanging SSE test must not block a run forever."""
        assert _ini().get("pytest", "timeout", fallback="").strip() == "120"

    def test_ini_has_no_duplicate_keys(self):
        """A duplicated ini key silently uses the last value."""
        text = _ini()
        for section in text.sections():
            keys = [k for k, _ in text.items(section)]
            assert len(keys) == len(set(keys))

    def test_both_marker_names_are_declared(self):
        """The two suite-level markers must exist."""
        assert {"live", "slow"} <= _declared_markers()


def _importable(name):
    """
    Return True when the module can be imported from the repo root.

    :param name: The module name.
    :type name: str
    :return: Whether the import succeeded.
    :rtype: bool
    """

    import importlib.util

    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


class TestMarkers:
    """Declared markers must be used, and used markers must be declared."""

    def test_every_declared_marker_is_used(self):
        """A declared-but-unused marker means the suite drifted."""
        declared = _declared_markers()
        used = _markers_used_in_tests()
        assert declared <= used, f"unused markers: {sorted(declared - used)}"

    def test_every_used_marker_is_declared(self):
        """``--strict-markers`` would fail, but fail earlier and clearer."""
        declared = _declared_markers()
        used = _markers_used_in_tests()
        assert used <= declared, f"undeclared markers: {sorted(used - declared)}"

    def test_live_marker_covers_every_credit_spending_module(self):
        """The four live modules must all be marked ``live``."""
        live_modules = (
            "test_ollama_live.py",
            "test_ollama_live_extra.py",
            "test_live_mail.py",
            "test_live_mail_extra.py",
        )
        for name in live_modules:
            path = os.path.join(TESTS_DIR, name)
            assert os.path.exists(path), f"{name} is missing"
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            assert "pytest.mark.live" in source, f"{name} is not marked live"

    def test_no_spend_mail_test_is_not_marked_live(self):
        """The body smoke test must stay in the default (free) run."""
        path = os.path.join(TESTS_DIR, "test_mail_bodies.py")
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        assert "live" not in _applied_markers(source)
        assert "test_txt_html_smoke_no_spend" in source


@pytest.mark.slow
class TestLiveSelection:
    """The ``-m live`` selection must be the inverse of the default run."""

    def test_live_selection_picks_up_the_live_modules(self):
        """``-m live`` must select the credit-spending tests."""
        output = _run_collect("-m", "live")
        assert "test_ollama_live.py::" in output
        assert "test_live_mail_extra.py::" in output

    def test_default_selection_excludes_the_live_modules(self):
        """A plain run must never touch the providers."""
        output = _run_collect()
        assert "test_ollama_live.py::" not in output
        assert "test_live_mail.py::" not in output
