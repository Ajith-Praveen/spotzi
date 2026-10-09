# SpotZⁱ — Product Feature Reference

**Evidence-first fraud, waste and abuse (FWA) intelligence for healthcare payer Special Investigations Units.**

SpotZⁱ turns thousands of unexplained claim alerts into a short, ranked list of evidence-backed cases that an investigator can understand, challenge and act on. Every number traces to source rows, every recommendation shows its reasoning, and every outcome is decided by a named human.

> **Data notice.** SpotZⁱ currently runs on fully synthetic data (no real member, provider or payer data). All accuracy figures in this document are measured against hidden synthetic labels and do **not** describe real-world performance.

---

## 1. At a glance

| | |
|---|---|
| Claim lines analysed per run | 62,507 synthetic lines · 8 service families · 132 providers · 2,500 members |
| Raw alerts → ranked cases | 5,577 flagged lines → **13 cases** (one provider in them, Juniper Clinical Lab, has no rule hit at all and was surfaced by the learned detectors) |
| Detectors | **9** (rules, Isolation Forest, network graph, case-mix twin, care-pathway, change-point, code-mix, patient-panel shift, temporal evolution) fused by the **Nexus Brain** |
| Forecast | Discrete-time hazard model, 30 / 60 / 90 days, calibrated |
| Second brain | Knowledge wiki (ingest → lint → human review → versioned memory) + 6-step decision chain |
| Full pipeline run | ~18 seconds on a laptop |
| External AI required | **None.** All detection, ranking, reasoning and knowledge is in-house. LLM features are optional add-ons. |

### Run it
```bash
cd spotzi && pip install -r requirements.txt
./start.sh                            # starts local PostgreSQL (port 5544) + SpotZⁱ → http://localhost:8000
./stop.sh                                  # stops both
```
**Storage.** SpotZⁱ runs on **PostgreSQL 16** (project-local cluster in `spotzi/data/pg`, SCRAM-SHA-256 password auth, listening on 127.0.0.1 only). Connection settings live in `spotzi/data/db.env` (owner-readable, git-ignored); point `SPOTZI_DB_URL` at any managed Postgres to move it. Without `SPOTZI_DB_URL` it falls back to a single SQLite file for laptops and quick demos. `migrate_to_postgres.py` copies an existing SQLite database into Postgres.
On first start SpotZⁱ creates five local demo accounts (2 investigators, 1 supervisor, 1 analyst, 1 admin) with random passwords, written only to `spotzi/data/seed_users.json` (owner-readable). Sign in with one of them; change or remove them for any shared deployment.

### Test it
```bash
cd spotzi && python3 -m unittest discover -s tests -v                               # SQLite, ~2 min
cd spotzi && SPOTZI_TEST_BACKEND=postgres python3 -m unittest discover -s tests -v  # PostgreSQL (separate spotzi_test database)
```

---

## 2. The user journey

**Load → validate → detect → connect → forecast → rank → investigate → decide → learn.**

1. **Data & pipeline** loads nine tables, validates them, and runs every model. If validation fails, the run stops and the previous analysis stays live.
2. **Overview** shows the funnel from raw alerts to cases inside review capacity.
3. **Nexus Brain** surfaces what changed, what the detectors disagree on, and leads no rule caught.
4. **SIU queue** ranks cases by a transparent weighted priority and packs them into the review hours you have.
5. **Case workspace** explains the case: brief, decision chain, evidence, network, timeline, forecast, Challenge Lab, precedents, claims.
6. **Decision** — a named investigator records an outcome with written rationale; referral needs a second person.
7. **Knowledge** — the decision becomes proposed knowledge; once a human approves it, it informs the next similar case and nudges the Brain's detector weights.

**When the system is uncertain** it says so: weak-evidence cases are held in *Needs more data* and cannot be referred; benign context sends a case to *Validate context first*; learned-detector-only findings arrive as *Brain lead*; "No safe precedent found" is a normal answer.

---

## 3. Access, roles and case management

**Sign-in and roles.** Local accounts with PBKDF2-hashed passwords (200,000 rounds) and HttpOnly, SameSite-strict session cookies (12-hour expiry). Every `/api` call requires a session. The server stamps the signed-in user's name and role on every action — a client cannot act as someone else.

| Permission | Investigator | Supervisor | Analyst | Admin |
|---|:-:|:-:|:-:|:-:|
| Record case decisions, run evidence checks, notes, blueprints | ✓ | ✓ | | ✓ |
| Approve / reject referrals (must differ from recommender) | | ✓ | | ✓ |
| Assign cases | | ✓ | | ✓ |
| Approve knowledge updates | | ✓ | ✓ | ✓ |
| Quality-approve precedents (must differ from decision-maker) | | ✓ | | ✓ |
| Run models, upload data, switch datasets | | | ✓ | ✓ |
| Manage users (create, role, deactivate, reset password) | | | | ✓ |

