"""End-to-end SpotZ^i pipeline: load → validate → detect → connect → forecast → rank → brief."""
from __future__ import annotations

import time
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

import sys
import analytics as A
import gen
sys.path.insert(0, str(Path(__file__).parent / "kaggle_model"))
import transfer as KT
from rules import RULES, RULESET_VERSION, apply_rules

ROOT = Path(__file__).parent
DATA = ROOT / "data" / "synthetic"
LOOKBACK = 180
PRIMARY_RISK = 35
MODEL_VERSION = "nexus-models-1.0"


# ---------------------------------------------------------------- load + validate
def load_tables(data_dir=DATA):
    d = Path(data_dir)
    t = {}
    t["lines"] = pd.read_csv(d / "claim_lines.csv", dtype={"code": str, "pos": str, "modifier": str}, parse_dates=["service_date", "service_end_date", "paid_date"])
    t["providers"] = pd.read_csv(d / "providers.csv").fillna({"context_note": ""})
    t["members"] = pd.read_csv(d / "members.csv", parse_dates=["enroll_date", "term_date", "death_date"])
    t["referrals"] = pd.read_csv(d / "referrals.csv")
    t["relationships"] = pd.read_csv(d / "relationships.csv")
    t["investigations"] = pd.read_csv(d / "investigations.csv")
    t["stays"] = pd.read_csv(d / "inpatient_stays.csv", parse_dates=["admit_date", "discharge_date"])
    t["facilities"] = pd.read_csv(d / "facilities.csv")
    tp = d.parent / "hidden" / "scenario_truth.csv"
    t["truth"] = pd.read_csv(tp) if tp.exists() else None
    return t


def validate(t) -> dict:
    L, P, M = t["lines"], t["providers"], t["members"]
    checks, errors, warnings = [], [], []

    def chk(name, ok, detail, critical=False):
        checks.append(dict(name=name, status="pass" if ok else ("fail" if critical else "warn"), detail=detail))
        if not ok: (errors if critical else warnings).append(f"{name}: {detail}")

    chk("Required columns present", {"line_id", "member_id", "provider_id", "service_date", "code", "paid"} <= set(L.columns), "claim_lines.csv schema", True)
    chk("Unique line_id", L.line_id.is_unique, f"{L.line_id.duplicated().sum()} duplicates", True)
    fk_p = L.provider_id.isin(P.provider_id).mean(); fk_m = L.member_id.isin(M.member_id).mean()
    chk("Provider foreign key", fk_p == 1, f"{fk_p * 100:.2f}% of lines resolve to providers.csv", True)
    chk("Member foreign key", fk_m == 1, f"{fk_m * 100:.2f}% of lines resolve to members.csv", True)
    chk("Non-negative paid amounts", (L.paid >= 0).all(), f"{(L.paid < 0).sum()} negative", True)
    chk("Service dates in range", L.service_date.between("2023-01-01", "2026-01-01").all(), f"{L.service_date.min():%Y-%m-%d} → {L.service_date.max():%Y-%m-%d}")
    chk("Paid date after service date", (L.paid_date >= L.service_end_date).mean() > .99, f"{(L.paid_date < L.service_end_date).sum()} violations")
    dx_null = L.dx.isna().mean(); chk("Diagnosis completeness", dx_null < .05, f"{dx_null * 100:.1f}% of lines lack a diagnosis code")
    ref_cov = L.referring_provider_id.notna().mean(); chk("Referral coverage", ref_cov > .1, f"{ref_cov * 100:.1f}% of lines carry a referring provider")
    dur_cov = (L.duration_min > 0).mean(); chk("Documented-time coverage", dur_cov > .15, f"{dur_cov * 100:.1f}% of lines have documented minutes; timing rules cover only these")
    chk("Hidden labels isolated", True, "Scenario truth is stored outside synthetic/ and used only for evaluation and forecast labels")
    return dict(checks=checks, errors=errors, warnings=warnings, rows={k: int(len(v)) for k, v in t.items() if v is not None},
                coverage=dict(dx_missing=float(dx_null), referral=float(ref_cov), documented_time=float(dur_cov)),
                period=dict(start=str(L.service_date.min().date()), end=str(L.service_date.max().date())))


