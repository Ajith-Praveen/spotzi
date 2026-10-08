"""Import public synthetic datasets into SpotZⁱ tables.

* CMS DE-SynPUF (2008–2010 synthetic Medicare claims, Sample 1). Institutional providers (hospital / outpatient CCNs) are
  realistic and reused; physician NPIs and tax IDs are deliberately scrambled by CMS, so they are NOT used as providers.
  Imported: beneficiaries (members), inpatient claims (hospital stays), outpatient claims (one line per HCPCS code,
  claim payment split evenly across its lines — flagged as allocated).
* Synthea sample (synthetic EHR). Imported: patients (no names / SSNs / addresses), clinicians as providers,
  organisations as shared-ownership entities, charges with payments as claim lines.
No hidden labels exist for either: forecasts show "unavailable" and evaluation is off."""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

STATE = {1: "AL", 2: "AK", 3: "AZ", 4: "AR", 5: "CA", 6: "CO", 7: "CT", 8: "DE", 9: "DC", 10: "FL", 11: "GA", 12: "HI", 13: "ID", 14: "IL", 15: "IN", 16: "IA", 17: "KS",
         18: "KY", 19: "LA", 20: "ME", 21: "MD", 22: "MA", 23: "MI", 24: "MN", 25: "MS", 26: "MO", 27: "MT", 28: "NE", 29: "NV", 30: "NH", 31: "NJ", 32: "NM", 33: "NY",
         34: "NC", 35: "ND", 36: "OH", 37: "OK", 38: "OR", 39: "PA", 41: "RI", 42: "SC", 43: "SD", 44: "TN", 45: "TX", 46: "UT", 47: "VT", 49: "VA", 50: "WA", 51: "WV",
         52: "WI", 53: "WY", 54: "Other"}


def _family_for_codes(codes: pd.Series) -> str:
    c = codes.astype(str)
    if (c.str.match(r"^8\d{4}$")).mean() > .6: return "LAB"
    if (c.str.startswith(("A04", "A0425", "A0427", "A0428"))).mean() > .5: return "AMB"
    if (c.str.match(r"^(E0|K0|L\d)")).mean() > .5: return "DME"
    return "FAC"


