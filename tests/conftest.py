import pytest

from app import create_app, db, user_datastore


@pytest.fixture(autouse=True)
def env_isolation(monkeypatch, request):
    """Keep unit tests hermetic w.r.t. the developer's real ``.env``.

    ``app.py`` calls ``load_dotenv()`` at import time, so the machine's
    ``.env`` (which may hold a live ``OLLAMA_API_KEY`` and ``MAIL_PASSWORD``)
    lands in ``os.environ`` for the whole session. That makes unit tests
    depend on local secrets. This fixture removes the app-relevant keys so
    every non-live test runs against defaults.

    ``live``-marked tests are left alone: they are the ones that *need*
    the real credentials (and are deselected by default anyway).

    :param monkeypatch: The pytest monkeypatch fixture.
    :param request: The pytest request fixture.
    :return: None.
    :rtype: None
    """

    if request.node.get_closest_marker("live"):
        yield
        return

    for key in (
        "OLLAMA_API_KEY",
        "OLLAMA-API-KEY",
        "OLLAMA_MODEL",
        "OLLAMA_HOST",
        "MAIL_SERVER",
        "SMTP-SERVER",
        "MAIL_PORT",
        "SMTP-PORT",
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
    ):
        monkeypatch.delenv(key, raising=False)

    # ``app.OLLAMA_API_KEY`` is read from .env at *import* time, so clearing
    # os.environ above is not enough: blank the module constant too. Any
    # test that wants a key sets it explicitly (and stubs the client), so
    # no non-live test can ever reach the paid Ollama API by accident.
    import app as app_module

    monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "")
    yield


@pytest.fixture()
def app(tmp_path):
    """Create a fresh app with an isolated file-based SQLite DB.

    NOTE: the app context is NOT held open across the test. Holding it
    open would share Flask's ``g`` (incl. ``g._login_user`` and
    ``fs_authn_via``) between test-client requests, so session-based
    ``@auth_required`` endpoints (e.g. /change) would misbehave.
    Each request therefore gets a fresh context, like in production.

    :param tmp_path: The pytest temporary path fixture.
    :return: The configured Flask app for tests.
    :rtype: flask.Flask
    """

    db_file = tmp_path / "test.db"
    flask_app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_file}",
            "MAIL_SUPPRESS_SEND": True,
            "SECURITY_SEND_PASSWORD_RESET_EMAIL": True,
            "SECURITY_SEND_PASSWORD_RESET_NOTICE_EMAIL": True,
            "SECURITY_SEND_PASSWORD_CHANGE_EMAIL": True,
        }
    )

    with flask_app.app_context():
        db.create_all()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.drop_all()
    # Close the SQLite file: every create_app() makes its own engine, and
    # Windows keeps the handle open until the engine is disposed.
    try:
        with flask_app.app_context():
            db.engine.dispose()
    except Exception:
        pass


@pytest.fixture()
def client(app):
    """Return a test client bound to the isolated app.

    :param app: The Flask app fixture.
    :return: The Flask test client.
    :rtype: flask.testing.FlaskClient
    """
    return app.test_client()


@pytest.fixture()
def logged_client(client, existing_user):
    """Log in existing_user and return the authenticated client."""
    client.post(
        "/login",
        data={
            "email": existing_user["email"],
            "password": existing_user["password"],
        },
    )
    return client


@pytest.fixture()
def second_user(app):
    """Create a second user; return its email/password dict."""
    from flask_security.utils import hash_password

    email = "second@example.com"
    password = "x" * 12
    with app.app_context():
        user_datastore.create_user(email=email, password=hash_password(password))
        db.session.commit()
    return {"email": email, "password": password}


