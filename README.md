# FamQuiz – Play Together, Even on Screens

FamQuiz is a family quiz game. Pick **one computer to run the game** (we call it the **main computer**). That computer must stay on and awake while you play. Everyone else plays in a web browser on a phone or laptop — nothing to install.

Fast correct answers get more points. During the game you may get bonus helpers (for example: double points, remove 2 wrong answers, extra time, or a hint showing the first letter). The highest total wins. You can see best-ever scores on the Leaderboard page and your own games/wins/bonuses on the Stats page.

> You do **not** need to know code. Follow the steps in order. Each step tells you what you should see.
> If something looks different, go to [If something goes wrong](#if-something-goes-wrong).

**What you need before you start (about 20–30 minutes):**

* One main computer to run the game (any recent Windows 10/11 or Mac; Linux also works). It stays on while playing. You need about 10 MB free space and an admin password for it.
* Family phones/laptops with a browser (Chrome, Safari, or Edge). Players do not install anything, but each player creates an account with an email + password inside the game.
* Everyone in the same house: connect all devices to the same home Wi-Fi name (watch out: guest Wi-Fi, extenders, or phone hotspots often count as a *different* network).
* Someone far away: you will install a free app called Tailscale so far-away phones act like they are in the same house — see Section 5.
* An email inbox you can open (for sign-ups and password resets). You will create 2 free website accounts — Ollama (writes quiz questions) and Mailjet (sends “forgot password” emails) — and copy 2 long secret passwords into setup once. No credit card needed.
* Internet on the main computer for setup (install takes 2–5 minutes).

**About examples in this guide:** every step describes what you should see on your screen. Example numbers like `192.168.1.20` or `100.87.45.12` and example keys are *not* yours — never type the example literally, always use your own numbers. Never share photos of your secret passwords — anyone with the photo can spend your free allowance or read your mail account.

---

## Words we will use

* **Main computer (host)** – the one computer that runs the game. Everyone else just opens a web address on a phone/laptop.
* **Instruction window (called PowerShell on Windows, Terminal on Mac/Linux)** – a window where you type one instruction line at a time, then press the big Enter key to run it. Just opening it changes nothing. Leave it open while you play — closing it stops the game for everyone.
* **Private settings file (.env)** – a text file inside the `FamQuiz` folder on the main computer that holds your secret passwords. Never share or photograph it. It starts with a dot, so it may be hidden in File Explorer/Finder — it is still there.

You will see two more ideas later, only when you need them: **IP address** (the main computer’s house number — see Section 5) and **`:5000`** (the door number for FamQuiz — always keep it at the end of the link).

## 0. Open an instruction window (do this first, leave it open)

**Windows:**

1. Press the Windows key, type `PowerShell`, click Windows PowerShell.
2. You should see a window with a line ending in `>` waiting for typing.

**Mac:**

1. Hold `Cmd` (⌘) + press `Space`, type `Terminal`, press Enter, click the `Terminal` app.
2. You should see your name and a prompt waiting for typing.

**Linux (Ubuntu):**

1. Press Ctrl + Alt + T.
2. You should see a prompt waiting for typing.

To use a line from this guide: copy it, click *inside* the window, paste (Windows `Ctrl+V`, Mac `Cmd+V`, Linux `Ctrl+Shift+V` or right-click → Paste), then press **Enter** to run. It means: click inside, paste/type exactly, press Enter, wait until it finishes.

If search shows nothing or two PowerShells, pick **Windows PowerShell** (not ISE). If you get lost, stop here — you only need this window open for the next steps.

---

## 1. Install Python (once, ~5 minutes)

FamQuiz needs a free helper called Python. You only install it once.

**Check first — type this exactly and press Enter:**

```text
python --version
```

Good: you see `Python 3.10.x` or higher (first number 10, 11, 12, or 13 — for example `Python 3.12.3`). Skip to Section 2.

Not good: you see an error, nothing happens, a Microsoft Store page opens, or the number starts with 2, 7, 8, or 9 (for example `Python 3.9`). Follow below for your computer. The Store opening means Python is *not* installed — install from python.org instead.

**If you need to install:**

* **Windows:** Open `https://www.python.org/downloads/` → click the yellow Download button → open the downloaded file → on the **very first page** tick the small box at the bottom that says **Add to PATH** → Install. If you missed that box, run the installer again → Modify → tick it. Close the instruction window and open a new one, try `python --version` again.
* **Mac:** Open `https://www.python.org/downloads/` → Download → open the downloaded file and click through. Then try `python3 --version`. Tip: on Macs always type `python3` (with a 3) everywhere below instead of `python`.
* **Linux (Ubuntu):** Type `sudo apt update`, press Enter (type your computer password when asked — you won’t see it while typing, that is normal), then `sudo apt install python3 python3-venv -y`, press Enter. Try `python3 --version`.

Success = you see a version number starting with 10 or higher.

## 2. Get the FamQuiz folder

1. Download: open the GitHub page for FamQuiz → click the green **Code** button → **Download ZIP**.
2. Open your Downloads folder → double-click the ZIP to open it → drag the `FamQuiz` folder inside to Documents (easy to find). Note: unzipping often creates `FamQuiz-main` inside — open it and use the inner folder that contains `app.py`.
3. You should see a folder named `FamQuiz` with files like `app.py`. On Windows/Mac file endings like `.py` or dot-files like `.env.example` may be hidden — that is normal.

**Open the instruction window inside that folder:**

* Windows: open the `FamQuiz` folder in File Explorer → click the top address bar → type `powershell` → Enter.
* Mac: open Terminal, type `cd ` (with a space), drag the `FamQuiz` folder into the window, press Enter. Or enable right-click → New Terminal at Folder.
* Linux: right-click inside the folder → Open in Terminal.

Check: type `ls` and press Enter (`ls` works on Windows too). You should see `app.py` in the list. If not, you are in the wrong folder — go one level in/out and try again.

## 3. Make FamQuiz its own private helper folder (once, copy-paste)

This keeps FamQuiz’s parts separate from other programs. Make sure your instruction window is open *inside* the `FamQuiz` folder (Section 2 check shows `app.py`).

Type one line at a time, press Enter after each. Wait until it finishes. Needs Wi-Fi, takes a few minutes.

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

What you should see:

* After line 1: no message, just a new prompt (it created a `.venv` folder).
* After line 2: `(.venv)` appears at the start of the line. That means it worked. You must repeat this line every time you close and reopen the window.
* After line 3: many lines saying `Collecting...` / `Successfully installed...`. Wait until the prompt returns. Yellow warnings are okay; red `ERROR: No such file` means you are in the wrong folder.

If line 2 on Windows is red about “scripts are disabled on this system”: that is just Windows being cautious. This is safe, one-time, no admin needed. Copy-paste this line, press Enter, type `Y` if it asks, then try line 2 again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Next, make your private settings copy (don’t fill it yet — that is Sections 4 and 6):

* Windows: `copy .env.example .env`
* Mac/Linux: `cp .env.example .env`

Check: `ls -a` (or `dir` on Windows) should show both `.env.example` (template — never edit) and `.env` (your copy — you will fill in Sections 4 and 6). If you can’t see `.env` in Explorer/Finder, it is hidden because it starts with a dot — it is still there.

Open `.env` only with a plain-text editor: Notepad on Windows, and on Mac use TextEdit → Format → Make Plain Text first (rich text breaks the file). On Linux use Text Editor/Gedit. Never let it save as `.env.txt` — turn off “hide extensions” if unsure. Do not share this file.

---

## 4. Let Ollama write questions for you (only the main computer does this, ~5 minutes)

**What:** Ollama is a website that writes quiz questions. You make one secret password (called a key) and paste it into your quiz files. Players skip this — only the person running the main computer does it. This is free, no credit card.

**Steps – exact clicks:**

1. Go to `https://ollama.com` → **Sign in** (Sign in with Google or GitHub is fine).
2. Click your face/icon → **API keys** → **New key** → Name it `FamQuiz` → **Create** → **Copy**. Keep that browser tab open until Step 4 is done — you see the key only once (a long mix of letters/numbers, 40+ characters). If you lose it, make a new one. On the API keys page you should see your `FamQuiz` key name with a Delete option next to it.
3. In your `FamQuiz` folder, open the file named `.env` (your copy from Section 3) in Notepad/TextEdit. Find the line `OLLAMA_API_KEY=` with nothing after `=`.
4. Click right after `=`, Paste, Save and close. Good = `OLLAMA_API_KEY=` followed immediately by the long code on one line, no spaces, no quotes, no line break. Bad = extra space or the file saved as `.env.txt`. Your `.env` already has mail lines *above* this line — that is normal, leave them for Section 6.
5. You won’t see a line starting `OLLAMA_MODEL` — that is normal, it is commented out in the template. Leave it. The app already uses the free default. Ignore model names like `gpt-oss:20b` unless a helper tells you to change it.
6. Restart the app so it reads the key: in the black window press `Ctrl+C` to stop, then run `python app.py` again (or `python3 app.py` on Mac). In the browser start a new game with Number of Questions = 2. If 2 questions appear, it works.

**Safety:** Treat the key like a bank password. Don’t send it in WhatsApp/email/screenshots — strangers can spend your free allowance. If you shared it: Ollama site → API keys → Delete `FamQuiz` → New key → paste the new one into `.env` → restart.

**If you skip this:** starting a quiz shows “Quiz questions aren’t turned on yet.” Everything else still opens.

> For helpers only — optional check (uses 1–2 free credits): with `(.venv)` active run `pytest tests/test_ollama_live.py -q -k "20b"`. `passed` = works, `skipped` = no key found so the test did nothing, `failed` = copy-paste error.

## 5. Play with far-away family with Tailscale (detailed, beginner)

**What:** In the same house, open the main computer’s address directly. Far away, everyone installs the free Tailscale app so far-away phones act like they are in the same house. No router changes. One person (the host) keeps the game running on their laptop the whole time.

**5A. Same Wi-Fi (try this first) — host only does step 1:**

1. On the main computer, find its home number:
   * Windows: type `ipconfig` Enter → look under Wi-Fi for `IPv4 Address ... 192.168.x.x` (pick Wi-Fi, not Ethernet/virtual).
   * Mac/Linux: type `ip a` Enter → look for `192.168.x.x` or `10.x.x.x` on Wi-Fi.
   Write it down. You should see an `IPv4 Address` like `192.168.1.23` — yours will differ.
2. Players: in the phone/laptop browser type `http://YOUR-numbers:5000` — for example if the host saw `192.168.1.23`, type `http://192.168.1.23:5000`. Keep `:5000` at the end (that is FamQuiz’s door number). Do NOT copy `192.168.x.x` literally. Use `http://`, not `https://`.
3. Windows firewall: if asked, tick **Private**, untick Public → Allow. Keep Public blocked.

**5B. Far away – Tailscale step-by-step (everyone does this, same account):**

1. Everyone: go to `https://tailscale.com` → **Get Started** → **Personal (free)** → Sign up. **Whole family must use the same login way** (for example all tap Continue with Google). If someone used a different email, the host goes to the Admin Console (`login.tailscale.com/admin/machines`) → Invite them.
2. Install and log in (host + every player, phones too):
   * Windows 10/11: Download Windows → Run → Next → click `^` in the taskbar → Tailscale icon → **Log in** → click **Approve** in the browser.
   * Mac: App Store → Tailscale → Open → Log in.
   * iPhone/Android: Store → Tailscale → Log in → switch **Connected ON**. Leave it ON during the game, open the link in Safari/Chrome.
   * Linux (helpers): paste `curl -fsSL https://tailscale.com/install.sh | sh` Enter, then `sudo tailscale up` Enter → click the printed login link.
3. Check: host opens Admin → Machines and sees all devices green, or types `tailscale status` Enter and sees devices active.
4. Find the host’s Tailscale number — host only: type `tailscale ip -4` Enter. You see something like `100.87.45.12` (yours differs — do not copy the example). Optional easier name: Admin → DNS → turn MagicDNS ON → use a name like `hostname.tailabcd.ts.net` instead of numbers.
5. Share **one** link in the family chat: `http://YOUR-number:5000` (for example `http://100.99.1.5:5000`, keep `:5000`). Only share in family chat, not publicly.
6. Play:
   1. Players tap the link → FamQuiz → Sign up / Log in.
   2. Host on the homepage → pick No. of questions, Difficulty, Waiting time 10–300 seconds → **Start game**.
   3. Everyone sees a blue banner “A family game is waiting — tap Join!” with a countdown like `Game starting in 04:32` → the game opens by itself when live. Answer fast = more points. Top total wins.
   4. Phone tip: turn Do Not Disturb off, or if reminders are off you will only see the in-app banner — tap Join yourself, it won’t auto-jump.
7. Done: players close the tab. Host: press `Ctrl+C` in the instruction window to stop the game. In the Tailscale app: Disconnect. To fully leave the family network later use `tailscale logout` — otherwise just Disconnect.

## 6. Turn on password-reset emails with Mailjet (optional, ~10 minutes — skip if you want)

**You can skip this.** Login and quiz still work — only Forgot Password won’t send mail. If you skip, you will just see a yellow warning in the instruction window when someone clicks Forgot Password, and the app still runs.

**What:** “Forgot password” needs to send mail. A free Mailjet account with no card is enough for a family. You only verify one email address (for example your Gmail) — no website to buy.

**Steps – exact clicks:**

1. Go to `https://www.mailjet.com` → Sign up (free).
2. Add a sender: find **Sender addresses** → **Add** → type the Gmail you actually read → **Add** → open that Gmail inbox → click Mailjet’s Verify link until Mailjet shows green Active. Use that same Gmail in Step 4 below, or Mailjet will reject the mail.
3. Find the two passwords: open Account → **API Key Management**. Copy the long **API Key** (this goes into `MAIL_USERNAME` in `.env`) and the **Secret Key** (this goes into `MAIL_PASSWORD`). They are two different passwords — don’t swap them. Note: keys and sender addresses are on different pages — you won’t see them together.
4. In your `FamQuiz` folder open `.env` in Notepad (plain text). Copy these lines exactly, do not edit the server/port lines. Replace only the placeholders:

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

For the last two lines keep the format `FamQuiz <...>` with brackets — just replace `you@your-verified-email.com` with the green-check Gmail from Step 2. Save, then restart the app (`Ctrl+C`, then `python app.py` again).

5. Test: in FamQuiz click Log out → Forgot password → type your green-check email → check that inbox + Spam in 1–2 minutes.

**If skipped:** mails are not sent and you see a warning in the window, app still runs.

> For helpers only — optional check (sends 1 real mail to your sender address): with `(.venv)` active run `pytest tests/test_live_mail.py -q`. `passed` = works, `skipped` = keys missing so it did nothing, `failed` = copy-paste error.

## 7. Run + play every day

1. On the main computer: open the instruction window inside `FamQuiz` (Section 2). If you closed it, repeat the activate line from Section 3 so you see `(.venv)` again. Then type `python app.py` Enter (on Mac `python3 app.py`). You should see `Running on http://...:5000`, no red error. Keep this window open while you play — closing it stops the game for everyone.
2. On that same computer, open Chrome/Edge and in the address bar go to: `http://127.0.0.1:5000`. You should see a Welcome card with Email and Password boxes and a blue Log in button. First time: Sign up with email + password → choose Game options → **Start game** → wait for the countdown → answer.
3. Invite family: send them the link you used in Section 5A/5B (same Wi-Fi number or Tailscale number, always with `:5000`). If your port is not `5000`, use the link shown on the in-app Guide page (`/guide` — for example `http://YOUR-number:5001/guide`): that page always shows the correct number from your `.env` `PORT` setting, so follow it.
4. Settings: click your profile → Settings. Theme applies instantly. Language (English / Mandarin Chinese / Spanish / Hindi) only changes your own screen.
5. Leaderboard page shows best-ever scores. Stats page shows your games played, wins, and bonus helpers used.
6. On the profile page: Erase = clear my scores but keep my account (stays logged in). Delete = permanently remove my account + cancel games I started. Both cannot be undone — Erase keeps the account, Delete removes it.

## 8. Languages

The game, questions, and emails work in English, Mandarin Chinese, Spanish, and Hindi. No extra download needed. Change it in Profile → Settings → Language — it only changes your screen.

> For builders: strings live in `translations.json` (`es`/`hi`/`zh_Hans`). To add text, add English to all three dicts and use `{{ _('...') }}` in the template, then run `pytest tests/test_i18n.py -q`.

## 9. Tests + size [Optional — skip this to just play]

No need to run this to play.

* Quick check (free, no mail/credits): `pytest tests/ -q --ignore=tests/test_ollama_live.py --ignore=tests/test_live_mail.py` → you should see `120 passed`.
* Live checks (use credits / send a real mail): the two commands in Sections 4 and 6.
* Size: the code is about 10 MB. It uses about 100 MB memory while running — fine on any recent laptop.

## If something goes wrong

Find your message below. Try only that fix first.

1. **You see: “Quiz questions aren’t turned on yet” (missing key)** → Ask the family admin to add the Ollama quiz key (see Section 4), save `.env`, then stop and restart with `Ctrl+C` + `python app.py`.
2. **Quiz says “Something went wrong” (error 502)** → Press Start once again. The question service is sometimes flaky and the app drops bad questions automatically. If it happens twice in a row, wait 1 minute.
3. **You see “Slow down / Cooling down” (error 429)** → Wait 15 seconds and try once. This is normal — it protects your free credits. Don’t double-click. Quiz allows 1 try per 10 seconds, lobby 1 per 5 seconds.
4. **“Timer not started” (error 409)** → Reload the question page, answer only once, don’t double-click. Answering before the question loads gives no points.
5. **“No live game / No active quiz” (error 404)** → Start from the homepage using the same link as everyone (don’t mix `localhost` on one device and the Tailscale number on another).
6. **Link won’t open (Tailscale)** → Checklist: 1) Is the main computer on with the app window open showing `Running on...`? 2) Is Tailscale ON and Connected for *both* people and logged into the *same* family account? 3) Did you copy the full link including `:5000` with `http://` (not `https://`)? For helpers: try `tailscale status`, `ping 100.x` (your number), `curl http://YOUR-number:5000/guide`.
7. **No mail arrives** → Check Spam first, search for your sender address. Was the sender verified green Active (Section 6 Step 2)? Are server/port exactly as shown? If the mail secret changed, old reset links stop working — request a new Forgot Password mail.
8. **“Port in use / address already in use”** → Close other copies of the app. If still stuck, ask a helper to run on another door number: Mac/Linux `PORT=5001 python app.py`, Windows `set PORT=5001` then `python app.py` → open `:5001` instead of `:5000`.
9. **Warning about `SECRET_KEY` / `supersecret`** → In `.env` make `SECRET_KEY=` and `SECURITY_PASSWORD_SALT=` long random strings (use a password manager to generate, 32+ characters). Save, restart. All logins reset — that is expected.
10. **Logged out in a loop / login won’t stick** → Use the same web address on all devices, allow cookies in the browser, don’t open the app inside another site’s frame.

