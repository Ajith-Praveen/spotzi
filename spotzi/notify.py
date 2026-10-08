"""SpotZ^i outbound notifications: durable outbox, opt-in per user, Slack-compatible webhook + SMTP email.
Content is deliberately neutral (case IDs and actions only — no provider/member names, scores or outcomes).
Configuration (environment):
  SPOTZI_SLACK_WEBHOOK   incoming-webhook URL (Slack, Teams-compatible relays, or any JSON endpoint)
  SPOTZI_SMTP_HOST / SPOTZI_SMTP_PORT / SPOTZI_SMTP_USER / SPOTZI_SMTP_PASSWORD / SPOTZI_SMTP_FROM / SPOTZI_SMTP_TLS (1 = STARTTLS)
  SPOTZI_BASE_URL        link prefix in messages (default http://localhost:8000)"""
from __future__ import annotations

import os
import smtplib
import threading
import time
from email.message import EmailMessage

MAX_ATTEMPTS = 5


def schema(c):
    c.executescript("""CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, recipient TEXT, subject TEXT, body TEXT,
        status TEXT, attempts INTEGER DEFAULT 0, next_try REAL, last_error TEXT, created TEXT, sent TEXT);""")


def channels():
    return dict(slack=bool(os.environ.get("SPOTZI_SLACK_WEBHOOK")), email=bool(os.environ.get("SPOTZI_SMTP_HOST")))


def base_url():
    return os.environ.get("SPOTZI_BASE_URL", "http://localhost:8000").rstrip("/")


def enqueue(c, user_row, text, link):
    """Called for every in-app notification; queues external copies only where the user opted in and the channel exists."""
    ch = channels(); now = time.strftime("%Y-%m-%d %H:%M:%S"); n = 0
    url = f"{base_url()}/#/{link}" if link else base_url()
    body = f"{text}\nOpen in SpotZ^i (sign-in required): {url}"
    if ch["email"] and user_row["notify_email"] and user_row["email"]:
        c.execute("INSERT INTO outbox(channel,recipient,subject,body,status,next_try,created) VALUES(?,?,?,?,?,?,?)",
                  ("email", user_row["email"], "SpotZ^i: " + text[:80], body, "pending", time.time(), now)); n += 1
    if ch["slack"] and user_row["notify_slack"]:
        c.execute("INSERT INTO outbox(channel,recipient,subject,body,status,next_try,created) VALUES(?,?,?,?,?,?,?)",
                  ("slack", user_row["name"], "", f"*{user_row['name']}*: {text} — <{url}|open in SpotZ^i>", "pending", time.time(), now)); n += 1
    return n


def _send(row, http=None):
    if row["channel"] == "slack":
        import httpx
        r = (http or httpx).post(os.environ["SPOTZI_SLACK_WEBHOOK"], json={"text": row["body"]}, timeout=10)
        if r.status_code >= 300: raise RuntimeError(f"webhook HTTP {r.status_code}")
    else:
        m = EmailMessage(); m["From"] = os.environ.get("SPOTZI_SMTP_FROM", "spotzi@localhost"); m["To"] = row["recipient"]; m["Subject"] = row["subject"]
        m.set_content(row["body"] + "\n\nThis message contains no case details by design.")
        with smtplib.SMTP(os.environ["SPOTZI_SMTP_HOST"], int(os.environ.get("SPOTZI_SMTP_PORT", "587")), timeout=15) as s:
            if os.environ.get("SPOTZI_SMTP_TLS", "1") == "1": s.starttls()
            if os.environ.get("SPOTZI_SMTP_USER"): s.login(os.environ["SPOTZI_SMTP_USER"], os.environ.get("SPOTZI_SMTP_PASSWORD", ""))
            s.send_message(m)


def deliver(db, http=None):
    """Process due outbox rows once. Retries with exponential back-off; gives up after MAX_ATTEMPTS."""
    c = db(); rows = [dict(r) for r in c.execute("SELECT * FROM outbox WHERE status='pending' AND next_try<=? ORDER BY id LIMIT 50", (time.time(),)).fetchall()]; c.close()
    done = 0
    for r in rows:
        try:
            _send(r, http); st, err, nt = "sent", None, None; done += 1
        except Exception as e:
            a = r["attempts"] + 1
            st = "failed" if a >= MAX_ATTEMPTS else "pending"; err = f"{type(e).__name__}: {str(e)[:150]}"; nt = time.time() + 30 * 2 ** a
        c = db()
        c.execute("UPDATE outbox SET status=?, attempts=attempts+1, last_error=?, next_try=?, sent=? WHERE id=?",
                  (st, err, nt, time.strftime("%Y-%m-%d %H:%M:%S") if st == "sent" else None, r["id"])); c.commit(); c.close()
    return done


def start_worker(db, every=5):
    def loop():
        while True:
            try: deliver(db)
            except Exception: pass
            time.sleep(every)
    threading.Thread(target=loop, daemon=True, name="spotzi-outbox").start()
