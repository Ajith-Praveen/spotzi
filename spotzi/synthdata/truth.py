"""Entity-level ground truth for synthetic data (hidden; evaluation only — never read by detection).

For every provider: true_state (fraudulent / legitimate / legitimate_anomaly / decoy), fraud_type (common taxonomy),
scheme_id, fraud_start, severity, ring_id (schemes spanning several providers) and labelled volume. Real datasets rarely
offer truth at claim, entity, temporal and network level at once; synthetic data does, so the evaluation engine uses all four."""
from __future__ import annotations

import pandas as pd

TAXONOMY = ["duplicate", "upcoding", "unit_inflation", "unbundling", "phantom", "impossible_timing", "excessive_services",
            "recruitment", "kickback_referral", "scope_expansion", "excluded_provider"]
SCENARIO_TYPE = {  # scenario prefix → fraud type
    "S1": "unbundling", "S2": "phantom", "S3": "impossible_timing", "S4": "upcoding", "S5": "excessive_services", "S6": "upcoding",
    "S7": "duplicate", "S8": "phantom", "S9": "recruitment",
    "dup": "duplicate", "units": "unit_inflation", "repeat": "excessive_services", "upcode": "upcoding", "deceased": "phantom",
    "influx": "recruitment", "scope": "scope_expansion",
}
RINGS = {"S1", "S2", "S5", "S9"}   # multi-provider schemes


def _type(scen: str) -> str | None:
    s = str(scen)
    return SCENARIO_TYPE.get(s.split("-")[0]) or SCENARIO_TYPE.get(s)


def build(lines: pd.DataFrame, providers: list, legit: pd.DataFrame | None = None, min_lines=20, exclusions: pd.DataFrame | None = None) -> pd.DataFrame:
    """lines: provider_id, service_date, paid, truth, scenario."""
    L = lines.copy(); L["service_date"] = pd.to_datetime(L.service_date)
    t = L[L.truth.astype(bool)]
    rows = []
    for pid in providers:
        g = t[t.provider_id == pid]
        if len(g) >= min_lines:
            sc = g.scenario.value_counts().index[0]
            paid = float(g.paid.sum()) if "paid" in g else 0.0
            sev = "high" if paid >= 15000 or len(g) >= 300 else "medium" if paid >= 4000 or len(g) >= 80 else "low"
            pre = str(sc).split("-")[0]
            rows.append(dict(provider_id=pid, true_state="fraudulent", fraud_type=_type(sc), scheme_id=pre, fraud_start=str(g.service_date.min().date()),
                             severity=sev, ring_id=pre if pre in RINGS else None, truth_lines=int(len(g)), truth_paid=round(paid, 2)))
            continue
        scen = L[L.provider_id == pid].scenario.astype(str)
        state = "decoy" if scen.str.startswith("decoy").any() else "legitimate"
        rows.append(dict(provider_id=pid, true_state=state, fraud_type=None, scheme_id=None, fraud_start=None, severity=None, ring_id=None,
                         truth_lines=int(len(g)), truth_paid=0.0))
    E = pd.DataFrame(rows)
    if exclusions is not None and len(exclusions):     # billing after an exclusion date is improper whatever the claims look like
        for r in exclusions.itertuples():
            after = L[(L.provider_id == r.provider_id) & (L.service_date >= pd.Timestamp(r.excl_date))]
            if len(after) and r.provider_id in set(E.provider_id):
                E.loc[E.provider_id == r.provider_id, ["true_state", "fraud_type", "scheme_id", "fraud_start", "severity"]] = \
                    ["fraudulent", "excluded_provider", "EXCL", str(after.service_date.min().date()), "high" if after.paid.sum() > 5000 else "medium"]
    if legit is not None and len(legit):
        for r in legit.itertuples():
            if getattr(r, "legitimate", True) and r.provider_id in set(E.provider_id):
                E.loc[(E.provider_id == r.provider_id) & (E.true_state != "fraudulent"), "true_state"] = "legitimate_anomaly"
    return E
