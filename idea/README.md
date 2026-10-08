# SpotZ^i — implementation blueprint

> Prepared 8 October 2026. This folder is a design deliverable, not an implemented application. Examples, thresholds, estimates, and performance targets are proposed or synthetic unless explicitly sourced.

Build an **evidence-first SIU investigation workbench** that turns individual alerts into understandable, prioritized cases. The main experience is **load → validate → detect → connect → forecast → rank → investigate → record a human outcome**.

**Hard requirements: synthetic data only; humans make every final decision.** The system recommends findings, case scope, priorities, and next steps. Authorized people decide investigation scope, assignments, outcomes, and approvals. No automated adverse action or external referral exists in the prototype.

## Reading guide

| Document | What it answers |
|---|---|
| [01 — Product and scope](01-product-and-scope.md) | What to build, for whom, and why |
| [02 — User journeys and UI](02-user-journeys-and-ui.md) | Screens, interactions, uncertainty, and user actions |
| [03 — System architecture](03-system-architecture.md) | Stack, components, data flow, failure handling, scale |
| [04 — Repository and file architecture](04-repository-and-file-architecture.md) | Exact proposed application filenames and responsibilities |
| [05 — Data model and contracts](05-data-model-and-contracts.md) | Tables, fields, keys, temporal semantics, validation |
| [06 — Synthetic data and scenarios](06-synthetic-data-and-scenarios.md) | Generation, hidden truth, controls, scenario design |
| [07 — Detection rules](07-detection-rules.md) | Rule logic, prerequisites, exceptions, evidence |
| [08 — Feature engineering](08-feature-engineering.md) | Claim, provider, member, temporal, and graph features |
| [09 — ML models and training](09-ml-models-and-training.md) | Models, hyperparameters, training, calibration, release gates |
| [10 — 30/60/90-day forecasting](10-forecasting-30-60-90-days.md) | Targets, censoring, probabilities, validation |
| [11 — Graph and network intelligence](11-graph-and-network-intelligence.md) | Entity relationships, communities, motifs, graph UI |
| [12 — SIU prioritization and case lifecycle](12-siu-prioritization-and-case-lifecycle.md) | Case construction, ranking, dollars, capacity, feedback |
| [13 — Evidence and investigation briefs](13-evidence-and-investigation-briefs.md) | Evidence contracts, grounded explanations, example brief |
| [14 — API and background jobs](14-api-and-background-jobs.md) | Endpoints, examples, idempotency, concurrency, errors |
| [15 — Responsible AI, security, governance](15-responsible-ai-security-and-governance.md) | Human control, uncertainty, access, audit, safeguards |
| [16 — Testing, evaluation, acceptance](16-testing-evaluation-and-acceptance.md) | Tests, metrics, leakage checks, release criteria |
| [17 — Implementation roadmap and demo](17-implementation-roadmap-and-demo.md) | Build order, estimates, demo narrative, scope cuts |
| [18 — Deployment, operations, cost](18-deployment-operations-and-cost.md) | Deployment, configuration, monitoring, recovery, resource budget |
| [19 — Decisions, risks, references](19-decisions-risks-and-references.md) | Decisions, open questions, glossary, primary sources |
| [20 — Human review and decision mechanism](20-human-review-and-decision-mechanism.md) | Review stages, roles, approvals, disagreements, decision records, audit |
| [21 — SpotZ^i Evidence Challenge Lab](21-nexus-evidence-challenge-lab.md) | Flagship add-on: competing explanations, evidence checks, scenario branches, and human decisions |
| [22 — Precedent Intelligence](22-precedent-intelligence.md) | Similar reviewed cases, material differences, and reusable review blueprints |
| [23 — Responsive web and PWA](23-responsive-web-and-pwa.md) | Installability, responsive layouts, offline boundaries, notifications, and updates |

## Proposed flagship differentiator

[SpotZ^i Evidence Challenge Lab](21-nexus-evidence-challenge-lab.md) helps a reviewer compare legitimate and suspicious explanations, select evidence that could distinguish them, and preserve the reasoning behind the final human decision. Its signature synthetic demonstration uses matched cases with identical visible claims and different underlying explanations. The proposal includes a competitive reality check, technical design, filenames, and evaluation plan; worldwide uniqueness is not claimed.

[Precedent Intelligence](22-precedent-intelligence.md) retrieves comparable, quality-reviewed historical cases and turns their evidence checks into an editable blueprint for the current review. It emphasizes material differences and never copies a prior outcome. SpotZ^i is delivered as a responsive internal web application with the installable PWA behavior specified in [document 23](23-responsive-web-and-pwa.md).

## Recommended foundation

- Web: React, TypeScript, Vite, TanStack Query/Table, Cytoscape.js, Recharts.
- Backend: Python, FastAPI, Pydantic, SQLAlchemy, Alembic.
- Data: PostgreSQL for operational state; Parquet plus DuckDB/Polars for batch analytics.
- Intelligence: versioned rules, Isolation Forest, NetworkX graph analytics, logistic regression baseline and XGBoost forecasting.
- Execution: one API and one worker sharing a codebase; PostgreSQL job table; Docker Compose.
- Explanations: deterministic evidence-based briefs; optional language model for wording only.

These are proposed choices. Pin compatible dependency versions during implementation. No packages, services, models, or datasets have been installed or built by this documentation task.

## Keep these distinctions visible

Rule hits, anomaly percentiles, future-event probabilities, evidence quality, and queue priority are different quantities. A suspicious pattern is not proof of fraud. Potential exposure is not a recovery. Synthetic performance is not validated real-world effectiveness.

Every finding must resolve to source rows and a versioned analysis run. Missing information becomes an explicit unknown. Hidden scenario truth never enters inference. All investigative decisions stay with a person.

Start with professional, laboratory, and DME scenarios deeply; support ingestion and family-specific limitations for all eight service families. The repository tree describes files to implement later. Only the Markdown files in this folder are created now.
