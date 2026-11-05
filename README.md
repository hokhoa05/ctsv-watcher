# CTSV HCMUS watcher

Watches https://ctsv.hcmus.edu.vn/info and notifies you (phone / email) when a new post contains a sentence like *"Sinh viên khoá 2023 tham gia được tính tích luỹ hoạt động chuyên đề A, đợt sinh hoạt
công dân – sinh viên cuối khóa năm học 2026-2027."*

Matching ignores diacritics and case, and accepts spelling variants ("khoá/khóa", "luỹ/lũy") and either "–" or "-".
Change the cohort / academic year with `COHORT` and `ACADEMIC_YEAR` (leave `ACADEMIC_YEAR` empty to skip the year check).

## Usage

```bash
python monitor.py                 # run once (for cron / GitHub Actions)
python monitor.py --loop 600      # run continuously, every 10 minutes
python monitor.py --discover      # list the latest posts and whether each matches (*), send nothing
python monitor.py --check URL     # check whether a specific post matches the filter
python monitor.py --check URL --send  # also send the notification for that post
python monitor.py --test-notify   # send a test notification
python monitor.py --baseline      # mark all current posts as seen without notifying
```

## How it works

The CTSV site is a JavaScript app backed by a JSON API. The script calls it directly (no browser needed):

- `GET /api/news/latest?page=1&limit=50` — latest posts, including `author` and the full HTML `content`
- `GET /api/news/<slug>` — a single post (used by `--check`)

A post matches when its content contains all required phrases (and, if `AUTHOR` is set, its `author` matches).
Seen posts are tracked by ID in `seen.json`.

## 1. Try it locally

```bash
pip install -r requirements.txt
python monitor.py --discover
python monitor.py --check https://ctsv.hcmus.edu.vn/news/<slug>
```

## 2. Configure notification channels (one or more)

Put credentials in a `.env` file next to `monitor.py` (it is git-ignored):

```bash
cp .env.example .env
```

Variables already set in the environment (e.g. GitHub Actions secrets) take precedence over `.env`.

**Telegram (recommended):** message @BotFather → `/newbot` → copy the token. Send any message to your new bot,
then open `https://api.telegram.org/bot<TOKEN>/getUpdates` to find `chat.id`.
→ `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

**ntfy:** install the ntfy app (Android/iOS) and subscribe to a hard-to-guess topic, e.g. `khoa-ctsv-8f3k2x`.
→ `NTFY_TOPIC`

**Gmail:** enable 2-Step Verification and create an *App password* at myaccount.google.com/apppasswords.
→ `SMTP_USER` (your Gmail address), `SMTP_PASSWORD` (the app password), `EMAIL_TO` (optional)

Fill in `.env`, then test it: `python monitor.py --test-notify`

## 3. Run it for free on GitHub Actions

1. Create a **public** repo and push this folder (the code holds no secrets; public repos get unlimited Actions minutes).
2. Settings → Secrets and variables → Actions:
   - *Secrets*: the variables from step 2.
3. Actions tab → "CTSV monitor" → **Run workflow** for the first run.

The first run scans every post currently on the page and notifies you about matching ones (usually activities still open for registration).
To skip that, run `python monitor.py --baseline` locally and commit `seen.json`.

Notes:
- If the API returns no posts, the job **fails** and GitHub emails you — a sign the site changed.
- GitHub disables scheduled workflows after 60 days without commits (you get a warning email first) — just re-enable it.
- If the university blocks foreign IPs, run it on a machine or VPS in Vietnam: `python monitor.py --loop 600`.

## Reliable scheduling

GitHub's `schedule` trigger is best-effort and often delayed or skipped. The workflow keeps a backup schedule
(`7,37 * * * *`), but the main trigger is an external cron service (e.g. [cron-job.org](https://cron-job.org)) calling the API every 15 minutes:

- URL: `https://api.github.com/repos/<owner>/<repo>/actions/workflows/monitor.yml/dispatches`
- Method: `POST`
- Headers: `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`
- Body: `{"ref":"main"}`

Use a fine-grained personal access token limited to this repository with **Actions: Read and write** only.
A successful call returns `204 No Content`.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SITE_URL` | `https://ctsv.hcmus.edu.vn` | Site (API is at `<SITE_URL>/api`) |
| `AUTHOR` | *(empty)* | Only match posts by this author, e.g. `Trương Quốc Tiên`; empty = any author |
| `COHORT` | `2023` | Student cohort |
| `ACADEMIC_YEAR` | `2026-2027` | Academic year; empty to ignore |
| `PAGE_SIZE` | `50` | Posts fetched per page (API max is 100) |
| `PAGES` | `1` | Number of pages fetched per run |
| `STATE_FILE` | `seen.json` | Where seen posts are stored |
| `ENV_FILE` | `.env` next to `monitor.py` | Optional env file to load |
| `NTFY_SERVER` | `https://ntfy.sh` | ntfy server |
| `SMTP_HOST` / `SMTP_PORT` | `smtp.gmail.com` / `465` | SMTP server |
