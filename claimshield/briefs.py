"""Queue ranking, case detail and explainable investigation briefs (deterministic, evidence-grounded)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline import ACTIONS, LOOKBACK, ego_graph
from rules import RULES

DEFAULT_WEIGHTS = dict(risk=.22, forecast=.15, dollars=.20, members=.10, severity=.15, evidence=.18)
WEIGHT_LABELS = dict(risk="Risk", forecast="Forecast", dollars="Potential dollars", members="Member impact", severity="Severity", evidence="Evidence strength")

STATUS_FROM_OUTCOME = {
    "Open investigation": "In investigation", "Request more information": "Awaiting information", "Monitor": "Monitoring",
    "Close - insufficient evidence": "Closed", "Close - legitimate explanation": "Closed",
    "Recommend referral": "Pending supervisor approval", "Approve referral": "Referral approved", "Reject referral": "In investigation",
}


def rank(S, weights=None, horizon=60, capacity_hours=96, statuses=None, sb=None, brain=None):
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    tw = sum(w.values()) or 1
    cs = S["cases"]
    mx_d = max(np.log1p(c["exposure"]) for c in cs) or 1
    mx_m = max(np.log1p(c["members"] + .5 * c["vulnerable"]) for c in cs) or 1
    rows = []
    for c in cs:
        ev_adj, sb_view = 0, None
        rs = [sb[p] for p in c["primary"] if sb and p in sb]
        if rs:
            top = max(r["suspicion"] for r in rs)
            if top >= 60: ev_adj, sb_view = 8, "agrees"
            elif top < 30 and all(r["confidence"] != "low" for r in rs): ev_adj, sb_view = -8, "disagrees"
            else: sb_view = "unsure"
        ev_now = float(np.clip(c["evidence"] + ev_adj, 0, 100))
        bscore = max(float(brain[p]) for p in c["primary"]) if brain is not None else None
        risk_eff = c["risk"] / 100 if bscore is None else .65 * c["risk"] / 100 + .35 * bscore
        comp = dict(risk=risk_eff, forecast=c["forecast"][horizon], dollars=np.log1p(c["exposure"]) / mx_d,
                    members=np.log1p(c["members"] + .5 * c["vulnerable"]) / mx_m, severity=c["severity"] / 100, evidence=ev_now / 100)
        pr = 100 * sum(w[k] * comp[k] for k in w) / tw
        gate = .65 if c["lane"] == "Needs more data" else .9 if c["lane"] in ("Validate context first", "Brain lead") else 1.0
        rows.append(dict(case_id=c["case_id"], title=c["title"], type=c["type"], priority=round(pr * gate, 1), raw_priority=round(pr, 1), gate=gate,
                         components={k: round(100 * comp[k], 1) for k in comp},
                         contributions={k: round(100 * w[k] * comp[k] / tw, 1) for k in w},
                         risk=round(c["risk"], 1), forecast=round(100 * c["forecast"][horizon], 1), exposure=round(c["exposure"], 0),
                         members=c["members"], vulnerable=c["vulnerable"], severity=round(c["severity"], 1),
                         severity_label="Critical" if c["severity"] >= 85 else "High" if c["severity"] >= 65 else "Medium",
                         evidence=round(ev_now, 1), second_brain=sb_view, brain=bscore, lane=c["lane"], effort_hours=c["effort_hours"], families=c["families"],
                         network=c["network"], n_providers=len(c["providers"]), rules=c["rules"], flagged_lines=c["flagged_lines"],
                         signal_flags=c["signal_flags"], escalating=c["escalating"],
                         status=(statuses or {}).get(c["case_id"], "New")))
    rows.sort(key=lambda r: -r["priority"])
    used = 0.0
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        if r["status"] == "Closed":
            r["capacity"] = "closed"; continue
        if used + r["effort_hours"] <= capacity_hours and r["lane"] != "Needs more data":
            used += r["effort_hours"]; r["capacity"] = "within"
        else:
            r["capacity"] = "deferred"
    return dict(queue=rows, weights=w, horizon=horizon, capacity_hours=capacity_hours, used_hours=round(used, 1))


def _fmt_money(x): return f"${x:,.0f}"


def case_detail(S, cid, horizon=60):
    c = next((x for x in S["cases"] if x["case_id"] == cid), None)
    if c is None: return None
    L, PT, END = S["L"], S["PT"], pd.Timestamp(S["run"]["as_of"])
    W = L[L.service_date > END - pd.Timedelta(days=LOOKBACK)]
    prim = c["primary"]
    sub = W[W.provider_id.isin(prim) & W.any_flag]
    detail = S["detail"]

    # ---- evidence items ----
    items = []
    n_id = 0
    for k in c["rules"]:
        spec = RULES[k]
        s = sub[sub[f"f_{k}"]].sort_values("paid", ascending=False)
        base = W[W.provider_id.isin(prim)]
        share = len(s) / max(1, len(base))
        n = len(s)
        strength = "Strong" if (share >= .05 and n >= 20) or (spec["severity"] >= .95 and n >= 5) else "Moderate" if n >= 5 else "Context"
        ex = [dict(line_id=r.line_id, claim_id=r.claim_id, provider_id=r.provider_id, member_id=r.member_id, date=str(r.service_date.date()), code=r.code,
                   paid=float(r.paid), reason=detail[k].get(r.line_id, spec["desc"]), anomaly=float(r.claim_anomaly)) for r in s.head(6).itertuples()]
        n_id += 1
        items.append(dict(id=f"EV-{n_id:03d}", kind="rule", rule=k, label=spec["name"], strength=strength, n_lines=n, paid=float(s.paid.sum()),
                          members=int(s.member_id.nunique()), share=float(share), rule_desc=spec["desc"], examples=ex,
                          source=f"claim_lines.csv · {n} rows · rule {k} ({S['run']['ruleset']})", providers=sorted(s.provider_id.unique())))
    for p in prim:
        pct = float(PT.at[p, "anomaly_pct"])
        if pct >= .85:
            n_id += 1
            items.append(dict(id=f"EV-{n_id:03d}", kind="anomaly", label=f"Provider behaviour unusual vs. {PT.at[p, 'family']} peers", provider=p,
                              strength="Moderate" if pct >= .93 else "Context", pct=pct, drivers=S["adrivers"].get(p, []),
                              source="Isolation Forest on 90-day provider features (peer-normalised)"))
    import sentinel as SN
    import brain as BR
    bc = S["brain_contrib"]
    for p in prim:
        n_id += 1
        parts = sorted([(lbl, float(bc.at[p, k])) for k, _, lbl, _ in BR.DETECTORS if bc.at[p, k] > .05], key=lambda x: -x[1])
        items.append(dict(id=f"EV-{n_id:03d}", kind="brain", label="Nexus Brain fusion", provider=p, strength="Strong" if PT.at[p, "brain"] >= .95 else "Moderate" if PT.at[p, "brain"] >= .7 else "Context",
                          score=float(PT.at[p, "brain"]), parts=parts,
                          detail=f"{PT.at[p, 'name']}: brain suspicion {PT.at[p, 'brain'] * 100:.0f}/100 from {len(parts)} detector(s) independently above their normal range.",
                          source="brain.py · one-sided evidence fusion over 7 detectors; weights learn from human decisions"))
        cp = S["change_points"].get(p, {})
        if cp.get("text") and PT.at[p, "drift_pct"] >= .85:
            n_id += 1
            items.append(dict(id=f"EV-{n_id:03d}", kind="drift", label=f"Behaviour changed in {cp['onset']}", provider=p, strength="Strong" if PT.at[p, "drift_pct"] >= .95 else "Moderate",
                              detail=cp["text"], changes=cp["changes"], source="brain.py · change-point search over monthly volume, members, new members, out-of-region share, paid per line, service mix"))
    for p in prim:
        sv = PT.at[p, "sentinel"]
        if sv == sv and sv >= .8:
            n_id += 1
            tr = SN.explain_transitions(S["paths"], p, 3)
            items.append(dict(id=f"EV-{n_id:03d}", kind="sentinel", label="SpotZ Sentinel (in-house learned models)", provider=p, strength="Strong" if PT.at[p, "twin_pct"] >= .85 and PT.at[p, "path_pct"] >= .85 else "Moderate",
                              detail=f"{PT.at[p, 'name']}: billed {PT.at[p, 'oe_paid']:.1f}× what its own patients' case mix predicts (≈${PT.at[p, 'unexplained_paid']:,.0f} unexplained, case-mix twin {PT.at[p, 'twin_pct'] * 100:.0f}th pct); care-pathway improbability {PT.at[p, 'path_pct'] * 100:.0f}th pct.",
                              transitions=tr, source="sentinel.py · cross-fitted case-mix twin + leave-provider-out care-pathway model (no rules, no labels)"))
    for p in prim:
        om = PT.at[p, "own_model"] if "own_model" in PT.columns else float("nan")
        if om == om and om >= .5:
            n_id += 1
            items.append(dict(id=f"EV-{n_id:03d}", kind="own_model", label="Own model (trained on Kaggle provider-fraud data)", provider=p, strength="Moderate" if om >= .8 else "Context",
                              detail=f"{PT.at[p, 'name']}: {om * 100:.0f}% fraud-likeness from relative behaviour (claims per beneficiary, amount spread, repeat-beneficiary share, inpatient share…). Transfer from a different dataset, so treat as a complementary signal.",
                              source="kaggle_model/model.joblib (gradient boosting + logistic) on shared provider features"))
    if c["network"]:
        ego = ego_graph(S, c["primary"], extra_hops=False)
        ent = [n for n in ego["nodes"] if n["kind"] != "provider"]
        refs = [e for e in ego["edges"] if e["kind"] == "referral"]
        shared = [e for e in ego["edges"] if e["kind"] == "shared_members"]
        n_id += 1
        items.append(dict(id=f"EV-{n_id:03d}", kind="graph", label="Connected providers", strength="Strong" if ent or any(e["strong"] for e in refs) else "Moderate",
                          detail=f"{len(c['providers'])} providers linked via {len(ent)} shared ownership/address/bank record(s), {len(refs)} strong referral edge(s), {len(shared)} shared-member edge(s).",
                          source="relationships.csv + referrals.csv + claim_lines.csv (graph build)"))
    inv = S["T"]["investigations"]
    pinv = inv[inv.provider_id.isin(prim)]
    if len(pinv):
        n_id += 1
        items.append(dict(id=f"EV-{n_id:03d}", kind="history", label="Prior investigations", strength="Context",
                          detail="; ".join(f"{r.investigation_id}: {r.outcome} (closed {r.closed_date})" for r in pinv.itertuples()),
                          source="investigations.csv"))

    # ---- timeline ----
    monthly = L[L.provider_id.isin(prim)].copy()
    monthly["month"] = monthly.service_date.dt.to_period("M").astype(str)
    mg = monthly.groupby("month").agg(paid=("paid", "sum"), flagged=("flag_paid", "sum"), lines=("line_id", "size")).reset_index()
    onset = {}
    for k in c["rules"]:
        d = L[L.provider_id.isin(prim) & L[f"f_{k}"]].service_date
        if len(d): onset[k] = d.min()
    events = [dict(date=str(v.date()), label=f"First {RULES[k]['name'].lower()} flag", kind="flag") for k, v in sorted(onset.items(), key=lambda kv: kv[1])]
    for r in pinv.itertuples():
        events.append(dict(date=r.closed_date, label=f"Prior investigation closed: {r.outcome}", kind="history"))
    events.sort(key=lambda e: e["date"])

    # ---- hypotheses ----
    ev = c["evidence"]
    sus = int(np.clip(ev + 5 * len(c["rules"]) - (20 if c["benign_context"] else 0), 8, 96))
    leg = int(np.clip(100 - ev * .9 + (20 if c["benign_context"] else 0) + 10 * (c["dx_missing"] > .1), 5, 90))
    unc = int(np.clip(20 + 120 * c["dx_missing"] + (15 if S["run"]["validation"]["coverage"]["documented_time"] < .3 else 0), 8, 80))
    hyps = [dict(title="Billing pattern consistent with fraud, waste or abuse", kind="Suspicious", support=sus,
                 summary="Multiple independent signals point the same direction; documentation has not yet been reviewed."),
            dict(title="Legitimate clinical or operational explanation", kind="Legitimate", support=leg,
                 summary=(c["benign_context"][0] + " " if c["benign_context"] else "") + "Benign causes listed below could produce the same claim pattern."),
            dict(title="Data incomplete or mis-measured", kind="Uncertain", support=unc,
                 summary=f"{c['dx_missing'] * 100:.0f}% of lines lack a diagnosis code; documented time covers only part of claims; claims run-out is not modelled.")]
    checks = []
    if not c["rules"]:
        checks.append(dict(rule="DRIFT", rule_name="Behaviour change", paid=c["exposure"], benign=["Practice expansion, new site or acquisition", "New payer contract or community programme", "Data feed change"],
                           check="Sample encounters from the onset month; verify how new members were acquired and whether referrals were independent.", minutes=35,
                           resolves=f"Could explain or confirm the behaviour shift behind {_fmt_money(c['exposure'])} of unexplained spend."))
    for k in c["rules"][:5]:
        sp = RULES[k]
        checks.append(dict(rule=k, rule_name=sp["name"], paid=c["rule_paid"][k], benign=sp["benign"], check=sp["check"], minutes=int(10 + 4 * len(sp["benign"]) + (6 if k in ("PHANTOM", "TIMING") else 0)),
                           resolves=f"Could clear or confirm {c['rule_counts'][k]} flagged line(s) worth {_fmt_money(c['rule_paid'][k])}."))

    # ---- confidence / limitations ----
    if ev >= 70 and not c["benign_context"]: conf = "High"
    elif ev >= 45: conf = "Moderate"
    else: conf = "Low"
    rationale = [f"{c['signals']} of 5 independent signal families agree (rules, anomaly, graph, escalation, Sentinel)." if c["signals"] >= 2 else "Only one signal family supports this case.",
                 f"{len(c['rules'])} distinct rule type(s) fired on {c['flagged_lines']} lines.",
                 ("Benign context present: " + c["benign_context"][0]) if c["benign_context"] else "No benign context recorded in provider master data."]
    limits = ["Synthetic data: results show the method, not real-world accuracy.",
              "A flag is a pattern for human review, not a finding of fraud. Exposure is gross flagged dollars, not an expected recovery.",
              "Peer baselines are family-level; specialty or panel mix can explain differences.",
              f"Claims run-out not modelled; as-of {S['run']['as_of']}. Recent months may be incomplete.",
              "Forecast probabilities come from a discrete-time hazard model trained on simulated outcomes; calibration is shown in Governance."]
    if c["dx_missing"] > .1: limits.append(f"{c['dx_missing'] * 100:.0f}% of lines lack diagnosis codes, limiting clinical-necessity checks.")
    if c["lane"] == "Needs more data":
        limits.append("Evidence is below the investigation threshold: system abstains from recommending an investigation and asks for more data.")
        action = "Do not open an investigation yet. Request the missing documentation (diagnosis context, specialty/panel mix) and re-run; monitor next cycle."
    else:
        action = (" ".join(ACTIONS[k] for k in c["rules"][:2]) or "No rule fired: learned detectors found a behaviour shift. Sample encounters from the onset month and verify member acquisition and referral independence before opening an investigation.") + " " + ("Validate benign context first. " if c["lane"] == "Validate context first" else "") + \
                 "Any payment hold, provider contact or referral requires human approval; the system takes no adverse action."

    # ---- summary ----
    names = ", ".join(PT.at[p, "name"] for p in prim[:3]) + ("…" if len(prim) > 3 else "")
    summ = (f"{c['flagged_lines']:,} flagged claim lines ({_fmt_money(c['exposure'])} paid) across {c['members']} members at {names}. "
            f"Main pattern: {c['type'].lower()}. " + ("Priority drivers: " + ", ".join(RULES[k]['name'].lower() for k in c['rules'][:3]) + "." if c["rules"] else "No billing rule fired; the learned detectors flagged it."))
    if c["network"]: summ += f" The case links {len(c['providers'])} providers through shared ownership, referral dependence or member overlap."

    # ---- sample lines ----
    sample = sub.sort_values(["claim_anomaly", "paid"], ascending=False).head(40)
    tags = lambda r: [k for k in RULES if r[f"f_{k}"]]
    lines = [dict(line_id=r["line_id"], date=str(r["service_date"].date()), provider=r["provider_id"], member=r["member_id"], code=r["code"], units=int(r["units"]),
                  paid=float(r["paid"]), rules=tags(r), anomaly=float(r["claim_anomaly"]),
                  reason="; ".join(detail[k].get(r["line_id"], "") for k in tags(r))) for _, r in sample.iterrows()]

    prov_tbl = [dict(provider_id=p, name=PT.at[p, "name"], family=PT.at[p, "family"], specialty=PT.at[p, "specialty"], city=PT.at[p, "city"], risk=float(PT.at[p, "risk"]),
                     role="primary" if p in prim else "linked", anomaly_pct=float(PT.at[p, "anomaly_pct"]), flagged_paid=float(PT.at[p, "flagged_paid"]),
                     lines=int(PT.at[p, "n_lines"]), context=PT.at[p, "context_note"]) for p in c["providers"]]
    fc = {h: dict(p=c["forecast"][h], why=c["forecast_why"][h], metrics=S["fc"]["metrics"].get(h, {})) for h in (30, 60, 90)}
    return dict(case_id=cid, title=c["title"], type=c["type"], summary=summ, metrics=dict(risk=c["risk"], exposure=c["exposure"], members=c["members"], vulnerable=c["vulnerable"],
                severity=c["severity"], evidence=ev, effort_hours=c["effort_hours"], flagged_lines=c["flagged_lines"]),
                lane=c["lane"], confidence=dict(label=conf, score=ev, rationale=rationale), hypotheses=hyps, checks=checks, evidence=items, timeline=dict(monthly=mg.to_dict("records"), events=events),
                network=ego_graph(S, c["primary"]), providers=prov_tbl, forecast=fc, limitations=limits, action=action, sample_lines=lines,
                signal_flags=c["signal_flags"], run=dict(run_id=S["run"]["run_id"], ruleset=S["run"]["ruleset"], model=S["run"]["model"], as_of=S["run"]["as_of"]))


def brief_markdown(d, decisions=None):
    m = d["metrics"]
    o = [f"# SpotZ^i investigation brief — {d['case_id']}: {d['title']}", "",
         f"*Run {d['run']['run_id']} · as of {d['run']['as_of']} · {d['run']['ruleset']} · {d['run']['model']} · SYNTHETIC DATA*", "",
         f"**Type:** {d['type']}  ", f"**Lane:** {d['lane']}  ", f"**Confidence:** {d['confidence']['label']} ({d['confidence']['score']:.0f}/100)", "",
         "> A flagged pattern is not a finding of fraud. This brief supports a human reviewer; it takes no adverse action.", "",
         "## Summary", d["summary"], "",
         "## Key numbers", f"- Risk {m['risk']:.0f}/100 · Severity {m['severity']:.0f}/100 · Evidence strength {m['evidence']:.0f}/100",
         f"- Gross flagged exposure {_fmt_money(m['exposure'])} (not a recovery estimate) · {m['members']} members ({m['vulnerable']} vulnerable) · est. {m['effort_hours']} review hours",
         f"- Forecast chance of repeat/escalating FWA: 30d {d['forecast'][30]['p'] * 100:.0f}% · 60d {d['forecast'][60]['p'] * 100:.0f}% · 90d {d['forecast'][90]['p'] * 100:.0f}%", "",
         "## Evidence"]
    for e in d["evidence"]:
        o.append(f"### {e['id']} {e['label']} — {e['strength']}")
        if e["kind"] == "rule":
            o.append(f"{e['rule_desc']} {e['n_lines']} lines, {_fmt_money(e['paid'])}, {e['members']} members. Source: {e['source']}.")
            for x in e["examples"][:3]:
                o.append(f"- `{x['line_id']}` {x['date']} {x['code']} {_fmt_money(x['paid'])} — {x['reason']}")
        elif e["kind"] == "anomaly":
            o.append("Peer-normalised drivers: " + ", ".join(f"{x['feature']} (z={x['peer_z']:.1f})" for x in e["drivers"]) + f". Source: {e['source']}.")
        else:
            o.append(f"{e['detail']} Source: {e['source']}.")
    o += ["", "## Competing explanations"] + [f"- **{h['kind']} ({h['support']}%)** {h['title']}: {h['summary']}" for h in d["hypotheses"]]
    o += ["", "## Checks that would distinguish them"] + [f"- {c['rule_name']}: {c['check']} (~{c['minutes']} min)" for c in d["checks"]]
    o += ["", "## Timeline"] + [f"- {e['date']} — {e['label']}" for e in d["timeline"]["events"]]
    o += ["", "## Network context"] + [f"- {p['name']} ({p['family']}, {p['role']}) risk {p['risk']:.0f}" for p in d["providers"]]
    o += ["", "## Confidence rationale"] + [f"- {r}" for r in d["confidence"]["rationale"]]
    o += ["", "## Limitations"] + [f"- {r}" for r in d["limitations"]]
    o += ["", "## Recommended human-review action", d["action"]]
    if decisions:
        o += ["", "## Decision log"] + [f"- {x['ts']} · {x['reviewer']} ({x['role']}): **{x['outcome']}** — {x['reason']}" for x in decisions]
    return "\n".join(o)
