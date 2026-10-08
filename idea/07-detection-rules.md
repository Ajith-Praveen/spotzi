# 07 — Detection rules and contextual indicators

## Detection contract

A detector returns findings, evaluated population, unsupported rows, and explicit exception decisions. Each finding contains source row IDs, field values, the comparator, rule/version, cutoff, family applicability, severity proposal, limitations, and recommended human-review step.

Statuses are `flagged`, `not_flagged`, `unsupported`, and `error`. “Not flagged” means that this detector found no qualifying pattern; it is not proof that the claim is legitimate. A detector cannot transition a case to substantiated or initiate a payer action..

Rules below are **synthetic demonstration policies**, not universal reimbursement rules. Real NCCI implementation would require program, provider setting, effective date, code pair, and modifier semantics. CMS describes NCCI edits as coding edits rather than a determination of medical necessity. [CMS NCCI FAQ](https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits/medicare-ncci-faq-library).

## R01 — Possible duplicate billing

Canonicalize replacements and voids first. Partition comparable active lines by member, rendering provider, code, service date/time, units, modifiers, place of service, and relevant encounter/item identity. Flag multiple independently submitted paid lines for one apparently equivalent service.

Do not equate identical import rows with distinct claims. Exclude reversed payments from paid exposure. Preserve legitimate repeated services with separate encounters, laterality, specimens, or rental periods. Missing differentiating fields reduce confidence rather than proving duplication.

Evidence: all competing line IDs, matching fields, differences, transaction lineage, net paid per line, and why exceptions did or did not apply. For an illustrative group of three equivalent paid lines at $100 each, potential duplicate overpayment is at most $200 when one legitimate payment is assumed; gross implicated paid amount is $300. Neither is confirmed recovery.

## R02 — Possible coding intensity mismatch

At provider/family/peer-group level, compare the share of higher-intensity synthetic procedure codes over a 30-day window with a supported peer distribution and the provider's earlier baseline. Example trigger: at least 30 comparable services and a robust deviation above a configured threshold.

Adjust comparisons for available simulated complexity, specialty, setting, and procedure group. If these controls are absent, state “coding mix outlier,” not “upcoding detected.” Claims alone usually cannot establish the clinical documentation needed to resolve an upcoding concern.

Evidence: numerator/denominator, peer definition/size, time trend, intensity map version, available case-mix fields, and representative claims. Human action: review a sample of supporting service records and coding context.

## R03 — Possible unbundling

Use a versioned synthetic pair table: code A, code B, effective interval, service family, allowed exception modifiers, and required same-encounter context. Flag conflicting co-billing only when all applicable conditions hold.

An allowed modifier does not automatically prove an exception; show it as a reason to check distinct-service evidence. Missing modifier or encounter data produces qualified findings. Do not apply an outpatient pair rule to every facility or pharmacy claim.

Evidence: code pair, line IDs, rule record, effective date, matching context, modifier evaluation, and potentially overlapping paid amount. Human action: confirm whether services were distinct and appropriately reported.

## R04 — Possible unperformed service indicators

Compare claimed services with an optional complete synthetic encounter/delivery feed, service availability windows, and supporting records. A missing encounter can be an indicator only if feed completeness for that provider/time/family is established.

Without a complete corroborating feed, return “supporting service record unavailable,” not “phantom service.” Claims after a facility closure may reflect late submission; compare service date and availability history, not receipt date alone.

Evidence: feed coverage statement, matching logic, relevant service rows, facility history, and unresolved alternatives. Human action: seek corroborating delivery or encounter documentation through the authorized simulated workflow.

## R05 — Excessive utilization

Count comparable units or episodes per member/procedure group over 7/30/90 days. Compare with simulation policy and condition-aware peers. Provider-wide concentrations add context. Do not use an arbitrary global count across unrelated families.

Distinguish units, visits, fills, admissions, and rental months. Exclude known reversals and same-episode fragments. A chronically ill member's appropriate utilization is a matched negative control. Utilization is an investigation signal, never a clinical necessity decision.

Evidence: distinct episodes, units, dates, policy/peer range, exceptions, and missing complexity information.

## R06 — Incompatible service timing

Use rendering individual rather than billing organization. For two services with trustworthy start/end times, compute overlap or available travel gap. Require in-person, individual-service context, distinct locations with adequate precision, and an explicit travel assumption.

Example: overlapping individual appointments at distinct facilities are inconsistent. A distance-based travel check should use a conservative lower bound and a configurable margin; straight-line distance is not road routing. Do not infer exact timing from date-only records, group sessions, telehealth, multiple clinicians, or an ambulance trip endpoint alone.

Evidence: both time intervals, timezones, source precision, distance, assumptions, and excluded alternatives. Return unsupported when timing precision is inadequate.

## R07–R10 — Family-aware extensions

| Rule | Logic | Required exception handling |
|---|---|---|
| R07 DME repetition | Same member/item group with repeated acquisition or overlapping rental | Replacement, repair, rental vs purchase, distinct devices |
| R08 Pharmacy supply | Overlapping fill supply after netting reversals | Dose changes, overrides, product substitutions, days-supply quality |
| R09 Referral concentration | Excess concentration relative to specialty and geography peers | Legitimate specialist networks, enrollment mix, exclusive service availability |
| R10 Capacity inconsistency | Individual service hours exceed declared supported capacity | Group services, multiple staff, capacity changes, unknown duration |

Graph outputs supplement R09; relationships alone never establish a billing violation.

## Rule configuration and changes

Every rule has ID, version, enabled families, required fields, minimum sample size, thresholds, effective dates, exception logic, and evidence template. Threshold changes require a human analyst proposal and an authorized review before the version becomes active. Run a before/after replay on fixed synthetic validation fixtures.

Duplicate findings from the same rule and source set use stable fingerprints. Multiple rules can cite the same claim, but dollars and case membership are de-duplicated downstream. Keep rule evidence visible separately from the combined case priority.

## Required fixture tests

For every rule: one positive, one benign lookalike, one missing-input case, one boundary-time case, and one corrected/reversed transaction case where relevant. Test that exceptions suppress only the intended pattern and that unsupported data never becomes a negative label.
