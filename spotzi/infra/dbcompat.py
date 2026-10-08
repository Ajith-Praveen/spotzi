"""SpotZⁱ storage layer: one connection API over PostgreSQL (production) or SQLite (single-machine / tests).

The application writes portable SQL with `?` placeholders. For PostgreSQL this module translates:
  ?                                  -> %s
  INTEGER PRIMARY KEY AUTOINCREMENT  -> BIGSERIAL PRIMARY KEY
  REAL                               -> DOUBLE PRECISION   (epoch seconds need 8-byte floats)
  INSERT OR REPLACE INTO t(cols)     -> INSERT ... ON CONFLICT (pk) DO UPDATE SET col = EXCLUDED.col
  ALTER TABLE .. ADD COLUMN          -> ADD COLUMN IF NOT EXISTS
  PRAGMA table_info(t)               -> information_schema.columns
and returns rows that support both row["col"] and row[0].
Select the backend with SPOTZI_DB_URL=postgresql://user:pass@host:port/db (otherwise SQLite at SPOTZI_DB)."""
from __future__ import annotations

import re
import sqlite3

UPSERT_KEYS = {"wiki_pages": "slug", "precedent_quality": "case_id", "case_assign": "case_id", "settings": "key"}
SERIAL_TABLES = {"decisions", "audit", "lab_events", "blueprints", "blueprint_items", "wiki_history", "wiki_proposals", "case_notes",
                 "notifications", "outbox", "case_scope", "users", "prepay_log", "recoveries", "custom_rules", "case_documents", "tips", "chart_reviews", "prediction_log", "dev_inbox"}


class Row(dict):
    def __init__(self, names, values):
        super().__init__(zip(names, values)); self._v = tuple(values)

    def __getitem__(self, k):
        return self._v[k] if isinstance(k, int) else dict.__getitem__(self, k)

    def keys(self):
        return list(dict.keys(self))


def _row_factory(cursor):
    names = [d.name for d in (cursor.description or [])]
    return lambda values: Row(names, values)


_INS = re.compile(r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\(([^)]*)\)", re.I | re.S)
_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.I)


def translate(sql: str) -> str:
    q = sql
    m = _INS.match(q)
    if m:
        table, cols = m.group(1), [c.strip() for c in m.group(2).split(",")]
        key = UPSERT_KEYS[table]
        q = _INS.sub(lambda mm: f"INSERT INTO {mm.group(1)}({mm.group(2)})", q, count=1)
        sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != key)
        q = q.rstrip().rstrip(";") + f" ON CONFLICT ({key}) DO UPDATE SET {sets}"
    q = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "BIGSERIAL PRIMARY KEY", q, flags=re.I)
    q = re.sub(r"\bREAL\b", "DOUBLE PRECISION", q)
    q = re.sub(r"ADD\s+COLUMN\s+(?!IF\s+NOT\s+EXISTS)", "ADD COLUMN IF NOT EXISTS ", q, flags=re.I)
    pm = re.match(r"^\s*PRAGMA\s+table_info\((\w+)\)", q, re.I)
    if pm:
        q = f"SELECT column_name AS name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = '{pm.group(1)}'"
    # ? -> %s outside quoted literals
    out, quote = [], False
    for ch in q:
        if ch == "'": quote = not quote
        out.append("%s" if ch == "?" and not quote else ch)
    return "".join(out)


class _Cursor:
    def __init__(self, cur, lastrowid=None):
        self._c, self.lastrowid = cur, lastrowid

    def fetchone(self):
        return self._c.fetchone() if self._c.description else None

    def fetchall(self):
        return self._c.fetchall() if self._c.description else []

    def __iter__(self):
        return iter(self.fetchall())


class PGConnection:
    backend = "postgres"

    def __init__(self, url):
        import psycopg
        self._c = psycopg.connect(url, row_factory=_row_factory)

    def execute(self, sql, params=()):
        q = translate(sql)
        m = _INSERT.match(q)
        returning = bool(m and m.group(1).lower() in SERIAL_TABLES and "RETURNING" not in q.upper() and "ON CONFLICT" not in q.upper())
        if returning: q = q.rstrip().rstrip(";") + " RETURNING id"
        cur = self._c.execute(q, tuple(params) if params else None)
        rid = None
        if returning:
            r = cur.fetchone(); rid = r[0] if r else None
        return _Cursor(cur, rid)

    def executescript(self, script):
        for stmt in [s.strip() for s in script.split(";") if s.strip()]:
            self._c.execute(translate(stmt))

    def commit(self): self._c.commit()
    def rollback(self): self._c.rollback()
    def close(self): self._c.close()

    @property
    def row_factory(self): return None

    @row_factory.setter
    def row_factory(self, _): pass


def connect(url=None, path=None):
    if url and url.startswith(("postgres://", "postgresql://")):
        return PGConnection(url)
    c = sqlite3.connect(path, timeout=15)
    c.row_factory = sqlite3.Row
    return c
