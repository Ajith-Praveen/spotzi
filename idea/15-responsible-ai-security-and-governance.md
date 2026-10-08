# 15 — Responsible AI, security, and governance

## Mandatory operating model

The prototype uses **synthetic data exclusively**. It is **human-decided**: analytics propose findings, candidate scopes, priorities, forecasts, and draft language; authorized people make final investigation and action decisions. These requirements are enforced in data contracts, permissions, state transitions, and acceptance tests, not only in disclaimers.

Public sources in document 19 support technical design. They do not authorize importing real public provider or patient records. No production connector belongs in the prototype.

## Synthetic-only controls

- Default the demo to generator-created bundles with recorded generator version, configuration, seed, and file hashes.
- For optional imports, require declared synthetic provenance and known schemas. Reject unsupported identity/free-text fields and unrecognized source formats.
- Require a human data reviewer to approve an imported bundle before scoring.
- Do not claim a content scanner can prove that data is synthetic. Hosted evaluation can disable arbitrary upload entirely and accept only packaged generated fixtures.
- Use fictional provider/member IDs and locations. Do not use real NPIs, account numbers, employee identities, or patient data.
- Separate hidden simulation truth from serving files and mounts. Do not leak scenario identity through UI metadata or IDs.
- Keep all exported reports visibly marked synthetic and restrict exports to authorized users.

## Human decision boundaries

| Action | System may do | Human must do |
|---|---|---|
| Validate input | Compute quality report, quarantine invalid rows | Approve dataset for use |
| Detect patterns | Produce evidence-linked findings | Decide whether evidence warrants investigation |
| Group cases | Propose related scope | Accept, merge, split, or dismiss scope |
| Prioritize | Compute transparent recommendations | Approve priority overrides and assignments |
| Forecast | Estimate defined synthetic event probabilities | Decide how prediction affects review |
| Brief | Produce a cited draft | Approve the final report and outcome |
| Escalate | Recommend additional review | Approve simulated escalation; external actions remain absent |
| Learn | Prepare candidate training/evaluation artifacts | Approve labels, model release, and policy changes |
| Use precedents | Retrieve similar approved cases and suggest review steps | Decide relevance, acknowledge differences, and judge the current case |

See document 20 for the implementable review mechanism.

## Uncertainty and safe failure

Represent source completeness, detector support, relationship confidence, model calibration, and reviewer certainty separately. Avoid one ambiguous “confidence: 95%” badge.

Unknown evidence is not exculpatory or incriminating. Missing service times disable timing checks. Sparse peers disable or broaden comparisons visibly. Out-of-domain forecasts are unavailable. Model errors do not turn cases low risk. A complete rule run does not prove all FWA types were assessed.

Versioned rules can disagree with anomaly models. Preserve disagreement in the brief and let reviewers inspect it; do not hide it by averaging signals into a single unexplained score. Reviewers can record a model error or plausible exception without deleting source evidence.

## Fairness and inappropriate inference

Use appropriate service-family, specialty, setting, and complexity comparators. High need, high cost, remote geography, or connectedness alone must not establish suspicious conduct. Do not infer member culpability from care utilization or network membership.

Evaluate false positives, abstention, and workload distribution across synthetic provider types, low-volume cohorts, geography, and supported demographic test slices. Small samples require uncertainty disclosure. A fairness result on generated data cannot establish fairness in an actual payer population.

Keep demographic evaluation fields separate from the serving feature allowlist. If a contextual variable is used, document its purpose, proxy risks, and ablation behavior.

Precedent retrieval creates anchoring and automation-bias risks. Show material differences before historical outcomes, include opposite-outcome matched cases, permit “no safe precedent,” and evaluate whether reviewers copy prior conclusions despite contradictory current evidence. Precedents improve review structure; they do not create policy or determine intent.

## Security architecture

Use tenant-scoped authorization in every repository query and download path. For a shared deployment, use established authentication with server-side role mapping, HTTPS, secure sessions, CSRF protection where relevant, and restrictive CORS. Local demo identities are explicitly fictional; do not present a role dropdown as production security.

Roles: analyst, data reviewer, investigator, SIU manager/approver, model reviewer, auditor. Service identities can generate artifacts but cannot impersonate reviewers. Enforce case-level access where teams differ. Scope graph traversals and evidence lookups to the tenant, not just the top-level case endpoint.

Validate upload paths, file sizes, schemas, and compressed-file expansion limits. Never load user-uploaded pickle/joblib artifacts. Prevent spreadsheet formula injection in CSV exports. Sanitize rendered Markdown/HTML and treat notes/source text as untrusted content.

Keep secrets outside Git and source manifests. Logs contain IDs and operational counts, not entire claim rows, free text, credentials, or authentication tokens. Even synthetic data should exercise production-shaped access and audit controls.

## Audit and retention

Record actor, role, action, object/version, reason, evidence references, request ID, and timestamp. Human decisions preserve the original recommendation and case snapshot. Append-only application behavior and restrictive database permissions provide an audit trail; they are not the same as a legally immutable archive. A future production system would need a separately reviewed retention and tamper-evidence design.

Define a configurable demo retention period and deletion workflow covering database records, artifacts, backups, and exports. A deleted dataset invalidates active links with an explicit status; do not fabricate historical evidence to keep reports readable.

## Governance checkpoints

Maintain dataset cards, model cards, rule-change records, policy approvals, and decision records. Review intended use, known limitations, drift, override trends, and failure modes before promotion. NIST AI RMF is a useful organizing reference for risk governance; this blueprint is not a certification or a claim of regulatory compliance. [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework).

The first release should be demonstrably safe under missing data, failed models, malicious notes, stale case versions, and unauthorized decision attempts. Any future real-data deployment is outside this prototype and requires a separate domain, privacy, security, and legal review.
