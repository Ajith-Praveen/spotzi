# SpotZ^i

End-to-end healthcare payer FWA (fraud, waste, abuse) intelligence prototype. **Synthetic data only.** Humans make every decision.

The responsive internal web app is installable as a PWA. It uses standalone display mode and caches only the application shell for quick startup. Case data, evidence reveals, and human decisions remain server-authoritative; offline users may view an explicit cached shell but cannot submit workflow actions.

## Run

```bash
pip install fastapi uvicorn pandas numpy scikit-learn networkx scipy
cd claimshield && python3 server.py      # → http://localhost:8000
```

First start generates ~64k synthetic claim lines (8 service families, 132 providers, 2,500 members) and runs the whole pipeline in ~7s.

## What it does

| Step | Implementation |
|---|---|
| Load + validate | `pipeline.py` – 9 CSV tables, FK/date/null/coverage checks; a failing run keeps the previous analysis live |
| Detect (rules) | `rules.py` – duplicate, repeat/early-refill, unbundling, upcoding/time mismatch, phantom (inpatient / post-termination / post-death), impossible timing, excessive utilisation. Each flag cites its source row + reason |
| Detect (ML) | `analytics.py` – Isolation Forest (provider, peer-normalised; claim-line) |
| Connect | `analytics.py` – provider graph (referral flow, shared ownership/address/bank, shared members), Louvain communities, "suspicious-tie" subgraph for case grouping |
| Forecast | logistic + gradient-boosting ensemble per 30/60/90-day horizon, biweekly provider snapshots, temporal split without label leakage, calibration + baseline shown |
| Rank | `briefs.rank` – weighted priority (risk, forecast, dollars, member impact, severity, evidence strength) + review-capacity packing; weights/capacity adjustable live |
| Explain | `briefs.case_detail` – evidence w/ sources, timeline, network, competing explanations, confidence, limitations, recommended action; Markdown export |
| Decide | sqlite audit + decisions; written rationale required; four-eyes referral approval; weak-evidence cases abstain and cannot be referred |

Screens: Overview · SIU queue · Case brief (Brief / Evidence / Network / Timeline / Forecast / Challenge lab / Claims / Decision) · Network explorer · Providers & claims · Data & pipeline (regenerate with new seed) · Governance.

## Honest notes

- Hidden scenario truth (`data/hidden/`) is used only for evaluation and forecast labels, never for detection.
- Decoy providers (oncology, dialysis, chain pharmacies) look suspicious but are benign, to exercise the uncertainty paths.
- Synthetic performance numbers do not transfer to real claims.
- Design docs live in `../idea/`.
