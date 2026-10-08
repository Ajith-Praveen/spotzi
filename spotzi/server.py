"""SpotZ^i API + static web app. Run: python3 server.py  → http://localhost:8000"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

import analytics as A
import briefs
import pipeline as PL
from rules import RULES

ROOT = Path(__file__).parent
DB = ROOT / "data" / "app.db"
app = FastAPI(title="SpotZ^i")
STATE: dict = {"S": None, "status": dict(state="idle", step="", started=None, error=None)}
LOCK = threading.Lock()


def clean(o):
    if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)): return [clean(v) for v in o]
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (math.isnan(o) or math.isinf(o)) else float(o)
    if isinstance(o, (np.bool_,)): return bool(o)
    if isinstance(o, (pd.Timestamp, pd.Period)): return str(o)[:10] if isinstance(o, pd.Timestamp) else str(o)
    if o is pd.NaT: return None
    return o


def J(o): return JSONResponse(clean(o))


# ---------------------------------------------------------------- db
def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, outcome TEXT, reason TEXT, reviewer TEXT, role TEXT,
        ts TEXT, run_id TEXT, priority REAL, evidence REAL, confidence TEXT, checks TEXT);
    CREATE TABLE IF NOT EXISTS lab_events(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, run_id TEXT, rule TEXT, outcome TEXT, reviewer TEXT, ts TEXT);
    CREATE TABLE IF NOT EXISTS blueprints(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, run_id TEXT, reviewer TEXT, ts TEXT, precedents TEXT, ack TEXT);
    CREATE TABLE IF NOT EXISTS blueprint_items(id INTEGER PRIMARY KEY AUTOINCREMENT, blueprint_id INTEGER, position INTEGER, text TEXT, why TEXT, sources TEXT, state TEXT, note TEXT, added_by_human INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS precedent_quality(case_id TEXT PRIMARY KEY, status TEXT, reviewer TEXT, reason TEXT, ts TEXT, snapshot TEXT);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, role TEXT, action TEXT, target TEXT, detail TEXT);
    """)
    import knowledge as KN
    KN.schema(c)
    return c


def audit(actor, role, action, target, detail=""):
    c = db(); c.execute("INSERT INTO audit(ts,actor,role,action,target,detail) VALUES(?,?,?,?,?,?)", (time.strftime("%Y-%m-%d %H:%M:%S"), actor, role, action, target, detail)); c.commit(); c.close()


import brain as BR


def brain_now(s):
    """Re-score with weights learned from every recorded human decision (stateless, reproducible)."""
    c = db(); dec = [dict(r) for r in c.execute("SELECT case_id, outcome FROM decisions ORDER BY id").fetchall()]; c.close()
    labels = BR.labels_from_decisions(dec, s["cases"])
    w, b, w0, n = BR.learn(s["PT"], labels)
    sc, ct = BR.score(s["PT"], w, b)
    return sc, ct, w, w0, n


def statuses():
    c = db()
    rows = c.execute("SELECT case_id, outcome FROM decisions ORDER BY id").fetchall(); c.close()
    st = {}
    for r in rows:
        st[r["case_id"]] = briefs.STATUS_FROM_OUTCOME.get(r["outcome"], "In investigation")
    return st


# ---------------------------------------------------------------- run management
CACHE = ROOT / "data" / "cache"


def start_run(seed=None, members=2500):
    with LOCK:
        if STATE["status"]["state"] == "running": return False
        STATE["status"] = dict(state="running", step="starting", started=time.time(), error=None)

    def work():
        try:
            S = PL.run_pipeline(seed=seed, n_members=members, progress=lambda s: STATE["status"].update(step=s))
            STATE["S"] = S
            _ingest(S)
            STATE["status"] = dict(state="idle", step="done", started=None, error=None)
            audit("system", "system", "pipeline_run", S["run"]["run_id"], json.dumps(dict(seed=seed, members=members)))
        except Exception as e:  # fail safe: keep the previous run live
            STATE["status"] = dict(state="error", step="failed", started=None, error=str(e))
            audit("system", "system", "pipeline_failed", "", str(e)[:300])
    threading.Thread(target=work, daemon=True).start()
    return True


@app.on_event("startup")
def boot():
    if not (PL.DATA / "claim_lines.csv").exists():
        import gen; gen.generate(out_dir=PL.DATA)
    STATE["status"] = dict(state="running", step="initial analysis", started=time.time(), error=None)
    def first():
        try:
            STATE["S"] = PL.run_pipeline(progress=lambda s: STATE["status"].update(step=s))
            _ingest(STATE["S"])
            STATE["status"] = dict(state="idle", step="done", started=None, error=None)
        except Exception as e:
            STATE["status"] = dict(state="error", step="failed", started=None, error=str(e))
    threading.Thread(target=first, daemon=True).start()


def _ingest(s):
    import knowledge as KN
    c = db(); KN.bootstrap(c); n = KN.ingest_run(c, s); c.commit(); c.close()
    if n: audit("system", "system", "wiki_ingest", s["run"]["run_id"], f"{n} proposed page update(s)")


def S():
    if STATE["S"] is None: raise HTTPException(503, "Analysis is still running. Try again in a few seconds.")
    return STATE["S"]


@app.get("/api/status")
def status():
    s = STATE["status"]
    return J(dict(state=s["state"], step=s["step"], error=s["error"], ready=STATE["S"] is not None,
                  run=None if STATE["S"] is None else {k: STATE["S"]["run"][k] for k in ("run_id", "as_of", "created", "ruleset", "model", "seconds")}))


