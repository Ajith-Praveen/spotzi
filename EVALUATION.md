# SpotZⁱ — Accuracy evaluation on independent synthetic data

## Why this exists
We generated SpotZⁱ's own demo data and wrote its fraud scenarios alongside the rules, so its near-perfect scores prove little. To measure accuracy on data we did **not** create, we use two **fully synthetic** public datasets as the *background* (normal) claims. Neither contains real patients. We then inject known fraud schemes plus legitimate look-alikes and score the full, unchanged SpotZⁱ pipeline. No real or production data is used anywhere in SpotZⁱ.

## Method
1. **Import** synthetic claims unchanged:
   - **CMS DE-SynPUF Sample 1**: synthetic Medicare claims for 2008–2010, covering hospitals and outpatient facilities.
   - **Synthea sample**: synthetic clinicians, patients and organisations.
2. **Inject** labelled schemes into a few providers. Each scheme starts at a random month and continues to the end of the data.
   - `dup`: duplicate submissions.
   - `units`: unit inflation.
   - `repeat`: panels re-billed within days.
   - `upcode`: visits shifted to level 5.
   - `deceased`: services billed after the patient's death.
   - `influx`: patient recruitment. A wave of new out-of-area patients each receives one identical bundle. This was the held-out scheme until v1.1. The new patient-panel detector targets this typology, so it is no longer a blind test.
   - **`scope` (held out)**: the provider starts billing a costly service it has never billed, for its own existing patients. No rule or detector was designed for this scheme.
   - **Benign look-alikes**: legitimate growth, meaning new local patients with complete, realistic care episodes. These should *not* be escalated.
3. **Run** the full pipeline. Labels are used only for scoring and to train the forecast, never for detection.
4. **Score**:
   - Did each injected provider become a case?
   - How well does each detector rank bad providers (AUC)?
   - What is the precision of the SIU queue?
   - Were look-alikes escalated?
   - What is the forecast AUC on a later, purged time window?

## Results

We designed the detectors and thresholds using injection seeds 21 and 99. **The numbers below come from a fresh injection (seed 7) with different providers and onsets.** None of these numbers were used for tuning.

### CMS DE-SynPUF Sample 1
148,437 claim lines · 4,332 providers · 23 cases opened · seed 7

| Measure | Result |
|---|---|
| Injected bad providers opened as cases | **16 / 21** (16 / 18 excluding the held-out `scope`) |
| Legitimate look-alikes escalated (lower is better) | 1 / 4 |
| SIU queue precision @5 / @10 | 100% / 100% |
| Share of all opened cases that are injected schemes | 70% |
| Claim-line precision / recall | 0.14 / 0.25 |
| Forecast AUC 30 / 60 / 90 days | 0.96 / 0.96 / 0.96 |

| Detector | Ranking AUC |
|---|---|
| Rules | 0.90 |
| Isolation Forest | 0.99 |
| Case-mix twin | 0.67 |
| Care pathway | 0.69 |
| Change-point | 0.80 |
| Code mix | 0.99 |
| Patient panel (targets one typology only) | 0.67 |
| Nexus Brain | 0.99 |
| Combined risk | 0.99 |

| Scheme | Caught / injected | Median Brain rank |
|---|---|---|
| deceased | 3 / 3 | 3 |
| dup | 3 / 3 | 9 |
| influx | **3 / 3** | 13 |
| repeat | 2 / 3 | 6 |
| units | 2 / 3 | 77 |
| upcode | 3 / 3 | 23 |
| scope (held out) | 0 / 3 | 107 |

### Synthea sample
9,393 claim lines · 200 providers · 13 cases opened · seed 7

| Measure | Result |
|---|---|
| Injected bad providers opened as cases | **12 / 14** |
| Legitimate look-alikes escalated (lower is better) | not testable (dataset too thin) |
| SIU queue precision @5 / @10 | 100% / 100% |
| Share of all opened cases that are injected schemes | 92% |
| Claim-line precision / recall | 0.71 / 0.19 |
| Forecast AUC 30 / 60 / 90 days | 0.95 / 0.93 / 0.95 |

