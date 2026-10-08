"""Local test inbox: an SMTP catcher (127.0.0.1:2525) and a webhook catcher (127.0.0.1:2526) so email and Slack delivery
can be verified end-to-end without any external account. Bound to the loopback interface only; messages are kept in the
dev_inbox table and shown in Settings. Switch to your real SMTP server / Slack webhook in Settings at any time."""
from __future__ import annotations

import asyncio
import email
import json
import threading
import time
from email import policy
from http.server import BaseHTTPRequestHandler, HTTPServer

SMTP_PORT, HOOK_PORT = 2525, 2526
_started = {"on": False}


def schema(c):
    c.executescript("CREATE TABLE IF NOT EXISTS dev_inbox(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, channel TEXT, recipient TEXT, subject TEXT, body TEXT);")


def _store(db, channel, recipient, subject, body):
    c = db(); c.execute("INSERT INTO dev_inbox(ts,channel,recipient,subject,body) VALUES(?,?,?,?,?)",
                        (time.strftime("%Y-%m-%d %H:%M:%S"), channel, recipient[:200], subject[:200], body[:4000])); c.commit(); c.close()


class _SMTP(asyncio.Protocol):
    """Minimal SMTP server: enough of RFC 5321 for smtplib (EHLO/HELO, MAIL, RCPT, DATA, RSET, NOOP, QUIT)."""
    def __init__(self, db): self.db, self.buf, self.data, self.rcpt = db, b"", None, []

    def connection_made(self, t): self.t = t; t.write(b"220 spotzi-test-inbox ESMTP\r\n")

    def data_received(self, d):
        self.buf += d
        while True:
            if self.data is not None:
                i = self.buf.find(b"\r\n.\r\n")
                if i < 0: return
                raw, self.buf = self.data + self.buf[:i], self.buf[i + 5:]; self.data = None
                msg = email.message_from_bytes(raw.replace(b"\r\n..", b"\r\n."), policy=policy.default)
                body = msg.get_body(("plain",)); text = body.get_content() if body else ""
                _store(self.db, "email", ", ".join(self.rcpt), str(msg.get("Subject", "")), text)
                self.rcpt = []; self.t.write(b"250 OK queued\r\n"); continue
            i = self.buf.find(b"\r\n")
            if i < 0: return
            line, self.buf = self.buf[:i].decode(errors="replace"), self.buf[i + 2:]
            cmd = line[:4].upper()
            if cmd in ("EHLO", "HELO"): self.t.write(b"250-spotzi-test-inbox\r\n250 8BITMIME\r\n" if cmd == "EHLO" else b"250 spotzi-test-inbox\r\n")
            elif cmd == "MAIL": self.t.write(b"250 OK\r\n")
            elif cmd == "RCPT": self.rcpt.append(line.split(":", 1)[-1].strip(" <>")); self.t.write(b"250 OK\r\n")
            elif cmd == "DATA": self.data = b""; self.t.write(b"354 End data with <CR><LF>.<CR><LF>\r\n")
            elif cmd in ("RSET", "NOOP"): self.rcpt = []; self.t.write(b"250 OK\r\n")
            elif cmd == "QUIT": self.t.write(b"221 Bye\r\n"); self.t.close(); return
            else: self.t.write(b"502 Not implemented\r\n")


def start(db):
    if _started["on"]: return True
    try:
        loop = asyncio.new_event_loop()
        srv = loop.run_until_complete(loop.create_server(lambda: _SMTP(db), "127.0.0.1", SMTP_PORT))

        class Hook(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0); raw = self.rfile.read(min(n, 20000))
                try: text = json.loads(raw).get("text", "")
                except Exception: text = raw.decode(errors="replace")
                _store(db, "slack", "#spotzi-alerts (test inbox)", "", text)
                self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
            def log_message(self, *a): pass
        hook = HTTPServer(("127.0.0.1", HOOK_PORT), Hook)
        threading.Thread(target=loop.run_forever, daemon=True, name="spotzi-test-smtp").start()
        threading.Thread(target=hook.serve_forever, daemon=True, name="spotzi-test-webhook").start()
        _started["on"] = True; return True
    except OSError as e:
        print("SpotZⁱ: test inbox not started:", e); return False
