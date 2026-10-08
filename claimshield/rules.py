"""Versioned, explainable detection rules. Every rule produces claim-line flags that resolve to source rows."""
from __future__ import annotations

import numpy as np
import pandas as pd

RULESET_VERSION = "rules-1.0"

RULES = {
    "DUP": dict(name="Duplicate billing", severity=0.55, weight=.9, desc="Same member, code and service date billed more than once by one provider (or by several pharmacies/transporters/DME suppliers).",
                benign=["Legitimately separate encounters the same day (needs modifier or timestamp).", "Resubmission after a corrected claim."],
                check="Compare claim submission timestamps, modifiers and remittance records for the paired lines."),
    "REPEAT": dict(name="Repeat service inside minimum interval", severity=.6, weight=.9, desc="Same service repeated sooner than its policy minimum interval (labs, early refills, equipment purchased twice).",
                   benign=["Acute episode requiring repeat testing.", "Chronic monitoring (e.g. dialysis) with supporting diagnosis.", "Dose change prompting early refill."],
                   check="Request specimen / accession records, prescriber notes, or the clinical indication for the repeat."),
    "UNBUNDLE": dict(name="Unbundling", severity=.6, weight=.8, desc="Component tests billed separately alongside the comprehensive panel that already includes them.",
                     benign=["Component run for a distinct clinical reason on a separate specimen."],
                     check="Compare lab accession numbers and specimen IDs for panel vs. component lines."),
    "UPCODE": dict(name="Upcoding / level mismatch", severity=.6, weight=1.0, desc="Highest-level visit codes far above peer share, or a time-based code billed with documented time below its threshold.",
                   benign=["Patient panel with genuinely higher complexity (oncology, transplant, multi-morbidity).", "Time documented elsewhere in the record."],
                   check="Review a sample of charts against level-of-service documentation; compare patient acuity mix with peers."),
    "PHANTOM": dict(name="Service not plausibly rendered", severity=1.0, weight=1.2, desc="Billed during the member's inpatient stay by a community provider, or after the member's coverage termination / death date.",
                    benign=["Delivery ordered pre-admission and billed by date of order.", "Eligibility file lag or incorrect termination date.", "Late data correction of stay dates."],
                    check="Verify delivery receipts / visit notes / GPS logs and confirm eligibility and stay dates with source systems."),
    "TIMING": dict(name="Impossible timing", severity=.95, weight=1.2, desc="Provider bills more than 16 documented hours in a day, or a member has overlapping time-based services with different providers.",
                   benign=["Multi-clinician practice billed under one provider number.", "Group sessions billed per member."],
                   check="Obtain clinician schedules, sign-in sheets and rendering-provider identifiers for the flagged days."),
    "EXCESS": dict(name="Excessive utilization", severity=.7, weight=.8, desc="A member receives the same service far more often than a typical clinical pathway within a week.",
                   benign=["Intensive outpatient program.", "Acute episode requiring frequent visits."],
                   check="Review treatment plan and medical-necessity documentation; confirm member received the services."),
}

EM_HIGH = {"99215"}
EM_ALL = {"99212", "99213", "99214", "99215"}
COMPONENTS = {"82947", "82565", "84132"}
MIN_INTERVAL = {"80053": 7, "85025": 7, "83036": 30, "80305": 3, "80307": 7, "RX-OPI": 21, "RX-COMP": 21, "RX-BRAND": 21,
                "RX-GEN": 21, "K0823": 365 * 3, "L1832": 180}
CROSS_PROVIDER_REPEAT = {"K0823", "L1832"}
EXCESS_LIMIT = {"90837": 3, "90834": 3, "G0299": 7, "G0151": 5, "99213": 2, "99214": 2, "99215": 2, "80305": 3}
MONITORING_DX = {"N18.6"}
COMMUNITY_FAMILIES = {"DME", "HH", "AMB", "PHARM", "BH"}


def _prev_gap(df, keys):
    df = df.sort_values(keys + ["service_date", "line_id"])
    return df.groupby(keys).service_date.diff().dt.days