Still stuck? Take a photo of the red text in the instruction window. Cover any long passwords or numbers starting with `100.` and send to your family admin.

## Project structure (for curious)

* `app.py` – settings, users/scores database (`site.db` on the main computer only), languages, quiz + mail helpers.
* `routes.py` – pages + quiz/game/lobby/countdown logic.
* `templates/` + `static/` – light-blue theme and game banner.
* `translations.json` – Spanish, Hindi, Simplified Chinese texts.
* `tests/` – 120 fast checks + live Ollama/Mailjet checks (skipped without keys).

Local only: `site.db` + `.env` stay on the main computer. Don’t share them. Use your computer password and disk encryption (BitLocker on Windows / FileVault on Mac).

---

## 10. Advanced (for curious family + builders)

Simple words first, deeper detail after. Skip if basics work.

### 10.1 All settings in one place

Open `.env` in Notepad/TextEdit (plain text). Each line is `NAME=value` with no spaces around `=`. Save, then restart (`Ctrl+C`, then `python app.py`) so it reads the file.

```env
SECRET_KEY=long-random-note-keeps-logins-safe-make-32-chars-or-more
SECURITY_PASSWORD_SALT=another-long-random-note-different-from-above
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

If email settings are empty, FamQuiz still runs but sends no mail — you will see a warning. If the Ollama key is missing, Start Quiz shows “Quiz service unavailable”. If secrets are short/missing you get a warning and logins reset on restart — make them long random with a password manager.

> Builder note: old names `SMTP-SERVER`, `SMTP-PORT`, `MAIL_SENDER`, `MAIL-API-KEY` still work. `PORT` is used by `python app.py`; plain `flask run` needs `FLASK_RUN_HOST=0.0.0.0` / `FLASK_RUN_PORT=5000` too (already in `.env.example`).

### 10.2 How scoring really works

Correct = 1000 points + up to 500 speed bonus. Answer instantly ≈ 1500, at the last second ≈ 1000, wrong = 0. Win = your total beats everyone else’s best. Tie keeps the earlier champ on top. Your last score shows in the top bar, best ever on the leaderboard.

Power-ups appear randomly about 1 in 3 questions when enabled: Double ×2, 50:50 removes 2 wrong answers, Extra Time 30s → 45s, Hint shows the first letter.

> Builder note: formula is `1000 + round(500 * (1 - elapsed_ms / limit_ms))`. Timer starts when the question appears. Answering without loading returns 409, no free points. Answers are stored in the signed login cookie (readable as text but tamper-proof if `SECRET_KEY` is strong) — don’t share your cookie, use a strong secret.

### 10.3 Lobby and auto-open

There is one shared lobby. It waits 10 seconds to 5 minutes (you pick), then goes live and ends automatically after the game time. Old games auto-close so ghosts don’t stick. Everyone sees the same countdown, recomputed every second.

If Do Not Disturb is on or reminders are off, you only see the banner — tap Join yourself, it won’t auto-jump. Dismiss is per game, so dismissing the lobby also dismisses its live phase. Join sends your language so each player gets questions in their own language.

> Builder note: `GameSession` model, Server-Sent Events primary + 4-second poll fallback, `?once=1` for tests, countdown from `starts_at`.

### 10.4 Safety checklist for the family

1. Use strong family passwords (no brute-force lockout, so passwords matter).
2. After everyone joined, turn off “Allow new accounts” so neighbours on the same Wi-Fi can’t register.
3. Don’t share `site.db` / `.env` files. Keep the main computer locked.

> Builder note: host runs with `debug=False` on `0.0.0.0` (reachable on LAN/Tailscale, debugger off). Headers `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`. Cookies `HttpOnly + SameSite=Lax`. JSON posts send `X-CSRFToken` (tests use `WTF_CSRF_ENABLED=False`). Limits: 1 quiz/10s, 1 lobby/5s (tests exempt). `SECURITY_REGISTERABLE=False` stops new registrations.

### 10.5 Languages for builders

Skip unless building. Order: per-mail choice → `?lang=` in address → saved session → your profile setting → browser → English. Mails use per-person templates. Browser code uses `window.I18N` + `/api/i18n/<locale>.json`. Add text with `{{ _('...') }}` and test with `pytest tests/test_i18n.py -q`.

### 10.6 Models, mail, network tweaks

Ollama uses the free default model. Any mail company works with the same `MAIL_*` lines (for example SendGrid single-sender). Network tips: prefer the Tailscale name over the raw `100.x` number if it changes, set a static home IP on your router for a stable link, firewall Allow Private only, `PORT=5001` fixes a clash (see troubleshooting #8).

> Builder note: `temperature 0.7`, strict JSON, single-line fix, tolerates `answer` text / `1.0` / `B`, drops duplicates, truncates to asked `n`.

### 10.7 Tests, size, peek at data

Family can skip this.

```bash
pytest tests/ -q --ignore=tests/test_ollama_live.py --ignore=tests/test_live_mail.py
```

You should see `120 passed`. Live commands in Sections 4/6 spend credits/mail. Code is ~10 MB. Peek (main computer only):

```bash
sqlite3 instance/site.db "select email,best_score,total_wins from user;"
```

`instance/` and `.env` are ignored by git and never served to players.