**Two-factor sign-in (TOTP).** Works with any authenticator app; ±30-second window, each code usable once (replay-protected), 8 single-use recovery codes. Admins choose which roles must use it; users in those roles must enrol before anything else works. Admins can reset a user's two-factor. Verified against the RFC 6238 test vectors.

**Single sign-on (OpenID Connect).** Authorization-code flow with PKCE, single-use state and nonce, ID-token signature verified (RS256 via the identity provider's published keys), issuer / audience / expiry checked. Users must already exist in SpotZⁱ (matched by work email) — the identity provider proves who you are; SpotZⁱ still decides your role. Configure with `SPOTZI_OIDC_ISSUER`, `SPOTZI_OIDC_CLIENT_ID`, `SPOTZI_OIDC_CLIENT_SECRET` (optional `SPOTZI_OIDC_REDIRECT`, `SPOTZI_OIDC_LABEL`). Tested end-to-end against a simulated identity provider; not yet tried with a live one.

**Security hardening.** Strict Content-Security-Policy (no inline scripts), no framing, no-sniff, no-referrer, `no-store` on API responses; cross-site writes blocked by origin check; a client/server contract version stops an outdated browser tab from submitting decisions ("refresh first").

**Settings** (every user): two-factor setup, password change, notification preferences. Admins also get the two-factor policy, SSO status and the delivery outbox.

**My work** (home screen, per user): my assigned cases with due dates and overdue flags; for supervisors — referral approvals waiting, unassigned cases, team workload, precedent quality review; for analysts — knowledge review count; notifications for assignments, notes and approval requests.

**Email and Slack notifications.** Every in-app notification can also go to email (SMTP) and/or a Slack-compatible webhook, if the user opts in. Messages carry only case IDs and actions — never provider or member names, scores or outcomes — and link back to SpotZⁱ, which requires sign-in. A durable outbox retries failures with exponential back-off (5 attempts) and shows status to admins. Configure `SPOTZI_SMTP_HOST/PORT/USER/PASSWORD/FROM`, `SPOTZI_SLACK_WEBHOOK`, `SPOTZI_BASE_URL`.

**Case split and merge.** Supervisors can merge cases that belong together or split providers into their own case, with a written reason. Edits are stored, replayed on every analysis run, can be undone, and are audited; a merged-away case ID points to its successor.

**Case management:** supervisors assign a case to an investigator with a due date (default 10 days); assignee shown in the queue; working notes on each case (member identifiers require explicit confirmation); in-app notifications.

**Users & roles** (admin): create users, change roles, deactivate (ends all sessions), reset passwords; users can change their own password.

## Operations (added to close gaps with enterprise FWA platforms)

| Capability | What it does |
|---|---|
| **Claim check (pre-payment)** | Scores a claim *before* it is paid in ~2 ms: eligibility and death, inpatient-stay overlap, excluded providers, duplicates against paid history, repeat intervals, unbundling, daily unit limits, impossible hours, excessive visits, level-5 patterns, and whether the provider is already under review. Recommends **Pay**, **Pay + monitor** or **Pend for human review** with reasons — it never denies. Reviewers release, adjust or deny pended claims with a written reason; avoided amounts feed Outcomes. API: `POST /api/prepay/score`. |
| **Unit-limit edits** | New rule: more units of a service per member per day than is medically plausible (per-code limit table, illustrative values to tune with coding experts). |
| **Excluded-provider screening** | New rule: claims on or after a provider's exclusion date. Loads `exclusions.csv` (synthetic list in the demo; same columns as an official list export). |
| **Rule studio** | Analysts build rules from conditions (code, family, place of service, units, paid, weekday, provider/member lines per day, member age…), preview exactly what would be flagged (lines, providers, paid, overlap with existing rules, share already in cases, warning if too broad), save as draft, activate, and re-run. Active rules flow into cases, the Brain and briefs. |
| **Recoveries & ROI** | Per case: identified → demand letter → repayment plan → recovered / written off. Outcomes page totals identified, recovered and avoided-before-payment money against review hours × hourly cost. Gross flagged exposure is never counted as savings. |
| **SIU report** | Outcomes summary (decisions, referrals, recoveries by scheme, pre-payment results) with CSV export and print layout. |
| **Case documents** | Upload records to a case (PDF, images, text, CSV, Word, Excel; ≤20 MB; content checked against extension; SHA-256 recorded); downloads require sign-in and are audited. |
| **Tips intake** | Log hotline / member / employee / provider / law-enforcement tips; supervisors are notified, triage each tip (link to case, watchlist, close) with a note; SpotZⁱ suggests the matching open case; linked tips appear on the case brief. |

## Synthetic data (the only data SpotZⁱ uses)
SpotZⁱ uses only its own generator (`spotzi/synthdata/gen.py`). No real, public or third-party dataset is used. The generator is built to resemble real payer claims:
- **Members:** a realistic age and plan mix (Medicare for 65+, Medicaid skewing young, children), and 12% enrolling mid-period.
- **Health and care use:** age-graded chronic conditions (hypertension, diabetes, COPD, heart failure, CKD, depression, osteoarthritis, asthma, high cholesterol). Care use is heavy-tailed: the top 10% of members generate about a third of claims, and sicker members use more care.
- **Diagnoses that fit the service:** for example A1c → diabetes, CPAP → sleep apnoea, ECG → cardiac; plus a winter respiratory season and a summer dip.
- **Claim mechanics:**
  - payer-realistic refill and repeat-test spacing;
  - contract-level price variation, copays and coinsurance, charge-master mark-ups;
  - log-normal payment lags with ~3% late or reprocessed claims;
  - modifiers 25, RT/LT and RR;
  - ~1.5% missing diagnoses;
  - format-valid NPIs (10 digits, Luhn) in a range real NPIs never use.
- **Fraud and context:**
  - 9 seeded schemes (S1–S9) plus an excluded provider;
  - decoys (oncology, dialysis, high-volume clinic, chain pharmacies);
  - 4 legitimate anomalies with observable business events, plus an adversarial upcoder with a genuine event;
  - hidden ground truth at claim, provider, timing and ring level.

Training uses other seeds (101–106). Held-out tests use seeds 201–202 and the demo world (seed 7).

## 4. Data layer

| Table | Contents |
|---|---|
| `claim_lines` | line, claim, member, provider, facility, referring provider, family, service/paid dates, code, units, billed, paid, place of service, diagnosis, documented minutes |
| `providers` | synthetic NPI, family, specialty, city, ownership org, address, bank account, context notes |
| `members` | age, sex, plan, region, enrolment, termination, death, vulnerability flag, primary-care provider |
| `facilities`, `inpatient_stays`, `referrals`, `relationships`, `investigations` | supporting context |
| `data/hidden/scenario_truth.csv` | evaluation-only labels — **never used for detection** |

**Synthetic generator** (`gen.py`): reproducible by seed, 9 seeded schemes (S1–S8 plus **S9, held out from rule design**), an excluded provider, and benign decoys:

| Scenario | What it simulates |
|---|---|
| S1 lab referral ring | lab + two practices under shared ownership; repeat panels, unbundling, upcoding |
| S2 DME / home-health ring | equipment and visits billed during inpatient stays and after death; shared address and bank |
| S3 behavioral health | impossible hours, daily sessions, 60-min codes with 35-min documentation |
| S4 upcoding | level-5 visit inflation |
| S5 compounding pharmacy | compounded drugs from one prescriber, early opioid refills |
| S6 ambulance | ALS billed for BLS, inflated mileage, transports during stays |
| S7 facility duplicates | duplicate emergency claims |
| S8 home-health phantom | visits during stays |
| **S9 recruitment mill (held-out)** | sudden wave of out-of-region members, one templated visit + lab bundle each |
| Decoys | oncology (legitimately high-level visits), dialysis lab (legitimate repeat labs), chain pharmacies (routine shared ownership) |

**Bring your own data.** Analysts upload CSVs on *Data & pipeline*: `claim_lines`, `providers`, `members` (required) plus optional referrals, relationships, investigations, inpatient stays and facilities. Required files and columns are validated before anything runs; missing optional columns get safe defaults (e.g. ownership links are derived from provider master data). Without outcome labels SpotZⁱ still detects, ranks, explains and reasons; forecasts show as **unavailable** (their queue weight is redistributed, never guessed), and evaluation and the evidence vault switch off. A test proves detection is identical with and without labels. One click switches back to the synthetic demo.

**X12 837 claim files.** Upload 837 professional (837P) and institutional (837I) files directly — alone or alongside CSVs. The parser reads billing provider, taxonomy, subscriber/patient and demographics, claims, diagnoses, referring provider, service lines and dates, and inpatient admission/discharge; provider type comes from the taxonomy code, falling back to place of service. Malformed segments are reported, never silently dropped. Round-trip tested: 100% of codes, amounts, dates and provider types preserved. 837 carries billed charges only, so paid amounts equal billed until 835 remittance is added. Sample 837P/837I files can be downloaded from *Data & pipeline*.

**Validation checks:** schema, unique IDs, provider and member foreign keys, non-negative amounts, date ranges, paid-after-service, diagnosis completeness, referral coverage, documented-time coverage, label isolation.

---

## 5. AI models — the detection brain

All nine detectors are built in-house and run on the claims themselves; no third-party or real-world data is used.

| # | Detector | How it works | What it catches | AUC* |
|---|---|---|---|---|
| 1 | **Rules engine** | 9 versioned built-in rules (plus analyst custom rules), each citing the exact line and reason: duplicates (incl. cross-pharmacy), repeat-inside-interval / early refill, unbundling, upcoding (level share + time-based codes + ALS share), services not plausibly rendered (inside stays, after coverage end / death), impossible timing (>16 h/day, overlapping sessions), excessive utilisation | Known billing patterns | 0.956 |
| 2 | **Isolation Forest** | Provider anomaly on 11 peer-normalised features; separate claim-line Isolation Forest | Unusual multivariate behaviour | 0.962 |
| 3 | **Network graph** | Referral flow, shared ownership / address / bank, shared-member overlap; Louvain communities; "suspicious-tie" subgraph groups providers into network cases | Coordinated rings | 0.798 |
| 4 | **Sentinel case-mix twin** | Gradient-boosted model of what a provider's own patients *should* cost (age, plan, diagnosis profile, utilisation elsewhere). Cross-fitted by provider groups; small panels shrunk (empirical Bayes) | Spend that case mix cannot explain (e.g. a pharmacy billing 32× expectation) | 0.750 |
| 5 | **Sentinel care-pathway** | Back-off sequence model of member journeys: next service given previous service, time gap, inside-stay, after-coverage-end. Leave-provider-out counts so a ring can't normalise its own pattern | Improbable care sequences (e.g. wheelchair during an inpatient stay: <0.01% of comparable journeys) | 0.727 |
| 6 | **Behaviour change-point** | Searches each provider's monthly history for the split that best explains a shift in volume, members, new members, out-of-region share, paid per line and service mix | *When* behaviour changed and how ("From 2025-03: new members 2/mo → 32/mo") | 0.939 |
| 7 | **Peer code-mix divergence** | Jensen–Shannon divergence of service mix vs family peers, volume-shrunk | Unusual service mix | 0.876 |
| 8 | **Patient-panel shift** | Among patients new to a provider in the review window: share given one templated bundle, share with no other care in the plan, share from outside the usual catchment — each vs peer baselines | Patient recruitment / brokering ("67 new patients, 100% same bundle, none seen elsewhere") | 0.751 |
| 9 | **Temporal evolution** | Monthly trajectories of 7 behaviours against the provider's own de-seasonalised baseline: bursts, CUSUM build-up, trend, sustained months (`detection/temporal.py`) | Schemes that grow or persist over time | 0.973 |
| ★ | **Nexus Brain (fused)** | One-sided evidence fusion: a quiet detector adds nothing (rule silence is not innocence). Logistic fusion with expert prior weights | All of the above | **0.998** |

\*Ranking AUC against hidden synthetic labels, all 132 providers of the demo world (seed 7), as shown on the Nexus Brain page.

**Held-out proof.** The recruitment mill (S9) was written without any rule targeting it. Its lab, **Juniper Clinical Lab**, has **no rule hit at all** (rule score 0, risk 29, below the case threshold); the Brain ranks it **#11 of 132**. Its clinic, **Northgate Wellness Partners**, trips only incidental upcoding/timing rules (risk 49) and is ranked **#9** by the Brain. Both are joined as one network case, **CS-0009**, so the lab no rule would have flagged reaches an investigator.

### Learning from humans
Detector weights start at expert priors and update from every recorded decision (*substantiated* vs *cleared*) by MAP logistic estimation with a strong Gaussian prior and non-negative weights. One decision moves a weight by roughly a tenth at most; the weights are recomputed from the decision log, so learning is reproducible and auditable. Learned changes appear in the Brain feed.

### Forecast — 30 / 60 / 90-day repeat or escalating FWA
- **Discrete-time hazard model:** intervals (0,30], (30,60], (60,90]; covariates frozen at the anchor date; `P60 = 1-(1-h1)(1-h2)` so horizons can never contradict each other.
- Baseline pooled logistic hazard vs gradient-boosting challenger; the challenger is chosen by a frozen rule (lower training-period log loss) — currently gradient boosting.
- Sigmoid calibration cross-fitted by provider group on the training period only; temporal holdout with a 90-day purge.
- Held-out results: AUC 0.955 / 0.956 / 0.953 · Brier 0.050 / 0.032 / 0.027 · calibration error 0.063 / 0.034 / 0.014 (30 / 60 / 90 days). Probabilities capped at 1–97 %.
- Local drivers shown per provider.

### Task models (trained per SIU process) — `spotzi/ai/models/`
Each model is trained by `python3 -m ai.models.train_all` on synthetic data only, saved as a versioned artifact with a model card (`data/models/*.json`), shown in **Governance → Task models**, and tested on data it never saw. Training: synthetic generator worlds (seeds 101–106). Tests: the demo world (seed 7) and held-out worlds (seeds 201–202) never used in training.

| Model | Process | Method | Held-out result |
|---|---|---|---|
| **Pre-payment line risk** | Operations → Pre-payment | Gradient-boosted trees on 18 behaviour features | see EVALUATION.md (held-out worlds) |
| **Chart documentation** | Case → Chart review | TF-IDF (word + char) → logistic regression over documented E/M level; parsed time rules | Unseen clinician wording: 100% vs 38% for a keyword reviewer |
| **Tip triage** | Tips → automatic structuring | Ensemble: TF-IDF → logistic regression + local sentence encoder (bge-small, frozen) → logistic regression; 9 scheme types | Unseen templates and names: **93%** (v1 was 54%; keyword matching 20%). An urgency model failed its test and was not shipped |
| **Case outcome** | Cases / providers | Logistic regression on detector outputs, learned from simulated closed cases | see EVALUATION.md |

Design rule kept in the code: features must mean the same thing in any claims system (no family one-hots or data-completeness artefacts), so models learn behaviour, not the generator.

### LLM-assisted detection (where a language model is genuinely needed) — `ai/llm_detect.py`
| Use | Why an LLM | Guardrails |
|---|---|---|
| **Chart review** (Case → Chart review) | Reads free-text clinical documentation and applies coding judgement (MDM / time / record present) | Structured output only; every finding must quote the note verbatim (string-checked, else discarded); the trained chart model gives a second opinion and disagreements are flagged |
| **Tip structuring** (Tips) | Extracts the allegation type, named entities and timeframe from messy free text | Entities are matched to providers by deterministic code, so the model cannot invent IDs; supervisors triage every tip |
| **Rule drafting** (Rule studio) | Turns an analyst's plain-English rule into conditions | Schema-validated against the rule language; draft only, previewed, then saved and activated by a human |

Providers: DeepSeek, z.ai (GLM), any OpenAI-compatible endpoint, Anthropic or a local server, configured by an admin in **Settings → AI & LLM**: on/off, provider, model, API key and a switch for each feature. Environment settings in `spotzi/data/llm.env` are the fallback. With none configured, every feature runs on the trained models and rules. The LLM never scores, ranks, opens cases or decides. Synthetic medical records come from `ai/charts.py` (a simulated record system). `evaluation/evaluate_llm.py` measures each reviewer.

| Supporting model | Status |
|---|---|
| **AI narrative & copilot** | Grounded in the case evidence package, citation-verified. Uses the same LLM configuration. |

---

## 6. The second brain — knowledge layer

SpotZⁱ keeps a persistent, linked memory that improves with every approved update.

| Stage | What happens |
|---|---|
| **Ingest** | Every run proposes provider and case pages; every human decision proposes a decision record and a *lesson learned* on the matching scheme page. Every fact carries a source. |
| **Lint** | Automatic checks: uncited facts, member identifiers (blocked — data minimisation), broken links, empty sections, a change to a prior conclusion, fraud wording stated as a conclusion. |
| **Review** | A named human approves or rejects, side-by-side with the current version. Updates that change a conclusion require a review note; lint-clean updates can be bulk-approved. |
| **Update** | Approved pages are versioned; history is kept; nothing is silently overwritten. Backlinks connect pages. |
| **Query** | TF-IDF retrieval over approved knowledge only. |
| **Compounds** | The decision chain retrieves approved memory, so the next similar case starts with what the team already learned. |

Seed knowledge: 7 rule/policy pages, 8 scheme pages, the human-decision policy.

### Decision chain (case tab)
A traceable reasoning path for every case:

1. **Retrieve** — approved policy, scheme and memory pages + comparable precedents
2. **Interpret** — observed facts, hypotheses, data gaps (each labelled)
3. **Apply rules** — rules fired, exception logic, benign-context and abstention policies
4. **Propose** — recommended human action and the highest-value next evidence check
5. **Score** — evidence strength, ambiguity (bits), impact (dollars, members, vulnerable members), precedent fit
6. **Cite** — claim lines, wiki pages with versions, run / ruleset / model versions, precedent IDs, and the five human checkpoints

**Output:** a grounded recommendation with evidence, confidence, impact and a path to human approval. It never decides.

---

## 7. Precedent Intelligence — where it is used

Precedents are retrieved for every case and used in **three places**:

1. **Precedents tab** — closest quality-approved prior cases, with *material differences shown before the prior outcome*.
2. **Decision chain** — step 1 retrieves them; step 5 scores precedent fit and difference count; step 6 cites them.
3. **Review blueprint** — an editable checklist built from the precedents' checks (requires acknowledging the differences first).

How it works:
- **Library:** 54 simulated human-reviewed cases across 18 scenario families (clearly labelled *simulated*), plus live cases once a supervisor (not the decision-maker) quality-approves them.
- **Eligibility then similarity:** same service family required; similarity = pattern overlap 25 % · provider context 20 % · evidence coverage 15 % · temporal shape 15 % · graph motif 15 % · financial/member band 10 %.
- **Diversity:** best match per scenario, so look-alikes with *opposite* outcomes appear together — e.g. the recruitment mill retrieves both a legitimate practice expansion (closed) and a confirmed recruitment scheme (referred).
- **Learned-detector leads** match behaviour-shift precedents.
- **Safeguards:** shows *retrieval similarity* (not fraud probability); warns on high similarity with contradictions; "No safe precedent found" is valid; never prefills an outcome; every blueprint item records its source; skipping an item requires a reason.

---

## 8. Evidence Challenge Lab

Helps the investigator test legitimate against suspicious explanations before deciding.

- **Competing explanations:** unsupported billing · legitimate explanation · data gap — prior and current belief shown.
- **Next best evidence check:** ranked by expected information gain per review hour; each check marked *can clear* and/or *can confirm*, so the system looks for exonerating evidence too.
- **Approve & reveal:** a named human approves each check; it reveals a pre-generated synthetic artifact (evidence vault). Nothing is sent to anyone.
- **Scenario branches:** for the top checks, every possible outcome with its probability, resulting belief and exposure impact — hypothetical, never overwrites observed evidence.
- **Evidence fragility:** "concern supported under N of M configured tests" (removing graph, anomaly, escalation, or individual findings).
- **Replay:** revealed checks persist and feed the decision record.

---

## 8b. Investigation readiness & action plan
**Investigation readiness** (Case → Brief) is a checklist score, not a fraud probability. It answers the question: is the investigation complete enough to support a referral? Items apply by case type:
- billing-pattern evidence;
- peer comparison;
- provider documentation reviewed (a chart review or uploaded records);
- member / service verification (phantom, recruitment, excess and timing cases);
- referral relationships verified (network cases);
- legitimate context ruled out;
- historical precedent;
- data completeness.

It produces a clear recommendation, for example: *"Do not refer yet. Next: obtain provider documentation."* If the sampled charts support the billing, it says: *"Do not refer — consider closing or education."*

**Investigation action plan** (Case → Action plan) answers *"what should I actually do next?"*:
- The gaps become ordered steps. Each has an owner, a time estimate, why it matters, what it adds to readiness, and the benign explanations to test.
- Each step has a button: request a chart sample, mark done or not applicable (with a required note), or go to the decision.
- Steps are stored in PostgreSQL and audited.

**Referral gate:** "Recommend referral" below 70% readiness is refused unless the reviewer explicitly acknowledges the listed gaps; the acknowledgement is written into the decision record. The exported brief includes readiness and the plan.

**Business context on file** (Case → Brief) lists provider events — new locations, clinicians, contracts, acquisitions — and shows which signals each event explains and which it does not.

## 9. SIU queue & prioritisation

- Transparent priority: **risk 22 % · forecast 15 % · potential dollars 20 % · member impact 10 % · severity 15 % · evidence strength 18 %** — all adjustable live with sliders.
- Case risk blends rule-based risk with the current (learned) Brain score.
- **Capacity packing:** investigators × hours/week × weeks; each case has an effort estimate; cases are marked *scheduled* or *over capacity*.
- Gates: *Needs more data* ×0.65 and never scheduled; *Validate context first* and *Brain lead* ×0.9.
- Columns: priority with contribution bar, risk, Brain score, forecast, exposure, members (vulnerable), severity, evidence, hours, lane, status, second-brain agreement.
- Horizon switch (30 / 60 / 90 days) and CSV export.

---

## 10. Case workspace

| Tab | Contents |
|---|---|
| **Brief** | summary, recommended human action, confidence rationale, signal families, competing explanations, LLM second opinion (optional), AI narrative (optional), limitations |
| **Decision chain** | the six-step reasoning path (§6) |
| **Evidence** | every rule finding with example lines and reasons, Isolation Forest drivers, Sentinel findings with improbable transitions, Brain fusion breakdown, behaviour change before→after, graph links, patient-panel shift, prior investigations — each with source |
| **Network** | interactive ego graph (zoom, pan, click) + provider roles; linked providers may be innocent bystanders |
| **Timeline** | monthly paid vs flagged; first-flag events; prior investigations |
| **Forecast** | 30/60/90-day probability, drivers, held-out metrics |
| **Challenge lab** | §8 |
| **Precedents** | §7 + review blueprint |
| **AI copilot** | optional grounded Q&A |
| **Claims** | highest-anomaly flagged lines with rules and reasons |
| **Decision** | outcome, rationale, role; history; four-eyes referral approval |

**Export:** investigation brief as Markdown; print layout.

---

## 10b. 3D link analysis
Link analysis and the Portfolio risk map have a **2D | 3D** switch, and your choice is remembered.

The 3D view uses the same cards, icons, risk colours and edge styles as 2D, rendered with three.js. Three.js 0.186.1 (MIT) is vendored in `spotzi/static/vendor/`, so no CDN is needed and it runs under the strict content-security policy.

Space has meaning: horizontal position comes from the network layout, and **height = risk**. High-risk entities rise above the portfolio, and drop-lines to the ground grid make depth readable.

Controls:
- orbit, zoom and pan;
- reset, top-down and auto-rotate buttons.

Hover highlights neighbours; click opens the same inspector or panel; path finding highlights the route in 3D. Edge width still encodes volume (fat lines).

## 11. Other screens

- **Installable app (PWA)** — installs as a standalone window. Offline it is read-only by design (doc 23): only the application shell is cached, never case data or tokens; an offline banner shows the run and as-of date; decisions, approvals and evidence checks are disabled and nothing is queued. Updates show "Update available" and apply only when the user chooses; caches are cleared at sign-out.
- **Overview** — KPIs, user-journey strip, top priorities, alert-to-action funnel, flagged lines by rule, flagged dollars by family, monthly trend, synthetic self-check.
- **Nexus Brain** — held-out test result, insight feed (leads, behaviour changes, detector disagreements, what it learned), detector weights prior → learned, ranking power per detector, highest-suspicion providers with driver breakdown.
- **Knowledge** — search, approved pages by kind, review queue with lint, version history, page view with backlinks.
- **Network explorer** — whole-portfolio graph tiled by component, risk filter, search, Louvain communities.
- **Providers & claims** — provider table (risk, rules, anomaly, graph, Sentinel, own model, forecast), provider page (scores, rule hits, anomaly drivers, monthly chart, top codes, relationships), claims explorer with filters, member timeline against inpatient stays.
- **Data & pipeline** — validation results, step-by-step run log, table schemas, code reference, regenerate with any seed and size.
- **Governance** — principles, limitations, synthetic self-evaluation, forecast model card with calibration plots, Sentinel model card, own-model card, rule catalogue (benign explanations + distinguishing checks), decision log, audit trail.

---

## 12. Human control & responsible AI

- The system recommends; **a named human decides** every outcome. No automated payment hold, provider contact or referral exists.
- Decisions require a written rationale (≥15 characters).
- **Four-eyes:** referral requires a supervisor who is not the recommender; precedent quality approval requires a reviewer who is not the decision-maker.
- **Abstention:** weak-evidence cases cannot be referred.
- **Uncertainty visible:** competing explanations, ambiguity in bits, fragility, missing-data rates, confidence labels.
- **No hidden-label leakage:** scenario truth is used only for evaluation, forecast labels and the Challenge-Lab vault.
- **Knowledge governance:** only human-approved pages are retrieved; member IDs are blocked from the wiki; history is never overwritten.
- **Audit:** every run, decision, evidence check, blueprint edit, wiki approval and export is logged with run, ruleset and model versions.
- **Fail safe:** failed validation or model steps keep the previous analysis live; optional AI layers degrade to deterministic output.
- Work is keyed to a data fingerprint, so it survives restarts.
- Every protected action is checked on the server by role; identity comes from the session, never from the request.

---

## 12b. Backend intelligence (not shown as investigator features)
```
                  SPOTZⁱ BACKEND
        ┌──────────────┼──────────────────┐
   DATA LAYER     DETECTION LAYER     INTELLIGENCE
   validation     rules (+ level-shift)  evidence · precedents
   data quality   ML detectors           readiness · action plan
   temporal       graph · peer baselines context reasoning
        └──────────────┼──────────────────┘
                 EVIDENCE FUSION (Nexus Brain)
          ┌────────────┴─────────────┐
   RISK · calibrated p_fraud     CONSENSUS / TRUST
   fraud stage · scheme type     independent evidence families, data quality, OOD
          └────────────┬─────────────┘
                  HUMAN DECISION  ← prediction log (versions + detector outputs) for replay

   behind it:  EVALUATION ENGINE (evaluation/engine.py) — hidden ground truth only
   ground truth (claim / provider / network / type) · calibration & thresholds · detection delay
   counterfactual tests · adversarial evasion · ablation · synthetic-to-real gap · data-quality robustness
```
| Component | File | What it adds |
|---|---|---|
| Temporal behaviour | `detection/temporal.py` | Monthly trajectories of 7 behaviours against the provider's own early baseline, de-seasonalised. Measures bursts, slow build-up (CUSUM), trend and sustained months. Labels a lifecycle stage: Normal → Deviation → Emerging → Sustained → Established |
| Hierarchical peer baselines | `detection/baselines.py` | Expected behaviour cascades portfolio → family → family×region → family×specialty with leave-one-out empirical-Bayes shrinkage. Each deviation names the peer group actually used |
| Consensus & evidence diversity | `detection/consensus.py` | Counts detectors firing and the *independent* evidence families behind them (correlated detectors merged; effective number by eigen participation ratio) |
| Data quality & out-of-distribution | `detection/consensus.py` | Per-provider data-quality score and a Mahalanobis out-of-distribution check against the training reference. Both can only **lower** confidence |
| Context & intensity | `detection/context.py` | A business event may explain volume. It cannot explain per-patient intensity it could not cause |
| Calibrated probability | `ai/models` `brain_calibrator` | Isotonic calibration of the fused score into `p_fraud`; tiers and capacity thresholds use it |
| Fraud-type classifier | `ai/models` `fraud_type` | Probability per scheme type. Steers which evidence the action plan asks for |
| Drift monitor | `detection/consensus.py` | PSI of every behaviour feature against the training reference, recorded on every run (`/api/monitoring`) |
| Model versioning & replay | `api/app.py` `prediction_log` | Every case prediction is stored with ruleset, model, feature and artifact versions plus all detector outputs (`/api/replay`) |
| Entity ground truth | `synthdata/truth.py` | Hidden per-provider true state, fraud type, start date, severity and ring, for evaluation only |

## 13. Architecture

The full folder layout is in `spotzi/README.md`. Main parts:

```
synthdata/gen.py ──► data/synthetic/*.csv ──► detection/pipeline.py
                                                ├─ detection/rules.py       rules engine + custom-rule language
                                                ├─ detection/analytics.py   features, Isolation Forest, hazard forecast, graph
                                                ├─ detection/sentinel.py    case-mix twin, care pathway
                                                ├─ detection/brain.py       change-point, code mix, patient panel, fusion, learning
                                                └─ ai/models/               trained task models (prepay, chart, tips, outcome)
api/app.py (FastAPI) ─┬─ intelligence/  briefs · lab · precedents · knowledge
                      ├─ ai/            llm (provider + switches) · llm_detect (chart review, tips, rule drafting) · charts (record system)
                      ├─ operations/    ops (pre-payment, recoveries, documents, tips) · scope · notify · x12
                      ├─ infra/         auth (sessions, roles, TOTP, OIDC) · dbcompat (PostgreSQL / SQLite)
                      └─ PostgreSQL     users, sessions, decisions, audit, assignments, notes, outbox, scope, tips + AI triage,
                                        documents, chart reviews, custom rules, pre-payment log, recoveries, wiki, settings
static/  vanilla JS PWA, no build step  ·  tests/test_spotzi.py  50 tests  ·  evaluation/  accuracy scripts
```

**Main API groups:** `/api/login` · `/api/login/mfa` · `/api/mfa/*` · `/api/sso/*` · `/api/security` · `/api/outbox` · `/api/me/prefs` · `/api/cases/{id}/merge` · `/api/cases/{id}/split` · `/api/data/sample.837` · `/api/me` · `/api/users` · `/api/my` · `/api/cases/{id}/assign` · `/api/cases/{id}/notes` · `/api/data/upload` · `/api/overview` · `/api/queue` · `/api/cases/{id}` (+ `/brief.md`, `/decision`, `/lab`, `/lab/reveal`, `/precedents`, `/blueprint`, `/chain`) · `/api/brain` · `/api/wiki` (+ `/page`, `/search`, `/proposals`) · `/api/providers` · `/api/claims` · `/api/members/{id}` · `/api/network` · `/api/governance` · `/api/data` · `/api/run` · `/api/audit` · `/api/llm/status`.

---

## 14. Honest limitations

- **Synthetic only.** The scenarios were written with rules in mind, so rules look stronger than they would on real claims; all metrics are synthetic.
- Rule thresholds and Challenge-Lab outcome probabilities are expert estimates, not measured.
- The precedent library is simulated; real retrieval will be messier.
- Peer baselines are by service family, not specialty; claims run-out is not modelled.
- Analysis runs in memory on one machine — fine for hundreds of thousands of lines, not for national payer volumes.
- SSO is tested against a simulated identity provider only; offline/PWA install could not be verified in the embedded preview browser (it blocks service workers) and needs a check in Chrome or Edge.
- Postgres runs as a single local instance; backups, replication and connection pooling are not set up yet.

## 15. Roadmap

1. Managed Postgres (backups, replicas, pooling) and row-level / multi-tenant access.
2. 835 remittance ingestion (paid amounts, reversals) and data-quality monitoring.
3. Learning-to-rank from investigator outcomes; continuous-time care-pathway model.
4. Precedent quality-review screen; automation-bias evaluation.
5. Drift monitoring, model registry with human-approved promotion.
6. Live identity-provider certification (Okta / Entra ID) and SCIM user provisioning.
