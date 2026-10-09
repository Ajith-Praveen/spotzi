# ClaimShield Nexus (SpotZⁱ) — 6-minute demo script

One path, one case, one story: **5,577 unexplained alerts → 13 ranked, evidence-backed cases → a human decision.**
Everything else in the product is for Q&A, not the demo.

## Before you go on stage (T-10 min)

- [ ] `cd spotzi && ./start.sh` — open http://localhost:8000 (landing page) → **Open the app** (or go straight to http://localhost:8000/app), sign in as `admin` (password in `spotzi/data/seed_users.json`).
- [ ] Browser zoom 110–125% so the back row can read numbers. Full screen, notifications off.
- [ ] Open these tabs in order, so a slow network never stalls you:
  1. `#/overview`
  2. `#/queue`
  3. `#/case/CS-0107/brief`
  4. `#/governance`
- [ ] Network tab of CS-0107 opened once beforehand (3D graph warms up).
- [ ] Queue capacity reset to 3 investigators · 24 h/week · 2 weeks; horizon 60-day.
- [ ] Backup: screenshots of each step in a folder, in case the laptop or Wi-Fi fails.

## The script

### 0:00 – 0:30 · The problem (no screen yet, or title slide)
> "Payers see thousands of FWA alerts. Most are noise, and real fraud hides across claims: a supplier, a home-health agency and a referral source that share an owner and a bank account. Investigators don't need more alerts; they need fewer, ranked, explained cases. That's ClaimShield Nexus."

### 0:30 – 1:15 · Overview: alerts to cases
Screen: **Overview**.
- Point at the six-step strip: **Load → Detect → Connect → Forecast → Rank → Investigate**. "This is the whole pipeline; it runs end-to-end in about 18 seconds on 62,507 synthetic claim lines."
- Point at the funnel: **62,507 lines → 5,577 flagged → 13 ranked cases → 2 that fit this week's capacity.**
> "Nine rules, an Isolation Forest, temporal change-point detectors and graph analytics each vote. A fusion layer turns 5,577 alerts into 13 cases. That's the outcome the brief asked for."

### 1:15 – 2:15 · SIU queue: ranking under real capacity
Screen: **SIU queue**.
- Read the columns out loud once: risk, forecast, dollars, members, severity, evidence, review hours.
- **Live interaction:** change investigators from **3 → 6**. More cases flip from "over capacity" to "✓ scheduled". "The queue packs cases into the hours your team actually has."
- Drag the **Potential dollars** weight up; the order changes. "Priorities are a policy choice, so the weights are transparent and adjustable, not hidden in a model."
- Switch **30 / 60 / 90-day** horizon. "The forecast column updates; the horizons are from one hazard model, so they can never contradict each other."
- Point at rows **#12 Oncology & Hematology** and **#13 Valley Internal Medicine**: lanes say **"Validate context first"** and **"Explained by context"**.
> "These look like upcoding, but the system found a legitimate explanation (a complex patient panel, a business event) and routes them away from investigation. This is how we keep innocent providers out of the Investigate lane."

Click **#1 Meridian Mobility Supply + 3 linked (CS-0107)**.

### 2:15 – 3:30 · The case brief: evidence, confidence, limits
Screen: **CS-0107 → Brief**.
- Top cards: risk 88, $58,227 exposure ("gross flagged, **not** a recovery"), 46 members, evidence 98, 60-day repeat risk 94%.
- **Investigation readiness: 50%, "Investigation not yet sufficiently supported. Do not refer yet."**
> "This is the most important thing on screen. The evidence is strong, but nobody has reviewed provider documentation yet, so the system refuses to recommend referral and tells the investigator the next step: request a chart sample, about 30 minutes."
- Scroll to **Competing explanations**: suspicious 96%, legitimate 11%, data gap 22%. "We show the other side of the argument, not only the accusation."
- Scroll to **Limitations**. Read one line: "A flag is a pattern for human review, not a finding of fraud."

### 3:30 – 4:15 · Network: why it's one case
Screen: **Network** tab (3D).
- Rotate once. "Four providers: a DME supplier, a home-health agency and two more, linked by shared ownership, address/bank and referral dependence. Individually each looks small; together it's a scheme. Entity resolution merged them into one case automatically."
- Optional 10 seconds: **Timeline** tab, "sustained since January 2025."

