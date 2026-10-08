"""SpotZ^i Evidence Challenge Lab: competing explanations, expected-information-gain check ranking,
scenario branches, evidence fragility and a synthetic evidence vault (doc 21).

Hidden scenario truth is used ONLY to decide what a revealed synthetic artifact says (the vault), never for ranking."""
from __future__ import annotations

import hashlib
import math

import numpy as np

STATES = ["unsupported", "legitimate", "data_gap"]
STATE_LABEL = {"unsupported": "Unsupported / suspicious billing", "legitimate": "Legitimate explanation", "data_gap": "Data gap or measurement problem"}

# P(outcome | state) — expert priors (columns sum to 1). Replace with measured tables once a real evidence vault exists.
# outcome: (label, [unsupported, legitimate, data_gap])
CATALOG = {
    "PHANTOM": dict(name="Verify delivery / visit records and stay dates", minutes=25, outcomes=[
        ("No record that the service was delivered", [.78, .04, .20]), ("Valid delivery or visit record exists", [.04, .74, .10]),
        ("Stay or eligibility dates were wrong", [.03, .15, .25]), ("Records unavailable", [.15, .07, .45])]),
    "TIMING": dict(name="Obtain clinician schedules and sign-in sheets", minutes=30, outcomes=[
        ("One clinician cannot cover the billed hours", [.75, .05, .15]), ("Several rendering clinicians documented", [.05, .80, .15]), ("Records unavailable", [.20, .15, .70])]),
    "UNBUNDLE": dict(name="Reconcile accession / specimen records", minutes=12, outcomes=[
        ("Same specimen billed as panel and components", [.80, .03, .15]), ("Distinct specimens documented", [.05, .85, .15]), ("Records unavailable", [.15, .12, .70])]),
    "REPEAT": dict(name="Request clinical indication or specimen record for repeats", minutes=15, outcomes=[
        ("No indication or distinct specimen", [.75, .05, .20]), ("Documented indication (e.g. monitoring)", [.08, .80, .15]), ("Records unavailable", [.17, .15, .65])]),
    "UPCODE": dict(name="Chart sample against level-of-service documentation", minutes=40, outcomes=[
        ("Documentation supports a lower level", [.78, .07, .20]), ("Documentation / patient acuity supports billed level", [.07, .78, .15]), ("Charts incomplete", [.15, .15, .65])]),
    "DUP": dict(name="Check submission lineage and reversals", minutes=10, outcomes=[
        ("Same submission, no adjustment lineage", [.78, .04, .15]), ("Replacement or reversal reconciled", [.05, .80, .20]), ("Records unavailable", [.17, .16, .65])]),
    "EXCESS": dict(name="Review treatment plan and medical necessity", minutes=25, outcomes=[
        ("No treatment plan supporting frequency", [.70, .05, .20]), ("Intensive program documented", [.10, .82, .15]), ("Records unavailable", [.20, .13, .65])]),
    "DRIFT": dict(name="Sample onset-month encounters and verify member acquisition", minutes=35, outcomes=[
        ("Members recruited or paid to attend; encounters templated", [.70, .04, .15]), ("Documented expansion / new programme", [.08, .80, .15]), ("Records unavailable", [.22, .16, .70])]),
    "GRAPH": dict(name="Verify ownership / relationship between linked providers", minutes=20, outcomes=[
        ("Undisclosed common control confirmed", [.55, .10, .20]), ("Routine relationship (e.g. chain, shared landlord)", [.15, .70, .30]), ("Cannot verify", [.30, .20, .50])]),
}
FAVOURS_LEGIT = .5


def _entropy(p):
    return -sum(x * math.log2(x) for x in p if x > 1e-12)


def _norm(p):
    s = sum(p); return [x / s for x in p]


def prior_from(hyps):
    sup = {h["kind"]: h["support"] for h in hyps}
    p = [max(5, sup.get("Suspicious", 50)), max(5, sup.get("Legitimate", 30)), max(5, sup.get("Uncertain", 20))]
    return _norm(p)


def posterior(prior, observed, case_checks):
    p = list(prior)
    for rule, label in observed:
        spec = case_checks.get(rule)
        if not spec: continue
        for o, lik in spec["outcomes"]:
            if o == label:
                p = _norm([p[i] * lik[i] for i in range(3)]); break
    return p


def available_checks(d):
    """checks relevant to this case: one per fired rule (+ graph check for networks)."""
    out = {}
    for c in d["checks"]:
        if c["rule"] in CATALOG: out[c["rule"]] = {**CATALOG[c["rule"]], "rule": c["rule"], "rule_name": c["rule_name"], "paid": c.get("paid", 0)}
    if len(d["providers"]) > 1: out["GRAPH"] = {**CATALOG["GRAPH"], "rule": "GRAPH", "rule_name": "Network relationship", "paid": 0}
    return out