@pytest.fixture()
def fake_ollama(monkeypatch):
    """Install a canned Ollama client; factory(n) returns recorded calls.

    Usage: calls = fake_ollama(n=2); client.post("/api/quiz/generate", ...)
    """
    import json as _json
    from types import SimpleNamespace as _NS

    import app as app_module

    calls = []

    def _factory(n=2, content=None):
        body = content or _json.dumps(
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

        class _Fake:
            def chat(self, model="", messages=None, **kwargs):
                calls.append({"model": model, "messages": messages, **kwargs})
                return _NS(message=_NS(content=body))

        monkeypatch.setattr(app_module, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(app_module, "get_ollama_client", lambda: _Fake())
        return calls

    return _factory


@pytest.fixture()
def frozen_time(monkeypatch):
    """Freeze the wall clock; returns a setter for new values.

    The base is one hour in the *future* on purpose. ``routes.time`` is
    the stdlib ``time`` module, so the freeze is process-wide. Freezing
    into the past would make every session cookie signed during the test
    look expired (``itsdangerous`` rejects an age < 0) and silently log
    the user out on the next request.

    :param monkeypatch: The pytest monkeypatch fixture.
    :return: Dict with a mutable ``now`` key.
    :rtype: dict
    """

    import time as _time

    import routes as routes_module

    state = {"now": _time.time() + 3600.0}
    monkeypatch.setattr(routes_module.time, "time", lambda: state["now"])
    return state


@pytest.fixture()
def frozen_clock(monkeypatch):
    """Freeze the wall clock at a *future* offset and let tests advance it.

    ``routes.time`` is the stdlib ``time`` module, so patching it freezes
    ``time.time()`` process-wide. Freezing *backwards* invalidates the
    session cookie (``itsdangerous`` refuses an age < 0), which logs the
    user out mid-test. This fixture therefore starts one hour in the
    future and only ever moves forward.

    :param monkeypatch: The pytest monkeypatch fixture.
    :return: Dict with a mutable ``now`` key.
    :rtype: dict
    """

    import time as _time

    import routes as routes_module

    state = {"now": _time.time() + 3600.0}
    monkeypatch.setattr(routes_module.time, "time", lambda: state["now"])
    return state


@pytest.fixture()
def sse_driver(monkeypatch):
    """Drive the ``/api/game/events`` SSE generator deterministically.

    The generator polls every 2 seconds and calls ``_get_live_game()``
    twice per iteration (once for the snapshot, once for the expiry
    check). This fixture stubs the sleep away and lets a test script the
    sequence of games the generator will see.

    Usage::

        body = sse_driver(client, [game("lobby"), game("active"), None])

    :param monkeypatch: The pytest monkeypatch fixture.
    :return: Callable ``(client, script) -> str`` returning the raw body.
    :rtype: callable
    """

    import routes as routes_module

    def _drive(client, script):
        """
        Stream the SSE endpoint with a scripted game sequence.

        :param client: The Flask test client.
        :param script: Sequence of game objects (or None) the generator sees.
        :return: The raw SSE body.
        :rtype: str
        """

        iterator = iter(script)
        monkeypatch.setattr(
            routes_module, "_get_live_game", lambda: next(iterator, None)
        )
        monkeypatch.setattr(routes_module.time, "sleep", lambda _s: None)
        response = client.get("/api/game/events", buffered=False)
        chunks = []
        stream = response.response
        for _ in range(400):
            try:
                chunks.append(next(stream))
            except StopIteration:
                break
        return b"".join(chunks).decode("utf-8", "replace")

    return _drive


@pytest.fixture()
def multiple_live_games(app):
    """Temporarily allow several live games at once.

    The app enforces "one family-wide lobby" with a partial unique
    index, so a test cannot build two live rows by accident. A few tests
    deliberately exercise the sweeper against a mixed set of rows; they
    use this fixture to drop the index for the duration.
    """
    from sqlalchemy import text

    with app.app_context():
        db.session.execute(text("DROP INDEX IF EXISTS ix_game_session_single_live"))
        db.session.commit()
    yield
    with app.app_context():
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_game_session_single_live "
                "ON game_session ((1)) WHERE status IN ('lobby', 'active')"
            )
        )
        db.session.commit()


@pytest.fixture()
def fake_game():
    from types import SimpleNamespace

    def _factory(status="lobby", expires_at=4_000_000_000.0, game_id=1):
        """
        Return a GameSession-like object.

        :param status: The game status to report.
        :type status: str
        :param expires_at: Epoch seconds when the game expires.
        :type expires_at: float
        :param game_id: The fake game id.
        :type game_id: int
        :return: A GameSession-like namespace.
        :rtype: types.SimpleNamespace
        """

        return SimpleNamespace(
            id=game_id,
            status=status,
            starts_at=expires_at - 300.0,
            expires_at=expires_at,
            num_questions=4,
            difficulty="easy",
            powerups_enabled=True,
            lobby_seconds=60,
            created_by_id=1,
        )

    return _factory


@pytest.fixture()
def existing_user(app):
    """Create a pre-registered user via the datastore (bypasses the form).

    :param app: The Flask app fixture.
    :return: Dict with the user's email and password.
    :rtype: dict
    """
    from flask_security.utils import hash_password

    email = "player@example.com"
    password = "correct-horse-123"
    with app.app_context():
        user_datastore.create_user(email=email, password=hash_password(password))
        db.session.commit()
    return {"email": email, "password": password}
