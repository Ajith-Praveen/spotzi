# 22 — Precedent Intelligence for faster claim judgment

## Product purpose

SpotZⁱ should help an investigator answer a new question quickly:

**“Which previously reviewed cases are materially similar, how are they different, and what reasoning can I reuse?”**

The feature is called **Precedent Intelligence**. It retrieves comparable historical human-reviewed cases, highlights matching evidence and critical differences, and produces a reusable review blueprint. The current investigator still examines the current evidence and owns the decision.

This is decision support rather than an automatic judgment engine. A prior outcome does not bind the current case, and the system must never copy an old disposition into the current decision form.

## Investigator experience

The case workspace gains a **Precedents** tab. It contains:

1. A concise pattern fingerprint for the current case.
2. The three to five most comparable closed or mature cases.
3. A side-by-side comparison of matching and differing facts.
4. Reusable evidence checks and review steps from those cases.
5. The previous human reasoning, limitations, and outcome.
6. A “Create review blueprint” action that builds an editable checklist.

Example:

```text
Current case: repeated laboratory panels + concentrated referrals

Closest precedent: SYN-CASE-0148                         87% retrieval similarity
Matched: service family, repeat interval, peer deviation, referral pattern
Different: current ownership link is unverified; precedent link was verified
Prior human outcome: legitimate explanation for 18 lines; 9 lines escalated
Reusable checks: specimen reconciliation, reversal check, ownership verification
Warning: prior outcome cannot be applied automatically
```

Display **retrieval similarity**, not “probability of fraud” or “decision confidence.” Similarity only means the configured case characteristics resemble one another.

## What becomes a precedent

A case becomes eligible only after a human decision and a quality review. Store a frozen precedent snapshot containing:

- case type, service family, provider specialty, and investigation window;
- normalized rule, anomaly, temporal, graph, and forecast features;
- evidence coverage, exceptions, and unresolved limitations;
- evidence checks performed and their observed results;
- included claim-line and relationship fingerprints without direct identifiers;
- human decision, rationale, reviewed evidence IDs, role, and approval chain;
- final review quality status and precedent version.

Exclude drafts, overturned decisions, incomplete approvals, low-quality rationales, and cases later marked unreliable. Reopening or amending a source case creates a new precedent version and retires the prior one from default retrieval without deleting its audit history.

Synthetic generator truth is never presented as human precedent. In the prototype, seed historical synthetic cases with simulated human reviews that are clearly labeled. Live demo decisions enter a candidate precedent pool only after an explicit human quality-review step.

## Retrieval pipeline

Use a two-stage retrieval process.

### Stage 1 — eligibility and structured filtering

Filter by tenant, service family, applicable policy/ruleset era, evidence maturity, supported provider setting, and precedent status. Apply temporal validity so a future policy or decision cannot influence a historical replay.

### Stage 2 — similarity ranking

Begin with a transparent weighted distance over structured features:

```text
similarity = 0.25 pattern overlap
           + 0.20 service and provider context
           + 0.15 evidence coverage
           + 0.15 temporal shape
           + 0.15 graph motif similarity
           + 0.10 financial/member-impact band
```

Weights are proposed starting values and require human review and evaluation. Missing components remain missing; do not silently assign zero. Candidates with incompatible core context are excluded rather than rescued by a high score elsewhere.

Use PostgreSQL for the structured baseline. Store normalized precedent features in typed columns and JSONB where detector-specific fields vary. `pgvector` can be added later for reviewed narrative or pattern embeddings after the structured retrieval is validated. Do not embed member/provider names, raw identifiers, or unrestricted notes.

The final score and every match explanation must identify which fields increased or decreased similarity. An LLM may summarize retrieved precedents but cannot choose candidates, fabricate comparisons, or infer the current outcome.

## Difference-first comparison

The value comes from differences as much as matches. Highlight material mismatches before the prior outcome:

| Comparison area | Current case | Precedent | Review impact |
|---|---|---|---|
| Specimen coverage | 82% | 100% | Current case cannot support the same missing-record inference |
| Ownership | Asserted | Verified | Current network evidence is weaker |
| Reversal status | Pending | Reconciled | Duplicate exposure remains provisional |
| Provider setting | Independent lab | Hospital lab | Peer behavior may not transfer |

A precedent with a high similarity score but a material contradiction remains visible with an explicit warning. It must not be presented as a recommended disposition.

## Review blueprint

The investigator may generate an editable checklist from multiple precedents:

