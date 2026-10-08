"""One-off: copy every SpotZⁱ table from the SQLite file into PostgreSQL (schema is created by the app first).
Usage: python3 migrate_to_postgres.py [path/to/app.db]   (target taken from data/db.env SPOTZI_DB_URL)"""
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "app.db"
env = ROOT / "data" / "db.env"
url = os.environ.get("SPOTZI_DB_URL") or [l.split("=", 1)[1].strip() for l in env.read_text().splitlines() if l.startswith("SPOTZI_DB_URL=")][0]
os.environ["SPOTZI_DB_URL"] = url
sys.path.insert(0, str(ROOT))
from api import app as server# noqa: E402  (creates the schema in Postgres)
from infra import dbcompat# noqa: E402

pg = server.db()
lite = sqlite3.connect(src); lite.row_factory = sqlite3.Row
tables = [r[0] for r in lite.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
total = 0
for t in tables:
    rows = lite.execute(f"SELECT * FROM {t}").fetchall()
    if not rows: continue
    pg_cols = {r["name"] for r in pg.execute(f"PRAGMA table_info({t})").fetchall()}
    cols = [c for c in rows[0].keys() if c in pg_cols]
    n_before = pg.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    if n_before:
        print(f"skip {t}: target already has {n_before} rows"); continue
    ph = ",".join("?" for _ in cols)
    for r in rows:
        pg._c.execute(dbcompat.translate(f"INSERT INTO {t}({','.join(cols)}) VALUES({ph})"), tuple(r[c] for c in cols))
    if "id" in cols:
        pg._c.execute(f"SELECT setval(pg_get_serial_sequence('{t}','id'), (SELECT COALESCE(MAX(id),1) FROM {t}))")
    total += len(rows); print(f"{t}: {len(rows)} rows")
pg.commit(); pg.close()
print(f"migrated {total} rows from {src} to PostgreSQL")
