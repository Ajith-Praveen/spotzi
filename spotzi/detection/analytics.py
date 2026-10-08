"""Feature engineering, anomaly detection, 30/60/90-day forecasting and graph analytics."""
from __future__ import annotations

import itertools

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

from detection.rules import RULES

RULE_KEYS = list(RULES)
FAMILIES = ["PRO", "LAB", "FAC", "PHARM", "AMB", "BH", "HH", "DME"]
FEATURES = (["n90", "paid90", "members90", "lines_per_member", "paid_per_line", "any_share", "flag_paid90", "flag_paid30",
             "escalation", "hi_em_share", "ref_conc", "ref_share", "weekend_share", "max_daily_min", "member_growth",
             "prior_inv", "prior_confirmed", "tie_flag", "ties"] + [f"s_{k}" for k in RULE_KEYS])
FEATURE_LABELS = {
    "n90": "Claim-line volume (90d)", "paid90": "Paid dollars (90d)", "members90": "Distinct members (90d)",
    "lines_per_member": "Lines per member", "paid_per_line": "Paid per line", "any_share": "Share of lines flagged by any rule",
    "flag_paid90": "Flagged dollars (90d)", "flag_paid30": "Flagged dollars (30d)", "escalation": "Flagged-dollar escalation (30d vs prior 30d)",
    "hi_em_share": "Share of level-5 visits", "ref_conc": "Referral concentration", "ref_share": "Share of lines with a referral",
    "weekend_share": "Weekend share", "max_daily_min": "Max documented minutes in a day", "member_growth": "Member growth vs prior 90d",
    "prior_inv": "Prior investigations", "prior_confirmed": "Prior confirmed findings", "tie_flag": "Flag rate of linked providers",
    "ties": "Ownership / address / bank links",
    **{f"s_{k}": f"{RULES[k]['name']} rate" for k in RULE_KEYS},
}


def prepare_flags(L: pd.DataFrame, F: pd.DataFrame) -> pd.DataFrame:
    L = L.copy()
    for k in RULE_KEYS:
        L[f"f_{k}"] = F[k].values
    L["any_flag"] = F.any(axis=1).values
    L["flag_paid"] = L.paid * L.any_flag
    return L


def ownership_ties(rel: pd.DataFrame) -> dict[str, set]:
    ties: dict[str, set] = {}
    for _, g in rel.groupby("entity_b"):
        ps = list(g.entity_a)
        if len(ps) > 1:
            for a in ps:
                ties.setdefault(a, set()).update(set(ps) - {a})
    return ties


