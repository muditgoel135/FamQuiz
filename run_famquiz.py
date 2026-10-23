"""Packaged entry point for FamQuiz.

Keeps ``.env`` and the scores database next to ``FamQuiz.exe`` (not in the
self-extracting temp folder, which is deleted on exit), so scores survive
a restart.

The module body is side-effect free on import: everything happens inside
:func:`main`. That keeps ``import app`` *after* the database URI is set
(``app.BASE_CONFIG`` is frozen at import time) while letting the test
suite import this file without starting a server.
"""

import os
import sys


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


def main():
    """
    Start the FamQuiz server (LAN-visible, never in debug mode).

    :return: None.
    :rtype: None
    """

    prepare_env(base_dir())

    import app as app_module

    port = int(os.getenv("PORT", 5000))
    app_module._print_lan_urls(port)
    # Keep 0.0.0.0 for LAN + Tailscale sharing; never debug on LAN (RCE).
    app_module.app.run(debug=False, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