# ---------------------------------------------------------------- helpers
def pct(x): return float(np.clip(x, 0, 1))


def case_type(rules, fams, network):
    if not rules: return "Multi-signal anomaly"
    r = set(rules)
    if "LAB" in fams and r & {"UNBUNDLE", "REPEAT"}: return "Laboratory billing pattern" + (" in a referral network" if network else "")
    if {"DME", "HH"} & set(fams) and "PHANTOM" in r and network: return "Equipment / home-health services not plausibly rendered"
    return {"PHANTOM": "Services not plausibly rendered", "TIMING": "Impossible timing and excessive utilization",
            "UPCODE": "Upcoding / level mismatch", "DUP": "Duplicate billing", "REPEAT": "Repeat services / early refills",
            "UNBUNDLE": "Unbundling", "EXCESS": "Excessive utilization"}[rules[0]]


ACTIONS = {
    "PHANTOM": "Verify proof of delivery or visit notes for the flagged dates and confirm stay and eligibility dates with source systems.",
    "TIMING": "Request clinician schedules and sign-in records for the flagged days; confirm rendering-provider identifiers.",
    "UNBUNDLE": "Request laboratory accession and specimen records to test whether components were separate draws.",
    "REPEAT": "Request clinical indication and specimen / prescriber records for the repeated services.",
    "UPCODE": "Pull a sample of charts and compare documented complexity and time with the billed level.",
    "DUP": "Compare submission timestamps and remittance records for paired lines; check for corrected-claim resubmissions.",
    "EXCESS": "Review treatment plans and medical-necessity documentation; confirm member received services.",
}


