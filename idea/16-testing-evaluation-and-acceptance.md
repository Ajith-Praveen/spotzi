# 16 — Testing, evaluation, and acceptance

## What must be proven

Prove a complete synthetic-data-to-human-decision workflow, the integrity of evidence and money, meaningful complementary detection, and honest handling of uncertainty. A model accuracy number alone is not sufficient.

## Test layers

| Layer | Critical cases | Expected invariant |
|---|---|---|
| Schema/ingestion | Missing keys, invalid dates, mismatched hashes, undeclared provenance | Invalid rows quarantined or dataset rejected clearly |
| Claim lifecycle | Replacement, void, partial/full reversal, duplicate import | Correct canonical services and net paid exposure |
| Rules | Positive, benign lookalike, missing prerequisite, boundary dates | Correct flag/exception/unsupported status |
| Features | Late claim, late relationship, outcome learned after cutoff | Historical feature vector unchanged by future knowledge |
| Graph | Shared address only, legitimate group, planted referral network | No guilt-by-association; supported paths preserved |
| Forecasts | First event, censored interval, inadequate history | Correct labels/eligibility and monotone horizons |
| Cases | Overlapping signals, multi-case line overlap, human split | Stable lineage and no duplicated portfolio dollars |
| Capacity | Zero hours, too-large case, skill mismatch, stale preview | Constraints respected; apply requires human action |
| Brief | Missing citation, altered amount, prompt injection, rewrite failure | Reject unsupported wording and render safe template |
| Human decisions | Service account, unauthorized approver, self-approval restriction | No unauthorized state transition |
| Precedents | Similar structure/opposite explanation, retired source, future policy version | Differences shown; invalid precedent excluded; no copied outcome |
| PWA | Offline launch, stale API, worker update during draft rationale | Read-only shell; no cached decision; no lost draft |
| Concurrency | Two reviewers editing, duplicate job, expired lease | No lost update or duplicate committed output |
| Security | Cross-tenant IDs, graph traversal, artifact download | No cross-tenant data exposure |

## Detection metrics

- **Finding precision:** supported injected-pattern findings / evaluated findings, with scenario truth definition disclosed.
- **Scenario recall:** distinct injected scenarios surfaced / eligible injected scenarios. Do not inflate recall by counting repeated alerts for one episode.
- **Precision@K:** supported candidate cases among the top K under a specified capacity policy.
- **Recall at hours:** qualifying scenarios reached within the review-hour budget.
- **Benign-control false-positive rate:** flagged controls / eligible benign controls, broken down by exception type.
- **Alert-to-case compression:** findings / proposed cases, accompanied by recall and bystander inclusion.
- **Distinct exposure capture:** unique scenario-attributable dollars surfaced / eligible simulated dollars; use hidden truth only in evaluation.

Keep claim-level, provider-level, and case-level denominators separate. Report PR-AUC for imbalanced event tasks; ROC-AUC can be supplementary. Neither high ROC-AUC nor high accuracy proves usefulness in a sparse SIU queue.

## Forecast metrics

For each target and horizon: event prevalence, sample/event counts, exclusions, Brier score, reliability plots, PR-AUC, precision/recall at capacity, and calibration by supported family/volume slices. Compare with prevalence-only and logistic baselines.

Use provider- or generating-network-clustered uncertainty estimates. Report when a slice is too small for a reliable conclusion. Verify `0 <= P30 <= P60 <= P90 <= 1` for every eligible prediction. Repeat and escalation are separate endpoints and need not be ordered against one another.

## Ablation plan

Evaluate rules only; anomalies only; rules + anomalies; rules + anomalies + graph; and the full recommendation policy with forecasting. Hold the capacity budget and case aggregation logic fixed where appropriate. Report which addition improves distinct supported cases, workload, or evidence quality rather than claiming that more algorithms automatically help.

## Leakage and shortcut audits

1. Scan feature schemas and artifacts for truth columns, scenario IDs, eventual outcomes, and future-only fields.
2. Add future records to a fixture and assert earlier outputs do not change.
3. Randomize irrelevant synthetic IDs; predictions should be unchanged.
4. Evaluate separate seeds, unseen provider groups, unseen network shapes, and held-out scenario variants.
5. Train a simple diagnostic on generator metadata; if it predicts truth, remove the shortcut before model evaluation.
6. Verify calibration transforms are fit only on the calibration partition.
7. Freeze thresholds before final evaluation; do not tune after seeing the reserved test report.

## Proposed acceptance targets

These are initial engineering/demo targets, not measured achievements or mandatory real-world performance claims. Final values should be frozen before evaluation and reported honestly if missed.

| Area | Target |
|---|---|
| End-to-end | Fresh seeded dataset reaches a reviewable case and recorded human decision |
| Requirement coverage | All eight families ingested; six named categories have positive and benign tests |
| Evidence | Every displayed finding has resolvable source/field/version links |
| Money | Exact reconciliation on ledger fixtures; no duplicated cross-case portfolio exposure |
| Human control | Zero automatic final decisions, assignments, external actions, or approved briefs |
| Synthetic provenance | All serving records come from approved synthetic manifests |
| Forecast integrity | All eligible outputs bounded/monotone; all ineligible outputs explain abstention |
| Evaluation | Multiple seeds plus temporal and entity-disjoint results, including failures |
| Detection utility | Aim for at least 80% top-20 case precision on held-out synthetic fixtures; publish actual result |
| Benign controls | Aim below 10% false positives on supported benign controls; disclose per-type counts |
| Performance | Aim for queue reads under 2 seconds and 100k-line analysis under 5 minutes on stated hardware |
| Precedent assistance | Material differences identified and review time measured without increased decision-copying errors |
| PWA safety | Installable shell; API responses excluded from cache; workflow mutations disabled offline |

Latency targets require an explicit benchmark fixture, cold/warm distinction, percentile, concurrency, and memory measurement. Do not report a single best run as the system's capacity.

## End-to-end acceptance script

Load the fixed demo seed; approve the validation report; start analysis; open a candidate; trace a duplicate line through its payment lineage; inspect a graph edge; compare all forecast horizons; inspect one unavailable forecast; preview a capacity plan; apply it as a manager; submit a decision as an investigator; approve it as an authorized human; export the approved brief; rerun analysis and verify the decision remains unchanged.

Repeat with model service unavailable, missing timestamps, and an unsupported import. The system must remain clear about partial capability and must never manufacture a final decision to complete the demo.

## Evaluation report artifact

Save code revision, dependency hashes, generator versions/seeds, all split manifests, policy/model versions, metrics and denominators, representative false positives/negatives, abstention rates, runtime/memory, and reviewer approval. Include a prominent statement that the results validate only the specified synthetic experiment.
