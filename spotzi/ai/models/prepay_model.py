"""Pre-payment line-risk model (task model #1).

Purpose: score each incoming claim line BEFORE payment, using only what is known at that moment (the line itself and
already-paid history). Complements the deterministic pre-payment rules: it learns combinations no single rule encodes.
Training: supervised gradient boosting on labelled lines from independent synthetic training worlds (different generator
seeds from the demo data). Test: the demo world and the public-data evaluation workspaces, which it never saw."""
from __future__ import annotations

import numpy as np
import pandas as pd

# Only behaviour that means the same thing in any claims system: no family one-hots or data-completeness artefacts
# (an early version used them and scored AUC 0.3 on DE-SynPUF — it had learned the generator, not the fraud).
FEATURES = ["units", "units_rel", "age", "after_death", "after_term", "during_stay", "same_day_repeat", "days_since_prev", "prov_day_rel",
            "prov_day_hours", "mem_day_lines", "em_level", "prov_month_hi", "prov_new_share", "new_patient", "dur_ratio", "pos_inpatient", "pos_home"]
LABELS = {"units_rel": "units vs typical for the code", "after_death": "service after death", "after_term": "service after coverage ended", "during_stay": "billed during an inpatient stay",
          "same_day_repeat": "same code, member, provider and day already billed", "days_since_prev": "days since the member's previous same service",
          "prov_day_rel": "provider volume that day vs its normal", "prov_new_share": "provider's share of first-time patients that month", "prov_day_hours": "provider documented hours that day", "mem_day_lines": "member lines that day",
          "em_level": "E/M level", "prov_month_hi": "provider level-5 share that month", "new_patient": "first visit with this provider", "dur_ratio": "documented minutes vs code time"}


def code_stats(L) -> dict:
    u = L.groupby("code").units.quantile(.95)
    return dict(u95=u[u.index.isin(L.code.value_counts()[lambda s: s >= 20].index)].to_dict())


def features(U: pd.DataFrame, members: pd.DataFrame, stays: pd.DataFrame, stats: dict, code_minutes: dict) -> pd.DataFrame:
    """U = history + lines to score (all rows get features; callers keep the rows they need)."""
    U = U.copy()
    U["service_date"] = pd.to_datetime(U.service_date); U["code"] = U.code.astype(str)
    M = members.set_index("member_id")
    X = pd.DataFrame(index=U.index)
    X["units"] = pd.to_numeric(U.units, errors="coerce").fillna(1)
    X["units_rel"] = X.units / U.code.map(stats["u95"]).fillna(X.units).clip(lower=1)
    X["age"] = U.member_id.map(M.age).fillna(60)
    dd = pd.to_datetime(U.member_id.map(M.death_date)); td = pd.to_datetime(U.member_id.map(M.term_date)) if "term_date" in M else pd.Series(pd.NaT, index=U.index)
    X["after_death"] = (dd.notna() & (U.service_date > dd)).astype(int)
    X["after_term"] = (td.notna() & (U.service_date > td)).astype(int)
    X["during_stay"] = 0
    if stays is not None and len(stays):
        s = stays[["member_id", "admit_date", "discharge_date"]].copy()
        s["admit_date"] = pd.to_datetime(s.admit_date); s["discharge_date"] = pd.to_datetime(s.discharge_date)
        cand = U[(U.pos.astype(str) != "21") & ~U.family.isin(["FAC", "INST"])][["member_id", "service_date"]].reset_index()
        j = cand.merge(s, on="member_id")
        hit = j[(j.service_date > j.admit_date) & (j.service_date < j.discharge_date)]["index"].unique()
        X.loc[hit, "during_stay"] = 1
    X["same_day_repeat"] = (U.groupby(["member_id", "provider_id", "code", "service_date"]).code.transform("size") - 1).clip(upper=5)
    o = U.sort_values("service_date")
    prev = o.groupby(["member_id", "code"]).service_date.shift()
    X["days_since_prev"] = ((o.service_date - prev).dt.days.reindex(U.index)).fillna(400).clip(upper=400)
    pdl = U.groupby(["provider_id", "service_date"]).code.transform("size")
    X["prov_day_rel"] = np.log(pdl / pdl.groupby(U.provider_id).transform("median").clip(lower=1))   # busy day vs the provider's own normal
    dur = pd.to_numeric(U.get("duration_min", 0), errors="coerce").fillna(0)
    X["prov_day_hours"] = dur.groupby([U.provider_id, U.service_date]).transform("sum") / 60
    X["mem_day_lines"] = U.groupby(["member_id", "service_date"]).code.transform("size").clip(upper=20)
    lvl = U.code.map({"99211": 1, "99212": 2, "99213": 3, "99214": 4, "99215": 5})
    X["em_level"] = lvl.fillna(0)
    ym = U.service_date.dt.to_period("M")
    isem = lvl.notna()
    hi = (lvl == 5).astype(float).where(isem)
    X["prov_month_hi"] = hi.groupby([U.provider_id, ym]).transform("mean").fillna(0)
    first = U.groupby(["member_id", "provider_id"]).service_date.transform("min")
    X["new_patient"] = (U.service_date == first).astype(int)
    X["prov_new_share"] = X.new_patient.groupby([U.provider_id, ym]).transform("mean")
    exp = U.code.map(code_minutes).fillna(0)
    X["dur_ratio"] = np.where(exp > 0, dur / exp.replace(0, np.nan), 1.0)
    X["dur_ratio"] = X.dur_ratio.fillna(1.0)
    X["pos_inpatient"] = (U.pos.astype(str) == "21").astype(int); X["pos_home"] = U.pos.astype(str).isin(["12", "13"]).astype(int)
    return X[FEATURES].astype(float)


def fit(X, y):
    from sklearn.ensemble import HistGradientBoostingClassifier
    w = np.where(y == 1, (y == 0).sum() / max(1, (y == 1).sum()), 1.0) ** .5
    m = HistGradientBoostingClassifier(max_depth=5, learning_rate=.08, max_iter=300, l2_regularization=1.0, min_samples_leaf=40, random_state=0)
    return m.fit(X, y, sample_weight=w)


def explain(m, x: pd.DataFrame, k=3):
    """Local explanation: change in probability when each feature is reset to its training median (occlusion)."""
    base = m.predict_proba(x)[:, 1][0]; med = m._spotzi_median
    out = []
    for f in FEATURES:
        if x[f].iat[0] == med[f]: continue
        z = x.copy(); z[f] = med[f]
        out.append((f, float(base - m.predict_proba(z)[:, 1][0])))
    return [dict(feature=LABELS.get(f, f), value=float(x[f].iat[0]), effect=round(e, 3)) for f, e in sorted(out, key=lambda t: -t[1])[:k] if e > .02]
