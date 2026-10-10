import pytest

from app import create_app, db, user_datastore


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
    """Freeze routes.time.time at FIXED; returns a setter for new values."""
    import routes as routes_module

    state = {"now": 1700000000.0}
    monkeypatch.setattr(
        routes_module.time, "time", lambda: state["now"]
    )
    return state


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