def run_pipeline(data_dir=DATA, seed=None, n_members=2500, progress=None):
    log = []
    t0 = time.time()

    def step(name, detail=""):
        log.append(dict(step=name, seconds=round(time.time() - t0, 1), detail=detail))
        if progress: progress(name)

    if seed is not None:
        gen.generate(seed=seed, n_members=n_members, out_dir=data_dir)
        step("Generate synthetic data", f"seed={seed}, members={n_members}")
    T = load_tables(data_dir)
    val = validate(T)
    step("Load + validate", f"{sum(val['rows'].values()):,} rows across {len(val['rows'])} tables; {len(val['warnings'])} warnings")
    if val["errors"]:
        raise ValueError("Data validation failed: " + "; ".join(val["errors"]))
    END = T["lines"].service_date.max()
    P, M = T["providers"], T["members"]
    prov_family = P.set_index("provider_id").family.to_dict()

    # ---- detect (rules) ----
    L, F, detail = apply_rules(T["lines"], M, T["stays"], P)
    L = A.prepare_flags(L, F)
    L["claim_anomaly"] = A.claim_anomaly(L)
    step("Rules + claim anomaly", f"{int(L.any_flag.sum()):,} flagged lines of {len(L):,}; ruleset {RULESET_VERSION}")

    ties = A.ownership_ties(T["relationships"])
    truth_lines = None
    if T["truth"] is not None:
        tr = T["truth"].set_index("line_id")
        L["_truth"] = L.line_id.map(tr.truth).fillna(False).astype(bool)
        L["_scenario"] = L.line_id.map(tr.scenario).fillna("")
        truth_lines = L[L._truth][["provider_id", "service_date"]]
    prov_ids = list(P.provider_id)
    panel, snaps = A.build_panel(L, prov_ids, ties, T["investigations"], END, truth_lines)
    X_end = panel[panel.snap == END].set_index("provider_id")
    step("Feature panel", f"{len(panel):,} provider-snapshots × {len(A.FEATURES)} features")

    # ---- anomaly ----
    apct, araw, adrivers = A.anomaly_scores(X_end, prov_family)
    step("Isolation Forest", "provider anomaly percentile within family peers")

    # ---- forecast ----
    fc = A.train_forecasts(panel, prov_family, truth_lines if truth_lines is not None else pd.DataFrame(columns=["provider_id", "service_date"]), END)
    step("Forecast models", f"discrete-time hazard · chosen {fc['model_choice']['chosen']} · purged temporal holdout")

    # ---- provider table (lookback window) ----
    W = L[L.service_date > END - pd.Timedelta(days=LOOKBACK)]
    g = W.groupby("provider_id")
    PT = P.set_index("provider_id").copy()
    PT["n_lines"] = g.size().reindex(PT.index).fillna(0)
    PT["paid"] = g.paid.sum().reindex(PT.index).fillna(0)
    PT["members"] = g.member_id.nunique().reindex(PT.index).fillna(0)
    PT["flagged_lines"] = g.any_flag.sum().reindex(PT.index).fillna(0)
    PT["flagged_paid"] = g.flag_paid.sum().reindex(PT.index).fillna(0)
    PT["any_share"] = (PT.flagged_lines / PT.n_lines.clip(lower=1))
    for k in RULES:
        PT[f"s_{k}"] = g[f"f_{k}"].mean().reindex(PT.index).fillna(0)
        PT[f"n_{k}"] = g[f"f_{k}"].sum().reindex(PT.index).fillna(0)
    # rule score (volume-guarded)
    def rscore(r):
        prod = 1.0
        for k, spec in RULES.items():
            s = min(1.0, r[f"s_{k}"] / .06) * min(1.0, r[f"n_{k}"] / 8)
            prod *= (1 - .8 * s * min(1.0, spec["severity"] + .2))
        return 1 - prod
    PT["rule_score"] = PT.apply(rscore, axis=1)
    PT["anomaly_pct"] = apct.reindex(PT.index)
    PT["ref_conc"] = X_end.ref_conc.reindex(PT.index).fillna(0)

    # ---- graph ----
    prelim = (PT.rule_score * 100).to_dict()
    G, ref = A.build_graph(L, P, T["relationships"], prelim, END)
    H = A.tie_graph(G, PT.rule_score.to_dict())
    gs = {}
    for p in PT.index:
        s = 0.0
        if PT.at[p, "ref_conc"] >= .6: s = max(s, .4)
        else: s = max(s, PT.at[p, "ref_conc"] * .5)
        for q in (H[p] if p in H else []):
            kinds = set(H[p][q]["kinds"]); qr = PT.at[q, "rule_score"]
            if kinds & {"ownership", "address", "bank"}:
                s = max(s, .9 if qr >= .35 else .2)
            if "referral" in kinds: s = max(s, .7 if qr >= .35 else .25)
            if "shared_members" in kinds: s = max(s, .6 if qr >= .35 else .2)
        gs[p] = s
    PT["graph_score"] = pd.Series(gs)
    aadj = ((PT.anomaly_pct - .5) / .5).clip(0, 1)
    PT["risk"] = (100 * (.55 * PT.rule_score + .20 * aadj + .25 * PT.graph_score)).clip(0, 100)
    # low-volume guard: no case from tiny providers
    PT.loc[PT.n_lines < 15, "risk"] *= .5
    for h in (30, 60, 90):
        PT[f"fc{h}"] = pd.Series({p: v.get(h, 0) for p, v in fc["pred"].items()})
    PT["escalation"] = X_end.escalation.reindex(PT.index).fillna(0)
    PT["flag_paid30"] = X_end.flag_paid30.reindex(PT.index).fillna(0)
    own_metrics = None
    PT["own_model"] = np.nan
    if KT.available():
        try:
            sc, _ = KT.score(L, M, P)
            PT["own_model"] = sc.reindex(PT.index)
            own_metrics = KT.metrics()
            step("Own model (Kaggle-trained)", f"scored {int(PT.own_model.notna().sum())} providers; CV AUC {own_metrics['auc_ensemble']:.2f} on Kaggle data" if own_metrics else "scored")
        except Exception as e:
            step("Own model (Kaggle-trained)", f"skipped: {type(e).__name__}: {str(e)[:80]}")
    else:
        step("Own model (Kaggle-trained)", "not trained yet: see kaggle_model/README.md")
    comms = A.communities(G)
    step("Graph analytics", f"{G.number_of_nodes()} providers, {G.number_of_edges()} relationships, {len(comms)} communities")

    # ---- cases ----
    cases = build_cases(L, PT, G, H, T, detail, fc, adrivers, END, ties)
    step("Case construction", f"{len(cases)} cases from {int(L.any_flag.sum()):,} flagged lines")

    # ---- evaluation vs hidden truth ----
    ev = evaluate(L, PT, cases, fc, T)
    step("Evaluation on synthetic truth", "precision@k, recall, forecast metrics")

    # ---- network explorer payload ----
    net = network_payload(G, H, PT, comms, L)
    run = dict(run_id=f"RUN-{time.strftime('%Y%m%d-%H%M%S')}", as_of=str(END.date()), created=time.strftime("%Y-%m-%d %H:%M:%S"),
               ruleset=RULESET_VERSION, model=MODEL_VERSION, seed=seed, log=log, validation=val, evaluation=ev, forecast_metrics=fc["metrics"],
               calibration=fc["calibration"], model_choice=fc["model_choice"], seconds=round(time.time() - t0, 1))
    run["own_model"] = own_metrics
    return dict(run=run, L=L, F=F, detail=detail, PT=PT, cases=cases, G=G, H=H, T=T, net=net, fc=fc, adrivers=adrivers, comms=comms, X_end=X_end)