def apply_rules(lines: pd.DataFrame, members: pd.DataFrame, stays: pd.DataFrame, providers: pd.DataFrame):
    L = lines.copy()
    L["service_date"] = pd.to_datetime(L.service_date)
    L["service_end_date"] = pd.to_datetime(L.service_end_date)
    flags = pd.DataFrame(False, index=L.index, columns=list(RULES))
    detail = {k: {} for k in RULES}  # line_id -> short reason

    def mark(rule, idx, reasons):
        flags.loc[idx, rule] = True
        for i, r in zip(idx, reasons):
            detail[rule][L.at[i, "line_id"]] = r

    # ---- DUP ----
    skip = L.code.isin(["A0425", "INP-DAY"]) | (L.family == "HH") | (L.code == "90853")
    keys = ["member_id", "provider_id", "code", "service_date"]
    d = L[~skip].sort_values(keys + ["line_id"])
    dup_idx = d.index[d.duplicated(keys, keep="first")]
    first = d.drop_duplicates(keys, keep="first").set_index(keys).line_id
    r = [f"Repeats {first.get(tuple(L.loc[i, keys]), '?')} (same member, provider, code, date)" for i in dup_idx]
    mark("DUP", dup_idx, r)
    # cross-provider duplicates for pharmacy / ambulance / DME
    cp = L[L.family.isin(["PHARM", "AMB", "DME"]) & ~skip & ~L.index.isin(dup_idx)].sort_values(["member_id", "code", "service_date", "line_id"])
    k2 = ["member_id", "code", "service_date"]
    cp = cp[cp.duplicated(k2, keep=False)]
    cp = cp[cp.groupby(k2).provider_id.transform("nunique") > 1]
    cp_later = cp[cp.duplicated(k2, keep="first")]
    mark("DUP", cp_later.index, ["Same service billed same day by a different provider"] * len(cp_later))

    # ---- REPEAT ----
    rep_idx, rep_r = [], []
    for code, mi in MIN_INTERVAL.items():
        sub = L[(L.code == code) & ~L.index.isin(dup_idx)]
        if code in MONITORING_DX or sub.empty: pass
        keys_ = ["member_id"] if code in CROSS_PROVIDER_REPEAT else ["member_id", "provider_id"]
        gap = _prev_gap(sub, keys_)
        ok = gap.index[(gap > 0) & (gap < mi)]
        ok = [i for i in ok if L.at[i, "dx"] not in MONITORING_DX]
        rep_idx += ok
        rep_r += [f"{code} repeated {int(gap[i])} days after previous (policy minimum {mi})" for i in ok]
    mark("REPEAT", rep_idx, rep_r)

    # ---- UNBUNDLE ----
    lab = L[L.family == "LAB"]
    panel = lab[lab.code == "80053"][["member_id", "provider_id", "service_date"]].drop_duplicates().assign(_p=1)
    comp = lab[lab.code.isin(COMPONENTS)].reset_index().merge(panel, on=["member_id", "provider_id", "service_date"], how="left")
    comp = comp[comp._p == 1]
    mark("UNBUNDLE", comp["index"].values, [f"{c} billed with 80053 same day (included in panel)" for c in comp.code])

    # ---- UPCODE ----
    em = L[L.code.isin(EM_ALL) & (L.pos == "11")].copy()
    em["ym"] = em.service_date.dt.to_period("M")
    g = em.groupby(["provider_id", "ym"]).agg(n=("code", "size"), hi=("code", lambda s: (s.isin(EM_HIGH)).mean()))
    peer_hi = em.groupby("code").size()[ "99215"] / len(em)
    flag_pm = g[(g.n >= 12) & (g.hi >= max(.30, 3 * peer_hi))]
    em = L[L.code.isin(EM_HIGH) & (L.pos == "11")].assign(ym=lambda x: x.service_date.dt.to_period("M")).reset_index() \
        .merge(flag_pm.reset_index()[["provider_id", "ym"]].assign(_f=1), on=["provider_id", "ym"], how="left")
    em = em[em._f == 1]
    mark("UPCODE", em["index"].values, [f"Level-5 visit in a month where {int(flag_pm.loc[(p, y), 'hi'] * 100)}% of the provider's visits were level 5 (peer {peer_hi * 100:.0f}%)" for p, y in zip(em.provider_id, em.ym)])
    t = L[(L.code == "90837") & (L.duration_min < 53) & (L.duration_min > 0)]
    mark("UPCODE", t.index, [f"90837 requires ≥53 min; documented {int(x)} min" for x in t.duration_min])
    # ambulance ALS share
    am = L[L.family == "AMB"]
    sh = am[am.code.isin(["A0427", "A0428"])].groupby("provider_id").apply(lambda x: (x.code == "A0427").mean(), include_groups=False)
    hi_amb = sh[(sh > .75) & (am.groupby("provider_id").size().reindex(sh.index) > 40)].index
    am_x = am[am.provider_id.isin(hi_amb) & (am.code == "A0427")]
    mark("UPCODE", am_x.index, [f"ALS-level transport; provider's ALS share {sh[p] * 100:.0f}% vs ~45% peer" for p in am_x.provider_id])

    # ---- PHANTOM ----
    st = stays.copy()
    st["admit_date"] = pd.to_datetime(st.admit_date); st["discharge_date"] = pd.to_datetime(st.discharge_date)
    cand = L[L.family.isin(COMMUNITY_FAMILIES) & (L.pos != "21")].reset_index().merge(st[["member_id", "admit_date", "discharge_date", "stay_id"]], on="member_id")
    cand = cand[(cand.service_date > cand.admit_date) & (cand.service_date < cand.discharge_date) & (cand.family != "PHARM")]
    cand = cand.drop_duplicates("index")
    mark("PHANTOM", cand["index"].values, [f"Billed {d:%Y-%m-%d} while member inpatient {a:%Y-%m-%d}–{b:%Y-%m-%d} ({s})" for d, a, b, s in zip(cand.service_date, cand.admit_date, cand.discharge_date, cand.stay_id)])
    mm = members.set_index("member_id")
    endd = pd.to_datetime(mm.death_date).fillna(pd.to_datetime(mm.term_date))
    ed = L.member_id.map(endd)
    late = L[ed.notna() & (L.service_date > ed) & ~L.index.isin(cand["index"])]
    mark("PHANTOM", late.index, [f"Billed {d:%Y-%m-%d}, after member coverage end / death {e:%Y-%m-%d}" for d, e in zip(late.service_date, ed[late.index])])

    # ---- TIMING ----
    tm = L[L.duration_min > 0].copy()
    day = tm.groupby(["provider_id", "service_date"]).duration_min.sum()
    bad = day[day > 16 * 60]
    t1 = L.reset_index().merge(bad.rename("mins").reset_index(), on=["provider_id", "service_date"])
    t1 = t1[t1.duration_min > 0]
    mark("TIMING", t1["index"].values, [f"Provider billed {m / 60:.1f} documented hours on {d:%Y-%m-%d}" for m, d in zip(t1.mins, t1.service_date)])
    tm = tm[tm.family.isin(["BH", "HH", "PRO"])].sort_values(["member_id", "service_date", "start_min"])
    tm["end_min"] = tm.start_min + tm.duration_min
    tm["prev_end"] = tm.groupby(["member_id", "service_date"]).end_min.cummax().groupby([tm.member_id, tm.service_date]).shift()
    tm["prev_prov"] = tm.groupby(["member_id", "service_date"]).provider_id.shift()
    ov = tm[(tm.start_min < tm.prev_end) & (tm.provider_id != tm.prev_prov) & tm.prev_prov.notna() & (tm.pos != "21")]
    mark("TIMING", ov.index, ["Overlaps another provider's service for the same member"] * len(ov))

    # ---- EXCESS ----
    ex_idx, ex_r = [], []
    for code, lim in EXCESS_LIMIT.items():
        sub = L[L.code == code].sort_values(["member_id", "provider_id", "service_date", "line_id"])
        grp = sub.groupby(["member_id", "provider_id"]).service_date
        span = sub.service_date - grp.shift(lim)
        hit = sub[(span.dt.days <= 6)].index
        ex_idx += list(hit)
        ex_r += [f"{code}: more than {lim} visits within 7 days" for _ in hit]
    mark("EXCESS", ex_idx, ex_r)

    L["n_flags"] = flags.sum(axis=1)
    return L, flags, detail
