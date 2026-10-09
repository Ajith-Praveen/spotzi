"""SpotZⁱ authentication and role-based access. Local users, PBKDF2 password hashing, HttpOnly session cookies.
Roles: investigator · supervisor · analyst · admin. The server, not the client, decides who is acting."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
import urllib.parse
from pathlib import Path

ROLES = ["investigator", "supervisor", "analyst", "admin"]
COOKIE = "spotzi_session"
SESSION_HOURS = 12
MIN_PASSWORD = 8  # NIST SP 800-63B minimum for user-chosen passwords
PERMS = {
    "decide": {"investigator", "supervisor", "admin"},
    "approve_referral": {"supervisor", "admin"},
    "investigate": {"investigator", "supervisor", "admin"},
    "assign": {"supervisor", "admin"},
    "review_knowledge": {"analyst", "supervisor", "admin"},
    "approve_precedent": {"supervisor", "admin"},
    "run_models": {"analyst", "admin"},
    "manage_users": {"admin"},
}


def schema(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, name TEXT, role TEXT, salt TEXT, pw_hash TEXT, active INTEGER DEFAULT 1, created TEXT);
    CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, created REAL, expires REAL);
    """)


def _hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()


def create_user(c, username, name, role, password):
    import re

    username = (username or "").lower().strip()
    if not re.match(r"^[a-z0-9][a-z0-9._-]{2,31}$", username):
        raise ValueError("username must be 3–32 characters: letters, digits, dot, dash or underscore")
    if not (name or "").strip():
        raise ValueError("name is required")
    if role not in ROLES:
        raise ValueError("unknown role")
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        raise ValueError(f"username '{username}' is already taken")
    salt = secrets.token_hex(16)
    c.execute(
        "INSERT INTO users(username,name,role,salt,pw_hash,active,created) VALUES(?,?,?,?,?,1,?)",
        (username.lower().strip(), name.strip(), role, salt, _hash(password, salt), time.strftime("%Y-%m-%d %H:%M:%S")),
    )


def set_password(c, uid, password):
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    salt = secrets.token_hex(16)
    c.execute("UPDATE users SET salt=?, pw_hash=? WHERE id=?", (salt, _hash(password, salt), uid))
    c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))


def seed(c, path: Path):
    """First boot only: create demo users with random passwords and write them to a local file (never to the UI or logs)."""
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return False
    people = [
        ("alex", "Alex Morgan", "investigator"),
        ("jordan", "Jordan Patel", "investigator"),
        ("sam", "Sam Rivera", "supervisor"),
        ("dana", "Dana Lee", "analyst"),
        ("admin", "Administrator", "admin"),
    ]
    creds = []
    for u, n, r in people:
        pw = secrets.token_urlsafe(12)
        create_user(c, u, n, r, pw)
        creds.append(dict(username=u, name=n, role=r, password=pw))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            dict(
                note="Local demo accounts for SpotZⁱ (synthetic environment). Change or delete for any shared deployment.",
                users=creds,
            ),
            indent=1,
        )
    )
    try:
        path.chmod(0o600)
    except Exception:
        pass
    return True


def login(c, username, password):
    r = c.execute("SELECT * FROM users WHERE username=? AND active=1", (username.lower().strip(),)).fetchone()
    time.sleep(0.2)  # blunt brute force
    if not r or not hmac.compare_digest(_hash(password, r["salt"]), r["pw_hash"]):
        return None
    tok = secrets.token_urlsafe(32)
    c.execute(
        "INSERT INTO sessions(token,user_id,created,expires) VALUES(?,?,?,?)",
        (tok, r["id"], time.time(), time.time() + SESSION_HOURS * 3600),
    )
    return tok


def user_for(c, token):
    if not token:
        return None
    r = c.execute(
        "SELECT u.id, u.username, u.name, u.role, s.expires FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND u.active=1",
        (token,),
    ).fetchone()
    if not r or r["expires"] < time.time():
        return None
    return dict(id=r["id"], username=r["username"], name=r["name"], role=r["role"])


def can(user, perm):
    return bool(user) and user["role"] in PERMS[perm]


# =============================================================================== two-factor (TOTP, RFC 6238)


