# 06 — Synthetic-only data and scenario generation

## Hard requirement

**Every claim, member, provider, employee/investigator persona, facility, location, relationship, and investigation record used by the prototype is synthetic.** Public technical documentation may inform the design; public real-person or real-provider records are not input datasets. Do not scrape provider directories or use de-identified production claims as a shortcut.

The generator is the default data source. A bundled demo is fully offline and deterministic for a seed. Optional Synthea-derived synthetic clinical context can be adapted later, but it does not supply validated FWA labels or all payer billing relationships. Synthea generates fictional health records; SpotZⁱ still needs its own claim lifecycle, network, and scenario simulation. [Synthea overview](https://synthetichealth.github.io/about.html).

Any adapter must validate the provenance of every exported table independently. Do not assume synthetic patient records imply that associated provider, organization, or location reference files are fictional. Replace any real-world reference entities with generated fictional equivalents and remap all keys before import; otherwise exclude that adapter from the synthetic-only prototype.

## Generator configuration

```yaml
dataset_id: SYN-DEMO-001
seed: 42
months: 24
members: 5000
providers: 500
facilities: 80
claim_lines_target: 100000
service_families:
  - professional
  - facility
  - pharmacy
  - laboratory
  - ambulance
  - behavioral_health
  - home_health
  - dme
scenario_prevalence: 0.02
late_arrival_fraction: 0.05
timestamp_missing_fraction: 0.15
include_benign_controls: true
```

Values are controllable simulation settings, not estimates of real FWA prevalence. Define prevalence at the scenario/line/entity levels separately in the manifest; the example parameter controls injected line-level involvement. Generate until the approximate volume is reached while preserving coherent episodes, then report actual counts.

## Generation sequence

1. Create fictional organizational groups, specialties, capacities, locations, and enrollment periods.
2. Generate heterogeneous member care needs and plausible utilization episodes, with seasonality, chronic follow-up, and referrals.
3. Convert episodes to family-specific claim transactions, lines, and signed payment events.
4. Simulate clean replacements, cancellations, reversals, delayed receipt, and noisy optional fields.
5. Create benign institutional relationships: group practice, hospital campus, referral hubs, and normal shared ownership.
6. Inject selected suspicious scenarios by modifying observable transactions and relationships.
7. Independently generate scenario truth with event times, roles, severity, affected lines, and attribution.
8. Simulate delayed investigation outcomes, including unresolved and inconclusive results; outcomes become features only after their availability time.
9. Validate referential integrity, timing, totals, label separation, and provenance. Export manifest and checksums.

Clinical plausibility is approximate. Synthetic code families such as `SYN-LAB-PANEL-A` avoid presenting invented billing policies as official codes. Use distinct code-system labels. Do not copy proprietary code descriptions into the fixture.

## Scenario catalog

| ID | Injected behavior | Observable signals | Benign matched control |
|---|---|---|---|
| S01 | Duplicate paid service | Matching service fingerprints across active transactions | Replacement plus full reversal |
| S02 | Coding intensity shift | High-level service mix changes within peer cohort | Higher simulated complexity or specialist referral mix |
| S03 | Synthetic bundle fragmentation | Mutually constrained synthetic codes billed together | Permitted distinct-service modifier with separate encounter |
| S04 | Possible unperformed service | Complete simulated encounter feed lacks expected event | Feed outage or delayed encounter availability |
| S05 | Excessive repeated testing | Short-interval repeats, concentrated ordering, high peer deviation | Documented synthetic monitoring episode |
| S06 | Incompatible timing | Overlapping individual in-person services at distant locations | Telehealth, group treatment, date-only records |
| S07 | Referral/ownership network | Concentrated referrals plus shared ownership and billing evidence | Integrated legitimate healthcare group |
| S08 | Escalating provider activity | Persistent increase in implicated paid lines and distinct members | Seasonal demand or expansion with increased capacity |
| S09 | DME supply pattern | Repeated purchases, rentals, or improbable delivery indicators | Authorized replacement or distinct item |
| S10 | Pharmacy pattern | Repeated fills across locations with overlapping supply | Reversal, dose change, vacation override |
| S11 | Facility/ambulance context | Repeated transport or overlapping episode indicators | Transfer and split billing with coherent journey |
| S12 | Behavioral/home-health timing | Individual sessions or visits exceed available time | Group sessions, multiple clinicians, legitimate episode billing |

Each scenario has at least one noisy variant and one benign control. Missingness is distributed across positives and negatives so the model cannot use it as a truth shortcut.

## Hidden truth and observed labels

Store `scenario_truth.parquet` and `event_truth.parquet` under `evaluation_private/`. They contain scenario family, actor roles, involvement, event times, and synthetic attribution. None of these columns enters raw claims, file names served to the UI, IDs, notes, or feature matrices.

An injected scenario is a simulation truth, not a real fraud finding. Distinguish involved providers, legitimate connected providers, affected members, and uninvolved bystanders. A graph neighbor is not automatically positive.

Historical synthetic investigation labels can be `substantiated_simulation`, `not_supported`, `inconclusive`, or `pending`. Absence of an investigation does not mean negative. A human review in the live demo creates a separate reviewer decision record; it does not overwrite generator truth or retroactively become perfect training truth.

## Prevent easy but misleading model success

- Randomize amounts, frequencies, durations, and relationship patterns within scenario families.
- Generate high-cost legitimate cases and low-cost suspicious cases.
- Avoid sequential IDs, single codes, or exact dollar amounts unique to suspicious rows.
- Use separate seeds and reserve actor groups for entity-disjoint tests.
- Hold out a scenario variant and network structure for novelty evaluation.
- Evaluate with several prevalence settings; do not assume a planted 2% transfers to reality.
- Preserve the same benign-complexity logic in training and held-out datasets.
- Keep the presentation fixture separate from final evaluation fixtures.

## Outputs and acceptance

Produce the input files in document 05, an optional complete simulated encounter feed, the manifest, a quality report, a scenario summary for evaluators, and hidden truth. Every identity must be provably generated by the configured pipeline. No external names or real addresses are required; generated coordinates live in explicitly fictional location records.

Running the same generator version, configuration, and seed must reproduce the same content hashes after excluding generation timestamps. The quality report reconciles payments and reversals, active claim counts, service-family counts, scenario involvement, and unsupported detector coverage.
