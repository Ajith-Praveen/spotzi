"""SpotZⁱ outbound notifications: durable outbox, opt-in per user, Slack-compatible webhook + SMTP email.
Content is deliberately neutral (case IDs and actions only — no provider/member names, scores or outcomes).
Configuration: set by an admin in Settings → Email & Slack delivery (operations.notify.configure); the environment
variables below are the fallback when nothing is saved in the app:
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


_CFG: dict | None = None


def _env():
    return dict(email_enabled=bool(os.environ.get("SPOTZI_SMTP_HOST")), smtp_host=os.environ.get("SPOTZI_SMTP_HOST", ""), smtp_port=int(os.environ.get("SPOTZI_SMTP_PORT", "587")),
                smtp_user=os.environ.get("SPOTZI_SMTP_USER", ""), smtp_password=os.environ.get("SPOTZI_SMTP_PASSWORD", ""), smtp_from=os.environ.get("SPOTZI_SMTP_FROM", "spotzi@localhost"),
                smtp_security="starttls" if os.environ.get("SPOTZI_SMTP_TLS", "1") == "1" else "none",
                slack_enabled=bool(os.environ.get("SPOTZI_SLACK_WEBHOOK")), slack_webhook=os.environ.get("SPOTZI_SLACK_WEBHOOK", ""),
                base_url=os.environ.get("SPOTZI_BASE_URL", "http://localhost:8000"))


def configure(cfg: dict | None):
    global _CFG
    _CFG = None if cfg is None else {**_env(), **{k: v for k, v in cfg.items() if v is not None}}


def config() -> dict:
    return _CFG if _CFG is not None else _env()


def channels():
    c = config()
    return dict(slack=bool(c.get("slack_enabled") and c.get("slack_webhook")), email=bool(c.get("email_enabled") and c.get("smtp_host")))


def base_url():
    return (config().get("base_url") or "http://localhost:8000").rstrip("/")


def enqueue(c, user_row, text, link):
    """Called for every in-app notification; queues external copies only where the user opted in and the channel exists."""
    ch = channels(); now = time.strftime("%Y-%m-%d %H:%M:%S"); n = 0
    url = f"{base_url()}/app#/{link}" if link else f"{base_url()}/app"
    body = f"{text}\nOpen in SpotZⁱ (sign-in required): {url}"
    if ch["email"] and user_row["notify_email"] and user_row["email"]:
        c.execute("INSERT INTO outbox(channel,recipient,subject,body,status,next_try,created) VALUES(?,?,?,?,?,?,?)",
                  ("email", user_row["email"], "SpotZⁱ: " + text[:80], body, "pending", time.time(), now)); n += 1
    if ch["slack"] and user_row["notify_slack"]:
        c.execute("INSERT INTO outbox(channel,recipient,subject,body,status,next_try,created) VALUES(?,?,?,?,?,?,?)",
                  ("slack", user_row["name"], "", f"*{user_row['name']}*: {text} — <{url}|open in SpotZⁱ>", "pending", time.time(), now)); n += 1
    return n


def _send(row, http=None):
    c = config()
    if row["channel"] == "slack":
        import httpx
        r = (http or httpx).post(c["slack_webhook"], json={"text": row["body"]}, timeout=10)
        if r.status_code >= 300: raise RuntimeError(f"webhook HTTP {r.status_code}")
    else:
        m = EmailMessage(); m["From"] = c.get("smtp_from") or "spotzi@localhost"; m["To"] = row["recipient"]; m["Subject"] = row["subject"]
        m.set_content(row["body"] + "\n\nThis message contains no case details by design.")
        sec, port = c.get("smtp_security", "starttls"), int(c.get("smtp_port") or 587)
        cls = smtplib.SMTP_SSL if sec == "ssl" else smtplib.SMTP
        with cls(c["smtp_host"], port, timeout=15) as s:
            if sec == "starttls": s.starttls()
            if c.get("smtp_user"): s.login(c["smtp_user"], c.get("smtp_password", ""))
            s.send_message(m)


def send_test(channel, to=None):
    """Immediate test message (no outbox), used by the Settings page."""
    row = dict(channel=channel, recipient=to or "", subject="SpotZⁱ test message",
               body=f"Test message from SpotZⁱ. Delivery for this channel works.\nOpen in SpotZⁱ (sign-in required): {base_url()}")
    _send(row)


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
