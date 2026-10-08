"""Accuracy on independent background data: import a public dataset, inject labelled schemes + benign look-alikes,
run the full SpotZⁱ pipeline, and score it. Writes data/evaluation/<dataset>.json and prints a scorecard."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

import importers as IM
import inject as INJ
import pipeline as PL

ROOT = Path(__file__).parent


def run(dataset, patients=4000, seed=21):
    ws = ROOT / "data" / "workspaces" / f"{dataset}-eval"
    rep = IM.synpuf(ROOT / "data/external/synpuf", ws, n_benes=patients) if dataset == "synpuf" else IM.synthea(ROOT / "data/external/synthea", ws)
    inj = INJ.inject(ws, seed=seed, n_per_scheme=3 if dataset == "synpuf" else 2, n_benign=4 if dataset == "synpuf" else 3, min_lines=200 if dataset == "synpuf" else 60)
    t = time.time(); S = PL.run_pipeline(data_dir=ws); secs = time.time() - t
    PT, L = S["PT"], S["L"]
    sp = pd.read_csv(ws / "hidden" / "scenario_providers.csv")
    bad = set(sp[sp.scheme != "benign-growth"].provider_id); benign = set(sp[sp.scheme == "benign-growth"].provider_id)
    in_case = {p for c in S["cases"] for p in c["primary"]}
    y = np.array([int(p in bad) for p in PT.index])
    def auc(col): return float(roc_auc_score(y, PT[col].fillna(0)))
    det = {name: auc(col) for name, col in [("Rules", "rule_score"), ("Isolation Forest", "anomaly_pct"), ("Case-mix twin", "twin_pct"), ("Care pathway", "path_pct"),
                                            ("Change-point", "drift_pct"), ("Code mix", "mix_pct"), ("Nexus Brain", "brain"), ("Combined risk", "risk")] if col in PT}
    det_ap = {"Nexus Brain": float(average_precision_score(y, PT["brain"].fillna(0))), "Combined risk": float(average_precision_score(y, PT["risk"].fillna(0)))}
    # ranking of the SIU queue (provider-level truth): precision@k of cases
    import briefs
    q = briefs.rank(S)["queue"]
    prim = {c["case_id"]: c["primary"] for c in S["cases"]}
    hits = [bool(set(prim[r["case_id"]]) & bad) for r in q]
    per = []
    for _, r in sp.iterrows():
        p = r.provider_id
        if p not in PT.index: continue
        per.append(dict(scheme=r.scheme, provider=p, in_case=p in in_case, risk=round(float(PT.at[p, "risk"]), 1), rules=round(float(PT.at[p, "rule_score"]), 2),
                        brain=round(float(PT.at[p, "brain"]), 2), brain_rank=int((PT.brain > PT.at[p, "brain"]).sum() + 1)))
    per = pd.DataFrame(per)
    scheme = per[per.scheme != "benign-growth"].groupby("scheme").agg(providers=("provider", "size"), caught=("in_case", "sum"), median_brain_rank=("brain_rank", "median")).reset_index()
    out = dict(dataset=dataset, import_report=rep, injection=inj, seconds=round(secs, 1), providers=int(len(PT)), lines=int(len(L)),
               cases=len(S["cases"]), bad_caught=int(per[per.scheme != "benign-growth"].in_case.sum()), bad_total=int((per.scheme != "benign-growth").sum()),
               benign_escalated=int(per[per.scheme == "benign-growth"].in_case.sum()), benign_total=int((per.scheme == "benign-growth").sum()),
               precision_at_5=float(np.mean(hits[:5])) if hits else 0, precision_at_10=float(np.mean(hits[:10])) if hits else 0,
               case_precision=float(np.mean(hits)) if hits else 0, line_precision=S["run"]["evaluation"].get("line_precision"), line_recall=S["run"]["evaluation"].get("line_recall"),
               detector_auc=det, detector_ap=det_ap, forecast=S["run"]["forecast_metrics"], forecast_model=S["run"]["model_choice"],
               per_scheme=scheme.to_dict("records"), per_provider=per.to_dict("records"),
               method="Background claims are unmodified public synthetic data; labelled schemes and benign look-alikes were injected; labels used only for scoring.")
    d = ROOT / "data" / "evaluation"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{dataset}.json").write_text(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    for ds in (sys.argv[1:] or ["synthea", "synpuf"]):
        o = run(ds)
        print(f"\n=== {ds}: {o['lines']:,} lines · {o['providers']} providers · {o['cases']} cases · {o['seconds']} s")
        print(f"caught {o['bad_caught']}/{o['bad_total']} injected bad providers · benign look-alikes escalated {o['benign_escalated']}/{o['benign_total']}")
        print(f"queue precision@5 {o['precision_at_5']:.2f} @10 {o['precision_at_10']:.2f} all {o['case_precision']:.2f} · line precision {o['line_precision']} recall {o['line_recall']}")
        print("detector AUC:", {k: round(v, 3) for k, v in o["detector_auc"].items()})
        print("per scheme:", o["per_scheme"])
        print("forecast:", {h: (round(m.get('auc', 0), 3), round(m.get('brier', 0), 3), m.get('positives')) for h, m in o["forecast"].items()}, o["forecast_model"].get("chosen"))
