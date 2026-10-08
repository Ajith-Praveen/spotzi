# 02 — User journeys and UI

## Navigation and layout

Use six main areas: **Overview, Data, SIU Queue, Network Explorer, Analysis Runs, Governance**. A case opens in a dedicated workspace, not a modal that hides the evidence. Show a persistent “Synthetic demonstration” banner, dataset version, and analysis as-of time.

Deliver this workspace as a responsive internal web application and installable PWA. Desktop is the primary investigation surface; compact layouts support triage on managed tablets. Offline mode exposes only the cached shell with a clear read-only banner. Evidence reveals and human decisions require a current server connection.

Use a restrained payer-operations visual style: neutral surfaces, readable tables, consistent service-family colors, risk badges with text, and clear whitespace. Red means attention required, not proven fraud. Every chart needs a textual summary or accessible table equivalent.

## Journey A — Load and analyze

1. Analyst chooses **Load demo dataset** or uploads a synthetic-only CSV/Parquet bundle.
2. System checks the manifest, schemas, relationships, currency, dates, claim versions, and declared provenance.
3. Validation screen shows input rows, accepted rows, quarantined rows, reasons, affected detectors, and coverage by family.
4. Analyst confirms a validated dataset and chooses an as-of timestamp. Advanced controls select rule/model versions; ordinary users get the current approved bundle.
5. Analysis runs asynchronously: canonicalization → features → rules/anomalies/graph → forecasts → cases → queue.
6. Run status shows each stage, row counts, elapsed time, warnings, and retry availability. It never shows a fabricated percentage.
7. Completed run opens the queue and summary. A partial run is labeled partial and names disabled capabilities.

Missing service times disable timing checks for those rows; they do not fail otherwise usable claims. Missing core identifiers quarantine rows. A dataset with no usable claims cannot be promoted.

## Journey B — Review a case

The queue contains case ID, primary entity, category, current-risk index, potential paid exposure, distinct members, severity, evidence quality, forecast status, estimated hours, age, assignee, and priority explanation.

Filters include family, status, severity, risk band, dollar range, rule, forecast availability, and investigation team. Sorting is server-side and stable. Save filters by user. Keep counts scoped to the same dataset and run as the table.

Clicking a case opens:

| Region | Contents |
|---|---|
| Header | Case ID, status, run, primary entities, assignment |
| Summary | Observed concern, distinct exposure, uncertainty, suggested review |
| Evidence tab | Findings table, fields, source rows, rule versions, exceptions |
| Claims tab | Included lines, replacements/reversals, dates, amounts |
| Timeline tab | Service events, received dates, flags, prior known outcomes |
| Network tab | Focused, typed, dated relationships with confidence |
| Forecast tab | 30/60/90-day probabilities, target and eligibility |
| Brief tab | Rendered Markdown, citations, limitations, export |
| Activity tab | Assignments, notes, changes, human decisions |
| Precedents tab | Similar reviewed cases, material differences, prior reasoning, reusable review blueprint |

An investigator can mark a finding “explained,” “needs corroboration,” or “supported.” This changes the current case assessment through a new version; it does not delete the original finding.

In the Precedents tab, show current-case facts before historical outcomes. The investigator compares the closest quality-approved cases, acknowledges material differences, and may generate an editable review checklist. Prior outcomes never prefill the current disposition.

## Journey C — Plan capacity

Manager sets available team hours for a named planning period and optional skill constraints. The system recommends a set of cases, shows used/remaining hours, exposes ranking components, and lists cases deferred by capacity.

Changing capacity is a preview until the manager selects **Apply assignments**. Preview has no assignment side effects. If a case changed since preview, applying returns a conflict and requests refresh. Urgent member-safety concerns appear in a dedicated review lane even when the ordinary queue is full; they still require human action.

## Journey D — Understand forecasts

The investigator selects 30, 60, or 90 days. Show: “Estimated probability of a new qualifying repeat event by day 60, given information available at [time].” A separate card reports escalation. Both identify synthetic-only validation.

Do not label a 0–100 prioritization index as a probability. Do not silently substitute an anomaly score when forecasting is unavailable. Explain whether the entity lacks prior qualifying history, sufficient observation time, supported service mix, or an approved model.

A probability is not itself a confidence interval. Display model validity, data completeness, cohort support, and uncertainty separately. If interval estimates have not been implemented and evaluated, omit them rather than inventing ± values.

## Uncertain, empty, and failed states

| State | Visible response | Next action |
|---|---|---|
| No alerts | “No enabled detector produced an alert in this run” with coverage | Inspect coverage or select another window |
| Missing timestamp | Timing evaluation unsupported for listed lines | Supply synthetic timestamp fixture or review records |
| Small peer cohort | Broader cohort used; comparator label changes | Inspect broader group or defer anomaly finding |
| Ambiguous ownership | Dashed relationship, source and confidence shown | Verify relationship before relying on it |
| Model failed | Forecast unavailable; successful rules remain inspectable | Retry failed stage; no automatic score substitution |
| Brief wording service failed | Deterministic template rendered | Continue investigation |
| Stale run | Prior result remains dated and read-only | Start a new run |
| Export denied | Role-specific explanation | Request access through normal team process |

## Important interaction details

- Evidence links highlight the exact source fields that supported a finding.
- Graph filters show when nodes/edges are truncated; “no visible connection” never means no underlying relationship.
- Notes and dispositions require a reason. Substantiation also requires references and an authorized role.
- Exports include synthetic label, run ID, timestamps, versions, and unresolved limitations.
- Member views use fictional IDs and minimal clinical detail. Names are unnecessary.
- Date filters distinguish date of service from receipt/payment dates.
- “Potential dollars” has an explanatory tooltip and an included-line breakdown.
- Keyboard navigation works through queue rows, case tabs, and evidence; graph-only information is also available as a relationship table.

## Definition of a complete experience

A new user can load the demo, understand a validation warning, run analysis, review a ranked case, inspect a source citation and graph edge, explain a forecast, change capacity, record a reasoned disposition, and reopen the same historical evidence after a later run.
