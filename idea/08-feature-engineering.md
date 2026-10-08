# 08 — Feature engineering and point-in-time computation

## Feature grains

Use three explicit grains: claim-line context, provider snapshot, and case/network snapshot. Forecasting starts at the provider snapshot grain. Members are contextual affected entities, not assigned personal “fraud propensity” scores.

All aggregations are parameterized by cutoff `t`, event window, and knowledge availability. Past features use event times before or at `t` and records available by `t`. Current-line comparisons explicitly state whether the line is excluded from its own comparator.

## Feature dictionary

| Feature | Grain/window | Definition | Missing-data rule |
|---|---|---|---|
| `paid_per_unit` | Claim | Net paid / valid positive units | Null if units invalid or payment absent |
| `peer_paid_unit_deviation` | Claim | Robust deviation from comparable procedure/setting peers | Broaden peer cohort or abstain |
| `duplicate_group_size` | Claim | Count of comparable independently active paid lines | Unsupported if core identity absent |
| `modifier_exception_present` | Claim | Supported exception marker for applicable pair | Unknown if field omitted |
| `rendering_overlap_minutes` | Claim pair | Positive overlap of eligible individual services | Null without reliable timestamps |
| `member_service_count_30d` | Member/procedure | Distinct canonical service episodes | Include enrollment-observation length |
| `member_provider_count_30d` | Member/family | Distinct rendering providers | Unknown for absent renderer |
| `units_per_episode_30d` | Provider/family | Total units / distinct episodes | Null for zero episodes |
| `high_intensity_share_30d` | Provider | High-intensity comparable services / eligible services | Require configured denominator |
| `duplicate_share_30d` | Provider | Distinct duplicate-implicated lines / eligible lines | Store detector coverage |
| `net_paid_growth_30d` | Provider | log1p(current positive paid) minus log1p(prior-window positive paid) | Flag incomplete windows |
| `service_count_growth_30d` | Provider | Current count relative to prior supported window | Shrink low-volume estimates |
| `repeat_member_share_30d` | Provider | Members with repeated comparable episodes / observed members | Keep denominator |
| `referral_concentration_90d` | Ordering provider | Sum of squared recipient referral shares | Null without complete referral coverage |
| `member_overlap_jaccard_90d` | Provider pair | Shared members / union members | Minimum support required |
| `observed_shared_owner_count` | Provider | Supported owner assertions active at cutoff | Unknown is not zero ownership |
| `cross_signal_member_overlap` | Network | Members appearing in independently supported billing patterns | Do not include mere adjacency |
| `supported_findings_growth` | Provider | Change in independently evidenced findings over windows | Frozen rule version |
| `prior_known_outcome_count` | Provider | Outcomes available before cutoff | Pending is separate from negative |
| `timestamp_coverage` | Provider/family | Eligible lines with trusted times / all eligible lines | Always publish denominator |
| `history_days_observed` | Provider | Available active observation span | Forecast eligibility input |

Use `log1p` only on nonnegative quantities. Negative net ledgers remain financial adjustments and are handled separately, not forced into positive spend features.

## Peer grouping

Start with service family × specialty × setting × procedure group. Add geography and simulated complexity only when support permits. An initial design minimum is 30 peer providers and 200 eligible lines; tune and disclose these as demo thresholds.

Fallback hierarchy: remove fine geography, widen specialty grouping, then mark unsupported. Never silently compare a rural specialist to a mixed all-provider population. Display the actual fallback cohort and support counts. Exclude the scored provider from its peer reference when feasible.

For a rate, use shrinkage toward an earlier peer prior:

```text
smoothed_rate = (observed_count + alpha * prior_rate) / (eligible_count + alpha)
```

Choose `alpha` on training/validation data, not the final test set. For continuous outliers:

```text
robust_z = (x - peer_median) / max(1.4826 * peer_MAD, epsilon)
```

A zero-spread cohort needs a documented fallback, not arbitrarily huge scores. Peer summaries used for calibration/scaling must be fit on permitted data. Contextual contemporaneous features can use the available scoring snapshot if defined consistently in training and serving; never use future arrivals.

## Temporal windows and leakage controls

Compute distinct 7-, 30-, and 90-day windows. For growth, compare non-overlapping periods of equal length. Include exposure time so a newly enrolled member or new provider is not compared with a full-history subject without qualification.

Exclude hidden scenario labels, future payments/reversals, future ownership assertions, future dispositions, case priority, eventual recoveries, and post-cutoff notes. `received_at <= t` alone is insufficient for a relationship learned later; every source has availability metadata.

Case groupings learned at a future cutoff cannot define historical network features. Rebuild graphs as of each anchor. Historical rule-derived features must use a frozen rule bundle rather than a version designed after viewing held-out outcomes.

## Transformations and missingness

Create one training/serving pipeline with ordered feature names and dtypes. Median imputation and missing indicators are acceptable for supported numerical ML features when learned on training data. A detector prerequisite cannot be “imputed” into evidence: synthetic imputed appointment times must never support a timing finding.

Scale the logistic baseline with training-fit transforms. Tree models usually do not need standard scaling, but input contracts still require bounded and finite values. Clip extreme values only with recorded training thresholds; preserve raw evidence values separately.

Do not use opaque IDs, fictional names, free-text notes, or exact addresses as predictive inputs. Sensitive simulated attributes can be isolated for evaluation slices where appropriate; they should not become adverse-action features.

## Storage and reproducibility

Store feature spec version, source snapshot hash, cutoff, graph version, cohort definition, coverage, and ordered schema beside each Parquet matrix. Persist raw feature values used for an explanation so a later recomputation cannot silently change a historical explanation.

Test feature values against hand-calculated tiny fixtures, future-row insertion invariance, and training/serving parity. A feature contract change requires a new model-compatible version.
