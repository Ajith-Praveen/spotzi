"""Hierarchical peer baselines with empirical-Bayes shrinkage.

A cardiologist should be compared with cardiology peers, not with every professional provider. But a specialty with
three providers is too small to trust on its own. So each provider's EXPECTED behaviour cascades down a hierarchy

    portfolio → service family → family × region → family × specialty

and at every level the peer mean is shrunk toward the level above by n / (n + k) (leave-one-out, so a provider never
shapes its own baseline). Deviation = (observed − expected) / shrunk spread, per metric; the peer score is the
root-mean-square of the upward deviations. Drivers name the metric and the peer group actually used."""

from __future__ import annotations

import numpy as np
import pandas as pd

METRICS = {
    "lines_per_member": "services per patient",
    "paid_per_member": "paid per patient",
    "paid_per_line": "paid per service",
    "hi_em_share": "level-5 visit share",
    "units_per_line": "units per service",
    "new_share": "new-patient share",
    "codes_per_member": "distinct services per patient",
}
K = 8.0


def features(W: pd.DataFrame) -> pd.DataFrame:
    g = W.groupby("provider_id")
    first = W.groupby(["provider_id", "member_id"]).service_date.transform("min")
    em = W.code.isin(["99212", "99213", "99214", "99215"])
    F = pd.DataFrame(
        {
            "lines": g.size(),
            "members": g.member_id.nunique(),
            "paid": g.paid.sum(),
            "units": g.units.mean(),
            "em": em.groupby(W.provider_id).sum(),
            "hi": (W.code == "99215").groupby(W.provider_id).sum(),
            "new": (W.service_date == first).groupby(W.provider_id).mean(),
            "codes": g.code.nunique(),
        }
    )
    return pd.DataFrame(
        {
            "lines_per_member": F.lines / F.members,
            "paid_per_member": F.paid / F.members,
            "paid_per_line": F.paid / F.lines,
            "hi_em_share": (F.hi / F.em.replace(0, np.nan)),
            "units_per_line": F.units,
            "new_share": F.new,
            "codes_per_member": F.codes / F.members,
            "n_lines": F.lines,
        }
    )


def _loo(stat_sum, stat_sq, n, x):
    """leave-one-out mean / sd for each member of a group"""
    n1 = (n - 1).clip(lower=1)
    m = (stat_sum - x) / n1
    v = ((stat_sq - x**2) / n1 - m**2).clip(lower=0)
    return m, np.sqrt(v), n - 1


def score(W: pd.DataFrame, providers: pd.DataFrame, min_lines=15) -> tuple[pd.DataFrame, dict]:
    F = features(W)
    P = providers.set_index("provider_id").reindex(F.index)
    F["family"] = P.family.fillna("?")
    F["region"] = P.city.fillna("?")
    F["specialty"] = P.specialty.fillna("?")
    F = F[F.n_lines >= min_lines].copy()
    levels = [("family",), ("family", "region"), ("family", "specialty")]
    Z, used = pd.DataFrame(index=F.index), {}
    for m in METRICS:
        x = F[m].astype(float)
        ok = x.notna()
        mu = pd.Series(float(x[ok].median()), index=F.index)
        sd = pd.Series(float((x[ok] - x[ok].median()).abs().median() * 1.4826 or x[ok].std() or 1.0), index=F.index)
        grp = pd.Series("portfolio", index=F.index)
        for lv in levels:
            key = F[list(lv)].astype(str).agg("|".join, axis=1)
            xs = x.where(ok)
            s = xs.groupby(key).transform("sum")
            s2 = (xs**2).groupby(key).transform("sum")
            n = xs.notna().groupby(key).transform("sum").astype(float)
            lm, lsd, ln = _loo(s, s2, n, xs.fillna(0))
            w = (ln / (ln + K)).where(ln > 0, 0.0)
            mu = w * lm.fillna(mu) + (1 - w) * mu
            sd = w * lsd.fillna(sd).clip(lower=1e-6) + (1 - w) * sd
            grp = grp.where(w < 0.5, key.str.replace("|", " · ", regex=False))
        floor = 0.1 * mu.abs() + (0.02 if m in ("hi_em_share", "new_share") else 1e-3)
        Z[m] = ((x - mu) / np.maximum(sd, floor)).where(ok)
        used[m] = (mu, grp)
    up = Z.clip(lower=0).fillna(0)
    raw = np.sqrt((up.clip(upper=8) ** 2).mean(axis=1))
    out = pd.DataFrame({"peer_raw": raw})
    drivers = {}
    for pid in F.index:
        top = Z.loc[pid].dropna().sort_values(ascending=False)
        drivers[pid] = [
            dict(
                metric=METRICS[k],
                z=round(float(v), 1),
                value=round(float(F.at[pid, k]), 3),
                expected=round(float(used[k][0][pid]), 3),
                peers=used[k][1][pid],
            )
            for k, v in top.items()
            if v >= 2
        ][:3]
    return out, drivers
