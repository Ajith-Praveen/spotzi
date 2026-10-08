"""SpotZⁱ Nexus Brain — the "second brain" layer.

* Two more detectors:
    - Behaviour change-point: finds the month a provider's behaviour shifted (volume, new members, out-of-region
      members, paid per line, code mix) and explains before -> after.
    - Peer code-mix divergence: Jensen-Shannon divergence of the provider's service mix vs its family.
* Fusion that LEARNS: a logistic model over every detector's percentile with a strong prior (expert weights);
  each human decision (substantiated vs cleared) updates the weights by MAP estimation. Stateless and
  reproducible: weights = f(prior, all recorded decisions). Output is a suspicion score, not a probability.
* Memory + feed: proactive insights (behaviour changes, detector disagreement, brain-only leads, what it learned).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DETECTORS = [  # key, column in PT, label, prior weight
    ("rules", "rule_pct", "Rules engine", .9),
    ("iforest", "anomaly_pct", "Isolation Forest", .5),
    ("graph", "graph_score", "Network graph", .4),
    ("twin", "twin_pct", "Sentinel case-mix twin", .5),
    ("path", "path_pct", "Sentinel care pathway", .6),
    ("drift", "drift_pct", "Behaviour change-point", .6),
    ("mix", "mix_pct", "Peer code-mix divergence", .35),
    ("panel", "panel_pct", "Patient-panel shift", .5),
]
BASE = list(DETECTORS)
EXTRA = {"temporal": ("temporal", "temporal_pct", "Temporal evolution", .5), "peer": ("peer", "peer_pct", "Hierarchical peer baseline", .5)}


def use(extra: list[str]):
    """Choose which optional detectors join the fusion (decided by the ablation study, see evaluation/engine.py)."""
    DETECTORS[:] = BASE + [EXTRA[k] for k in extra if k in EXTRA]
PRIOR_BIAS = -3.2
POSITIVE = {"Open investigation", "Recommend referral", "Approve referral"}
NEGATIVE = {"Close - legitimate explanation", "Close - insufficient evidence"}


def _js(p, q):
    p = np.asarray(p, float) + 1e-9; q = np.asarray(q, float) + 1e-9
    p /= p.sum(); q /= q.sum(); m = (p + q) / 2
    return float(.5 * (p * np.log2(p / m)).sum() + .5 * (q * np.log2(q / m)).sum())


def change_points(L, M, providers):
    reg = M.set_index("member_id").region
    city = providers.set_index("provider_id").city
    d = L[["provider_id", "member_id", "service_date", "paid", "code"]].copy()
    d["month"] = d.service_date.dt.to_period("M")
    first = d.groupby(["provider_id", "member_id"]).service_date.transform("min")
    d["new"] = (first.dt.to_period("M") == d.month)
    d["far"] = d.member_id.map(reg) != d.provider_id.map(city)
    months = sorted(d.month.unique())
    out = {}
    for pid, g in d.groupby("provider_id"):
        mg = g.groupby("month").agg(lines=("code", "size"), members=("member_id", "nunique"), paid=("paid", "sum"),
                                    new=("new", lambda s: 0), far=("far", "mean"))
        nm = g[g.new].groupby("month").member_id.nunique()
        mg["new"] = nm.reindex(mg.index).fillna(0)
        mg = mg.reindex(months).fillna({"lines": 0, "members": 0, "paid": 0, "new": 0})
        mg["far"] = mg.far.fillna(mg.far.mean() if mg.far.notna().any() else 0)
        X = pd.DataFrame({"volume": np.log1p(mg.lines), "members": np.log1p(mg.members), "new members": np.log1p(mg.new),
                          "out-of-region share": mg.far, "paid per line": np.log1p(mg.paid / mg.lines.replace(0, np.nan)).fillna(0)})
        cm = g.groupby(["month", "code"]).size().unstack(fill_value=0).reindex(months, fill_value=0)
        best = (0.0, None, None)
        n = len(months)
        for t in range(4, n - 1):
            a, b = X.iloc[:t], X.iloc[t:]
            if mg.lines.iloc[t:].sum() < 15: continue
            dz = (b.mean() - a.mean()) / (a.std().fillna(0) + .15 * a.mean().abs() + .1)
            js = _js(cm.iloc[:t].sum().values, cm.iloc[t:].sum().values)
            volume = float(np.sqrt((dz[["volume", "members", "new members"]] ** 2).mean()))
            composition = 6 * js + abs(float(dz["out-of-region share"])) + .5 * abs(float(dz["paid per line"]))
            # who is treated and how changes matters more than raw growth (legitimate expansion grows volume, keeps its mix)
            score = float(composition + .35 * volume + .25 * volume * min(1.0, composition)) * min(1.0, (n - t) / 4)
            if score > best[0]: best = (score, t, (dz, js, a.mean(), b.mean()))
        if best[1] is None:
            out[pid] = dict(score=0.0); continue
        dz, js, ma, mb = best[2]
        top = dz.abs().sort_values(ascending=False).head(3).index
        def fmt(k, v):
            if k == "out-of-region share": return f"{v * 100:.0f}%"
            if k == "paid per line": return f"${np.expm1(v):,.0f}"
            return f"{np.expm1(v):.0f}/mo"
        changes = [dict(metric=k, before=fmt(k, ma[k]), after=fmt(k, mb[k]), z=float(dz[k])) for k in top]
        out[pid] = dict(score=best[0], onset=str(months[best[1]]), js=js, changes=changes,
                        text=f"From {months[best[1]]}: " + ", ".join(f"{c['metric']} {c['before']} → {c['after']}" for c in changes) + (f"; service mix shifted (JS {js:.2f})" if js > .05 else ""))
    return out


def code_mix(L, providers, end, lookback=180):
    W = L[L.service_date > end - pd.Timedelta(days=lookback)]
    fam = providers.set_index("provider_id").family
    res = {}
    for f, gf in W.groupby("family"):
        peer = gf.code.value_counts()
        for pid, g in gf.groupby("provider_id"):
            if fam.get(pid) != f: continue
            own = g.code.value_counts().reindex(peer.index, fill_value=0)
            js = _js(own.values, (peer - own).clip(lower=0).values)
            res[pid] = js * len(g) / (len(g) + 50)
    return pd.Series(res)


def panel_shift(L, M, end, lookback=180):
    """Patient-panel shift (recruitment / patient-brokering typology). Among patients NEW to a provider in the review window:
    (a) bundle uniformity — share given the provider's single most common service bundle, vs family peers;
    (b) isolation — share with no care from any other provider in the plan, vs the portfolio;
    (c) catchment — share from regions the provider's shared-care patients do not come from.
    Peer baselines rather than the provider's own history, so a scheme that began before the window cannot hide by
    contaminating its own baseline. Legitimate growth brings varied care for local patients who are also seen elsewhere."""
    w0 = end - pd.Timedelta(days=lookback)
    d = L[["provider_id", "member_id", "service_date", "code", "family"]]
    pm = d.groupby(["provider_id", "member_id"]).agg(first=("service_date", "min"), bundle=("code", lambda s: "+".join(sorted(set(s))))).reset_index()
    nprov = d.groupby("member_id").provider_id.nunique()
    pm["isolated"] = pm.member_id.map(nprov).fillna(1) <= 1
    pm["region"] = pm.member_id.map(M.set_index("member_id").region).fillna("Unknown")
    fam = d.drop_duplicates("provider_id").set_index("provider_id").family
    shared = pm[~pm.isolated].region.value_counts(normalize=True)
    portfolio_usual = set(shared.index[(shared.cumsum() - shared) < .8])
    recent = d[d.service_date > w0].groupby("provider_id").member_id.nunique()
    new = pm[pm["first"] > w0]
    rows = {}
    for pid, g in new.groupby("provider_id"):
        if len(g) < 5: continue
        own = pm[(pm.provider_id == pid) & ~pm.isolated].region.value_counts(normalize=True)
        usual = set(own.index[(own.cumsum() - own) < .9]) if own.sum() and len(pm[(pm.provider_id == pid) & ~pm.isolated]) >= 5 else portfolio_usual
        top = g.bundle.value_counts()
        rows[pid] = dict(n=len(g), share=len(g) / max(1, int(recent.get(pid, len(g)))), tmpl=float(top.iat[0] / len(g)), bundle=top.index[0],
                         iso=float(g.isolated.mean()), far=float((~g.region.isin(usual)).mean()), family=fam.get(pid))
    R = pd.DataFrame.from_dict(rows, orient="index")
    if R.empty: return {}
    base_t = R.groupby("family").tmpl.transform("median").fillna(R.tmpl.median())
    base_i = float(new.isolated.mean()); base_f = float(R.far.median())
    R["score"] = (R.share * R.n / (R.n + 15) * (.45 * (R.tmpl - base_t).clip(lower=0) + .3 * (R.iso - base_i).clip(lower=0) + .25 * (R.far - base_f).clip(lower=0)))
    out = {}
    for pid, r in R.iterrows():
        out[pid] = dict(score=float(r.score), new=int(r.n), share=float(r.share), tmpl=float(r.tmpl), bundle=r.bundle, isolated=float(r.iso), far=float(r.far),
                        text=f"{int(r.n)} new patients in {lookback} days ({r.share * 100:.0f}% of the panel); {r.tmpl * 100:.0f}% received the same bundle ({str(r.bundle)[:40]}); "
                             f"{r.iso * 100:.0f}% have no other care in the plan (portfolio {base_i * 100:.0f}%); {r.far * 100:.0f}% from outside the usual catchment")
    return out


def detector_matrix(PT):
    X = pd.DataFrame(index=PT.index)
    for k, col, _, _ in DETECTORS:
        X[k] = PT[col].fillna(.5) if col in PT else .5
    return X


def _logit(p):
    """One-sided evidence: a detector that is quiet (<= median) contributes nothing, because narrow detectors
    (especially rules) staying silent is not proof of innocence."""
    p = np.clip(p, .02, .98); return np.maximum(0, np.log(p / (1 - p)))


def learn(PT, labels: dict, lam=40.0, iters=800, lr=.01):
    """MAP logistic regression with a strong Gaussian prior centred on expert weights.
    Each decision nudges weights; many consistent decisions are needed to move them far.
    Weights are kept >= 0 because every detector is one-sided evidence of concern."""
    w0 = np.array([w for *_, w in DETECTORS]); b0 = PRIOR_BIAS
    w, b = w0.copy(), b0
    ids = [p for p in labels if p in PT.index]
    if ids:
        X = _logit(detector_matrix(PT).loc[ids].values); y = np.array([labels[p] for p in ids], float)
        for _ in range(iters):
            p = 1 / (1 + np.exp(-(X @ w + b)))
            w -= lr * (X.T @ (p - y) + lam * (w - w0))
            b -= lr * (float((p - y).sum()) + lam * (b - b0))
            w = np.maximum(w, 0)
    return w, b, w0, len(ids)


def score(PT, w, b):
    X = _logit(detector_matrix(PT).values)
    z = X @ w + b
    s = pd.Series(1 / (1 + np.exp(-z)), index=PT.index)
    contrib = pd.DataFrame(X * w, index=PT.index, columns=[k for k, *_ in DETECTORS])
    return s, contrib


def labels_from_decisions(decisions, cases):
    last = {}
    for d in decisions: last[d["case_id"]] = d["outcome"]
    lab = {}
    for c in cases:
        o = last.get(c["case_id"])
        if o in POSITIVE: v = 1
        elif o in NEGATIVE: v = 0
        else: continue
        for p in c["primary"]: lab[p] = v
    return lab


def feed(S, brain, contrib, w, w0, n_labels):
    PT = S["PT"]; cps = S.get("change_points", {}); items = []
    in_case = {p for c in S["cases"] for p in c["providers"]}
    case_of = {p: c["case_id"] for c in S["cases"] for p in c["providers"]}
    end = pd.Timestamp(S["run"]["as_of"])
    learned_only = [k for k in ("twin", "path", "drift", "mix", "iforest")]
    for pid in PT.index:
        r = PT.loc[pid]; bs = brain[pid]; ct = contrib.loc[pid]
        cp = cps.get(pid, {})
        if bs >= .6 and r.rule_score < .3:
            items.append(dict(kind="lead", severity=bs, provider=pid, case_id=case_of.get(pid),
                              title=f"{r['name']}: suspicious without any rule firing",
                              text=f"Brain suspicion {bs * 100:.0f}. Driven by " + ", ".join(lbl for k, _, lbl, _ in DETECTORS if ct[k] > .8 and k != "rules") + "." + (f" {cp['text']}." if cp.get("text") and r.drift_pct >= .85 else "")))
        if cp.get("onset") and r.drift_pct >= .9 and pd.Period(cp["onset"]).to_timestamp() >= end - pd.Timedelta(days=200):
            items.append(dict(kind="change", severity=.55 + .4 * r.drift_pct * min(1, bs * 2), provider=pid, case_id=case_of.get(pid),
                              title=f"{r['name']} changed behaviour in {cp['onset']}", text=cp["text"]))
        if r.rule_score >= .5 and np.mean([r.get(f"{k}_pct", .5) if k != "iforest" else r.anomaly_pct for k in ("twin", "path", "drift")]) < .55:
            items.append(dict(kind="disagree", severity=.45, provider=pid, case_id=case_of.get(pid),
                              title=f"{r['name']}: rules fire but learned detectors see normal behaviour",
                              text="Possible false positive or a legitimate context (specialty mix, chronic monitoring). Validate before investing review time."))
    for (k, _, lbl, _), wi, w0i in zip(DETECTORS, w, w0):
        if n_labels and abs(wi - w0i) > .05:
            items.append(dict(kind="learned", severity=.4, provider=None, case_id=None, title=f"Learned from {n_labels} decision(s): {lbl} weight {w0i:.2f} → {wi:.2f}",
                              text="Investigator outcomes " + ("support" if wi > w0i else "discount") + f" this detector. Ranking adapts automatically; human decisions stay final."))
    items.sort(key=lambda x: -x["severity"])
    return items
