"""Measure the chart reviewer: does it correctly say "documentation does not support the billed service"?
Samples synthetic lines whose truth is known (upcoded E/M, short psychotherapy, phantom services) plus legitimate
look-alikes, renders their synthetic notes, and scores the deterministic reviewer and (with --llm) the LLM reviewer.
Writes data/evaluation/chart_review.json.   Run: python3 evaluate_llm.py [--llm] [--n=30]"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[1]))   # allow `python3 evaluation/x.py` as well as `python3 -m`

import json
import sys
from pathlib import Path

import pandas as pd

from ai import charts as CH
from ai import llm
from ai import llm_detect as LD

ROOT = Path(__file__).resolve().parents[1]


def run(use_llm=False, n=30, seed=5, batch=10):
    L = pd.read_csv(ROOT / "data/synthetic/claim_lines.csv", dtype={"code": str}, low_memory=False)
    t = pd.read_csv(ROOT / "data/hidden/scenario_truth.csv").set_index("line_id")
    L["truth"] = L.line_id.map(t.truth).fillna(False).astype(bool); L["sc"] = L.line_id.map(t.scenario).fillna("")
    em, ps = list(CH.EM_OFFICE), list(CH.PSYCHO)
    groups = {"upcoded E/M": L[L.truth & L.code.isin(["99214", "99215"]) & L.sc.str.contains("upcod")],
              "legitimate E/M (levels 4-5)": L[~L.truth & L.code.isin(["99214", "99215"])],
              "short psychotherapy": L[L.truth & L.code.isin(ps)], "legitimate psychotherapy": L[~L.truth & L.code.isin(ps)],
              "phantom services": L[L.truth & L.sc.str.contains("phantom|dme-hh")]}
    items = []
    for style in ("A", "B"):   # B = wording the deterministic reviewer was never written against
        for g, sub in groups.items():
            for _, r in sub.sample(min(n, len(sub)), random_state=seed).iterrows():
                nt = CH.note(r.to_dict(), r.sc if r.truth else "", style=style)
                items.append(dict(group=g, style=style, line_id=f"{r.line_id}{'' if style == 'A' else '-B'}", code=r.code, note=nt["text"], unsupported=bool(r.truth)))
    res = {"keyword rules": [not LD.review_heuristic(i["code"], i["note"])["supports_billed"] for i in items]}
    from ai.models import registry as MR
    cm = MR.load("chart_documentation")
    if cm is not None: res["trained model"] = [not cm.review(i["code"], i["note"])["supports_billed"] for i in items]
    meta = dict(llm=None)
    if use_llm:
        if not llm.available(): raise SystemExit("No LLM configured (set ANTHROPIC_API_KEY or a local server).")
        preds, engines, dropped = [], [], 0
        for k in range(0, len(items), batch):
            chunk = items[k:k + batch]
            r = LD.chart_review([dict(line_id=i["line_id"], code=i["code"], note=i["note"]) for i in chunk])
            by = {x["line_id"]: x for x in r["rows"]}
            preds += [not by[i["line_id"]]["supports_billed"] for i in chunk]; engines += [by[i["line_id"]]["engine"] for i in chunk]; dropped += r["ungrounded_dropped"]
        res["llm"] = preds; meta = dict(llm=llm.model_name(), llm_answered=sum(e == "llm" for e in engines), ungrounded_dropped=dropped)

    def score(pred):
        return {f"style {st}": score1([p for p, i in zip(pred, items) if i["style"] == st], [i for i in items if i["style"] == st]) for st in ("A", "B")}

    def score1(pred, items):
        y = [i["unsupported"] for i in items]
        tp = sum(p and t for p, t in zip(pred, y)); fp = sum(p and not t for p, t in zip(pred, y)); fn = sum(t and not p for p, t in zip(pred, y))
        per = {}
        for g in groups:
            ix = [k for k, i in enumerate(items) if i["group"] == g]
            if ix: per[g] = round(sum(pred[k] == items[k]["unsupported"] for k in ix) / len(ix), 3)
        return dict(accuracy=round(sum(p == t for p, t in zip(pred, y)) / len(y), 3), precision=round(tp / max(1, tp + fp), 3), recall=round(tp / max(1, tp + fn), 3), per_group=per)
    out = dict(samples=len(items), groups={g: int(sum(i["group"] == g for i in items)) for g in groups}, styles="A = house template wording; B = different clinician wording (unseen by the deterministic reviewer)", **meta, results={k: score(v) for k, v in res.items()},
               method="Synthetic notes rendered by charts.py from hidden truth; reviewers see only note text and billed code. Labels used only for scoring.")
    d = ROOT / "data" / "evaluation"; d.mkdir(parents=True, exist_ok=True)
    prev = json.loads((d / "chart_review.json").read_text()) if (d / "chart_review.json").exists() else {}
    if not use_llm and "llm" in prev.get("results", {}): out["results"]["llm"] = prev["results"]["llm"]; out["llm"] = prev.get("llm")
    (d / "chart_review.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    n = int(next((a.split("=")[1] for a in sys.argv[1:] if a.startswith("--n=")), 30))
    print(json.dumps(run("--llm" in sys.argv, n), indent=1))
