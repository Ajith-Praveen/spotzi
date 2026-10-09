"""Tamper-evident audit chain and hashed investigation policy.

Every audit row gets a chain entry: hash = SHA-256(previous hash | canonical row | policy version). Altering,
deleting or re-ordering any audited row breaks the chain from that row on, and ``verify`` names the first bad entry.
The policy (rules, priority weights, gates) is hashed, so each entry also records which policy was in force.
"""

from __future__ import annotations

import hashlib
import json
import threading

GENESIS = "0" * 64
LOCK = threading.Lock()  # one writer at a time keeps the chain linear


def schema(c):
    c.executescript(
        "CREATE TABLE IF NOT EXISTS audit_chain(audit_id INTEGER PRIMARY KEY, prev_hash TEXT, hash TEXT, policy TEXT);"
    )


def policy():
    """The investigation policy actually enforced by the code, as one canonical, hashable document."""
    from detection.rules import RULES, RULESET_VERSION
    from intelligence import briefs

    doc = dict(
        ruleset=RULESET_VERSION,
        rules={k: dict(name=v["name"], severity=v["severity"], weight=v["weight"]) for k, v in sorted(RULES.items())},
        priority_weights=dict(sorted(briefs.DEFAULT_WEIGHTS.items())),
        gates=dict(
            rationale_min_chars=15,
            referral_readiness_bar=70,
            referral_needs_second_person=True,
            needs_more_data_cannot_be_referred=True,
            model_outputs_cannot_authorise_actions=True,
        ),
    )
    h = hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return dict(version="policy-" + h[:12], sha256=h, document=doc)


def _row_hash(prev, row, pol):
    payload = json.dumps(
        [row["id"], row["ts"], row["actor"], row["role"], row["action"], row["target"], row["detail"] or "", pol],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256((prev + "|" + payload).encode()).hexdigest()


def _head(c):
    r = c.execute("SELECT audit_id, hash FROM audit_chain ORDER BY audit_id DESC LIMIT 1").fetchone()
    return (r["audit_id"], r["hash"]) if r else (0, GENESIS)


def seal(c, pol_version=None):
    """Chain every audit row newer than the chain head (called after each audit insert, and once at start-up)."""
    pol_version = pol_version or policy()["version"]
    last_id, prev = _head(c)
    rows = c.execute("SELECT * FROM audit WHERE id > ? ORDER BY id", (last_id,)).fetchall()
    for r in rows:
        r = dict(r)
        h = _row_hash(prev, r, pol_version)
        c.execute(
            "INSERT INTO audit_chain(audit_id, prev_hash, hash, policy) VALUES(?,?,?,?)",
            (r["id"], prev, h, pol_version),
        )
        prev = h
    return len(rows)


def verify(c):
    """Recompute the whole chain. Returns ok, entry count, the first broken entry (if any) and the head hash."""
    audit = {r["id"]: dict(r) for r in c.execute("SELECT * FROM audit ORDER BY id").fetchall()}
    chain = [dict(r) for r in c.execute("SELECT * FROM audit_chain ORDER BY audit_id").fetchall()]
    prev = GENESIS
    for e in chain:
        row = audit.pop(e["audit_id"], None)
        if row is None:
            return dict(
                ok=False, entries=len(chain), first_bad=dict(audit_id=e["audit_id"], reason="audit row deleted")
            )
        if e["prev_hash"] != prev:
            return dict(
                ok=False,
                entries=len(chain),
                first_bad=dict(audit_id=e["audit_id"], reason="chain link broken (row removed or re-ordered)"),
            )
        if _row_hash(prev, row, e["policy"]) != e["hash"]:
            return dict(
                ok=False,
                entries=len(chain),
                first_bad=dict(audit_id=e["audit_id"], reason="audit row altered after it was written"),
            )
        prev = e["hash"]
    unsealed = sorted(audit)
    head_id = chain[-1]["audit_id"] if chain else 0
    early = [i for i in unsealed if i < head_id]
    if early:
        return dict(
            ok=False,
            entries=len(chain),
            first_bad=dict(audit_id=early[0], reason="audit row inserted outside the chain"),
        )
    return dict(ok=True, entries=len(chain), unsealed=len(unsealed), head=prev, first_bad=None)
