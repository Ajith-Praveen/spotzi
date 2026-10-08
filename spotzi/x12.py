"""SpotZ^i X12 837 support (005010X222A1 professional / 005010X223A2 institutional).

parse_837(text)  -> dict of DataFrames shaped like SpotZ^i tables (claim_lines, providers, members, inpatient_stays)
export_837(...)  -> 837 text from SpotZ^i tables (used for round-trip tests and demo files)

Covers the loops SpotZ^i needs: billing provider (2010AA), subscriber/patient (2010BA, DMG), claim (CLM, DTP, HI),
referring provider (2310A/NM1*DN), service lines (LX + SV1/SV2 + DTP*472). Unknown segments are ignored; every
skipped or malformed segment is reported, never silently dropped.
Payment amounts: 837 carries billed charges only. Paid amounts come from 835 remittance; when absent SpotZ^i uses billed
amounts and marks the dataset as charge-based."""
from __future__ import annotations

import re

import pandas as pd

POS_FAMILY = {"81": "LAB", "21": "FAC", "22": "FAC", "23": "FAC", "41": "AMB", "42": "AMB", "12": "HH", "01": "PHARM"}
TAXONOMY_FAMILY = {"291U": "LAB", "282N": "FAC", "3336": "PHARM", "3416": "AMB", "251E": "HH", "332B": "DME", "1041": "BH", "103T": "BH", "2084": "BH", "207Q": "PRO", "208D": "PRO"}


FAMILY_TAXONOMY = {"LAB": "291U00000X", "PHARM": "333600000X", "AMB": "341600000X", "HH": "251E00000X", "DME": "332B00000X", "BH": "103T00000X", "FAC": "282N00000X", "PRO": "207Q00000X"}


def _seps(text):
    if not text.startswith("ISA"): raise ValueError("Not an X12 interchange (missing ISA)")
    el = text[3]; seg = text[105] if len(text) > 105 else "~"
    comp = text[104] if len(text) > 104 else ":"
    return el, seg, comp


def _d8(s):
    s = (s or "").split("-")[0]
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 else None


