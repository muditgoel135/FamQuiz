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

## 11. One-file version: build FamQuiz as a single program (optional — helpers only)

This section is for the helper who wants the game as **one program file** (`FamQuiz.exe` on Windows, `FamQuiz` on Mac/Linux), so the main computer does not need Python or the code folder. Players notice nothing — same game, same links, same `.env` secrets.

**Before you start:** you must have finished Section 3 at least once (the `.venv` helper folder exists) and have your `.env` filled (Sections 4 and 6). You build **on the same kind of computer that will run the game**: a file built on Windows runs only on Windows, a build made on a Mac runs only on a Mac, Linux likewise. Want all three kinds? Repeat 11.1–11.6 on each machine.

**Good to know:** the finished file is one program of about 30–60 MB. Opening it takes 2–5 seconds longer than `python app.py` (it unpacks itself first). Closing its black window still stops the game for everyone, exactly like Section 7.

### 11.1 Install the builder (once)

Open the instruction window inside the `FamQuiz` folder (Section 2) and make sure you see `(.venv)` at the start of the line (Section 3). If you closed the window, redo the activate line(s) from Section 3 first. Then copy this one line, paste, Enter, wait.

**Windows:**

```powershell
python -m pip install "pyinstaller>=6.15"
```

**Mac / Linux:**

```bash
python3 -m pip install "pyinstaller>=6.15"
```

What you should see: the last line says `Successfully installed pyinstaller-6.x.x`. This project's Python needs PyInstaller **6.15 or newer**. If you see a red error instead, you are not in the right folder or `(.venv)` is missing — recheck Sections 2 and 3.

### 11.2 Create two small text files in the `FamQuiz` folder

Both go **next to `app.py`** (not inside any subfolder). Nothing in `app.py`, `routes.py` or any other game file changes — these two files are only for packaging. After adding them you can re-run the quick checks any time (`pytest tests/ -q --ignore=tests/test_ollama_live.py --ignore=tests/test_live_mail.py` → still `120 passed`).

