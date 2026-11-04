#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import sys
import time
import unicodedata
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

import requests


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


load_env(Path(os.getenv("ENV_FILE", Path(__file__).resolve().with_name(".env"))))

SITE_URL = os.getenv("SITE_URL", "https://ctsv.hcmus.edu.vn").rstrip("/")
STATE_FILE = Path(os.getenv("STATE_FILE", "seen.json"))
AUTHOR = os.getenv("AUTHOR", "Trương Quốc Tiên")
COHORT = os.getenv("COHORT", "2023")
ACADEMIC_YEAR = os.getenv("ACADEMIC_YEAR", "2026-2027")
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "50"))
PAGES = int(os.getenv("PAGES", "1"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept": "application/json"})


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm(text: str) -> str:
    t = unicodedata.normalize("NFC", text).lower().replace("đ", "d")
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) not in ("Mn", "Cf"))
    t = re.sub(r"[‐-―−]", "-", t)
    return re.sub(r"\s+", " ", t).strip()


def html_to_text(raw: str) -> str:
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw or "")
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return html.unescape(t)


def required_patterns() -> list[str]:
    pats = [
        rf"khoa {COHORT}",
        r"tich luy hoat dong chuyen de a\b",
        r"sinh hoat cong dan ?- ?sinh vien cuoi khoa",
    ]
    if ACADEMIC_YEAR:
        y1, _, y2 = ACADEMIC_YEAR.partition("-")
        pats.append(rf"{y1.strip()} ?- ?{y2.strip()}")
    return pats


def match_post(post: dict) -> tuple[bool, list[str]]:
    reasons = []
    if norm(AUTHOR) not in norm(post.get("author") or ""):
        reasons.append(f"tác giả là '{post.get('author')}', không phải '{AUTHOR}'")
    text = norm(f"{post.get('title') or ''}\n{post.get('summary') or ''}\n{html_to_text(post.get('content') or '')}")
    for p in required_patterns():
        if not re.search(p, text):
            reasons.append(f"thiếu mẫu /{p}/")
    return not reasons, reasons


def post_url(post: dict) -> str:
    return f"{SITE_URL}/news/{post['slug']}"


def post_key(post: dict) -> str:
    return str(post.get("idCode") or post["slug"])


