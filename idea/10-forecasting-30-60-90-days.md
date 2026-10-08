# 10 — Forecasting repeat and escalating activity

## Define the target before choosing the model

Forecast at **provider × observation cutoff** first. Case pages display the primary provider's forecast, labeled as such. They do not average provider probabilities into a network probability: connected providers are dependent. A separate network model can be added only with a defined network cohort and evaluation.

The product predicts future qualifying events in the synthetic simulation, not legal guilt. A future human confirmation can be a later experimental endpoint, but confirmation also reflects investigation selection and delay.

## Two separate endpoints

**Repeat event:** a new synthetic suspicious episode begins after cutoff, following a previous episode known through an available simulated investigation outcome or a human-accepted qualifying pattern. Use a configurable 14-day episode separation/washout to avoid counting continuing claim fragments as recurrence. Those without known prior history are ineligible for the “repeat” endpoint; show “no qualifying prior history,” not zero probability.

**Escalation event:** an ongoing or new synthetic suspicious episode crosses a predeclared severity threshold after cutoff. Example simulation definition: at least five newly affected members and rolling 30-day incident-attributable paid exposure exceeding both $5,000 and twice the anchor-period incident-attributable exposure. Require that the threshold is not already crossed at the anchor. These are synthetic label-design choices, not clinical or payer standards.

Escalation can occur within a continuing episode without a new repeat episode. Therefore the two endpoints are not nested, their probabilities need not be ordered against each other, and they must not be added. Within each endpoint, cumulative 30/60/90-day probabilities must be monotone.

Hidden incident-attributable amounts are used only to create evaluation labels. Serving eligibility uses observable history and record coverage, never future or hidden truth. Keep the truth-based endpoint and a future human-adjudicated endpoint as different `target_version` values.

## Prediction interface

```text
Input:
  provider_id, as_of, dataset_version, feature_snapshot,
  known_prior_history, observation_coverage, model_version

Output per endpoint:
  target_version, eligibility_status, unavailable_reasons,
  p_30, p_60, p_90, model_version, calibration_version,
  evidence_refs, coverage_summary, validation_domain="synthetic"
```

For eligible cases, all horizons are generated from the same frozen cutoff and feature vector. Selecting a horizon changes the displayed cumulative window; it does not secretly change the historical evidence.

## Discrete-time hazard model

Divide the next 90 days into intervals `(0,30]`, `(30,60]`, and `(60,90]`. For each target, estimate:

```text
h_k(x) = P(first target event in interval k | no earlier target event, x at cutoff)

P_30 = h_1
P_60 = 1 - (1-h_1)(1-h_2)
P_90 = 1 - (1-h_1)(1-h_2)(1-h_3)
```

With hazards in `[0,1]`, cumulative probabilities satisfy `P_30 <= P_60 <= P_90`. This avoids three unrelated classifiers producing contradictory horizon values.

Expand each training anchor into one row per observed at-risk interval. An interval label is 1 only for the first event; later intervals after an event are omitted. The interval index is an input. **All other covariates stay frozen at the anchor**, because future covariates are unavailable during prediction.

Train a pooled logistic hazard model with interval indicators. A tree-based pooled hazard model is the challenger. Calibrate hazards using the separate calibration rows, with interval-specific calibrators only if support permits. Compute cumulative probabilities afterward and assess cumulative calibration at every horizon; calibrated conditional hazards do not remove the need for that check.

Illustration only: hazards 0.20, 0.25, and 0.30 produce cumulative risks 0.20, 0.40, and 0.58. These are arithmetic examples, not model results.

## Right censoring and label delay

A negative requires observation through the end of its interval and the configured label-maturation allowance. If the dataset ends at day 45, the first 30-day interval may be usable while later event-free intervals are censored. Do not call them negative. If an event is observed before censoring, include its observed event interval and remove subsequent intervals.

For the simplest validated baseline, use anchors with complete 90-day follow-up plus a 30-day simulated label delay. Later expand to interval-level censoring with explicit assumptions. Disenrollment, provider exit, missing feeds, and incomplete claim runout can censor observations. If censoring is informative, complete-case performance can be biased; report exclusions and do not imply that the issue is solved by dropping rows.

Synthetic truth has a known event time, but replay validation should still respect the intended claim-arrival and investigation-delay model. For a future human-confirmation endpoint, distinguish service-event time from confirmation time and label availability.

## Temporal split example

For a 730-day generated period, one conservative plan with a 90-day horizon and 30-day maturation delay is:

| Partition | Anchor days | Last possible label availability |
|---|---|---|
| Training | 91–180 | 300 |
| Tuning validation | 301–330 | 450 |
| Calibration | 451–480 | 600 |
| Final test | 601–610 | 730 |

Use weekly anchors or one sampled anchor per provider/phase to reduce dependence. Small partitions may lack positives; enlarge the synthetic population or duration instead of shrinking gaps until leakage appears. Also reserve entire provider/ownership groups for a cold-entity test. A built-in time splitter alone does not enforce group isolation or label-availability purging.

## Forecast validation and display

Report endpoint prevalence, positive event counts, exclusions, PR-AUC, Brier score, reliability plots, and precision/recall at review capacity for each horizon. Cluster bootstrap by provider or generating network for uncertainty; do not treat correlated weekly snapshots as independent samples.

Abstain for incompatible feature versions, unsupported family mix, inadequate history, unavailable calibration, or severe out-of-distribution inputs. The model card defines thresholds before testing. UI explanation: target, eligibility, cutoff, horizon, data coverage, leading contextual factors, and synthetic-only validation. Optional bootstrap model ranges must be labeled model variability, not a guarantee for an individual case.

A forecast contributes to a review recommendation. A person decides whether it changes the investigation plan, and records that decision separately.