**File 1 — `run_famquiz.py`** (the small starter for the packaged game: it keeps your `.env` and the scores database in the folder you put the exe in, instead of inside the exe's throw-away unpack space — without it, scores would vanish on every close). New file, paste exactly:

```python
import os
import sys

# In a frozen exe, place .env + database next to FamQuiz.exe (not in the
# self-extracting temp folder, which is deleted on exit).
if getattr(sys, "frozen", False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

from dotenv import load_dotenv

load_dotenv(os.path.join(base_dir, ".env"))

instance = os.path.join(base_dir, "instance")
os.makedirs(instance, exist_ok=True)
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
    instance, "site.db"
).replace("\\", "/")

import app as app_module

port = int(os.getenv("PORT", 5000))
app_module._print_lan_urls(port)
app_module.app.run(debug=False, host="0.0.0.0", port=port)
```

**File 2 — `FamQuiz.spec`** (the build recipe: what goes inside the one file — templates, game theme and style files, all four UI languages — and what stays out, like the test files; it also packs Flask's login library parts that plain scanning misses). New file, paste exactly:

```python
# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

fs_data, fs_binaries, fs_hidden = collect_all("flask_security")

a = Analysis(
    ["run_famquiz.py"],
    pathex=[],
    binaries=fs_binaries,
    datas=[
        ("templates", "templates"),
        ("static", "static"),
        ("translations.json", "."),
    ],
    hiddenimports=fs_hidden,
    excludes=["tests", "pytest", "pytest_cache"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FamQuiz",
    console=True,
    debug=False,
    upx=False,
)

# No COLLECT(): placing the EXE call last (without it) is what makes this
# a single-file (onefile) build. Data lands in the exe's temp folder,
# exactly where app.py and Flask look for it when frozen.
```

> Builder note: the `EXE(...)` call last without a `COLLECT(...)` section is what makes this a **single-file** build. `console=True` keeps the black window visible; setting it to `False` would make an invisible game nobody can stop.

### 11.3 Build the one file

**Windows:**

```powershell
python -m PyInstaller --clean FamQuiz.spec
```

**Mac / Linux:**

```bash
python3 -m PyInstaller --clean FamQuiz.spec
```

Takes about 1 minute. You should see a final line like `Building EXE from EXE-00.toc ... successfully`. The result:

* Windows: `dist\FamQuiz\FamQuiz.exe`
* Mac / Linux: `dist/FamQuiz/FamQuiz`

The `build\` folder next to it is working material; delete it freely (Windows `Remove-Item -LiteralPath build -Recurse -Force`; Mac/Linux `rm -rf build`). Opening many warnings inside `build\` with words like "not found" is normal — only worry if the final `successfully` line is missing.

> Tip: building inside a synced folder (Google Drive/OneDrive/Dropbox) can turn 1 minute into 10. If it crawls, copy the whole `FamQuiz` folder to Documents, build there, then move the finished file back.

### 11.4 Put your secret settings next to the file

**Windows:**

```powershell
copy .env dist\FamQuiz\
```

**Mac / Linux:**

```bash
cp .env dist/FamQuiz/
```

On first run the scores database appears **next to the exe** inside a new `instance\site.db` (Windows) or `instance/site.db` (Mac/Linux). Treat the exe's folder like the old `FamQuiz` folder: `.env` holds your secrets (Section 6 safety note), and Section 10.4 applies as is.

### 11.5 First run

* **Windows:** double-click `dist\FamQuiz\FamQuiz.exe`.
  * If Windows shows "Windows protected your PC": More info → **Run anyway**. This appears because the file has no paid digital signature; it is normal for one-file programs.
  * If Windows asks about firewall: tick **Private**, untick Public → **Allow** (same choice as Section 5A.3).
* **Mac / Linux:** start it from a Terminal, not the file manager. On Mac also the very first time: if macOS refuses to open it ("unidentified developer"), right-click `FamQuiz` → **Open** → **Open** again. Then:

```bash
cd dist/FamQuiz
./FamQuiz
```

Why Terminal on Mac/Linux: double-clicking this kind of program there often runs it **invisibly** — no window with the web addresses, no easy way to stop it. From Terminal you see the same three `FamQuiz on this computer / Wi-Fi / Tailscale` lines as always, and Ctrl+C stops the game.

### 11.6 Check it works (once) + every day after

Every day: Windows → double-click the exe. Mac/Linux → the two Terminal lines from 11.5. Players join exactly as in Sections 5A/5B (`:5000` links, Guide page shows the port).

Quick one-time check list after building:

1. The black window prints the three `FamQuiz on ...` URLs, no red errors.
2. `http://127.0.0.1:5000` shows the light-blue FamQuiz screen (means styles are packed correctly).
3. Sign up a test user (means logins work in the packaged game).
4. Start a game with 2 questions → questions appear (means your `.env` Ollama key is read).
5. Profile → Settings → switch language to Spanish → the screen switches (means all languages are packed).
6. Close the window, start the exe again → your test user and score are still there (means the database now lives next to the exe and survives).

### 11.7 When a helper updates the game

Repeat only 11.3. The build overwrites the old program file; your `.env` and `instance\site.db` next to it are untouched. No other step needs repeating.

### 11.8 If something goes wrong (exe version only)

Everything from the regular list at the top still applies. Exe-specific fixes:

1. **The black window flashes and disappears** → open the window inside `dist\FamQuiz` (Windows: type `powershell` in the address bar; Mac/Linux: right-click the folder → Open in Terminal) and run `.\FamQuiz.exe` (Windows) or `./FamQuiz` (Mac/Linux). The error text stays on screen — cover any secrets (lines starting `OLLAMA_API_KEY`, `MAIL_USERNAME`, `SECRET_KEY` or numbers starting `100.`) before photographing.
2. **`ModuleNotFoundError: xxx`** in that error → a helper adds the missing name to `FamQuiz.spec` the same way `flask_security` is handled (`collect_all("xxx")`), then rebuilds (11.3).
3. **"Port in use / address already in use"** → the game is already running in another window (`python app.py` or a second exe). Close that one, or set a new door number with `PORT` (regular troubleshooting #8).
4. **Antivirus/Defender removes or blocks the exe** → restore it and add an exception; one-file programs are flagged most, and this one is just packaged FamQuiz.
5. **Building (11.3) stops with red errors** → almost always one of the two files from 11.2 has a wrong name or a missing line, or 11.1 never said `Successfully installed`. Redo 11.1–11.2 exactly.
6. **Players say the links stopped working after the switch** → the exe serves on the same `0.0.0.0:5000` as `python app.py`; nothing about Sections 5A/5B changes. Only one copy of FamQuiz may run at a time.

### 11.9 Put the two files in git (for builders)

`run_famquiz.py` and `FamQuiz.spec` are **source files** — commit them so any helper can rebuild. The default Python `.gitignore` used to hide recipes (the `*.spec` line); on this project that line is already removed. If your copy still has it, delete it or add `!FamQuiz.spec` after it. `build/`, `dist/` and the built program file itself stay ignored — never commit the exe, and never commit `.env` (Section 6: secrets).
