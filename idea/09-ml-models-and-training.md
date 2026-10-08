# 09 — ML models and training strategy

## Use a small complementary model set

| Component | First implementation | Purpose | Output semantics |
|---|---|---|---|
| Known-pattern detection | Versioned rules | Specific, inspectable billing conditions | Finding with evidence, not probability |
| Unusual behavior | Isolation Forest | Multivariate provider outliers | Anomaly score and reference percentile |
| Network intelligence | Typed graph features and motifs | Relationships and coordinated patterns | Supported structural indicators |
| Future events | Pooled logistic hazard baseline, then XGBoost hazard challenger | Repeat and escalation within 30/60/90 days | Calibrated cumulative probability for defined target |

These already exceed the requirement for two complementary approaches. A separate supervised current-fraud classifier is optional later work; it is not necessary for the prototype. Avoid adding deep learning, GNNs, autoencoders, or an LLM classifier just to increase the model count.

## Isolation Forest design

Score provider/family snapshots, using approximately 15–30 reviewed features from document 08. Start with interpretable aggregates: utilization rates, coding mix, payment-per-unit deviations, repeat-service share, concentration, growth, and coverage. Exclude raw IDs and hidden truth.

Isolation Forest isolates unusual observations through random partitions. Its scores are outlier measures, not fraud probabilities. In scikit-learn, lower `score_samples` values indicate more anomalous observations; preserve and test the chosen direction. [Isolation Forest API](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html).

Proposed initial configuration, to validate rather than copy unquestioningly:

```yaml
n_estimators: 300
max_samples: 256
max_features: 1.0
contamination: auto
random_state: 42
```

Fit on the training-period reference distribution without using hidden labels to remove every suspicious example. Normalize features within supported family/peer contexts or train family-specific models with sufficient sample size. A very small family gets a pooled, explicitly broader model or an unsupported status.

Define `raw_anomaly = -score_samples(X)`. Fit a frozen empirical reference distribution on a held-out permitted reference sample and map raw scores to percentiles. A 99th percentile anomaly means unusual relative to that reference, not 99% likely fraud. Choose alert thresholds through validation and review capacity, not by treating `contamination` as known FWA prevalence.

Explain anomaly results using actual feature values, peer comparisons, and matched reference examples. Those deviations are contextual explanations, not exact attributions of Isolation Forest output. Do not label them SHAP contributions unless a compatible attribution method is separately implemented and tested.

## Forecast baseline and challenger

Create provider-anchor-period rows for each target as detailed in document 10. A logistic model with interval indicators is the baseline. It is cheap to train, inspectable, and establishes whether nonlinear models add value.

Use XGBoost as a challenger when there are enough independent positive events. Candidate settings:

```yaml
objective: binary:logistic
eval_metric: logloss
tree_method: hist
max_depth: 3
learning_rate: 0.05
n_estimators_max: 600
min_child_weight: 10
subsample: 0.8
colsample_bytree: 0.8
reg_lambda: 5.0
```

These are proposed search starting points. Tune a small budget of configurations with early stopping on temporal validation data; freeze the configuration before final testing. Exact API placement of early-stopping options depends on the pinned library version. XGBoost documents the binary logistic objective and tree regularization parameters. [XGBoost parameters](https://xgboost.readthedocs.io/en/stable/parameter.html).

Prefer natural class prevalence for probability estimation. If training uses class weights or sampled negatives, retain sampling metadata and recalibrate on representative, unweighted observations. Do not interpret a weighted classifier's raw output as a calibrated probability. Avoid SMOTE across temporally related provider observations.

## Training pipeline

1. Freeze generator version, seeds, label definitions, feature schema, cutoff logic, and split manifest.
2. Build labels using evaluation-only truth or matured simulated human outcomes, according to the declared experiment. Never mix the two silently.
3. Split chronologically with purge gaps for the 90-day target and label delay; add an entity/network-disjoint test.
4. Fit transforms and models on training only. Tune on validation only.
5. Calibrate on a separate later calibration partition with natural prevalence.
6. Evaluate the frozen bundle once on the reserved test partition and unseen scenario variants.
7. Publish metrics, denominators, confidence estimates where supported, and failure slices.
8. A human model owner reviews the report and approves or rejects promotion.

Calibration estimates whether probabilities align with observed outcomes; fit it on observations not used to fit the underlying estimator. Start with sigmoid calibration when support is modest; consider isotonic only with sufficient representative data. Measure reliability by horizon, not just one aggregate score. [scikit-learn calibration guide](https://scikit-learn.org/stable/modules/calibration.html).

## Explanations and model artifacts

For the tree challenger, TreeExplainer can explain supported tree-model outputs. Report the exact explained scale and background population. Contributions on raw log-odds are not percentage-point contributions to cumulative 90-day probability. The calibrator and cumulative hazard transformation add stages that a raw tree explanation does not automatically explain. [SHAP TreeExplainer](https://shap.readthedocs.io/en/latest/generated/shap.TreeExplainer.html).

Use feature/peer evidence alongside SHAP; feature attribution is not causation or proof. For the logistic baseline, show transformed-feature contributions and document the same calibration limitation.

Each bundle contains model artifact, preprocessing artifact, calibration artifact, feature schema, label specification, reference distributions, training manifest, evaluation report, model card, dependency lock hash, artifact checksums, and human approval metadata. Store XGBoost models in its supported structured format; load serialized Python estimators only from a trusted internal build pipeline, never user uploads.

## Release gates and fallbacks

Do not promote a challenger simply because its ROC-AUC is high. Require better or comparable precision at capacity, rare-event ranking, calibration, stable family slices, and no regression on important benign controls. Thresholds and tolerances are set before test evaluation.

If event counts are inadequate, keep the logistic baseline only if it passes its gates; otherwise show forecasts unavailable. Rules and graph evidence still support human review. Neither a heuristic weighted score nor an LLM-generated number may fill the probability field.

All performance statements are explicitly synthetic-only. Human decisions remain independent of model output, and no model promotion automatically changes investigation policy without a reviewed policy version.
