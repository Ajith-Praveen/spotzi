"""Live tamper-detection demo on the real audit log — nothing is changed.

    python3 -m scripts.audit_tamper_demo

1. verifies the chain, 2. alters the newest audit row inside a transaction, 3. verifies again (the alteration is
caught and the exact entry named), 4. rolls the transaction back, 5. verifies once more.
"""

from api import app as server
from infra import ledger


def show(step, r):
    if r["ok"]:
        print(f"{step}: chain VALID  ·  {r['entries']} entries  ·  head {r['head'][:16]}…")
    else:
        print(f"{step}: TAMPERING DETECTED  ·  audit entry #{r['first_bad']['audit_id']}: {r['first_bad']['reason']}")


def main():
    c = server.db()
    print("Policy in force:", ledger.policy()["version"])
    show("1 · before", ledger.verify(c))
    row = c.execute("SELECT id, actor, action, detail FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        print("No audit entries yet — use the app first.")
        return
    print(f"2 · altering entry #{row['id']} ({row['actor']} · {row['action']}) inside a transaction…")
    c.execute("UPDATE audit SET detail=? WHERE id=?", ("edited after the fact", row["id"]))
    show("3 · after edit", ledger.verify(c))
    c.rollback()
    show("4 · after rollback", ledger.verify(c))
    c.close()


if __name__ == "__main__":
    main()
