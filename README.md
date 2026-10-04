# FamQuiz

## Prerequisites

* Python 3.10 or above (with `pip` and `venv`)
* Git (to clone the repo)
* An Ollama API Key — free tier works (`OLLAMA_API_KEY` in `.env`)
* A Mailjet account (free tier covers a family app) with one verified
  sender address (`MAIL_USERNAME` = API Key, `MAIL_PASSWORD` = Secret Key).
  Any SMTP provider works via the `MAIL_*` variables — see `.env.example`.
* (Optional, for running tests) `pytest`, installed via `requirements.txt`

Quick start: `python -m venv .venv`, activate it,
`pip install -r requirements.txt`, copy `.env.example` to `.env` and fill
in the keys, then `python app.py`. Run `pytest tests/ -q` to verify.

## Password reset emails (Mailjet SMTP)

Copy `.env.example` to `.env` and set the `MAIL_*` values from your
Mailjet dashboard (API Key + Secret Key). Verify the sender address once
under Mailjet → Sender addresses — no domain purchase needed; that one
verified address can mail all users (free tier covers a family app).

Routes: `GET/POST /reset` (forgot), `GET/POST /reset/<token>`,
`GET/POST /change` (logged in). If `MAIL_SERVER`/`MAIL_PASSWORD` are
missing, emails are suppressed and a warning is logged instead of crashing.
`SECRET_KEY` must be set in production or reset tokens invalidate on restart.

## Languages (Client 1: English, Spanish, Hindi, Mandarin Simplified)

Full UI including quiz and mails. No extra dependency — `translations.json`
holds the `es`/`hi`/`zh_Hans` dictionaries (zero-dependency equivalent of the
Flask-User/Flask-Security-Too + Flask-Babel internationalisation in the
E-portfolio). `User.language` stores the full name; `get_locale()` in
`app.py` resolves per-email override > `?lang=` > session > user >
`Accept-Language` > `en`.

* Switch in Settings (persists + applies immediately via session) or
  `/?lang=es`, `/?lang=hi`, `/?lang=zh_Hans` for anonymous preview.
* Quiz questions use the same language (`build_quiz_messages()`), with an
  explicit `Use Simplified Chinese.` clause for Mandarin.
* Mails (reset instructions/notice, change notice) use per-recipient
  templates in `templates/security/email/` plus translated subjects via
  `TranslatedMailUtil` — verified in `tests/test_i18n.py::TestTranslatedMails`.
* JS strings come from `window.I18N` (injected per-page) and
  `GET /api/i18n/<locale>.json`.
* Add a string: add the English source to all three dicts in
  `translations.json` and use `{{ _('...') }}` in templates. Run
  `pytest tests/test_i18n.py -q` to verify.

## Project structure

* `app.py` — config, models, i18n helpers, quiz helpers, mail hooks, slim
  `create_app()` factory.
* `routes.py` — all view functions + `register_routes(app)` (endpoint names
  unchanged, so `url_for()` calls keep working).
* `translations.json` — UI + mail strings for `es`/`hi`/`zh_Hans`.

Note: `tests/test_live_mail.py` runs with the suite and sends one real
password-reset email to the verified sender address, then confirms via
Mailjet's API that it was delivered — so a green suite means the mailing
system actually works. Keep it; each run costs one email from the free quota.
