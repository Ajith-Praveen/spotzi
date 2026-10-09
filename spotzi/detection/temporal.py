"""Temporal behavioural intelligence: how has each provider's behaviour EVOLVED, not just "is it abnormal now?".

Per provider, a monthly trajectory of seven behaviour metrics (volume, paid per member, paid per line, new-patient share,
level-5 visit share, units per line, rule-flag share). Volume is de-seasonalised with a portfolio month index. Each metric
is standardised against the provider's OWN early baseline (median / MAD), then:

  burst        max positive deviation in the last 6 months           (sudden spikes)
  cusum        one-sided CUSUM of the composite deviation             (gradual build-up)
  trend        Theil–Sen slope of the composite over the last 6 months (still rising?)
  sustained    consecutive recent months above the deviation threshold
  onset        first month of the current sustained deviation

and a fraud-stage label (lifecycle, not binary):
  Normal → Behavioural deviation → Emerging anomaly → Sustained anomaly → Established pattern
Stage describes how far a behaviour change has developed (legitimate growth moves through the same stages); combined
with the detectors and context it separates EARLY, still-forming patterns from established ones. It is not a finding of fraud."""

from __future__ import annotations

import numpy as np
import pandas as pd

METRICS = ["volume", "paid_per_member", "paid_per_line", "new_share", "hi_em_share", "units_per_line", "flag_share"]
STAGES = ["Normal", "Behavioural deviation", "Emerging anomaly", "Sustained anomaly", "Established pattern"]


def _theil_sen(y):
    y = np.asarray(y, float)
    n = len(y)
    if n < 3:
        return 0.0
    s = [(y[j] - y[i]) / (j - i) for i in range(n) for j in range(i + 1, n)]
    return float(np.median(s))


def monthly(L: pd.DataFrame) -> pd.DataFrame:
    d = L[["provider_id", "member_id", "service_date", "paid", "code", "units"]].copy()
    d["flag"] = L["any_flag"].astype(float) if "any_flag" in L else 0.0
    d["m"] = d.service_date.dt.to_period("M")
    first = d.groupby(["provider_id", "member_id"]).service_date.transform("min").dt.to_period("M")
    d["new"] = (first == d.m).astype(float)
    em = d.code.isin(["99211", "99212", "99213", "99214", "99215"])
    d["em"] = em.astype(float)
    d["hi"] = (d.code == "99215").astype(float)
    g = d.groupby(["provider_id", "m"])
    M = pd.DataFrame(
        {
            "lines": g.size(),
            "paid": g.paid.sum(),
            "members": g.member_id.nunique(),
            "new": g.new.mean(),
            "em": g.em.sum(),
            "hi": g.hi.sum(),
            "units": g.units.mean(),
            "flag": g.flag.mean(),
        }
    )
    return M


def analyse(L: pd.DataFrame, end, baseline_months=6, recent=6, z_on=2.5) -> pd.DataFrame:
    M = monthly(L)
    months = pd.period_range(L.service_date.min().to_period("M"), pd.Timestamp(end).to_period("M"), freq="M")
    # portfolio seasonal index: median provider volume relative to that provider's mean, by calendar month
    vol = M.lines.unstack().reindex(columns=months)
    rel = vol.div(vol.mean(axis=1), axis=0)
    season = rel.median().groupby([p.month for p in months]).mean()
    season = (season / season.mean()).reindex(range(1, 13)).fillna(1.0)
    out = {}
    for pid, g in M.groupby(level=0):
        g = g.droplevel(0).reindex(months)
        if g.lines.notna().sum() < baseline_months + 3:
            out[pid] = dict(
                temporal_raw=0.0,
                burst=0.0,
                cusum=0.0,
                trend=0.0,
                sustained=0,
                onset=None,
                stage=STAGES[0],
                trend_label="stable",
                months=int(g.lines.notna().sum()),
            )
            continue
        lines = g.lines.fillna(0)
        X = pd.DataFrame(
            {
                "volume": lines / np.array([season[p.month] for p in months]),
                "paid_per_member": (g.paid / g.members).fillna(0),
                "paid_per_line": (g.paid / g.lines).fillna(0),
                "new_share": g.new.fillna(0),
                "hi_em_share": (g.hi / g.em.replace(0, np.nan)).fillna(0),
                "units_per_line": g.units.fillna(0),
                "flag_share": g.flag.fillna(0),
            },
            index=months,
        )
        active = lines.values > 0
        first = int(np.argmax(active))
        base = X.iloc[first : first + baseline_months]
        med = base.median()
        mad = (base - med).abs().median() * 1.4826
        scale = np.maximum(mad.values, np.maximum(0.1 * med.abs().values, np.array([1, 5, 5, 0.03, 0.03, 0.1, 0.02])))
        Z = (X - med.values) / scale
        Z = Z.clip(-6, 8)
        comp = Z.clip(lower=0).apply(
            lambda r: np.sort(r.values)[-2:].mean(), axis=1
        )  # top-2 upward deviations per month
        comp.iloc[: first + baseline_months] = comp.iloc[: first + baseline_months].clip(upper=1.0)
        last = comp.iloc[-recent:]
        burst = float(last.max())
        c, cmax = 0.0, 0.0
        for v in comp.iloc[first + baseline_months :]:
            c = max(0.0, c + v - 1.0)
            cmax = max(cmax, c)
        trend = _theil_sen(last.values)
        above = (comp >= z_on).values
        sustained = 0
        for a in above[::-1]:
            if a:
                sustained += 1
            else:
                break
        onset = str(months[len(months) - sustained]) if sustained else None
        drivers = Z.iloc[-recent:].clip(lower=0).mean().sort_values(ascending=False)
        flag_now = float(X.flag_share.iloc[-recent:].mean())
        if sustained == 0:
            stage = STAGES[1] if burst >= z_on + 0.5 else STAGES[0]
        elif sustained <= 2:
            stage = STAGES[2] if (trend > 0.3 or burst >= z_on + 1.5) else STAGES[1]
        elif sustained <= 5:
            stage = STAGES[3]
        else:
            stage = STAGES[4] if flag_now >= 0.05 or cmax >= 20 else STAGES[3]
        out[pid] = dict(
            temporal_raw=float(0.5 * min(burst, 8) + 0.35 * min(cmax, 40) / 5 + 1.5 * max(0.0, trend)),
            burst=round(burst, 2),
            cusum=round(cmax, 2),
            trend=round(trend, 3),
            sustained=int(sustained),
            onset=onset,
            stage=stage,
            trend_label="rising" if trend > 0.15 else "falling" if trend < -0.15 else "stable",
            drivers=[k for k, v in drivers.items() if v >= 1.5][:3],
            months=int(active.sum()),
        )
    return pd.DataFrame.from_dict(out, orient="index")
