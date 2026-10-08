# 01 — Product idea and scope

## The product in one sentence

SpotZ^i is a workspace where an SIU investigator can understand **what looks suspicious, which entities connect the activity, what evidence supports it, how it may develop, and whether it deserves scarce investigation time**.

An alerting model alone does not solve the problem. Ten duplicate alerts, twenty unusual laboratory claims, and three referral signals may describe one investigation. The product must preserve the evidence while reducing repeated work.

**Mandatory boundaries:** every input record is synthetic, and all final decisions belong to humans. Automatic candidate creation and scoring produce recommendations only. A person accepts the investigation scope, a manager approves assignments, and an authorized reviewer approves the outcome and final brief. The detailed mechanism is specified in [document 20](20-human-review-and-decision-mechanism.md).

## The signature demonstration

A synthetic ordering practice sends an unusually concentrated set of referrals to two laboratories and a DME supplier. The businesses share a simulated ownership indicator. Some member journeys contain repeated tests and apparently incompatible appointments. None of the shared relationships alone establishes wrongdoing.

Nexus identifies billing signals, compares behavior with appropriate peers, highlights the observed connections, groups the evidence into a reviewable case, and forecasts further qualifying suspicious activity over 30, 60, and 90 days. An investigator inspects an exception, dismisses one misleading alert, and retains the supported case. The dashboard recomputes the case evidence and exposure without changing historical snapshots.

Include a second, legitimate network with shared premises and high referral volume. This demonstrates restraint and shows why graph connectivity alone cannot be a fraud detector.

## Users and jobs

| User | Main job | Necessary controls |
|---|---|---|
| SIU investigator | Review facts and decide next steps | Evidence drill-down, notes, disposition, case history |
| SIU manager | Allocate limited investigation hours | Ranked queue, skills, capacity, assignments, override reasons |
| Payment integrity analyst | Tune patterns and reduce noise | Rule versions, cohort comparisons, exceptions, dry runs |
| Data/ML analyst | Validate data and model quality | Dataset manifests, feature lineage, evaluation reports |
| Auditor/read-only reviewer | Reconstruct a decision | Immutable snapshots, access history, export provenance |

For a prototype, role switching can use seeded local accounts. A shared public deployment requires real authentication and server-side permission enforcement.

## Scope and release levels

**First runnable slice:** synthetic ingestion, canonical claim versions, duplicate and utilization rules, provider anomaly scores, one relationship graph, one ranked queue, structured briefs, and human dispositions. This slice proves the data-to-case plumbing but does not yet complete every problem requirement.

**Complete evaluated prototype:** add all six named suspicious-behavior categories with appropriate limitations, repeat/escalation forecasts, capacity planning, benign controls, graph case grouping, delayed outcomes, and evaluation. This is the recommended submission scope.

**Later product:** payer-specific policies, reviewed real-world integrations, advanced identity resolution, enterprise authentication, larger graph infrastructure, mature recovery tracking, and formal external validation. These are separate projects.

## Requirement traceability

| Problem requirement | Concrete delivery | Proof in demo |
|---|---|---|
| Synthetic claims and related data | Manifest-driven CSV/Parquet import and generator | Load a dataset and inspect accepted/rejected rows |
| Duplicate, upcoding, unbundling, phantom, utilization, timing | Versioned rule catalog plus contextual indicators | Open each scenario and a matching benign exception |
| Two complementary approaches | Rules + Isolation Forest; graph and forecasting add depth | Show independent outputs before case fusion |
| Relationships | Typed graph with dated edges and evidence | Expand provider → referral → facility/member/ownership |
| Future 30/60/90-day risk | Discrete-time event model, horizon selector | Explain target, eligibility, and unavailable forecasts |
| Prioritized SIU queue | De-duplicated case ranking and hour budget | Change capacity and inspect selection reasons |
| Explainable investigation brief | Deterministic report from evidence records | Follow a report citation back to a source claim |
| Human control | Assign, request review, dismiss, substantiate, reopen | Record reason and preserve audit trail |

## Service-family coverage

Professional, laboratory, and DME receive the richest initial scenarios. Facility, pharmacy, ambulance, behavioral health, and home health still have typed records and appropriate baseline checks. Each screen states which detectors support its service family. A hospital stay is not judged using an office-visit duration rule; a pharmacy reversal is not counted as a second paid fill.

## Success measures

Measure distinct supported cases surfaced within a fixed hour budget, precision at review capacity, scenario recall, distinct potentially implicated dollars, time to find supporting evidence, and false alerts on benign controls. Report denominators, seed counts, and uncertainty. Alert reduction is useful only if meaningful cases are retained.

Example target, not a claimed result: a manager can move from thousands of claim signals to tens of coherent candidate cases and understand the top case in a few minutes. Actual counts must come from the pipeline.

## Product boundaries

This prototype supports investigation prioritization. It does not determine criminal intent, adjudicate medical necessity, deny claims, suspend payment, contact members, or send external referrals. Claims can support suspicions of phantom services or upcoding, but source records and human review are needed to resolve them. The UI uses “indicator,” “potential exposure,” and “review recommended,” with specific missing evidence.

No universal numerical threshold is presented as a clinical, legal, or payer policy standard. All thresholds are editable demo assumptions and must be versioned.