- required claim-line and payment reconciliation;
- likely legitimate explanations to test;
- evidence requests that resolved similar ambiguity;
- policy/ruleset references valid for the current cutoff;
- network relationships needing verification;
- conditions that should keep the result inconclusive;
- final human decision and approval steps.

Every checklist item records its precedent source. The investigator can accept, remove, reorder, or add items with a reason. Completion speeds the review but does not preselect an outcome.

The Evidence Challenge Lab and Precedent Intelligence reinforce each other: precedents suggest useful evidence checks; the challenge workflow tests those checks against the current case. Only current-case evidence supports the current decision.

## Data model

Add these PostgreSQL tables:

| Table | Purpose |
|---|---|
| `precedent_snapshots` | Frozen, versioned, quality-approved historical case representation |
| `precedent_features` | Structured normalized retrieval features and missingness |
| `precedent_decisions` | Human outcome/rationale references and approval metadata |
| `precedent_retrieval_runs` | Current case/version, policy version, candidate pool, ranked results |
| `precedent_matches` | Per-candidate score, matches, differences, warnings |
| `review_blueprints` | Human-created checklist for the current case |
| `review_blueprint_items` | Item source, state, investigator edits, evidence references |
| `precedent_quality_reviews` | Approve, retire, or restrict a precedent with reason |

Do not update a frozen retrieval result when the source precedent changes. New retrieval creates a new version so the investigator's original context can be reconstructed.

## API surface

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/cases/{id}/precedents` | Retrieve ranked, explainable matches for a case version |
| `GET /api/v1/precedents/{id}` | Read the authorized frozen precedent snapshot |
| `POST /api/v1/cases/{id}/review-blueprints` | Human creates an editable blueprint from selected precedents |
| `PATCH /api/v1/review-blueprints/{id}/items/{item}` | Record a human checklist edit or completion |
| `POST /api/v1/precedents/{id}/quality-reviews` | Human approves, retires, or restricts precedent use |
| `GET /api/v1/cases/{id}/precedent-replay` | Reconstruct retrieval and blueprint context used for a decision |

Retrieval is read-only. No endpoint applies a precedent outcome to another case.

## Proposed implementation files

```text
backend/src/spotzi/precedents/
  contracts.py
  eligibility.py
  fingerprint.py
  structured_similarity.py
  differences.py
  retrieval.py
  quality_review.py
  blueprint_builder.py
  replay.py
backend/src/spotzi/api/routers/precedents.py
backend/src/spotzi/db/models/precedents.py
backend/migrations/versions/0006_precedent_intelligence.py
frontend/src/features/precedents/PrecedentsTab.tsx
frontend/src/features/precedents/PrecedentComparison.tsx
frontend/src/features/precedents/ReviewBlueprint.tsx
configs/precedent_similarity.yaml
backend/tests/unit/test_precedent_eligibility.py
backend/tests/unit/test_material_differences.py
backend/tests/integration/test_precedent_to_blueprint.py
backend/tests/evaluation/test_precedent_retrieval.py
```

## Human-decision safeguards

- Never prefill the current outcome from a precedent.
- Show the current evidence before the historical outcome.
- Require the reviewer to acknowledge material differences before using a blueprint.
- Keep source-case provider/member identities minimized and access-controlled.
- Record which precedents were opened, ignored, or used.
- Allow “no safe precedent found” as a normal result.
- Flag circularity when a source decision relied on another precedent.
- Prevent a current decision from entering the precedent pool until quality review.
- Measure automation bias with seeded misleading precedents and independent review.

## Evaluation

Use held-out synthetic cases and reviewer studies. Compare review without precedents, structured precedents, and precedents plus the Evidence Challenge Lab.

Measure time to first useful evidence, total review minutes, checklist reuse, missed material differences, supported decision rate, inappropriate copying of prior outcomes, and reviewer agreement after independent evidence inspection. Include cases with no valid precedent and deliberately similar cases with opposite legitimate explanations.

Retrieval metrics include precision@K for scenario/context compatibility, material-difference recall, and coverage. High similarity retrieval alone is insufficient if investigators make worse decisions.

## Delivery sequence

1. Create frozen precedent snapshots from reviewed synthetic historical cases.
2. Implement structured eligibility, similarity, and difference explanations.
3. Add the Precedents tab and side-by-side comparison.
4. Add human-created review blueprints with source lineage.
5. Evaluate review speed and automation bias.
6. Add `pgvector` only if narrative retrieval improves measured results.

The initial release should support three scenario families: duplicates versus replacements, repeat laboratory services versus distinct specimens, and behavioral-health timing versus group sessions. A small reliable precedent library is more useful than a large noisy archive.
