"""SpotZⁱ operations: pre-payment claim check, recoveries & savings, SIU reports, case documents, tips.
Pre-payment never denies: it recommends PAY or PEND FOR HUMAN REVIEW with reasons."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

from detection.rules import EXCESS_LIMIT, MIN_INTERVAL, MONITORING_DX, MUE_LIMIT, RULES
from synthdata import gen

COMPONENTS = {"82947", "82565", "84132"}


def schema(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS prepay_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, user_name TEXT, claim TEXT, recommendation TEXT, score REAL, reasons TEXT,
        amount REAL, status TEXT, resolved_by TEXT, resolution TEXT, avoided REAL, resolved_ts TEXT);
    CREATE TABLE IF NOT EXISTS recoveries(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, stage TEXT, identified REAL, recovered REAL, note TEXT, user_name TEXT, ts TEXT);
    CREATE TABLE IF NOT EXISTS custom_rules(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, conditions TEXT, active INTEGER DEFAULT 0, author TEXT, ts TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS case_documents(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, filename TEXT, mime TEXT, size INTEGER, path TEXT, sha256 TEXT, uploaded_by TEXT, ts TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS tips(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, channel TEXT, subject_type TEXT, subject_id TEXT, allegation TEXT, received_by TEXT,
        status TEXT, case_id TEXT, triaged_by TEXT, triage_note TEXT);
    CREATE TABLE IF NOT EXISTS plan_steps(case_id TEXT, step_key TEXT, status TEXT, note TEXT, user_name TEXT, ts TEXT, PRIMARY KEY(case_id, step_key));
    CREATE TABLE IF NOT EXISTS tip_ai(tip_id INTEGER PRIMARY KEY, ts TEXT, result TEXT);
    CREATE TABLE IF NOT EXISTS chart_reviews(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, ts TEXT, user_name TEXT, engine TEXT, result TEXT);
    """)


# =============================================================================== pre-payment claim check
def _line_model(S, claim, mid, pid, fam, d, pos, dx):
    """Trained pre-payment line-risk model (models/prepay_model.py) on this claim + the member's and provider's paid history."""
    from ai.models import prepay_model, registry

    art = registry.load("prepay_line_risk")
    if art is None or not claim.get("lines"):
        return None
    L = S["L"]
    H = L[(L.member_id == mid) | (L.provider_id == pid)][
        ["member_id", "provider_id", "code", "family", "units", "service_date", "pos", "dx", "duration_min"]
    ]
    cm = {k: v[3] for k, v in gen.CODES.items()}
    new = pd.DataFrame(
        [
            dict(
                member_id=mid,
                provider_id=pid,
                code=str(x.get("code", "")).strip(),
                family=fam or "OTHER",
                units=float(x.get("units") or 1),
                service_date=d,
                pos=pos,
                dx=dx,
                duration_min=cm.get(str(x.get("code", "")).strip(), 0) * float(x.get("units") or 1),
            )
            for x in claim["lines"]
        ]
    )
    U = pd.concat([H, new], ignore_index=True)
    X = prepay_model.features(
        U,
        S["T"]["members"],
        S["T"]["stays"][S["T"]["stays"].member_id == mid] if len(S["T"]["stays"]) else S["T"]["stays"],
        art["stats"],
        cm,
    ).iloc[len(H) :]
    p = art["model"].predict_proba(X)[:, 1]
    lines = [
        dict(p=round(float(pi), 3), drivers=prepay_model.explain(art["model"], X.iloc[[i]])) for i, pi in enumerate(p)
    ]
    return dict(max=float(p.max()), lines=lines)


def prepay_index(S):
    """Indexes over paid history, built once per run."""
    L = S["L"]
    by_mpc = {k: np.sort(g.values.astype("datetime64[D]")) for k, g in L.groupby(["member_id", "code"]).service_date}
    by_mppc = {
        k: np.sort(g.values.astype("datetime64[D]"))
        for k, g in L.groupby(["member_id", "provider_id", "code"]).service_date
    }
    day_min = L.groupby(["provider_id", "service_date"]).duration_min.sum().to_dict()
    same_day = L.groupby(["member_id", "provider_id", "code", "service_date"]).units.sum().to_dict()
    em = L[L.code.isin(["99212", "99213", "99214", "99215"])]
    end = L.service_date.max()
    em = em[em.service_date > end - pd.Timedelta(days=90)]
    hi_share = em.groupby("provider_id").code.apply(lambda s: (s == "99215").mean()).to_dict()
    return dict(by_mpc=by_mpc, by_mppc=by_mppc, day_min=day_min, same_day=same_day, hi_share=hi_share)