def synpuf(src: Path, out: Path, n_benes=4000, seed=11, states=None):
    src, out = Path(src), Path(out); out.mkdir(parents=True, exist_ok=True)
    f = lambda pat: sorted(glob.glob(str(src / pat)))[0]
    ben = pd.read_csv(f("*2009_Beneficiary*"), dtype=str)
    if states: ben = ben[ben.SP_STATE_CODE.astype(int).isin(states)]
    rng = np.random.default_rng(seed)
    ip = pd.read_csv(f("*Inpatient*"), dtype=str, usecols=["DESYNPUF_ID", "CLM_ID", "CLM_FROM_DT", "CLM_THRU_DT", "PRVDR_NUM", "CLM_PMT_AMT", "CLM_ADMSN_DT",
                                                          "NCH_BENE_DSCHRG_DT", "CLM_UTLZTN_DAY_CNT", "ICD9_DGNS_CD_1", "CLM_DRG_CD"])
    # prefer beneficiaries with institutional activity so the network is meaningful
    active = set(ip.DESYNPUF_ID)
    pool = ben[ben.DESYNPUF_ID.isin(active)].DESYNPUF_ID.values
    rest = ben[~ben.DESYNPUF_ID.isin(active)].DESYNPUF_ID.values
    k1 = min(len(pool), int(n_benes * .7)); keep = set(rng.choice(pool, k1, replace=False)) | set(rng.choice(rest, min(len(rest), n_benes - k1), replace=False))
    ben = ben[ben.DESYNPUF_ID.isin(keep)]
    ip = ip[ip.DESYNPUF_ID.isin(keep)]
    hcpcs = [f"HCPCS_CD_{i}" for i in range(1, 46)]
    op_cols = ["DESYNPUF_ID", "CLM_ID", "CLM_FROM_DT", "CLM_THRU_DT", "PRVDR_NUM", "CLM_PMT_AMT", "ICD9_DGNS_CD_1"]
    ops = []
    for ch in pd.read_csv(f("*Outpatient*"), dtype=str, chunksize=200_000):
        ch = ch[ch.DESYNPUF_ID.isin(keep)]
        cols = [c for c in hcpcs if c in ch.columns]
        ops.append(ch[op_cols + cols])
    op = pd.concat(ops, ignore_index=True)
    d8 = lambda s: pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    # ---- members
    asof = pd.Timestamp("2010-12-31")
    m = pd.DataFrame({"member_id": "B-" + ben.DESYNPUF_ID.str[:12], "_id": ben.DESYNPUF_ID})
    bd = d8(ben.BENE_BIRTH_DT.values)
    m["age"] = ((asof - bd).days / 365.25).astype(int).values
    m["sex"] = np.where(ben.BENE_SEX_IDENT_CD.values == "1", "M", "F")
    m["plan"] = "Medicare (synthetic)"
    m["region"] = [STATE.get(int(x), "Other") for x in ben.SP_STATE_CODE]
    m["death_date"] = d8(ben.BENE_DEATH_DT.values)
    m["term_date"] = pd.NaT; m["enroll_date"] = pd.Timestamp("2008-01-01")
    m["vulnerable"] = (m.age >= 75) | (ben.BENE_ESRD_IND.values == "Y")
    idmap = dict(zip(m._id, m.member_id))
    # ---- inpatient lines + stays
    ipl = pd.DataFrame({"claim_id": "IP" + ip.CLM_ID, "member_id": ip.DESYNPUF_ID.map(idmap), "provider_id": "INST-" + ip.PRVDR_NUM,
                        "service_date": d8(ip.CLM_FROM_DT), "service_end_date": d8(ip.CLM_THRU_DT), "code": "INP-DAY",
                        "units": pd.to_numeric(ip.CLM_UTLZTN_DAY_CNT, errors="coerce").fillna(1).clip(lower=1).astype(int),
                        "paid": pd.to_numeric(ip.CLM_PMT_AMT, errors="coerce").fillna(0).clip(lower=0), "pos": "21", "dx": ip.ICD9_DGNS_CD_1,
                        "modifier": "DRG" + ip.CLM_DRG_CD.fillna("")})
    stays = pd.DataFrame({"stay_id": "S" + ip.CLM_ID, "member_id": ip.DESYNPUF_ID.map(idmap), "admit_date": d8(ip.CLM_ADMSN_DT).fillna(d8(ip.CLM_FROM_DT)),
                          "discharge_date": d8(ip.NCH_BENE_DSCHRG_DT).fillna(d8(ip.CLM_THRU_DT)), "facility_id": "INST-" + ip.PRVDR_NUM})
    stays = stays.dropna(subset=["admit_date", "discharge_date"])
    # ---- outpatient lines: one per HCPCS code; claim payment allocated evenly
    long = op.melt(id_vars=op_cols, value_vars=[c for c in hcpcs if c in op.columns], value_name="code").dropna(subset=["code"])
    long = long[long.code.str.len() > 0]
    # the same HCPCS listed several times on one claim = several units of one service, not duplicate lines
    long = long.groupby(op_cols + ["code"], dropna=False).size().rename("units_").reset_index()
    n_per = long.groupby("CLM_ID").units_.transform("sum")
    opl = pd.DataFrame({"claim_id": "OP" + long.CLM_ID, "member_id": long.DESYNPUF_ID.map(idmap), "provider_id": "INST-" + long.PRVDR_NUM,
                        "service_date": d8(long.CLM_FROM_DT), "service_end_date": d8(long.CLM_THRU_DT), "code": long.code.str.upper(), "units": long.units_,
                        "paid": (pd.to_numeric(long.CLM_PMT_AMT, errors="coerce").fillna(0).clip(lower=0) * long.units_ / n_per).round(2), "pos": "22", "dx": long.ICD9_DGNS_CD_1,
                        "modifier": "ALLOC"})
    # outpatient claims without HCPCS: keep one visit line so the payment is not lost
    no_h = op[~op.CLM_ID.isin(long.CLM_ID)]
    opv = pd.DataFrame({"claim_id": "OP" + no_h.CLM_ID, "member_id": no_h.DESYNPUF_ID.map(idmap), "provider_id": "INST-" + no_h.PRVDR_NUM, "service_date": d8(no_h.CLM_FROM_DT),
                        "service_end_date": d8(no_h.CLM_THRU_DT), "code": "OP-VISIT", "units": 1, "paid": pd.to_numeric(no_h.CLM_PMT_AMT, errors="coerce").fillna(0).clip(lower=0),
                        "pos": "22", "dx": no_h.ICD9_DGNS_CD_1, "modifier": ""})
    L = pd.concat([ipl, opl, opv], ignore_index=True).dropna(subset=["service_date", "member_id"])
    L = L[L.provider_id.str.len() > 5]
    L["line_no"] = L.groupby("claim_id").cumcount() + 1
    L["line_id"] = L.claim_id + "-" + L.line_no.astype(str)
    L["billed"] = (L.paid * 1.8).round(2)
    L["duration_min"] = 0; L["start_min"] = 540; L["referring_provider_id"] = None
    L["facility_id"] = np.where(L.pos == "21", L.provider_id, None)
    # ---- providers: institutions (CCN). Hospital if it has inpatient claims, else family by its code mix
    inp_ids = set(ipl.provider_id)
    fam = L.groupby("provider_id").code.apply(_family_for_codes)
    fam[fam.index.isin(inp_ids)] = "FAC"
    region = L.merge(m[["member_id", "region"]], on="member_id").groupby("provider_id").region.agg(lambda s: s.mode().iat[0])
    P = pd.DataFrame({"provider_id": fam.index, "family": fam.values})
    P["name"] = [("Hospital " if f_ == "FAC" and p in inp_ids else {"LAB": "Laboratory ", "AMB": "Ambulance service ", "DME": "Supplier "}.get(f_, "Outpatient facility ")) + p.replace("INST-", "CCN ") for p, f_ in zip(P.provider_id, P.family)]
    P["specialty"] = np.where(P.provider_id.isin(inp_ids), "Hospital (inpatient + outpatient)", "Outpatient institution")
    P["city"] = P.provider_id.map(region).fillna("Other")
    P["npi"] = P.provider_id; P["context_note"] = ""
    P["L"] = 0
    keep_cols = ["line_id", "claim_id", "line_no", "member_id", "provider_id", "facility_id", "referring_provider_id", "family", "service_date", "service_end_date",
                 "paid_date", "code", "units", "billed", "paid", "pos", "dx", "modifier", "start_min", "duration_min"]
    L["family"] = L.provider_id.map(fam)
    L["paid_date"] = L.service_end_date.fillna(L.service_date) + pd.Timedelta(days=21)
    L[keep_cols].to_csv(out / "claim_lines.csv", index=False)
    P[["provider_id", "npi", "name", "family", "specialty", "city", "context_note"]].to_csv(out / "providers.csv", index=False)
    m.drop(columns=["_id"]).to_csv(out / "members.csv", index=False)
    stays.to_csv(out / "inpatient_stays.csv", index=False)
    (out / "SOURCE.txt").write_text("CMS 2008-2010 Data Entrepreneurs' Synthetic Public Use File (DE-SynPUF), Sample 1 — synthetic Medicare claims.\n"
                                    "Institutional providers only (physician NPIs / tax IDs are scrambled by CMS). Outpatient payments allocated evenly across HCPCS lines.\n")
    return dict(dataset="DE-SynPUF Sample 1", lines=int(len(L)), claims=int(L.claim_id.nunique()), members=int(len(m)), providers=int(len(P)),
                hospitals=int(P.provider_id.isin(inp_ids).sum()), stays=int(len(stays)), period=f"{L.service_date.min():%Y-%m-%d} → {L.service_date.max():%Y-%m-%d}")


