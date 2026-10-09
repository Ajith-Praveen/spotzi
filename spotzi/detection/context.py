"""Legitimate-context reasoning: does an OBSERVABLE business event explain an anomaly?

Payers hold provider events outside claims — enrolment updates (new service locations), credentialing rosters
(clinicians joining), contract registries (nursing-facility coverage), ownership disclosures (acquisitions).
A legitimate event can explain changes in VOLUME, PATIENT PANEL and SERVICE MIX that start after it. It never explains
billing-integrity findings (duplicates, services after death or during stays, impossible timing, unbundling, unit
limits, exclusions, analyst rules) — those stay suspicious whatever the business context.

Output per case: which signals are explained, by which event, and whether the case is fully or partly explained.
The system never closes a case because of context; it routes it to "Explained by context" or "Validate context first"
and a human decides."""

from __future__ import annotations

import pandas as pd

# event type → (rules it can explain, learned detectors it can explain, plain-English reason)
EXPLAINS = {
    "location_opened": (
        set(),
        {"drift", "panel", "iforest", "twin", "mix"},
        "new service locations bring more patients and visits",
    ),
    "clinician_joined": (
        {"UPCODE"},
        {"drift", "mix", "iforest", "twin", "path"},
        "a new clinician changes the case mix and visit complexity",
    ),
    "contract_started": (
        {"EXCESS", "REPEAT"},
        {"drift", "panel", "mix", "iforest", "path", "twin"},
        "a facility contract brings a cohort of frail patients needing frequent visits",
    ),
    "acquisition": (set(), {"drift", "panel", "iforest", "twin"}, "an acquired practice's existing patients move over"),
}
NEVER = {"DUP", "PHANTOM", "TIMING", "UNBUNDLE", "MUE", "EXCLUDED", "CUSTOM"}
# per-patient intensity changes an event CAN explain (anything else stays unexplained, e.g. a "new clinic" does not explain
# each patient suddenly costing three times more)
INTENSITY = {
    "location_opened": set(),
    "acquisition": set(),
    "clinician_joined": {"hi_em_share", "paid_per_line", "paid_per_member", "codes_per_member", "lines_per_member"},
    "contract_started": {"lines_per_member", "paid_per_member"},
}
LEARNED = {
    "drift": "drift_pct",
    "panel": "panel_pct",
    "mix": "mix_pct",
    "iforest": "anomaly_pct",
    "twin": "twin_pct",
    "path": "path_pct",
}


def load(T) -> pd.DataFrame:
    e = T.get("provider_events")
    if e is None or not len(e):
        return pd.DataFrame(columns=["event_id", "provider_id", "event_date", "event_type", "detail", "source"])
    e = e.copy()
    e["event_date"] = pd.to_datetime(e.event_date)
    return e


def events_for(E, pid, end, lookback_days=420):
    if E is None or not len(E):
        return []
    x = E[(E.provider_id == pid) & (E.event_date <= end) & (E.event_date >= end - pd.Timedelta(days=lookback_days))]
    return [
        dict(event_id=r.event_id, date=str(r.event_date.date()), type=r.event_type, detail=r.detail, source=r.source)
        for r in x.itertuples()
    ]


def assess(pid, PT, rule_onsets: dict, events: list, cp_onset=None, intensity=()) -> dict:
    """rule_onsets: {rule: first flag date}. Learned detectors count as 'firing' at >= .85 percentile."""
    firing_rules = {k for k in rule_onsets}
    firing_learned = {
        k for k, col in LEARNED.items() if col in PT and PT.at[pid, col] == PT.at[pid, col] and PT.at[pid, col] >= 0.85
    }
    if not events or not (firing_rules or firing_learned):
        return dict(
            events=events,
            explained=[],
            unexplained=sorted(firing_rules) + sorted(firing_learned),
            status="none" if not events else "not relevant",
        )
    explained, why = set(), []
    for ev in events:
        rules_ok, learned_ok, reason = EXPLAINS.get(ev["type"], (set(), set(), ""))
        d = pd.Timestamp(ev["date"])
        r_hit = {
            k for k in firing_rules & rules_ok if pd.Timestamp(rule_onsets[k]) >= d - pd.Timedelta(days=30)
        }  # behaviour began after the event
        cp_ok = cp_onset is None or pd.Period(cp_onset).to_timestamp() >= d - pd.Timedelta(days=45)
        l_hit = (firing_learned & learned_ok) if cp_ok else set()
        if r_hit or l_hit:
            explained |= r_hit | l_hit
            why.append(dict(event=ev, explains=sorted(r_hit | l_hit), reason=reason))
    ok_int = set().union(*[INTENSITY.get(ev["type"], set()) for ev in events]) if events else set()
    unexplained = sorted((firing_rules | firing_learned) - explained) + [
        f"intensity:{m}" for m in intensity if m not in ok_int
    ]
    blocking = sorted(set(unexplained) & (NEVER | firing_rules))
    status = "full" if explained and not unexplained else "partial" if explained else "none"
    return dict(
        events=events, explained=sorted(explained), unexplained=unexplained, blocking=blocking, why=why, status=status
    )