def migrate(c):
    cols = {r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()}
    for col, ddl in [
        ("email", "TEXT"),
        ("mfa_secret", "TEXT"),
        ("mfa_enabled", "INTEGER DEFAULT 0"),
        ("mfa_last", "INTEGER DEFAULT 0"),
        ("recovery", "TEXT"),
        ("notify_email", "INTEGER DEFAULT 0"),
        ("notify_slack", "INTEGER DEFAULT 0"),
    ]:
        if col not in cols:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS mfa_tickets(ticket TEXT PRIMARY KEY, user_id INTEGER, expires REAL);
    CREATE TABLE IF NOT EXISTS sso_states(state TEXT PRIMARY KEY, nonce TEXT, verifier TEXT, expires REAL);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    """)


def setting(c, key, default=None):
    r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_setting(c, key, value):
    c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, json.dumps(value)))


def totp(secret_b32, t=None, step=30, digits=6, counter=None):
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8))
    ctr = counter if counter is not None else int((t if t is not None else time.time()) // step)
    h = hmac.new(key, struct.pack(">Q", ctr), hashlib.sha1).digest()
    o = h[-1] & 15
    return f"{(struct.unpack('>I', h[o : o + 4])[0] & 0x7FFFFFFF) % 10**digits:0{digits}d}"


def totp_verify(c, user_row, code, t=None):
    """±1 step window; a code (time step) can be used only once (replay protection)."""
    if not user_row["mfa_secret"] or not code:
        return False
    code = code.strip().replace(" ", "")
    now = int((t if t is not None else time.time()) // 30)
    for ctr in (now - 1, now, now + 1):
        if ctr > (user_row["mfa_last"] or 0) and hmac.compare_digest(totp(user_row["mfa_secret"], counter=ctr), code):
            c.execute("UPDATE users SET mfa_last=? WHERE id=?", (ctr, user_row["id"]))
            return True
    # recovery code (single use)
    rec = json.loads(user_row["recovery"] or "[]")
    hc = hashlib.sha256(code.encode()).hexdigest()
    if hc in rec:
        rec.remove(hc)
        c.execute("UPDATE users SET recovery=? WHERE id=?", (json.dumps(rec), user_row["id"]))
        return True
    return False


def mfa_begin(c, uid, username):
    secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    c.execute("UPDATE users SET mfa_secret=?, mfa_enabled=0, mfa_last=0 WHERE id=?", (secret, uid))
    uri = f"otpauth://totp/{urllib.parse.quote('SpotZⁱ:' + username)}?secret={secret}&issuer={urllib.parse.quote('SpotZⁱ')}&digits=6&period=30"
    return secret, uri


def mfa_confirm(c, uid, code):
    r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not totp_verify(c, r, code):
        return None
    codes = [secrets.token_hex(4) + "-" + secrets.token_hex(4) for _ in range(8)]
    c.execute(
        "UPDATE users SET mfa_enabled=1, recovery=? WHERE id=?",
        (json.dumps([hashlib.sha256(x.encode()).hexdigest() for x in codes]), uid),
    )
    return codes


def password_ok(c, username, password):
    r = c.execute("SELECT * FROM users WHERE username=? AND active=1", (username.lower().strip(),)).fetchone()
    time.sleep(0.2)
    if not r or not hmac.compare_digest(_hash(password, r["salt"]), r["pw_hash"]):
        return None
    return r


def new_session(c, uid):
    tok = secrets.token_urlsafe(32)
    c.execute(
        "INSERT INTO sessions(token,user_id,created,expires) VALUES(?,?,?,?)",
        (tok, uid, time.time(), time.time() + SESSION_HOURS * 3600),
    )
    return tok


def mfa_ticket(c, uid):
    t = secrets.token_urlsafe(24)
    c.execute("INSERT INTO mfa_tickets(ticket,user_id,expires) VALUES(?,?,?)", (t, uid, time.time() + 300))
    return t


def mfa_ticket_user(c, ticket):
    r = c.execute("SELECT * FROM mfa_tickets WHERE ticket=?", (ticket,)).fetchone()
    if not r or r["expires"] < time.time():
        return None
    return r["user_id"]


# =============================================================================== SSO (OpenID Connect, authorization code + PKCE)

HTTP = None  # injectable httpx.Client (tests use a MockTransport)


def _http():
    global HTTP
    if HTTP is None:
        import httpx

        HTTP = httpx.Client(timeout=10)
    return HTTP


def oidc_config():
    iss = os.environ.get("SPOTZI_OIDC_ISSUER", "").rstrip("/")
    if not iss:
        return None
    return dict(
        issuer=iss,
        client_id=os.environ.get("SPOTZI_OIDC_CLIENT_ID", ""),
        client_secret=os.environ.get("SPOTZI_OIDC_CLIENT_SECRET", ""),
        redirect=os.environ.get("SPOTZI_OIDC_REDIRECT", "http://localhost:8000/api/sso/callback"),
        label=os.environ.get("SPOTZI_OIDC_LABEL", "Sign in with SSO"),
        claim=os.environ.get("SPOTZI_OIDC_USER_CLAIM", "email"),
    )


def _b64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def oidc_discover(cfg):
    return _http().get(cfg["issuer"] + "/.well-known/openid-configuration").json()


def oidc_start(c, cfg):
    meta = oidc_discover(cfg)
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    c.execute(
        "INSERT INTO sso_states(state,nonce,verifier,expires) VALUES(?,?,?,?)",
        (state, nonce, verifier, time.time() + 600),
    )
    q = dict(
        response_type="code",
        client_id=cfg["client_id"],
        redirect_uri=cfg["redirect"],
        scope="openid email profile",
        state=state,
        nonce=nonce,
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    return meta["authorization_endpoint"] + "?" + urllib.parse.urlencode(q)


def verify_jwt(token, jwks, issuer, audience, nonce=None, leeway=60):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    h64, p64, s64 = token.split(".")
    header, payload = json.loads(_b64u(h64)), json.loads(_b64u(p64))
    if header.get("alg") != "RS256":
        raise ValueError("unsupported alg")
    key = next((k for k in jwks["keys"] if k.get("kid") == header.get("kid")), None) or (
        jwks["keys"][0] if len(jwks["keys"]) == 1 else None
    )
    if not key:
        raise ValueError("signing key not found")
    pub = rsa.RSAPublicNumbers(
        int.from_bytes(_b64u(key["e"]), "big"), int.from_bytes(_b64u(key["n"]), "big")
    ).public_key()
    pub.verify(_b64u(s64), f"{h64}.{p64}".encode(), padding.PKCS1v15(), hashes.SHA256())
    now = time.time()
    if payload.get("iss", "").rstrip("/") != issuer:
        raise ValueError("issuer mismatch")
    aud = payload.get("aud")
    aud = aud if isinstance(aud, list) else [aud]
    if audience not in aud:
        raise ValueError("audience mismatch")
    if payload.get("exp", 0) + leeway < now:
        raise ValueError("token expired")
    if payload.get("nbf", 0) - leeway > now:
        raise ValueError("token not yet valid")
    if nonce is not None and payload.get("nonce") != nonce:
        raise ValueError("nonce mismatch")
    return payload


def oidc_finish(c, cfg, code, state):
    r = c.execute("SELECT * FROM sso_states WHERE state=?", (state,)).fetchone()
    c.execute("DELETE FROM sso_states WHERE state=?", (state,))
    if not r or r["expires"] < time.time():
        raise ValueError("invalid or expired login state")
    meta = oidc_discover(cfg)
    tok = (
        _http()
        .post(
            meta["token_endpoint"],
            data=dict(
                grant_type="authorization_code",
                code=code,
                redirect_uri=cfg["redirect"],
                client_id=cfg["client_id"],
                client_secret=cfg["client_secret"],
                code_verifier=r["verifier"],
            ),
        )
        .json()
    )
    if "id_token" not in tok:
        raise ValueError("no id_token returned")
    jwks = _http().get(meta["jwks_uri"]).json()
    claims = verify_jwt(tok["id_token"], jwks, cfg["issuer"], cfg["client_id"], r["nonce"])
    ident = str(claims.get(cfg["claim"], "")).lower()
    u = c.execute(
        "SELECT * FROM users WHERE (lower(email)=? OR username=?) AND active=1",
        (ident, ident.split("@")[0] if cfg["claim"] == "username" else ident),
    ).fetchone()
    if not u:
        raise PermissionError(f"No active SpotZⁱ account is linked to {ident}. Ask an administrator to add it.")
    return u, claims
