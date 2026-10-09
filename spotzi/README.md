# SpotZⁱ — ClaimShield Nexus

Healthcare payer FWA (fraud, waste, abuse) intelligence for Special Investigations Units. **Synthetic data only — no real or public datasets are used anywhere.** Humans make every decision.

## Run

```bash
cd spotzi
pip install -r requirements.txt
./start.sh                         # PostgreSQL 16 (data/pg) + web app → http://localhost:8000
./stop.sh
```
The app runs on PostgreSQL 16: a local cluster in `data/pg`, connection settings in `data/db.env` (git-ignored). Point `SPOTZI_DB_URL` at a managed PostgreSQL to move it.
Accounts: `data/seed_users.json` (owner-readable only) lists vipul and amith (investigators), reshika (supervisor), raveena (analyst) and ajith (admin). After editing it, run `python3 -m scripts.sync_users`.

## Project layout

```
spotzi/
├── server.py                 entry point (python3 server.py / ./start.sh)
├── start.sh · stop.sh        start/stop PostgreSQL + web server
│
├── api/                      HTTP layer
│   └── app.py                FastAPI routes, auth middleware, CSRF/CSP, RBAC, audit
├── detection/                detection engine
│   ├── pipeline.py           load → validate → detect → connect → forecast → cases
│   ├── rules.py              9 explainable rules + analyst custom-rule language
│   ├── analytics.py          features, Isolation Forest, 30/60/90 hazard forecast, provider graph
│   ├── sentinel.py           case-mix twin, care-pathway model
│   ├── brain.py              change-point, code mix, patient panel, Nexus Brain fusion + learning
│   └── linkgraph.py          link analysis (hospital ↔ doctor ↔ patient ↔ organisation)
├── intelligence/             investigator reasoning
│   ├── briefs.py             ranking, case detail, evidence, Markdown brief
│   ├── lab.py                Challenge Lab (expected information gain)
│   ├── precedents.py         difference-first precedent retrieval
│   └── knowledge.py          knowledge wiki + decision chain
├── ai/                       LLM layer + trained task models
│   ├── llm.py                provider config (DeepSeek, z.ai, OpenAI-compatible, Anthropic, local), feature switches
│   ├── llm_detect.py         chart review, tip structuring, rule drafting (grounded, schema-validated)
│   ├── charts.py             synthetic medical-record system for chart review
│   └── models/               trained per-process models
│       ├── train_all.py      trains + evaluates every model, writes model cards
│       ├── registry.py       versioned artifacts + cards (data/models/)
│       ├── prepay_model.py · chart_model.py · tip_model.py · outcome_model.py
│       └── tipgen.py         synthetic tip corpus
├── operations/               SIU operations
│   ├── ops.py                pre-payment check, recoveries/ROI, documents, tips
│   ├── scope.py              case split / merge
│   ├── notify.py             notifications + email/Slack/webhook outbox
│   └── x12.py                837P / 837I import & export
├── infra/                    platform
│   ├── auth.py               PBKDF2 passwords, sessions, TOTP MFA, OIDC SSO, roles & permissions
│   ├── ledger.py             tamper-evident audit chain (SHA-256) + hashed investigation policy
│   └── dbcompat.py           database connection layer
├── synthdata/                synthetic data
│   ├── gen.py                realistic synthetic claims world (conditions, seasonality, cost-share, schemes, legit anomalies)
│   └── truth.py              hidden entity-level ground truth (evaluation only)
├── evaluation/               measurement
│   ├── engine.py             model validation: truth, calibration, delay, counterfactual, adversarial, ablation, gap, quality
│   └── evaluate_llm.py       chart-review reviewer comparison
├── scripts/                  migrate_to_postgres.py · sync_users.py (load seed_users.json) · audit_tamper_demo.py
├── static/                   web app (PWA): index.html, app.js, styles.css, sw.js
├── tests/test_spotzi.py      55 tests
└── data/                     runtime data (mostly git-ignored)
    ├── synthetic/ · hidden/  demo claims world · its hidden labels (evaluation only)
    ├── pg/ · db.env          PostgreSQL cluster · connection string
    ├── models/               trained model artifacts + cards (+ local sentence encoder)
    ├── secrets/              LLM API key (owner-only file; never in the DB)
    ├── llm.env               optional LLM settings via environment
    ├── evaluation/           evaluation results (JSON)
    ├── training/             generated training and held-out worlds (other seeds)
    └── documents/ · cache/   case attachments · LLM response cache
```

## Database
PostgreSQL 16 holds application state: users, sessions, MFA, decisions, four-eyes approvals, audit log, assignments, notes, notifications/outbox, case scope (split/merge), tips and AI triage, case documents metadata, chart reviews, custom rules, pre-payment log, recoveries, knowledge wiki and settings, plus the tamper-evident audit chain (`audit_chain`). Claims are loaded from CSV / X12 files into memory for each analysis run. The automated tests create their own throwaway database, so they need no setup.

## Common tasks
```bash
python3 -m pytest -q tests                      # or: python3 -m unittest tests.test_spotzi
python3 -m ai.models.train_all                  # retrain all task models (~6 min)
python3 -m evaluation.engine                     # full model validation (synthetic worlds)
python3 -m evaluation.evaluate_llm [--llm]      # chart reviewers (LLM needs a key)
python3 -m scripts.sync_users                  # load accounts from data/seed_users.json
python3 -m scripts.audit_tamper_demo           # show a tampered audit entry being detected (rolled back)
```

## LLM (optional)
An admin opens **Settings → AI & LLM** and chooses:
- **on/off**;
- the **provider** (DeepSeek, z.ai, OpenAI-compatible, Anthropic, or a local server) and the **model**;
- the **API key** (stored on the server, never shown again);
- which features to use: chart review, tip structuring, rule drafting and copilot.

**Test connection** checks the setup. With the LLM off, everything runs on the trained models and rules.

See `../SPOTZI_PRODUCT.md` for the full feature list and `../EVALUATION.md` for measured accuracy.