def snapshot_features(L, T, prov_ids, ties, inv):
    T = pd.Timestamp(T)
    w = L[(L.service_date <= T) & (L.service_date > T - pd.Timedelta(days=90))]
    prior = L[(L.service_date <= T - pd.Timedelta(days=90)) & (L.service_date > T - pd.Timedelta(days=180))]
    g = w.groupby("provider_id")
    X = pd.DataFrame(index=prov_ids)
    X["n90"] = g.size(); X["paid90"] = g.paid.sum(); X["members90"] = g.member_id.nunique()
    X = X.fillna(0)
    X["lines_per_member"] = X.n90 / X.members90.clip(lower=1)
    X["paid_per_line"] = X.paid90 / X.n90.clip(lower=1)
    X["any_share"] = g.any_flag.mean()
    X["flag_paid90"] = g.flag_paid.sum()
    last30 = w[w.service_date > T - pd.Timedelta(days=30)].groupby("provider_id").flag_paid.sum()
    prev30 = w[w.service_date <= T - pd.Timedelta(days=30)]
    prev30 = prev30[prev30.service_date > T - pd.Timedelta(days=60)].groupby("provider_id").flag_paid.sum()
    X["flag_paid30"] = last30; X["escalation"] = (last30.reindex(X.index).fillna(0) - prev30.reindex(X.index).fillna(0)) / (prev30.reindex(X.index).fillna(0) + 500)
    em = w[w.code.isin(["99212", "99213", "99214", "99215"])]
    X["hi_em_share"] = em.groupby("provider_id").code.apply(lambda s: (s == "99215").mean())
    rf = w[w.referring_provider_id.notna()]
    c = rf.groupby(["provider_id", "referring_provider_id"]).size()
    tot = c.groupby(level=0).sum(); top = c.groupby(level=0).max()
    X["ref_conc"] = (top / tot).where(tot >= 10)
    X["ref_share"] = rf.groupby("provider_id").size() / X.n90.clip(lower=1)
    X["weekend_share"] = g.service_date.apply(lambda s: (s.dt.dayofweek >= 5).mean())
    X["max_daily_min"] = w.groupby(["provider_id", "service_date"]).duration_min.sum().groupby(level=0).max()
    pm = prior.groupby("provider_id").member_id.nunique()
    X["member_growth"] = np.log1p(X.members90) - np.log1p(pm.reindex(X.index).fillna(0))
    done = inv[pd.to_datetime(inv.closed_date) <= T]
    X["prior_inv"] = done.groupby("provider_id").size()
    X["prior_confirmed"] = done[done.outcome.str.startswith("Confirmed")].groupby("provider_id").size()
    for k in RULE_KEYS:
        X[f"s_{k}"] = g[f"f_{k}"].mean()
    X["ties"] = [len(ties.get(p, ())) for p in X.index]
    X = X.fillna(0)
    X["tie_flag"] = [max([X.any_share.get(q, 0) for q in ties.get(p, ())] or [0]) for p in X.index]
    # a provider whose single dominant referrer is itself flagged inherits a little of that signal
    top_ref = c.groupby(level=0).idxmax().map(lambda t: t[1]) if len(c) else pd.Series(dtype=object)
    X["tie_flag"] = np.maximum(X.tie_flag, [X.any_share.get(top_ref.get(p), 0) * (X.ref_conc[p] > .5) for p in X.index])
    return X


def snapshot_dates(end, step=14, first=None):
    """Bi-weekly anchors over the last ~14 months of data (relative to the data, not the calendar)."""
    first = pd.Timestamp(first) if first is not None else pd.Timestamp(end) - pd.Timedelta(days=427)
    d, out = pd.Timestamp(end), []
    while d >= pd.Timestamp(first):
        out.append(d); d -= pd.Timedelta(days=step)
    return sorted(out)


def build_panel(L, prov_ids, ties, inv, end, truth_lines):
    snaps = snapshot_dates(end)
    parts = []
    for T in snaps:
        X = snapshot_features(L, T, prov_ids, ties, inv); X["snap"] = T; X["provider_id"] = X.index
        parts.append(X)
    panel = pd.concat(parts, ignore_index=True)
    return panel, snaps


def label_panel(panel, truth_lines, horizon, end):
    tl = truth_lines[["provider_id", "service_date"]].copy()
    y = np.full(len(panel), np.nan)
    ends = panel.snap + pd.Timedelta(days=horizon)
    ok = ends <= pd.Timestamp(end)
    key = tl.groupby("provider_id").service_date.apply(lambda s: np.sort(s.values.astype("datetime64[D]")))
    for i in np.where(ok)[0]:
        arr = key.get(panel.provider_id.iat[i])
        if arr is None: y[i] = 0; continue
        a = np.datetime64(panel.snap.iat[i].date()); b = np.datetime64(ends.iat[i].date())
        n = np.searchsorted(arr, b, side="right") - np.searchsorted(arr, a, side="right")
        y[i] = 1.0 if n >= 3 else 0.0
    return y


def _fam_dummies(panel, prov_family):
    fam = panel.provider_id.map(prov_family)
    return pd.DataFrame({f"fam_{f}": (fam == f).astype(float) for f in FAMILIES}, index=panel.index)


