"""SpotZⁱ evaluation engine — model validation that never reaches the investigator UI.

  python3 -m evaluation.engine                 # everything (~20-25 min)
  python3 -m evaluation.engine --quick         # demo world only, fewer perturbation runs
  python3 -m evaluation.engine --sections=truth,counterfactual

Sections
  truth           ground truth at claim, provider, network and type level; queue precision/recall@k; consensus vs truth
  calibration     reliability, ECE, Brier for calibrated fraud probability; capacity tiers and threshold optimisation
  delay           temporal: how many days after a scheme starts is it opened as a case (rolling as-of replays)
  counterfactual  metamorphic tests: change one thing, check the score moves in the expected direction
  adversarial     evasion: weaker / mimicking / split schemes — how much does detection degrade?
  ablation        does each optional detector (temporal, peer baseline) improve the fused ranking?
  gap             robustness gap: distribution shift (PSI) and OOD rate of each world vs the training reference
  quality         data-quality robustness: corrupted data must lower confidence, not inflate it
Hidden labels are used here only. Writes data/evaluation/engine.json."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import average_precision_score, roc_auc_score  # noqa: E402

from detection import baselines as BL  # noqa: E402
from detection import consensus as CS  # noqa: E402
from detection import pipeline as PL  # noqa: E402
from intelligence import briefs  # noqa: E402
from synthdata import truth as TRU  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "synthetic"
OUT = ROOT / "data" / "evaluation" / "engine.json"
ESCALATED = ("Investigate", "Brain lead", "Validate context first")   # surfaced for review (detection counts)
ESCALATED_ACTION = ("Investigate", "Brain lead")                      # recommended for investigation (false-positive counts)
HELDOUT = [201, 202]


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


def truth_of(S) -> pd.DataFrame:
    L = S["L"]
    lt = L.assign(truth=L["_truth"], scenario=L["_scenario"])[["provider_id", "service_date", "paid", "truth", "scenario"]]
    lg = S["T"].get("legit")
    return TRU.build(lt, list(S["PT"].index), lg, exclusions=S["T"].get("exclusions")).set_index("provider_id")


def in_cases(S, lanes=ESCALATED):
    return {p for c in S["cases"] if c["lane"] in lanes for p in c["primary"]}


# ---------------------------------------------------------------- workspace helpers
def workspace(src=DEMO):
    tmp = Path(tempfile.mkdtemp(prefix="spotzi-eval-"))
    shutil.copytree(src, tmp / "synthetic")
    hid = src.parent / "hidden" if not (src / "hidden").exists() else src / "hidden"
    shutil.copytree(hid, tmp / "hidden")
    return tmp / "synthetic"


def run(ws, **kw):
    return PL.run_pipeline(data_dir=ws, **kw)


def lines(ws):
    return pd.read_csv(ws / "claim_lines.csv", dtype={"code": str, "pos": str, "modifier": str, "dx": str, "facility_id": str, "referring_provider_id": str}, low_memory=False)


def hidden_truth(ws):
    return pd.read_csv(ws.parent / "hidden" / "scenario_truth.csv").set_index("line_id")


# ---------------------------------------------------------------- 1. ground truth (claim / provider / network / type)
def truth_metrics(S, name):
    PT = S["PT"]; E = truth_of(S)
    y = (E.true_state.reindex(PT.index) == "fraudulent").astype(int)
    det = {}
    for c in ("risk", "brain", "p_fraud", "outcome_p", "rule_score", "anomaly_pct", "temporal_pct", "peer_pct", "drift_pct", "panel_pct"):
        if c in PT and PT[c].notna().any() and 0 < y.sum() < len(y):
            v = PT[c].fillna(PT[c].min())
            det[c] = dict(auc=round(float(roc_auc_score(y, v)), 3), ap=round(float(average_precision_score(y, v)), 3))
    q = briefs.rank(S, brain=PT.brain)["queue"]
    prim = {c["case_id"]: c["primary"] for c in S["cases"]}
    q = [r for r in q if r["lane"] != "Explained by context"]
    fraud = set(E.index[E.true_state == "fraudulent"])
    def at(k):
        top = q[:k]; hits = [bool(set(prim[r["case_id"]]) & fraud) for r in top]
        found = {p for r in top for p in prim[r["case_id"]]} & fraud
        return dict(precision=round(float(np.mean(hits)), 3) if hits else None, recall=round(len(found) / max(1, len(fraud)), 3))
    esc = in_cases(S)
    # network: rings captured, and captured together
    rings = {}
    for rid, g in E[E.ring_id.notna()].groupby("ring_id"):
        mem = set(g.index); together = max((len(mem & set(c["primary"]) | (mem & set(c["providers"]))) for c in S["cases"]), default=0)
        rings[rid] = dict(members=len(mem), in_cases=len(mem & esc), largest_together=together)
    types = {t: dict(n=int(len(g)), caught=int(sum(p in esc for p in g.index))) for t, g in E[E.true_state == "fraudulent"].groupby("fraud_type")}
    by_state = {}
    for st, g in E.groupby("true_state"):
        idx = [p for p in g.index if p in PT.index]
        esc_a = in_cases(S, ESCALATED_ACTION)
        by_state[st] = dict(n=len(idx), escalated=int(sum(p in (esc if st == "fraudulent" else esc_a) for p in idx)),
                            stage=PT.loc[idx, "stage"].value_counts().to_dict() if "stage" in PT else {},
                            consensus=PT.loc[idx, "consensus"].value_counts().to_dict() if "consensus" in PT else {},
                            mean_independent_families=round(float(PT.loc[idx, "n_families"].mean()), 2) if "n_families" in PT else None)
    cons_prec = {}
    if "consensus" in PT:
        for lab in ("High", "Moderate", "Low"):
            cs = [c for c in S["cases"] if c["lane"] in ESCALATED and (c.get("consensus") or {}).get("consensus") == lab]
            if cs: cons_prec[lab] = dict(cases=len(cs), precision=round(float(np.mean([bool(set(c["primary"]) & fraud) for c in cs])), 3))
    ev = S["run"]["evaluation"]
    out = dict(dataset=name, providers=int(len(PT)), fraudulent=int(y.sum()), cases=len(S["cases"]),
               claim=dict(precision=round(ev.get("line_precision", 0), 3), recall=round(ev.get("line_recall", 0), 3)),
               provider_detectors=det, queue={f"@{k}": at(k) for k in (5, 10, 20)}, rings=rings, fraud_types=types, by_true_state=by_state,
               case_precision_by_consensus=cons_prec)
    log("truth", name, "AUC/AP p_fraud", det.get("p_fraud"), "queue", out["queue"]["@10"])
    return out


# ---------------------------------------------------------------- 2. calibration + thresholds / capacity tiers
def calibration(S, name, bins=10):
    PT = S["PT"]; E = truth_of(S)
    if "p_fraud" not in PT or PT.p_fraud.isna().all(): return None
    y = (E.true_state.reindex(PT.index) == "fraudulent").astype(int).values; p = PT.p_fraud.values
    order = np.argsort(p); chunks = np.array_split(order, bins)
    rel = [dict(mean_predicted=round(float(p[c].mean()), 3), observed=round(float(y[c].mean()), 3), n=int(len(c))) for c in chunks if len(c)]
    ece = float(sum(abs(r["mean_predicted"] - r["observed"]) * r["n"] for r in rel) / len(p))
    # tiers by rank (capacity), not by a hard-coded score threshold
    rk = np.argsort(-p); n = len(p); tiers = {}
    for lab, frac in (("Critical (top 1%)", .01), ("High (top 5%)", .05), ("Review (top 15%)", .15)):
        k = max(1, int(round(n * frac))); sel = rk[:k]
        tiers[lab] = dict(providers=k, threshold=round(float(p[sel].min()), 3), precision=round(float(y[sel].mean()), 3), recall=round(float(y[sel].sum() / max(1, y.sum())), 3),
                          false_positive_rate=round(float(((1 - y[sel]).sum()) / max(1, (1 - y).sum())), 4))
    # operating points: low capacity favours precision (F0.5), high capacity favours recall (F2)
    ops = {}
    for lab, beta in (("low capacity (F0.5)", .5), ("balanced (F1)", 1.0), ("high capacity (F2)", 2.0)):
        best = None
        for k in range(1, min(n, 200) + 1):
            sel = rk[:k]; tp = y[sel].sum(); pr = tp / k; rc = tp / max(1, y.sum())
            f = (1 + beta ** 2) * pr * rc / max(1e-9, beta ** 2 * pr + rc)
            if best is None or f > best[0]: best = (f, k, pr, rc, p[sel].min())
        ops[lab] = dict(review_top_k=int(best[1]), threshold=round(float(best[4]), 3), precision=round(float(best[2]), 3), recall=round(float(best[3]), 3))
    out = dict(dataset=name, brier=round(float(np.mean((p - y) ** 2)), 4), ece=round(ece, 4), reliability=rel, tiers=tiers, operating_points=ops)
    log("calibration", name, "ECE", out["ece"], "tiers", {k: (v["precision"], v["recall"]) for k, v in tiers.items()})
    return out


# ---------------------------------------------------------------- 3. detection delay (rolling as-of replays)
def delay(cutoffs=("2024-10-31", "2024-12-31", "2025-02-28", "2025-04-30", "2025-06-30", "2025-08-31")):
    ws = workspace(); L0 = lines(ws); first_case, first_stage = {}, {}
    E = pd.read_csv(DEMO.parent / "hidden" / "entity_truth.csv").set_index("provider_id")
    fraud = E[E.true_state == "fraudulent"]
    for cut in cutoffs:
        L0[pd.to_datetime(L0.service_date) <= pd.Timestamp(cut)].to_csv(ws / "claim_lines.csv", index=False)
        S = run(ws); esc = in_cases(S)
        for p in fraud.index:
            if p in esc and p not in first_case: first_case[p] = cut
            if p in S["PT"].index and S["PT"].at[p, "stage"] in ("Emerging anomaly", "Sustained anomaly", "Established pattern") and p not in first_stage: first_stage[p] = cut
        log("delay", cut, f"{len(esc & set(fraud.index))}/{len(fraud)} fraud providers escalated")
    rows = []
    for p, r in fraud.iterrows():
        st = pd.Timestamp(r.fraud_start)
        d_case = (pd.Timestamp(first_case[p]) - st).days if p in first_case else None
        d_stage = (pd.Timestamp(first_stage[p]) - st).days if p in first_stage else None
        rows.append(dict(provider_id=p, fraud_type=r.fraud_type, fraud_start=r.fraud_start, first_case_cutoff=first_case.get(p), days_to_case=d_case,
                         first_stage_cutoff=first_stage.get(p), days_to_early_warning=d_stage))
    shutil.rmtree(ws.parent, ignore_errors=True)
    d = [r["days_to_case"] for r in rows if r["days_to_case"] is not None]; w = [r["days_to_early_warning"] for r in rows if r["days_to_early_warning"] is not None]
    return dict(cutoffs=list(cutoffs), providers=rows, median_days_to_case=float(np.median(d)) if d else None, median_days_to_early_warning=float(np.median(w)) if w else None,
                note="Cutoffs are every ~2 months, so delays are upper bounds with 2-month resolution. 'Early warning' = temporal stage ≥ Emerging anomaly.")


# ---------------------------------------------------------------- 4. counterfactual / metamorphic tests
def counterfactual(base):
    E = truth_of(base); PT0 = base["PT"]; rng = np.random.default_rng(3)
    fraud = [p for p in E.index[E.true_state == "fraudulent"] if p in PT0.index]
    legit = [p for p in E.index[E.true_state == "legitimate"] if p in PT0.index and PT0.at[p, "n_lines"] >= 60]
    legit = list(rng.choice(legit, min(8, len(legit)), replace=False))
    lanomaly = list(E.index[E.true_state == "legitimate_anomaly"])
    tests = []

    def perturb(name, change, targets, metric, expect, fn, tol=0.0):
        ws = workspace(); fn(ws); S = run(ws); PT = S["PT"]
        for p in targets:
            if p not in PT.index: continue
            a, b = float(PT0.at[p, metric]), float(PT.at[p, metric])
            ok = (b < a - tol) if expect == "down" else (b > a + tol) if expect == "up" else (abs(b - a) <= tol)
            tests.append(dict(test=name, change=change, provider=p, metric=metric, expected=expect, before=round(a, 3), after=round(b, 3), passed=bool(ok)))
        if name == "add_fake_event":
            esc = in_cases(S); esc0 = in_cases(base)
            for p in [q for q in targets if q in esc0]: tests.append(dict(test=name, change="still escalated after a business event is added", provider=p, metric="escalated", expected="same",
                                                before=True, after=p in esc, passed=p in esc))
        if name == "remove_context":
            esc = in_cases(S); explained0 = {p for c in base["cases"] if c["lane"] == "Explained by context" for p in c["primary"]}
            for p in targets:
                if p in explained0: tests.append(dict(test=name, change="context removed → no longer 'Explained by context'", provider=p, metric="lane", expected="up",
                                                      before="Explained by context", after="escalated" if p in esc else "not escalated", passed=p in esc))
        shutil.rmtree(ws.parent, ignore_errors=True)
        log("counterfactual", name, f"{sum(t['passed'] for t in tests if t['test'] == name)}/{sum(t['test'] == name for t in tests)} passed")

    def remove_fraud(ws):
        L = lines(ws); T = hidden_truth(ws); L[~L.line_id.map(T.truth).fillna(False).astype(bool)].to_csv(ws / "claim_lines.csv", index=False)
    labelled = [p for p in fraud if E.at[p, "truth_lines"] > 0]          # excluded-provider truth is entity-level only (no lines to remove)
    perturb("remove_fraud_lines", "drop the scheme's labelled lines", labelled, "risk", "down", remove_fraud)

    def add_dups(ws):
        L = lines(ws); add = []
        for p in legit:
            s = L[L.provider_id == p].sample(frac=.2, random_state=1).copy()
            s["line_id"] = s.line_id + "D"; s["paid_date"] = (pd.to_datetime(s.paid_date) + pd.Timedelta(days=14)).astype(str); add.append(s)
        pd.concat([L] + add).to_csv(ws / "claim_lines.csv", index=False)
    perturb("inject_duplicates", "resubmit 20% of a clean provider's claims", legit, "risk", "up", add_dups)

    def upcode_off(ws):
        L = lines(ws); T = hidden_truth(ws); m = L.line_id.map(T.scenario).fillna("").str.startswith("S4") & (L.code == "99215")
        L.loc[m, "code"] = "99213"; L.loc[m, "paid"] = L.loc[m, "paid"] * .55; L.to_csv(ws / "claim_lines.csv", index=False)
    s4 = [p for p in fraud if E.at[p, "scheme_id"] == "S4"]
    perturb("revert_upcoding", "bill the true visit level", s4, "rule_score", "down", upcode_off)

    def fake_event(ws):
        ev = pd.read_csv(ws / "provider_events.csv") if (ws / "provider_events.csv").exists() else pd.DataFrame(columns=["event_id", "provider_id", "event_date", "event_type", "detail", "source"])
        new = pd.DataFrame([dict(event_id=f"EVX-{i}", provider_id=p, event_date=E.at[p, "fraud_start"], event_type="location_opened", detail="New location (counterfactual)", source="test")
                            for i, p in enumerate(fraud)])
        pd.concat([ev, new]).to_csv(ws / "provider_events.csv", index=False)
    perturb("add_fake_event", "a business event coincides with the scheme", fraud, "risk", "same", fake_event, tol=1.0)

    def no_context(ws):
        ev = pd.read_csv(ws / "provider_events.csv"); ev[~ev.provider_id.isin(lanomaly)].to_csv(ws / "provider_events.csv", index=False)
    perturb("remove_context", "remove the recorded legitimate event", lanomaly, "brain", "same", no_context, tol=.001)

    rings = [p for p in fraud if pd.notna(E.at[p, "ring_id"])]
    def cut_links(ws):
        P = pd.read_csv(ws / "providers.csv")
        for c in ("org_id", "address_id", "bank_id"): P.loc[P.provider_id.isin(rings), c] = P.loc[P.provider_id.isin(rings), c] + "-" + P.provider_id
        P.to_csv(ws / "providers.csv", index=False)
        r = pd.read_csv(ws / "relationships.csv"); r[~r.entity_a.isin(rings)].to_csv(ws / "relationships.csv", index=False)
    perturb("cut_network_links", "remove shared ownership / address / bank links", rings, "graph_score", "down", cut_links, tol=-1e-9)

    def scale_legit(ws):
        L = lines(ws); M = pd.read_csv(ws / "members.csv"); add = []
        for p in legit:
            s = L[L.provider_id == p].copy()          # same mix = the same kind of patients again: clone each patient as a new member
            s["member_id"] = s.member_id + "-N"; s["line_id"] = s.line_id + "V"; s["claim_id"] = s.claim_id + "V"; add.append(s)
        clones = M[M.member_id.isin(pd.concat(add).member_id.str[:-2])].copy(); clones["member_id"] = clones.member_id + "-N"
        pd.concat([M, clones]).to_csv(ws / "members.csv", index=False)
        pd.concat([L] + add).to_csv(ws / "claim_lines.csv", index=False)
    perturb("double_clean_volume", "double a clean provider's volume with the same mix", legit, "rule_score", "same", scale_legit, tol=.05)
    by = {}
    for t in tests: by.setdefault(t["test"], []).append(t["passed"])
    return dict(summary={k: dict(passed=int(sum(v)), total=len(v)) for k, v in by.items()}, pass_rate=round(float(np.mean([t["passed"] for t in tests])), 3), tests=tests)


# ---------------------------------------------------------------- 5. adversarial evasion
def adversarial():
    out = []; E = pd.read_csv(DEMO.parent / "hidden" / "entity_truth.csv").set_index("provider_id"); fraud = list(E.index[E.true_state == "fraudulent"])
    for keep in (1.0, .5, .25, .1):
        ws = workspace(); L = lines(ws); T = hidden_truth(ws); tr = L.line_id.map(T.truth).fillna(False).astype(bool)
        drop = L[tr].sample(frac=1 - keep, random_state=4).index if keep < 1 else []
        L.drop(index=drop).to_csv(ws / "claim_lines.csv", index=False)
        S = run(ws); esc = in_cases(S)
        out.append(dict(attack=f"scheme intensity {int(keep * 100)}%", detected=int(sum(p in esc for p in fraud)), of=len(fraud),
                        by_type={t: f"{sum(p in esc for p in g.index)}/{len(g)}" for t, g in E.loc[fraud].groupby("fraud_type")}))
        shutil.rmtree(ws.parent, ignore_errors=True); log("adversarial", out[-1]["attack"], out[-1]["detected"], "/", len(fraud))
    # mimicry: upcoders bill level 4 instead of 5 (stays inside the 'normal' level-5 rule)
    ws = workspace(); L = lines(ws); T = hidden_truth(ws); m = L.line_id.map(T.scenario).fillna("").str.startswith("S4") & (L.code == "99215")
    L.loc[m, "code"] = "99214"; L.to_csv(ws / "claim_lines.csv", index=False); S = run(ws); esc = in_cases(S)
    s4 = [p for p in fraud if E.at[p, "scheme_id"] == "S4"]
    out.append(dict(attack="mimicry: upcode to level 4 instead of 5", detected=int(sum(p in esc for p in s4)), of=len(s4),
                    note="Level-5 rule no longer fires; learned detectors must carry it")); shutil.rmtree(ws.parent, ignore_errors=True)
    log("adversarial", out[-1])
    # split: move half of each scheme's lines to a cloned billing identity (same owner/address/bank)
    ws = workspace(); L = lines(ws); T = hidden_truth(ws); P = pd.read_csv(ws / "providers.csv")
    tr = L.line_id.map(T.truth).fillna(False).astype(bool); sel = L[tr].sample(frac=.5, random_state=6).index
    L.loc[sel, "provider_id"] = L.loc[sel, "provider_id"] + "B"
    clones = P[P.provider_id.isin(fraud)].copy(); clones["provider_id"] = clones.provider_id + "B"; clones["name"] = clones.name + " (2)"; clones["npi"] = clones.npi.astype(str) + "9"
    pd.concat([P, clones]).to_csv(ws / "providers.csv", index=False); L.to_csv(ws / "claim_lines.csv", index=False)
    if (ws / "relationships.csv").exists(): (ws / "relationships.csv").unlink()     # re-derived from master data (clones share org/address/bank)
    S = run(ws); esc = in_cases(S)
    det = sum((p in esc) or (p + "B" in esc) for p in fraud)
    merged = S["run"].get("entity_aliases") or {}
    linked = sum((merged.get(p + "B") == p) or any((p in c["providers"]) and (p + "B" in c["providers"]) for c in S["cases"]) for p in fraud)
    out.append(dict(attack="split billing across a second identity (shared owner/address/bank)", detected=int(det), of=len(fraud), both_identities_in_one_case=int(linked), note="entity resolution merges identities sharing owner, address and bank account"))
    shutil.rmtree(ws.parent, ignore_errors=True); log("adversarial", out[-1])
    return out


# ---------------------------------------------------------------- 6. ablation of optional detectors
def ablation(datasets):
    variants = {"base": [], "+temporal": ["temporal"], "+peer": ["peer"], "+temporal+peer": ["temporal", "peer"]}
    res = {}
    for name, ws in datasets.items():
        for v, extra in variants.items():
            S = run(ws, extra_detectors=extra); PT = S["PT"]; E = truth_of(S)
            y = (E.true_state.reindex(PT.index) == "fraudulent").astype(int); fraud = set(E.index[E.true_state == "fraudulent"])
            leads = [c for c in S["cases"] if c["lane"] in ESCALATED_ACTION]
            res.setdefault(name, {})[v] = dict(brain_auc=round(float(roc_auc_score(y, PT.brain)), 3), brain_ap=round(float(average_precision_score(y, PT.brain)), 3),
                                               cases=len(S["cases"]), caught=int(len(fraud & in_cases(S))), of=len(fraud),
                                               false_leads=int(sum(not (set(c["primary"]) & fraud) for c in leads)),
                                               legit_escalated=int(sum(E.at[p, "true_state"] != "fraudulent" for p in in_cases(S, ESCALATED_ACTION) if p in E.index)))
            log("ablation", name, v, res[name][v])
    mean_ap = {v: round(float(np.mean([res[d][v]["brain_ap"] for d in res])), 3) for v in variants}
    fl = {v: sum(res[d][v]["false_leads"] for d in res) for v in variants}
    caught = {v: sum(res[d][v]["caught"] for d in res) for v in variants}
    best = max(variants, key=lambda v: (caught[v] - fl[v], mean_ap[v]))
    return dict(results=res, mean_brain_ap=mean_ap, total_false_leads=fl, total_caught=caught, chosen=best,
                rule="Choose the variant with the most fraud caught minus false leads across datasets; ties → higher mean AP.")


# ---------------------------------------------------------------- 7. synthetic-to-real gap
def gap(runs):
    from ai.models import registry as MR
    ref = MR.load("reference_profile")
    prof = {}
    for name, S in runs.items():
        L = S["L"]; end = L.service_date.max(); W = L[L.service_date > end - pd.Timedelta(days=PL.LOOKBACK)]
        f = BL.features(W); prof[name] = f[f.n_lines >= 15][list(BL.METRICS)]
    base = "demo world"
    out = {}
    for name, f in prof.items():
        psi = {m: round(CS.psi(np.log1p(f[m].clip(lower=0).dropna()), np.log1p(prof[base][m].clip(lower=0).dropna())) or 0, 3) for m in BL.METRICS}
        oodr = float(runs[name]["PT"].ood.fillna(False).mean()) if "ood" in runs[name]["PT"] else None
        out[name] = dict(psi_vs_demo=psi, shifted_features=[BL.METRICS[k] for k, v in psi.items() if v >= .25], ood_rate=round(oodr, 3) if oodr is not None else None,
                         drift_vs_training=runs[name]["run"].get("monitoring"))
    return dict(reference_providers=ref["n"] if ref else None, datasets=out,
                reading="Features with PSI ≥ 0.25 are synthetic assumptions that do not hold on the other data; models relying on them need re-validation there. "
                        "OOD rate = share of providers the models have never seen anything like (confidence is capped for them).")


# ---------------------------------------------------------------- 8. data-quality robustness
def quality(base):
    E = truth_of(base); rng = np.random.default_rng(8)
    cand = [p for p in base["PT"].index if base["PT"].at[p, "n_lines"] >= 60]
    fr = [p for p in cand if E.at[p, "true_state"] == "fraudulent"][:4]; lg = list(rng.choice([p for p in cand if E.at[p, "true_state"] == "legitimate"], 6, replace=False))
    hit = fr + lg
    ws = workspace(); L = lines(ws); m = L.provider_id.isin(hit)
    idx = L[m].index; r = rng.random(len(idx))
    L.loc[idx[r < .6], "dx"] = None
    L.loc[idx[(r >= .6) & (r < .7)], "code"] = "X9999"
    bad = idx[(r >= .7) & (r < .8)]
    L.loc[bad, "paid_date"] = (pd.to_datetime(L.loc[bad, "service_date"]) - pd.Timedelta(days=5)).astype(str)
    L.to_csv(ws / "claim_lines.csv", index=False)
    S = run(ws); PT, PT0 = S["PT"], base["PT"]
    rows = [dict(provider=p, true_state=E.at[p, "true_state"], dq_before=round(float(PT0.at[p, "dq"]), 3), dq_after=round(float(PT.at[p, "dq"]), 3),
                 consensus_before=PT0.at[p, "consensus"], consensus_after=PT.at[p, "consensus"], risk_before=round(float(PT0.at[p, "risk"]), 1), risk_after=round(float(PT.at[p, "risk"]), 1)) for p in hit]
    shutil.rmtree(ws.parent, ignore_errors=True)
    return dict(corrupted_providers=len(hit), rows=rows,
                confidence_never_high=all(r["consensus_after"] != "High" for r in rows), dq_dropped=all(r["dq_after"] < r["dq_before"] for r in rows),
                legit_risk_inflated=int(sum(r["risk_after"] > r["risk_before"] + 10 for r in rows if r["true_state"] != "fraudulent")))


def main(sections=None, quick=False):
    sec = set(sections or ["truth", "calibration", "delay", "counterfactual", "adversarial", "ablation", "gap", "quality"])
    res = json.loads(OUT.read_text()) if OUT.exists() else {}
    log("demo world"); demo = run(DEMO)
    runs = {"demo world": demo}
    pub = {}
    for seed in ([] if quick else HELDOUT):     # independent held-out synthetic worlds (different generator seeds, never trained on)
        d = ROOT / "data" / "training" / f"world-{seed}" / "synthetic"
        if not (d / "claim_lines.csv").exists():
            from synthdata import gen as G; G.generate(seed=seed, n_members=2500, out_dir=d)
        pub[f"held-out world {seed}"] = d
        if sec & {"truth", "calibration", "gap"}: log("held-out world", seed); runs[f"held-out world {seed}"] = run(d)
    if "truth" in sec: res["truth"] = [truth_metrics(S, n) for n, S in runs.items()]
    if "calibration" in sec: res["calibration"] = [c for c in (calibration(S, n) for n, S in runs.items()) if c]
    if "gap" in sec: res["gap"] = gap(runs)
    if "quality" in sec: res["quality"] = quality(demo)
    if "counterfactual" in sec: res["counterfactual"] = counterfactual(demo)
    if "adversarial" in sec: res["adversarial"] = adversarial()
    if "delay" in sec: res["delay"] = delay()
    if "ablation" in sec: res["ablation"] = ablation({"demo world": DEMO, **({} if quick else pub)})
    res["generated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    OUT.parent.mkdir(parents=True, exist_ok=True); OUT.write_text(json.dumps(res, indent=1, default=str))
    log("written", OUT)
    return res


if __name__ == "__main__":
    s = next((a.split("=", 1)[1].split(",") for a in sys.argv[1:] if a.startswith("--sections=")), None)
    main(s, "--quick" in sys.argv)
