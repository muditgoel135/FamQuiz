"""Packaged entry point for FamQuiz.

Keeps ``.env`` and the scores database next to ``FamQuiz.exe`` (not in the
self-extracting temp folder, which is deleted on exit), so scores survive
a restart.

On the very first run there is no ``.env`` yet. :func:`write_default_env`
creates it next to the exe with the two placeholder keys and *fresh random
secrets*, then :func:`main` prints a plain first-run banner describing
exactly what is left before quiz questions work. The server always starts,
so the family can explore and create accounts while the host fetches keys.

The module body is side-effect free on import: everything happens inside
:func:`main`. That keeps ``import app`` *after* the database URI is set
(``app.BASE_CONFIG`` is frozen at import time) while letting the test
suite import this file without starting a server.
"""

import os
import secrets
import sys

# The first-run settings file. Plain language for a non-coder host: only
# two keys may stay empty (` OLLAMA_API_KEY` to make quiz questions, and
# the MAIL_ pair for forgot-password emails). Secrets are filled in with
# freshly generated random values at write time (not placeholders), so a
# handed-out exe never runs with a known default secret.
DEFAULT_ENV_TEMPLATE = """\
# FamQuiz settings file (.env) -- created automatically on first run.
#
# Still empty here:
#   1) OLLAMA_API_KEY -- makes quiz questions (free, needed for quizzes)
#   2) MAIL_PASSWORD (and MAIL_USERNAME) -- sends forgot-password
#      emails (free). Leave empty to skip emails; the game still runs.
#
# Add your key(s), save the file, then restart FamQuiz: close this
# window and open FamQuiz.exe again.
# The game window prints a guide web address (ends in /guide) that
# walks through both steps click by click.
# Lines starting with # are notes and are ignored by the game.

# --- Quiz questions (Ollama, free) --------------------------------------
OLLAMA_API_KEY=
OLLAMA_HOST=https://ollama.com
OLLAMA_MODEL=gpt-oss:20b

# --- Forgot-password emails (Mailjet, free, optional) -------------------
# If you skip these two keys, password-reset emails are not sent.
MAIL_SERVER=in-v3.mailjet.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USE_SSL=false
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_DEFAULT_SENDER=FamQuiz <you@your-verified-sender.com>
SECURITY_EMAIL_SENDER=FamQuiz <you@your-verified-sender.com>

# --- Door number --------------------------------------------------------
# Keep 5000. Change to 5001 only if starting the game says "Port in use".
PORT=5000
FLASK_RUN_HOST=0.0.0.0
FLASK_RUN_PORT=5000

# --- Do NOT edit below this line ----------------------------------------
# The two secret codes below were generated at random the first time
# FamQuiz ran. They keep everyone's accounts safe. Never share this file
# with anyone outside the family.
SECRET_KEY={SECRET_KEY}
SECURITY_PASSWORD_SALT={PASSWORD_SALT}
"""


def base_dir():
    """
    Return the folder that holds ``.env``, the database and the exe.

    :return: Absolute path of the base folder.
    :rtype: str
    """

    if getattr(sys, "frozen", False):
        # In a frozen exe, place .env + database next to FamQuiz.exe.
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def write_default_env(base):
    """
    Create ``.env`` from the bundled template when it does not exist.

    Called before ``load_dotenv`` so the fresh file (including its random
    secrets and ``PORT=5000``) is picked up on the very same launch.

    :param base: The base folder that holds .env and the instance folder.
    :type base: str
    :return: True when a fresh ``.env`` was created on this run.
    :rtype: bool
    """

    path = os.path.join(base, ".env")
    if os.path.exists(path):
        return False
    content = DEFAULT_ENV_TEMPLATE.replace(
        "{SECRET_KEY}", secrets.token_urlsafe(32)
    ).replace("{PASSWORD_SALT}", secrets.token_urlsafe(32))
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError:
        # Read-only folder and friends: still start the server; the host
        # can create .env by hand (the app then behaves as before).
        return False
    return True


def prepare_env(base):
    """
    Load ``.env`` and point the database at ``<base>/instance/site.db``.

    Must run *before* ``app`` is imported: ``app.BASE_CONFIG`` reads
    ``SQLALCHEMY_DATABASE_URI`` once, at import time.

    :param base: The base folder that holds .env and the instance folder.
    :type base: str
    :return: The database URI that was set.
    :rtype: str
    """

    from dotenv import load_dotenv

    load_dotenv(os.path.join(base, ".env"))

    instance = os.path.join(base, "instance")
    os.makedirs(instance, exist_ok=True)
    uri = "sqlite:///" + os.path.join(instance, "site.db").replace("\\", "/")
    os.environ["SQLALCHEMY_DATABASE_URI"] = uri
    return uri


def _print_first_run_banner(port):
    """
    Print plain first-run instructions for the host.

    Only shown when a fresh ``.env`` was just created. Everything here
    mirrors the in-app guide so the parent is never left guessing what
    to do next.

    :param port: The port the server will listen on.
    :type port: int
    """

    print()
    print("============================================================")
    print("  Welcome! First-run setup -- two small steps left:")
    print("  A settings file (.env) was created next to FamQuiz.exe.")
    print()
    print("    1. Quiz key -- makes quiz questions (Ollama, free)")
    print("    2. Mail key -- sends forgot-password emails (optional)")
    print()
    print("  Open this on the main computer and follow the steps:")
    print(f"    http://127.0.0.1:{port}/guide")
    print()
    print("  After saving the keys, close this window and open")
    print("  FamQuiz.exe again. Players can already create accounts --")
    print("  quiz questions appear once the quiz key is added.")
    print("============================================================")
    print()


def main():
    """
    Start the FamQuiz server (LAN-visible, never in debug mode).

    :return: None.
    :rtype: None
    """

    base = base_dir()
    first_run = write_default_env(base)
    prepare_env(base)

    import app as app_module

    port = int(os.getenv("PORT", 5000))
    if first_run:
        _print_first_run_banner(port)
    app_module._print_lan_urls(port)
    # Keep 0.0.0.0 for LAN + Tailscale sharing; never debug on LAN (RCE).
    app_module.app.run(debug=False, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
