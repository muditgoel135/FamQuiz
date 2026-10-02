import pytest

from app import create_app, db, user_datastore


@pytest.fixture()
def app(tmp_path):
    """Create a fresh app with an isolated file-based SQLite DB."""

    db_file = tmp_path / "test.db"
    flask_app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_file}",
        }
    )

    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    """Test client bound to the isolated app."""
    return app.test_client()


@pytest.fixture()
def existing_user(app):
    """A pre-registered user created via the datastore (bypasses the form)."""
    from flask_security.utils import hash_password

    email = "player@example.com"
    password = "correct-horse-123"
    with app.app_context():
        user_datastore.create_user(email=email, password=hash_password(password))
        db.session.commit()
    return {"email": email, "password": password}
