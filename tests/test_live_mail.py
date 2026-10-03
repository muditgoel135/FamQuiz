"""Live SMTP test — sends a REAL password-reset email to a real user.

Runs with the normal suite (no gate): every run proves end-to-end
delivery through the configured provider. Uses an isolated temp DB;
the only real-world side effect is one email to the verified sender
address from .env (recipient = sender). Fails loudly if mail creds
are missing.
"""

import base64
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parseaddr

MJ_MESSAGES_URL = "https://api.mailjet.com/v3/REST/message"
DELIVERED_STATUSES = {"sent", "opened", "clicked"}


def _sender_address(flask_app):
    """Recipient = sender, so the test tracks whatever .env configures."""
    _, address = parseaddr(flask_app.config.get("MAIL_DEFAULT_SENDER", ""))
    assert address and "@" in address, "MAIL_DEFAULT_SENDER not configured"
    return address


def _mailjet_status(api_key, secret, recipient, sent_after, timeout=120):
    """Poll Mailjet's Messages API until our message shows up. Returns
    (ok, detail): ok=True only if Mailjet reports a delivered status."""
    token = base64.b64encode(f"{api_key}:{secret}".encode()).decode()
    deadline = time.time() + timeout
    last_detail = "no messages returned yet"
    while time.time() < deadline:
        query = urllib.parse.urlencode(
            {"To": recipient, "Limit": 5, "Sort": "ID DESC"}
        )
        req = urllib.request.Request(
            f"{MJ_MESSAGES_URL}?{query}",
            headers={"Authorization": f"Basic {token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                messages = json.load(resp).get("Data", [])
        except Exception as exc:  # network/API blip: keep polling
            last_detail = f"api error: {exc}"
            time.sleep(10)
            continue
        fresh = [
            m
            for m in messages
            if _arrived_at(m) and _arrived_at(m) >= sent_after
        ]
        if fresh:
            statuses = sorted({m.get("Status") for m in fresh})
            last_detail = f"statuses={statuses} count={len(fresh)}"
            if any(m.get("Status") in DELIVERED_STATUSES for m in fresh):
                return True, last_detail
        else:
            last_detail = f"{len(messages)} message(s) found, none newer than send"
        time.sleep(10)
    return False, last_detail


def _arrived_at(message):
    try:
        return datetime.fromisoformat(
            message.get("ArrivedAt", "").replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def test_forgot_password_sends_real_email_to_user(tmp_path):
    from app import create_app, db, user_datastore

    flask_app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'live.db'}",
            # Explicit overrides beat TESTING_CONFIG in create_app, so this
            # genuinely re-enables sending (Flask-Mail snapshots suppress
            # at init time; flipping config afterwards would NOT work).
            "MAIL_SUPPRESS_SEND": False,
        }
    )
    # Fail loudly if creds are absent.
    assert flask_app.config.get("MAIL_SERVER"), "MAIL_SERVER not configured"
    assert flask_app.config.get("MAIL_PASSWORD"), "MAIL_PASSWORD not configured"
    assert (
        flask_app.extensions["mail"].suppress is False
    ), "mail extension still suppressing sends"

    from flask_security.utils import hash_password

    recipient = _sender_address(flask_app)
    with flask_app.app_context():
        db.create_all()
        user_datastore.create_user(
            email=recipient, password=hash_password("live-mail-probe-123")
        )
        db.session.commit()

    client = flask_app.test_client()
    sent_after = datetime.now(timezone.utc)
    resp = client.post("/reset", data={"email": recipient})
    assert resp.status_code == 200

    # SMTP acceptance isn't delivery: confirm via Mailjet's API that the
    # message exists with a delivered status (else it bounced / went spam).
    ok, detail = _mailjet_status(
        flask_app.config.get("MAIL_USERNAME"),
        flask_app.config.get("MAIL_PASSWORD"),
        recipient,
        sent_after,
    )
    assert ok, f"Mailjet has no delivered message to {recipient}: {detail}"