def prepay_score(S, IX, claim):
    t0 = time.time()
    PT, M, st = S["PT"], S["T"]["members"].set_index("member_id"), S["T"]["stays"]
    mid, pid = claim.get("member_id", "").strip(), claim.get("provider_id", "").strip()
    d = pd.Timestamp(claim.get("service_date"))
    pos = str(claim.get("pos") or "11")
    dx = claim.get("dx") or None
    reasons, line_out = [], []

    def why(rule, text, sev=None, line=None):
        reasons.append(
            dict(
                rule=rule,
                name=RULES[rule]["name"] if rule in RULES else rule,
                text=text,
                severity=sev if sev is not None else RULES.get(rule, {}).get("severity", 0.5),
                line=line,
            )
        )

    if pid not in PT.index:
        reasons.append(
            dict(
                rule="IDENTITY",
                name="Unknown provider",
                text=f"Provider {pid} is not on the enrolled provider file.",
                severity=0.9,
                line=None,
            )
        )
    if mid not in M.index:
        reasons.append(
            dict(
                rule="IDENTITY",
                name="Unknown member",
                text=f"Member {mid} is not on the eligibility file.",
                severity=0.9,
                line=None,
            )
        )
    fam = PT.at[pid, "family"] if pid in PT.index else None
    if mid in M.index:
        m = M.loc[mid]
        endd = m.death_date if pd.notna(m.death_date) else m.term_date
        if pd.notna(endd) and d > endd:
            why(
                "PHANTOM",
                f"Service date {d:%Y-%m-%d} is after coverage ended / death ({pd.Timestamp(endd):%Y-%m-%d}).",
                1.0,
            )
        if fam not in ("FAC",) and pos != "21" and len(st):
            ss = st[(st.member_id == mid) & (st.admit_date < d) & (st.discharge_date > d)]
            if len(ss):
                why(
                    "PHANTOM",
                    f"Member was an inpatient {ss.admit_date.iloc[0]:%Y-%m-%d} → {ss.discharge_date.iloc[0]:%Y-%m-%d} (stay {ss.stay_id.iloc[0]}).",
                    1.0,
                )
    ex = S["T"].get("exclusions")
    if ex is not None and len(ex) and pid in set(ex.provider_id):
        e = ex[ex.provider_id == pid].iloc[0]
        if d >= pd.Timestamp(e.excl_date) and pd.isna(e.get("reinstate_date")):
            why("EXCLUDED", f"Provider excluded since {e.excl_date} ({e.source}).", 1.0)
    codes = [str(x.get("code", "")).strip() for x in claim.get("lines", [])]
    day = np.datetime64(d.date())
    minutes = IX["day_min"].get((pid, d), 0)
    total = 0.0
    for i, ln in enumerate(claim.get("lines", [])):
        code = str(ln.get("code", "")).strip()
        units = float(ln.get("units") or 1)
        price = gen.CODES.get(code, (None, None, 0, 0))[2]
        billed = float(ln.get("billed") or price * units * 2)
        est = price * units if price else billed * 0.45
        total += est
        hits = []
        hist = IX["by_mppc"].get((mid, pid, code))
        if hist is not None and (hist == day).any():
            hits.append("DUP")
            why("DUP", f"{code} already paid for this member, provider and date.", line=i)
        mi = MIN_INTERVAL.get(code)
        if mi and dx not in MONITORING_DX:
            h = IX["by_mpc"].get((mid, code)) if code in ("K0823", "L1832") else hist
            if h is not None and len(h):
                prev = h[h < day]
                if len(prev) and (day - prev[-1]).astype(int) < mi:
                    hits.append("REPEAT")
                    why(
                        "REPEAT",
                        f"{code} repeated {(day - prev[-1]).astype(int)} days after the last one (minimum {mi}).",
                        line=i,
                    )
        if code in COMPONENTS and ("80053" in codes or IX["same_day"].get((mid, pid, "80053", d), 0) > 0):
            hits.append("UNBUNDLE")
            if not any(x["rule"] == "UNBUNDLE" for x in reasons):
                why(
                    "UNBUNDLE",
                    f"Component tests ({', '.join(c for c in codes if c in COMPONENTS)}) billed with panel 80053 the same day.",
                    line=i,
                )
        lim = MUE_LIMIT.get(code)
        if lim:
            u = (
                units
                + IX["same_day"].get((mid, pid, code, d), 0)
                + sum(
                    float(x.get("units") or 1)
                    for j, x in enumerate(claim["lines"])
                    if j < i and str(x.get("code")).strip() == code
                )
            )
            if u > lim:
                hits.append("MUE")
                why("MUE", f"{code}: {int(u)} units in one day (limit {lim}).", line=i)
        minutes += gen.CODES.get(code, (None, None, 0, 0))[3] * units
        el = EXCESS_LIMIT.get(code)
        if el and hist is not None:
            recent = ((day - hist[hist <= day]).astype(int) <= 6).sum()
            if recent >= el:
                hits.append("EXCESS")
                why("EXCESS", f"{code}: {int(recent) + 1} visits within 7 days (limit {el}).", line=i)
        if code == "99215" and IX["hi_share"].get(pid, 0) >= 0.3:
            hits.append("UPCODE")
            why("UPCODE", f"Provider billed level-5 for {IX['hi_share'][pid]:.0%} of recent visits (peer ≈7%).", line=i)
        line_out.append(
            dict(
                code=code,
                description=gen.CODES.get(code, ("", "Unknown code"))[1],
                units=units,
                billed=billed,
                expected_paid=round(est, 2),
                flags=hits,
            )
        )
    mdl = _line_model(S, claim, mid, pid, fam, d, pos, dx)
    if mdl:
        for lo, pr in zip(line_out, mdl["lines"]):
            lo["model_risk"] = pr["p"]
            lo["model_drivers"] = pr["drivers"]
    if minutes > 16 * 60:
        why("TIMING", f"Provider would bill {minutes / 60:.1f} documented hours on {d:%Y-%m-%d}.", 0.95)
    ctx = []
    if mdl and mdl["max"] >= 0.8:
        ctx.append(
            f"Trained line-risk model: {mdl['max']:.0%} ("
            + ", ".join(x["feature"] for x in max(mdl["lines"], key=lambda z: z["p"])["drivers"])
            + ")."
        )
    if pid in PT.index:
        r = PT.loc[pid]
        case = next((c["case_id"] for c in S["cases"] if pid in c["primary"]), None)
        if case:
            ctx.append(f"Provider is in open case {case}.")
        if r.risk >= 60:
            ctx.append(f"Provider risk {r.risk:.0f}/100.")
        if r.get("brain", 0) >= 0.9:
            ctx.append(f"Nexus Brain suspicion {r.brain * 100:.0f}/100.")
    sev = max([x["severity"] for x in reasons] or [0])
    score = min(100, 100 * sev * (1 + 0.15 * max(0, len(reasons) - 1)) + 8 * len(ctx))
    if sev >= 0.9 or len(reasons) >= 2 or (reasons and ctx):
        rec = "PEND"
    elif reasons or ctx:
        rec = "PAY_MONITOR"
    else:
        rec = "PAY"
    label = {"PEND": "Pend for human review", "PAY_MONITOR": "Pay — add to monitoring", "PAY": "Pay"}[rec]
    return dict(
        recommendation=rec,
        label=label,
        score=round(score, 1),
        reasons=reasons,
        context=ctx,
        lines=line_out,
        expected_paid=round(total, 2),
        model=dict(name="prepay_line_risk", max=mdl["max"]) if mdl else None,
        latency_ms=round((time.time() - t0) * 1000, 1),
        note="Recommendation only. A pended claim waits for a human; SpotZⁱ never denies a claim automatically.",
    )


