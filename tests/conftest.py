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
