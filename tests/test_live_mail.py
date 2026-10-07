"""Live SMTP test — sends a REAL password-reset email to a real user.

Skipped automatically when MAIL_SERVER/MAIL_PASSWORD are missing;
runs live when creds are present (user approved credit spend).
Uses an isolated temp DB; the only real-world side effect is one email
to the verified sender address from .env (recipient = sender).
"""

import base64
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parseaddr

import pytest

MJ_MESSAGES_URL = "https://api.mailjet.com/v3/REST/message"
DELIVERED_STATUSES = {"sent", "opened", "clicked"}


def _sender_address(flask_app):
    """Return the sender address as the live-mail recipient.

    Recipient = sender, so the test tracks whatever .env configures.

    :param flask_app: The Flask app with mail config.
    :return: The sender email address.
    :rtype: str
    """
    _, address = parseaddr(flask_app.config.get("MAIL_DEFAULT_SENDER", ""))
    assert address and "@" in address, "MAIL_DEFAULT_SENDER not configured"
    return address


def _mailjet_status(api_key, secret, recipient, sent_after, timeout=120):
    """Poll Mailjet's Messages API until our message shows up.

    :param api_key: The Mailjet API key.
    :param secret: The Mailjet API secret.
    :param recipient: The recipient address to search for.
    :param sent_after: Only consider messages arriving after this time.
    :param timeout: Maximum seconds to poll.
    :return: Tuple (ok, detail); ok=True only if Mailjet reports a delivered status.
    :rtype: tuple
    """
    token = base64.b64encode(f"{api_key}:{secret}".encode()).decode()
    deadline = time.time() + timeout
    last_detail = "no messages returned yet"
    while time.time() < deadline:
        query = urllib.parse.urlencode({"To": recipient, "Limit": 5, "Sort": "ID DESC"})
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
        fresh = [m for m in messages if _arrived_at(m) and _arrived_at(m) >= sent_after]
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
    """Parse a Mailjet message ArrivedAt to UTC datetime.

    :param message: The message fixture.
    :return: Helper value for tests.
    :rtype: object
    """
    try:
        return datetime.fromisoformat(
            message.get("ArrivedAt", "").replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def test_forgot_password_sends_real_email_to_user(tmp_path):
    """Verify forgot password sends real email to user.

    :param tmp_path: The tmp_path fixture.
    """
    # Check both canonical and legacy dash-names (.env uses SMTP-SERVER etc).
    has_server = bool(os.getenv("MAIL_SERVER") or os.getenv("SMTP-SERVER"))
    has_pass = bool(os.getenv("MAIL_PASSWORD"))
    if not has_server or not has_pass:
        pytest.skip("MAIL_SERVER/MAIL_PASSWORD not configured; live mail skipped.")
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