@app.post("/api/run")
async def run(req: Request):
    b = await req.json() if (await req.body()) else {}
    ok = start_run(seed=int(b.get("seed", 7)), members=int(b.get("members", 2500)))
    if ok: audit(b.get("reviewer", "analyst"), "analyst", "request_pipeline_run", "", json.dumps(b))
    return J(dict(started=ok))


# ---------------------------------------------------------------- overview
@app.get("/api/overview")
def overview(horizon: int = 60, capacity: float = 96):
    s = S(); L, PT = s["L"], s["PT"]
    q = briefs.rank(s, horizon=horizon, capacity_hours=capacity, statuses=statuses(), brain=brain_now(s)[0])
    rows = q["queue"]
    fl = L[L.any_flag]
    by_rule = [dict(rule=k, name=RULES[k]["name"], lines=int(L[f"f_{k}"].sum()), paid=float(L.loc[L[f"f_{k}"], "paid"].sum())) for k in RULES]
    fam = fl.groupby("family").agg(lines=("line_id", "size"), paid=("paid", "sum")).reset_index()
    tot = L.groupby("family").paid.sum()
    fam["share"] = fam.apply(lambda r: r.paid / tot[r.family], axis=1)
    mt = L.assign(m=L.service_date.dt.to_period("M").astype(str)).groupby("m").agg(paid=("paid", "sum"), flagged=("flag_paid", "sum")).reset_index()
    funnel = [dict(label="Claim lines analysed", value=len(L)), dict(label="Lines flagged by any rule", value=int(L.any_flag.sum())),
              dict(label="Providers with flags", value=int((PT.flagged_lines > 0).sum())), dict(label="Providers above case threshold", value=int((PT.risk >= PL.PRIMARY_RISK).sum())),
              dict(label="Ranked cases", value=len(rows)), dict(label="Inside review capacity", value=sum(1 for r in rows if r["capacity"] == "within"))]
    return J(dict(run=s["run"], kpis=dict(lines=len(L), paid=float(L.paid.sum()), flagged_lines=int(L.any_flag.sum()), flagged_paid=float(L.flag_paid.sum()),
                  cases=len(rows), exposure=sum(r["exposure"] for r in rows), members=int(sum(r["members"] for r in rows)),
                  critical=sum(1 for r in rows if r["severity_label"] == "Critical"), within=sum(1 for r in rows if r["capacity"] == "within"),
                  hours=q["used_hours"], escalating=sum(1 for r in rows if r["escalating"])),
                  funnel=funnel, by_rule=by_rule, by_family=fam.to_dict("records"), monthly=mt.to_dict("records"), top=rows[:5], status=statuses()))


# ---------------------------------------------------------------- queue / cases
@app.get("/api/queue")
def queue(request: Request, horizon: int = 60, capacity: float = 96):
    w = {k[2:]: float(v) for k, v in request.query_params.items() if k.startswith("w_")}
    q = briefs.rank(S(), weights=w, horizon=horizon, capacity_hours=capacity, statuses=statuses(), brain=brain_now(S())[0], sb=llm.SB.state["results"] if llm.SB.state.get("run_id") == STATE["S"]["run"]["run_id"] else None)
    q["weight_labels"] = briefs.WEIGHT_LABELS; q["defaults"] = briefs.DEFAULT_WEIGHTS
    return J(q)


@app.get("/api/queue.csv")
def queue_csv(horizon: int = 60, capacity: float = 96):
    q = briefs.rank(S(), horizon=horizon, capacity_hours=capacity, statuses=statuses())["queue"]
    df = pd.DataFrame(q).drop(columns=["components", "contributions", "signal_flags"])
    return PlainTextResponse(df.to_csv(index=False), media_type="text/csv")


@app.get("/api/cases/{cid}")
def case(cid: str, horizon: int = 60):
    s = S(); d = briefs.case_detail(s, cid, horizon)
    if d is None: raise HTTPException(404, "Unknown case")
    c = db(); rows = [dict(r) for r in c.execute("SELECT * FROM decisions WHERE case_id=? ORDER BY id", (cid,)).fetchall()]; c.close()
    d["decisions"] = rows
    sbr = llm.SB.state["results"] if llm.SB.state.get("run_id") == s["run"]["run_id"] else {}
    d["second_brain"] = [dict(provider_id=p, name=s["PT"].at[p, "name"], first_brain_risk=float(s["PT"].at[p, "risk"]), **sbr[p]) for p in next(x for x in s["cases"] if x["case_id"] == cid)["providers"] if p in sbr]
    d["status"] = statuses().get(cid, "New")
    return J(d)


@app.get("/api/cases/{cid}/brief.md")
def brief_md(cid: str):
    s = S(); d = briefs.case_detail(s, cid)
    if d is None: raise HTTPException(404)
    c = db(); rows = [dict(r) for r in c.execute("SELECT * FROM decisions WHERE case_id=? ORDER BY id", (cid,)).fetchall()]; c.close()
    audit("viewer", "investigator", "export_brief", cid)
    return PlainTextResponse(briefs.brief_markdown(d, rows), media_type="text/markdown", headers={"Content-Disposition": f"attachment; filename={cid}-brief.md"})


OUTCOMES = ["Open investigation", "Request more information", "Monitor", "Close - insufficient evidence", "Close - legitimate explanation", "Recommend referral", "Approve referral", "Reject referral"]