| Detector | Ranking AUC |
|---|---|
| Rules | 0.86 |
| Isolation Forest | 0.99 |
| Case-mix twin | 0.72 |
| Care pathway | 0.81 |
| Change-point | 0.90 |
| Code mix | 0.98 |
| Patient panel (targets one typology only) | 0.57 |
| Nexus Brain | 1.00 |
| Combined risk | 1.00 |

| Scheme | Caught / injected | Median Brain rank |
|---|---|---|
| deceased | 2 / 2 | 13 |
| dup | 2 / 2 | 13 |
| influx | **2 / 2** (was 0 / 2) | 4 |
| repeat | 1 / 2 | 9 |
| units | 2 / 2 | 9 |
| upcode | 2 / 2 | 2 |
| scope (held out) | 1 / 2 (caught via a unit-limit finding) | 9 |

## What this shows
- **Patient recruitment (influx) is now caught on both datasets** (Synthea 2/2, DE-SynPUF 3/3) by the new patient-panel detector, without loosening the 0.97 lead threshold.
- **The fused Nexus Brain ranks bad providers better than rules alone**: DE-SynPUF AUC 0.99 vs 0.90; Synthea 1.00 vs 0.86.
- **The top of the queue is reliable.** Precision @5 is 100% on both datasets, which matters most when investigator capacity is limited.

## Known weaknesses (measured, not hidden)
- **The held-out `scope` scheme is mostly missed.** It was caught 0/3 on DE-SynPUF (median rank 107 of 4,332) and 1/2 on Synthea. Learned detectors see the providers as somewhat unusual (fused score 0.90–0.94), but not enough to open a lead. A blind test exposed a real gap; a "new costly service line" view is the next detector to build.
- **One legitimate-growth facility was escalated on DE-SynPUF** (1/4). It was a Brain lead driven by Isolation Forest and code mix, not by the panel detector.
- **Claim-line recall is low** (~0.2). SpotZⁱ finds *providers worth reviewing*; it does not label every line.
- **Synthea is thin** (≈ one clinician per patient), so benign look-alikes cannot be tested there.

## Changes made because of this evaluation (general rules, not tuned to specific providers)
1. The duplicate rule treats the **later-paid** submission as the duplicate.
2. **Data-driven unit limits** (99th percentile per code) supplement the fixed limit table.
3. **Quarterly upcoding view**: flags providers with ≥ 8 visits in 90 days and a level-5 share ≥ max(50%, 3× peers).
4. **Concentrated-findings case trigger**: a provider whose recent billing is ≥ 40% flagged (at least 5 lines) is opened even at low volume.
5. **Brain leads need near-unanimous consensus** (fused score ≥ 0.97).
6. The change-point detector weighs **composition change** above raw growth.
7. Importers merge repeated codes on one claim into **units**.
8. **New: patient-panel shift detector** (v1.1), for the recruitment / patient-brokering typology. Among patients new to a provider in the review window, it measures:
   - how many received the provider's single most common service bundle;
   - how many have no other care anywhere in the plan;
   - how many come from outside the provider's usual catchment.

   Each measure is compared with **peer baselines**, not the provider's own history, so a scheme that began before the window cannot hide by contaminating its own baseline.

Evaluation-setup corrections (not product changes):
- Schemes are sized to be material (≥ 30 lines).
- Legitimate growth is built from complete patient episodes.
- Synthetic deaths are assigned only to patients with no later care.
- A new held-out scheme (`scope`) replaces `influx` as the blind test.

## Legitimate anomalies (look suspicious, are legitimate)
The demo world now contains four providers whose behaviour changes sharply for legitimate reasons. Each has an **observable** explanation in `provider_events.csv`, the kind of record payers hold in enrolment updates, credentialing rosters, contract registries and ownership disclosures:

| Provider | What happened | What it looks like |
|---|---|---|
| Brookside Family Practice | opened two new clinics | volume ~4×, many new patients |
| Valley Internal Medicine | a cardiologist joined | more level-4/5 visits + ECGs (the upcoding rule fires) |
| Evergreen House Calls | nursing-facility contract | wave of frail new patients, monthly visits |
| Summit Ridge Medical | acquired another practice | new-patient wave, volume jump |

