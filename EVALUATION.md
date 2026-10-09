# SpotZⁱ — Evaluation (synthetic data only)

SpotZⁱ uses **only its own synthetic data**. No real, public or third-party dataset is used anywhere.

The generator (`spotzi/synthdata/gen.py`) is built to resemble real payer claims:
- **Members:**
  - a realistic age and plan mix;
  - age-graded chronic conditions;
  - heavy-tailed care use;
  - mid-period enrolment.
- **Diagnoses and timing:**
  - diagnoses that fit each service;
  - a winter respiratory season.
- **Claim mechanics:**
  - refill and repeat spacing like payer edits;
  - copays, coinsurance and mark-ups;
  - realistic payment lags and late claims;
  - modifiers;
  - ~1.5% missing data;
  - format-valid NPIs;
  - clinician capacity limits;
  - non-overlapping appointments.
- **Fraud and context:**
  - 9 fraud schemes plus an excluded provider;
  - decoys;
  - 4 legitimate anomalies with observable business events;
  - an adversarial upcoder that has a genuine event.

Hidden ground truth exists at claim, provider, timing and ring level. It is used **only** by the evaluation engine.

**Worlds:**
- **Training:** seeds 101–106.
- **Testing:** the demo world (seed 7) plus held-out worlds 201 and 202, which are never used in training.
- **Reproduce:**
  - `python3 -m ai.models.train_all`
  - `python3 -m evaluation.engine` (results in `spotzi/data/evaluation/engine.json`, summarised in Governance → Model validation)

## Detection on every world
| | Demo (7) | Held-out 201 | Held-out 202 |
|---|---|---|---|
| Fraudulent providers caught | **16 / 16** | **16 / 16** | **16 / 16** |
| Legitimate providers escalated (of 109) | **0** | **0** | **0** |
| Legitimate anomalies escalated (of 4) | **0** | **0** | **0** |
| Decoys escalated (of 3) | **0** | **0** | **0** |
| SIU queue precision @10 | 100% | 100% | 100% |
| Calibrated p_fraud: ECE / Brier | 0.015 / 0.017 | 0.015 / 0.026 | 0.014 / 0.016 |
| Rings: every member caught, together in one case | 4 / 4 | 4 / 4 | 4 / 4 |

All 8 fraud types are caught on every world:
- duplicate
- upcoding
- unbundling
- phantom
- impossible timing
- excessive services
- recruitment
- excluded provider

**Capacity tiers** (calibrated probability, held-out worlds):

| Tier | Precision | Recall |
|---|---|---|
| Critical (top 1%) | 100% | 6% |
| High (top 5%) | 100% | 44% |
| Review (top 15%) | 75% | 94% |

## Model validation
**Counterfactual tests** (change one thing, check the score moves the right way): **79 / 79 pass.**
- Removing a scheme's lines lowers risk.
- Duplicates raise it.
- Reverting upcoding lowers it.
- A fake business event never hides fraud.
- Removing a legitimate event re-escalates the case.
- Cutting network links lowers the graph score.
- Doubling a clean provider's volume leaves its score unchanged.

**Adversarial evasion:**

| Attack | Detected |
|---|---|
| Full scheme | 16 / 16 |
| Mimicry: upcode to level 4 instead of 5 | **2 / 2** |
| Split billing across a second identity (shared owner, address and bank) | **16 / 16** (merged by entity resolution) |
| Scheme intensity cut to 50% / 25% / 10% | 14 / 11 / 10 of 16 |

The last row is a sensitivity curve, not a pass/fail test: at 10% intensity, a scheme is only a handful of claims.

**Detection delay:** rolling as-of replays every ~2 months put the median at **~55 days** from scheme start to case, with an early-warning stage at ~50 days.

**Ablation of optional fusion detectors:** temporal is adopted.

| Variant | Caught (of 48, three worlds) | False leads | Mean AP |
|---|---|---|---|
| base | 48 | 0 | 0.952 |
| **+temporal** | 48 | 0 | **0.953** |
| +peer | 48 | 0 | 0.937 |
| +temporal+peer | 48 | 1 | 0.938 |

Every variant catches all 48 fraudulent providers; +temporal has no false leads and the highest mean AP, so it is adopted. Peer baselines feed consensus and confidence only, not the fusion.

**Data-quality robustness:** missing diagnoses, invalid codes and impossible dates were injected into 10 providers. In every case data quality dropped, confidence was never High, and innocent risk was never inflated. Invalid lines never raise fraud flags.

**Distribution shift:** out-of-distribution rate 4–5% against the training reference. The drift monitor reports stable or watch.

## Task models (held-out worlds)
| Model | Result |
|---|---|
| Pre-payment line risk | AUC 0.996–0.997. At the rules' flag budget: precision 0.96 vs 0.82, recall 0.85–0.88 vs 0.73–0.75 |
| Fraud-type classifier | **100%** on all three worlds (dominant-rule baseline 69–75%) |
| Case outcome | AUC 0.99–1.00 |
| Calibration | ECE 0.17 → 0.001–0.011 |
| Chart documentation | 100% on unseen clinician wording (keyword reviewer 38%) |
| Tip triage | 93% on unseen tip wording (v1 54%, keywords 20%) |

## What changed to reach this
**Generator realism**, which removed false patterns that real data does not have:
- clinician capacity limits;
- non-overlapping appointments;
- payer-like refill spacing;
- correct ground truth for scheme lines during hospital stays or after death;
- ring members with few lines labelled correctly.

**Detection:**
- Rate-based rule evidence (Wilson lower bound), so growth alone is not suspicious.
- A statistical visit-level-shift test against mimicry.
- Cross-pharmacy duplicate-therapy checks ("pharmacy shopping").
- Entity resolution of identities that share owner, address and bank.
- Owned co-subjects are joined into one case.
- Business events cannot excuse a per-patient intensity change they could not cause.
- Data errors cannot create fraud flags or suspicion.
- Context-explained specialty patterns go to "Validate context first".

## Limits
All results are on synthetic worlds from one generator family. Real claims will differ. The drift and out-of-distribution monitors exist to show where they differ, and the models must then be recalibrated on real outcomes.
