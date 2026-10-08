"""Case scope editing: human merge / split of system-proposed cases (doc 11: 'an investigator accepts, splits, or merges').
Edits are stored and replayed on every analysis run; retired case IDs keep a pointer to their successor."""
from __future__ import annotations

import json


def schema(c):
    c.executescript("""CREATE TABLE IF NOT EXISTS case_scope(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, target TEXT, other TEXT, providers TEXT,
        new_id TEXT, actor TEXT, role TEXT, reason TEXT, ts TEXT, active INTEGER DEFAULT 1);""")


def edits(c):
    return [dict(r) for r in c.execute("SELECT * FROM case_scope WHERE active=1 ORDER BY id").fetchall()]


def apply(base_cases, edit_rows):
    """Return (groups for build_cases, retired map, problems)."""
    groups = {c["case_id"]: dict(case_id=c["case_id"], primary=list(c["primary"]), providers=list(c["providers"])) for c in base_cases}
    retired, problems = {}, []
    resolve = lambda cid: resolve(retired[cid]) if cid in retired else cid
    for e in edit_rows:
        tgt = resolve(e["target"])
        if tgt not in groups: problems.append(f"edit {e['id']}: case {e['target']} no longer exists"); continue
        if e["kind"] == "merge":
            oth = resolve(e["other"])
            if oth not in groups or oth == tgt: problems.append(f"edit {e['id']}: cannot merge {e['other']}"); continue
            g, o = groups[tgt], groups.pop(oth)
            g["primary"] = sorted(set(g["primary"]) | set(o["primary"])); g["providers"] = sorted(set(g["providers"]) | set(o["providers"]))
            retired[oth] = tgt
        elif e["kind"] == "split":
            move = set(json.loads(e["providers"]))
            g = groups[tgt]
            if not move <= set(g["primary"]) or move == set(g["primary"]): problems.append(f"edit {e['id']}: split must move some, not all, primary providers"); continue
            g["primary"] = sorted(set(g["primary"]) - move); g["providers"] = sorted(set(g["providers"]) - move) or g["primary"]
            groups[e["new_id"]] = dict(case_id=e["new_id"], primary=sorted(move), providers=sorted(move))
    return list(groups.values()), retired, problems


def rebuild(S, c):
    import pipeline as PL
    rows = edits(c)
    if not rows:
        S["cases"] = S["base_cases"]; S["retired"] = {}; S["scope_problems"] = []; return
    groups, retired, problems = apply(S["base_cases"], rows)
    S["cases"] = PL.build_cases(*S["build_ctx"], forced=groups)
    S["retired"] = retired; S["scope_problems"] = problems
