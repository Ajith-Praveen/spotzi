"""Investigation Readiness + Investigation Action Plan.

Risk says how suspicious a case looks. Readiness says whether the INVESTIGATION is complete enough to support a
referral: which evidence an SIU needs for this kind of case, what is already in hand, and what is missing. The action
plan turns the gaps into ordered, owned, time-boxed steps ("What should I actually do next?").

Readiness is a checklist score, not a probability. It never decides: referral below the readiness bar requires the
reviewer to acknowledge the gaps in writing, and that acknowledgement is audited."""

from __future__ import annotations

REFERRAL_BAR = 70

ITEMS = {  # key: (label, weight, owner, minutes, how)
    "billing_pattern": ("Billing pattern evidence", 20, "system", 0, "auto"),
    "peer_comparison": ("Peer comparison", 10, "system", 0, "auto"),
    "documentation": ("Provider documentation reviewed", 25, "investigator", 30, "chart_review"),
    "member_verification": ("Member / service verification", 15, "investigator", 45, "mark"),
    "referral_verification": ("Referral relationships verified", 10, "analyst", 30, "mark"),
    "context": ("Legitimate context ruled out", 10, "investigator", 20, "mark"),
    "precedent": ("Historical precedent", 5, "system", 0, "auto"),
    "data_quality": ("Data completeness", 5, "analyst", 15, "mark"),
}
VERIFY_TYPES = (
    "not plausibly rendered",
    "recruitment",
    "panel",
    "phantom",
    "equipment",
    "home-health",
    "excessive",
    "timing",
    "repeat",
    "impossible_timing",
    "excessive_services",
)


def applicable(c: dict, d: dict) -> dict:
    t = (
        (c["type"] or "").lower()
        + " "
        + " ".join(x["type"] for x in (c.get("scheme_types") or [])[:2] if x["p"] >= 0.25)
    )  # fraud-type model steers evidence
    rules = set(c.get("rules") or [])
    return dict(
        billing_pattern=True,
        peer_comparison=True,
        documentation=True,
        member_verification=any(k in t for k in VERIFY_TYPES)
        or bool(rules & {"PHANTOM", "EXCESS", "REPEAT", "TIMING"}),
        referral_verification=bool(c.get("network") or c.get("has_graph"))
        or any(p.get("role") == "linked" for p in d.get("providers", [])),
        context=True,
        precedent=True,
        data_quality=True,
    )


def assess(c: dict, d: dict, state: dict) -> dict:
    """state: chart (latest chart review | None), documents (int), steps ({key: row}), precedents (int)."""
    steps = state.get("steps", {})
    ap = applicable(c, d)
    ev_kinds = {e["kind"] for e in d["evidence"]}
    rule_lines = sum(e.get("n_lines", 0) for e in d["evidence"] if e["kind"] == "rule")
    chart = state.get("chart")
    auto = dict(
        billing_pattern=(
            rule_lines >= 5,
            f"{rule_lines} flagged lines across {len(c.get('rules') or [])} rule type(s)"
            if rule_lines
            else (
                "learned-detector evidence only"
                if ev_kinds & {"brain", "drift", "panel", "sentinel"}
                else "no billing evidence"
            ),
        ),
        peer_comparison=(
            bool(ev_kinds & {"anomaly", "sentinel"}),
            "peer-relative anomaly / case-mix comparison on file"
            if ev_kinds & {"anomaly", "sentinel"}
            else "no peer comparison",
        ),
        documentation=(
            bool(chart) or state.get("documents", 0) > 0,
            (
                f"chart review: {chart['summary']}"
                if chart
                else f"{state.get('documents', 0)} document(s) uploaded"
                if state.get("documents")
                else "no records reviewed yet"
            ),
        ),
        precedent=(state.get("precedents", 0) > 0, f"{state.get('precedents', 0)} comparable past case(s)"),
        data_quality=(
            c.get("dx_missing", 0) < 0.1,
            "diagnosis coverage adequate"
            if c.get("dx_missing", 0) < 0.1
            else f"{c.get('dx_missing', 0) * 100:.0f}% of lines lack a diagnosis",
        ),
        context=(
            not c.get("benign_context")
            and not c.get("context")
            and not any(p.get("context") for p in d.get("providers", [])),
            "no business events or context notes on file"
            if not (c.get("benign_context") or c.get("context"))
            else "business context on file — must be checked",
        ),
    )
    items = []
    for k, (label, w, owner, mins, how) in ITEMS.items():
        if not ap.get(k):
            continue
        st = steps.get(k)
        done, detail = auto.get(k, (False, "not yet verified"))
        if st and st["status"] in ("done", "skipped"):
            done, detail = st["status"] == "done", f"{st['status']} by {st['user_name']}: {st['note']}"
        items.append(
            dict(
                key=k,
                label=label,
                weight=w,
                done=bool(done),
                detail=detail,
                owner=owner,
                minutes=mins,
                how=how,
                skipped=bool(st and st["status"] == "skipped"),
            )
        )
    tot = sum(i["weight"] for i in items)
    got = sum(i["weight"] for i in items if i["done"])
    score = round(100 * got / tot) if tot else 0
    missing = [i for i in items if not i["done"]]
    supports = chart is not None and chart.get("reviewed", 0) >= 4 and chart.get("not_supported", 0) == 0
    if c.get("lane") == "Explained by context" and not next(
        (i for i in items if i["key"] == "context" and i["done"]), None
    ):
        rec, level = (
            "A recorded business event explains every signal in this case. Confirm the event, then close or monitor — do not refer unless the confirmation fails.",
            "stop",
        )
    elif supports:
        rec, level = (
            "Do not refer. The sampled documentation supports what was billed — consider closing or provider education.",
            "stop",
        )
    elif score >= 85:
        rec, level = (
            "Ready for a referral decision. A human reviewer decides; a supervisor approves (four-eyes).",
            "ready",
        )
    elif score >= REFERRAL_BAR:
        rec, level = (
            "Nearly ready. Close the remaining gaps before referring: "
            + ", ".join(i["label"].lower() for i in missing)
            + ".",
            "almost",
        )
    else:
        first = missing[0] if missing else None
        rec, level = ("Do not refer yet. " + (f"Next: {_action(first)}." if first else "")).strip(), "not_ready"
    return dict(
        score=score,
        level=level,
        recommendation=rec,
        items=items,
        missing=[i["label"] for i in missing],
        referral_bar=REFERRAL_BAR,
        plan=plan(c, d, items, steps),
    )


