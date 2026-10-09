"""Synthetic medical-record system. SIUs confirm upcoding / timing / phantom-service patterns by requesting charts for a
sample of claim lines and comparing documentation with what was billed. SpotZⁱ has no real records, so this module
plays the provider's record system: a deterministic synthetic note per line (seeded by line_id).

The note reflects what actually happened in the synthetic world: for lines labelled as a scheme (hidden truth) the
documentation supports less than was billed (or is missing); otherwise it supports the billed service. Detection
code never reads the truth directly — it only sees note text, exactly like an investigator reading a chart.

All content is synthetic. No real patient, provider or clinical text is used."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

EM_OFFICE = {"99211": 1, "99212": 2, "99213": 3, "99214": 4, "99215": 5}
EM_ED = {"99281": 1, "99282": 2, "99283": 3, "99284": 4, "99285": 5}
PSYCHO = {"90832": 30, "90834": 45, "90837": 60}
# 2021 AMA office E/M total-time bands (minutes) and psychotherapy minimums
TIME_BAND = {2: (10, 19), 3: (20, 29), 4: (30, 39), 5: (40, 60)}
PSYCHO_MIN = {"90832": 16, "90834": 38, "90837": 53}

PROBLEMS = {
    1: ["minor rash, self-limited", "insect bite, no complications", "request for work note, no active complaint"],
    2: [
        "acute uncomplicated upper respiratory infection",
        "single stable chronic condition (hypertension), at goal",
        "mild seasonal allergies",
    ],
    3: [
        "two stable chronic illnesses (type 2 diabetes, hyperlipidaemia)",
        "acute illness with systemic symptoms (influenza-like illness)",
        "chronic hypertension with mild exacerbation",
    ],
    4: [
        "chronic heart failure with progression; new lower-extremity oedema",
        "two chronic illnesses, one with exacerbation (COPD flare, diabetes)",
        "undiagnosed new problem with uncertain prognosis (weight loss, night sweats)",
    ],
    5: [
        "chronic kidney disease with severe exacerbation and rising potassium",
        "acute illness posing a threat to bodily function (chest pain with ECG changes)",
        "COPD with severe exacerbation, hypoxic at rest",
    ],
}
DATA = {
    1: ["No tests reviewed.", "No external records."],
    2: ["Reviewed last CBC.", "No new tests ordered."],
    3: ["Ordered HbA1c and lipid panel; reviewed prior metabolic panel.", "Reviewed results of 2 prior tests."],
    4: [
        "Independent interpretation of today's ECG; reviewed external hospital notes; ordered BMP, BNP and chest X-ray.",
        "Discussed management with the treating cardiologist.",
    ],
    5: [
        "Independent interpretation of chest imaging; discussed with nephrology; reviewed external ED records and 4 unique test results.",
        "Ordered troponin series, BMP, ABG.",
    ],
}
RISK = {
    1: ["Reassurance; over-the-counter emollient.", "Rest and fluids."],
    2: ["Over-the-counter analgesia; return precautions.", "Continue current medication unchanged."],
    3: ["Prescription drug management: metformin dose adjusted.", "Started prescription antiviral."],
    4: [
        "Prescription drug management: diuretic increased, potassium monitoring.",
        "Considered but deferred escalation of inhaled therapy; social determinants limit adherence.",
    ],
    5: [
        "Decision regarding hospitalization: direct admission arranged.",
        "Parenteral medication considered; patient sent to ED for escalation of care.",
    ],
}
# Second wording style (different clinicians write differently). The deterministic reviewer's keywords were written
# against style A only, so style B measures how each reviewer copes with unfamiliar phrasing.
PROBLEMS_B = {
    1: ["small scrape on the forearm, healing", "came in for a sick note only"],
    2: ["sore throat for two days, afebrile", "blood pressure check, readings fine on current dose"],
    3: ["sugars and cholesterol both steady on current regimen", "flu-like illness with fever and body aches"],
    4: [
        "heart failure getting worse — ankles more swollen this month",
        "emphysema flaring while diabetes also needs attention",
    ],
    5: ["kidney failure with dangerously high potassium today", "crushing chest pain, ECG looks ischaemic"],
}
DATA_B = {
    1: ["Nothing to review."],
    2: ["Looked at last month's blood count."],
    3: ["Sent off an A1c and lipids; went over last metabolic results."],
    4: [
        "I read today's ECG myself and went through the hospital discharge summary; bloods and a chest film requested."
    ],
    5: [
        "Personally read the chest CT; spoke with the kidney team; pulled outside ER records and four separate results."
    ],
}
RISK_B = {
    1: ["Nothing prescribed, just reassurance."],
    2: ["Paracetamol as needed."],
    3: ["Bumped up the metformin."],
    4: ["Upped the water tablet and arranged potassium checks."],
    5: ["Arranged admission to the ward today."],
}
DISTRACT = [
    "Review of systems: 14-point review otherwise negative.",
    "Patient talkative; discussed upcoming family travel at length.",
    "Comprehensive past medical, family and social history reviewed and unchanged.",
    "Vitals stable. Patient pleasant and cooperative.",
]


def _rng(line_id: str):
    return np.random.default_rng(int(hashlib.sha1(str(line_id).encode()).hexdigest()[:12], 16))


def _pick(rng, xs):
    return xs[int(rng.integers(len(xs)))]


def note(line: dict, truth_scenario: str = "", style: str = "A") -> dict:
    """Return {"line_id", "available", "text"} for one claim line (dict with line_id, code, service_date, duration_min...)."""
    lid, code = str(line["line_id"]), str(line.get("code", ""))
    rng = _rng(lid)
    date = str(line.get("service_date", ""))[:10]
    scheme = (truth_scenario or "").lower()
    phantom = any(k in scheme for k in ("phantom", "dme-hh", "deceased"))
    if phantom and rng.random() < 0.85:
        return dict(
            line_id=lid,
            available=False,
            text=f"Records request for {date}, service {code}: provider returned no encounter documentation for this date. "
            f"{_pick(rng, ['Appointment log shows no visit.', 'Sign-in sheet for the date does not list the patient.', 'Delivery ticket not signed by the member.'])}",
        )
    if code in EM_OFFICE or code in EM_ED:
        billed = EM_OFFICE.get(code) or EM_ED.get(code)
        upc = ("upcod" in scheme or "upcode" in scheme or ("lab-ring" in scheme and billed == 5)) and billed >= 4
        level = int(max(2, billed - int(rng.integers(1, 3)))) if upc else billed
        level = min(level, 5)
        lo, hi = TIME_BAND.get(level, (10, 19))
        minutes = int(line.get("duration_min") or 0) or int(rng.integers(lo, hi + 1))
        if upc:
            minutes = min(minutes, TIME_BAND[level][1])
        PB, DB, RB = (PROBLEMS_B, DATA_B, RISK_B) if style == "B" else (PROBLEMS, DATA, RISK)
        parts = [
            f"Office visit {date}." if code in EM_OFFICE else f"Emergency department visit {date}.",
            f"Assessment: {_pick(rng, PB[level])}.",
            _pick(rng, DB[level]),
            f"Plan: {_pick(rng, RB[level])}",
        ]
        if rng.random() < 0.6:
            parts.append(
                f"Total time on the date of the encounter: {minutes} minutes."
                if style != "B"
                else f"Spent {minutes} min with the patient and on the chart today."
            )
        for _ in range(int(rng.integers(1, 3))):
            parts.insert(int(rng.integers(1, len(parts) + 1)), _pick(rng, DISTRACT))
        return dict(
            line_id=lid, available=True, text=" ".join(parts), level=level
        )  # level: ground truth for training only
    if code in PSYCHO:
        dur = int(line.get("duration_min") or 0)
        short = "timing" in scheme or "bh" in scheme
        minutes = (
            dur
            if dur
            else (int(rng.integers(26, 46)) if short else int(rng.integers(PSYCHO_MIN[code], PSYCHO[code] + 8)))
        )
        if short:
            minutes = min(minutes, PSYCHO_MIN[code] - 3)
        txt = (
            f"Psychotherapy session {date}. Session start and stop documented; psychotherapy time {minutes} minutes. "
            if style != "B"
            else f"Therapy {date}, started {9 + minutes // 120}:00 and finished {9 + minutes // 120}:{minutes % 60:02d}. "
            if minutes < 60
            else f"Therapy {date}, ran the full hour ({minutes} min). "
        ) + (
            f"Focus: {_pick(rng, ['CBT for generalised anxiety', 'grief processing', 'behavioural activation for depression'])}. "
            f"{_pick(rng, ['Patient engaged.', 'Homework reviewed.', 'Safety screen negative.'])}"
        )
        return dict(line_id=lid, available=True, text=txt)
    return dict(
        line_id=lid,
        available=True,
        text=f"Service record {date}: {code} performed as ordered; order and result on file. {_pick(rng, DISTRACT)}",
    )


def sample_lines(L, providers, n=8, seed=0, flagged_first=True):
    """Pick the chart-review sample: reviewable lines (E/M, psychotherapy, or any flagged line) for the given providers."""
    W = L[L.provider_id.isin(providers)]
    reviewable = W.code.isin(list(EM_OFFICE) + list(EM_ED) + list(PSYCHO)) | (W.any_flag if "any_flag" in W else False)
    W = W[reviewable]
    if flagged_first and "any_flag" in W and W.any_flag.sum() >= n // 2:
        f = W[W.any_flag]
        o = W[~W.any_flag]
        k = min(len(f), n - min(len(o), n // 4))
        return pd.concat([f.sample(k, random_state=seed), o.sample(min(len(o), n - k), random_state=seed)])
    return W.sample(min(len(W), n), random_state=seed)