# ---------------------------------------------------------------- case construction
def build_cases(L, PT, G, H, T, detail, fc, adrivers, END, ties):
    W = L[L.service_date > END - pd.Timedelta(days=LOOKBACK)]
    primary = set(PT.index[PT.risk >= PRIMARY_RISK])
    groups, seen = [], set()
    for comp in nx.connected_components(H):
        pr = comp & primary
        if not pr: continue
        comp = set(pr) | {n for p in pr for n in H[p]}
        groups.append((sorted(pr), sorted(comp))); seen |= pr
    for p in sorted(primary - seen):
        groups.append(([p], [p]))
    cases = []
    inv = T["investigations"]
    for prim, comp in groups:
        sub = W[W.provider_id.isin(prim) & W.any_flag]
        if sub.empty: continue
        fam = sorted({PT.at[p, "family"] for p in prim})
        rule_counts = {k: int(sub[f"f_{k}"].sum()) for k in RULES if sub[f"f_{k}"].sum() > 0}
        rule_paid = {k: float(sub.loc[sub[f"f_{k}"], "paid"].sum()) for k in rule_counts}
        exposure = float(sub.paid.sum())
        members = sub.member_id.nunique()
        mv = T["members"].set_index("member_id").vulnerable.reindex(sub.member_id.unique()).fillna(False)
        n_vuln = int(mv.sum())
        sev_w = {k: RULES[k]["severity"] for k in rule_counts}
        severity = 100 * (max(sev_w.values()) * .7 + np.average(list(sev_w.values()), weights=[rule_paid[k] + 1 for k in sev_w]) * .3)
        prov_all = W[W.provider_id.isin(prim)]
        dx_missing = float(prov_all.dx.isna().mean()); ref_missing = float(prov_all.referring_provider_id.isna().mean())
        anomalous = max(PT.at[p, "anomaly_pct"] for p in prim) >= .9
        has_graph = len(comp) > 1 and max(PT.at[p, "graph_score"] for p in prim) >= .5
        escal = max(PT.at[p, "escalation"] for p in prim) > .5 and max(PT.at[p, "flag_paid30"] for p in prim) > 1500
        signals = int(len(rule_counts) > 0) + int(anomalous) + int(has_graph) + int(escal)
        ev = 12 * signals + (14 if len(rule_counts) >= 2 else 4 if rule_counts else 0) + 24 * min(1, len(sub) / 40) \
            + 10 * (1 - dx_missing) + (8 if sub.claim_anomaly.mean() > .85 else 0) + (8 if any(PT.at[p, "n_lines"] >= 60 for p in prim) else 0)
        ev += 12 if any(sev_w.get(k, 0) >= .95 and rule_counts[k] >= 5 for k in rule_counts) else 0
        prior_conf = int(inv[inv.provider_id.isin(prim) & inv.outcome.str.startswith("Confirmed")].shape[0])
        ev += 6 * min(prior_conf, 1)
        ctx = [PT.at[p, "context_note"] for p in prim if PT.at[p, "context_note"]]
        benign_ctx = bool(ctx) and not has_graph
        if benign_ctx: ev -= 22
        ev = float(np.clip(ev, 5, 98))
        risk = float(max(PT.at[p, "risk"] for p in prim))
        fcs = {h: float(max(PT.at[p, f"fc{h}"] for p in prim)) for h in (30, 60, 90)}
        why = {}
        for h in (30, 60, 90):
            top = max(prim, key=lambda p: PT.at[p, f"fc{h}"])
            why[h] = fc["why"].get(top, {}).get(h, [])
        flagged_lines = int(len(sub))
        effort = float(np.round(8 + 7 * len(prim) + 1.4 * np.sqrt(flagged_lines) + 0.09 * members, 1))
        top_prov = max(prim, key=lambda p: PT.at[p, "risk"])
        pid_num = min(int(p.split("-")[1]) for p in prim)
        net = len(comp) > 1
        title = PT.at[top_prov, "name"] + (f" + {len(comp) - 1} linked" if net else "")
        rules_sorted = sorted(rule_counts, key=lambda k: -rule_paid[k])
        ctype = case_type(rules_sorted, fam, net)
        cid = f"CS-{pid_num:04d}"
        lane = "Investigate"
        if ev < 35: lane = "Needs more data"
        elif benign_ctx and ev < 60: lane = "Validate context first"
        cases.append(dict(
            case_id=cid, title=title, type=ctype, primary=prim, providers=comp, families=fam, network=net,
            risk=risk, exposure=exposure, members=int(members), vulnerable=n_vuln, severity=float(severity), evidence=ev,
            forecast=fcs, forecast_why=why, flagged_lines=flagged_lines, effort_hours=effort, rules=rules_sorted,
            rule_counts=rule_counts, rule_paid=rule_paid, signals=signals, lane=lane, benign_context=ctx,
            anomalous=bool(anomalous), has_graph=bool(has_graph), escalating=bool(escal), dx_missing=dx_missing,
            signal_flags=dict(rules=bool(rule_counts), anomaly=bool(anomalous), graph=bool(has_graph), temporal=bool(escal)),
        ))
    return cases