def _ece(y, p, bins=5):
    q = pd.qcut(pd.Series(p).rank(method="first"), bins, labels=False, duplicates="drop")
    d = pd.DataFrame({"y": y, "p": p, "q": q}).groupby("q").agg(n=("y", "size"), y=("y", "mean"), p=("p", "mean"))
    return float((d.n * (d.y - d.p).abs()).sum() / d.n.sum()), d


def train_forecasts(panel, prov_family, truth_lines, end, groups=None):
    """Discrete-time hazard model (doc 10). Intervals (0,30],(30,60],(60,90]; covariates frozen at the anchor;
    P30=h1, P60=1-(1-h1)(1-h2), P90=1-(1-h1)(1-h2)(1-h3) so horizons can never contradict each other.
    Baseline: pooled logistic hazard. Challenger: pooled gradient-boosting hazard. Both sigmoid-calibrated with
    provider-group cross-fitting on the TRAINING period only; evaluation is a temporal, purged holdout."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import GroupKFold
    from sklearn.metrics import log_loss
    end = pd.Timestamp(end)
    base_cols = FEATURES + [f"fam_{f}" for f in FAMILIES]
    X0 = pd.concat([panel[FEATURES], _fam_dummies(panel, prov_family)], axis=1)
    tl = truth_lines[["provider_id", "service_date"]]
    arr = tl.groupby("provider_id").service_date.apply(lambda s: np.sort(s.values.astype("datetime64[D]")))
    def count(pid, a, b):
        x = arr.get(pid)
        return 0 if x is None else int(np.searchsorted(x, np.datetime64(b.date()), side="right") - np.searchsorted(x, np.datetime64(a.date()), side="right"))
    anchors = sorted(panel.snap.unique())
    full = [T for T in anchors if T + pd.Timedelta(days=90) <= end]
    rows = []
    active = (panel.n90 >= 5).values
    for i in np.where(panel.snap.isin(full).values & active)[0]:
        T, pid = panel.snap.iat[i], panel.provider_id.iat[i]
        ev = []
        for k in (1, 2, 3):
            c = count(pid, T + pd.Timedelta(days=30 * (k - 1)), T + pd.Timedelta(days=30 * k))
            ev.append(int(c >= 2))
        rows.append((i, T, pid, ev))
    cut = end - pd.Timedelta(days=259)   # same split as the original calendar (relative to the data end)
    eval_from = cut + pd.Timedelta(days=90)
    def expand(sel):
        r_, y_, g_ = [], [], []
        for i, T, pid, ev in sel:
            for k in (1, 2, 3):
                r_.append((i, k)); y_.append(ev[k - 1]); g_.append(pid)
                if ev[k - 1]: break
        idx = np.array([i for i, _ in r_]); ks = np.array([k for _, k in r_])
        X = X0.iloc[idx].reset_index(drop=True).copy()
        for k in (1, 2, 3): X[f"int{k}"] = (ks == k).astype(float)
        return X, np.array(y_), np.array(g_), idx, ks
    tr = [r for r in rows if r[1] <= cut]
    te = [r for r in rows if r[1] >= eval_from]
    Xtr, ytr, gtr, _, _ = expand(tr)
    def make(kind):
        if kind == "logistic":
            from sklearn.pipeline import make_pipeline
            return make_pipeline(StandardScaler(), LogisticRegression(C=.4, max_iter=800))
        return HistGradientBoostingClassifier(max_depth=3, learning_rate=.06, max_iter=120, l2_regularization=1.0, min_samples_leaf=30, random_state=0)
    def fit_cal(X, y, g, kind):
        splits = list(GroupKFold(5).split(X, y, g))
        splits = [s_ for s_ in splits if len(set(y[s_[0]])) > 1]
        m = CalibratedClassifierCV(make(kind), method="sigmoid", cv=splits) if len(splits) >= 3 else make(kind).fit(X, y)
        return m.fit(X, y) if hasattr(m, "classes_") is False or isinstance(m, CalibratedClassifierCV) else m
    models = {k: fit_cal(Xtr, ytr, gtr, k) for k in ("logistic", "gboost")}
    cvll = {}
    for k, mdl in models.items():
        cvll[k] = float(log_loss(ytr, np.clip(mdl.predict_proba(Xtr)[:, 1], 1e-4, 1 - 1e-4)))
    chosen = min(cvll, key=cvll.get)  # frozen rule: lower training-period log loss
    def hazards(models_, X1):
        """X1 = anchor-level feature frame; return n×3 hazards"""
        out = []
        for k in (1, 2, 3):
            Xk = X1.copy()
            for j in (1, 2, 3): Xk[f"int{j}"] = float(j == k)
            out.append(models_.predict_proba(Xk)[:, 1])
        return np.column_stack(out)
    def cumul(h):
        s1 = 1 - h[:, 0]; s2 = s1 * (1 - h[:, 1]); s3 = s2 * (1 - h[:, 2])
        return np.column_stack([1 - s1, 1 - s2, 1 - s3])
    res = {"metrics": {}, "pred": {}, "why": {}, "calibration": {}, "model_choice": dict(chosen=chosen, cv_logloss=cvll, train_anchors=len({r[1] for r in tr}), eval_anchors=len({r[1] for r in te}), cut=str(cut.date()), eval_from=str(eval_from.date()))}
    if te:
        idx = np.array([r[0] for r in te]); X1 = X0.iloc[idx].reset_index(drop=True)
        Yc = np.array([[int(any(r[3][:k])) for k in (1, 2, 3)] for r in te])
        P = {k: cumul(hazards(m, X1)) for k, m in models.items()}
        flag = panel.iloc[idx].any_share.values
        for j, H in enumerate((30, 60, 90)):
            y = Yc[:, j]
            if len(set(y)) < 2: continue
            met = dict(test_rows=int(len(y)), positives=int(y.sum()), base_rate=float(y.mean()), train_anchors=res["model_choice"]["train_anchors"], eval_anchors=res["model_choice"]["eval_anchors"])
            for k in P:
                e, _ = _ece(y, P[k][:, j])
                met[k] = dict(auc=float(roc_auc_score(y, P[k][:, j])), ap=float(average_precision_score(y, P[k][:, j])), brier=float(brier_score_loss(y, P[k][:, j])), ece=e)
            met["baseline_auc_flag_share"] = float(roc_auc_score(y, flag))
            ch = met[chosen]; met.update(auc=ch["auc"], ap=ch["ap"], brier=ch["brier"], ece=ch["ece"], chosen=chosen)
            res["metrics"][H] = met
            _, d = _ece(y, P[chosen][:, j])
            res["calibration"][H] = [dict(bin=str(i), n=int(r.n), predicted=float(r.p), observed=float(r.y)) for i, r in d.iterrows()]
    # production: refit on all fully observed anchors (hyper-parameters frozen), then predict at the as-of date
    Xall, yall, gall, _, _ = expand(rows)
    prod = fit_cal(Xall, yall, gall, chosen)
    lr_all = fit_cal(Xall, yall, gall, "logistic")
    cur = (panel.snap == end).values
    Xc = X0[cur].reset_index(drop=True)
    pids = panel.provider_id[cur].tolist()
    H3 = hazards(prod, Xc); C = cumul(H3)
    # local explanation from the pooled logistic hazard (coef × standardised value), horizon-specific via interval
    pipe = make("logistic").fit(Xall, yall)
    sc, lrm = pipe.steps[0][1], pipe.steps[1][1]
    names = list(Xall.columns)
    for n_, pid in enumerate(pids):
        res["pred"][pid] = {30: float(np.clip(C[n_, 0], .01, .97)), 60: float(np.clip(C[n_, 1], .01, .97)), 90: float(np.clip(C[n_, 2], .01, .97))}
        res["pred"][pid]["hazards"] = [float(x) for x in H3[n_]]
        row = Xc.iloc[[n_]].copy()
        for j in (1, 2, 3): row[f"int{j}"] = 0.0
        row["int1"] = 1.0
        ct = lrm.coef_[0] * sc.transform(row[names])[0]
        order = [i for i in np.argsort(-ct)[:6] if names[i] in FEATURE_LABELS or names[i].startswith("fam_")][:4]
        why = [dict(feature=FEATURE_LABELS.get(names[i], names[i].replace("fam_", "Family: ")), contribution=float(ct[i]), value=float(row[names[i]].iloc[0])) for i in order if ct[i] > .05]
        res["why"][pid] = {30: why, 60: why, 90: why}
    for pid in list(res["pred"]):
        p = res["pred"][pid]; p[60] = max(p[60], p[30]); p[90] = max(p[90], p[60])
    return res


def anomaly_scores(X_end, prov_family):
    """Isolation Forest on peer-normalised provider features. Returns percentile (0-1) per provider."""
    cols = ["n90", "paid90", "members90", "lines_per_member", "paid_per_line", "hi_em_share", "ref_conc", "weekend_share",
            "max_daily_min", "member_growth", "any_share"]
    Z = X_end[cols].copy()
    Z["n90"] = np.log1p(Z.n90); Z["paid90"] = np.log1p(Z.paid90); Z["paid_per_line"] = np.log1p(Z.paid_per_line)
    fam = pd.Series(prov_family).reindex(Z.index).fillna("UNK")

    def _norm(col):
        med = col.median(); spread = col.quantile(.75) - col.quantile(.25)
        if not spread or pd.isna(spread): spread = col.std()
        if not spread or pd.isna(spread): spread = 1.0
        return ((col - med) / spread).clip(-8, 8)
    Z = Z.astype(float).groupby(fam).transform(_norm)
    Z = Z.fillna(0)
    iso = IsolationForest(n_estimators=300, contamination="auto", random_state=0).fit(Z)
    raw = -iso.decision_function(Z)
    pct = pd.Series(raw, index=Z.index).rank(pct=True)
    drivers = {}
    for pid in Z.index:
        z = Z.loc[pid]
        top = z.abs().sort_values(ascending=False).head(3)
        drivers[pid] = [dict(feature=FEATURE_LABELS.get(k, k), peer_z=float(z[k])) for k in top.index if abs(z[k]) >= 1.5]
    return pct, pd.Series(raw, index=Z.index), drivers


def claim_anomaly(L):
    d = pd.DataFrame(index=L.index)
    d["lp"] = np.log1p(L.paid)
    price_ratio = L.paid / L.groupby("code").paid.transform("median").replace(0, 1)
    d["pr"] = price_ratio.clip(0, 10)
    d["lu"] = np.log1p(L.units)
    d["dur"] = L.duration_min
    d["start"] = L.start_min
    d["wk"] = (L.service_date.dt.dayofweek >= 5).astype(int)
    s = L.sort_values(["member_id", "code", "service_date"])
    gap = s.groupby(["member_id", "code"]).service_date.diff().dt.days
    d["gap"] = np.log1p(gap.reindex(L.index).fillna(400))
    d["pd_cnt"] = np.log1p(L.groupby(["provider_id", "service_date"]).line_id.transform("size"))
    d["m_cnt"] = np.log1p(L.groupby(["member_id", "provider_id"]).line_id.transform("size"))
    iso = IsolationForest(n_estimators=200, contamination=.02, random_state=0, n_jobs=-1).fit(d)
    return pd.Series(-iso.decision_function(d), index=L.index).rank(pct=True)


# ---------------------------------------------------------------- graph
def build_graph(L, providers, rel, risk, end):
    """Provider graph: referral edges, shared ownership/address/bank, shared-member overlap."""
    pid_name = providers.set_index("provider_id").name.to_dict()
    G = nx.Graph()
    for p, r in providers.set_index("provider_id").iterrows():
        G.add_node(p, kind="provider", label=r["name"], family=r.family, city=r.city, risk=float(risk.get(p, 0)))
    ref = L[L.referring_provider_id.notna()].groupby(["referring_provider_id", "provider_id"]).agg(n=("line_id", "size"), paid=("paid", "sum")).reset_index()
    recv_tot = L[L.referring_provider_id.notna()].groupby("provider_id").size()
    ref["share"] = ref.n / ref.provider_id.map(recv_tot)
    edges = []
    for r in ref.itertuples():
        if r.n >= 8 and r.share >= .15:
            edges.append((r.referring_provider_id, r.provider_id, dict(kind="referral", n=int(r.n), paid=float(r.paid), share=float(r.share), strong=bool(r.share >= .35 and r.n >= 25))))
    for e in rel.groupby(["entity_b", "relationship_type"]):
        (ent, typ), g = e
        ps = list(g.entity_a)
        for a, b in itertools.combinations(ps, 2):
            edges.append((a, b, dict(kind={"owned_by": "ownership", "located_at": "address", "paid_to_account": "bank"}[typ], via=ent, strong=True)))
    # shared members among non-trivial providers
    mem = L.groupby(["provider_id", "member_id"]).size().reset_index()
    pidx = {p: i for i, p in enumerate(sorted(mem.provider_id.unique()))}
    midx = {m: i for i, m in enumerate(mem.member_id.unique())}
    from scipy import sparse
    M = sparse.csr_matrix((np.ones(len(mem)), (mem.provider_id.map(pidx), mem.member_id.map(midx))), shape=(len(pidx), len(midx)))
    S = (M @ M.T).tocoo()
    sizes = np.asarray(M.sum(axis=1)).ravel()
    inv = {i: p for p, i in pidx.items()}
    for i, j, v in zip(S.row, S.col, S.data):
        if i < j and v >= 25:
            jac = v / (sizes[i] + sizes[j] - v)
            if jac >= .25:
                edges.append((inv[i], inv[j], dict(kind="shared_members", n=int(v), jaccard=float(jac), strong=False)))
    for a, b, d in edges:
        if a in G and b in G:
            if G.has_edge(a, b):
                G[a][b].setdefault("multi", []).append(d)
            else:
                G.add_edge(a, b, multi=[d])
    return G, ref


def tie_graph(G, rs):
    """Subgraph of 'suspicious ties': ownership/address/bank, strong referral dependence on a flagged party,
    and large shared-member overlap between two already-flagged providers."""
    H = nx.Graph()
    for a, b, d in G.edges(data=True):
        kinds = {m["kind"] for m in d["multi"]}
        keep = set(kinds & {"ownership", "address", "bank"})
        if any(m["kind"] == "referral" and m.get("strong") for m in d["multi"]) and max(rs.get(a, 0), rs.get(b, 0)) >= .25:
            keep.add("referral")
        if "shared_members" in kinds and min(rs.get(a, 0), rs.get(b, 0)) >= .2:
            keep.add("shared_members")
        if keep:
            H.add_edge(a, b, kinds=sorted(keep))
    return H


def layout(sub, seed=3):
    if len(sub) == 0: return {}
    if len(sub) == 1: return {n: (0.0, 0.0) for n in sub}
    try:
        if len(sub) <= 70:
            pos = nx.kamada_kawai_layout(sub)
        else:
            pos = nx.spring_layout(sub, seed=seed, k=2.2 / np.sqrt(len(sub)), iterations=200)
    except Exception:
        pos = nx.spring_layout(sub, seed=seed)
    return {n: (float(x), float(y)) for n, (x, y) in pos.items()}


def communities(G):
    from networkx.algorithms.community import louvain_communities
    Gw = nx.Graph()
    for a, b, d in G.edges(data=True):
        w = sum({"referral": 1.5, "ownership": 3, "address": 3, "bank": 3, "shared_members": 1}[m["kind"]] for m in d["multi"])
        Gw.add_edge(a, b, weight=w)
    comms = louvain_communities(Gw, weight="weight", seed=11, resolution=1.1)
    return [sorted(c) for c in comms if len(c) >= 2]
