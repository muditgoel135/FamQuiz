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