# ---------------------------------------------------------------- evaluation
def evaluate(L, PT, cases, fc, T):
    if "_truth" not in L: return {}
    tp = L[L._truth].groupby("provider_id").size()
    truth_prov = set(tp[tp >= 20].index)
    flagged = L.any_flag
    prec = float(L[flagged]._truth.mean()); rec = float(L[L._truth].any_flag.mean())
    queue = sorted(cases, key=lambda c: -(c["risk"] * .5 + c["evidence"] * .3 + c["exposure"] ** .3))
    hit = [bool(set(c["primary"]) & truth_prov) for c in queue]
    out = dict(
        line_precision=prec, line_recall=rec, raw_flagged_lines=int(flagged.sum()), total_lines=int(len(L)),
        truth_providers=len(truth_prov), cases=len(cases),
        precision_at_5=float(np.mean(hit[:5])) if hit else 0, precision_at_10=float(np.mean(hit[:10])) if hit else 0,
        provider_recall=float(len(truth_prov & {p for c in cases for p in c["primary"]}) / max(1, len(truth_prov))),
        case_precision=float(np.mean(hit)) if hit else 0,
        flagged_providers=int((PT.any_share > 0).sum()),
        decoys_in_cases=[p for c in cases for p in c["primary"] if p not in truth_prov],
        note="Computed against hidden synthetic scenario labels. Not evidence of real-world performance.")
    return out


# ---------------------------------------------------------------- network payload
KIND_LABEL = {"referral": "Referral flow", "ownership": "Shared ownership", "address": "Shared address", "bank": "Shared bank account", "shared_members": "Shared members"}


