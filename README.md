# FamQuiz – Play Together, Even on Screens

FamQuiz is a small family quiz game that runs on **one** family computer (we call it the **host**).
Everyone else joins from a phone or laptop, answers fun questions, and the fastest correct answers score more.
Top score wins. Power-ups appear sometimes. There is a leaderboard and stats.

> You do **not** need to know code. Follow the steps in order. Each step tells you what you should see.
> If something looks different, go to [If something goes wrong](#if-something-goes-wrong).

**What you need:**

* One host computer (Windows 10/11, Mac, or Linux) – about 10 MB free.
* Family phones/laptops.
* Same Wi-Fi **or** Tailscale (free, for far-away family – see Section 5 below).
* Two free keys: Ollama (makes questions) + Mailjet (sends password-reset mails). Both have free tiers.

**Pictures in this guide:** every step describes what you should see on your screen. Where addresses or keys are shown, yours will have your own values – never share photos of your keys.

---

## Words we will use

* **Terminal / PowerShell / Console** – a black window where you type one line and press Enter. It only does what you type. Nothing breaks by opening it.
* **Python** – a free helper the app needs. You install it once.
* **`.venv`** – the app’s private box. Keeps FamQuiz separate from other things.
* **`.env`** – a small secret note with your keys. Never share it or post a photo of it.
* **IP address** – a computer’s house number, like `192.168.1.20` at home or `100.87.45.12` on Tailscale. You always add `:5000` at the end for FamQuiz.
* **Host** – the one computer that runs `python app.py`. Others just open the link.

## 0. Open a terminal (do this first)

**Windows:**

1. Press Start, type `PowerShell`, open Windows PowerShell.
2. You should see a blue window with `PS C:\Users\...>` waiting.

**Mac:**

1. Press Cmd + Space, type `Terminal`, press Enter.
2. You should see your name and `$` waiting.

**Linux (Ubuntu):**

1. Press Ctrl + Alt + T.
2. You should see `$` waiting.

How to paste: Windows `Ctrl+V`, Mac `Cmd+V`, Linux `Ctrl+Shift+V`. Press Enter to run.

---

## 1. Install Python (once)

You need Python 3.10 or newer.

**Check first – type this and press Enter:**

```text
python --version
```

You should see `Python 3.10...` or `3.11`, `3.12`, `3.13`. If yes, skip to Section 2.

**If it says “not found”:**

* **Windows:** Go to `https://www.python.org/downloads/` → Download → Run installer → Tick **“Add python.exe to PATH”** (checkbox on the first page) → Install. Close and reopen PowerShell, try `python --version` again.
* **Mac:** Go to `https://www.python.org/downloads/` → Download pkg → Install. Or if you use Homebrew: `brew install python`. Try `python3 --version`. If only `python3` works, use `python3` everywhere below instead of `python`.
* **Linux:** Type `sudo apt update` Enter, then `sudo apt install python3 python3-venv -y` Enter. Try `python3 --version`.

You should see a version number. That is success.

## 2. Get the FamQuiz folder

1. Download the FamQuiz ZIP from GitHub → Unzip (double-click).
2. You should see a folder named `FamQuiz` with files like `app.py`, `.env.example`.
3. Move it somewhere easy, e.g. Documents.

No `git` needed for family play.

**Open terminal inside that folder:**

* Windows: open `FamQuiz` in File Explorer → click address bar → type `powershell` → Enter.
* Mac: right-click `FamQuiz` → New Terminal at Folder.
* Linux: right-click → Open in Terminal.

Type `dir` (Windows) or `ls` (Mac/Linux) Enter. You should see `app.py`.

## 3. Make the private box and install (copy-paste)

Type one line at a time, press Enter after each. Wait until it finishes.

**Windows:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Mac / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

You should see many lines installing, ending with no red error. If Windows blocks `Activate.ps1`, type `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` Enter, then try again.

Next, make your secret note:

* Windows: `copy .env.example .env`
* Mac/Linux: `cp .env.example .env`

You should now have a file named `.env`. Open it with Notepad (Win) / TextEdit (Mac) / Gedit (Linux). Do not share it. Your terminal should show the install finishing with no red error and `Running on http://127.0.0.1:5000` after `python app.py`.

---

## 4. Ollama – makes the questions (detailed, beginner)

**What:** Ollama cloud writes your quiz questions. The app needs **one** family key. The key stays on the host only, never on players’ phones.

**Steps – exact clicks:**

1. Go to `https://ollama.com` → **Sign in** (Google or GitHub is fine).
2. Click your face/icon → **API keys** → **New key** → Name it `FamQuiz` → **Create** → **Copy**.
   You see the key once. If you lose it, make a new one. On the API keys page you should see your `FamQuiz` key name with a Delete option next to it.
3. Open `.env` in Notepad/TextEdit. Find the line `OLLAMA_API_KEY=`.
4. Paste after `=`. It looks like `OLLAMA_API_KEY=abc123...`. Save and close. Your `.env` should show the pasted key on that line and `MAIL_*` lines below it.
5. Leave `OLLAMA_MODEL=gpt-oss:20b` as is. Free keys can use: `gemma4:31b, gpt-oss:120b, gpt-oss:20b, nemotron-3-nano:30b, nemotron-3-super, nemotron-3-ultra`. Do not change unless asked.
6. Restart the app (see Section 6). Start a game with 2 questions. If questions appear, it works.

**Safety:** Never post a photo of the key. If leaked, go back to Ollama → Delete → New key → paste again.

**If you skip this:** Quiz shows “not configured yet (missing OLLAMA_API_KEY)”. Everything else still opens.

**Cheap check (optional, spends 1–2 credits):**

```bash
pytest tests/test_ollama_live.py -q -k "20b"
```

You should see `passed`. Missing key = tests skip.

## 5. Tailscale – play with far-away family (detailed, beginner)

**What:** Same Wi-Fi = open host address directly. Far away = Tailscale makes a free private tunnel so far family looks like same room. No router changes. Host still runs with `0.0.0.0:5000`, debug off (safe).

**5A. Same Wi-Fi (try this first):**

1. On host, find home number:
   * Windows: type `ipconfig` Enter → look for `IPv4 Address ... 192.168.x.x`.
   * Mac/Linux: type `ifconfig` or `ip a` Enter → `192.168.x.x` or `10.x.x.x`.
2. Players open `http://192.168.x.x:5000` (use YOUR numbers, keep `:5000`).
3. Windows firewall: Allow on Private, keep Public blocked if asked. Your terminal should show an `IPv4 Address` like `192.168.x.x` – use your numbers with `:5000` at the end.

**5B. Far away – Tailscale step-by-step:**

1. Go to `https://tailscale.com` → **Get Started** → **Personal (free)** → Sign up. **Whole family must use the same login way** (e.g. all Google). If someone used a different account, Admin → Machines → Invite.
2. Install:
   * Windows 10/11: Download Windows → Run → Next → taskbar arrow → Tailscale icon → **Log in** → browser **Approve**.
   * Mac: App Store → Tailscale → Open → Log in. Or `brew install --cask tailscale`.
   * Linux: paste `curl -fsSL https://tailscale.com/install.sh | sh` Enter, then `sudo tailscale up` Enter → click printed login link.
   * iPhone/Android: Store → Tailscale → Log in → switch **Connected ON**.
3. Check: Admin → Machines shows all devices. Or type `tailscale status` Enter – you should see active. Note the host's `100.x` address for the next step.
4. Find host address: on host type `tailscale ip -4` Enter. You see `100.87.45.12` (yours differs). Optional easier name: Admin → DNS → MagicDNS ON → use `hostname.tailabcd.ts.net`.
5. Share **one** link in family chat: `http://100.87.45.12:5000` (keep `:5000`).
6. Play:
   1. Players tap link → FamQuiz → Sign up / Log in.
   2. Host homepage → pick No. of questions, Difficulty, Waiting time 10–300s → **Start game**.
   3. Everyone sees a blue banner “A family game is waiting — tap Join!” with a countdown like `Game starting in 04:32` → the game opens by itself at live.
   4. Answer fast = more points. Top wins. Do Not Disturb / reminders off = banner only, tap Join yourself.
7. Done: close tab. To fully leave: Tailscale → Disconnect / Exit, host press `Ctrl+C` in terminal.
   Safety: do not post the `100.x` link publicly. `tailscale logout` to leave tailnet.

## 6. Mailjet – password-reset mails (detailed, beginner)

**What:** Forgot/change password needs to send mail. Free tier covers a family. One verified sender can mail all. No domain to buy.

**Steps – exact clicks:**

1. Go to `https://www.mailjet.com` → Sign up (free).
2. Top menu → **Sender addresses** → **Add** → type YOUR email → **Add** → open inbox → click Verify → green check.
3. **API Key Management** → **API Key** (= `MAIL_USERNAME`) → eye icon → Copy. **Secret Key** (= `MAIL_PASSWORD`) → Copy. You should see both keys listed with your verified sender address.
4. Open `.env`. Fill:

```env
MAIL_SERVER=in-v3.mailjet.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USE_SSL=false
MAIL_USERNAME=paste-api-key-here
MAIL_PASSWORD=paste-secret-here
MAIL_DEFAULT_SENDER=FamQuiz <you@your-verified-email.com>
SECURITY_EMAIL_SENDER=FamQuiz <you@your-verified-email.com>
```

   Old names `SMTP-SERVER/SMTP-PORT/MAIL_SENDER` still work. Any SMTP (e.g. SendGrid single-sender) uses same pattern. Save, restart app.
5. Check: Log out → Forgot password → type email → you get mail in ~1 min. Check spam first.

**If skipped:** mails are suppressed + warning in terminal, app still runs.

**Cheap check (sends 1 real mail to sender):**

```bash
pytest tests/test_live_mail.py -q
```

You should see `passed` or `skipped` if keys missing.

## 7. Run + play every day

1. Terminal in `FamQuiz`, activate (Section 3), type `python app.py` Enter (or `python3 app.py`).
   You should see `Running on http://...:5000`, no red error. Keep window open.
2. Open `http://127.0.0.1:5000` on host. You should see a Welcome card with Email and Password boxes and a blue Log in button. Sign up → choose Game options → **Start game** → wait countdown → answer.
3. Others open LAN or Tailscale link from Sections 5A/5B. The in-app Guide page always shows your actual port number (from `.env` `PORT` or `flask run --port`), so follow it if yours isn't `5000`.
4. Settings: profile, theme (applies instantly), language English / Mandarin Chinese / Spanish / Hindi. Or `/?lang=es`, `/?lang=hi`, `/?lang=zh_Hans` preview.
5. Leaderboard shows best. Stats show games/wins/power-ups.
6. Erase = clear my scores (keep account). Delete = remove me + cancel my lobbies.

## 8. Languages

Full UI + quiz + mails in 4 languages. No extra install. `translations.json` holds `es/hi/zh_Hans`. Quiz uses your language + `Use Simplified Chinese.` for Mandarin. Add a string: add English to all three dicts + `{{ _('...') }}` in template, run `pytest tests/test_i18n.py -q`.

## 9. Tests + size

* Quick check (no cost): `pytest tests/ -q --ignore=tests/test_ollama_live.py --ignore=tests/test_live_mail.py` → `120 passed`.
* Live (spends credits/mail): two commands in Sections 4/6.
* Size: source ~9.6 MB (<2 GB / <1 GB installer). RAM ~100 MB – 64 MB ideal not met on Flask, noted for school report.

## If something goes wrong

Read `I see X → do Y`. Order matters.

1. **I see “not configured (missing OLLAMA_API_KEY)”** → Section 4 paste key → restart `python app.py`.
2. **Quiz fails 502 / unreadable** → Retry Start. Cloud flaky, app drops bad questions automatically.
3. **“Cooling down / Slow down” 429** → Wait 10s (quiz) / 5s (lobby). Cost guard, not broken.
4. **“Timer not started / Stale 409”** → Reload question, answer once, don’t double-click.
5. **“No live game / No active quiz” 404** → Start from homepage via same link (not localhost vs Tailscale mixed).
6. **Link won’t open (Tailscale)** → Tailscale OFF? Different accounts? Host `app.py` closed? Missing `:5000`? Try `tailscale status`, `ping 100.x`, `curl http://100.x:5000/guide`.
7. **No mail** → spam? Sender unverified? Wrong port/TLS? Check Section 6. Secret changed = old reset links stop – request new.
8. **Port in use** → `PORT=5001 python app.py` → open `:5001`.
9. **Secrets warning `supersecret...`** → make long random in `.env`: `SECRET_KEY=` + `SECURITY_PASSWORD_SALT=` (use password manager). Restart, logins reset – expected.
10. **CSRF / logout loop** → use same URL everywhere, allow cookies, don’t iframe the app.

Still stuck? Copy the terminal red lines (hide keys/IPs) and ask for help.

## Project structure (for curious)

* `app.py` – settings, users/scores DB (`site.db` local), languages, quiz + mail helpers, safe `create_app()` (`debug=False`, `0.0.0.0`, security headers, CSRF).
* `routes.py` – pages + `/api/quiz/*`, `/api/game/*`, lobby + countdown + auto-open.
* `templates/` + `static/` – light-blue theme, `game_notify.js` banner/poll.
* `translations.json` – `es/hi/zh_Hans`.
* `tests/` – 120 fast + live Ollama/Mailjet (skipped without keys).

Local only: `site.db` + `.env` stay on host. Restrict file sharing, use OS password + BitLocker/FileVault.

---

## 10. Advanced (for curious family + builders)

Simple words, deeper detail. Skip if basics work.

### 10.1 All settings in one place

Open `.env` in Notepad/TextEdit. Each line is `NAME=value`. Restart `python app.py` after saving.

```env
SECRET_KEY=long-random-note-keeps-logins-safe
SECURITY_PASSWORD_SALT=another-long-random-note
PORT=5000
MAIL_SERVER=in-v3.mailjet.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USE_SSL=false
MAIL_USERNAME=paste-api-key-here
MAIL_PASSWORD=paste-secret-here
MAIL_DEFAULT_SENDER=FamQuiz <you@verified.com>
SECURITY_EMAIL_SENDER=FamQuiz <you@verified.com>
OLLAMA_API_KEY=paste-ollama-key-here
OLLAMA_MODEL=gpt-oss:20b
OLLAMA_HOST=https://ollama.com
```

Old names `SMTP-SERVER`, `SMTP-PORT`, `MAIL_SENDER`, `MAIL-API-KEY` still work. Missing mail = suppressed + warning. Missing Ollama = quiz 503. Missing secrets = warning + logins reset on restart – make them long random with a password manager.

### 10.2 How scoring really works

Each correct answer gives:

```text
1000 + round(500 * (1 - elapsed_ms / limit_ms))
```

Fast = up to 1500, slow = 1000, wrong = 0. Timer starts when the question appears (`quiz_state`). Answering without loading = 409, no free points. Power-ups: Double ×2, 50:50 removes 2 wrong, Extra Time 30s → 45s, Hint shows first letter. They appear randomly about 1 in 3 questions when enabled. Win = your total beats everyone else’s best. Tie keeps the earlier champ on top. Your last score shows in the top bar, best ever on leaderboard.

Note: answers travel in the login cookie readable as text (base64) but tamper-proof with a strong `SECRET_KEY`. Don’t share your cookie; use a strong secret.

### 10.3 Lobby and auto-open

One shared lobby (`GameSession`): lobby 10–300s → live → ends after `num*30s + 120s`. App expires old lobbies automatically so ghosts don’t stick. Banner uses Server-Sent Events primary + 4-second poll fallback, `?once=1` for tests. Countdown is recomputed from `starts_at` every second. Do Not Disturb / reminders off = banner only, tap Join yourself. Dismiss is per game, so dismissing the lobby also dismisses its live phase. `Join` returns config so each player generates questions in their own language.

### 10.4 Security for the LAN host

Host runs `debug=False` on `0.0.0.0` – LAN + Tailscale can reach it, debugger RCE is off. Headers sent: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`. Cookies are `HttpOnly + SameSite=Lax`. JSON posts send `X-CSRFToken` (tests bypass with `WTF_CSRF_ENABLED=False`). Limits: 1 quiz per 10s per user, 1 lobby per 5s (tests exempt) – protects Ollama credits. No brute-force lockout, so use strong family passwords. After everyone joined, you may set `SECURITY_REGISTERABLE=False` to stop LAN strangers registering. Keep `site.db` + `.env` private.

### 10.5 Languages for builders

`translations.json` holds `es/hi/zh_Hans`. Order: per-mail override → `?lang=` → session → user setting → browser → `en`. Mails use per-recipient templates + translated subjects. JS uses `window.I18N` + `GET /api/i18n/<locale>.json`. Always use `{{ _('...')|tojson }}` in JS. Add a string: add English to all three dicts, use `{{ _('...') }}`, run `pytest tests/test_i18n.py -q`.

### 10.6 Models, mail, network tweaks

Ollama: `temperature 0.7`, strict JSON schema, single-line fence fix, `answer` text / `1.0` / `B` tolerated, duplicates dropped, truncated to asked `n`. Free models listed in Section 4. Mail: any SMTP works with `MAIL_*`. Network: prefer MagicDNS name over raw `100.x`, set static LAN IP on router for stable link, firewall allow Private only, `PORT=5001 python app.py` fixes clash.

### 10.7 Tests, size, peek at data

```bash
pytest tests/ -q --ignore=tests/test_ollama_live.py --ignore=tests/test_live_mail.py
```

You should see `120 passed`. Live commands are in Sections 4/6 and spend credits/mail. Source ~9.6 MB. Peek (host only):

```bash
sqlite3 instance/site.db "select email,best_score,total_wins from user;"
```

`instance/` and `.env` are git-ignored and never served.
