"""SpotZⁱ Precedent Intelligence (doc 22): retrieve comparable, quality-approved, human-reviewed cases;
show differences first; build an editable review blueprint. Never copies an outcome into the current decision.
The seeded library is SIMULATED human review, labelled as such."""
from __future__ import annotations

import numpy as np

RULES = ["DUP", "REPEAT", "UNBUNDLE", "UPCODE", "PHANTOM", "TIMING", "EXCESS"]
BANDS = {"$": ["<$10k", "$10–50k", ">$50k"]}

# Scenario templates: (code, family, setting, rule weights, motif, ownership, exceptions, checks[(name,result)], outcome, rationale)
T = [
    ("dup_vs_replace", "Duplicate billing vs replacement claims", "FAC", "hospital", {"DUP": 1.0}, "none", "none", ["reversal_pending"],
     [("Reconcile reversals and replacement lineage", "9 of 12 pairs were valid replacements"), ("Compare submission timestamps", "3 pairs resubmitted without adjustment")],
     "Narrowed: 9 pairs legitimate replacements; 3 pairs recommended for payment review", "Replacement lineage explained most pairs; only unreversed resubmissions remained."),
    ("dup_true", "Duplicate billing without lineage", "PRO", "group practice", {"DUP": 1.0, "REPEAT": .3}, "none", "none", [],
     [("Compare submission timestamps", "Same-minute duplicate submissions"), ("Reconcile reversals and replacement lineage", "No reversals found")],
     "Substantiated: duplicate payments; recoupment recommended (human-approved)", "No adjustment lineage and identical submissions; duplicate exposure confirmed."),
    ("lab_repeat_legit", "Repeat laboratory panels vs distinct specimens", "LAB", "independent", {"REPEAT": 1.0, "UNBUNDLE": .2}, "none", "none", ["monitoring_population"],
     [("Reconcile accession / specimen records", "Distinct specimens for 31 of 35 repeats"), ("Request clinical indication", "Dialysis monitoring documented")],
     "Closed: legitimate monitoring; 4 lines queried", "Specimen records separated the visits; documented chronic monitoring explained the cadence."),
    ("lab_repeat_bad", "Repeat laboratory panels, no distinct specimens", "LAB", "independent", {"REPEAT": 1.0, "UNBUNDLE": .8}, "referral_ring", "asserted", ["feed_gaps"],
     [("Reconcile accession / specimen records", "13 of 31 groups lacked a distinct specimen"), ("Verify ownership", "Ownership link unverified at review time")],
     "Escalated: 13 service groups; network scope held pending ownership verification", "Complete source coverage showed unsupported repeats; relationship evidence was only asserted."),
    ("unbundle", "Panel plus component billing", "LAB", "independent", {"UNBUNDLE": 1.0}, "none", "none", [],
     [("Reconcile accession / specimen records", "Components drawn from same specimen"), ("Review fee schedule", "Components included in panel")],
     "Substantiated: unbundled components; corrective education + recoupment (human-approved)", "Same accession for panel and components; policy states they are included."),
    ("bh_group", "Behavioral-health timing vs group sessions", "BH", "independent", {"TIMING": 1.0, "EXCESS": .5}, "none", "none", ["group_session_possible"],
     [("Obtain clinician schedules and sign-in sheets", "Group sessions billed per member"), ("Review treatment plan", "Intensive outpatient program documented")],
     "Closed: group sessions with documented program; billing guidance issued", "Per-member group billing explained the apparent hours; no overlap of individual sessions."),
    ("bh_bad", "Behavioral-health impossible hours", "BH", "independent", {"TIMING": 1.0, "UPCODE": .6, "EXCESS": .7}, "none", "none", [],
     [("Obtain clinician schedules and sign-in sheets", "Single clinician on schedule"), ("Chart sample against time documentation", "35–45 min documented for 60-min code")],
     "Referred (supervisor-approved): impossible hours and time-code mismatch", "Hours exceeded what one clinician could deliver; documented times contradicted billed codes."),
    ("upcode_specialty", "High-level visit share vs specialty mix", "PRO", "group practice", {"UPCODE": 1.0}, "none", "none", ["specialty_case_mix"],
     [("Chart sample against level-of-service documentation", "Documentation supported billed level"), ("Compare acuity mix with specialty peers", "Oncology panel, higher acuity")],
     "Closed: legitimate case mix; peer group refined", "Acuity and specialty explained the level mix; peer baseline was the issue."),
    ("upcode_bad", "Level-5 visit inflation", "PRO", "solo", {"UPCODE": 1.0, "DUP": .2}, "none", "none", [],
     [("Chart sample against level-of-service documentation", "Documentation supports level 3–4"), ("Compare acuity mix with peers", "No acuity difference")],
     "Substantiated: upcoding; recoupment and prepayment review recommended (human-approved)", "Chart sample did not support billed level; peer acuity was similar."),
    ("phantom_lag", "Services during stay — eligibility / stay-date lag", "DME", "independent", {"PHANTOM": 1.0}, "none", "none", ["eligibility_lag"],
     [("Verify delivery records and stay dates", "Delivered before admission; stay dates corrected")],
     "Closed: data error in stay dates", "Delivery receipts predated admission; the stay feed had been corrected late."),
    ("phantom_bad", "Services during inpatient stay, no delivery record", "DME", "independent", {"PHANTOM": 1.0, "REPEAT": .3}, "shared_ownership", "verified", [],
     [("Verify delivery records and stay dates", "No delivery or visit records"), ("Verify ownership", "Common control verified")],
     "Referred (supervisor-approved): services not rendered; linked suppliers in scope", "No proof of delivery while members were inpatient; verified common control across suppliers."),
    ("hh_phantom", "Home-health visits after discharge or death", "HH", "agency", {"PHANTOM": 1.0, "TIMING": .2}, "none", "none", [],
     [("Verify delivery records and stay dates", "Visit notes missing; dates after coverage end")],
     "Substantiated: visits not rendered", "Visit logs absent and dates fell outside coverage."),
    ("chain_pharm", "Shared ownership among chain pharmacies", "PHARM", "chain", {"REPEAT": .4}, "chain", "verified", ["routine_ownership"],
     [("Verify ownership", "Routine corporate chain"), ("Review refill intervals", "Dose changes documented")],
     "Closed: no concern; ownership routine", "Shared ownership alone did not indicate risk; refills had clinical reasons."),
    ("comp_bad", "Compounded drug concentration and early refills", "PHARM", "independent", {"REPEAT": 1.0, "DUP": .3}, "referral_ring", "asserted", [],
     [("Review prescriber relationship", "Single prescriber drove 85% of volume"), ("Review refill intervals", "Early refills without dose change")],
     "Escalated: prescriber–pharmacy relationship review", "Concentration and early refills without documented changes; relationship still being verified."),
    ("shift_mill", "Recruitment mill: sudden out-of-region member influx", "PRO", "independent", {}, "referral_ring", "none", [],
     [("Sample onset-month encounters and verify member acquisition", "Members recruited via paid transport; templated notes"), ("Verify referral independence", "All lab orders routed to one lab")],
     "Referred (supervisor-approved): recruitment scheme; linked lab in scope", "Templated encounters for out-of-region members with no prior relationship; referrals not independent."),
    ("shift_expansion", "Behaviour shift from a legitimate expansion", "PRO", "group practice", {}, "none", "none", ["documented_expansion"],
     [("Sample onset-month encounters and verify member acquisition", "New satellite clinic opened; members assigned by plan"), ("Review payer contract", "New community contract started that month")],
     "Closed: legitimate expansion; baseline reset", "The shift matched a documented new site and contract; encounter notes were individualised."),
    ("shift_lab", "Lab volume surge tied to one ordering practice", "LAB", "independent", {}, "referral_ring", "none", [],
     [("Verify referral independence", "One new practice ordered 90% of panels"), ("Sample onset-month encounters and verify member acquisition", "Orders lacked clinical indication")],
     "Escalated: lab in scope of linked practice review", "Volume surge was entirely from one practice under review; panels lacked indication."),
    ("amb_bad", "Ambulance level inflation and mileage", "AMB", "independent", {"UPCODE": 1.0, "PHANTOM": .5}, "none", "none", [],
     [("Chart sample against level-of-service documentation", "BLS-level transports billed as ALS"), ("Review trip logs", "Mileage 3× routed distance")],
     "Substantiated: level and mileage inflation", "Trip logs contradicted level and mileage."),
]


