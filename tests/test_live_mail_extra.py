"""Extended live SMTP tests — send REAL emails (quota spend).

Skipped automatically when MAIL_SERVER/MAIL_PASSWORD are missing.
Isolated temp DB; recipient == sender so no external spam.
Delivery confirmed via Mailjet Messages API (SMTP acceptance is not proof).
"""

import os
from datetime import datetime, timezone

import pytest

import test_live_mail as _live


def _needs_creds():
    has_server = bool(os.getenv("MAIL_SERVER") or os.getenv("SMTP-SERVER"))
    return not (has_server and os.getenv("MAIL_PASSWORD"))


needs_mail = pytest.mark.skipif(
    _needs_creds(), reason="MAIL_SERVER/MAIL_PASSWORD not configured."
)


def _live_app(tmp_path, name):
    from app import create_app, db

    flask_app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / name}",
            "MAIL_SUPPRESS_SEND": False,
        }
    )
    assert flask_app.config.get("MAIL_SERVER")
    assert flask_app.config.get("MAIL_PASSWORD")
    assert flask_app.extensions["mail"].suppress is False
    return flask_app


@needs_mail
def test_change_notice_live(tmp_path):
    from app import db, user_datastore
    from flask_security.utils import hash_password

    flask_app = _live_app(tmp_path, "change.db")
    recipient = _live._sender_address(flask_app)
    with flask_app.app_context():
        db.create_all()
        user_datastore.create_user(
            email=recipient, password=hash_password("live-mail-probe-123")
        )
        db.session.commit()
    client = flask_app.test_client()
    client.post(
        "/login", data={"email": recipient, "password": "live-mail-probe-123"}
    )
    sent_after = datetime.now(timezone.utc)
    resp = client.post(
        "/change",
        data={
            "password": "live-mail-probe-123",
            "new_password": "live-changed-456",
            "new_password_confirm": "live-changed-456",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    ok, detail = _live._mailjet_status(
        flask_app.config.get("MAIL_USERNAME"),
        flask_app.config.get("MAIL_PASSWORD"),
        recipient,
        sent_after,
    )
    assert ok, f"no delivered change notice to {recipient}: {detail}"


@needs_mail
def test_reset_notice_live(tmp_path):
    from flask_security.recoverable import generate_reset_password_token
    from app import User, db, user_datastore
    from flask_security.utils import hash_password

    flask_app = _live_app(tmp_path, "notice.db")
    recipient = _live._sender_address(flask_app)
    with flask_app.app_context():
        db.create_all()
        user_datastore.create_user(
            email=recipient, password=hash_password("live-mail-probe-123")
        )
        db.session.commit()
        user = User.query.filter_by(email=recipient).one()
        token = generate_reset_password_token(user)
    client = flask_app.test_client()
    sent_after = datetime.now(timezone.utc)
    resp = client.post(
        f"/reset/{token}",
        data={"password": "live-new-789", "password_confirm": "live-new-789"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    ok, detail = _live._mailjet_status(
        flask_app.config.get("MAIL_USERNAME"),
        flask_app.config.get("MAIL_PASSWORD"),
        recipient,
        sent_after,
    )
    assert ok, f"no delivered reset notice to {recipient}: {detail}"


@needs_mail
def test_forgot_spanish_live(tmp_path):
    from app import User, db, user_datastore
    from flask_security.utils import hash_password

    flask_app = _live_app(tmp_path, "es.db")
    recipient = _live._sender_address(flask_app)
    with flask_app.app_context():
        db.create_all()
        user_datastore.create_user(
            email=recipient, password=hash_password("live-mail-probe-123")
        )
        db.session.commit()
        user = User.query.filter_by(email=recipient).one()
        user.language = "Spanish"
        db.session.commit()
    client = flask_app.test_client()
    sent_after = datetime.now(timezone.utc)
    assert client.post("/reset", data={"email": recipient}).status_code == 200
    ok, detail = _live._mailjet_status(
        flask_app.config.get("MAIL_USERNAME"),
        flask_app.config.get("MAIL_PASSWORD"),
        recipient,
        sent_after,
    )
    assert ok, f"no delivered Spanish reset to {recipient}: {detail}"


def test_txt_html_smoke_no_spend(client, app, existing_user):
    """No-spend link: live delivery proves acceptance, this proves bodies."""
    from app import User, db, mail

    with app.app_context():
        user = User.query.filter_by(email=existing_user["email"]).one()
        user.language = "Spanish"
        db.session.commit()
    with mail.record_messages() as outbox:
        client.post("/reset", data={"email": existing_user["email"]})
    assert len(outbox) == 1
    assert outbox[0].body and outbox[0].html
    assert "Hola," in outbox[0].body
    assert "Hola," in outbox[0].html
