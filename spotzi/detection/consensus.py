"""Detector consensus, evidence diversity, data quality and out-of-distribution checks.

Fusion answers "how suspicious?". Consensus answers "how much independent evidence says so?":
  * firing detectors — each detector's one-sided verdict (high percentile)
  * evidence families — detectors grouped by what they look at; families whose scores are strongly correlated in the
    current portfolio are merged, so five detectors reading the same signal count once
  * effective independent detectors — participation ratio of the eigenvalues of the firing detectors' correlation matrix
Data quality: per-provider completeness / consistency score; poor data caps confidence.
Out-of-distribution: robust Mahalanobis distance of the provider's behaviour profile from the reference population the
models were trained on; OOD caps confidence ("the model has not seen anything like this").
None of this changes a score — it changes how much the score should be trusted."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import chi2

DETECTORS = {  # key: (column, a-priori evidence family, firing threshold)
    "rules": ("rule_score", "billing rules", .35), "iforest": ("anomaly_pct", "peer statistics", .9), "peer": ("peer_pct", "peer statistics", .9),
    "graph": ("graph_score", "network", .5), "twin": ("twin_pct", "clinical models", .9), "path": ("path_pct", "clinical models", .9),
    "drift": ("drift_pct", "behaviour over time", .9), "temporal": ("temporal_pct", "behaviour over time", .9), "mix": ("mix_pct", "service mix", .9),
    "panel": ("panel_pct", "patient panel", .75),
}


def correlation(PT, min_lines=15):
    cols = {k: v[0] for k, v in DETECTORS.items() if v[0] in PT}
    X = PT[PT.n_lines >= min_lines][list(cols.values())].astype(float)
    C = X.rank().corr().fillna(0)
    C.index = C.columns = list(cols)
    return C


def families(C, merge_at=.7):
    fam = {k: DETECTORS[k][1] for k in C.index}
    parent = {f: f for f in set(fam.values())}

    def find(f):
        while parent[f] != f: f = parent[f]
        return f
    for a in C.index:
        for b in C.index:
            if a < b and C.at[a, b] >= merge_at: parent[find(fam[a])] = find(fam[b])
    return {k: find(f) for k, f in fam.items()}


def effective_n(C):
    if len(C) == 0: return 0.0
    lam = np.clip(np.linalg.eigvalsh(C.values), 0, None)
    return float(lam.sum() ** 2 / (lam ** 2).sum()) if lam.sum() > 0 else 0.0


def data_quality(W: pd.DataFrame) -> pd.Series:
    vocab = W.code.value_counts(); known = set(vocab[vocab >= 3].index)
    d = pd.DataFrame({"provider_id": W.provider_id,
                      "dx": W.dx.isna() if "dx" in W else False,
                      "code": ~W.code.isin(known),
                      "dates": (W.service_end_date < W.service_date) | (W.paid_date < W.service_end_date),
                      "paid": W.paid <= 0,
                      "ref": W.family.isin(["LAB", "PHARM", "DME"]) & W.referring_provider_id.isna()})
    g = d.groupby("provider_id").mean()
    penalty = .6 * g.dx + 1.2 * g.code + 1.2 * g.dates + 1.0 * g.paid + .3 * g.ref     # invalid codes / impossible dates weigh most
    return (1 - penalty).clip(0, 1)


def ood(profile: pd.DataFrame, reference: dict | None):
    """profile: provider × behaviour features. reference: {"cols", "mean", "cov_inv", "dof"} from training worlds; None → portfolio itself."""
    X = np.log1p(profile.clip(lower=0).fillna(0))
    if reference:
        cols = [c for c in reference["cols"] if c in X]; X = X[cols]
        mu = np.array([reference["mean"][c] for c in cols]); ci = np.array(reference["cov_inv"])[[reference["cols"].index(c) for c in cols]][:, [reference["cols"].index(c) for c in cols]]
    else:
        med = X.median(); mad = (X - med).abs().median() * 1.4826 + 1e-6
        Xs = X[((X - med).abs() / mad).max(axis=1) < 6]
        mu = Xs.mean().values; ci = np.linalg.pinv(np.cov(Xs.values, rowvar=False) + 1e-6 * np.eye(X.shape[1]))
    D = X.values - mu
    d2 = np.einsum("ij,jk,ik->i", D, ci, D)
    p = chi2.sf(d2, df=X.shape[1])
    return pd.DataFrame({"ood_d2": d2, "ood_p": p, "ood": p < 1e-3}, index=X.index)


def assess(PT: pd.DataFrame, dq: pd.Series, oodf: pd.DataFrame | None, C=None):
    C = correlation(PT) if C is None else C
    fam = families(C)
    rows = {}
    for pid in PT.index:
        firing = [k for k, (col, _, th) in DETECTORS.items() if col in PT and PT.at[pid, col] == PT.at[pid, col] and PT.at[pid, col] >= th]
        fams = sorted({fam.get(k, DETECTORS[k][1]) for k in firing})
        n_eff = effective_n(C.loc[[k for k in firing if k in C.index], [k for k in firing if k in C.index]]) if firing else 0.0
        q = float(dq.get(pid, 1.0)); o = bool(oodf.at[pid, "ood"]) if oodf is not None and pid in oodf.index else False
        if len(fams) >= 3 and q >= .8 and not o: conf = "High"
        elif len(fams) >= 2 and q >= .6: conf = "Moderate"
        else: conf = "Low"
        caps = ([f"data quality {q:.0%}"] if q < .6 else []) + (["profile is out of distribution for the trained models"] if o else [])
        rows[pid] = dict(n_firing=len(firing), firing=firing, families=fams, n_families=len(fams), n_eff=round(n_eff, 2), dq=round(q, 3), ood=o,
                         consensus=conf, consensus_text=f"{len(firing)} of {len(DETECTORS)} detectors fire · {len(fams)} independent evidence famil{'y' if len(fams) == 1 else 'ies'}"
                         + (f" · effective {n_eff:.1f}" if firing else "") + ("; capped: " + ", ".join(caps) if caps else ""))
    return pd.DataFrame.from_dict(rows, orient="index"), dict(correlation=C.round(3).to_dict(), families=fam, effective_detectors=round(effective_n(C), 2))


def psi(a, b, bins=10):
    """Population stability index of sample a (current) vs b (reference)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 10 or len(b) < 10: return None
    edges = np.unique(np.quantile(b, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3: return 0.0
    pa = np.histogram(np.clip(a, edges[0], edges[-1]), edges)[0] / len(a) + 1e-4
    pb = np.histogram(b, edges)[0] / len(b) + 1e-4
    return float(np.sum((pa - pb) * np.log(pa / pb)))


def drift(profile: pd.DataFrame, reference: dict) -> dict:
    """Concept-drift / population-shift monitor: PSI of each behaviour feature vs the training reference histogram."""
    X = np.log1p(profile.clip(lower=0).fillna(0))
    out = {}
    for c, h in (reference.get("hist") or {}).items():
        if c not in X: continue
        cur = np.histogram(X[c].values, np.array(h["edges"]))[0] / max(1, len(X)) + 1e-4
        ref = np.array(h["share"]) + 1e-4
        out[c] = round(float(np.sum((cur - ref) * np.log(cur / ref))), 3)
    worst = max(out.values()) if out else 0
    return dict(psi=out, max_psi=worst, status="drift" if worst >= .25 else "watch" if worst >= .1 else "stable",
                shifted=[k for k, v in out.items() if v >= .25],
                note="PSI ≥ 0.25 = significant shift: review / recalibrate models; 0.1–0.25 = monitor.")