def ego_graph(S, provider_ids, extra_hops=True, limit=16):
    G, PT, L = S["G"], S["PT"], S["L"]
    nodes = set(provider_ids)
    if extra_hops:
        cand = []
        for p in provider_ids:
            for q in G[p] if p in G else []:
                if q not in nodes:
                    w = sum(m.get("n", 5) for m in G[p][q]["multi"])
                    cand.append((w, q))
        for _, q in sorted(cand, reverse=True)[:limit]:
            nodes.add(q)
    sub = G.subgraph(nodes)
    nd, ed = [], []
    ent = {}
    for n in sub.nodes:
        d = G.nodes[n]
        nd.append(dict(id=n, label=d["label"], kind="provider", family=d["family"], risk=float(PT.at[n, "risk"]), primary=n in provider_ids, city=d["city"]))
    for a, b, d in sub.edges(data=True):
        for m in d["multi"]:
            if m["kind"] in ("ownership", "address", "bank"):
                e = m["via"]
                ent.setdefault(e, dict(kind=m["kind"], members=set()))["members"].update([a, b])
            else:
                ed.append(dict(source=a, target=b, kind=m["kind"], n=m.get("n"), share=m.get("share"), strong=m.get("strong", False),
                               label=(f"{m['n']} referrals · {m['share'] * 100:.0f}% of target's" if m["kind"] == "referral" else f"{m['n']} shared members")))
    for e, v in ent.items():
        nd.append(dict(id=e, label=e, kind=v["kind"], family=None, risk=0, primary=False))
        for p in v["members"]:
            ed.append(dict(source=p, target=e, kind=v["kind"], strong=True, label=KIND_LABEL[v["kind"]]))
    # layout
    H = nx.Graph()
    for n in nd: H.add_node(n["id"])
    for e in ed: H.add_edge(e["source"], e["target"])
    pos = A.layout(H, seed=5)
    for n in nd: n["x"], n["y"] = pos.get(n["id"], (0, 0))
    return dict(nodes=nd, edges=ed)


def network_payload(G, H, PT, comms, L):
    nodes = []
    cid = {}
    for i, c in enumerate(comms):
        for p in c: cid[p] = i
    # lay out every connected component separately and tile them on a grid
    comps = sorted([c for c in nx.connected_components(G) if len(c) > 1], key=lambda c: -len(c))
    ncol = max(1, int(np.ceil(np.sqrt(len(comps)))))
    pos = {}
    for i, c in enumerate(comps):
        sub = G.subgraph(c)
        lp = A.layout(sub, seed=2)
        xs = np.array([v[0] for v in lp.values()]); ys = np.array([v[1] for v in lp.values()])
        sx = (xs.max() - xs.min()) or 1; sy = (ys.max() - ys.min()) or 1
        span = 0.45 + 0.55 * min(1.0, len(c) / 12)
        for n, (x, y) in lp.items():
            pos[n] = ((i % ncol) + .5 + ((x - xs.min()) / sx - .5) * span * .9, (i // ncol) + .5 + ((y - ys.min()) / sy - .5) * span * .9)
    for n in G.nodes:
        if n not in pos: continue
        d = G.nodes[n]
        nodes.append(dict(id=n, label=d["label"], family=d["family"], risk=float(PT.at[n, "risk"]), community=cid.get(n, -1), x=pos[n][0], y=pos[n][1], degree=G.degree(n)))
    edges = []
    for a, b, d in G.edges(data=True):
        kinds = sorted({m["kind"] for m in d["multi"]})
        edges.append(dict(source=a, target=b, kinds=kinds, strong=any(m.get("strong") for m in d["multi"])))
    cinfo = []
    for i, c in enumerate(comms):
        sub = PT.loc[c]
        cinfo.append(dict(id=i, size=len(c), providers=c, avg_risk=float(sub.risk.mean()), max_risk=float(sub.risk.max()),
                          flagged=int((sub.risk >= PRIMARY_RISK).sum()), paid=float(sub.paid.sum()),
                          ties=int(sum(1 for a, b in H.subgraph(c).edges))))
    return dict(nodes=nodes, edges=edges, communities=cinfo, isolated=int(G.number_of_nodes() - len(nodes)))