def _action(i):
    return {
        "documentation": "obtain provider documentation (request a chart sample)",
        "member_verification": "verify with members that services were received",
        "referral_verification": "verify referral relationships and ownership",
        "context": "confirm or rule out the legitimate business context",
        "data_quality": "obtain missing diagnosis / claim data",
        "billing_pattern": "collect more billing evidence",
        "peer_comparison": "run a peer comparison",
        "precedent": "review comparable past cases",
    }.get(i["key"], i["label"].lower())


HOWTO = {
    "context": (
        "Confirm or rule out the business context",
        "Check enrolment, credentialing and contract records for the events listed; confirm the timing matches the change in billing.",
    ),
    "documentation": (
        "Request and review a chart sample",
        "Pull a sample of records for flagged lines and compare documentation with what was billed (Chart review tab).",
    ),
    "member_verification": (
        "Verify services with members",
        "Send explanation-of-benefits confirmation letters or call a sample of members; confirm dates, places and services.",
    ),
    "referral_verification": (
        "Verify referral relationships",
        "Check ownership, address and bank links and referral concentration; confirm referrals were independent.",
    ),
    "data_quality": (
        "Fix data gaps",
        "Request missing diagnosis codes / claim attachments so medical necessity can be judged.",
    ),
    "billing_pattern": (
        "Collect billing evidence",
        "Widen the look-back or add a targeted analyst rule to quantify the pattern.",
    ),
    "peer_comparison": ("Compare with peers", "Compare against same-specialty peers in the Explorer."),
    "precedent": ("Review precedents", "Open the Precedents tab and note what resolved similar cases."),
}
ORDER = [
    "context",
    "documentation",
    "member_verification",
    "referral_verification",
    "data_quality",
    "billing_pattern",
    "peer_comparison",
    "precedent",
]


def plan(c, d, items, steps):
    by = {i["key"]: i for i in items}
    out, n = [], 0
    for k in ORDER:
        i = by.get(k)
        if not i or i["done"] or i["skipped"]:
            continue
        n += 1
        title, how = HOWTO[k]
        why = {
            "context": "; ".join(c.get("benign_context") or []) or "Business context is on file for this provider.",
            "documentation": "Billing patterns show what was paid, not what was done; documentation is the primary evidence for "
            + (", ".join(c.get("rules") or []) or "the behaviour shift")
            + ".",
            "member_verification": "Services that may not have been rendered must be confirmed with the people who supposedly received them.",
            "referral_verification": "Linked providers may be bystanders; relationships must be verified before anyone is implicated.",
            "data_quality": "Missing data limits clinical-necessity judgements.",
        }.get(k, "")
        out.append(
            dict(
                order=n,
                key=k,
                title=title,
                how=how,
                why=why,
                owner=i["owner"],
                minutes=i["minutes"],
                action=i["how"],
                status="todo",
                weight=i["weight"],
            )
        )
    for ch in d.get("checks", [])[
        :3
    ]:  # rule-specific checks from the evidence (what would clear or confirm the finding)
        key = f"check_{ch['rule']}"
        st = steps.get(key)
        if st and st["status"] in ("done", "skipped"):
            continue
        n += 1
        out.append(
            dict(
                order=n,
                key=key,
                title=f"Check: {ch['rule_name']}",
                how=ch["check"],
                why=ch.get("resolves", ""),
                owner="investigator",
                minutes=ch["minutes"],
                action="mark",
                status="todo",
                weight=0,
                benign=ch.get("benign", []),
            )
        )
    n += 1
    out.append(
        dict(
            order=n,
            key="decision",
            title="Decide",
            how="Record a decision with a written rationale on the Decision tab. Referral needs supervisor approval (four-eyes).",
            why="Humans decide; SpotZⁱ never refers, holds payment or contacts a provider.",
            owner="investigator",
            minutes=10,
            action="link",
            status="todo",
            weight=0,
        )
    )
    done = [
        dict(
            key=k,
            title=HOWTO.get(k, (k,))[0] if k in HOWTO else k.replace("check_", "Check: "),
            status=v["status"],
            note=v["note"],
            user=v["user_name"],
            ts=v["ts"],
        )
        for k, v in steps.items()
        if v["status"] in ("done", "skipped")
    ]
    return dict(next=out[0] if out else None, steps=out, completed=done, total_minutes=sum(s["minutes"] for s in out))
