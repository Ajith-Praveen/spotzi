# 13 — Evidence and explainable investigation briefs

## Evidence is a first-class output

Persist facts before rendering narrative. Each important sentence in a brief references an evidence item or is explicitly a hypothesis, limitation, or proposed next step. Source links resolve within the frozen run, not whichever dataset is current later.

```json
{
  "evidence_id": "EV-SYN-101",
  "run_id": "RUN-SYN-001",
  "finding_id": "FIND-SYN-014",
  "kind": "duplicate_service_pattern",
  "subject": {"type": "provider", "id": "SYN-PROV-0042"},
  "source_refs": [
    {"file": "claim_lines.csv", "row_id": "ROW-101", "fields": ["service_from", "procedure_code", "units"]}
  ],
  "observed": {"equivalent_active_paid_lines": 3},
  "comparator": {"retained_service_assumption": 1},
  "rule_version": "R01-1.0",
  "as_of": "2025-08-31T23:59:59Z",
  "limitations": ["Distinct-encounter documentation requires human review"],
  "status": "requires_human_review"
}
```

This abbreviated example is illustrative. A real emitted item must cite all three source lines, transaction lineage, payment events, and relevant exception fields, not just the first source row shown above.

## Brief schema

1. Case and snapshot identity, synthetic label, authorship mode, generation timestamp.
2. One-paragraph reason for review, carefully separating observation and inference.
3. Scope: entities, dates, claim lines, members, service families.
4. Dollars: gross implicated paid exposure, potential excess where estimable, exclusions.
5. Findings: observed values, comparators, source links, rules/model versions.
6. Timeline: service, receipt, known relationship, and review events.
7. Network: supported paths, relationship confidence, uninvolved/uncertain neighbors.
8. Forecasts: entity, target, cutoff, horizon, eligibility, synthetic validation domain.
9. Confidence and limitations: data coverage, support, alternatives, unresolved contradictions.
10. Recommended human-review tasks, decision owner, and approvals required.
11. Human decision section, initially blank, with reason and citations required on completion.

## Deterministic generation first

Build a typed `BriefInput` from the case snapshot and evidence store. Validate values, aggregate distinct money/people correctly, sort timeline events, and render a Jinja Markdown template. This is sufficient for a strong demo and works offline.

An optional language model can rewrite validated narrative sections for readability. It cannot choose risk scores, invent facts, modify money, assign cases, decide outcomes, or contact anyone. Send only minimized synthetic facts. Do not include arbitrary instructions from notes, CSV fields, or source documents as trusted prompts.

Require structured output with evidence IDs. After rewriting, verify every referenced ID exists, every emitted numeric claim matches an allowed fact, and mandatory limitations remain. A failed check discards the rewrite and uses the deterministic template. Merely asking a model to “be accurate” is not a sufficient safeguard.

## Illustrative brief

> **Synthetic example; the values below are invented to specify presentation, not actual analysis results.**

### Case SYN-CASE-0042 — concentrated laboratory and DME activity

**Review recommendation:** Examine repeated services and referral concentration involving three fictional providers. Available claims suggest potentially overlapping billings; the relationship context warrants a joint review. The evidence does not establish intent or prove the services were unperformed.

**Scope:** 42 distinct implicated paid lines, 28 distinct synthetic members, a 90-day observation window ending 31 August 2025. Gross implicated paid exposure: **$12,480**. No recovery is established.

| Evidence | Observation | Dollars and interpretation |
|---|---|---|
| EV-SYN-101 | Three equivalent paid service lines at $300 each | $900 gross implicated; $600 potential excess if one service is retained |
| EV-SYN-102 | Nine lines contain a synthetic bundle-pair indicator | $2,580 gross implicated; excess cannot yet be estimated |
| EV-SYN-103 | Thirty lines show repeated laboratory activity requiring review | $9,000 gross implicated; clinical appropriateness unresolved |
| EV-SYN-104 | Referrals concentrate among entities sharing an ownership assertion | Context only; no additional dollars added |

These line sets are disjoint in this example; actual aggregation must de-duplicate them. Distinct members overlap across findings and are counted once.

**Timeline:** a simulated referral concentration increase appears in June; repeated laboratory activity appears in July; the duplicate-service group appears in August. The relationship assertion was available before the run cutoff. Each statement must link to its underlying dated rows in the implemented brief.

**Forecast:** for the eligible primary provider, illustrative repeat-event probabilities are 20% by 30 days, 40% by 60 days, and 58% by 90 days. These demonstrate formatting only. A live report must substitute validated model outputs and include the target and model version. No network-wide probability is inferred.

**Evidence strength:** moderate. Billing and payment rows are available, but distinct-encounter documentation is absent; ownership is asserted rather than independently confirmed. Some dates lack time precision, so no impossible-travel conclusion is drawn for those records.

**Alternative explanations:** legitimate repeat monitoring, appropriately distinct services, and a legitimate integrated referral network.

**Recommended human steps:** confirm claim lineage and reversals; inspect distinct-encounter documentation for the duplicate group; review bundle exceptions; verify referral and ownership context; decide whether the case should be split or retained as a joint investigation.

**Decision:** pending authorized human review. The system has not substantiated FWA, approved an external referral, or taken a payment action.

## Citation and export controls

Each brief saves its evidence hash, source manifest, template version, optional rewrite model/version, validation result, and case snapshot. Evidence links identify the exact file/row/fields; row hashes detect later source drift. Exports include a relationship table and the visible limitations.

A reviewer edits a draft through a tracked version and explicitly approves a final brief. Later analysis creates an amendment or new draft, never silently overwrites the approved report. Unapproved drafts are visibly labeled and cannot be mistaken for an authorized decision record.
