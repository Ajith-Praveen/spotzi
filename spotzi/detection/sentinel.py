"""SpotZ Sentinel — in-house learned detection models (no LLM, no hidden labels).

1. Case-mix twin  : predicts what a provider's own patients would normally cost from who they are
                     (age, plan, diagnosis profile, utilisation elsewhere, service family). Cross-fitted by
                     provider groups so no provider ever contributes to its own expectation. Unexplained
                     spend = observed − expected, shrunk toward zero for small panels (empirical Bayes).
2. Care-pathway   : a smoothed back-off sequence model of member journeys:
                     P(code_t | code_{t-1}, gap bucket, inside-inpatient-stay, after-coverage-end).
                     Counts are leave-provider-out: a provider's own claims never make its own pattern look normal.
                     Line surprisal = −log2 P. Provider score = mean excess surprisal vs family.
3. Fusion         : rank-average of the two percentiles (within service family) -> Sentinel score.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold

GAP_EDGES = [-1, 0, 2, 7, 30, 10**6]
GAP_LABEL = ["same day", "1–2 days", "3–7 days", "8–30 days", ">30 days"]


# ------------------------------------------------------------------ case-mix twin
def case_mix_twin(L, M, end, lookback=180):
    W = L[L.service_date > end - pd.Timedelta(days=lookback)]
    pm = (
        W.groupby(["provider_id", "member_id", "family"])
        .agg(paid=("paid", "sum"), lines=("line_id", "size"))
        .reset_index()
    )
    mem = M.set_index("member_id")
    # member profile from ALL their claims (who they are, not what this provider did)
    dx = W.assign(dxc=W.dx.fillna("NA").str[:1]).groupby(["member_id", "dxc"]).size().unstack(fill_value=0)
    dx = dx.div(dx.sum(axis=1), axis=0).add_prefix("dx_")
    tot = W.groupby("member_id").agg(
        m_lines=("line_id", "size"), m_paid=("paid", "sum"), m_prov=("provider_id", "nunique")
    )
    fam_tot = W.groupby(["member_id", "family"]).agg(f_lines=("line_id", "size"), f_paid=("paid", "sum")).reset_index()
    stays = W[W.code == "INP-DAY"].groupby("member_id").size().rename("m_stays")
    X = pm.merge(fam_tot, on=["member_id", "family"], how="left")
    X = X.join(tot, on="member_id").join(dx, on="member_id").join(stays, on="member_id")
    X["m_stays"] = X.m_stays.fillna(0)
    # utilisation elsewhere = member totals minus this provider's own contribution
    X["else_lines"] = np.log1p(X.m_lines - X.lines)
    X["else_paid"] = np.log1p((X.m_paid - X.paid).clip(lower=0))
    X["else_fam_lines"] = np.log1p(X.f_lines - X.lines)
    X["else_fam_paid"] = np.log1p((X.f_paid - X.paid).clip(lower=0))
    X["age"] = X.member_id.map(mem.age)
    X["medicaid"] = (X.member_id.map(mem.plan) == "Medicaid").astype(float)
    X["medicare"] = (X.member_id.map(mem.plan) == "Medicare Advantage").astype(float)
    for f in ["PRO", "LAB", "FAC", "PHARM", "AMB", "BH", "HH", "DME"]:
        X[f"fam_{f}"] = (X.family == f).astype(float)
    feats = [
        "else_lines",
        "else_paid",
        "else_fam_lines",
        "else_fam_paid",
        "m_prov",
        "m_stays",
        "age",
        "medicaid",
        "medicare",
    ] + [c for c in X.columns if c.startswith("dx_") or c.startswith("fam_")]
    X[feats] = X[feats].fillna(0)
    y_paid = np.log1p(X.paid.values)
    y_lines = np.log1p(X.lines.values)
    e_paid = np.zeros(len(X))
    e_lines = np.zeros(len(X))
    groups = X.provider_id.values
    for tr, te in GroupKFold(5).split(X, groups=groups):
        for y, out in ((y_paid, e_paid), (y_lines, e_lines)):
            m = HistGradientBoostingRegressor(
                max_depth=4,
                learning_rate=0.06,
                max_iter=250,
                min_samples_leaf=40,
                l2_regularization=1.0,
                random_state=0,
            )
            m.fit(X.iloc[tr][feats], y[tr])
            out[te] = m.predict(X.iloc[te][feats])
    X["exp_paid"] = np.expm1(e_paid).clip(min=0)
    X["exp_lines"] = np.expm1(e_lines).clip(min=0)
    X["r_paid"] = y_paid - e_paid
    X["r_lines"] = y_lines - e_lines
    g = X.groupby("provider_id")
    P = pd.DataFrame(
        {
            "obs_paid": g.paid.sum(),
            "exp_paid": g.exp_paid.sum(),
            "obs_lines": g.lines.sum(),
            "exp_lines": g.exp_lines.sum(),
            "n_members": g.size(),
            "r_paid": g.r_paid.mean(),
            "r_lines": g.r_lines.mean(),
            "sd": g.r_paid.std().fillna(1),
        }
    )
    k = 15  # empirical-Bayes shrinkage: small panels pulled toward "explained"
    P["shrunk"] = (P.r_paid * 0.6 + P.r_lines * 0.4) * P.n_members / (P.n_members + k)
    P["oe_paid"] = P.obs_paid / P.exp_paid.clip(lower=1)
    P["unexplained_paid"] = (P.obs_paid - P.exp_paid).clip(lower=0)
    r2 = lambda y, e: float(1 - np.var(y - e) / np.var(y)) if np.var(y) > 0 else 0.0
    fit = dict(r2_paid=r2(y_paid, e_paid), r2_lines=r2(y_lines, e_lines), rows=int(len(X)))
    return P, fit


# ------------------------------------------------------------------ care pathway
def _tokens(L, M, stays):
    d = (
        L[["line_id", "member_id", "provider_id", "family", "code", "service_date", "pos"]]
        .sort_values(["member_id", "service_date", "line_id"])
        .copy()
    )
    d["prev"] = d.groupby("member_id").code.shift().fillna("START")
    gap = d.groupby("member_id").service_date.diff().dt.days
    d["gap"] = pd.cut(gap.fillna(10**5), GAP_EDGES, labels=False).astype(int)
    d.loc[gap.isna(), "gap"] = 4
    st = stays[["member_id", "admit_date", "discharge_date"]]
    x = d[["line_id", "member_id", "service_date", "pos", "family"]].merge(st, on="member_id")
    ins = x[
        (x.service_date > x.admit_date) & (x.service_date < x.discharge_date) & (x.pos != "21") & (x.family != "FAC")
    ].line_id.unique()
    d["stay"] = d.line_id.isin(ins).astype(int)
    mm = M.set_index("member_id")
    endd = pd.to_datetime(mm.death_date).fillna(pd.to_datetime(mm.term_date))
    e = d.member_id.map(endd)
    d["after"] = (e.notna() & (d.service_date > e)).astype(int)
    d["ctx"] = d.stay * 2 + d.after  # 0 normal, 1 after coverage end, 2 in stay, 3 both
    return d


def care_pathway(L, M, stays, alpha=4.0, beta=8.0):
    d = _tokens(L, M, stays)
    codes = sorted(d.code.unique())
    V = len(codes)
    # global counts and per-provider counts (for leave-provider-out)
    c3 = d.groupby(["prev", "gap", "ctx", "code"]).size()
    c3p = d.groupby(["provider_id", "prev", "gap", "ctx", "code"]).size()
    c2 = d.groupby(["gap", "ctx", "code"]).size()
    c2p = d.groupby(["provider_id", "gap", "ctx", "code"]).size()
    c1 = d.groupby("code").size()
    c1p = d.groupby(["provider_id", "code"]).size()
    k3 = ["prev", "gap", "ctx", "code"]
    k2 = ["gap", "ctx", "code"]
    d = d.join(c3.rename("n3"), on=k3).join(c3p.rename("n3p"), on=["provider_id"] + k3)
    d = d.join(c2.rename("n2"), on=k2).join(c2p.rename("n2p"), on=["provider_id"] + k2)
    d = d.join(c1.rename("n1"), on="code").join(c1p.rename("n1p"), on=["provider_id", "code"])
    # context totals
    t3 = d.groupby(["prev", "gap", "ctx"]).size()
    t3p = d.groupby(["provider_id", "prev", "gap", "ctx"]).size()
    t2 = d.groupby(["gap", "ctx"]).size()
    t2p = d.groupby(["provider_id", "gap", "ctx"]).size()
    d = d.join(t3.rename("t3"), on=["prev", "gap", "ctx"]).join(
        t3p.rename("t3p"), on=["provider_id", "prev", "gap", "ctx"]
    )
    d = d.join(t2.rename("t2"), on=["gap", "ctx"]).join(t2p.rename("t2p"), on=["provider_id", "gap", "ctx"])
    N = len(d)
    Np = d.groupby("provider_id").line_id.transform("size")
    n1 = d.n1 - d.n1p
    p1 = (n1 + 1) / (N - Np + V)
    n2 = d.n2 - d.n2p
    tt2 = d.t2 - d.t2p
    p2 = (n2 + beta * p1) / (tt2 + beta)
    n3 = d.n3 - d.n3p
    tt3 = d.t3 - d.t3p
    p3 = (n3 + alpha * p2) / (tt3 + alpha)
    d["p"] = p3.clip(lower=1e-9)
    d["surprisal"] = -np.log2(d.p)
    d["support"] = tt3  # how many comparable transitions (other providers) back the estimate
    # expected surprisal for the same code elsewhere -> excess (removes "rare code" effect)
    d["excess"] = d.surprisal - d.groupby("code").surprisal.transform("median")
    prov = d.groupby("provider_id").agg(
        mean_excess=("excess", "mean"), share_rare=("p", lambda s: float((s < 0.01).mean())), lines=("line_id", "size")
    )
    prov["score"] = prov.mean_excess * prov.lines / (prov.lines + 30) + prov.share_rare * 3
    return d[
        ["line_id", "provider_id", "member_id", "prev", "code", "gap", "ctx", "p", "surprisal", "excess", "support"]
    ], prov


def _pfmt(p):
    return "<0.01%" if p < 1e-4 else f"{p * 100:.2f}%"


def explain_transitions(paths, pid, k=5):
    x = paths[(paths.provider_id == pid)]
    if x.empty:
        return []
    g = (
        x.groupby(["prev", "code", "gap", "ctx"])
        .agg(n=("line_id", "size"), p=("p", "median"), support=("support", "median"), ex=("line_id", "first"))
        .reset_index()
    )
    g["impact"] = g.n * -np.log2(g.p)
    g = g.sort_values("impact", ascending=False).head(k)
    ctx = {0: "", 1: " after coverage ended", 2: " during an inpatient stay", 3: " during a stay after coverage ended"}
    return [
        dict(
            prev=r.prev,
            code=r.code,
            gap=GAP_LABEL[int(r.gap)],
            context=ctx[int(r.ctx)].strip() or "routine",
            lines=int(r.n),
            probability=float(r.p),
            support=int(r.support),
            example=r.ex,
            text=f"{r.code} {GAP_LABEL[int(r.gap)]} after {r.prev}{ctx[int(r.ctx)]}: seen in {_pfmt(r.p)} of comparable journeys elsewhere ({int(r.n)} lines here)",
        )
        for r in g.itertuples()
    ]


# ------------------------------------------------------------------ fusion
def run(L, M, stays, providers, end):
    twin, fit = case_mix_twin(L, M, end)
    paths, path_p = care_pathway(L, M, stays)
    fam = providers.set_index("provider_id").family
    S = pd.DataFrame(index=providers.provider_id)
    S["twin_raw"] = twin.shrunk.reindex(S.index)
    S["path_raw"] = path_p.score.reindex(S.index)
    S["family"] = fam.reindex(S.index)
    for c in ("twin", "path"):
        S[f"{c}_pct"] = S.groupby("family")[f"{c}_raw"].rank(pct=True).fillna(0.5)
        # small families get a pooled ranking blend
        S[f"{c}_pct"] = 0.7 * S[f"{c}_pct"] + 0.3 * S[f"{c}_raw"].rank(pct=True).fillna(0.5)
    S["sentinel"] = (S.twin_pct + S.path_pct) / 2
    S["both_high"] = (S.twin_pct >= 0.85) & (S.path_pct >= 0.85)
    S = S.join(twin[["obs_paid", "exp_paid", "oe_paid", "unexplained_paid", "n_members"]]).join(
        path_p[["mean_excess", "share_rare"]]
    )
    return S, paths, fit
