# 17 — Implementation roadmap and demonstration

## Delivery strategy

Build one coherent investigation flow before expanding model sophistication. Each milestone produces something executable and reviewable. Forecasts and broader family coverage are required for the complete prototype; do not describe an early slice as full completion.

Indicative effort: one experienced full-stack/ML engineer might need 15–25 focused working days for the evaluated prototype; a small team may shorten elapsed time with clear interfaces. These are planning estimates, dependent on experience and polish, not commitments. A 48-hour demo should disclose its narrower scope and precomputed artifacts.

## Milestone 1 — Contracts and synthetic data, days 1–3

Create backend/frontend foundations, typed configuration, migrations, input contracts, generator seed, claim lifecycle, validation reports, and fixture tests. Generate approximately 10,000 lines first, then the 100,000-line demo.

Outputs: valid dataset manifest, all eight family schemas, source provenance, working import/validation endpoint, no hidden truth in serving inputs. Human data approval is already present.

Exit condition: a duplicate-payment fixture and a legitimate reversal fixture reconcile correctly. Without this, model development risks learning from incorrect claim accounting.

## Milestone 2 — Rules to human-reviewed case, days 4–6

Implement duplicate/utilization rules, evidence persistence, case candidate builder, queue, case page, and deterministic brief. Add seeded fictional reviewer identities and server-side decision permissions.

Outputs: a person can accept a candidate, inspect exact source fields, record a reason, and approve an outcome through the defined role flow. The system cannot finalize a decision as a worker.

Exit condition: one end-to-end UI test proves data → recommendation → human decision → preserved audit history. This is the first vertical slice.

## Milestone 3 — Complementary intelligence, days 7–10

Add Isolation Forest, peer comparison views, graph extraction, referral/ownership motif, benign shared-facility network, and remaining six-category rule coverage. Add family-specific unsupported messages.

Outputs: multiple independent signal types remain visible and traceable; graph relationships have provenance and validity; anomalies are labeled percentiles, not probabilities.

Exit condition: a legitimate connected network is not promoted to a suspicious case solely because of its structure. Evaluate incremental case yield over rules alone.

## Milestone 4 — Forecasting and capacity, days 11–15

Build temporal anchors, event labels, purged partitions, logistic hazard baseline, calibration, horizon UI, and abstention logic. Add the XGBoost challenger only after the baseline evaluation works. Implement transparent capacity previews and explicit human assignment approval.

Outputs: reproducible target-specific 30/60/90-day forecasts; monotonicity tests; capacity constraints; disclosed missing predictions; separate human approval.

Exit condition: held-out report with known denominators and no truth leakage. If the model fails release gates, do not invent probabilities; improve data/model design or declare that requirement incomplete.

## Milestone 5 — Evaluation and presentation, days 16–20+

Run benign-control, cold-entity, unseen-scenario, and multi-seed evaluation. Review false positives, improve evidence presentation, complete security/concurrency checks, benchmark the pipeline, and rehearse the demo.

Outputs: approved model/rule cards, measured limits, a stable seeded demonstration, accessible evidence views, exportable human-approved brief, and recovery instructions.

Exit condition: all acceptance criteria are evidenced or explicitly documented as unmet. Do not change test data merely to improve the presentation score.

## Work packages for a small team

| Owner | Work package | Interface to agree first |
|---|---|---|
| Data/backend engineer | Generator, ledger, canonicalization, ingestion | Dataset and point-in-time contracts |
| ML/analytics engineer | Features, rules, graph, forecasts, evaluation | DetectorResult and feature schema |
| Frontend/product engineer | Queue, evidence, graph, human workflow | OpenAPI contracts and state transitions |
| Shared domain reviewer | Exception logic, scope, responsible language | Review rubric and decision boundaries |

These are suggested responsibilities, not agents or tasks created by this documentation.

## Ten-minute demo script

1. **0:00–1:00 — Explain the user problem.** Show synthetic label, data counts, and case-centric goal.
2. **1:00–2:00 — Load and validate.** Display one useful missing-data warning and approve the synthetic bundle as a human.
3. **2:00–3:00 — Analyze.** Show rules/anomaly/graph stages or a clearly labeled precomputed run if runtime is long.
4. **3:00–4:30 — Inspect the top candidate.** Explain its priority components and trace a duplicate finding to claims and payments.
5. **4:30–5:30 — Reveal the network.** Show referrals and ownership assertion; open the legitimate lookalike to demonstrate restraint.
6. **5:30–6:30 — Forecast.** Switch 30/60/90 days, explain the endpoint, and show an ineligible provider.
7. **6:30–7:30 — Plan capacity.** Preview limited hours, inspect deferred cases, approve assignments as the manager.
8. **7:30–9:00 — Human decision.** Reviewer requests or evaluates evidence, proposes an outcome, and an approver explicitly decides. Demonstrate disagreement or an exception.
9. **9:00–10:00 — Brief and accountability.** Export the approved brief, show audit history, and state measured synthetic-only limitations.

All dashboard totals must be computed from the displayed run. Precomputed model outputs are acceptable only if genuinely generated by the pipeline and visibly identified; fabricated inference results are not.

## Scope cuts under time pressure

Cut optional language-model rewriting, graph database, streaming, advanced optimization, elaborate animations, custom authentication UI, and recovery estimation before cutting provenance, human review, or synthetic-data safeguards. Use the logistic forecaster if the challenger adds no demonstrated value.

Keep simple tables where interactive charts would delay a working flow. The evidence table, source drill-down, forecast definitions, and decision audit are more important than a cinematic dashboard.

## Future command contract

The following commands are a proposed developer experience, not commands that exist yet:

```text
make setup
make demo-data
make validate-data
make train-baseline
make evaluate
make up
make test
make benchmark
```

Document arguments and artifacts when implementing them. A successful `make up` should not silently retrain or approve a new model; use an explicitly reviewed bundle.