### 4:15 – 4:45 · Forecast
Screen: **Forecast** tab.
- 30 / 60 / 90-day: **81% / 94% / 97%**, each with its drivers (ownership/address/bank links, prior investigations, flag rate of linked providers).
> "Discrete-time hazard model, tested on later snapshots it never saw. Capped at 97% so it never claims certainty."

### 4:45 – 5:30 · Human in the loop: Challenge lab + Decision
Screen: **Challenge lab** tab.
> "Which check should the investigator do first? The lab ranks evidence checks by information gained per review hour, including checks that could **clear** the provider."
- Click **Approve & reveal** on check #1. Belief bars move. "Each check is human-approved and logged."

Screen: **Decision** tab.
- Show the outcome list and the required rationale. "The system recommends; a person decides. Referral needs a **second** person, a supervisor, to approve: four-eyes. Every action is audited."
- (Optional) Record "Request more information" with a one-line rationale.

### 5:30 – 6:00 · Proof it works, and its limits
Screen: **Governance** (or one slide).
- Held-out synthetic worlds never used in training: **16/16 fraudulent providers caught, 0 legitimate providers escalated, 4/4 rings caught as one case.**
- Calibration: ECE **0.17 → 0.006**. 79/79 counterfactual tests pass.
- **Say the weakness out loud:** "If a fraudster cuts their scheme to 10% intensity, we catch 10 of 16. And all of this is synthetic data from our own generator; on real claims the drift monitor tells you where to recalibrate."
> "From thousands of alerts to a short, ranked, explained list, with a human making every call. Thank you."

## If something goes wrong

| Problem | Do this |
|---|---|
| App won't load | Switch to the screenshot folder and keep talking; the story is the same. |
| 3D network slow | Click **2D** in the top-right of the graph. |
| Pipeline needs re-run | Data & pipeline → Regenerate + re-run (≈18 s). Talk over it: "validation runs first; a failed check stops the run and the last good analysis stays live." |
| Running long | Skip Timeline and the Decision recording; never skip Readiness ("do not refer yet") or the limitations line. |

## Likely judge questions

**"You built the data generator *and* the detector. Isn't 100% just grading your own homework?"**
Partly, and we say so. Three things make it more than that:
1. Models are trained on worlds 101–106 and tested on 201–202, which are never seen.
2. Adversarial tests: mimicry (upcode to level 4 not 5) and split identities are still caught.
3. We publish where it breaks: at 10% scheme intensity we catch 10/16. The generator also plants **legitimate anomalies and decoys** specifically to produce false positives, and none are escalated.

**"Governance says 2 decoys surfaced as cases, but you said 0 false positives?"**
Both are true. The 2 decoys appear in the queue (#12, #13) but in the **"Validate context first" / "Explained by context"** lanes, never "Investigate", and they can't be referred. Surfacing them with context is intended; escalating them would be the error.

**"Which approaches, specifically?"** Rules (9 built-in plus analyst rules, versioned, each with benign explanations and a verification step); Isolation Forest against family peers; temporal (CUSUM, change-point, burst); graph (shared owner/address/bank, referral concentration, member overlap); a discrete-time hazard model for 30/60/90 days; isotonic calibration; a fusion layer over 9 detectors.

**"What happens when the system is unsure?"** Cases below the evidence threshold go to "Needs more data" and can't be referred; readiness blocks referral until documentation is reviewed; competing explanations and missing-data rates show on every case; data-validation failures stop the run and keep the last good analysis.

**"Is an LLM making decisions?"** No. The LLM is optional and off by default. Everything shown runs on rules and in-house trained models. If enabled, the LLM only rewrites the deterministic brief, with citation checks; the deterministic brief stays the source of truth.

**"Does it scale?"** 62k lines in about 18 s on a laptop. Claims are processed in pandas per run; state lives in PostgreSQL. The production path is incremental runs per new claim batch, plus the pre-payment **Claim check** screen for single claims.

**"Real data?"** None. Synthetic only, generated in `spotzi/synthdata/gen.py`; hidden labels are stored outside the inference path and used only for evaluation.