def parse_837(text: str):
    text = text.strip().replace("\r", "").replace("\n", "")
    el, seg, comp = _seps(text)
    segs = [s.split(el) for s in text.split(seg) if s.strip()]
    kind = "P"
    providers, members, lines, stays, issues = {}, {}, [], [], []
    bill = sub = ref = clm = None
    clm_dates = {}; dx = None; line_no = 0; pos = "11"
    cur = {}

    def _flush_stay():
        c_ = cur.get("clm"); d_ = cur.get("dates") or {}
        if c_ and d_.get("admit"):
            stays.append(dict(stay_id=f"S-{c_['claim_id']}", member_id=cur["member"], admit_date=d_["admit"], discharge_date=d_.get("discharge") or d_.get("end"), facility_id=cur["bill"]))
        cur.clear()
    for i, s in enumerate(segs):
        tag = s[0]
        try:
            if tag == "ST" and len(s) > 3: kind = "I" if "223" in s[3] else "P"
            elif tag == "GS" and len(s) > 8: kind = "I" if "223" in s[8] else kind
            elif tag == "HL":
                level = s[3] if len(s) > 3 else ""
                if level == "20": bill = {"id": None, "name": None, "tax": None}
                elif level in ("22", "23"): sub = {"id": None, "name": None, "dob": None, "sex": None}; ref = None
            elif tag == "NM1":
                q = s[1]
                if q == "85" and bill is not None:
                    bill["name"] = (s[3] or "").strip() + ((" " + s[4]) if len(s) > 4 and s[4] else "")
                    bill["id"] = s[9] if len(s) > 9 and s[9] else (bill["name"] or "UNKNOWN")
                elif q in ("IL", "QC") and sub is not None:
                    if len(s) > 9 and s[9]: sub["id"] = s[9]
                    sub["name"] = " ".join(x for x in (s[4] if len(s) > 4 else "", s[3]) if x)
                elif q == "DN":
                    ref = s[9] if len(s) > 9 and s[9] else None
            elif tag == "PRV" and bill is not None and len(s) > 3 and s[1] == "BI":
                bill["tax"] = s[3]
            elif tag == "DMG" and sub is not None:
                sub["dob"] = _d8(s[2]) if len(s) > 2 else None; sub["sex"] = s[3] if len(s) > 3 else "U"
            elif tag == "CLM":
                _flush_stay()
                if bill is None or sub is None or not bill["id"] or not sub["id"]:
                    issues.append(f"segment {i}: CLM before billing provider/subscriber; skipped"); clm = None; continue
                parts = s[5].split(comp) if len(s) > 5 else ["11"]
                pos = parts[0] or "11"
                clm = dict(claim_id=s[1], total=float(s[2] or 0), freq=parts[2] if len(parts) > 2 else "1")
                clm_dates = {}; dx = None; line_no = 0
                cur.update(clm=clm, dates=clm_dates, member=sub["id"], bill=bill["id"])
                providers.setdefault(bill["id"], dict(provider_id=bill["id"], name=bill["name"] or bill["id"], tax=bill["tax"], pos=set()))
                providers[bill["id"]]["pos"].add(pos)
                members.setdefault(sub["id"], dict(member_id=sub["id"], dob=sub["dob"], sex=sub["sex"]))
            elif tag == "DTP" and clm is not None:
                q, fmt, val = s[1], s[2], s[3]
                if q in ("434", "472"):
                    a, b = (val.split("-") + [val])[:2] if fmt == "RD8" else (val, val)
                    if q == "434": clm_dates.update(start=_d8(a), end=_d8(b))
                    else: clm_dates.update(line_start=_d8(a), line_end=_d8(b))
                    if q == "472" and lines and lines[-1]["claim_id"] == clm["claim_id"]:
                        lines[-1]["service_date"] = _d8(a); lines[-1]["service_end_date"] = _d8(b)
                elif q == "435": clm_dates["admit"] = _d8(val[:8])
                elif q == "096": clm_dates["discharge"] = _d8(val[:8])
            elif tag == "HI" and clm is not None and dx is None and len(s) > 1:
                code = s[1].split(comp)[1] if comp in s[1] else s[1]
                dx = (code[:3] + "." + code[3:]) if len(code) > 3 and "." not in code else code
            elif tag in ("SV1", "SV2") and clm is not None:
                line_no += 1
                if tag == "SV1":
                    proc = s[1].split(comp); code = proc[1] if len(proc) > 1 else proc[0]
                    charge = float(s[2] or 0); units = float(s[4] or 1) if len(s) > 4 else 1
                    lpos = s[5] if len(s) > 5 and s[5] else pos
                else:
                    proc = s[2].split(comp) if len(s) > 2 and s[2] else ["", s[1]]
                    code = proc[1] if len(proc) > 1 and proc[1] else (s[1] or "REV")
                    charge = float(s[3] or 0); units = float(s[5] or 1) if len(s) > 5 and s[5] else 1
                    lpos = pos
                lines.append(dict(line_id=f"{clm['claim_id']}-{line_no}", claim_id=clm["claim_id"], line_no=line_no, member_id=sub["id"], provider_id=bill["id"],
                                  referring_provider_id=ref, code=code, units=int(round(units)) or 1, billed=charge, paid=charge, pos=lpos, dx=dx,
                                  service_date=clm_dates.get("start"), service_end_date=clm_dates.get("end"), claim_frequency=clm["freq"]))
                providers[bill["id"]]["pos"].add(lpos)
            elif tag == "SE":
                _flush_stay()
        except Exception as e:
            issues.append(f"segment {i} ({tag}): {type(e).__name__}")
    if not lines: raise ValueError("No service lines found in 837 file")
    L = pd.DataFrame(lines)
    L = L[L.service_date.notna()].copy()
    P = []
    for p in providers.values():
        fam = next((f for k, f in TAXONOMY_FAMILY.items() if p["tax"] and p["tax"].startswith(k)), None)
        if not fam: fam = next((POS_FAMILY[x] for x in p["pos"] if x in POS_FAMILY), "FAC" if kind == "I" else "PRO")
        P.append(dict(provider_id=p["provider_id"], name=p["name"], family=fam, specialty=p["tax"] or "Unknown"))
    P = pd.DataFrame(P)
    L["family"] = L.provider_id.map(P.set_index("provider_id").family)
    M = pd.DataFrame(members.values())
    asof = pd.to_datetime(L.service_date).max()
    M["age"] = ((asof - pd.to_datetime(M.dob)).dt.days / 365.25).fillna(50).astype(int)
    M["sex"] = M.sex.fillna("U")
    out = dict(claim_lines=L.drop(columns=["claim_frequency"]), providers=P, members=M[["member_id", "age", "sex"]],
               inpatient_stays=pd.DataFrame(stays, columns=["stay_id", "member_id", "admit_date", "discharge_date", "facility_id"]))
    replaced = int((L.claim_frequency == "7").sum())
    return out, dict(kind=f"837{kind}", segments=len(segs), lines=len(L), claims=int(L.claim_id.nunique()), providers=len(P), members=len(M),
                     replacement_lines=replaced, issues=issues[:50], charge_based=True)