def _rng(seed): return np.random.default_rng(seed)


def seed_library(n_per=3, seed=42):
    rng = _rng(seed); lib = []
    for t in T:
        code, title, fam, setting, rw, motif, own, exc, checks, outcome, why = t
        for k in range(n_per):
            w = {r: float(np.clip(rw.get(r, 0) * rng.uniform(.7, 1.1), 0, 1)) for r in RULES}
            cov = float(np.clip(rng.normal(.9 if not exc or "feed_gaps" not in exc else .78, .07), .5, 1))
            lib.append(dict(id=f"PREC-{len(lib) + 1:04d}", code=code, title=title, family=fam, setting=setting, rules=w, motif=motif,
                            ownership=own if rng.random() > .2 else ("asserted" if own == "verified" else own), exceptions=exc, coverage=cov,
                            escalating=bool(rng.random() < (.6 if "bad" in code or code in ("dup_true", "unbundle", "phantom_bad") else .25)),
                            anomaly=str(rng.choice(["medium", "high"], p=[.4, .6])), exposure_band=int(rng.choice([0, 1, 2], p=[.3, .5, .2])),
                            member_band=int(rng.choice([0, 1, 2], p=[.35, .45, .2])), checks=[dict(check=c, result=r) for c, r in checks], outcome=outcome, rationale=why,
                            reviewer_role="supervisor" if "supervisor" in outcome else "investigator", quality="approved", closed=f"2024-{int(rng.integers(3, 13)):02d}-{int(rng.integers(1, 28)):02d}",
                            source="SIMULATED human review (seeded library)"))
    return lib