def synthea(src: Path, out: Path):
    src, out = Path(src), Path(out); out.mkdir(parents=True, exist_ok=True)
    pat = pd.read_csv(src / "patients.csv", usecols=["Id", "BIRTHDATE", "DEATHDATE", "GENDER", "STATE", "COUNTY"])
    prov = pd.read_csv(src / "providers.csv", usecols=["Id", "ORGANIZATION", "SPECIALITY", "CITY", "STATE"])
    org = pd.read_csv(src / "organizations.csv", usecols=["Id", "NAME", "CITY"])
    ct = pd.read_csv(src / "claims_transactions.csv", usecols=["CLAIMID", "CHARGEID", "PATIENTID", "TYPE", "AMOUNT", "PAYMENTS", "FROMDATE", "TODATE", "PLACEOFSERVICE",
                                                               "PROCEDURECODE", "UNITS", "PROVIDERID"])
    ch = ct[ct.TYPE == "CHARGE"].copy()
    paid = ct[ct.TYPE == "PAYMENT"].groupby(["CLAIMID", "CHARGEID"]).PAYMENTS.sum()
    ch = ch.join(paid.rename("paid_amt"), on=["CLAIMID", "CHARGEID"])
    pmap = {p: f"PR-{i + 1:04d}" for i, p in enumerate(prov.Id)}
    mmap = {p: f"SY-{i + 1:05d}" for i, p in enumerate(pat.Id)}
    asof = pd.to_datetime(ch.FROMDATE, utc=True).max().tz_localize(None)
    m = pd.DataFrame({"member_id": pat.Id.map(mmap), "age": ((asof - pd.to_datetime(pat.BIRTHDATE)).dt.days / 365.25).astype(int), "sex": pat.GENDER, "plan": "Synthetic payer",
                      "region": pat.COUNTY.fillna(pat.STATE), "death_date": pd.to_datetime(pat.DEATHDATE, errors="coerce"), "term_date": pd.NaT})
    L = pd.DataFrame({"claim_id": "SY-" + ch.CLAIMID.astype(str), "member_id": ch.PATIENTID.map(mmap), "provider_id": ch.PROVIDERID.map(pmap),
                      "service_date": pd.to_datetime(ch.FROMDATE, utc=True).dt.tz_localize(None).dt.normalize(),
                      "service_end_date": pd.to_datetime(ch.TODATE, utc=True).dt.tz_localize(None).dt.normalize(),
                      "code": ch.PROCEDURECODE.astype(str), "units": pd.to_numeric(ch.UNITS, errors="coerce").fillna(1).astype(int).clip(lower=1),
                      "billed": pd.to_numeric(ch.AMOUNT, errors="coerce").fillna(0), "paid": pd.to_numeric(ch.paid_amt, errors="coerce").fillna(0), "pos": "11", "dx": None,
                      "modifier": "", "family": "PRO"}).dropna(subset=["member_id", "provider_id"])
    L = L[L.service_date > L.service_date.max() - pd.Timedelta(days=3 * 365)]   # recent three years, not whole lifetimes
    L["line_no"] = L.groupby("claim_id").cumcount() + 1
    L["line_id"] = L.claim_id + "-" + L.line_no.astype(str)
    L["paid_date"] = L.service_end_date + pd.Timedelta(days=21); L["duration_min"] = 0; L["start_min"] = 540; L["referring_provider_id"] = None; L["facility_id"] = None
    omap = dict(zip(org.Id, org.NAME)); ocity = dict(zip(org.Id, org.CITY))
    P = pd.DataFrame({"provider_id": prov.Id.map(pmap), "npi": prov.Id.map(pmap), "name": [f"Clinician {pmap[i][3:]} · {omap.get(o, 'clinic')[:28]}" for i, o in zip(prov.Id, prov.ORGANIZATION)],
                      "family": "PRO", "specialty": prov.SPECIALITY.str.title(), "city": prov.CITY, "context_note": "",
                      "org_id": "ORG-" + prov.ORGANIZATION.astype(str).str[:8]})
    P = P[P.provider_id.isin(set(L.provider_id))]
    L[["line_id", "claim_id", "line_no", "member_id", "provider_id", "facility_id", "referring_provider_id", "family", "service_date", "service_end_date", "paid_date",
       "code", "units", "billed", "paid", "pos", "dx", "modifier", "start_min", "duration_min"]].to_csv(out / "claim_lines.csv", index=False)
    P.to_csv(out / "providers.csv", index=False)
    m.to_csv(out / "members.csv", index=False)
    (out / "SOURCE.txt").write_text("Synthea synthetic patient sample (synthetichealth.github.io). Names, SSNs, addresses and identifiers were NOT imported.\n")
    return dict(dataset="Synthea sample", lines=int(len(L)), claims=int(L.claim_id.nunique()), members=int(len(m)), providers=int(len(P)),
                organisations=int(P.org_id.nunique()), period=f"{L.service_date.min():%Y-%m-%d} → {L.service_date.max():%Y-%m-%d}")
