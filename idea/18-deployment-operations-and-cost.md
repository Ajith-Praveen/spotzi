# 18 — Deployment, operations, and resource budget

## Local-first deployment

Docker Compose starts PostgreSQL, API, worker, and web/reverse proxy. The API and worker use the same built backend image but different entrypoints. The training/evaluation command runs separately, with access to hidden truth that serving containers do not receive.

The web client is a responsive PWA served over HTTPS outside localhost. Its service worker caches only application-shell assets and an offline status view. API responses, claim records, case evidence, exports, and decision requests are excluded from the cache. Installed clients follow the same server authentication and authorization as browser sessions.

Mount raw/canonical/features directories read/write only where necessary. API downloads go through authorized artifact routes, never an unauthenticated static directory. Bind the local demo to localhost by default.

## Environment configuration

| Variable | Purpose | Safe default/constraint |
|---|---|---|
| `APP_ENV` | local/test/shared-demo | local |
| `DATABASE_URL` | PostgreSQL connection | Local isolated database; secret outside Git |
| `SYNTHETIC_ONLY` | Enforce source provenance | true; startup rejects false in prototype build |
| `ALLOW_ARBITRARY_UPLOADS` | Optional import capability | false for shared demos |
| `REQUIRE_HUMAN_DECISIONS` | Enforce workflow boundary | true; startup rejects false |
| `AUTH_MODE` | Fictional local identities or real auth integration | local only on localhost |
| `ARTIFACT_ROOT` | Versioned output directory | Dedicated workspace storage |
| `MODEL_BUNDLE_VERSION` | Approved compatible model | Explicit, no implicit latest |
| `RULESET_VERSION` | Active reviewed rules | Explicit |
| `WORKER_CONCURRENCY` | Parallel jobs | 1 initially |
| `MAX_GRAPH_NODES` | Initial graph response bound | 100, with truncation metadata |
| `BRIEF_REWRITING_ENABLED` | Optional language model | false |
| `UPLOAD_MAX_BYTES` | Input size bound | Set from measured fixture needs |

Critical synthetic-only and human-decision enforcement must also exist in code and tests. Environment flags are assertions of required behavior, not a backdoor to switch it off.

## Resource planning

Start development with approximately 4–8 CPU cores and 16 GB RAM if available, then measure actual needs. A smaller fixture can run on less. No GPU is required for the proposed rule, Isolation Forest, graph, and tree/logistic models.

Disk usage includes raw inputs, canonical copies, feature matrices, database indexes, model bundles, and retained run artifacts. It can exceed source CSV size several times. Bound retention and avoid copying full datasets per small case export.

A planning cost model is:

```text
monthly_cost = compute_hours * provider_hourly_price
             + database_storage_gb * storage_price
             + artifact_storage_gb * storage_price
             + backup_and_egress
             + optional_language_model_usage
```

No cloud prices or dollar estimates are asserted here. Check the chosen provider's current calculator when deploying. Offline templates eliminate optional inference-service cost and network dependency.

## Observability

Collect job runtime and failures by stage, queue age, rows processed, validation errors, unsupported-detector rates, model abstention rates, memory, API latency, graph truncation, and artifact sizes. For workflow health, record recommendation acceptance, overrides, time to first review, decisions pending approval, and reviewer disagreements.

Monitor feature drift and calibration only against a defined reference and matured labels. A distribution change is an alert for human analysis, not automatic model replacement. A rising override rate can reflect a poor model, new context, or policy disagreement; it is not proof the reviewer is wrong.

All logs include request/job/run IDs. Do not log entire rows or model prompts by default. Errors reveal enough context to debug without leaking secrets.

## Release and rollback

Build immutable images and model bundles. Run migrations separately with a backup/recovery plan. Validate model-feature compatibility before activating a bundle. A human model reviewer approves a registry pointer change; record old/new versions and reason.

Rollback restores the previous approved application/model/rule combination. Existing case snapshots and human decisions stay intact. A new analysis can be generated with the previous bundle; do not rewrite historical results to look as though the newer run never existed.

Destructive schema changes require a separately reviewed migration. For the prototype, favor additive fields and explicit versioned contracts.

## Recovery playbooks

| Failure | Expected response |
|---|---|
| Worker crash | Lease expires; resume/retry idempotent stage; preserve error history |
| Database unavailable | Readiness fails; stop writes; UI shows unavailable, not empty queue |
| Disk full | Fail artifact write; do not promote run; retain previous completed snapshot |
| Corrupt model artifact | Checksum failure; forecast unavailable; notify analyst |
| Optional rewrite timeout | Use deterministic brief |
| Incomplete dataset | Quarantine/partial coverage; human data reviewer decides next step |
| Concurrent case decisions | Reject stale version; require refresh and deliberate resubmission |
| Discovered bad rule | Human disables future use; annotate affected runs and initiate re-review |

## Backup and reproducibility

For a shared demo, back up PostgreSQL, manifests, approved bundles, case snapshots, decision audit records, and approved briefs. Generated raw data may be reproducible from seeds, but human decisions and notes are not. Test a restore rather than merely checking that a backup file exists.

A reproducibility bundle contains generator seed/config/version, source hashes, code revision, dependency lock hashes, feature/model/rule/policy versions, and analysis cutoff. Human decisions are reproduced as historical records, not rerun through an algorithm.

## Scale checkpoint

Before supporting a million-line fixture, measure canonicalization, feature aggregation, graph projection, scoring, and query time separately. Optimize the bottleneck: indexes/materialized aggregates, chunked Parquet scans, incremental updates, and graph filtering are likely earlier steps than new distributed services.

Do not promise million-claim real-time performance based on a small demonstration. Publish the measured throughput and distinguish batch preparation time from interactive queue latency.