There is also an **adversarial** case: a real upcoder (S4) that opened a genuine new location shortly before its scheme began.

| | Naive volume-spike alarm (any month ≥ 2× usual) | SpotZⁱ |
|---|---|---|
| Legitimate providers escalated | 3 / 4 | **0 / 4** (1 shown as "Explained by context", 3 never become cases) |
| Other innocent providers alarmed | 16 | — |
| Upcoder with a genuine event | not alarmed | **still escalated** (Investigate) |

**How it works** (`detection/context.py`):
- An event can explain only the signals it could cause, and only when they started after it. For example, new locations explain volume, panel and mix; a new clinician explains case mix and visit level.
- Billing-integrity findings are **never** explained by context: duplicates, services after death or during stays, impossible timing, unbundling, unit limits and exclusions.
- A case whose rule findings are not covered by the event keeps its lane.
- Context never closes a case. "Explained by context" cases are kept, down-ranked and visible, and a human decides.

The fraud results on the demo world are unchanged: 14 cases, precision@5 / @10 = 100% / 100%. The held-out recruitment mill is now opened through a patient-panel lead; it had fallen just below the 0.97 consensus threshold once peer baselines became noisier. DE-SynPUF and Synthea results are identical to before.

## Task models (trained per process) — held-out results
Trained by `spotzi/ai/models/train_all.py` (`python3 -m ai.models.train_all`).
- **Training data:** three generator worlds (seeds 101–103) plus DE-SynPUF patients disjoint from the evaluation patients, with schemes injected at a different seed.
- **Tests:** the demo world, the DE-SynPUF evaluation workspace, and Synthea. Synthea is never used in training.

**Pre-payment line-risk model**, compared with the rules at the rules' own flag budget:

| Test set | Rules precision / recall | Model precision / recall | Model AUC |
|---|---|---|---|
| Demo world | 0.80 / 0.70 | **0.90 / 0.78** | 0.99 |
| DE-SynPUF (disjoint patients) | 0.14 / 0.25 | **0.36 / 0.64** | 0.97 |
| Synthea (never trained on) | 0.71 / 0.19 | **0.82 / 0.22** | 0.91 |

**Case-outcome model** (provider substantiation):
- DE-SynPUF: AP 0.80 vs 0.57 for Nexus Brain; AUC 0.99 for both.
- Synthea: AP 1.00 vs 0.95.

**Chart-documentation model**:
- Notes in an unseen clinician wording: 100% correct vs 36% for a keyword reviewer.
- Familiar wording: both 100%.
- Caveat: synthetic notes share key clinical terms across wordings, so real charts would be harder.

**Tip-triage model**:
- Unseen templates and names: **94%** scheme accuracy (v1: 53%; keyword matching: 20%).
- v2 changes: a compositional training corpus (TF-IDF alone reaches 89%), plus a local sentence encoder (bge-small, frozen, runs offline) in an ensemble.
- Fine-tuning the encoder was also tried and gave no further gain, so it was not shipped.
- An urgency model was trained, failed its test (33%) and was **not shipped**.

**A failure we caught.** The first pre-payment model scored **AUC 0.3** on DE-SynPUF: it had learned the generator, not the fraud. We fixed it by removing generator-specific features (service-family flags, data-completeness artefacts) and adding real-format training patients.

## LLM chart review
`spotzi/evaluation/evaluate_llm.py` scores reviewers on 300 synthetic notes: half in the house wording, half in an unseen wording.
- **Keyword reviewer:** 99% / 64%.
- **Trained chart model:** 99% / 99%.
- **LLM reviewer:** pending until a DeepSeek / z.ai key is configured (Settings → AI & LLM, then `python3 -m evaluation.evaluate_llm --llm`).

## Limits of this evidence
All data is synthetic. Injected schemes are our own models of fraud. The results show SpotZⁱ detects *these* patterns against background data we did not generate; they are **not** real-world fraud detection rates. A payer's closed SIU outcomes would be the true test.

*Reproduce:* `cd spotzi && python3 -m evaluation.evaluate_public synthea synpuf` (seed 7 by default; results in `spotzi/data/evaluation/`).