@app.post("/api/cases/{cid}/decision")
async def decide(cid: str, req: Request):
    s = S(); b = await req.json()
    outcome, reason, reviewer, role = b.get("outcome"), (b.get("reason") or "").strip(), (b.get("reviewer") or "").strip(), b.get("role", "investigator")
    if outcome not in OUTCOMES: raise HTTPException(400, "Unknown outcome")
    if len(reason) < 15: raise HTTPException(400, "A written rationale of at least 15 characters is required: decisions are human-owned and must be explainable.")
    if not reviewer: raise HTTPException(400, "Reviewer name is required.")
    case = next((x for x in s["cases"] if x["case_id"] == cid), None)
    if not case: raise HTTPException(404)
    c = db()
    prev = [dict(r) for r in c.execute("SELECT * FROM decisions WHERE case_id=? ORDER BY id", (cid,)).fetchall()]
    if outcome in ("Approve referral", "Reject referral"):
        pend = [p for p in prev if p["outcome"] == "Recommend referral"]
        if not pend or briefs.STATUS_FROM_OUTCOME[prev[-1]["outcome"]] != "Pending supervisor approval":
            c.close(); raise HTTPException(409, "No referral recommendation is pending.")
        if role != "supervisor": c.close(); raise HTTPException(403, "Only a supervisor can approve or reject a referral.")
        if pend[-1]["reviewer"].lower() == reviewer.lower(): c.close(); raise HTTPException(403, "Four-eyes rule: the approver must differ from the recommender.")
    if outcome == "Recommend referral" and case["lane"] == "Needs more data":
        c.close(); raise HTTPException(409, "Evidence is below the referral threshold; request more information first.")
    d = briefs.case_detail(s, cid)
    c.execute("INSERT INTO decisions(case_id,outcome,reason,reviewer,role,ts,run_id,priority,evidence,confidence,checks) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (cid, outcome, reason, reviewer, role, time.strftime("%Y-%m-%d %H:%M:%S"), s["run"]["run_id"], case["risk"], case["evidence"], d["confidence"]["label"], json.dumps(b.get("checks", []))))
    c.commit(); c.close()
    audit(reviewer, role, "decision:" + outcome, cid, reason[:200])
    import knowledge as KN
    cx = db(); last = dict(cx.execute("SELECT * FROM decisions WHERE case_id=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone())
    n = KN.ingest_decision(cx, case, last); cx.commit(); cx.close()
    return J(dict(ok=True, status=briefs.STATUS_FROM_OUTCOME[outcome], wiki_proposals=n))


@app.get("/api/audit")
def audit_log(limit: int = 100):
    c = db(); rows = [dict(r) for r in c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    dec = [dict(r) for r in c.execute("SELECT * FROM decisions ORDER BY id DESC LIMIT 200").fetchall()]; c.close()
    return J(dict(audit=rows, decisions=dec))


# ---------------------------------------------------------------- claims / providers / members
@app.get("/api/claims")
def claims(provider_id: str = "", member_id: str = "", rule: str = "", flagged: bool = True, min_anomaly: float = 0, limit: int = 100, offset: int = 0, sort: str = "claim_anomaly"):
    L = S()["L"]
    m = pd.Series(True, index=L.index)
    if provider_id: m &= L.provider_id == provider_id
    if member_id: m &= L.member_id == member_id
    if rule: m &= L[f"f_{rule}"]
    elif flagged: m &= L.any_flag
    if min_anomaly: m &= L.claim_anomaly >= min_anomaly
    sub = L[m].sort_values(sort if sort in L.columns else "claim_anomaly", ascending=False)
    det = S()["detail"]
    out = []
    for r in sub.iloc[offset: offset + limit].itertuples():
        tags = [k for k in RULES if getattr(r, f"f_{k}")]
        out.append(dict(line_id=r.line_id, claim_id=r.claim_id, date=str(r.service_date.date()), provider_id=r.provider_id, member_id=r.member_id, code=r.code, family=r.family,
                        units=int(r.units), paid=float(r.paid), billed=float(r.billed), dx=r.dx, anomaly=float(r.claim_anomaly), rules=tags,
                        reasons=[det[k].get(r.line_id, "") for k in tags]))
    return J(dict(total=int(m.sum()), rows=out, paid=float(sub.paid.sum())))


@app.get("/api/providers")
def providers():
    PT = S()["PT"]
    cs = {p: c["case_id"] for c in S()["cases"] for p in c["providers"]}
    df = PT.reset_index()[["provider_id", "name", "family", "specialty", "city", "risk", "rule_score", "anomaly_pct", "graph_score", "sentinel", "own_model", "n_lines", "paid", "members", "flagged_lines", "flagged_paid", "fc30", "fc60", "fc90", "context_note"]]
    df["case_id"] = df.provider_id.map(cs)
    return J(df.sort_values("risk", ascending=False).to_dict("records"))


@app.get("/api/providers/{pid}")
def provider(pid: str):
    s = S(); PT = s["PT"]
    if pid not in PT.index: raise HTTPException(404)
    L = s["L"]; sub = L[L.provider_id == pid]
    mg = sub.assign(month=sub.service_date.dt.to_period("M").astype(str)).groupby("month").agg(paid=("paid", "sum"), flagged=("flag_paid", "sum"), lines=("line_id", "size")).reset_index()
    codes = sub.groupby("code").agg(lines=("line_id", "size"), paid=("paid", "sum"), flagged=("any_flag", "sum")).reset_index().sort_values("paid", ascending=False).head(10)
    r = PT.loc[pid]
    return J(dict(provider_id=pid, profile={k: r[k] for k in ["name", "family", "specialty", "city", "npi", "org_id", "address_id", "bank_id", "context_note"]},
                  scores={k: r[k] for k in ["risk", "rule_score", "anomaly_pct", "graph_score", "sentinel", "twin_pct", "path_pct", "oe_paid", "own_model", "fc30", "fc60", "fc90"]},
                  rules={k: dict(name=RULES[k]["name"], lines=int(r[f"n_{k}"]), share=float(r[f"s_{k}"])) for k in RULES},
                  monthly=mg.to_dict("records"), codes=codes.to_dict("records"), network=PL.ego_graph(s, [pid], True, 12),
                  anomaly_drivers=s["adrivers"].get(pid, []), forecast_why=s["fc"]["why"].get(pid, {})))


@app.get("/api/members/{mid}")
def member(mid: str):
    s = S(); L = s["L"]; sub = L[L.member_id == mid].sort_values("service_date")
    if sub.empty: raise HTTPException(404)
    M = s["T"]["members"].set_index("member_id").loc[mid]
    st = s["T"]["stays"]; st = st[st.member_id == mid]
    rows = [dict(date=str(r.service_date.date()), provider=r.provider_id, code=r.code, paid=float(r.paid), rules=[k for k in RULES if getattr(r, f"f_{k}")]) for r in sub.itertuples()]
    return J(dict(member_id=mid, profile=dict(age=M.age, plan=M.plan, region=M.region, term_date=M.term_date, death_date=M.death_date, vulnerable=bool(M.vulnerable)),
                  stays=st.to_dict("records"), lines=rows[-200:], total=len(rows)))


# ---------------------------------------------------------------- network
@app.get("/api/network")
def network():
    s = S(); net = s["net"]
    cs = {p: c["case_id"] for c in s["cases"] for p in c["providers"]}
    nodes = [{**n, "case_id": cs.get(n["id"])} for n in net["nodes"]]
    return J(dict(nodes=nodes, edges=net["edges"], communities=net["communities"], isolated=net["isolated"]))


@app.get("/api/network/ego/{pid}")
def ego(pid: str):
    return J(PL.ego_graph(S(), [pid], True, 14))


# ---------------------------------------------------------------- governance & data
@app.get("/api/governance")
def governance():
    s = S(); run = s["run"]
    return J(dict(run=run, rules=[dict(key=k, **{kk: v for kk, v in spec.items()}) for k, spec in RULES.items()],
                  forecast=dict(metrics=run["forecast_metrics"], calibration=run["calibration"]), own_model=run.get("own_model"),
                  principles=[
                      "Human in the loop: the system ranks and explains; people open, scope, close, and refer cases. There is no automated adverse action.",
                      "Four-eyes referral: a recommended referral needs a different supervisor to approve it, with written rationale.",
                      "Abstain on weak evidence: cases below the evidence threshold are held in 'Needs more data' and cannot be referred.",
                      "Uncertainty is visible: competing explanations, missing-data rates and confidence are shown with every case.",
                      "Hidden scenario labels are isolated from inference and used only for evaluation and forecast labels (simulated confirmed outcomes).",
                      "Synthetic data only. No real member, provider or payer data. Performance numbers do not transfer to production.",
                      "Every decision, export and pipeline run is written to an audit log with the run, ruleset and model versions."],
                  limitations=["Forecast labels come from simulated outcomes; real labels are delayed, biased towards what was investigated, and noisy.",
                               "Peer baselines are by service family, not specialty; panel mix can cause false positives (see the oncology and dialysis decoys).",
                               "Claims run-out is not modelled; shared-member graph edges can link unrelated providers.",
                               "Rules reflect simplified, illustrative policy thresholds and must be tuned with clinical and coding experts."]))


@app.get("/api/data")
def data_overview():
    s = S(); T = s["T"]
    tabs = []
    for k, v in T.items():
        if v is None or k == "truth": continue
        tabs.append(dict(name=k, rows=int(len(v)), columns=list(v.columns), sample=clean(v.head(5).astype(str).to_dict("records"))))
    return J(dict(tables=tabs, validation=s["run"]["validation"], log=s["run"]["log"], codes=[dict(code=c, family=v[0], description=v[1], price=v[2]) for c, v in __import__("gen").CODES.items()]))



# ---------------------------------------------------------------- LLM (grounded, optional)
import llm
NARR: dict = {}


@app.get("/api/llm/status")
def llm_status():
    return J(dict(available=llm.available(), model=llm.model_name(), provider=llm.provider()))


def _llm_guard():
    if not llm.available(): raise HTTPException(503, "No LLM available. Start a local model server (see README: mlx_lm.server on :8080) or set a valid ANTHROPIC_API_KEY. Deterministic briefs still work.")


@app.post("/api/cases/{cid}/narrative")
async def narrative(cid: str, req: Request):
    _llm_guard(); s = S(); d = briefs.case_detail(s, cid)
    if d is None: raise HTTPException(404)
    key = (s["run"]["run_id"], cid)
    if key in NARR: return J({**NARR[key], "cached": True})
    try:
        out = await __import__("asyncio").to_thread(llm.narrate, d)
    except Exception as e:
        audit("system", "system", "llm_failed", cid, str(e)[:200]); raise HTTPException(502, f"AI layer unavailable ({type(e).__name__}); the deterministic brief is unaffected.")
    NARR[key] = out; audit("system", "system", "llm_narrative", cid, f"{out['model']} grounded={out['grounded']}")
    return J(out)


@app.post("/api/cases/{cid}/ask")
async def ask_case(cid: str, req: Request):
    _llm_guard(); s = S(); d = briefs.case_detail(s, cid)
    if d is None: raise HTTPException(404)
    b = await req.json(); q = (b.get("question") or "").strip()
    if not q: raise HTTPException(400, "Empty question")
    try:
        out = await __import__("asyncio").to_thread(llm.ask, d, q, b.get("history", []))
    except Exception as e:
        audit("system", "system", "llm_failed", cid, str(e)[:200]); raise HTTPException(502, f"AI layer unavailable ({type(e).__name__}).")
    audit(b.get("reviewer") or "viewer", "investigator", "llm_question", cid, q[:150])
    return J(out)


@app.get("/api/secondbrain")
def sb_state():
    s = S(); st = llm.SB.state; cur = st.get("run_id") == s["run"]["run_id"]
    res = st["results"] if cur else {}
    return J(dict(available=llm.available(), model=llm.model_name(), status=st["status"] if cur else "idle", done=st["done"] if cur else 0, total=st["total"] if cur else 0,
                  error=st["error"] if cur else None, failed=st["failed"] if cur else {}, rows=llm.compare(s, res), scorecard=llm.scorecard(s, res) if res else None))


@app.post("/api/secondbrain/run")
async def sb_run(req: Request):
    _llm_guard(); s = S()
    b = await req.json() if (await req.body()) else {}
    ok = llm.SB.start(s, limit=int(b.get("limit", 45)))
    if ok: audit("analyst", "analyst", "second_brain_run", s["run"]["run_id"], f"model={llm.model_name()} limit={b.get('limit', 45)}")
    return J(dict(started=ok))


@app.get("/api/secondbrain/{pid}")
def sb_provider(pid: str):
    s = S(); st = llm.SB.state
    if st.get("run_id") != s["run"]["run_id"] or pid not in st["results"]: raise HTTPException(404, "No second-brain review for this provider yet")
    r = st["results"][pid]; PT = s["PT"]
    first = dict(risk=float(PT.at[pid, "risk"]), rule_score=float(PT.at[pid, "rule_score"]), anomaly_pct=float(PT.at[pid, "anomaly_pct"]), graph_score=float(PT.at[pid, "graph_score"]),
                 rules={k: int(PT.at[pid, f"n_{k}"]) for k in RULES})
    return J(dict(provider_id=pid, name=PT.at[pid, "name"], family=PT.at[pid, "family"], review=r, first_brain=first, dossier=llm.dossier(s, pid)))


# ---------------------------------------------------------------- Evidence Challenge Lab (doc 21)
import lab
import precedents as PR
SEED_LIB = PR.seed_library()


def _case_obj(s, cid):
    return next((x for x in s["cases"] if x["case_id"] == cid), None)


def _truth_share(s, c, rule):
    L = s["L"]
    if "_truth" not in L: return None
    W = L[L.service_date > pd.Timestamp(s["run"]["as_of"]) - pd.Timedelta(days=PL.LOOKBACK)]
    sub = W[W.provider_id.isin(c["primary"]) & W.any_flag]
    if rule != "GRAPH": sub = sub[sub[f"f_{rule}"]]
    return float(sub._truth.mean()) if len(sub) else None


def _lab_events(cid, run_id):
    c = db(); rows = [dict(r) for r in c.execute("SELECT * FROM lab_events WHERE case_id=? AND run_id=? ORDER BY id", (cid, run_id)).fetchall()]; c.close()
    return rows


@app.get("/api/cases/{cid}/lab")
def lab_state(cid: str):
    s = S(); c = _case_obj(s, cid)
    if not c: raise HTTPException(404)
    d = briefs.case_detail(s, cid)
    ev = _lab_events(cid, s["run"]["run_id"])
    out = lab.analyse(d, ev, c["exposure"])
    out["fragility"] = lab.fragility(c, d)
    out["vault"] = "_truth" in s["L"]
    out["case_exposure"] = c["exposure"]
    return J(out)


@app.post("/api/cases/{cid}/lab/reveal")
async def lab_reveal(cid: str, req: Request):
    s = S(); c = _case_obj(s, cid); b = await req.json()
    if not c: raise HTTPException(404)
    rule, reviewer = b.get("rule"), (b.get("reviewer") or "").strip()
    if not reviewer: raise HTTPException(400, "Reviewer name is required: a human approves each evidence check.")
    d = briefs.case_detail(s, cid)
    if rule not in lab.available_checks(d): raise HTTPException(400, "Unknown check")
    if any(e["rule"] == rule for e in _lab_events(cid, s["run"]["run_id"])): raise HTTPException(409, "Check already performed")
    share = _truth_share(s, c, rule)
    if share is None: raise HTTPException(409, "No synthetic evidence vault is available for this dataset.")
    outcome = lab.vault_outcome(cid, rule, d, share)
    cx = db(); cx.execute("INSERT INTO lab_events(case_id,run_id,rule,outcome,reviewer,ts) VALUES(?,?,?,?,?,?)", (cid, s["run"]["run_id"], rule, outcome, reviewer, time.strftime("%Y-%m-%d %H:%M:%S"))); cx.commit(); cx.close()
    audit(reviewer, "investigator", "evidence_check_revealed", cid, f"{rule}: {outcome}")
    return J(dict(ok=True, outcome=outcome))


# ---------------------------------------------------------------- Precedent Intelligence (doc 22)
def _live_precedents(s):
    c = db(); rows = [dict(r) for r in c.execute("SELECT * FROM precedent_quality WHERE status='approved'").fetchall()]; c.close()
    out = []
    for r in rows:
        snap = json.loads(r["snapshot"]); snap["quality"] = "approved"; out.append(snap)
    return out


@app.get("/api/cases/{cid}/precedents")
def precedents_for(cid: str):
    s = S(); c = _case_obj(s, cid)
    if not c: raise HTTPException(404)
    d = briefs.case_detail(s, cid)
    fp = PR.fingerprint(c, d)
    lib = SEED_LIB + [p for p in _live_precedents(s) if p.get("source_case") != cid]
    res = PR.retrieve(fp, lib, 5)
    best = res[0]["similarity"] if res else 0
    cx = db(); bp = cx.execute("SELECT id FROM blueprints WHERE case_id=? AND run_id=? ORDER BY id DESC LIMIT 1", (cid, s["run"]["run_id"])).fetchone(); cx.close()
    audit("viewer", "investigator", "precedent_retrieval", cid, f"{len(res)} matches, best {best:.2f}")
    return J(dict(fingerprint=fp, matches=res, library_size=len(lib), live_precedents=len(lib) - len(SEED_LIB),
                  safe_precedent=bool(res) and best >= .6, blueprint_id=bp["id"] if bp else None,
                  notice="Retrieval similarity is not a probability of fraud and not decision confidence. A prior outcome never binds this case."))


@app.post("/api/cases/{cid}/blueprint")
async def make_blueprint(cid: str, req: Request):
    s = S(); c = _case_obj(s, cid); b = await req.json()
    if not c: raise HTTPException(404)
    reviewer = (b.get("reviewer") or "").strip()
    if not reviewer: raise HTTPException(400, "Reviewer name is required.")
    d = briefs.case_detail(s, cid); fp = PR.fingerprint(c, d)
    lib = SEED_LIB + [p for p in _live_precedents(s) if p.get("source_case") != cid]
    res = PR.retrieve(fp, lib, 5)
    sel = set(b.get("precedents") or [m["precedent"]["id"] for m in res[:3]])
    chosen = [m for m in res if m["precedent"]["id"] in sel]
    if any(m["differences"] for m in chosen) and not b.get("acknowledged_differences"):
        raise HTTPException(409, "Acknowledge the material differences between this case and the selected precedents before using a blueprint.")
    items = PR.blueprint_items(res, sel)
    cx = db(); cur = cx.execute("INSERT INTO blueprints(case_id,run_id,reviewer,ts,precedents,ack) VALUES(?,?,?,?,?,?)", (cid, s["run"]["run_id"], reviewer, time.strftime("%Y-%m-%d %H:%M:%S"), json.dumps(sorted(sel)), "yes" if b.get("acknowledged_differences") else "n/a"))
    bid = cur.lastrowid
    for i, it in enumerate(items):
        cx.execute("INSERT INTO blueprint_items(blueprint_id,position,text,why,sources,state,note) VALUES(?,?,?,?,?,?,?)", (bid, i, it["text"], it["why"], json.dumps(it["sources"]), "todo", ""))
    cx.commit(); cx.close()
    audit(reviewer, "investigator", "blueprint_created", cid, f"precedents={sorted(sel)}")
    return J(dict(ok=True, blueprint_id=bid))


@app.get("/api/cases/{cid}/blueprint")
def get_blueprint(cid: str):
    s = S(); cx = db()
    bp = cx.execute("SELECT * FROM blueprints WHERE case_id=? AND run_id=? ORDER BY id DESC LIMIT 1", (cid, s["run"]["run_id"])).fetchone()
    if not bp: cx.close(); return J(dict(blueprint=None))
    items = [dict(r) for r in cx.execute("SELECT * FROM blueprint_items WHERE blueprint_id=? ORDER BY position", (bp["id"],)).fetchall()]; cx.close()
    for i in items: i["sources"] = json.loads(i["sources"])
    return J(dict(blueprint=dict(bp), items=items, note="Completing the checklist speeds review but never preselects an outcome."))


@app.patch("/api/blueprint/items/{iid}")
async def patch_item(iid: int, req: Request):
    b = await req.json(); cx = db()
    st, note, who = b.get("state"), b.get("note", ""), b.get("reviewer", "viewer")
    if st not in ("todo", "done", "skipped"): cx.close(); raise HTTPException(400, "Bad state")
    if st == "skipped" and len(note.strip()) < 5: cx.close(); raise HTTPException(400, "A reason is required to skip an item.")
    cx.execute("UPDATE blueprint_items SET state=?, note=? WHERE id=?", (st, note, iid)); cx.commit(); cx.close()
    audit(who, "investigator", f"blueprint_item_{st}", str(iid), note[:100])
    return J(dict(ok=True))


@app.post("/api/blueprint/{bid}/items")
async def add_item(bid: int, req: Request):
    b = await req.json(); txt = (b.get("text") or "").strip()
    if len(txt) < 4: raise HTTPException(400, "Describe the item")
    cx = db(); pos = cx.execute("SELECT COALESCE(MAX(position),0)+1 FROM blueprint_items WHERE blueprint_id=?", (bid,)).fetchone()[0]
    cx.execute("INSERT INTO blueprint_items(blueprint_id,position,text,why,sources,state,note,added_by_human) VALUES(?,?,?,?,?,?,?,1)", (bid, pos, txt, "Added by reviewer", "[]", "todo", "")); cx.commit(); cx.close()
    return J(dict(ok=True))


@app.get("/api/precedents/candidates")
def precedent_candidates():
    s = S(); cx = db()
    dec = [dict(r) for r in cx.execute("SELECT * FROM decisions ORDER BY id").fetchall()]
    q = {r["case_id"]: dict(r) for r in cx.execute("SELECT * FROM precedent_quality").fetchall()}; cx.close()
    last = {}
    for d in dec: last[d["case_id"]] = d
    out = []
    for cid, d in last.items():
        if d["outcome"].startswith("Close") or d["outcome"] == "Approve referral":
            out.append(dict(case_id=cid, outcome=d["outcome"], reason=d["reason"], reviewer=d["reviewer"], ts=d["ts"], quality=q.get(cid, {}).get("status", "pending")))
    return J(out)


@app.post("/api/precedents/{cid}/quality")
async def precedent_quality(cid: str, req: Request):
    s = S(); b = await req.json(); c = _case_obj(s, cid)
    if not c: raise HTTPException(404)
    if b.get("role") != "supervisor": raise HTTPException(403, "Only a supervisor can approve a precedent.")
    reviewer, action, reason = (b.get("reviewer") or "").strip(), b.get("action"), (b.get("reason") or "").strip()
    if action not in ("approve", "reject") or not reviewer or len(reason) < 10: raise HTTPException(400, "Action, reviewer and a written reason (10+ chars) are required.")
    cx = db(); dec = [dict(r) for r in cx.execute("SELECT * FROM decisions WHERE case_id=? ORDER BY id", (cid,)).fetchall()]
    if not dec or not (dec[-1]["outcome"].startswith("Close") or dec[-1]["outcome"] == "Approve referral"): cx.close(); raise HTTPException(409, "Only closed or referral-approved cases can become precedents.")
    if dec[-1]["reviewer"].lower() == reviewer.lower(): cx.close(); raise HTTPException(403, "Four-eyes rule: the quality reviewer must differ from the decision maker.")
    d = briefs.case_detail(s, cid); fp = PR.fingerprint(c, d)
    snap = dict(id=f"PREC-LIVE-{cid}", code="live", title=c["type"], family=fp["family"], setting=fp["setting"], rules=fp["rules"], motif=fp["motif"], ownership=fp["ownership"],
                exceptions=fp["exceptions"], coverage=fp["coverage"], escalating=fp["escalating"], anomaly=fp["anomaly"], exposure_band=fp["exposure_band"], member_band=fp["member_band"],
                checks=[dict(check=ch["check"], result="performed in live review") for ch in d["checks"][:3]], outcome=dec[-1]["outcome"], rationale=dec[-1]["reason"],
                reviewer_role=dec[-1]["role"], closed=dec[-1]["ts"][:10], source="LIVE human review (quality-approved)", source_case=cid)
    cx.execute("INSERT OR REPLACE INTO precedent_quality(case_id,status,reviewer,reason,ts,snapshot) VALUES(?,?,?,?,?,?)", (cid, "approved" if action == "approve" else "rejected", reviewer, reason, time.strftime("%Y-%m-%d %H:%M:%S"), json.dumps(snap))); cx.commit(); cx.close()
    audit(reviewer, "supervisor", f"precedent_{action}", cid, reason[:150])
    return J(dict(ok=True))


@app.get("/api/brain")
def brain_api():
    s = S(); sc, ct, w, w0, n = brain_now(s); PT = s["PT"]
    feed = BR.feed(s, sc, ct, w, w0, n)
    case_of = {p: c["case_id"] for c in s["cases"] for p in c["providers"]}
    top = [dict(provider_id=p, name=PT.at[p, "name"], family=PT.at[p, "family"], brain=float(sc[p]), risk=float(PT.at[p, "risk"]), case_id=case_of.get(p),
                parts={k: float(ct.at[p, k]) for k, *_ in BR.DETECTORS}) for p in sc.sort_values(ascending=False).index[:25]]
    ev = s["run"].get("evaluation", {})
    auc = None
    if "_truth" in s["L"]:
        from sklearn.metrics import roc_auc_score
        tp = s["L"][s["L"]._truth].groupby("provider_id").size(); truth = set(tp[tp >= 20].index); y = [int(p in truth) for p in PT.index]
        auc = {lbl: float(roc_auc_score(y, PT[col].fillna(0))) for k, col, lbl, _ in BR.DETECTORS if col in PT}
        auc["Nexus Brain (fused)"] = float(roc_auc_score(y, sc.reindex(PT.index)))
        held = [p for p in PT.index if s["L"][(s["L"].provider_id == p) & s["L"]._scenario.str.startswith("S9")].shape[0] >= 20]
        auc_held = [dict(provider=PT.at[p, "name"], rules=float(PT.at[p, "rule_score"]), brain=float(sc[p]), brain_rank=int((sc > sc[p]).sum() + 1), risk=float(PT.at[p, "risk"]), case_id=case_of.get(p)) for p in held]
    else:
        auc_held = []
    return J(dict(detectors=[dict(key=k, label=lbl, prior=float(a), learned=float(b_)) for (k, _, lbl, _), a, b_ in zip(BR.DETECTORS, w0, w)], decisions_used=n,
                  feed=feed[:40], top=top, auc=auc, held_out=auc_held))


# ---------------------------------------------------------------- Knowledge wiki + decision chain
import knowledge as KN


@app.get("/api/wiki")
def wiki_index():
    c = db()
    pages = [dict(slug=r["slug"], kind=r["kind"], title=r["title"], version=r["version"], updated=r["updated"], author=r["author"]) for r in c.execute("SELECT * FROM wiki_pages ORDER BY kind, title").fetchall()]
    props = [dict(r) for r in c.execute("SELECT id, slug, kind, title, reason, lint, status, created, source FROM wiki_proposals WHERE status='pending' ORDER BY id DESC").fetchall()]
    hist = [dict(r) for r in c.execute("SELECT slug, version, author, ts, note FROM wiki_history ORDER BY id DESC LIMIT 25").fetchall()]
    c.close()
    for p in props: p["lint"] = json.loads(p["lint"])
    return J(dict(pages=pages, proposals=props, history=hist))


@app.get("/api/wiki/page")
def wiki_page(slug: str):
    c = db(); r = c.execute("SELECT * FROM wiki_pages WHERE slug=?", (slug,)).fetchone()
    hist = [dict(x) for x in c.execute("SELECT version, author, ts, note FROM wiki_history WHERE slug=? ORDER BY version DESC", (slug,)).fetchall()]
    back = [dict(slug=x["slug"], title=x["title"]) for x in c.execute("SELECT slug, title FROM wiki_pages WHERE body LIKE ?", (f"%[[{slug}]]%",)).fetchall()]
    pend = c.execute("SELECT id FROM wiki_proposals WHERE slug=? AND status='pending'", (slug,)).fetchone(); c.close()
    if not r: raise HTTPException(404, "Page not approved yet")
    return J(dict(page=dict(r), history=hist, backlinks=back, pending_proposal=pend["id"] if pend else None))


@app.get("/api/wiki/search")
def wiki_search(q: str):
    c = db(); res = KN.search(c, q, 10); c.close()
    return J(res)


@app.get("/api/wiki/proposals/{pid}")
def wiki_proposal(pid: int):
    c = db(); r = c.execute("SELECT * FROM wiki_proposals WHERE id=?", (pid,)).fetchone()
    if not r: c.close(); raise HTTPException(404)
    old = c.execute("SELECT body, version FROM wiki_pages WHERE slug=?", (r["slug"],)).fetchone(); c.close()
    d = dict(r); d["lint"] = json.loads(d["lint"]); d["current"] = dict(old) if old else None
    return J(d)


@app.post("/api/wiki/proposals/{pid}/review")
async def wiki_review(pid: int, req: Request):
    b = await req.json(); action, reviewer, note = b.get("action"), (b.get("reviewer") or "").strip(), (b.get("note") or "").strip()
    if action not in ("approve", "reject") or not reviewer: raise HTTPException(400, "Action and reviewer name are required.")
    c = db(); r = c.execute("SELECT * FROM wiki_proposals WHERE id=?", (pid,)).fetchone()
    if not r or r["status"] != "pending": c.close(); raise HTTPException(409, "Proposal is not pending")
    lint = json.loads(r["lint"])
    if action == "approve" and any(x["level"] == "block" for x in lint): c.close(); raise HTTPException(409, "Lint blocks approval: " + "; ".join(x["detail"] for x in lint if x["level"] == "block"))
    if action == "approve" and any(x["level"] == "review" for x in lint) and len(note) < 10: c.close(); raise HTTPException(400, "This update changes a prior conclusion or wording; add a review note (10+ characters).")
    if action == "approve": v = KN.apply(c, pid, reviewer, note)
    else: c.execute("UPDATE wiki_proposals SET status='rejected', reviewer=?, review_note=? WHERE id=?", (reviewer, note, pid)); v = None
    c.commit(); c.close()
    audit(reviewer, b.get("role", "reviewer"), f"wiki_{action}", r["slug"], note[:150])
    return J(dict(ok=True, version=v))


@app.post("/api/wiki/proposals/approve-clean")
async def wiki_approve_clean(req: Request):
    """Bulk-approve proposals whose lint is fully clean (named reviewer still required)."""
    b = await req.json(); reviewer = (b.get("reviewer") or "").strip()
    if not reviewer: raise HTTPException(400, "Reviewer name is required.")
    c = db(); n = 0
    for r in c.execute("SELECT id, lint FROM wiki_proposals WHERE status='pending'").fetchall():
        if all(x["level"] == "ok" for x in json.loads(r["lint"])):
            KN.apply(c, r["id"], reviewer, "bulk approval of lint-clean updates"); n += 1
    c.commit(); c.close(); audit(reviewer, "reviewer", "wiki_bulk_approve", "", f"{n} pages")
    return J(dict(approved=n))


@app.get("/api/cases/{cid}/chain")
def case_chain(cid: str):
    s = S(); c = _case_obj(s, cid)
    if not c: raise HTTPException(404)
    d = briefs.case_detail(s, cid)
    labst = lab.analyse(d, _lab_events(cid, s["run"]["run_id"]), c["exposure"])
    fp = PR.fingerprint(c, d); prec = PR.retrieve(fp, SEED_LIB + [p for p in _live_precedents(s) if p.get("source_case") != cid], 3)
    cx = db(); out = KN.decision_chain(cx, s, c, d, labst, prec); cx.close()
    return J(out)

app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(ROOT / "static" / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/spotzi-icon.svg")
def app_icon():
    return FileResponse(ROOT / "static" / "spotzi-icon.svg", media_type="image/svg+xml")


@app.get("/sw.js")
def service_worker():
    return FileResponse(ROOT / "static" / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
