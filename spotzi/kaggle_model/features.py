"""Provider-level features shared by the Kaggle training data and the SpotZ^i synthetic claims.
Both sides are reduced to the same schema, then rank-normalised so only *relative* behaviour transfers."""
from __future__ import annotations

import numpy as np
import pandas as pd

SHARED = ["log_claims", "log_benes", "claims_per_bene", "avg_amt", "std_amt", "max_amt", "cv_amt", "ip_share", "n_physicians",
          "claims_per_physician", "avg_los", "avg_age", "repeat_bene_share", "dup_share", "weekend_share", "top_phys_share"]
LABELS = {"log_claims": "Claim volume", "log_benes": "Distinct beneficiaries", "claims_per_bene": "Claims per beneficiary", "avg_amt": "Average claim amount",
          "std_amt": "Claim amount spread", "max_amt": "Largest claim", "cv_amt": "Amount variability", "ip_share": "Inpatient share", "n_physicians": "Distinct physicians",
          "claims_per_physician": "Claims per physician", "avg_los": "Average length of stay", "avg_age": "Average beneficiary age", "repeat_bene_share": "Repeat-beneficiary share",
          "dup_share": "Same-day duplicate share", "weekend_share": "Weekend share", "top_phys_share": "Top-physician concentration"}


def _agg(c: pd.DataFrame) -> pd.DataFrame:
    """c columns: provider, bene, amt, ip(bool), phys, start(datetime), los, age"""
    g = c.groupby("provider")
    f = pd.DataFrame(index=g.size().index)
    n = g.size()
    f["log_claims"] = np.log1p(n)
    nb = g.bene.nunique()
    f["log_benes"] = np.log1p(nb)
    f["claims_per_bene"] = n / nb.clip(lower=1)
    f["avg_amt"] = np.log1p(g.amt.mean()); f["std_amt"] = np.log1p(g.amt.std().fillna(0)); f["max_amt"] = np.log1p(g.amt.max())
    f["cv_amt"] = (g.amt.std().fillna(0) / g.amt.mean().clip(lower=1))
    f["ip_share"] = g.ip.mean()
    f["n_physicians"] = np.log1p(g.phys.nunique())
    f["claims_per_physician"] = n / g.phys.nunique().clip(lower=1)
    f["avg_los"] = c[c.ip].groupby("provider").los.mean().reindex(f.index).fillna(0)
    f["avg_age"] = g.age.mean()
    pb = c.groupby(["provider", "bene"]).size()
    f["repeat_bene_share"] = (pb >= 3).groupby(level=0).mean().reindex(f.index).fillna(0)
    d = c.assign(_d=c.start.dt.normalize()).groupby(["provider", "bene", "_d"]).size()
    f["dup_share"] = (d > 1).groupby(level=0).mean().reindex(f.index).fillna(0)
    f["weekend_share"] = g.start.apply(lambda s: (s.dt.dayofweek >= 5).mean())
    top = c.groupby(["provider", "phys"]).size().groupby(level=0).max()
    f["top_phys_share"] = (top / n).reindex(f.index).fillna(0)
    return f.fillna(0)


def rank_norm(f: pd.DataFrame, groups: pd.Series | None = None) -> pd.DataFrame:
    if groups is None:
        return f.rank(pct=True)
    return f.groupby(groups.reindex(f.index)).rank(pct=True).fillna(.5)


def from_kaggle(ben: pd.DataFrame, inp: pd.DataFrame, out: pd.DataFrame) -> pd.DataFrame:
    def prep(df, ip):
        d = pd.DataFrame({"provider": df["Provider"], "bene": df["BeneID"], "amt": pd.to_numeric(df["InscClaimAmtReimbursed"], errors="coerce").fillna(0),
                          "ip": ip, "phys": df["AttendingPhysician"].fillna("NA"), "start": pd.to_datetime(df["ClaimStartDt"], errors="coerce")})
        if ip and "AdmissionDt" in df:
            d["los"] = (pd.to_datetime(df["DischargeDt"], errors="coerce") - pd.to_datetime(df["AdmissionDt"], errors="coerce")).dt.days.fillna(0).clip(lower=0)
        else:
            d["los"] = 0
        return d
    c = pd.concat([prep(inp, True), prep(out, False)], ignore_index=True)
    b = ben[["BeneID", "DOB"]].copy(); b["age"] = (pd.Timestamp("2009-12-31") - pd.to_datetime(b.DOB, errors="coerce")).dt.days / 365.25
    c = c.merge(b[["BeneID", "age"]].rename(columns={"BeneID": "bene"}), on="bene", how="left")
    c["age"] = c.age.fillna(c.age.median())
    return _agg(c)[SHARED]


def from_spotzi(L: pd.DataFrame, M: pd.DataFrame, providers: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    inp = L.code.eq("INP-DAY")
    c = pd.DataFrame({"provider": L.provider_id, "bene": L.member_id, "amt": L.paid, "ip": inp.values,
                      "phys": L.referring_provider_id.fillna(L.provider_id + "-self"), "start": pd.to_datetime(L.service_date),
                      "los": np.where(inp, L.units, 0)})
    c = c.merge(M[["member_id", "age"]].rename(columns={"member_id": "bene"}), on="bene", how="left")
    f = _agg(c)[SHARED]
    fam = providers.set_index("provider_id").family.reindex(f.index)
    return f, fam
