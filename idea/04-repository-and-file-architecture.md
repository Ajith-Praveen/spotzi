# 04 — Repository and file architecture

## How to use this tree

The repository root is `/Users/ajith/acentra`. The files below are the **proposed implementation tree**; this task creates only `idea/*.md`. Build modules in the roadmap order instead of creating hundreds of empty stubs.

Use a Python package called `claimshield` under `backend/src/`. Tests import public module interfaces. API routers delegate to services; services use repositories and analytics contracts. Models never import frontend or API code.

```text
acentra/
├── idea/                              # This blueprint and its index
├── README.md                          # Setup, demo, status, measured limits
├── .env.example                       # Names and safe local defaults, no secrets
├── .gitignore                         # Data, model binaries, secrets, build output
├── Makefile                           # Documented local developer commands
├── compose.yaml                       # Web, API, worker, PostgreSQL
├── backend/
│   ├── pyproject.toml                 # Dependencies, package and tooling configuration
│   ├── uv.lock                        # Reproducible Python environment
│   ├── alembic.ini
│   ├── migrations/
│   │   ├── env.py
│   │   └── versions/
│   │       ├── 0001_tenants_datasets_claims.py
│   │       ├── 0002_entities_relationships.py
│   │       ├── 0003_analysis_evidence_predictions.py
│   │       └── 0004_cases_jobs_audit.py
│   ├── src/claimshield/
│   │   ├── __init__.py
│   │   ├── main.py                    # API construction and middleware
│   │   ├── cli.py                     # Generate, validate, run, train, evaluate
│   │   ├── settings.py                # Typed configuration and environment validation
│   │   ├── api/
│   │   │   ├── dependencies.py        # Tenant, actor, database session
│   │   │   ├── errors.py              # Stable structured error responses
│   │   │   └── routers/
│   │   │       ├── health.py
│   │   │       ├── datasets.py
│   │   │       ├── analysis_runs.py
│   │   │       ├── claims.py
│   │   │       ├── cases.py
│   │   │       ├── human_review.py    # Proposal, approval, disagreement, reopening routes
│   │   │       ├── forecasts.py
│   │   │       ├── graphs.py
│   │   │       ├── capacity.py
│   │   │       └── governance.py
│   │   ├── schemas/
│   │   │   ├── common.py              # IDs, money, timestamps, pagination
│   │   │   ├── ingestion.py
│   │   │   ├── claims.py
│   │   │   ├── findings.py
│   │   │   ├── forecasts.py
│   │   │   ├── cases.py
│   │   │   ├── human_review.py        # Typed recommendation, proposal and decision contracts
│   │   │   ├── graphs.py
│   │   │   └── briefs.py
│   │   ├── db/
│   │   │   ├── session.py
│   │   │   ├── models/
│   │   │   │   ├── identity.py        # Tenant, actor, role
│   │   │   │   ├── source.py          # Dataset, raw rows, claim versions
│   │   │   │   ├── entities.py
│   │   │   │   ├── analysis.py
│   │   │   │   ├── cases.py
│   │   │   │   ├── human_review.py    # Separate recommendation/proposal/decision tables
│   │   │   │   └── operations.py      # Jobs, leases, audit records
│   │   │   └── repositories/
│   │   │       ├── claims.py
│   │   │       ├── evidence.py
│   │   │       ├── cases.py
│   │   │       └── jobs.py
│   │   ├── ingestion/
│   │   │   ├── manifest.py
│   │   │   ├── csv_reader.py
│   │   │   ├── parquet_reader.py
│   │   │   ├── validation.py
│   │   │   ├── quarantine.py
│   │   │   └── canonicalize_claims.py
│   │   ├── synthetic/
│   │   │   ├── generator.py
│   │   │   ├── entities.py
│   │   │   ├── utilization.py
│   │   │   ├── payment_lifecycle.py
│   │   │   ├── relationships.py
│   │   │   ├── delayed_outcomes.py
│   │   │   └── scenarios/
│   │   │       ├── duplicates.py
│   │   │       ├── coding_patterns.py
│   │   │       ├── service_timing.py
│   │   │       ├── referral_network.py
│   │   │       ├── escalating_activity.py
│   │   │       └── benign_controls.py
│   │   ├── features/
│   │   │   ├── contracts.py
│   │   │   ├── point_in_time.py
│   │   │   ├── peer_groups.py
│   │   │   ├── pipeline.py
│   │   │   └── sql/
│   │   │       ├── claim_context.sql
│   │   │       ├── provider_windows.sql
│   │   │       ├── member_windows.sql
│   │   │       └── referral_windows.sql
│   │   ├── detection/
│   │   │   ├── contracts.py           # DetectorResult, evaluated/unknown statuses
│   │   │   ├── runner.py
│   │   │   ├── rule_registry.py
│   │   │   ├── duplicate.py
│   │   │   ├── coding.py
│   │   │   ├── utilization.py
│   │   │   ├── timing.py
│   │   │   ├── phantom_indicators.py
│   │   │   └── anomaly.py
│   │   ├── graph/
│   │   │   ├── builder.py
│   │   │   ├── projections.py
│   │   │   ├── communities.py
│   │   │   ├── motifs.py
│   │   │   └── evidence_paths.py
│   │   ├── ml/
│   │   │   ├── labels.py
│   │   │   ├── temporal_splits.py
│   │   │   ├── train_anomaly.py
│   │   │   ├── train_forecast.py
│   │   │   ├── calibration.py
│   │   │   ├── evaluate.py
│   │   │   ├── explain.py
│   │   │   ├── registry.py
│   │   │   └── predict.py
│   │   ├── forecasting/
│   │   │   ├── eligibility.py
│   │   │   ├── person_period.py
│   │   │   ├── cumulative_risk.py
│   │   │   └── service.py
│   │   ├── cases/
│   │   │   ├── builder.py
│   │   │   ├── deduplicate.py
│   │   │   ├── exposure.py
│   │   │   ├── prioritization.py
│   │   │   ├── capacity.py
│   │   │   ├── lifecycle.py
│   │   │   └── service.py
│   │   ├── evidence/
│   │   │   ├── provenance.py
│   │   │   ├── store.py
│   │   │   └── coverage.py
│   │   ├── human_review/
│   │   │   ├── proposals.py
│   │   │   ├── approval_policy.py
│   │   │   ├── decisions.py
│   │   │   ├── disagreements.py
│   │   │   └── label_curation.py
│   │   ├── precedents/
│   │   │   ├── contracts.py
│   │   │   ├── eligibility.py
│   │   │   ├── fingerprint.py
│   │   │   ├── structured_similarity.py
│   │   │   ├── differences.py
│   │   │   ├── retrieval.py
│   │   │   ├── quality_review.py
│   │   │   ├── blueprint_builder.py
│   │   │   └── replay.py
│   │   ├── briefs/
│   │   │   ├── builder.py
│   │   │   ├── renderer.py
│   │   │   ├── validator.py
│   │   │   ├── optional_rewriter.py
│   │   │   └── templates/investigation.md.j2
│   │   ├── jobs/
│   │   │   ├── worker.py
│   │   │   ├── lease.py
│   │   │   ├── pipeline.py
│   │   │   └── tasks.py
│   │   ├── security/
│   │   │   ├── auth.py
│   │   │   ├── permissions.py
│   │   │   └── audit.py
│   │   └── observability/
│   │       ├── logging.py
│   │       └── metrics.py
│   └── tests/
│       ├── conftest.py
│       ├── unit/test_duplicate_reversals.py
│       ├── unit/test_rule_exceptions.py
│       ├── unit/test_point_in_time.py
│       ├── unit/test_cumulative_risk.py
│       ├── unit/test_exposure_deduplication.py
│       ├── unit/test_capacity_constraints.py
│       ├── integration/test_dataset_to_case.py
│       ├── integration/test_job_retry.py
│       ├── integration/test_tenant_isolation.py
│       ├── integration/test_human_decision_boundary.py
│       ├── integration/test_precedent_to_blueprint.py
│       ├── evaluation/test_precedent_retrieval.py
│       └── evaluation/test_truth_exclusion.py
├── frontend/
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── public/
│   │   ├── manifest.webmanifest
│   │   ├── spotzi-icon.svg
│   │   ├── sw.js
│   │   └── offline.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── routes.tsx
│   │   ├── api/client.ts
│   │   ├── api/generated.ts           # Generated from backend OpenAPI
│   │   ├── components/
│   │   │   ├── AppShell.tsx
│   │   │   ├── SyntheticBanner.tsx
│   │   │   ├── EvidenceLink.tsx
│   │   │   ├── RiskBadge.tsx
│   │   │   ├── MoneyCell.tsx
│   │   │   └── CoverageNotice.tsx
│   │   ├── features/
│   │   │   ├── overview/OverviewPage.tsx
│   │   │   ├── datasets/DatasetsPage.tsx
│   │   │   ├── datasets/ValidationReport.tsx
│   │   │   ├── runs/RunDetailPage.tsx
│   │   │   ├── queue/QueuePage.tsx
│   │   │   ├── queue/CapacityPlanner.tsx
│   │   │   ├── cases/CasePage.tsx
│   │   │   ├── cases/EvidenceTable.tsx
│   │   │   ├── cases/ClaimsTable.tsx
│   │   │   ├── cases/CaseTimeline.tsx
│   │   │   ├── cases/DispositionForm.tsx
│   │   │   ├── cases/HumanDecisionPanel.tsx
│   │   │   ├── cases/ApprovalReviewPanel.tsx
│   │   │   ├── precedents/PrecedentsTab.tsx
│   │   │   ├── precedents/PrecedentComparison.tsx
│   │   │   ├── precedents/ReviewBlueprint.tsx
│   │   │   ├── forecasts/ForecastPanel.tsx
│   │   │   ├── graph/NetworkPage.tsx
│   │   │   ├── graph/NetworkCanvas.tsx
│   │   │   ├── graph/RelationshipTable.tsx
│   │   │   ├── briefs/BriefPanel.tsx
│   │   │   └── governance/GovernancePage.tsx
│   │   └── styles/theme.css
│   └── tests/e2e/investigation-flow.spec.ts
├── configs/
│   ├── demo_small.yaml
│   ├── demo_large.yaml
│   ├── rules.yaml
│   ├── peer_groups.yaml
│   ├── features.yaml
│   ├── forecasts.yaml
│   ├── human_review_policy.yaml
│   ├── precedent_similarity.yaml
│   ├── priority_policy.yaml
│   └── capacity_policy.yaml
├── data/                              # Generated locally, excluded from Git
│   ├── raw/<dataset_id>/
│   ├── canonical/<dataset_id>/
│   ├── features/<run_id>/
│   └── quarantine/<dataset_id>/
├── evaluation_private/                # Never mounted in serving containers
│   ├── truth/<dataset_id>/
│   └── splits/<experiment_id>/
├── artifacts/                         # Immutable, versioned, excluded from Git
│   ├── models/<model_version>/
│   ├── evaluations/<experiment_id>/
│   ├── graphs/<run_id>/
│   └── briefs/<case_id>/<brief_version>/
├── contracts/
│   ├── dataset-manifest.schema.json
│   └── openapi.json
├── scripts/
│   ├── seed_demo.py
│   ├── check_contracts.py
│   └── benchmark_pipeline.py
├── infra/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   └── reverse-proxy.conf
└── .github/workflows/ci.yml
```

## Module contracts

`canonicalize_claims(dataset, as_of)` produces active service/payment facts plus lineage. `build_features(snapshot, feature_spec)` returns typed matrices with coverage. `detect(context)` returns findings and unsupported reasons. `predict(entity_snapshot)` returns target/horizon probabilities or explicit abstention. `build_cases(findings, graph)` returns versioned groupings. `rank_cases(policy, capacity)` returns a reproducible preview. `render_brief(evidence_bundle)` returns text and citations.

Keep these functions callable from tests and CLI without HTTP. Configuration is validated against schemas; a rules YAML file cannot execute arbitrary Python. Use typed enums for states and shared money utilities. Do not duplicate financial or risk calculations in React.

## Files to implement first

Start with `settings.py`, source models and migrations, ingestion validation, claim canonicalization, detector contracts, `duplicate.py`, evidence storage, case builder, the case router, and `QueuePage.tsx`/`CasePage.tsx`. One vertical slice should work before adding every planned module. Add `__init__.py` files as needed for the selected Python package layout; repetitive package markers are omitted from the tree.
