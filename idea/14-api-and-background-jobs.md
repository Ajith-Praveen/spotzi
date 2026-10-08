# 14 — API contracts and background jobs

## Conventions

Prefix endpoints with `/api/v1`. Infer tenant and actor from authentication; never trust a caller-supplied role or tenant ID. Reads return the dataset/run/case version they represent. Use cursor pagination, stable ordering, ISO UTC timestamps, integer cents, and explicit enums.

Job submissions return `202 Accepted` with `job_id` and a status URL. Mutating requests accept `Idempotency-Key`; repeating a key with a different body returns conflict. Case changes use `If-Match` with the case version to prevent lost updates.

## Endpoint map

| Method and path | Purpose | Permission/semantics |
|---|---|---|
| `GET /health/live` | Process alive | No dataset details |
| `GET /health/ready` | Required dependencies and migrations ready | Minimal status |
| `POST /datasets/demo` | Generate a seeded synthetic dataset | Analyst, async |
| `POST /datasets/imports` | Upload an allowed synthetic bundle | Analyst, validated/quarantined |
| `GET /datasets/{id}/validation` | Validation report and detector coverage | Tenant reader |
| `POST /datasets/{id}/approve` | Human accepts validated dataset for analysis | Data reviewer |
| `POST /analysis-runs` | Start a versioned analysis | Analyst, async |
| `GET /analysis-runs/{id}` | Stages, warnings, versions, outputs | Tenant reader |
| `GET /jobs/{id}` | Job progress and retry state | Authorized owner/team |
| `POST /jobs/{id}/retry` | Retry a failed eligible stage | Analyst, bounded retries |
| `GET /cases` | Ranked candidate/investigation queue | Investigator/manager |
| `GET /cases/{id}` | Current or explicit historical snapshot | Authorized reader |
| `GET /cases/{id}/evidence` | Evidence, source fields, exceptions | Authorized reader |
| `GET /claims/{id}` | Transaction history and canonical lines | Authorized reader |
| `GET /cases/{id}/timeline` | Dated source and human-review events | Authorized reader |
| `GET /cases/{id}/precedents` | Explainable similar-case retrieval and material differences | Authorized investigator |
| `POST /cases/{id}/review-blueprints` | Human creates a checklist from selected precedents | Investigator |
| `PATCH /review-blueprints/{id}/items/{item}` | Human edits or completes a sourced review step | Blueprint owner/team |
| `GET /cases/{id}/graph` | Bounded graph with provenance | Authorized reader |
| `GET /providers/{id}/forecasts` | Target/horizon results or abstention | Authorized reader |
| `POST /cases/{id}/scope-proposals` | Propose merge, split, or scope change | Investigator |
| `POST /cases/{id}/scope-decisions` | Human accepts/rejects scope proposal | Case owner/manager |
| `POST /cases/{id}/assignments` | Human assignment | Manager, optimistic concurrency |
| `POST /cases/{id}/notes` | Add a referenced note | Investigator, versioned |
| `POST /cases/{id}/decision-proposals` | Reviewer proposes disposition | Assigned investigator |
| `POST /cases/{id}/decision-approvals` | Human approves/rejects proposal | Authorized approver |
| `POST /cases/{id}/reopen` | Human reopens with reason | Authorized investigator/manager |
| `POST /capacity-plans/preview` | Compute assignment recommendation | Manager, no assignment side effects |
| `POST /capacity-plans/{id}/apply` | Human applies reviewed assignments | Manager, conflict checks |
| `POST /cases/{id}/briefs` | Generate a draft evidence-based brief | Investigator, async if needed |
| `POST /briefs/{id}/approve` | Human approves final brief | Authorized reviewer |
| `GET /briefs/{id}/export` | Download authorized version | Export permission, audit |
| `GET /governance/models` | Model cards and approval status | Analyst/auditor |
| `GET /audit-events` | Search scoped decision history | Auditor/manager |

There are no payment-denial, member-contact, provider-sanction, or automatic external-referral endpoints. A system service account cannot call human decision endpoints.

There is no endpoint that copies a precedent outcome to the current case. Precedent retrieval is contextual and read-only; blueprint creation requires a human action and records the selected sources.

## Start an analysis

```json
{
  "dataset_id": "SYN-DEMO-001",
  "as_of": "2025-08-31T23:59:59Z",
  "ruleset_version": "rules-1.0",
  "model_bundle_version": "bundle-1.0-approved",
  "priority_policy_version": "siu-1.0",
  "forecast_horizons_days": [30, 60, 90]
}
```

Reject future cutoffs beyond the dataset's known availability boundary, unapproved datasets/models, unsupported schema versions, and incompatible feature/model versions. A rules-only run can be explicitly requested, but the resulting forecast status is unavailable.

## Case response shape

```json
{
  "case_id": "SYN-CASE-0042",
  "case_version": 3,
  "run_id": "RUN-SYN-001",
  "status": "candidate",
  "decision_status": "pending_human_review",
  "recommendation": {
    "priority_score": 82.1,
    "policy_version": "siu-1.0",
    "risk_index_0_100": 84.5,
    "risk_is_probability": false
  },
  "exposure": {
    "currency": "USD",
    "gross_implicated_paid_cents": 1248000,
    "potential_excess_cents": 60000,
    "potential_excess_scope": "duplicate subset only",
    "confirmed_recovery_cents": null
  },
  "human_decision": null,
  "coverage_status": "partial",
  "limitations": ["Some services lack precise timestamps"],
  "links": {"evidence": "/api/v1/cases/SYN-CASE-0042/evidence"}
}
```

Values above are illustrative, not computed results. The implemented response includes component breakdowns, supported detector coverage, data/model timestamps, and endpoint-specific forecasts.

## Human decision request

```json
{
  "proposal_id": "PROP-SYN-009",
  "action": "approve",
  "outcome": "inconclusive",
  "reason": "Billing overlap remains unresolved without distinct-service records.",
  "evidence_ids": ["EV-SYN-101"],
  "reviewed_case_version": 3
}
```

The server supplies actor and decision timestamp, checks the approver role and separation-of-duties policy, validates evidence ownership, and atomically records state transition and audit event. A model-generated proposal cannot contain a forged human actor.

## Errors

Return `{error: {code, message, details, request_id}}`. Use stable codes such as `SYNTHETIC_PROVENANCE_REQUIRED`, `DATASET_NOT_APPROVED`, `MODEL_FEATURE_MISMATCH`, `HORIZON_UNSUPPORTED`, `CASE_VERSION_CONFLICT`, `HUMAN_APPROVAL_REQUIRED`, and `TENANT_ACCESS_DENIED`. Forecast ineligibility is a normal result with reasons, not necessarily an HTTP failure.

## Durable jobs

Job states: queued → running → succeeded/failed/cancelled. Stages: validate, canonicalize, features, detectors, graph, forecasts, cases, briefs. A worker acquires a lease transactionally, heartbeats, and records attempt-level errors. Expired leases are recoverable with bounded retry.

Use idempotent stage keys based on run, stage, and input hash. Output artifacts are written to temporary locations, validated, then promoted with a manifest. Do not expose partially written Parquet or models. External model rewriting has timeout and fallback; it cannot hold a database transaction open.

For PostgreSQL queue claiming, use transactionally safe locking such as `FOR UPDATE SKIP LOCKED` with a tested lease protocol. Avoid executing the same job concurrently under two valid leases. All human workflow changes stay in the API/service transaction path; workers cannot approve decisions.