def fingerprint(c, d):
    tot = sum(c["rule_counts"].values()) or 1
    rules = {r: (0.0 if c.get("brain_lead") else float(c["rule_counts"].get(r, 0) / tot)) for r in RULES}
    top = max(rules.values()) or 1
    rules = {r: v / top for r, v in rules.items()}
    motif = "none"
    if c["network"]: motif = "referral_ring" if any(e["kind"] == "referral" for e in d["network"]["edges"]) else "shared_ownership"
    own = "none"
    if any(n["kind"] in ("ownership", "address", "bank") for n in d["network"]["nodes"]): own = "asserted"
    prov = max((p for p in d["providers"] if p["role"] == "primary"), key=lambda p: p["risk"])
    exc = [x for x in ("specialty_case_mix",) if c["benign_context"] and "case mix" in " ".join(c["benign_context"]).lower() or "complex" in " ".join(c["benign_context"]).lower()]
    if any("chain" in x.lower() for x in c["benign_context"]): motif, exc = "chain", exc + ["routine_ownership"]
    if any("dialysis" in x.lower() or "monitoring" in x.lower() for x in c["benign_context"]): exc.append("monitoring_population")
    fam = prov["family"]
    return dict(family=fam, setting={"FAC": "hospital", "PHARM": "chain" if motif == "chain" else "independent"}.get(fam, "independent"), rules=rules, motif=motif, ownership=own,
                exceptions=exc, coverage=float(1 - c["dx_missing"]), escalating=bool(c["escalating"]), anomaly="high" if c["anomalous"] else "medium",
                exposure_band=0 if c["exposure"] < 10000 else 1 if c["exposure"] < 50000 else 2,
                member_band=0 if c["members"] < 40 else 1 if c["members"] < 150 else 2)


def _cos(a, b):
    x = np.array([a[r] for r in RULES]); y = np.array([b[r] for r in RULES])
    d = np.linalg.norm(x) * np.linalg.norm(y)
    return float(x @ y / d) if d else 0.0


