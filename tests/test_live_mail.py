"""Live SMTP test — sends a REAL password-reset email to a real user.

Skipped by default so the normal suite never sends real mail or needs
real creds. Run explicitly with::

    $env:FAMQUIZ_LIVE_MAIL = "1"   # PowerShell
    pytest tests/test_live_mail.py -q

Uses an isolated temp DB; the only real-world side effect is one email
to the verified sender address below.
"""

import os
from email.utils import parseaddr

import pytest


def _sender_address(flask_app):
    """Recipient = sender, so the test tracks whatever .env configures."""
    _, address = parseaddr(flask_app.config.get("MAIL_DEFAULT_SENDER", ""))
    assert address and "@" in address, "MAIL_DEFAULT_SENDER not configured"
    return address

needs_live = pytest.mark.skipif(
    os.getenv("FAMQUIZ_LIVE_MAIL") != "1",
    reason="Set FAMQUIZ_LIVE_MAIL=1 to send a real test email",
)


@needs_live
def test_forgot_password_sends_real_email_to_user(tmp_path):
    from app import create_app, db, user_datastore

    flask_app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'live.db'}",
        }
    )
    # create_app suppresses sending when creds are missing; here we want
    # a REAL send, so re-enable it and fail loudly if creds are absent.
    assert flask_app.config.get("MAIL_SERVER"), "MAIL_SERVER not configured"
    assert flask_app.config.get("MAIL_PASSWORD"), "MAIL_PASSWORD not configured"
    flask_app.config["MAIL_SUPPRESS_SEND"] = False

    from flask_security.utils import hash_password

    recipient = _sender_address(flask_app)
    with flask_app.app_context():
        db.create_all()
        user_datastore.create_user(
            email=recipient, password=hash_password("live-mail-probe-123")
        )
        db.session.commit()

    client = flask_app.test_client()
    resp = client.post("/reset", data={"email": recipient})
    assert resp.status_code == 200
