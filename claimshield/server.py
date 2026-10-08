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
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, role TEXT, action TEXT, target TEXT, detail TEXT);
    """)
    return c


def audit(actor, role, action, target, detail=""):
    c = db(); c.execute("INSERT INTO audit(ts,actor,role,action,target,detail) VALUES(?,?,?,?,?,?)", (time.strftime("%Y-%m-%d %H:%M:%S"), actor, role, action, target, detail)); c.commit(); c.close()


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
            STATE["status"] = dict(state="idle", step="done", started=None, error=None)
        except Exception as e:
            STATE["status"] = dict(state="error", step="failed", started=None, error=str(e))
    threading.Thread(target=first, daemon=True).start()


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
    q = briefs.rank(s, horizon=horizon, capacity_hours=capacity, statuses=statuses())
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
    q = briefs.rank(S(), weights=w, horizon=horizon, capacity_hours=capacity, statuses=statuses())
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
    return J(dict(ok=True, status=briefs.STATUS_FROM_OUTCOME[outcome]))


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
    df = PT.reset_index()[["provider_id", "name", "family", "specialty", "city", "risk", "rule_score", "anomaly_pct", "graph_score", "n_lines", "paid", "members", "flagged_lines", "flagged_paid", "fc30", "fc60", "fc90", "context_note"]]
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
                  scores={k: r[k] for k in ["risk", "rule_score", "anomaly_pct", "graph_score", "fc30", "fc60", "fc90"]},
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
                  forecast=dict(metrics=run["forecast_metrics"], calibration=run["calibration"]),
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
    return J(dict(available=llm.available(), model=llm.MODEL))


def _llm_guard():
    if not llm.available(): raise HTTPException(503, "No ANTHROPIC_API_KEY set. Deterministic briefs still work; set the key and restart to enable the AI layer.")


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