def api_get(path: str, **params) -> dict:
    r = session.get(f"{SITE_URL}/api{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_latest() -> list[dict]:
    posts: list[dict] = []
    for page in range(1, PAGES + 1):
        data = api_get("/news/latest", page=page, limit=PAGE_SIZE)
        posts.extend(p for p in data.get("data", []) if p.get("slug"))
        if page >= (data.get("meta") or {}).get("totalPages", page):
            break
    return posts


def fetch_post(url_or_slug: str) -> dict:
    slug = urlparse(url_or_slug).path.rstrip("/").rsplit("/", 1)[-1] or url_or_slug
    return api_get(f"/news/{slug}")


def configured_channels() -> list[str]:
    ch = []
    if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        ch.append("telegram")
    if os.getenv("NTFY_TOPIC"):
        ch.append("ntfy")
    if os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD"):
        ch.append("email")
    return ch


def send_all(title: str, body: str, url: str) -> list[str]:
    sent = []
    for ch in configured_channels():
        try:
            if ch == "telegram":
                r = requests.post(
                    f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
                    json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": f"🔔 {title}\n\n{body}"},
                    timeout=20)
                r.raise_for_status()
            elif ch == "ntfy":
                r = requests.post(
                    os.getenv("NTFY_SERVER", "https://ntfy.sh"),
                    json={"topic": os.environ["NTFY_TOPIC"], "title": title, "message": body,
                          "click": url, "priority": 5, "tags": ["bell"]},
                    timeout=20)
                r.raise_for_status()
            elif ch == "email":
                user = os.environ["SMTP_USER"]
                msg = EmailMessage()
                msg["Subject"], msg["From"] = title, user
                msg["To"] = os.getenv("EMAIL_TO") or user
                msg.set_content(body)
                host = os.getenv("SMTP_HOST", "smtp.gmail.com")
                with smtplib.SMTP_SSL(host, int(os.getenv("SMTP_PORT", "465")), timeout=30) as s:
                    s.login(user, os.environ["SMTP_PASSWORD"])
                    s.send_message(msg)
            sent.append(ch)
        except Exception as e:
            print(f"  gửi {ch} lỗi: {e}", file=sys.stderr)
    return sent


def notify_post(p: dict) -> list[str]:
    title = (p.get("title") or "").strip()
    url = post_url(p)
    body = f"{title}\n\n{url}\n\nVào đăng ký ngay kẻo hết chỗ!"
    return send_all(f"[CTSV] Chuyên đề A: {title[:90]}", body, url)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text("utf-8"))
    return {"seen": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")


def run_once(baseline: bool = False) -> int:
    if not baseline and not configured_channels():
        print("Chưa cấu hình kênh thông báo nào (Telegram / ntfy / email).", file=sys.stderr)
        return 3
    state = load_state()
    seen = state.setdefault("seen", {})
    posts = fetch_latest()
    print(f"[{now()}] Lấy được {len(posts)} bài từ API")
    if not posts:
        print("CẢNH BÁO: API không trả về bài nào, có thể trang đã đổi cấu trúc. "
              "Chạy `python monitor.py --discover` để kiểm tra.", file=sys.stderr)
        return 2
    new = [p for p in posts if post_key(p) not in seen]
    if baseline:
        for p in new:
            seen[post_key(p)] = {"title": p.get("title", "")[:200], "matched": None, "at": now()}
        save_state(state)
        print(f"Đã đánh dấu {len(new)} bài là đã xem.")
        return 0

    for p in reversed(new):
        title = (p.get("title") or "").strip()
        url = post_url(p)
        ok, _ = match_post(p)
        if ok:
            channels = notify_post(p)
            if not channels:
                print(f"  KHỚP nhưng gửi thông báo thất bại, sẽ thử lại lần sau: {title}")
                continue
            print(f"  ✅ KHỚP: {title} -> đã báo qua {', '.join(channels)}")
        else:
            print(f"  bỏ qua: {title[:90]}")
        seen[post_key(p)] = {"title": title[:200], "url": url, "matched": ok, "at": now()}
        save_state(state)
    save_state(state)
    return 0


def discover() -> int:
    posts = fetch_latest()
    print(f"=== {len(posts)} bài mới nhất (dấu * = khớp bộ lọc) ===")
    for p in posts:
        ok, _ = match_post(p)
        date = (p.get("createdAt") or "")[:10]
        print(f" {'*' if ok else ' '} [{date}] {p.get('author', '')} | {(p.get('title') or '').strip()[:80]}")
        print(f"     {post_url(p)}")
    return 0


def check(url: str, send: bool = False) -> int:
    p = fetch_post(url)
    ok, reasons = match_post(p)
    print(f"Tiêu đề: {(p.get('title') or '').strip()}\nTác giả: {p.get('author')}")
    print(f"Kết quả: {'KHỚP ✅' if ok else 'KHÔNG KHỚP'}")
    for r in reasons:
        print(f"  - {r}")
    if send:
        sent = notify_post(p)
        print("Đã gửi qua:", sent or "không kênh nào")
        return 0 if sent else 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Theo dõi thông báo CTSV HCMUS")
    ap.add_argument("--loop", type=int, metavar="GIÂY", help="chạy lặp lại mỗi N giây")
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--check", metavar="URL")
    ap.add_argument("--send", action="store_true", help="dùng với --check: gửi thông báo cho bài đó")
    ap.add_argument("--test-notify", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    a = ap.parse_args()

    if a.discover:
        return discover()
    if a.check:
        return check(a.check, send=a.send)
    if a.test_notify:
        sent = send_all("[CTSV] Thông báo thử", "Nếu bạn thấy tin này là cấu hình đã đúng.", SITE_URL)
        print("Đã gửi qua:", sent or "không kênh nào")
        return 0 if sent else 1
    if a.loop:
        while True:
            try:
                run_once()
            except Exception as e:
                print(f"[{now()}] lỗi: {e}", file=sys.stderr)
            time.sleep(a.loop)
    return run_once(baseline=a.baseline)


if __name__ == "__main__":
    sys.exit(main())