EXAMPLES = None


def examples(S):
    """Realistic test claims drawn from the data (synthetic)."""
    L, st = S["L"], S["T"]["stays"]
    ex = []
    PT = S["PT"]
    dme = PT[(PT.family == "DME")].sort_values("risk", ascending=False).index[0]
    s_ = st[(st.discharge_date - st.admit_date).dt.days >= 4].sort_values("admit_date").iloc[-1]
    ex.append(
        dict(
            title="Wheelchair while the patient is in hospital",
            claim=dict(
                member_id=s_.member_id,
                provider_id=dme,
                service_date=str((s_.admit_date + pd.Timedelta(days=2)).date()),
                pos="12",
                lines=[dict(code="K0823", units=1, billed=6200)],
            ),
        )
    )
    r = L[(L.code == "80053") & ~L.any_flag].sample(1, random_state=3).iloc[0]
    ex.append(
        dict(
            title="Lab panel billed twice + components",
            claim=dict(
                member_id=r.member_id,
                provider_id=r.provider_id,
                service_date=str(r.service_date.date()),
                pos="81",
                dx=r.dx,
                lines=[dict(code="80053", units=1), dict(code="82947", units=1), dict(code="84132", units=1)],
            ),
        )
    )
    r = L[(L.code == "99213") & ~L.any_flag].sample(1, random_state=5).iloc[0]
    ex.append(
        dict(
            title="Routine office visit",
            claim=dict(
                member_id=r.member_id,
                provider_id=r.provider_id,
                service_date=str((r.service_date + pd.Timedelta(days=40)).date()),
                pos="11",
                dx=r.dx,
                lines=[dict(code="99213", units=1)],
            ),
        )
    )
    exl = S["T"].get("exclusions")
    if exl is not None and len(exl):
        pid = exl.provider_id.iloc[0]
        r = L[L.provider_id == pid].tail(1)
        if len(r):
            r = r.iloc[0]
            ex.append(
                dict(
                    title="Claim from an excluded supplier",
                    claim=dict(
                        member_id=r.member_id,
                        provider_id=pid,
                        service_date=str((r.service_date + pd.Timedelta(days=3)).date()),
                        pos="12",
                        lines=[dict(code="L1832", units=1, billed=1150)],
                    ),
                )
            )
    return ex


