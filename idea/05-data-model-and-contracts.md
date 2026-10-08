# 05 — Data model and contracts

## Conventions

Every tenant-owned table includes `tenant_id`. IDs are stable opaque strings or UUIDs; synthetic display IDs use prefixes such as `SYN-PROV-0042`. Do not generate apparently real NPIs. Monetary values use integer minor units with ISO currency; USD cents are the demo default. Quantities use decimals and explicit unit types.

All timestamps are UTC instants where known. Store original timezone, precision (`date`, `minute`, `second`), and source row. Dimension history includes business validity (`valid_from`, `valid_to`) and knowledge availability (`available_at`, `superseded_at`). An as-of query must satisfy both histories.

## Input bundle

| File | Grain and key | Required fields | Important optional fields |
|---|---|---|---|
| `members.csv` | Member version | member_id, version, age_band, region, enrollment_start/end, available_at | simulated morbidity bucket, coverage product |
| `providers.csv` | Provider version | provider_id, version, specialty, organization_id, active_from/to, available_at | practice capacity, taxonomy proxy |
| `facilities.csv` | Facility version | facility_id, type, location_id, active_from/to, available_at | staffed capacity |
| `locations.csv` | Fictional location | location_id, latitude, longitude, timezone, precision | campus_id, normalized address token |
| `claim_headers.csv` | Claim transaction version | claim_id, claim_version, family, member_id, billing_provider_id, received_at, status | original_claim_id, replacement_for_version, facility_id |
| `claim_lines.csv` | Claim version line | claim_id, claim_version, line_id, service_from/to, code_system, procedure_code, units, billed_cents, allowed_cents, currency | rendering_provider_id, modifiers, encounter_id, referral_id, authorization_id |
| `payments.csv` | Payment event | payment_event_id, claim_id, claim_version, line_id, amount_cents, event_type, effective_at, available_at | reverses_event_id |
| `referrals.csv` | Referral event | referral_id, member_id, ordering_provider_id, receiving_entity_id/type, ordered_at, available_at | completed_at, procedure_group |
| `relationships.csv` | Dated assertion | relationship_id, source_id/type, target_id/type, relationship_type, valid_from/to, available_at, source_record_id, confidence | ownership share, asserted/verified status |
| `investigations.csv` | Investigation history event | investigation_id, entity_id/type, event_type, event_at, available_at, outcome_status | adjudicator, reason, evidence refs |

Use `available_at` in all files, even where the table abbreviates other fields. No private notes, real names, full dates of birth, telephone numbers, or real account details are necessary.

Family extensions use separate typed tables or validated extension objects: pharmacy has fill date, product group, days supply, and reversal references; ambulance has trip origin/destination and transport mode; facility has admission/discharge and bill type; home health has episode and visit identity; behavioral health has individual/group setting; DME has item group, rental/purchase status, and delivery indicator; laboratory has order/specimen/accession references when generated. Do not assume these fields exist for all families.

## Claim lifecycle and money

Preserve raw transactions. Resolve replacements and voids into a canonical active service-line view at the selected cutoff. A replacement updates the claim lineage; a payment reversal updates the ledger. These are different operations and must not be conflated.

Define `net_paid_cents(line, t)` as the sum of valid signed ledger events attributable to the canonical service line and available by `t`. Prevent reversal events from being applied twice. Follow explicit mappings when a replacement changes line identifiers; unresolved mappings are excluded from exposure calculations with a warning.

Two identical source rows in the same import are ingestion duplicates. Two independently submitted active paid claims for the same service are possible billing duplicates. De-duplicating the former must not erase the latter.

## Derived operational tables

| Table | Essential fields and meaning |
|---|---|
| `datasets` | id, manifest hash, schema version, provenance, state, counts |
| `raw_records` | dataset, file, row number, stable row hash, immutable payload |
| `analysis_runs` | dataset/version, cutoff, all component versions, status, coverage |
| `feature_snapshots` | run, entity, observation time, feature version, values, missingness |
| `findings` | id, run, detector/version, subject, category, strength, status |
| `evidence_items` | id, finding, source row/field refs, values, comparator, computation |
| `graph_edges` | run, type, endpoints, source refs, confidence, effective dates |
| `forecasts` | run, entity, target version, horizon, probability/null, eligibility, model version |
| `cases` | stable case id, current version, primary entity, lifecycle state, assignee |
| `case_snapshots` | case/version, run, risk components, exposure, member count, limits |
| `case_findings` | case/version to finding associations; preserves original ownership |
| `case_claim_lines` | case/version to distinct canonical lines and exposure attribution |
| `case_events` | actor, state transition, reason, evidence refs, timestamp |
| `recommendations` | run, case/version, proposed scope/action/priority, evidence, machine author; cannot encode final approval |
| `decision_proposals` | case/version, human investigator, proposed outcome, rationale, evidence, unresolved questions |
| `human_decisions` | proposal, reviewed case version, human approver/role, outcome, rationale, evidence, time, prior-decision lineage |
| `capacity_plans` | policy, run, hours, selected cases, estimates, preview/apply state |
| `briefs` | case version, evidence hash, template version, text, citation manifest |
| `jobs` | type, input hash, state, attempts, lease owner/expiry, progress |
| `audit_events` | actor, tenant, action, object, old/new version, reason, timestamp |
| `precedent_snapshots` | approved source case/version, policy era, frozen features/evidence, eligibility state |
| `precedent_retrieval_runs` | current case/version, retrieval policy, candidates, similarity and difference records |
| `review_blueprints` | investigator-selected precedents and editable, source-linked checklist |

Cases persist across runs, while their evidence snapshots are immutable. A merge creates a recorded alias/relationship and new snapshot; it never deletes the source cases.

Precedent snapshots are immutable derivatives of quality-reviewed human decisions. A source-case amendment retires the old snapshot from new retrieval and creates a new version. Historical retrievals retain the original snapshot so the context used by a reviewer remains reconstructable.

Use separate database/service permissions for analysis writers and human workflow writers. The worker cannot insert final human decisions. Link each decision to the exact evidence reviewed; approval cannot be inferred from a high score or a completed job.

## Index and constraint plan

Create unique constraints on dataset/file/row hash, claim transaction/line identity, payment event ID, run/detector/finding fingerprint, and case version. Index member/date, rendering-provider/date, referral endpoints/date, relationship endpoints/validity, run/status, and queue priority fields. Include tenant keys in lookup indexes and foreign-key design.

Require known currency, finite quantities, valid enums, linked providers/members, coherent date ranges, and recognized payment event semantics. Negative ledger events are valid reversals; negative billed values require an explicitly supported adjustment type. Validate reference existence without assuming every referral must have a completed claim.

## Example manifest

```json
{
  "schema_version": "1.0",
  "dataset_id": "SYN-DEMO-001",
  "synthetic_only": true,
  "generator_version": "0.1.0",
  "seed": 42,
  "observation_start": "2024-01-01T00:00:00Z",
  "observation_end": "2026-01-01T00:00:00Z",
  "currency": "USD",
  "files": [
    {"name": "claim_lines.csv", "sha256": "<computed hash>", "rows": 100000}
  ]
}
```

The completed manifest lists every file. A declaration is provenance metadata, not proof that arbitrary uploads are safe. The hosted demo should default to bundled generated datasets; synthetic-only import controls are detailed in document 15.

## Output semantics

Use `null` plus a reason for unavailable values. Every output reports `as_of`, version, coverage, and status. Separate `risk_index_0_100`, `anomaly_percentile`, `forecast_probability`, `evidence_quality`, and `priority_score` at the schema level so the frontend cannot accidentally interchange them.
