"""Synthetic healthcare-payer data generator for SpotZⁱ.

Everything here is fabricated. Names, IDs and addresses are invented; code values are
public billing-code identifiers with invented prices. Hidden scenario truth is written to
a separate file and is used ONLY for evaluation / forecast labels, never for detection.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

START = pd.Timestamp("2024-01-01")
END = pd.Timestamp("2025-08-31")
DAYS = (END - START).days + 1

# code: (family, description, price, documented minutes)
CODES = {
    "99212": ("PRO", "Office visit, level 2", 55, 10),
    "99213": ("PRO", "Office visit, level 3", 90, 20),
    "99214": ("PRO", "Office visit, level 4", 130, 30),
    "99215": ("PRO", "Office visit, level 5", 185, 40),
    "93000": ("PRO", "Electrocardiogram", 22, 10),
    "80053": ("LAB", "Comprehensive metabolic panel", 14, 0),
    "82947": ("LAB", "Glucose (panel component)", 5, 0),
    "82565": ("LAB", "Creatinine (panel component)", 6, 0),
    "84132": ("LAB", "Potassium (panel component)", 6, 0),
    "85025": ("LAB", "Complete blood count", 10, 0),
    "83036": ("LAB", "Hemoglobin A1c", 12, 0),
    "80305": ("LAB", "Drug screen, presumptive", 45, 0),
    "80307": ("LAB", "Drug screen, definitive", 130, 0),
    "99283": ("FAC", "Emergency visit, moderate", 320, 0),
    "99285": ("FAC", "Emergency visit, high", 710, 0),
    "INP-DAY": ("FAC", "Inpatient per diem", 2300, 0),
    "RX-GEN": ("PHARM", "Generic fill (30 day)", 18, 0),
    "RX-BRAND": ("PHARM", "Brand fill (30 day)", 190, 0),
    "RX-OPI": ("PHARM", "Opioid fill (30 day)", 48, 0),
    "RX-COMP": ("PHARM", "Compounded preparation", 640, 0),
    "A0427": ("AMB", "Ambulance ALS emergency", 480, 35),
    "A0428": ("AMB", "Ambulance BLS non-emergency", 310, 30),
    "A0425": ("AMB", "Ambulance mileage (per mile)", 8, 0),
    "90791": ("BH", "Psychiatric evaluation", 190, 50),
    "90834": ("BH", "Psychotherapy 45 min", 110, 45),
    "90837": ("BH", "Psychotherapy 60 min", 145, 60),
    "90853": ("BH", "Group psychotherapy", 35, 60),
    "G0299": ("HH", "Home health nursing visit", 115, 60),
    "G0151": ("HH", "Home health PT visit", 125, 45),
    "E0601": ("DME", "CPAP rental (month)", 65, 0),
    "E1390": ("DME", "Oxygen concentrator rental (month)", 185, 0),
    "K0823": ("DME", "Power wheelchair", 2650, 0),
    "L1832": ("DME", "Knee brace", 510, 0),
    "A4253": ("DME", "Glucose test strips", 42, 0),
}
FAMILY_NAMES = {"PRO": "Professional", "LAB": "Laboratory", "FAC": "Facility", "PHARM": "Pharmacy",
                "AMB": "Ambulance", "BH": "Behavioral health", "HH": "Home health", "DME": "DME"}
CODE_MIX = {
    "PRO": {"99212": .10, "99213": .45, "99214": .33, "99215": .07, "93000": .05},
    "LAB": {"80053": .20, "85025": .22, "83036": .15, "82947": .12, "82565": .10, "84132": .08, "80305": .08, "80307": .05},
    "FAC": {"99283": .65, "99285": .35},
    "PHARM": {"RX-GEN": .70, "RX-BRAND": .22, "RX-OPI": .06, "RX-COMP": .02},
    "AMB": {"A0427": .45, "A0428": .55},
    "BH": {"90834": .40, "90837": .30, "90791": .06, "90853": .24},
    "HH": {"G0299": .60, "G0151": .40},
    "DME": {"E0601": .30, "E1390": .20, "K0823": .03, "L1832": .15, "A4253": .32},
}
RATE_PER_YEAR = {"PRO": 3.6, "LAB": 2.0, "FAC": 0.35, "PHARM": 3.5, "AMB": 0.10}
PROVIDER_COUNTS = {"PRO": 46, "LAB": 14, "FAC": 10, "PHARM": 14, "AMB": 8, "BH": 14, "HH": 12, "DME": 14}
SPECIALTY = {"PRO": ["Family medicine", "Internal medicine", "Cardiology", "Orthopedics", "Pain management"],
             "LAB": ["Independent laboratory"], "FAC": ["Acute care hospital"], "PHARM": ["Retail pharmacy"],
             "AMB": ["Ground ambulance"], "BH": ["Outpatient behavioral health"], "HH": ["Home health agency"],
             "DME": ["Durable medical equipment"]}
REGIONS = [("Rivergate", 40.10, -75.30), ("Pinecrest", 40.45, -75.90), ("Lakemont", 40.80, -75.20),
           ("Stonebridge", 40.20, -76.40), ("Fairhaven", 40.60, -76.00), ("Eastvale", 40.90, -75.70)]
NAME_A = ["Maple", "Harbor", "Summit", "Cedar", "Bright", "Union", "Oak", "Lake", "Ridge", "Valley", "Pioneer", "Crest",
          "Willow", "Granite", "Beacon", "Silver", "Orchard", "Clear", "Falcon", "Juniper", "Prairie", "Coastal", "Heron"]
NAME_B = {"PRO": ["Family Care", "Medical Group", "Health Associates", "Primary Care", "Clinic", "Physicians"],
          "LAB": ["Laboratories", "Diagnostics", "Clinical Lab"], "FAC": ["Medical Center", "Regional Hospital", "Community Hospital"],
          "PHARM": ["Pharmacy", "Drug", "Apothecary"], "AMB": ["Ambulance", "EMS", "Medical Transport"],
          "BH": ["Behavioral Health", "Counseling", "Wellness Center"], "HH": ["Home Health", "Home Care", "Visiting Nurses"],
          "DME": ["Medical Supply", "Home Medical", "Mobility Equipment"]}
DX = ["I10", "E11.9", "J44.9", "M54.5", "F32.9", "Z00.00", "K21.9", "G47.33", "N39.0", "R07.9"]


def price(code):
    return CODES[code][2]


def _weekday_shift(dates: pd.Series, rng, families: pd.Series):
    wk = dates.dt.dayofweek
    weekend_ok = families.isin(["FAC", "PHARM", "AMB", "HH"])
    move = (wk >= 5) & ~weekend_ok & (rng.random(len(dates)) < 0.92)
    shift = np.where(wk == 5, -1, -2)
    return dates + pd.to_timedelta(np.where(move, shift, 0), unit="D")


def generate(seed: int = 7, n_members: int = 2500, out_dir: str | Path = Path(__file__).resolve().parents[1] / "data" / "synthetic") -> dict:
    rng = np.random.default_rng(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ---------------- providers ----------------
    rows, used = [], set()
    for fam, n in PROVIDER_COUNTS.items():
        for i in range(n):
            for _ in range(50):
                nm = f"{rng.choice(NAME_A)} {rng.choice(NAME_B[fam])}"
                if nm not in used:
                    used.add(nm)
                    break
            reg = int(rng.integers(0, len(REGIONS)))
            rows.append(dict(family=fam, name=nm, specialty=rng.choice(SPECIALTY[fam]), region=reg,
                             size=float(np.exp(rng.normal(0, 0.55)))))
    prov = pd.DataFrame(rows)
    prov.insert(0, "provider_id", [f"P-{i + 1:04d}" for i in range(len(prov))])
    prov["npi"] = [f"SYN{9000000 + i * 37:07d}" for i in range(len(prov))]
    prov["city"] = [REGIONS[r][0] for r in prov.region]
    prov["lat"] = [REGIONS[r][1] + rng.normal(0, .05) for r in prov.region]
    prov["lon"] = [REGIONS[r][2] + rng.normal(0, .05) for r in prov.region]
    prov["org_id"] = [f"ORG-{i + 1:04d}" for i in range(len(prov))]
    prov["address_id"] = [f"ADDR-{i + 1:04d}" for i in range(len(prov))]
    prov["bank_id"] = [f"BANK-{i + 1:04d}" for i in range(len(prov))]
    prov["enrolled_date"] = [(START - pd.Timedelta(days=int(rng.integers(200, 3000)))).date() for _ in range(len(prov))]
    # strip the family prefix on a few names so the lists read naturally
    prov["context_note"] = ""

    def P(fam, k):
        return prov[prov.family == fam].provider_id.iloc[k]

    def setp(pid, **kw):
        for k, v in kw.items():
            prov.loc[prov.provider_id == pid, k] = v

    # named scenario cast
    cast = {
        P("LAB", 0): ("Northstar Diagnostics", "Independent laboratory", 0, "ORG-A", None, None),
        P("PRO", 0): ("Harbor Family Care", "Family medicine", 0, "ORG-A", None, None),
        P("PRO", 1): ("Lakeside Primary Group", "Internal medicine", 0, "ORG-A", None, None),
        P("DME", 0): ("Meridian Mobility Supply", "Durable medical equipment", 2, None, "ADDR-B", "BANK-B"),
        P("DME", 1): ("Atlas Home Medical", "Durable medical equipment", 2, None, "ADDR-B", "BANK-B"),
        P("HH", 0): ("CarePath Home Health", "Home health agency", 2, None, "ADDR-B", None),
        P("PRO", 2): ("Eastgate Geriatric Associates", "Internal medicine", 2, None, None, None),
        P("BH", 0): ("Summit Behavioral Wellness", "Outpatient behavioral health", 1, None, None, None),
        P("PRO", 3): ("Clearview Internal Medicine", "Internal medicine", 3, None, None, None),
        P("PRO", 4): ("Pinnacle Primary Care", "Family medicine", 4, None, None, None),
        P("PHARM", 0): ("Keystone Compounding Pharmacy", "Retail pharmacy", 4, "ORG-C", None, None),
        P("PHARM", 1): ("Keystone Express Rx", "Retail pharmacy", 4, "ORG-C", None, None),
        P("PRO", 5): ("Westgate Pain Clinic", "Pain management", 4, None, None, None),
        P("AMB", 0): ("Rapid Response Transport", "Ground ambulance", 3, None, None, None),
        P("FAC", 2): ("Riverbend Medical Center", "Acute care hospital", 1, None, None, None),
        P("HH", 1): ("Sunrise Home Care", "Home health agency", 5, None, None, None),
        # benign decoys
        P("PRO", 6): ("Oncology & Hematology Associates", "Hematology/Oncology", 0, None, None, None),
        P("LAB", 3): ("Dialysis Reference Laboratory", "Independent laboratory", 1, None, None, None),
        P("PHARM", 2): ("CityChain Pharmacy #12", "Retail pharmacy", 0, "ORG-D", None, None),
        P("PHARM", 3): ("CityChain Pharmacy #47", "Retail pharmacy", 0, "ORG-D", None, None),
        P("PRO", 7): ("Regional Multispecialty Clinic", "Internal medicine", 1, None, None, None),
    }
    for pid, (nm, spec, reg, org, addr, bank) in cast.items():
        setp(pid, name=nm, specialty=spec, region=reg, city=REGIONS[reg][0])
        if org: setp(pid, org_id=org)
        if addr: setp(pid, address_id=addr)
        if bank: setp(pid, bank_id=bank)
    setp(P("PRO", 7), size=5.0)
    setp(P("PRO", 6), context_note="Oncology practice: higher-complexity visits can be clinically appropriate.")
    setp(P("LAB", 3), context_note="Serves dialysis patients: frequent monitoring labs can be appropriate.")
    setp(P("PHARM", 2), context_note="Chain pharmacy: shared ownership is routine.")
    setp(P("PHARM", 3), context_note="Chain pharmacy: shared ownership is routine.")
    for pid in [P("LAB", 0), P("PRO", 0), P("PRO", 1)]:
        setp(pid, size=1.0)
    prov["region"] = prov["region"].astype(int)
    prov["city"] = [REGIONS[r][0] for r in prov.region]
    prov["lat"] = [REGIONS[r][1] + rng.normal(0, .05) for r in prov.region]
    prov["lon"] = [REGIONS[r][2] + rng.normal(0, .05) for r in prov.region]

    # ---------------- members ----------------
    m = pd.DataFrame({"member_id": [f"M-{i + 1:05d}" for i in range(n_members)]})
    m["age"] = np.clip(rng.normal(52, 20, n_members), 1, 95).astype(int)
    m["region"] = rng.integers(0, len(REGIONS), n_members)
    m["sex"] = rng.choice(["F", "M"], n_members)
    m["plan"] = rng.choice(["Commercial", "Medicare Advantage", "Medicaid"], n_members, p=[.5, .3, .2])
    m["enroll_date"] = START
    m["term_date"] = pd.NaT
    m["death_date"] = pd.NaT
    t = rng.random(n_members) < 0.08
    m.loc[t, "term_date"] = START + pd.to_timedelta(rng.integers(120, DAYS - 20, t.sum()), unit="D")
    elderly = m.index[(m.age >= 68) & ~t]
    dead = rng.choice(elderly, 12, replace=False)
    m.loc[dead, "death_date"] = START + pd.to_timedelta(rng.integers(300, DAYS - 150, len(dead)), unit="D")
    m["vulnerable"] = (m.age >= 65) | (m.plan == "Medicaid")
    pro = prov[prov.family == "PRO"].reset_index(drop=True)

    def pick_pcp(region):
        w = pro["size"].values * np.where(pro.region.values == region, 5.0, 0.4)
        return rng.choice(pro.provider_id.values, p=w / w.sum())
    m["pcp"] = [pick_pcp(r) for r in m.region]
    # ensure scenario practices have patient panels
    m_end = m.term_date.fillna(END).where(m.death_date.isna(), m.death_date).clip(upper=END)
    active_days = np.maximum(1, (m_end - START).dt.days.values + 1)

    # ---------------- base claim lines ----------------
    fam_prov = {f: prov[prov.family == f].reset_index(drop=True) for f in PROVIDER_COUNTS}

    def choose_provider(fam, regions, pcp=None, pcp_prob=0.0):
        fp = fam_prov[fam]
        out_ = np.empty(len(regions), dtype=object)
        for r in range(len(REGIONS)):
            idx = np.where(regions == r)[0]
            if not len(idx): continue
            w = fp["size"].values * np.where(fp.region.values == r, 4.0, 0.5)
            out_[idx] = rng.choice(fp.provider_id.values, size=len(idx), p=w / w.sum())
        if pcp is not None and pcp_prob:
            use = rng.random(len(regions)) < pcp_prob
            out_[use] = pcp[use]
        return out_

    chunks = []

    def add(fam, midx, dates, codes, provider, units=None, dur=None, ref=None, pos="11", dx=None):
        n = len(midx)
        d = pd.DataFrame({"member_id": m.member_id.values[midx], "provider_id": provider, "family": fam,
                          "service_date": pd.to_datetime(dates), "code": codes})
        d["units"] = 1 if units is None else units
        d["referring_provider_id"] = ref if ref is not None else None
        d["pos"] = pos
        d["dx"] = dx if dx is not None else rng.choice(DX, n)
        base_min = np.array([CODES[c][3] for c in codes], dtype=float)
        d["duration_min"] = (base_min * rng.uniform(0.9, 1.15, n)).round() if dur is None else dur
        d["start_min"] = rng.integers(8 * 60, 16 * 60, n)
        chunks.append(d)

    for fam, rate in RATE_PER_YEAR.items():
        mult = np.where(m.age >= 60, 1.5, 1.0) if fam in ("PRO", "LAB", "PHARM") else 1.0
        counts = rng.poisson(rate * mult * active_days / 365.0)
        midx = np.repeat(np.arange(n_members), counts)
        if not len(midx): continue
        dates = START + pd.to_timedelta((rng.random(len(midx)) * active_days[midx]).astype(int), unit="D")
        codes = rng.choice(list(CODE_MIX[fam]), len(midx), p=list(CODE_MIX[fam].values()))
        regs = m.region.values[midx]
        provider = choose_provider(fam, regs, pcp=m.pcp.values[midx], pcp_prob=0.65 if fam == "PRO" else 0.0)
        ref = m.pcp.values[midx] if fam in ("LAB", "PHARM", "AMB") else None
        if fam in ("LAB", "PHARM"):
            ref = np.where(rng.random(len(midx)) < .85, ref, rng.choice(pro.provider_id.values, len(midx)))
        pos = {"FAC": "23", "PHARM": "01", "AMB": "41", "LAB": "81"}.get(fam, "11")
        add(fam, midx, dates, codes, provider, ref=ref, pos=pos)
    base = pd.concat(chunks, ignore_index=True)
    chunks.clear()
    # ambulance mileage companion lines
    amb = base[base.code.isin(["A0427", "A0428"])]
    if len(amb):
        mil = amb.copy(); mil["code"] = "A0425"; mil["units"] = rng.integers(4, 26, len(mil)); mil["duration_min"] = 0
        base = pd.concat([base, mil], ignore_index=True)

    # clustered services: behavioral health, home health, DME rentals / supplies
    def clusters(fam, share, n_events_fn, gap_fn, code_fn, extra=None):
        users = rng.choice(n_members, int(n_members * share), replace=False)
        rowsl = []
        for mi in users:
            st = START + pd.Timedelta(days=int(rng.integers(0, max(1, active_days[mi] - 60))))
            n = n_events_fn(); d = st
            prv = choose_provider(fam, np.array([m.region.values[mi]]))[0]
            code = code_fn()
            for _ in range(n):
                if d > m_end.iloc[mi]: break
                rowsl.append((mi, d, code if code_fn.__name__ != "_bh" else code_fn(), prv))
                d = d + pd.Timedelta(days=int(gap_fn()))
        if not rowsl: return
        mi, dd, cc, pp = zip(*rowsl)
        mi = np.array(mi)
        add(fam, mi, pd.to_datetime(list(dd)), list(cc), np.array(pp, dtype=object),
            ref=m.pcp.values[mi], pos="12" if fam == "HH" else "11")
    def _bh(): return rng.choice(list(CODE_MIX["BH"]), p=list(CODE_MIX["BH"].values()))
    clusters("BH", .16, lambda: int(rng.integers(6, 22)), lambda: int(rng.choice([7, 7, 7, 14])), _bh)
    clusters("HH", .04, lambda: int(rng.integers(5, 12)), lambda: int(rng.integers(2, 5)), lambda: rng.choice(["G0299", "G0151"]))
    clusters("DME", .07, lambda: int(rng.integers(4, 13)), lambda: 30, lambda: rng.choice(["E0601", "E1390", "A4253"]))
    one = rng.choice(n_members, 70, replace=False)
    add("DME", one, START + pd.to_timedelta(rng.integers(0, DAYS - 5, 70), unit="D"),
        list(rng.choice(["K0823", "L1832"], 70, p=[.3, .7])), choose_provider("DME", m.region.values[one]), ref=m.pcp.values[one])
    base = pd.concat([base] + chunks, ignore_index=True); chunks.clear()
    base["service_date"] = _weekday_shift(base.service_date, rng, base.family)
    base["truth"] = False
    base["scenario"] = ""

    # inpatient stays
    n_stay = int(n_members * 0.05)
    st_m = rng.choice(np.where(active_days > 200)[0], n_stay, replace=False)
    admit = START + pd.to_timedelta((rng.random(n_stay) * (active_days[st_m] - 12)).astype(int), unit="D")
    los = rng.integers(2, 10, n_stay)
    disch = admit + pd.to_timedelta(los, unit="D")
    hosp = choose_provider("FAC", m.region.values[st_m])
    stays = pd.DataFrame({"member_id": m.member_id.values[st_m], "admit_date": admit, "discharge_date": disch, "facility_id": hosp, "mi": st_m})
    inp = pd.DataFrame({"member_id": stays.member_id, "provider_id": stays.facility_id, "family": "FAC", "service_date": admit,
                        "code": "INP-DAY", "units": los, "referring_provider_id": None, "pos": "21",
                        "dx": rng.choice(DX, n_stay), "duration_min": 0, "start_min": 0, "truth": False, "scenario": ""})
    inp["service_end_date"] = disch.values
    # hospital-based professional visits (legit services during stays)
    hv = stays.sample(frac=.7, random_state=seed)
    hpro = choose_provider("PRO", m.region.values[hv.mi.values])
    hosp_vis = pd.DataFrame({"member_id": hv.member_id, "provider_id": hpro, "family": "PRO",
                             "service_date": hv.admit_date + pd.Timedelta(days=1), "code": "99214", "units": 1,
                             "referring_provider_id": None, "pos": "21", "dx": rng.choice(DX, len(hv)), "duration_min": 30,
                             "start_min": 600, "truth": False, "scenario": ""})
    base["service_end_date"] = base.service_date
    hosp_vis["service_end_date"] = hosp_vis.service_date
    base = pd.concat([base, inp, hosp_vis], ignore_index=True)

    new = []  # injected lines

    def inject(df, scenario, truth=True):
        df = df.copy()
        df["truth"] = truth; df["scenario"] = scenario
        if "service_end_date" not in df: df["service_end_date"] = df.service_date
        new.append(df)

    def sample_base(mask, n=None, frac=None):
        s = base[mask]
        return s.sample(n=min(n, len(s)), random_state=int(rng.integers(1e6))) if n else s.sample(frac=frac, random_state=int(rng.integers(1e6)))

    def line(member_idx, provider, fam, code, dates, units=1, ref=None, pos="11", dx=None, dur=None, startm=None):
        member_idx = np.asarray(member_idx)
        n = len(member_idx)
        d = pd.DataFrame({"member_id": m.member_id.values[member_idx], "provider_id": provider, "family": fam,
                          "service_date": pd.to_datetime(dates), "code": code, "units": units,
                          "referring_provider_id": ref, "pos": pos,
                          "dx": dx if dx is not None else rng.choice(DX, n)})
        d["duration_min"] = dur if dur is not None else CODES[code][3] if isinstance(code, str) else 0
        d["start_min"] = startm if startm is not None else rng.integers(8 * 60, 16 * 60, n)
        return d

    def bump(df, new_code, scen):
        df = df.copy(); df["code"] = new_code; return df

    def upcode(pid, start, share, scen, truth=True):
        mask = (base.provider_id == pid) & base.code.isin(["99212", "99213", "99214"]) & (base.service_date >= start) & (base.pos == "11")
        idx = base.index[mask & (rng.random(len(base)) < share)]
        base.loc[idx, "code"] = "99215"; base.loc[idx, "duration_min"] = rng.integers(15, 28, len(idx))
        if truth:
            base.loc[idx, "truth"] = True; base.loc[idx, "scenario"] = scen

    ST = lambda s: pd.Timestamp(s)

    # S1 lab referral ring (lab + two practices, shared ownership)
    lab, p0, p1 = P("LAB", 0), P("PRO", 0), P("PRO", 1)
    ring = rng.choice(np.where(np.isin(m.region.values, [0, 1]) & (m.death_date.isna()).values & m.term_date.isna().values)[0], 240, replace=False)
    m.loc[ring, "pcp"] = rng.choice([p0, p1], len(ring))
    ev_n = rng.integers(2, 6, len(ring))
    ri = np.repeat(ring, ev_n)
    d1 = ST("2024-09-15") + pd.to_timedelta((rng.random(len(ri)) * (END - ST("2024-09-15")).days).astype(int), unit="D")
    codes1 = rng.choice(["80053", "85025", "83036"], len(ri), p=[.5, .3, .2])
    s1 = line(ri, lab, "LAB", "80053", d1, ref=m.pcp.values[ri], pos="81"); s1["code"] = codes1
    inject(s1, "S1-lab-ring", truth=False)
    rep = s1.sample(frac=.45, random_state=1).copy(); rep["service_date"] += pd.to_timedelta(rng.integers(2, 6, len(rep)), unit="D")
    inject(rep, "S1-lab-ring")
    ub = s1[s1.code == "80053"].sample(frac=.6, random_state=2)
    for c in ["82947", "82565", "84132"]:
        x = ub.copy(); x["code"] = c; inject(x, "S1-lab-ring")
    inject(s1.sample(frac=.05, random_state=3), "S1-lab-ring")
    # practice visits for ring members (legit volume) + p0 upcoding
    pv = line(ri[: len(ring) * 2], np.where(rng.random(len(ring) * 2) < .5, p0, p1), "PRO", "99213",
              ST("2024-09-01") + pd.to_timedelta(rng.integers(0, 360, len(ring) * 2), unit="D"))
    pv["code"] = rng.choice(["99212", "99213", "99214"], len(pv), p=[.15, .55, .30])
    inject(pv, "S1-lab-ring", truth=False)
    # S4 upcoders (written later on merged base), S1 practice p0 included
    # S2 DME / home health ring: phantom after discharge, after death
    d0, d1_, h0, ger = P("DME", 0), P("DME", 1), P("HH", 0), P("PRO", 2)
    late = stays[stays.discharge_date >= ST("2025-01-10")]
    sel = late.sample(n=min(75, len(late)), random_state=4)
    for _, r in sel.iterrows():
        span = max(1, (r.discharge_date - r.admit_date).days - 1)
        dt = r.admit_date + pd.Timedelta(days=int(rng.integers(1, span + 1)))
        prv, code = (d0, "K0823") if rng.random() < .55 else (d1_, "L1832")
        inject(line([r.mi], prv, "DME", code, [dt], ref=ger), "S2-dme-hh-ring")
        if rng.random() < .55:
            inject(line([r.mi], h0, "HH", "G0299", [dt + pd.Timedelta(days=int(rng.integers(0, 2)))], ref=ger, pos="12"), "S2-dme-hh-ring")
    dead_m = m.index[m.death_date.notna() & (m.death_date > ST("2025-01-15"))]
    for mi in dead_m[:8]:
        dt = m.death_date[mi] + pd.Timedelta(days=int(rng.integers(5, 40)))
        if dt > END: continue
        inject(line([mi], d1_, "DME", "L1832", [dt], ref=ger), "S2-dme-hh-ring")
        inject(line([mi], h0, "HH", "G0299", [dt, dt + pd.Timedelta(days=3)][0:1], ref=ger, pos="12"), "S2-dme-hh-ring")
    gm = rng.choice(np.where(m.age.values >= 65)[0], 90, replace=False)
    gd = ST("2025-01-10") + pd.to_timedelta(rng.integers(0, 230, 90), unit="D")
    inject(line(gm, np.where(rng.random(90) < .5, d0, d1_), "DME", "L1832", gd, ref=ger), "S2-dme-hh-ring", truth=False)
    m.loc[gm, "pcp"] = ger
    # S3 behavioral health: impossible timing, excess, time-based upcoding
    bh = P("BH", 0)
    bhm = rng.choice(np.where(m.region.values == 1)[0], 70, replace=False)
    wk = pd.bdate_range("2024-06-03", END)
    days = rng.choice(wk, 40, replace=False)
    for dday in days:
        mi = rng.choice(bhm, 20, replace=False)
        inject(line(mi, bh, "BH", "90837", [dday] * 20, startm=360 + np.arange(20) * 45), "S3-bh-timing")
    for mi in bhm[:25]:
        s = ST("2024-08-05") + pd.Timedelta(days=int(rng.integers(0, 140)))
        ds = [dd for dd in pd.bdate_range(s, periods=45) if dd <= END]
        inject(line([mi] * len(ds), bh, "BH", "90837", ds), "S3-bh-timing")
    mk = (base.provider_id == bh) & (base.code == "90837") & (base.service_date >= ST("2024-06-01"))
    ix = base.index[mk & (rng.random(len(base)) < .6)]
    base.loc[ix, "duration_min"] = rng.integers(28, 46, len(ix)); base.loc[ix, "truth"] = True; base.loc[ix, "scenario"] = "S3-bh-timing"
    # S4 upcoders
    upcode(p0, ST("2024-11-01"), .75, "S1-lab-ring")
    upcode(P("PRO", 3), ST("2024-08-01"), .80, "S4-upcoding")
    upcode(P("PRO", 4), ST("2025-02-01"), .75, "S4-upcoding")
    c3 = rng.choice(np.where(m.region.values == 3)[0], 150, replace=False)
    m.loc[c3, "pcp"] = P("PRO", 3)
    xv = line(c3, P("PRO", 3), "PRO", "99215", ST("2024-08-01") + pd.to_timedelta(rng.integers(0, 390, 150), unit="D"))
    inject(xv, "S4-upcoding")
    # S5 compounding pharmacy
    ph0, ph1, pain = P("PHARM", 0), P("PHARM", 1), P("PRO", 5)
    pm = rng.choice(np.where(m.region.values == 4)[0], 140, replace=False)
    m.loc[pm, "pcp"] = pain
    for k in range(7):
        dts = ST("2025-02-03") + pd.Timedelta(days=30 * k) + pd.to_timedelta(rng.integers(0, 4, len(pm)), unit="D")
        sub = pm[rng.random(len(pm)) < .75]
        inject(line(sub, ph0, "PHARM", "RX-COMP", dts[: len(sub)], ref=pain, pos="01"), "S5-compounding")
    dup = line(pm[:60], ph1, "PHARM", "RX-COMP", ST("2025-03-04") + pd.to_timedelta(rng.integers(0, 120, 60), unit="D"), ref=pain, pos="01")
    inject(dup, "S5-compounding")
    for mi in pm[:55]:
        s = ST("2025-03-01") + pd.Timedelta(days=int(rng.integers(0, 40)))
        ds = [s + pd.Timedelta(days=11 * j) for j in range(8) if s + pd.Timedelta(days=11 * j) <= END]
        inject(line([mi] * len(ds), ph0, "PHARM", "RX-OPI", ds, ref=pain, pos="01"), "S5-compounding")
    # S6 ambulance
    amb0 = P("AMB", 0)
    am = stays.sample(n=40, random_state=6)
    for _, r in am.iterrows():
        dt = r.admit_date + pd.Timedelta(days=int(rng.integers(1, max(2, (r.discharge_date - r.admit_date).days))))
        if dt < ST("2024-12-01"): dt = ST("2024-12-01") + pd.Timedelta(days=int(rng.integers(0, 200)))
        inject(line([r.mi], amb0, "AMB", "A0427", [dt], pos="41", dur=35), "S6-ambulance")
        inject(line([r.mi], amb0, "AMB", "A0425", [dt], units=int(rng.integers(40, 90)), pos="41", dur=0), "S6-ambulance")
    ma = (base.provider_id == amb0)
    ixb = base.index[ma & (base.code == "A0428") & (rng.random(len(base)) < .8)]
    base.loc[ixb, "code"] = "A0427"; base.loc[ixb, "truth"] = True; base.loc[ixb, "scenario"] = "S6-ambulance"
    ixm = base.index[ma & (base.code == "A0425")]
    base.loc[ixm, "units"] = (base.loc[ixm, "units"] * 3).astype(int); base.loc[ixm, "truth"] = True; base.loc[ixm, "scenario"] = "S6-ambulance"
    extra_a = rng.choice(n_members, 120, replace=False)
    ad = ST("2024-12-01") + pd.to_timedelta(rng.integers(0, 270, 120), unit="D")
    inject(line(extra_a, amb0, "AMB", "A0427", ad, pos="41", dur=35), "S6-ambulance", truth=False)
    # S7 facility duplicates
    f2 = P("FAC", 2)
    fx = base[(base.provider_id == f2) & (base.service_date >= ST("2025-03-01")) & (base.code != "INP-DAY")]
    fd = fx.sample(frac=.0, random_state=1) if len(fx) == 0 else fx.sample(frac=.35, random_state=1)
    # add ED volume to this hospital then duplicate part of it
    fm = rng.choice(np.where(m.region.values == 1)[0], 160, replace=False)
    fe = line(fm, f2, "FAC", "99283", ST("2025-03-01") + pd.to_timedelta(rng.integers(0, 180, 160), unit="D"), pos="23")
    fe["code"] = rng.choice(["99283", "99285"], 160, p=[.6, .4])
    inject(fe, "S7-facility-dup", truth=False)
    dd_ = fe.sample(frac=.3, random_state=2).copy(); dd_["service_date"] += pd.to_timedelta(0, unit="D")
    inject(dd_, "S7-facility-dup")
    # S8 home health phantom
    h1 = P("HH", 1)
    s8 = stays[stays.discharge_date >= ST("2025-04-01")].sample(n=28, random_state=8) if (stays.discharge_date >= ST("2025-04-01")).sum() >= 28 else stays[stays.discharge_date >= ST("2025-04-01")]
    for _, r in s8.iterrows():
        for j in range(int(rng.integers(2, 4))):
            dt = r.admit_date + pd.Timedelta(days=min(j + 1, max(1, (r.discharge_date - r.admit_date).days - 1)))
            if dt < ST("2025-04-01"): dt = r.discharge_date - pd.Timedelta(days=1)
            inject(line([r.mi], h1, "HH", "G0299", [dt], ref=m.pcp.values[r.mi], pos="12"), "S8-hh-phantom")
    hm = rng.choice(np.where(m.region.values == 5)[0], 110, replace=False)
    for mi in hm:
        s = ST("2025-04-01") + pd.Timedelta(days=int(rng.integers(0, 120)))
        ds = [s + pd.Timedelta(days=3 * j) for j in range(6) if s + pd.Timedelta(days=3 * j) <= END]
        inject(line([mi] * len(ds), h1, "HH", "G0299", ds, ref=m.pcp.values[mi], pos="12"), "S8-hh-phantom", truth=False)
    # S9 HELD-OUT scheme (no rule targets it): patient-recruitment mill. A practice suddenly sees a wave of
    # members from distant regions, each getting one identical visit bundle plus a lab panel at one lab.
    mill, mlab = P("PRO", 8), P("LAB", 5)
    setp(mill, name="Northgate Wellness Partners", specialty="Family medicine", region=5, city=REGIONS[5][0])
    far = rng.choice(np.where(np.isin(m.region.values, [0, 1, 3]) & m.death_date.isna().values & m.term_date.isna().values)[0], 190, replace=False)
    md = ST("2025-03-03") + pd.to_timedelta(rng.integers(0, 170, len(far)), unit="D")
    md = pd.to_datetime([d - pd.Timedelta(days=max(0, d.dayofweek - 4)) for d in md])
    inject(line(far, mill, "PRO", "99214", md, dx=np.array(["Z00.00"] * len(far))), "S9-recruitment-mill")
    inject(line(far, mill, "PRO", "93000", md, dx=np.array(["Z00.00"] * len(far))), "S9-recruitment-mill")
    for code in ("80053", "85025", "83036"):
        inject(line(far, mlab, "LAB", code, md, ref=np.array([mill] * len(far)), pos="81", dx=np.array(["Z00.00"] * len(far))), "S9-recruitment-mill")
    # decoys: oncology upcoding-like mix, dialysis lab monitoring, high-volume regional clinic
    onc = P("PRO", 6)
    om = rng.choice(np.where(m.region.values == 0)[0], 90, replace=False)
    m.loc[om, "pcp"] = onc
    ov = line(np.repeat(om, 4), onc, "PRO", "99215", ST("2024-02-01") + pd.to_timedelta(rng.integers(0, 580, len(om) * 4), unit="D"))
    ov["code"] = rng.choice(["99214", "99215"], len(ov), p=[.45, .55])
    inject(ov, "decoy-oncology", truth=False)
    dl = P("LAB", 3)
    dm = rng.choice(np.where(m.region.values == 1)[0], 40, replace=False)
    for mi in dm:
        ds = [ST("2024-03-04") + pd.Timedelta(days=7 * j) for j in range(70) if ST("2024-03-04") + pd.Timedelta(days=7 * j) <= END]
        x = line([mi] * len(ds), dl, "LAB", "80053", ds, ref=m.pcp.values[mi], pos="81")
        x["dx"] = np.where(rng.random(len(x)) < .5, "N18.6", None)
        inject(x, "decoy-dialysis", truth=False)
    rc = P("PRO", 7)
    rm = rng.choice(n_members, 320, replace=False)
    m.loc[rm, "pcp"] = rc
    rv = line(np.repeat(rm, 3), rc, "PRO", "99213", ST("2024-01-15") + pd.to_timedelta(rng.integers(0, 590, len(rm) * 3), unit="D"))
    rv["code"] = rng.choice(["99212", "99213", "99214", "99215"], len(rv), p=[.12, .45, .35, .08])
    inject(rv, "decoy-volume", truth=False)

    # ---------------- legitimate anomalies (look suspicious, are legitimate) ----------------
    # Each has an OBSERVABLE explanation in provider_events.csv (enrolment updates, credentialing, contracts) and a
    # hidden ground-truth label in hidden/legit_anomalies.csv. A separate RNG keeps every other scenario unchanged.
    r2 = np.random.default_rng(seed + 991)
    events, legit = [], []

    def ev(pid, date, kind, detail, source):
        events.append(dict(provider_id=pid, event_date=str(ST(date).date()), event_type=kind, detail=detail, source=source))

    def visits(pid, members_idx, start, per_member, codes, probs, pos="11", dx=None, gap=None):
        rows = []
        for mi in members_idx:
            k = int(r2.integers(*per_member)); d0 = ST(start) + pd.Timedelta(days=int(r2.integers(0, 45)))
            ds = [d0 + pd.Timedelta(days=int(gap or r2.integers(20, 75)) * j) for j in range(k)]
            ds = [d for d in ds if d <= END]
            if not ds: continue
            x = line([mi] * len(ds), pid, "PRO", "99213", ds, pos=pos)
            x["code"] = r2.choice(codes, len(x), p=probs)
            x["duration_min"] = [CODES[c][3] for c in x.code]
            if dx is not None: x["dx"] = r2.choice(dx, len(x))
            rows.append(x)
        return pd.concat(rows) if rows else None

    alive = m.death_date.isna().values & m.term_date.isna().values
    # LA1 — opened two new clinics: volume ~4x from March 2025, new LOCAL patients with ordinary visit mix
    la1 = P("PRO", 9); setp(la1, name="Brookside Family Practice", specialty="Family medicine")
    reg1 = int(prov.loc[prov.provider_id == la1, "region"].iat[0])
    pool = np.where((m.region.values == reg1) & alive & (m.pcp.values != la1))[0]
    x = visits(la1, r2.choice(pool, min(len(pool), 230), replace=False), "2025-03-01", (2, 4), ["99212", "99213", "99214", "99215", "93000"], [.12, .48, .30, .06, .04])
    inject(x, "legit-new-clinics", truth=False)
    ev(la1, "2025-02-17", "location_opened", "New service location: Brookside Elm Street clinic", "provider enrolment update")
    ev(la1, "2025-03-03", "location_opened", "New service location: Brookside Riverside clinic", "provider enrolment update")
    legit.append((la1, "new-clinics", "2025-03-01", "Opened two new clinics; new local patients with an ordinary visit mix.", True))
    # LA2 — cardiologist joined an internal-medicine group: more level-4/5 visits + ECGs for older cardiac patients
    la2 = P("PRO", 10); setp(la2, name="Valley Internal Medicine", specialty="Internal medicine")
    reg2 = int(prov.loc[prov.provider_id == la2, "region"].iat[0])
    pool = np.where((m.region.values == reg2) & alive & (m.age.values >= 60))[0]
    x = visits(la2, r2.choice(pool, min(len(pool), 110), replace=False), "2025-01-06", (3, 6), ["99214", "99215", "93000"], [.45, .38, .17],
               dx=["I50.9", "I25.10", "I48.91", "I10"])
    inject(x, "legit-specialist-joined", truth=False)
    ev(la2, "2025-01-06", "clinician_joined", "Cardiologist credentialed to the group (heart failure / arrhythmia clinic)", "credentialing roster")
    legit.append((la2, "specialist-joined", "2025-01-06", "A cardiologist joined; complex cardiac patients justify higher visit levels and ECGs.", True))
    # LA3 — nursing-facility contract: wave of frail new patients, similar monthly visit bundle, all with other care in the plan
    la3 = P("PRO", 11); setp(la3, name="Evergreen House Calls", specialty="Geriatric medicine")
    reg3 = int(prov.loc[prov.provider_id == la3, "region"].iat[0])
    pool = np.where((m.region.values == reg3) & alive & (m.age.values >= 70))[0]
    x = visits(la3, r2.choice(pool, min(len(pool), 70), replace=False), "2025-04-01", (3, 6), ["99213", "99214", "99215"], [.30, .55, .15], pos="32",
               dx=["I10", "E11.9", "J44.9", "F03.90"], gap=30)
    inject(x, "legit-nursing-contract", truth=False)
    ev(la3, "2025-03-24", "contract_started", "Attending-physician contract with Maplewood Care Center (nursing facility, 120 beds)", "contract registry")
    legit.append((la3, "nursing-contract", "2025-04-01", "Started covering a nursing facility; frail residents need monthly visits.", True))
    # LA4 — practice acquisition: the acquired practice's patients move to the acquirer, whose new-patient count jumps
    la4, la4b = P("PRO", 12), P("PRO", 13)
    setp(la4, name="Summit Ridge Medical", specialty="Family medicine"); setp(la4b, name="Crestline Family Doctors", specialty="Family medicine")
    acq = ST("2025-02-03")
    moved = (base.provider_id == la4b) & (base.service_date >= acq)
    base.loc[moved, "provider_id"] = la4; base.loc[moved, "scenario"] = "legit-acquisition"
    m.loc[m.pcp == la4b, "pcp"] = la4
    ev(la4, "2025-02-03", "acquisition", f"Acquired Crestline Family Doctors ({la4b}); its patients transferred to Summit Ridge", "ownership disclosure")
    setp(la4b, org_id=prov.loc[prov.provider_id == la4, "org_id"].iat[0])
    legit.append((la4, "acquisition", "2025-02-03", "Acquired another practice; its existing patients moved over.", True))
    # adversarial check: a provider that IS upcoding also has a genuine-looking business event. Context must not hide it.
    ev(P("PRO", 4), "2025-01-20", "location_opened", "New service location: Pinnacle West clinic", "provider enrolment update")
    legit.append((P("PRO", 4), "fraud-with-event", "2025-02-01", "Upcoding scheme (S4) that coincides with a real new location.", False))

    allx = pd.concat([base] + new, ignore_index=True)
    allx["service_date"] = allx.service_date.clip(upper=END)
    allx["service_end_date"] = allx.service_end_date.fillna(allx.service_date).clip(upper=END)
    allx = allx[allx.service_date >= START].copy()
    # drop normal-looking lines after member term/death where not scenario phantom
    mm = m.set_index("member_id")
    endd = mm.term_date.fillna(mm.death_date)
    ed = allx.member_id.map(endd)
    allx = allx[~((ed.notna()) & (allx.service_date > ed) & (~allx.scenario.str.startswith("S2")) & (~allx.scenario.str.startswith("S8")))].copy()
    # drop scenario-less lines after death
    allx = allx.sort_values(["service_date", "member_id"]).reset_index(drop=True)
    allx["line_id"] = [f"L{i + 1:07d}" for i in range(len(allx))]
    # claim ids: group lines of same member/provider/date into a claim, except duplicates get their own
    allx["_g"] = allx.groupby(["member_id", "provider_id", "service_date"]).cumcount()
    key = allx.groupby(["member_id", "provider_id", "service_date"], sort=False).ngroup()
    allx["claim_id"] = [f"C{k + 1:07d}" for k in key]
    allx["line_no"] = allx.groupby("claim_id").cumcount() + 1
    pr = allx.code.map(lambda c: price(c))
    allx["paid"] = (pr * allx.units * rng.uniform(.93, 1.05, len(allx))).round(2)
    allx["billed"] = (allx.paid * rng.uniform(1.6, 2.8, len(allx))).round(2)
    lag = rng.integers(10, 45, len(allx))
    allx["paid_date"] = allx.service_end_date + pd.to_timedelta(lag, unit="D")
    allx["modifier"] = ""
    fac_map = fam_prov["FAC"]
    allx["facility_id"] = np.where(allx.pos.isin(["21", "23"]), np.where(allx.family == "FAC", allx.provider_id, allx.member_id.map(stays.drop_duplicates("member_id").set_index("member_id").facility_id)), None)
    allx.loc[allx.family == "LAB", "dx"] = allx.loc[allx.family == "LAB", "dx"]
    cols = ["line_id", "claim_id", "line_no", "member_id", "provider_id", "facility_id", "referring_provider_id", "family",
            "service_date", "service_end_date", "paid_date", "code", "units", "billed", "paid", "pos", "dx", "modifier",
            "start_min", "duration_min"]
    lines = allx[cols].copy()
    truth = allx[["line_id", "truth", "scenario"]].copy()

    # referrals table
    rf = lines[lines.referring_provider_id.notna()][["line_id", "referring_provider_id", "provider_id", "member_id", "service_date", "family"]].copy()
    rf.columns = ["referral_id", "referring_provider_id", "receiving_provider_id", "member_id", "referral_date", "service_family"]
    rf["referral_id"] = rf.referral_id.str.replace("L", "R")

    # relationships
    rel = []
    for _, r in prov.iterrows():
        rel.append((r.provider_id, r.org_id, "owned_by", "enrollment_ownership_disclosure"))
    for col, typ in [("address_id", "located_at"), ("bank_id", "paid_to_account")]:
        for _, r in prov.iterrows():
            rel.append((r.provider_id, r[col], typ, "provider_enrollment" if col == "address_id" else "payment_remittance"))
    relationships = pd.DataFrame(rel, columns=["entity_a", "entity_b", "relationship_type", "source"])
    stay_out = stays[["member_id", "admit_date", "discharge_date", "facility_id"]].copy()
    stay_out.insert(0, "stay_id", [f"S{i + 1:05d}" for i in range(len(stay_out))])

    # investigation history (closed before as-of; some on bad actors, some decoys)
    inv_rows = [
        (P("BH", 0), "2024-02-10", "2024-04-20", "Confirmed overpayment", 18400),
        (P("PRO", 4), "2023-06-01", "2023-09-12", "Unfounded", 0),
        (P("LAB", 3), "2024-05-02", "2024-07-30", "Unfounded", 0),
        (P("PHARM", 1), "2024-03-01", "2024-06-01", "Education letter", 0),
        (P("DME", 1), "2023-11-15", "2024-02-01", "Confirmed overpayment", 9200),
        (P("PRO", 20), "2024-04-10", "2024-06-14", "Unfounded", 0),
        (P("LAB", 7), "2024-01-20", "2024-03-30", "Education letter", 0),
        (P("HH", 5), "2024-02-02", "2024-05-15", "Confirmed overpayment", 5300),
    ]
    inv = pd.DataFrame(inv_rows, columns=["provider_id", "opened_date", "closed_date", "outcome", "recovered_amount"])
    inv.insert(0, "investigation_id", [f"INV-{i + 1:04d}" for i in range(len(inv))])

    facilities = prov[prov.family == "FAC"][["provider_id", "name", "city", "lat", "lon"]].rename(columns={"provider_id": "facility_id"})
    facilities["licensed_beds"] = rng.integers(60, 420, len(facilities))

    members_out = m[["member_id", "age", "sex", "plan", "region", "enroll_date", "term_date", "death_date", "vulnerable", "pcp"]].copy()
    members_out["region"] = members_out.region.map(lambda r: REGIONS[r][0])
    providers_out = prov[["provider_id", "npi", "name", "family", "specialty", "city", "lat", "lon", "org_id", "address_id", "bank_id", "enrolled_date", "context_note"]]

    lines.to_csv(out / "claim_lines.csv", index=False)
    providers_out.to_csv(out / "providers.csv", index=False)
    members_out.to_csv(out / "members.csv", index=False)
    facilities.to_csv(out / "facilities.csv", index=False)
    rf.to_csv(out / "referrals.csv", index=False)
    relationships.to_csv(out / "relationships.csv", index=False)
    inv.to_csv(out / "investigations.csv", index=False)
    stay_out.to_csv(out / "inpatient_stays.csv", index=False)
    pe = pd.DataFrame(events); pe.insert(0, "event_id", [f"EVT-{i + 1:04d}" for i in range(len(pe))])
    pe.to_csv(out / "provider_events.csv", index=False)
    hid = out.parent / "hidden"; hid.mkdir(parents=True, exist_ok=True)
    truth.to_csv(hid / "scenario_truth.csv", index=False)
    lg = pd.DataFrame(legit, columns=["provider_id", "kind", "onset", "explanation", "legitimate"]); lg.to_csv(hid / "legit_anomalies.csv", index=False)
    from synthdata import truth as TR
    TR.build(allx, list(providers_out.provider_id), lg).to_csv(hid / "entity_truth.csv", index=False)
    return dict(lines=len(lines), providers=len(providers_out), members=len(members_out), truth_lines=int(truth.truth.sum()))


if __name__ == "__main__":
    print(generate())