def eig(post, spec):
    h0 = _entropy(post); exp_h = 0.0; per = []
    for o, lik in spec["outcomes"]:
        po = sum(post[i] * lik[i] for i in range(3))
        pp = _norm([post[i] * lik[i] for i in range(3)])
        exp_h += po * _entropy(pp); per.append((o, po, pp))
    return h0 - exp_h, per


def analyse(d, events, case_exposure):
    """events: list of dict(rule, outcome) already revealed (persisted)."""
    checks = available_checks(d)
    prior = prior_from(d["hypotheses"])
    obs = [(e["rule"], e["outcome"]) for e in events]
    post = posterior(prior, obs, checks)
    done = {e["rule"] for e in events}
    ranking, branches = [], []
    for rule, spec in checks.items():
        if rule in done: continue
        g, per = eig(post, spec)
        can_clear = any(pp[1] >= .6 for _, po, pp in per if po > .02)
        can_confirm = any(pp[0] >= .75 for _, po, pp in per if po > .02)
        ranking.append(dict(rule=rule, name=spec["name"], minutes=spec["minutes"], eig_bits=g, bits_per_hour=g / spec["minutes"] * 60,
                            can_clear=can_clear, can_confirm=can_confirm, rule_name=spec["rule_name"], paid=spec["paid"]))
    ranking.sort(key=lambda r: -r["bits_per_hour"])
    for r in ranking[:3]:
        spec = checks[r["rule"]]; _, per = eig(post, spec)
        branches.append(dict(rule=r["rule"], name=r["name"], outcomes=[dict(outcome=o, probability=po, posterior=dict(zip(STATES, pp)),
                              exposure_if=max(0, case_exposure - r["paid"]) if pp[1] >= FAVOURS_LEGIT else case_exposure,
                              reading=("favours a legitimate explanation: related exposure may narrow" if pp[1] >= FAVOURS_LEGIT else "strengthens the unsupported-billing concern" if pp[0] >= .75 else "leaves the question open"))
                              for o, po, pp in per if po > .005]))
    return dict(states=[dict(key=k, label=STATE_LABEL[k], prior=prior[i], posterior=post[i]) for i, k in enumerate(STATES)],
                entropy_bits=_entropy(post), entropy_prior_bits=_entropy(prior), ranking=ranking, branches=branches, observed=events,
                method="Expected information gain per review hour over three mutually exclusive case-level explanations; checks assumed conditionally independent given the explanation; likelihoods are expert priors.",
                caveat="Case-level simplification: real cases mix explanations across lines. Probabilities describe this model's belief after the evidence shown, not truth.")


def fragility(c, d):
    """Robustness of the concern under configured assumption removals (not a probability)."""
    sig = dict(c["signal_flags"]); rules = list(c["rules"]); n = c["rule_counts"]
    def supported(s, rs):
        fam = sum(bool(v) for v in s.values())
        strong = any(n.get(r, 0) >= 20 for r in rs)
        return (fam >= 2 and bool(rs)) or (strong and fam >= 1)
    tests = [("Baseline (all evidence)", sig, rules)]
    if sig.get("graph"): tests.append(("Ignore the relationship / ownership links", {**sig, "graph": False}, rules))
    if sig.get("anomaly"): tests.append(("Ignore the anomaly model", {**sig, "anomaly": False}, rules))
    if sig.get("temporal"): tests.append(("Ignore the escalation trend", {**sig, "temporal": False}, rules))
    for r in rules[:3]: tests.append((f"Drop the {r} finding", sig, [x for x in rules if x != r]))
    if len(rules) > 1: tests.append(("Keep only the single strongest finding", sig, rules[:1]))
    res = [dict(test=t, supported=supported(s, rs), signals=sum(bool(v) for v in s.values()), rules=len(rs)) for t, s, rs in tests]
    return dict(supported=sum(r["supported"] for r in res), total=len(res), tests=res,
                note="Robustness over the listed checks only. Verified facts cannot be removed to manufacture an exoneration.")


def vault_outcome(case_id, rule, d, truth_share, seed="spotzi"):
    """Deterministic synthetic artifact. truth_share = fraction of the rule's flagged lines that are seeded-bad (evaluation-only)."""
    checks = available_checks(d); spec = checks[rule]
    if truth_share is None: raise ValueError("no vault")
    if rule == "GRAPH": state = 0 if truth_share >= .5 else 1
    else: state = 0 if truth_share >= .5 else 1
    rng = np.random.default_rng(int(hashlib.sha1(f"{seed}{case_id}{rule}".encode()).hexdigest()[:8], 16))
    probs = [lik[state] for _, lik in spec["outcomes"]]
    i = int(rng.choice(len(probs), p=_norm(probs)))
    return spec["outcomes"][i][0]