def export_837(L, P, M, kind="P", sender="SPOTZI", receiver="PAYER", limit=None):
    """Write SpotZ^i tables as a single 837 transaction (one billing-provider loop per provider)."""
    el, seg, comp = "*", "~", ":"
    S = []
    add = lambda *x: S.append(el.join(str(v) for v in x))
    L = L.copy()
    if limit: L = L.head(limit)
    add("ISA", "00", " " * 10, "00", " " * 10, "ZZ", sender.ljust(15), "ZZ", receiver.ljust(15), "251001", "1200", "^", "00501", "000000001", "0", "T", comp)
    add("GS", "HC", sender, receiver, "20251001", "1200", "1", "X", "005010X223A2" if kind == "I" else "005010X222A1")
    add("ST", "837", "0001", "005010X223A2" if kind == "I" else "005010X222A1")
    add("BHT", "0019", "00", "1", "20251001", "1200", "CH")
    Mi = M.set_index("member_id"); Pi = P.set_index("provider_id")
    hl = 0
    for pid, gp in L.groupby("provider_id"):
        hl += 1; parent = hl
        add("HL", hl, "", "20", "1")
        add("NM1", "85", "2", str(Pi.at[pid, "name"])[:60], "", "", "", "", "XX", pid)
        add("PRV", "BI", "PXC", FAMILY_TAXONOMY.get(Pi.at[pid, "family"], "207Q00000X"))
        for mid, gm in gp.groupby("member_id"):
            hl += 1
            add("HL", hl, parent, "22", "0")
            add("SBR", "P", "18", "", "", "", "", "", "", "CI")
            add("NM1", "IL", "1", "MEMBER", mid[-5:], "", "", "", "MI", mid)
            dob = pd.Timestamp("2025-08-31") - pd.Timedelta(days=int(Mi.at[mid, "age"]) * 365.25) if mid in Mi.index else pd.Timestamp("1970-01-01")
            add("DMG", "D8", dob.strftime("%Y%m%d"), str(Mi.at[mid, "sex"]) if mid in Mi.index and "sex" in Mi else "U")
            for cid, gc in gm.groupby("claim_id"):
                r0 = gc.iloc[0]
                add("CLM", cid, f"{gc.billed.fillna(gc.paid).sum():.2f}", "", "", f"{r0.pos or '11'}{comp}B{comp}1", "Y", "A", "Y", "Y")
                d0 = pd.Timestamp(r0.service_date).strftime("%Y%m%d"); d1 = pd.Timestamp(r0.service_end_date if pd.notna(r0.service_end_date) else r0.service_date).strftime("%Y%m%d")
                if kind == "I":
                    add("DTP", "434", "RD8", f"{d0}-{d1}")
                    if r0.code == "INP-DAY": add("DTP", "435", "D8", d0); add("DTP", "096", "D8", d1)
                if pd.notna(r0.dx) and r0.dx: add("HI", f"{'ABK' if True else 'BK'}{comp}{str(r0.dx).replace('.', '')}")
                if pd.notna(r0.referring_provider_id) and r0.referring_provider_id: add("NM1", "DN", "1", "REFERRING", "", "", "", "", "XX", r0.referring_provider_id)
                for n, r in enumerate(gc.itertuples(), 1):
                    add("LX", n)
                    if kind == "I": add("SV2", "0450", f"HC{comp}{r.code}", f"{(r.billed if pd.notna(r.billed) else r.paid):.2f}", "UN", int(r.units))
                    else: add("SV1", f"HC{comp}{r.code}", f"{(r.billed if pd.notna(r.billed) else r.paid):.2f}", "UN", int(r.units), r.pos or "11", "", "1")
                    if kind != "I": add("DTP", "472", "D8", pd.Timestamp(r.service_date).strftime("%Y%m%d"))
    add("SE", len(S) - 1, "0001"); add("GE", "1", "1"); add("IEA", "1", "000000001")
    return seg.join(S) + seg