def compare(fp, p):
    """returns (similarity or None if ineligible, components, matches, differences, warnings)"""
    if fp["family"] != p["family"]: return None
    no_rules_now = not any(v > 0 for v in fp["rules"].values()); no_rules_p = not any(v > 0 for v in p["rules"].values())
    if no_rules_now or no_rules_p:  # learned-detector leads compare against behaviour-shift precedents only
        if not (no_rules_now and no_rules_p): return None
        pat = 1.0
    else:
        pat = _cos(fp["rules"], p["rules"])
    if pat < .35: return None
    comp = {}
    comp["pattern overlap"] = (.25, pat)
    comp["service and provider context"] = (.20, .5 * 1 + .5 * (1.0 if fp["setting"] == p["setting"] else .3))
    comp["evidence coverage"] = (.15, max(0, 1 - abs(fp["coverage"] - p["coverage"]) * 2.5))
    comp["temporal shape"] = (.15, 1.0 if fp["escalating"] == p["escalating"] else .4)
    comp["graph motif"] = (.15, 1.0 if fp["motif"] == p["motif"] else .5 if {fp["motif"], p["motif"]} <= {"referral_ring", "shared_ownership"} else .15)
    comp["financial / member band"] = (.10, 1 - (abs(fp["exposure_band"] - p["exposure_band"]) + abs(fp["member_band"] - p["member_band"])) / 4)
    wsum = sum(w for w, _ in comp.values())
    sim = sum(w * v for w, v in comp.values()) / wsum
    matches = [k for k, (w, v) in comp.items() if v >= .8]
    diffs, warn = [], []
    if fp["ownership"] != p["ownership"]:
        diffs.append(dict(area="Ownership evidence", current=fp["ownership"], precedent=p["ownership"], impact="Network evidence strength differs; do not assume the same scope applies." if fp["ownership"] == "asserted" else "Relationship evidence differs."))
    if abs(fp["coverage"] - p["coverage"]) > .12:
        diffs.append(dict(area="Evidence coverage", current=f"{fp['coverage'] * 100:.0f}%", precedent=f"{p['coverage'] * 100:.0f}%", impact="Different data completeness: the same inference may not be supportable."))
    if fp["setting"] != p["setting"]:
        diffs.append(dict(area="Provider setting", current=fp["setting"], precedent=p["setting"], impact="Peer behaviour may not transfer."))
    if fp["motif"] != p["motif"]:
        diffs.append(dict(area="Network motif", current=fp["motif"], precedent=p["motif"], impact="Structure differs; check whether relationship evidence applies."))
    for e in set(p["exceptions"]) - set(fp["exceptions"]):
        diffs.append(dict(area="Precedent exception absent here", current="not recorded", precedent=e.replace("_", " "), impact="That explanation drove the prior outcome; verify whether it exists in this case."))
    for e in set(fp["exceptions"]) - set(p["exceptions"]):
        diffs.append(dict(area="Current exception not in precedent", current=e.replace("_", " "), precedent="absent", impact="A benign context here was not present in the precedent."))
    if any(d["area"] in ("Evidence coverage", "Ownership evidence") for d in diffs):
        warn.append("Material difference: the prior outcome cannot be applied automatically.")
    if sim >= .8 and diffs:
        warn.append("High similarity with material contradictions — read the differences before the outcome.")
    return sim, {k: round(v, 2) for k, (w, v) in comp.items()}, matches, diffs, warn


def retrieve(fp, library, k=5):
    out = []
    for p in library:
        if p.get("quality") != "approved": continue
        r = compare(fp, p)
        if r is None: continue
        sim, comp, m, diffs, warn = r
        out.append(dict(precedent=p, similarity=sim, components=comp, matches=m, differences=diffs, warnings=warn))
    out.sort(key=lambda x: -x["similarity"])
    # diversity: best match per scenario template, so opposite outcomes of look-alike cases both appear
    seen, diverse = set(), []
    for m in out:
        code = m["precedent"]["code"]
        if code in seen: continue
        seen.add(code); diverse.append(m)
    return diverse[:k]


def blueprint_items(matches, selected=None):
    items, seen = [], {}
    for m in matches:
        if selected and m["precedent"]["id"] not in selected: continue
        for c in m["precedent"]["checks"]:
            key = c["check"]
            if key in seen:
                seen[key]["sources"].append(m["precedent"]["id"]); continue
            it = dict(text=key, why=f"Resolved ambiguity in {m['precedent']['id']}: {c['result']}", sources=[m["precedent"]["id"]], state="todo", note="")
            seen[key] = it; items.append(it)
    items += [dict(text="Reconcile claim lines and payments for the current case", why="Standard first step; evidence must come from the current case", sources=[], state="todo", note=""),
              dict(text="Record explicit alternative explanations tested", why="Required for the decision record", sources=[], state="todo", note=""),
              dict(text="Decide and record rationale (human only)", why="Outcome is never prefilled from a precedent", sources=[], state="todo", note="")]
    return items
