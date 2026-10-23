"""
Mail body smoke tests — no credits, no SMTP.

These assert the *content* of the security emails (plain text + HTML
parts, per-recipient language) without sending anything. They live in
their own module because the sibling live modules are marked
``pytest.mark.live`` and are deselected by default.
"""

from app import User, db, mail


def test_txt_html_smoke_no_spend(client, app, existing_user):
    """No-spend link: live delivery proves acceptance, this proves bodies."""
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