# =============================================================================== outcomes, ROI and SIU report
STAGES = ["Identified", "Demand letter sent", "Repayment plan", "Recovered", "Written off"]


def outcomes(c, S, rate=65.0, frm=None, to=None):
    rec = [dict(r) for r in c.execute("SELECT * FROM recoveries ORDER BY id").fetchall()]
    pre = [dict(r) for r in c.execute("SELECT * FROM prepay_log ORDER BY id").fetchall()]
    dec = [dict(r) for r in c.execute("SELECT * FROM decisions ORDER BY id").fetchall()]
    inr = lambda ts: (not frm or ts[:10] >= frm) and (not to or ts[:10] <= to)
    rec = [r for r in rec if inr(r["ts"])]
    pre = [p for p in pre if inr(p["ts"])]
    dec = [d for d in dec if inr(d["ts"])]
    last_rec = {}
    for r in rec:
        last_rec[r["case_id"]] = r
    identified = sum(r["identified"] or 0 for r in last_rec.values())
    recovered = sum(r["recovered"] or 0 for r in last_rec.values())
    avoided = sum(p["avoided"] or 0 for p in pre)
    cases = {c_["case_id"]: c_ for c_ in S["cases"]}
    worked = {d["case_id"] for d in dec}
    hours = sum(cases[x]["effort_hours"] for x in worked if x in cases)
    cost = hours * rate
    by_type = {}
    for cid, r in last_rec.items():
        t = cases[cid]["type"] if cid in cases else "Other"
        b = by_type.setdefault(t, dict(type=t, cases=0, identified=0.0, recovered=0.0))
        b["cases"] += 1
        b["identified"] += r["identified"] or 0
        b["recovered"] += r["recovered"] or 0
    last_dec = {}
    for d in dec:
        last_dec[d["case_id"]] = d
    first_dec = {}
    for d in dec:
        first_dec.setdefault(d["case_id"], d)
    outcomes_count = {}
    for d in last_dec.values():
        outcomes_count[d["outcome"]] = outcomes_count.get(d["outcome"], 0) + 1
    return dict(
        identified=identified,
        recovered=recovered,
        avoided=avoided,
        hours=hours,
        cost=cost,
        rate=rate,
        roi=((recovered + avoided) / cost) if cost else None,
        cases_with_recovery=len(last_rec),
        prepay=dict(
            checked=len(pre),
            pended=sum(p["recommendation"] == "PEND" for p in pre),
            resolved=sum(bool(p["status"] == "resolved") for p in pre),
        ),
        decisions=len(dec),
        cases_decided=len(last_dec),
        outcomes=outcomes_count,
        referrals=sum(1 for d in dec if d["outcome"] == "Approve referral"),
        by_type=sorted(by_type.values(), key=lambda x: -x["identified"]),
        recoveries=list(last_rec.values()),
        period=dict(frm=frm, to=to),
    )


# =============================================================================== documents
ALLOWED = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
MAGIC = {".pdf": b"%PDF", ".png": b"\x89PNG", ".jpg": b"\xff\xd8", ".jpeg": b"\xff\xd8", ".docx": b"PK", ".xlsx": b"PK"}


def safe_name(n):
    n = Path(n).name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", n)[:120] or "file"


def check_upload(name, data):
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise ValueError(f"File type {ext or '(none)'} not allowed. Allowed: {', '.join(sorted(ALLOWED))}")
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("File is larger than 20 MB")
    if ext in MAGIC and not data.startswith(MAGIC[ext]):
        raise ValueError("File content does not match its extension")
    return ALLOWED[ext], hashlib.sha256(data).hexdigest()
