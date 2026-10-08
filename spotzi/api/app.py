"""SpotZⁱ API + static web app. Run: python3 server.py  → http://localhost:8000"""
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

from detection import analytics as A
from intelligence import briefs
from detection import pipeline as PL
from detection.rules import RULES

ROOT = Path(__file__).resolve().parents[1]
import os
_envf = ROOT / "data" / "db.env"
if _envf.exists() and "SPOTZI_DB_URL" not in os.environ and "SPOTZI_DB" not in os.environ:
    for _l in _envf.read_text().splitlines():
        if _l.startswith("SPOTZI_DB_URL="): os.environ["SPOTZI_DB_URL"] = _l.split("=", 1)[1].strip()
DB = Path(os.environ.get("SPOTZI_DB", ROOT / "data" / "app.db"))
USERS_FILE = Path(os.environ.get("SPOTZI_USERS_FILE", ROOT / "data" / "seed_users.json"))
from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app_):
    boot()
    try: load_llm_settings()
    except Exception as e: print("SpotZⁱ: LLM settings not loaded:", e)
    yield


app = FastAPI(title="SpotZⁱ", lifespan=_lifespan)
from infra import auth as AU
from fastapi.responses import Response

PUBLIC_API = {"/api/login", "/api/login/mfa", "/api/logout", "/api/me", "/api/sso/config", "/api/sso/login", "/api/sso/callback"}
MFA_OPEN = {"/api/me", "/api/mfa/begin", "/api/mfa/confirm", "/api/logout", "/api/status"}
CONTRACT = "4"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
       "font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


@app.middleware("http")
async def require_login(request: Request, call_next):
    p = request.url.path
    if p.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
        from urllib.parse import urlparse
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
        cv = request.headers.get("x-spotzi-contract")
        if cv and cv != CONTRACT:
            return JSONResponse({"detail": "SpotZⁱ was updated. Refresh the page before continuing.", "refresh": True}, status_code=409)
    if p.startswith("/api/") and p not in PUBLIC_API:
        c = db(); u = AU.user_for(c, request.cookies.get(AU.COOKIE))
        if u:
            row = c.execute("SELECT mfa_enabled FROM users WHERE id=?", (u["id"],)).fetchone()
            u["mfa_enabled"] = bool(row["mfa_enabled"]); req_roles = AU.setting(c, "mfa_required_roles", [])
            u["mfa_required"] = u["role"] in req_roles
        c.close()
        if not u: return JSONResponse({"detail": "Sign in required"}, status_code=401)
        if u["mfa_required"] and not u["mfa_enabled"] and p not in MFA_OPEN:
            return JSONResponse({"detail": "mfa_enrollment_required"}, status_code=403)
        request.state.user = u
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-SpotZi-Contract"] = CONTRACT
    if p.startswith("/api/"): resp.headers["Cache-Control"] = "no-store"
    return resp


def me(req: Request):
    return getattr(req.state, "user", None)


def need(req: Request, perm: str):
    u = me(req)
    if not AU.can(u, perm): raise HTTPException(403, f"Your role ({u['role'] if u else 'none'}) cannot do this.")
    return u


async def body(req: Request):
    """Request JSON with identity fields stamped by the server from the session (clients cannot impersonate)."""
    raw = await req.body()
    b = json.loads(raw) if raw else {}
    u = me(req)
    if u: b["reviewer"], b["role"] = u["name"], u["role"]
    return b


def notify(username, kind, text, link=""):
    from operations import notify as NT
    c = db(); c.execute("INSERT INTO notifications(username,ts,kind,text,link) VALUES(?,?,?,?,?)", (username, time.strftime("%Y-%m-%d %H:%M:%S"), kind, text, link))
    u = c.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
    if u: NT.enqueue(c, u, text, link)
    c.commit(); c.close()


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
_SCHEMA_READY = set()


def db_target():
    return os.environ.get("SPOTZI_DB_URL") or str(DB)


def db():
    from infra import dbcompat
    url = os.environ.get("SPOTZI_DB_URL")
    if not url: DB.parent.mkdir(parents=True, exist_ok=True)
    c = dbcompat.connect(url=url, path=DB)
    if db_target() in _SCHEMA_READY: return c
    _schema(c); c.commit(); _SCHEMA_READY.add(db_target())
    return c


def _schema(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, outcome TEXT, reason TEXT, reviewer TEXT, role TEXT,
        ts TEXT, run_id TEXT, priority REAL, evidence REAL, confidence TEXT, checks TEXT);
    CREATE TABLE IF NOT EXISTS lab_events(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, run_id TEXT, rule TEXT, outcome TEXT, reviewer TEXT, ts TEXT);
    CREATE TABLE IF NOT EXISTS blueprints(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, run_id TEXT, reviewer TEXT, ts TEXT, precedents TEXT, ack TEXT);
    CREATE TABLE IF NOT EXISTS blueprint_items(id INTEGER PRIMARY KEY AUTOINCREMENT, blueprint_id INTEGER, position INTEGER, text TEXT, why TEXT, sources TEXT, state TEXT, note TEXT, added_by_human INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS precedent_quality(case_id TEXT PRIMARY KEY, status TEXT, reviewer TEXT, reason TEXT, ts TEXT, snapshot TEXT);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, role TEXT, action TEXT, target TEXT, detail TEXT);
    """)
    from intelligence import knowledge as KN
    KN.schema(c)
    from infra import auth as AU
    AU.schema(c); AU.migrate(c)
    from operations import notify as NT
    NT.schema(c)
    from operations import scope as SC
    SC.schema(c)
    from operations import ops as OP
    OP.schema(c)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY, value TEXT, updated_by TEXT, ts TEXT);""")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS case_assign(case_id TEXT PRIMARY KEY, assignee TEXT, assignee_name TEXT, assigned_by TEXT, ts TEXT, due TEXT);
    CREATE TABLE IF NOT EXISTS case_notes(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, author TEXT, role TEXT, ts TEXT, text TEXT);
    CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, ts TEXT, kind TEXT, text TEXT, link TEXT, read INTEGER DEFAULT 0);
    """)


def audit(actor, role, action, target, detail=""):
    c = db(); c.execute("INSERT INTO audit(ts,actor,role,action,target,detail) VALUES(?,?,?,?,?,?)", (time.strftime("%Y-%m-%d %H:%M:%S"), actor, role, action, target, detail)); c.commit(); c.close()


from detection import brain as BR


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


def start_run(seed=None, members=2500, data_dir=None):
    with LOCK:
        if STATE["status"]["state"] == "running": return False
        STATE["status"] = dict(state="running", step="starting", started=time.time(), error=None)

    def work():
        try:
            S = PL.run_pipeline(data_dir=data_dir or PL.DATA, seed=seed if data_dir is None else None, n_members=members, progress=lambda s: STATE["status"].update(step=s), custom_rules=_active_rules())
            if data_dir is not None: STATE["data_dir"] = data_dir
            S["run"]["dataset"] = "synthetic" if data_dir is None or Path(data_dir) == PL.DATA else Path(data_dir).name
            STATE["S"] = S
            _ingest(S)
            STATE["status"] = dict(state="idle", step="done", started=None, error=None)
            audit("system", "system", "pipeline_run", S["run"]["run_id"], json.dumps(dict(seed=seed, members=members)))
        except Exception as e:  # fail safe: keep the previous run live
            STATE["status"] = dict(state="error", step="failed", started=None, error=str(e))
            audit("system", "system", "pipeline_failed", "", str(e)[:300])
    threading.Thread(target=work, daemon=True).start()
    return True


def boot():
    c = db()
    from operations import notify as NT
    NT.start_worker(db)
    if AU.seed(c, USERS_FILE): print(f"SpotZⁱ: created local demo accounts -> {USERS_FILE}")
    c.commit(); c.close()
    if not (PL.DATA / "claim_lines.csv").exists():
        from synthdata import gen; gen.generate(out_dir=PL.DATA)
    STATE["status"] = dict(state="running", step="initial analysis", started=time.time(), error=None)
    def first():
        try:
            STATE["S"] = PL.run_pipeline(progress=lambda s: STATE["status"].update(step=s), custom_rules=_active_rules())
            _ingest(STATE["S"])
            STATE["status"] = dict(state="idle", step="done", started=None, error=None)
        except Exception as e:
            STATE["status"] = dict(state="error", step="failed", started=None, error=str(e))
    threading.Thread(target=first, daemon=True).start()


def _active_rules():
    try:
        c = db(); rows = [dict(id=r["id"], name=r["name"], conditions=json.loads(r["conditions"])) for r in c.execute("SELECT * FROM custom_rules WHERE active=1").fetchall()]; c.close()
        return rows
    except Exception:
        return []


def _ingest(s):
    from operations import scope as SC
    c0 = db(); SC.rebuild(s, c0); c0.close()
    from intelligence import knowledge as KN
    c = db(); KN.bootstrap(c); n = KN.ingest_run(c, s); c.commit(); c.close()
    if n: audit("system", "system", "wiki_ingest", s["run"]["run_id"], f"{n} proposed page update(s)")


def S():
    if STATE["S"] is None: raise HTTPException(503, "Analysis is still running. Try again in a few seconds.")
    return STATE["S"]


@app.get("/api/status")
def status():
    s = STATE["status"]
    return J(dict(state=s["state"], step=s["step"], error=s["error"], ready=STATE["S"] is not None,
                  run=None if STATE["S"] is None else {k: STATE["S"]["run"].get(k) for k in ("run_id", "as_of", "created", "ruleset", "model", "seconds", "dataset")}))


@app.post("/api/run")
async def run(req: Request):
    need(req, "run_models")
    b = await body(req)
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
    q = briefs.rank(S(), weights=w, horizon=horizon, capacity_hours=capacity, statuses=statuses(), brain=brain_now(S())[0])
    q["weight_labels"] = briefs.WEIGHT_LABELS; q["defaults"] = briefs.DEFAULT_WEIGHTS
    c = db(); asg = {r["case_id"]: r["assignee_name"] for r in c.execute("SELECT case_id, assignee_name FROM case_assign").fetchall()}; c.close()
    for r in q["queue"]: r["assignee"] = asg.get(r["case_id"])
    return J(q)


@app.get("/api/queue.csv")
def queue_csv(horizon: int = 60, capacity: float = 96):
    q = briefs.rank(S(), horizon=horizon, capacity_hours=capacity, statuses=statuses())["queue"]
    df = pd.DataFrame(q).drop(columns=["components", "contributions", "signal_flags"])
    return PlainTextResponse(df.to_csv(index=False), media_type="text/csv")


@app.get("/api/cases/{cid}")
def case(cid: str, horizon: int = 60):
    s = S(); d = briefs.case_detail(s, cid, horizon)
    if d is None:
        to = s.get("retired", {}).get(cid)
        if to: raise HTTPException(410, f"{cid} was merged into {to}")
        raise HTTPException(404, "Unknown case")
    c = db(); rows = [dict(r) for r in c.execute("SELECT * FROM decisions WHERE case_id=? ORDER BY id", (cid,)).fetchall()]; c.close()
    d["decisions"] = rows
    d["status"] = statuses().get(cid, "New")
    cx = db()
    d["tips"] = [dict(r) for r in cx.execute("SELECT id, ts, channel, allegation, status FROM tips WHERE case_id=? ORDER BY id", (cid,)).fetchall()]
    d["documents"] = [dict(r) for r in cx.execute("SELECT id, filename, size, uploaded_by, ts FROM case_documents WHERE case_id=? ORDER BY id", (cid,)).fetchall()]
    cr = cx.execute("SELECT * FROM chart_reviews WHERE case_id=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    d["chart_review"] = {**json.loads(cr["result"]), "ts": cr["ts"], "by": cr["user_name"]} if cr else None
    cx.close()
    d["ai"] = LD.status()
    d["readiness"] = _readiness(s, cid, d)
    d["context"] = (_case_obj(s, cid) or {}).get("context") or {}
    return J(d)


def _readiness(s, cid, d=None):
    from intelligence import plan as PLN
    c_ = _case_obj(s, cid)
    if not c_: return None
    d = d or briefs.case_detail(s, cid)
    cx = db()
    steps = {r["step_key"]: dict(r) for r in cx.execute("SELECT * FROM plan_steps WHERE case_id=?", (cid,)).fetchall()}
    cr = cx.execute("SELECT result FROM chart_reviews WHERE case_id=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    nd = cx.execute("SELECT COUNT(*) AS n FROM case_documents WHERE case_id=?", (cid,)).fetchone()["n"]
    cx.close()
    try:
        fp = PR.fingerprint(c_, d); n_prec = len(PR.retrieve(fp, SEED_LIB + [p for p in _live_precedents(s) if p.get("source_case") != cid], 3))
    except Exception:
        n_prec = 0
    return PLN.assess(c_, d, dict(steps=steps, chart=json.loads(cr["result"]) if cr else None, documents=int(nd), precedents=n_prec))


@app.get("/api/cases/{cid}/plan")
def case_plan(cid: str):
    r = _readiness(S(), cid)
    if r is None: raise HTTPException(404)
    return J(r)


@app.post("/api/cases/{cid}/plan/{key}")
async def case_plan_step(cid: str, key: str, req: Request):
    u = need(req, "investigate"); b = json.loads(await req.body() or b"{}")
    st, note = b.get("status"), (b.get("note") or "").strip()
    if st not in ("done", "skipped", "todo"): raise HTTPException(400, "status must be done, skipped or todo")
    if st != "todo" and len(note) < 5: raise HTTPException(400, "Add a note (5+ characters) saying what was done or why it was skipped")
    if not _re.match(r"^[a-z_A-Z]{3,40}$", key) or not _case_obj(S(), cid): raise HTTPException(404)
    c = db(); c.execute("DELETE FROM plan_steps WHERE case_id=? AND step_key=?", (cid, key))
    if st != "todo":
        c.execute("INSERT INTO plan_steps(case_id,step_key,status,note,user_name,ts) VALUES(?,?,?,?,?,?)", (cid, key, st, note[:500], u["name"], time.strftime("%Y-%m-%d %H:%M:%S")))
    c.commit(); c.close()
    audit(u["name"], u["role"], f"plan_step_{st}", cid, f"{key}: {note[:150]}")
    return J(_readiness(S(), cid))


@app.get("/api/cases/{cid}/brief.md")
def brief_md(cid: str):
    s = S(); d = briefs.case_detail(s, cid)
    if d is None: raise HTTPException(404)
    c = db(); rows = [dict(r) for r in c.execute("SELECT * FROM decisions WHERE case_id=? ORDER BY id", (cid,)).fetchall()]
    cr = c.execute("SELECT * FROM chart_reviews WHERE case_id=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone(); c.close()
    md = briefs.brief_markdown(d, rows)
    rd = _readiness(s, cid, d)
    if rd:
        md += (f"\n\n## Investigation readiness: {rd['score']}% (referral bar {rd['referral_bar']}%)\n\n**Recommendation:** {rd['recommendation']}\n\n"
               + "\n".join(f"- [{'x' if i['done'] else ' '}] {i['label']} — {i['detail']}" for i in rd["items"])
               + "\n\n### Action plan\n\n" + "\n".join(f"{st['order']}. **{st['title']}** ({st['owner']}, ~{st['minutes']} min) — {st['how']}" for st in rd["plan"]["steps"]) + "\n")
    if cr:
        r = json.loads(cr["result"])
        md += (f"\n\n## Chart review sample ({cr['ts']}, {r['engine']}{' · ' + r['model'] if r.get('model') else ''})\n\n{r['summary']}\n\n| Line | Billed | Documented | Supports billed | Quote |\n|---|---|---|---|---|\n"
               + "\n".join(f"| {x['line_id']} | {x['code']} | {x.get('documented_code') or '-'} | {'yes' if x['supports_billed'] else 'no'} | {str(x['quote']).replace('|', '/')[:120]} |" for x in r["rows"])
               + "\n\n_A sample, not the population; findings are for human review._\n")
    audit("viewer", "investigator", "export_brief", cid)
    return PlainTextResponse(md, media_type="text/markdown", headers={"Content-Disposition": f"attachment; filename={cid}-brief.md"})


OUTCOMES = ["Open investigation", "Request more information", "Monitor", "Close - insufficient evidence", "Close - legitimate explanation", "Recommend referral", "Approve referral", "Reject referral"]


@app.post("/api/cases/{cid}/decision")
async def decide(cid: str, req: Request):
    need(req, "decide")
    s = S(); b = await body(req)
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
        if role not in ("supervisor", "admin"): c.close(); raise HTTPException(403, "Only a supervisor can approve or reject a referral.")
        if pend[-1]["reviewer"].lower() == reviewer.lower(): c.close(); raise HTTPException(403, "Four-eyes rule: the approver must differ from the recommender.")
    if outcome == "Recommend referral" and case["lane"] == "Needs more data":
        c.close(); raise HTTPException(409, "Evidence is below the referral threshold; request more information first.")
    d = briefs.case_detail(s, cid)
    if outcome == "Recommend referral":
        rd = _readiness(s, cid, d)
        if rd and rd["score"] < rd["referral_bar"] and not b.get("acknowledge_gaps"):
            c.close(); raise HTTPException(409, f"Investigation readiness is {rd['score']}% (bar {rd['referral_bar']}%). Missing: {', '.join(rd['missing'])}. "
                                                 "Complete the action plan, or acknowledge the gaps explicitly to refer anyway.")
        if rd and rd["score"] < rd["referral_bar"]:
            reason = f"{reason} [Referred below readiness bar ({rd['score']}%); gaps acknowledged: {', '.join(rd['missing'])}]"
    c.execute("INSERT INTO decisions(case_id,outcome,reason,reviewer,role,ts,run_id,priority,evidence,confidence,checks) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (cid, outcome, reason, reviewer, role, time.strftime("%Y-%m-%d %H:%M:%S"), s["run"]["run_id"], case["risk"], case["evidence"], d["confidence"]["label"], json.dumps(b.get("checks", []))))
    c.commit(); c.close()
    audit(reviewer, role, "decision:" + outcome, cid, reason[:200])
    if outcome == "Recommend referral":
        cn = db(); sups = [r["username"] for r in cn.execute("SELECT username FROM users WHERE role IN ('supervisor','admin') AND active=1").fetchall()]; cn.close()
        for su in sups: notify(su, "approval", f"{reviewer} recommends referral for {cid}: approval needed", f"case/{cid}/decision")
    from intelligence import knowledge as KN
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
    df = PT.reset_index()[["provider_id", "name", "family", "specialty", "city", "risk", "rule_score", "anomaly_pct", "graph_score", "sentinel", "panel_pct", "n_lines", "paid", "members", "flagged_lines", "flagged_paid", "fc30", "fc60", "fc90", "context_note"]]
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
                  scores={k: r[k] for k in ["risk", "rule_score", "anomaly_pct", "graph_score", "sentinel", "twin_pct", "path_pct", "oe_paid", "panel_pct", "outcome_p", "fc30", "fc60", "fc90"]},
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
    return J(dict(tables=tabs, validation=s["run"]["validation"], log=s["run"]["log"], codes=[dict(code=c, family=v[0], description=v[1], price=v[2]) for c, v in __import__("synthdata.gen", fromlist=["CODES"]).CODES.items()]))



# ---------------------------------------------------------------- LLM (grounded, optional)
from ai import llm
NARR: dict = {}


@app.get("/api/llm/status")
def llm_status():
    return J(dict(available=llm.feature_enabled("copilot"), model=llm.model_name(), provider=llm.provider()))


def _llm_guard():
    if not llm.feature_enabled("copilot"): raise HTTPException(503, "The AI copilot is off. An admin can enable an LLM under Settings → AI & LLM. Deterministic briefs still work.")


# ---------------------------------------------------------------- LLM settings (admin): provider, model, key, per-feature switches
SECRET = Path(os.environ.get("SPOTZI_SECRETS_DIR", ROOT / "data" / "secrets")) / "llm_api_key"


def _read_secret():
    try: return SECRET.read_text().strip()
    except FileNotFoundError: return ""


def _write_secret(v: str | None):
    SECRET.parent.mkdir(parents=True, exist_ok=True); SECRET.parent.chmod(0o700)
    if not v:
        SECRET.unlink(missing_ok=True); return
    SECRET.touch(mode=0o600); SECRET.chmod(0o600); SECRET.write_text(v)


def load_llm_settings():
    """Apply settings saved in the app (DB + secret file). Nothing saved → environment / data/llm.env."""
    c = db(); r = c.execute("SELECT value FROM app_settings WHERE key='llm'").fetchone(); c.close()
    if not r: llm.configure(None); return
    cfg = json.loads(r["value"]); cfg["api_key"] = _read_secret() or (llm._env_cfg()["api_key"] if cfg.get("provider") == llm._env_cfg()["provider"] else "")
    llm.configure(cfg)


def _llm_public():
    c = llm.config(); k = c.get("api_key") or ""
    return dict(enabled=bool(c.get("enabled")), provider=c.get("provider") or "none", model=c.get("model") or "", base_url=c.get("base_url") or "",
                key_set=bool(k), key_hint=("…" + k[-4:]) if len(k) >= 8 else ("set" if k else ""), features=c.get("features", {}),
                feature_labels=llm.FEATURES, active=llm.provider(), active_model=llm.model_name() if llm.available() else None,
                providers={**{p: dict(base_url=b, model=m) for p, (b, m) in llm.PRESETS.items()}, "anthropic": dict(base_url=llm.ANTHROPIC_DEFAULT[0], model=llm.ANTHROPIC_DEFAULT[1]),
                           "local": dict(base_url=llm.LOCAL_URL, model="")},
                note="The API key is stored on the server in an owner-only file, never in the database, never returned to the browser and never written to the audit log.")


@app.get("/api/settings/llm")
def llm_settings_get(req: Request):
    need(req, "manage_users"); return J(_llm_public())


@app.put("/api/settings/llm")
async def llm_settings_put(req: Request):
    u = need(req, "manage_users"); b = json.loads(await req.body() or b"{}")
    prov = (b.get("provider") or "none").lower()
    if prov not in ("none", "local", "anthropic", *llm.PRESETS): raise HTTPException(400, "Unknown provider")
    base = (b.get("base_url") or "").strip()
    if base and not _re.match(r"^https?://[\w.\-:]+(/[\w.\-/]*)?$", base): raise HTTPException(400, "Base URL must be an http(s) URL")
    if base.startswith("http://") and not _re.match(r"^http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(/|$)", base): raise HTTPException(400, "Plain http is allowed only for a local server; use https")
    feats = {k: bool((b.get("features") or {}).get(k, True)) for k in llm.FEATURES}
    cfg = dict(enabled=bool(b.get("enabled")), provider=prov, model=(b.get("model") or "").strip()[:80], base_url=base, features=feats)
    if b.get("clear_key"): _write_secret(None)
    elif b.get("api_key"):
        k = str(b["api_key"]).strip()
        if len(k) < 8 or len(k) > 400 or any(ch.isspace() for ch in k): raise HTTPException(400, "That does not look like an API key")
        _write_secret(k)
    c = db()
    c.execute("DELETE FROM app_settings WHERE key='llm'")
    c.execute("INSERT INTO app_settings(key,value,updated_by,ts) VALUES(?,?,?,?)", ("llm", json.dumps(cfg), u["name"], time.strftime("%Y-%m-%d %H:%M:%S")))
    c.commit(); c.close()
    load_llm_settings()
    audit(u["name"], u["role"], "llm_settings_changed", prov, json.dumps({**cfg, "key": "changed" if b.get("api_key") else ("cleared" if b.get("clear_key") else "unchanged")}))
    return J(_llm_public())


@app.post("/api/settings/llm/test")
async def llm_settings_test(req: Request):
    u = need(req, "manage_users"); r = await asyncio.to_thread(llm.test_connection)
    audit(u["name"], u["role"], "llm_connection_test", r.get("provider") or "none", "ok" if r["ok"] else "failed")
    return J(r)


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
    b = await body(req); q = (b.get("question") or "").strip()
    if not q: raise HTTPException(400, "Empty question")
    try:
        out = await __import__("asyncio").to_thread(llm.ask, d, q, b.get("history", []))
    except Exception as e:
        audit("system", "system", "llm_failed", cid, str(e)[:200]); raise HTTPException(502, f"AI layer unavailable ({type(e).__name__}).")
    audit(b.get("reviewer") or "viewer", "investigator", "llm_question", cid, q[:150])
    return J(out)


# ---------------------------------------------------------------- Evidence Challenge Lab (doc 21)
from intelligence import lab
from intelligence import precedents as PR
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
    need(req, "investigate")
    s = S(); c = _case_obj(s, cid); b = await body(req)
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
    need(req, "investigate")
    s = S(); c = _case_obj(s, cid); b = await body(req)
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
    b = await body(req); cx = db()
    need(req, "investigate")
    st, note, who = b.get("state"), b.get("note", ""), b.get("reviewer", "viewer")
    if st not in ("todo", "done", "skipped"): cx.close(); raise HTTPException(400, "Bad state")
    if st == "skipped" and len(note.strip()) < 5: cx.close(); raise HTTPException(400, "A reason is required to skip an item.")
    cx.execute("UPDATE blueprint_items SET state=?, note=? WHERE id=?", (st, note, iid)); cx.commit(); cx.close()
    audit(who, "investigator", f"blueprint_item_{st}", str(iid), note[:100])
    return J(dict(ok=True))


@app.post("/api/blueprint/{bid}/items")
async def add_item(bid: int, req: Request):
    b = await body(req); txt = (b.get("text") or "").strip()
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
    need(req, "approve_precedent")
    s = S(); b = await body(req); c = _case_obj(s, cid)
    if not c: raise HTTPException(404)
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
        held = [p for p in PT.index if s["L"][(s["L"].provider_id == p) & s["L"]._scenario.str.startswith(("S9", "influx"))].shape[0] >= 20]
        auc_held = [dict(provider=PT.at[p, "name"], rules=float(PT.at[p, "rule_score"]), brain=float(sc[p]), brain_rank=int((sc > sc[p]).sum() + 1), risk=float(PT.at[p, "risk"]), case_id=case_of.get(p)) for p in held]
    else:
        auc_held = []
    return J(dict(detectors=[dict(key=k, label=lbl, prior=float(a), learned=float(b_)) for (k, _, lbl, _), a, b_ in zip(BR.DETECTORS, w0, w)], decisions_used=n,
                  feed=feed[:40], top=top, auc=auc, held_out=auc_held))


# ---------------------------------------------------------------- Knowledge wiki + decision chain
from intelligence import knowledge as KN


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
    need(req, "review_knowledge")
    b = await body(req); action, reviewer, note = b.get("action"), (b.get("reviewer") or "").strip(), (b.get("note") or "").strip()
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
    need(req, "review_knowledge")
    b = await body(req); reviewer = (b.get("reviewer") or "").strip()
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


# ---------------------------------------------------------------- auth endpoints
def _session_response(c, u_row, method):
    tok = AU.new_session(c, u_row["id"]); c.commit()
    u = AU.user_for(c, tok); c.close()
    audit(u["name"], u["role"], "login", "", method)
    r = JSONResponse(clean(dict(user=u)))
    r.set_cookie(AU.COOKIE, tok, httponly=True, samesite="lax", max_age=AU.SESSION_HOURS * 3600)
    return r


@app.post("/api/login")
async def api_login(req: Request):
    b = json.loads(await req.body() or b"{}")
    c = db(); r = AU.password_ok(c, b.get("username", ""), b.get("password", ""))
    if not r:
        c.close(); audit(str(b.get("username", "?"))[:40], "-", "login_failed", "")
        raise HTTPException(401, "Wrong username or password")
    if r["mfa_enabled"]:
        t = AU.mfa_ticket(c, r["id"]); c.commit(); c.close()
        return J(dict(mfa_required=True, ticket=t))
    return _session_response(c, r, "password")


@app.post("/api/login/mfa")
async def api_login_mfa(req: Request):
    b = json.loads(await req.body() or b"{}")
    c = db(); uid = AU.mfa_ticket_user(c, b.get("ticket", ""))
    if not uid: c.close(); raise HTTPException(401, "Sign-in expired. Start again.")
    r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    time.sleep(.2)
    if not AU.totp_verify(c, r, b.get("code", "")):
        c.commit(); c.close(); audit(r["name"], r["role"], "mfa_failed", ""); raise HTTPException(401, "Code not accepted")
    c.execute("DELETE FROM mfa_tickets WHERE ticket=?", (b.get("ticket"),))
    return _session_response(c, r, "password+totp")


@app.post("/api/mfa/begin")
def mfa_begin(req: Request):
    u = me(req); c = db(); secret, uri = AU.mfa_begin(c, u["id"], u["username"]); c.commit(); c.close()
    audit(u["name"], u["role"], "mfa_enrolment_started", "")
    return J(dict(secret=secret, uri=uri))


@app.post("/api/mfa/confirm")
async def mfa_confirm(req: Request):
    u = me(req); b = json.loads(await req.body() or b"{}")
    c = db(); codes = AU.mfa_confirm(c, u["id"], b.get("code", "")); c.commit(); c.close()
    if not codes: raise HTTPException(400, "Code not accepted. Check the time on your device and try again.")
    audit(u["name"], u["role"], "mfa_enabled", "")
    return J(dict(ok=True, recovery_codes=codes))


@app.get("/api/security")
def security_get(req: Request):
    need(req, "manage_users"); c = db(); roles = AU.setting(c, "mfa_required_roles", [])
    rows = [dict(username=r["username"], name=r["name"], role=r["role"], mfa=bool(r["mfa_enabled"])) for r in c.execute("SELECT * FROM users WHERE active=1").fetchall()]; c.close()
    return J(dict(mfa_required_roles=roles, users=rows, sso=bool(AU.oidc_config())))


@app.post("/api/security")
async def security_set(req: Request):
    u = need(req, "manage_users"); b = json.loads(await req.body() or b"{}")
    roles = [r for r in b.get("mfa_required_roles", []) if r in AU.ROLES]
    c = db(); AU.set_setting(c, "mfa_required_roles", roles); c.commit(); c.close()
    audit(u["name"], u["role"], "security_policy", "mfa_required_roles", ",".join(roles))
    return J(dict(ok=True))


@app.post("/api/users/{uid}/mfa-reset")
def mfa_reset(uid: int, req: Request):
    u = need(req, "manage_users"); c = db(); c.execute("UPDATE users SET mfa_enabled=0, mfa_secret=NULL, recovery=NULL WHERE id=?", (uid,)); c.execute("DELETE FROM sessions WHERE user_id=?", (uid,)); c.commit(); c.close()
    audit(u["name"], u["role"], "mfa_reset", str(uid)); return J(dict(ok=True))


@app.get("/api/sso/config")
def sso_config():
    cfg = AU.oidc_config()
    return J(dict(enabled=bool(cfg), label=cfg["label"] if cfg else None))


@app.get("/api/sso/login")
def sso_login():
    from fastapi.responses import RedirectResponse
    cfg = AU.oidc_config()
    if not cfg: raise HTTPException(404, "SSO is not configured")
    c = db(); url = AU.oidc_start(c, cfg); c.commit(); c.close()
    return RedirectResponse(url, status_code=302)


@app.get("/api/sso/callback")
def sso_callback(code: str = "", state: str = "", error: str = ""):
    from fastapi.responses import RedirectResponse
    cfg = AU.oidc_config()
    if not cfg: raise HTTPException(404, "SSO is not configured")
    if error: return RedirectResponse("/#/login?sso_error=" + error[:80], status_code=302)
    c = db()
    try:
        u_row, claims = AU.oidc_finish(c, cfg, code, state)
    except Exception as e:
        c.commit(); c.close(); audit("sso", "-", "sso_failed", "", str(e)[:200])
        from urllib.parse import quote
        return RedirectResponse("/#/login?sso_error=" + quote(str(e)[:160]), status_code=302)
    tok = AU.new_session(c, u_row["id"]); c.commit(); c.close()
    audit(u_row["name"], u_row["role"], "login", "", "sso:" + cfg["issuer"])
    r = RedirectResponse("/#/my", status_code=302)
    r.set_cookie(AU.COOKIE, tok, httponly=True, samesite="lax", max_age=AU.SESSION_HOURS * 3600)
    return r


@app.post("/api/logout")
async def api_logout(req: Request):
    tok = req.cookies.get(AU.COOKIE)
    if tok: c = db(); c.execute("DELETE FROM sessions WHERE token=?", (tok,)); c.commit(); c.close()
    r = JSONResponse({"ok": True}); r.delete_cookie(AU.COOKIE); return r


@app.get("/api/me")
def api_me(req: Request):
    c = db(); u = AU.user_for(c, req.cookies.get(AU.COOKIE))
    if u:
        row = c.execute("SELECT mfa_enabled, email, notify_email, notify_slack FROM users WHERE id=?", (u["id"],)).fetchone()
        u.update(mfa_enabled=bool(row["mfa_enabled"]), mfa_required=u["role"] in AU.setting(c, "mfa_required_roles", []), email=row["email"], notify_email=bool(row["notify_email"]), notify_slack=bool(row["notify_slack"]))
    c.close()
    if not u: raise HTTPException(401, "Sign in required")
    return J(dict(user=u, contract=CONTRACT, permissions=sorted(p for p, roles in AU.PERMS.items() if u["role"] in roles)))


@app.get("/api/users")
def users_list(req: Request):
    u = me(req)
    c = db(); rows = [dict(id=r["id"], username=r["username"], name=r["name"], role=r["role"], active=bool(r["active"]), created=r["created"], email=r["email"], mfa=bool(r["mfa_enabled"])) for r in c.execute("SELECT * FROM users ORDER BY role, name").fetchall()]; c.close()
    if not AU.can(u, "manage_users"):  # others only need the investigator directory for assignment
        rows = [dict(username=r["username"], name=r["name"], role=r["role"]) for r in rows if r["active"]]
    return J(rows)


@app.post("/api/users")
async def users_create(req: Request):
    u = need(req, "manage_users"); b = json.loads(await req.body() or b"{}")
    c = db()
    try:
        AU.create_user(c, b.get("username", ""), b.get("name", ""), b.get("role", ""), b.get("password", ""))
        if b.get("email"): c.execute("UPDATE users SET email=? WHERE username=?", (b["email"].strip().lower(), b["username"].lower().strip()))
    except Exception as e: c.close(); raise HTTPException(400, str(e))
    c.commit(); c.close(); audit(u["name"], u["role"], "user_created", b.get("username", ""), b.get("role", ""))
    return J(dict(ok=True))


@app.patch("/api/users/{uid}")
async def users_update(uid: int, req: Request):
    u = need(req, "manage_users"); b = json.loads(await req.body() or b"{}"); c = db()
    if uid == u["id"] and b.get("active") is False: c.close(); raise HTTPException(400, "You cannot deactivate yourself.")
    try:
        if "role" in b:
            if b["role"] not in AU.ROLES: raise ValueError("unknown role")
            c.execute("UPDATE users SET role=? WHERE id=?", (b["role"], uid))
        if "active" in b:
            c.execute("UPDATE users SET active=? WHERE id=?", (1 if b["active"] else 0, uid))
            if not b["active"]: c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        if b.get("password"): AU.set_password(c, uid, b["password"])
        if "email" in b: c.execute("UPDATE users SET email=? WHERE id=?", ((b["email"] or "").strip().lower() or None, uid))
    except Exception as e: c.close(); raise HTTPException(400, str(e))
    c.commit(); c.close(); audit(u["name"], u["role"], "user_updated", str(uid), ",".join(k for k in b if k != "password") + (" +password" if b.get("password") else ""))
    return J(dict(ok=True))


@app.post("/api/me/password")
async def my_password(req: Request):
    u = me(req); b = json.loads(await req.body() or b"{}")
    c = db(); r = c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
    if not AU.hmac.compare_digest(AU._hash(b.get("current", ""), r["salt"]), r["pw_hash"]): c.close(); raise HTTPException(400, "Current password is wrong")
    try: AU.set_password(c, u["id"], b.get("new", ""))
    except Exception as e: c.close(); raise HTTPException(400, str(e))
    c.commit(); c.close(); audit(u["name"], u["role"], "password_changed", "")
    return J(dict(ok=True, relogin=True))


# ---------------------------------------------------------------- case management
@app.post("/api/cases/{cid}/assign")
async def assign(cid: str, req: Request):
    u = need(req, "assign"); s = S(); b = json.loads(await req.body() or b"{}")
    if not _case_obj(s, cid): raise HTTPException(404)
    c = db(); a = c.execute("SELECT * FROM users WHERE username=? AND active=1", (b.get("assignee", ""),)).fetchone()
    if not a or a["role"] not in ("investigator", "supervisor"): c.close(); raise HTTPException(400, "Assign to an active investigator or supervisor")
    due = time.strftime("%Y-%m-%d", time.localtime(time.time() + int(b.get("days", 10)) * 86400))
    c.execute("INSERT OR REPLACE INTO case_assign(case_id,assignee,assignee_name,assigned_by,ts,due) VALUES(?,?,?,?,?,?)", (cid, a["username"], a["name"], u["name"], time.strftime("%Y-%m-%d %H:%M:%S"), due))
    c.commit(); c.close()
    notify(a["username"], "assignment", f"{u['name']} assigned you {cid} (due {due})", f"case/{cid}")
    audit(u["name"], u["role"], "case_assigned", cid, f"{a['username']} due {due}")
    return J(dict(ok=True, due=due))


@app.get("/api/cases/{cid}/notes")
def notes(cid: str):
    c = db(); rows = [dict(r) for r in c.execute("SELECT * FROM case_notes WHERE case_id=? ORDER BY id", (cid,)).fetchall()]
    a = c.execute("SELECT * FROM case_assign WHERE case_id=?", (cid,)).fetchone(); c.close()
    return J(dict(notes=rows, assignment=dict(a) if a else None))


@app.post("/api/cases/{cid}/notes")
async def add_note(cid: str, req: Request):
    u = need(req, "investigate"); b = json.loads(await req.body() or b"{}"); t = (b.get("text") or "").strip()
    if len(t) < 3: raise HTTPException(400, "Write a note")
    if AU_MEMBER_RE.search(t) and not b.get("confirm_member_ids"): raise HTTPException(409, "Note contains member IDs. Confirm this is necessary for the investigation.")
    c = db(); c.execute("INSERT INTO case_notes(case_id,author,role,ts,text) VALUES(?,?,?,?,?)", (cid, u["name"], u["role"], time.strftime("%Y-%m-%d %H:%M:%S"), t[:4000]))
    a = c.execute("SELECT assignee FROM case_assign WHERE case_id=?", (cid,)).fetchone(); c.commit(); c.close()
    if a and a["assignee"] != u["username"]: notify(a["assignee"], "note", f"{u['name']} added a note on {cid}", f"case/{cid}")
    audit(u["name"], u["role"], "note_added", cid, t[:80])
    return J(dict(ok=True))


import re as _re
AU_MEMBER_RE = _re.compile(r"\bM-\d{5}\b")


@app.get("/api/my")
def my_work(req: Request):
    u = me(req); s = S(); c = db()
    asg = {r["case_id"]: dict(r) for r in c.execute("SELECT * FROM case_assign").fetchall()}
    dec = [dict(r) for r in c.execute("SELECT * FROM decisions ORDER BY id").fetchall()]
    notes_ = [dict(r) for r in c.execute("SELECT * FROM notifications WHERE username=? ORDER BY id DESC LIMIT 30", (u["username"],)).fetchall()]
    wiki_pending = c.execute("SELECT COUNT(*) FROM wiki_proposals WHERE status='pending'").fetchone()[0]
    pq = {r["case_id"]: r["status"] for r in c.execute("SELECT case_id, status FROM precedent_quality").fetchall()}
    c.close()
    st = statuses(); last = {}
    for d in dec: last[d["case_id"]] = d
    q = {r["case_id"]: r for r in briefs.rank(s, statuses=st, brain=brain_now(s)[0])["queue"]}
    now = time.time()
    def row(cid):
        a = asg.get(cid); r = q.get(cid, {})
        age = (now - time.mktime(time.strptime(a["ts"], "%Y-%m-%d %H:%M:%S"))) / 86400 if a else None
        overdue = bool(a and a["due"] < time.strftime("%Y-%m-%d") and st.get(cid, "New") != "Closed")
        return dict(case_id=cid, title=r.get("title"), priority=r.get("priority"), lane=r.get("lane"), status=st.get(cid, "New"), assignee=a["assignee_name"] if a else None,
                    due=a["due"] if a else None, age_days=round(age, 1) if age is not None else None, overdue=overdue)
    mine = [row(cid) for cid, a in asg.items() if a["assignee"] == u["username"]]
    out = dict(user=u, mine=sorted(mine, key=lambda r: (r["status"] == "Closed", -(r["priority"] or 0))), notifications=notes_)
    if AU.can(u, "approve_referral"):
        out["approvals"] = [dict(case_id=cid, recommender=d["reviewer"], ts=d["ts"], reason=d["reason"]) for cid, d in last.items() if d["outcome"] == "Recommend referral"]
        out["unassigned"] = [row(cid) for cid in q if cid not in asg and st.get(cid, "New") != "Closed"]
        out["team"] = [row(cid) for cid in asg]
    if AU.can(u, "approve_precedent"):
        out["precedent_candidates"] = [dict(case_id=cid, outcome=d["outcome"], reason=d["reason"], reviewer=d["reviewer"], ts=d["ts"], quality=pq.get(cid, "pending"))
                                       for cid, d in last.items() if (d["outcome"].startswith("Close") or d["outcome"] == "Approve referral")]
    if AU.can(u, "review_knowledge"):
        out["wiki_pending"] = wiki_pending
    return J(out)


@app.post("/api/notifications/read")
async def notif_read(req: Request):
    u = me(req); c = db(); c.execute("UPDATE notifications SET read=1 WHERE username=?", (u["username"],)); c.commit(); c.close()
    return J(dict(ok=True))


# ---------------------------------------------------------------- bring your own data
from fastapi import UploadFile, File
import shutil


@app.post("/api/data/upload")
async def upload(req: Request, files: list[UploadFile] = File(...)):
    u = need(req, "run_models")
    names = {f.filename.rsplit("/", 1)[-1].lower(): f for f in files}
    edi = [n for n in names if n.endswith((".837", ".edi", ".x12", ".txt"))]
    x12_report = None
    if edi:  # X12 837 files -> SpotZⁱ tables (CSV files of the same table override)
        from operations import x12
        frames = {}
        for n in edi:
            raw = (await names[n].read()).decode("latin-1")
            try: out, rep = x12.parse_837(raw)
            except Exception as e: raise HTTPException(400, f"{n}: {e}")
            x12_report = (x12_report or []) + [dict(file=n, **rep)]
            for k, df in out.items(): frames[k] = pd.concat([frames[k], df], ignore_index=True) if k in frames else df
        for k, df in frames.items():
            if f"{k}.csv" not in names:
                import io
                class _F:
                    def __init__(s, n, b): s.filename, s._b = n, b
                    async def read(s): return s._b
                buf = io.StringIO(); df.drop_duplicates(subset=[df.columns[0]]).to_csv(buf, index=False) if k != "claim_lines" else df.to_csv(buf, index=False)
                names[f"{k}.csv"] = _F(f"{k}.csv", buf.getvalue().encode())
        for n in edi: names.pop(n)
    missing = [n for n in PL.REQUIRED if f"{n}.csv" not in names]
    if missing: raise HTTPException(400, "Missing required file(s): " + ", ".join(f"{m}.csv" for m in missing))
    ws = ROOT / "data" / "workspaces" / time.strftime("upload-%Y%m%d-%H%M%S"); ws.mkdir(parents=True, exist_ok=True)
    report = []
    for fname, f in names.items():
        stem = fname[:-4] if fname.endswith(".csv") else fname
        if stem not in PL.REQUIRED and stem not in PL.OPTIONAL: report.append(dict(file=fname, status="ignored")); continue
        raw = await f.read()
        if len(raw) > 300 * 1024 * 1024: shutil.rmtree(ws); raise HTTPException(413, f"{fname} is larger than 300 MB")
        (ws / f"{stem}.csv").write_bytes(raw)
        try:
            cols = pd.read_csv(ws / f"{stem}.csv", nrows=5).columns
        except Exception as e:
            shutil.rmtree(ws); raise HTTPException(400, f"{fname} is not a readable CSV: {e}")
        need_cols = PL.REQUIRED.get(stem, PL.OPTIONAL.get(stem, []))
        miss = [c for c in need_cols if c not in cols]
        if miss and stem in PL.REQUIRED: shutil.rmtree(ws); raise HTTPException(400, f"{fname} is missing columns: {', '.join(miss)}")
        report.append(dict(file=fname, status="ok" if not miss else "partial", missing=miss))
    ok = start_run(data_dir=ws)
    audit(u["name"], u["role"], "data_upload", ws.name, json.dumps(report)[:300])
    return J(dict(started=ok, workspace=ws.name, files=report, x12=x12_report))


@app.post("/api/data/use-synthetic")
async def use_synth(req: Request):
    u = need(req, "run_models"); ok = start_run(data_dir=PL.DATA)
    audit(u["name"], u["role"], "dataset_switch", "synthetic")
    return J(dict(started=ok))


@app.get("/api/data/sample.837")
def sample_837(req: Request, kind: str = "P", n: int = 3000):
    """Export current synthetic claims as an 837 file (demo / integration testing)."""
    need(req, "run_models"); from operations import x12
    t = PL.load_tables(PL.DATA); L = t["lines"]
    L = L[L.code == "INP-DAY"] if kind == "I" else L[L.family != "FAC"]
    txt = x12.export_837(L.head(min(n, 20000)), t["providers"], t["members"], kind)
    return PlainTextResponse(txt, media_type="application/edi-x12", headers={"Content-Disposition": f"attachment; filename=spotzi-sample-837{kind}.edi"})


@app.get("/api/data/template")
def data_template():
    return J(dict(required=PL.REQUIRED, optional=PL.OPTIONAL,
                  notes=["Dates as YYYY-MM-DD.", "family is one of PRO, LAB, FAC, PHARM, AMB, BH, HH, DME.", "Optional claim_lines columns: referring_provider_id, pos, dx, duration_min, start_min, billed, service_end_date, paid_date.",
                         "Without outcome labels, forecasts show as unavailable and evaluation is switched off; detection, ranking, briefs and the decision chain all work."]))


@app.post("/api/me/prefs")
async def my_prefs(req: Request):
    u = me(req); b = json.loads(await req.body() or b"{}"); c = db()
    if "email" in b: c.execute("UPDATE users SET email=? WHERE id=?", ((b["email"] or "").strip().lower() or None, u["id"]))
    for k in ("notify_email", "notify_slack"):
        if k in b: c.execute(f"UPDATE users SET {k}=? WHERE id=?", (1 if b[k] else 0, u["id"]))
    c.commit(); c.close(); audit(u["name"], u["role"], "notification_prefs", "", json.dumps({k: b[k] for k in b if k != "email"}))
    return J(dict(ok=True))


@app.get("/api/outbox")
def outbox(req: Request):
    need(req, "manage_users"); from operations import notify as NT
    c = db(); rows = [dict(r) for r in c.execute("SELECT id, channel, recipient, subject, status, attempts, last_error, created, sent FROM outbox ORDER BY id DESC LIMIT 100").fetchall()]; c.close()
    return J(dict(channels=NT.channels(), rows=rows))


@app.post("/api/outbox/test")
def outbox_test(req: Request):
    u = need(req, "manage_users"); notify(u["username"], "test", "Test notification from SpotZⁱ", "my")
    return J(dict(ok=True))


@app.post("/api/cases/{cid}/merge")
async def case_merge(cid: str, req: Request):
    u = need(req, "assign"); s = S(); b = json.loads(await req.body() or b"{}")
    other, reason = b.get("other", ""), (b.get("reason") or "").strip()
    if len(reason) < 10: raise HTTPException(400, "Explain why these cases belong together (10+ characters).")
    if not _case_obj(s, cid) or not _case_obj(s, other) or cid == other: raise HTTPException(400, "Pick two different existing cases")
    from operations import scope as SC
    c = db(); c.execute("INSERT INTO case_scope(kind,target,other,providers,new_id,actor,role,reason,ts) VALUES(?,?,?,?,?,?,?,?,?)", ("merge", cid, other, "[]", None, u["name"], u["role"], reason, time.strftime("%Y-%m-%d %H:%M:%S")))
    c.commit(); SC.rebuild(s, c); c.close()
    audit(u["name"], u["role"], "case_merged", cid, f"{other} merged in: {reason[:120]}")
    return J(dict(ok=True, case_id=cid, retired=other))


@app.post("/api/cases/{cid}/split")
async def case_split(cid: str, req: Request):
    u = need(req, "assign"); s = S(); b = json.loads(await req.body() or b"{}")
    move, reason = list(b.get("providers") or []), (b.get("reason") or "").strip()
    c0 = _case_obj(s, cid)
    if not c0: raise HTTPException(404)
    if len(reason) < 10: raise HTTPException(400, "Explain why these providers need a separate case (10+ characters).")
    if not move or not set(move) < set(c0["primary"]): raise HTTPException(400, "Move some, but not all, of the case's primary providers.")
    from operations import scope as SC
    c = db(); n = c.execute("SELECT COUNT(*) FROM case_scope WHERE kind='split' AND target=?", (cid,)).fetchone()[0] + 1
    new_id = f"{cid}-S{n}"
    c.execute("INSERT INTO case_scope(kind,target,other,providers,new_id,actor,role,reason,ts) VALUES(?,?,?,?,?,?,?,?,?)", ("split", cid, None, json.dumps(move), new_id, u["name"], u["role"], reason, time.strftime("%Y-%m-%d %H:%M:%S")))
    c.commit(); SC.rebuild(s, c); c.close()
    audit(u["name"], u["role"], "case_split", cid, f"{','.join(move)} -> {new_id}: {reason[:120]}")
    return J(dict(ok=True, new_case=new_id))


@app.get("/api/cases/{cid}/scope")
def case_scope(cid: str):
    s = S(); from operations import scope as SC
    c = db(); rows = [e for e in SC.edits(c) if cid in (e["target"], e["other"], e["new_id"])]; c.close()
    return J(dict(edits=rows, retired_to=s.get("retired", {}).get(cid), problems=s.get("scope_problems", [])))


@app.post("/api/scope/{eid}/undo")
def scope_undo(eid: int, req: Request):
    u = need(req, "assign"); s = S(); from operations import scope as SC
    c = db(); c.execute("UPDATE case_scope SET active=0 WHERE id=?", (eid,)); c.commit(); SC.rebuild(s, c); c.close()
    audit(u["name"], u["role"], "case_scope_undo", str(eid)); return J(dict(ok=True))


# ---------------------------------------------------------------- link analysis (entity graph)
from detection import linkgraph as LGM


def _lg():
    s = S()
    if s.get("_lg_run") != s["run"]["run_id"] or "_lg" not in s:
        s["_lg"] = LGM.build(s); s["_lg_run"] = s["run"]["run_id"]
    return s, s["_lg"]


@app.get("/api/graph/start")
def graph_start():
    s, lg = _lg(); return J(LGM.starting_points(s, lg))


@app.get("/api/graph/search")
def graph_search(q: str = ""):
    s, lg = _lg(); return J(LGM.search(s, lg, q))


@app.get("/api/graph/entity")
def graph_entity(req: Request, id: str, flagged_only: bool = False, kinds: str = "", limit: int = 24):
    s, lg = _lg()
    ks = [k for k in kinds.split(",") if k] or None
    if ks and "referred" in ks: ks = ks + ["ordered_tests", "prescribed", "ordered_equipment", "home_care", "behavioral_referral", "transport"]
    out = LGM.neighborhood(s, lg, id, flagged_only, ks, limit)
    if out is None: raise HTTPException(404, "Unknown entity")
    u = me(req); audit(u["name"], u["role"], "graph_view", id)
    return J(out)


@app.get("/api/graph/inspect")
def graph_inspect(id: str):
    s, lg = _lg(); out = LGM.inspect(s, lg, id)
    if out is None: raise HTTPException(404, "Unknown entity")
    return J(out)


@app.get("/api/graph/path")
def graph_path(a: str, b: str):
    s, lg = _lg(); out = LGM.path(s, lg, a, b)
    if out is None: raise HTTPException(404, "Unknown entity")
    return J(out)


# ---------------------------------------------------------------- operations: pre-payment, outcomes, rules, documents, tips
from operations import ops as OP
import asyncio
import logging
from ai import charts as CH
from ai import llm_detect as LD
log = logging.getLogger("spotzi")
from fastapi import UploadFile as _UF, File as _File


def _ix():
    s = S()
    if s.get("_ix_run") != s["run"]["run_id"]: s["_ix"] = OP.prepay_index(s); s["_ix_run"] = s["run"]["run_id"]
    return s, s["_ix"]


@app.get("/api/prepay/examples")
def prepay_examples():
    s = S(); return J(OP.examples(s))


@app.post("/api/prepay/score")
async def prepay_score(req: Request):
    u = me(req); s, ix = _ix(); b = json.loads(await req.body() or b"{}")
    if not b.get("lines"): raise HTTPException(400, "Add at least one claim line")
    try: out = OP.prepay_score(s, ix, b)
    except Exception as e: raise HTTPException(400, f"Could not score claim: {e}")
    c = db(); cur = c.execute("INSERT INTO prepay_log(ts,user_name,claim,recommendation,score,reasons,amount,status) VALUES(?,?,?,?,?,?,?,?)",
                              (time.strftime("%Y-%m-%d %H:%M:%S"), u["name"], json.dumps(b), out["recommendation"], out["score"], json.dumps(out["reasons"]), out["expected_paid"],
                               "pending" if out["recommendation"] == "PEND" else "paid"))
    out["id"] = cur.lastrowid; c.commit(); c.close()
    audit(u["name"], u["role"], "prepay_check", str(out["id"]), out["recommendation"])
    return J(out)


@app.get("/api/prepay")
def prepay_log(limit: int = 50):
    c = db(); rows = [dict(r) for r in c.execute("SELECT * FROM prepay_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]; c.close()
    for r in rows: r["claim"] = json.loads(r["claim"]); r["reasons"] = json.loads(r["reasons"])
    return J(rows)


@app.post("/api/prepay/{pid}/resolve")
async def prepay_resolve(pid: int, req: Request):
    u = need(req, "investigate"); b = json.loads(await req.body() or b"{}")
    res, note = b.get("resolution"), (b.get("note") or "").strip()
    if res not in ("Released for payment", "Adjusted", "Denied by reviewer"): raise HTTPException(400, "Unknown resolution")
    if len(note) < 10: raise HTTPException(400, "Write a short rationale (10+ characters)")
    c = db(); r = c.execute("SELECT * FROM prepay_log WHERE id=?", (pid,)).fetchone()
    if not r or r["status"] != "pending": c.close(); raise HTTPException(409, "Not a pending claim")
    avoided = 0.0 if res == "Released for payment" else float(b.get("avoided") if b.get("avoided") is not None else r["amount"] or 0)
    c.execute("UPDATE prepay_log SET status='resolved', resolved_by=?, resolution=?, avoided=?, resolved_ts=? WHERE id=?", (u["name"], f"{res}: {note}", avoided, time.strftime("%Y-%m-%d %H:%M:%S"), pid))
    c.commit(); c.close(); audit(u["name"], u["role"], "prepay_resolved", str(pid), f"{res} avoided={avoided:.2f}")
    return J(dict(ok=True, avoided=avoided))


@app.get("/api/cases/{cid}/recovery")
def recovery_get(cid: str):
    c = db(); rows = [dict(r) for r in c.execute("SELECT * FROM recoveries WHERE case_id=? ORDER BY id", (cid,)).fetchall()]; c.close()
    return J(dict(history=rows, stages=OP.STAGES))


@app.post("/api/cases/{cid}/recovery")
async def recovery_add(cid: str, req: Request):
    u = need(req, "assign"); b = json.loads(await req.body() or b"{}")
    if b.get("stage") not in OP.STAGES: raise HTTPException(400, "Unknown stage")
    try: ident, recv = float(b.get("identified") or 0), float(b.get("recovered") or 0)
    except ValueError: raise HTTPException(400, "Amounts must be numbers")
    if recv > ident: raise HTTPException(400, "Recovered cannot exceed identified")
    c = db(); c.execute("INSERT INTO recoveries(case_id,stage,identified,recovered,note,user_name,ts) VALUES(?,?,?,?,?,?,?)", (cid, b["stage"], ident, recv, (b.get("note") or "")[:500], u["name"], time.strftime("%Y-%m-%d %H:%M:%S")))
    c.commit(); c.close(); audit(u["name"], u["role"], "recovery_update", cid, f"{b['stage']} identified={ident} recovered={recv}")
    return J(dict(ok=True))


@app.get("/api/outcomes")
def outcomes_api(rate: float = 65, frm: str = "", to: str = ""):
    s = S(); c = db(); out = OP.outcomes(c, s, rate, frm or None, to or None); c.close(); return J(out)


@app.get("/api/reports/siu.csv")
def siu_csv(req: Request, rate: float = 65, frm: str = "", to: str = ""):
    s = S(); c = db(); o = OP.outcomes(c, s, rate, frm or None, to or None); c.close()
    q = {r["case_id"]: r for r in briefs.rank(s, statuses=statuses())["queue"]}
    st = statuses()
    rows = [dict(case_id=cid, title=r["title"], type=r["type"], status=st.get(cid, "New"), priority=r["priority"], risk=r["risk"], exposure=r["exposure"], members=r["members"],
                 identified=next((x["identified"] for x in o["recoveries"] if x["case_id"] == cid), 0), recovered=next((x["recovered"] for x in o["recoveries"] if x["case_id"] == cid), 0)) for cid, r in q.items()]
    u = me(req); audit(u["name"], u["role"], "report_export", "siu.csv")
    return PlainTextResponse(pd.DataFrame(rows).to_csv(index=False), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=spotzi-siu-report.csv"})


@app.get("/api/rules/custom")
def rules_list():
    c = db(); rows = [dict(r) for r in c.execute("SELECT * FROM custom_rules ORDER BY id DESC").fetchall()]; c.close()
    for r in rows: r["conditions"] = json.loads(r["conditions"])
    from detection.rules import CUSTOM_FIELDS, CUSTOM_OPS
    return J(dict(rules=rows, fields=CUSTOM_FIELDS, ops=sorted(CUSTOM_OPS)))


@app.post("/api/rules/preview")
async def rules_preview(req: Request):
    need(req, "run_models"); s = S(); b = json.loads(await req.body() or b"{}")
    from detection.rules import custom_mask
    L = s["L"].assign(_age=s["L"].member_id.map(s["T"]["members"].set_index("member_id").age))
    try: m = custom_mask(L, b.get("conditions") or [])
    except Exception as e: raise HTTPException(400, str(e))
    if not (b.get("conditions")): raise HTTPException(400, "Add at least one condition")
    hit = L[m]
    in_case = {p for c_ in s["cases"] for p in c_["primary"]}
    top = hit.groupby("provider_id").agg(lines=("line_id", "size"), paid=("paid", "sum")).sort_values("lines", ascending=False).head(8)
    out = dict(lines=int(len(hit)), share=float(len(hit) / len(L)), providers=int(hit.provider_id.nunique()), members=int(hit.member_id.nunique()), paid=float(hit.paid.sum()),
               already_flagged=float(hit.any_flag.mean()) if len(hit) else 0.0, in_cases=float(hit.provider_id.isin(in_case).mean()) if len(hit) else 0.0,
               top=[dict(provider_id=p, name=s["PT"].at[p, "name"], lines=int(r.lines), paid=float(r.paid)) for p, r in top.iterrows()],
               sample=[dict(line_id=r.line_id, date=str(r.service_date.date()), provider=r.provider_id, code=r.code, units=int(r.units), paid=float(r.paid)) for r in hit.head(8).itertuples()])
    out["warning"] = "Very broad: this rule would flag more than 5% of all claim lines." if out["share"] > .05 else None
    return J(out)


@app.post("/api/rules/custom")
async def rules_save(req: Request):
    u = need(req, "run_models"); b = json.loads(await req.body() or b"{}")
    name = (b.get("name") or "").strip()
    if len(name) < 4 or not b.get("conditions"): raise HTTPException(400, "Give the rule a name and at least one condition")
    c = db(); c.execute("INSERT INTO custom_rules(name,conditions,active,author,ts,note) VALUES(?,?,?,?,?,?)", (name, json.dumps(b["conditions"]), 0, u["name"], time.strftime("%Y-%m-%d %H:%M:%S"), (b.get("note") or "")[:300]))
    c.commit(); c.close(); audit(u["name"], u["role"], "custom_rule_saved", name, json.dumps(b["conditions"])[:200])
    return J(dict(ok=True))


@app.post("/api/rules/custom/{rid}/toggle")
def rules_toggle(rid: int, req: Request):
    u = need(req, "run_models"); c = db(); r = c.execute("SELECT * FROM custom_rules WHERE id=?", (rid,)).fetchone()
    if not r: c.close(); raise HTTPException(404)
    c.execute("UPDATE custom_rules SET active=? WHERE id=?", (0 if r["active"] else 1, rid)); c.commit(); c.close()
    audit(u["name"], u["role"], "custom_rule_" + ("deactivated" if r["active"] else "activated"), r["name"])
    return J(dict(ok=True, active=not r["active"]))


@app.post("/api/rules/apply")
def rules_apply(req: Request):
    u = need(req, "run_models"); ok = start_run(data_dir=STATE.get("data_dir"))
    audit(u["name"], u["role"], "custom_rules_applied", ""); return J(dict(started=ok))


@app.post("/api/cases/{cid}/documents")
async def doc_upload(cid: str, req: Request, files: list[_UF] = _File(...)):
    u = need(req, "investigate")
    if not _case_obj(S(), cid): raise HTTPException(404)
    out = []
    for f in files:
        data = await f.read()
        try: mime, sha = OP.check_upload(f.filename, data)
        except ValueError as e: raise HTTPException(400, f"{f.filename}: {e}")
        d = ROOT / "data" / "documents" / OP.safe_name(cid); d.mkdir(parents=True, exist_ok=True)
        c = db(); cur = c.execute("INSERT INTO case_documents(case_id,filename,mime,size,path,sha256,uploaded_by,ts,note) VALUES(?,?,?,?,?,?,?,?,?)",
                                  (cid, OP.safe_name(f.filename), mime, len(data), "", sha, u["name"], time.strftime("%Y-%m-%d %H:%M:%S"), ""))
        did = cur.lastrowid; p = d / f"{did}_{OP.safe_name(f.filename)}"; p.write_bytes(data)
        c.execute("UPDATE case_documents SET path=? WHERE id=?", (str(p.relative_to(ROOT)), did)); c.commit(); c.close()
        audit(u["name"], u["role"], "document_uploaded", cid, f"{OP.safe_name(f.filename)} sha256={sha[:12]}")
        out.append(dict(id=did, filename=OP.safe_name(f.filename)))
    return J(dict(ok=True, files=out))


@app.get("/api/cases/{cid}/documents")
def doc_list(cid: str):
    c = db(); rows = [dict(r) for r in c.execute("SELECT id, filename, mime, size, sha256, uploaded_by, ts FROM case_documents WHERE case_id=? ORDER BY id", (cid,)).fetchall()]; c.close()
    return J(rows)


@app.get("/api/documents/{did}")
def doc_download(did: int, req: Request):
    u = me(req); c = db(); r = c.execute("SELECT * FROM case_documents WHERE id=?", (did,)).fetchone(); c.close()
    if not r: raise HTTPException(404)
    audit(u["name"], u["role"], "document_downloaded", r["case_id"], r["filename"])
    return FileResponse(ROOT / r["path"], media_type=r["mime"], filename=r["filename"], headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@app.post("/api/tips")
async def tip_create(req: Request):
    u = me(req); b = json.loads(await req.body() or b"{}")
    if b.get("channel") not in ("Hotline", "Member", "Employee", "Provider", "Law enforcement", "Other"): raise HTTPException(400, "Choose a channel")
    if len((b.get("allegation") or "").strip()) < 15: raise HTTPException(400, "Describe the allegation (15+ characters)")
    c = db(); cur = c.execute("INSERT INTO tips(ts,channel,subject_type,subject_id,allegation,received_by,status) VALUES(?,?,?,?,?,?,?)",
                              (time.strftime("%Y-%m-%d %H:%M:%S"), b["channel"], b.get("subject_type") or "provider", (b.get("subject_id") or "").strip(), b["allegation"].strip()[:4000], u["name"], "new"))
    tid = cur.lastrowid
    try:
        tri = LD.triage_tip(b["allegation"].strip()[:4000], S()["PT"])
        c.execute("INSERT INTO tip_ai(tip_id,ts,result) VALUES(?,?,?)", (tid, time.strftime("%Y-%m-%d %H:%M:%S"), json.dumps(tri, default=str)))
    except Exception as e:
        log.warning("tip triage failed: %s", e)
    sups = [r["username"] for r in c.execute("SELECT username FROM users WHERE role IN ('supervisor','admin') AND active=1").fetchall()]; c.commit(); c.close()
    for su in sups: notify(su, "tip", f"New tip #{tid} received ({b['channel']})", "tips")
    audit(u["name"], u["role"], "tip_received", str(tid), b["channel"])
    return J(dict(ok=True, id=tid))


@app.get("/api/tips")
def tip_list():
    s = S(); c = db(); rows = [dict(r) for r in c.execute("SELECT * FROM tips ORDER BY id DESC").fetchall()]
    ai = {r["tip_id"]: json.loads(r["result"]) for r in c.execute("SELECT * FROM tip_ai").fetchall()}; c.close()
    case_of = {p: c_["case_id"] for c_ in s["cases"] for p in c_["providers"]}
    for r in rows:
        sid = r["subject_id"]
        r["subject_name"] = s["PT"].at[sid, "name"] if sid in s["PT"].index else sid
        r["suggested_case"] = case_of.get(sid)
        r["subject_risk"] = float(s["PT"].at[sid, "risk"]) if sid in s["PT"].index else None
        r["ai"] = ai.get(r["id"])
        if r["ai"] and not r["suggested_case"]:
            r["suggested_case"] = next((case_of[m["provider_id"]] for m in r["ai"].get("matched_providers", []) if m["provider_id"] in case_of), None)
    return J(rows)


# ---------------------------------------------------------------- LLM-assisted detection (chart review, tip triage, rule drafting)
@app.get("/api/ai/status")
def ai_status():
    return J(LD.status())


@app.get("/api/models")
def models_list():
    from ai.models import registry as MR
    return J(dict(models=MR.cards(), llm=LD.status()))


@app.post("/api/cases/{cid}/chart-review")
async def chart_review(cid: str, req: Request):
    u = need(req, "investigate"); b = json.loads(await req.body() or b"{}"); s = S()
    c_ = _case_obj(s, cid)
    if not c_: raise HTTPException(404, "Unknown case")
    n = max(4, min(int(b.get("n", 8)), 16))
    L = s["L"]; END = L.service_date.max()
    W = L[L.service_date > END - pd.Timedelta(days=PL.LOOKBACK)]
    smp = CH.sample_lines(W, c_["primary"], n=n, seed=int(b.get("seed", 0)))
    if smp.empty: raise HTTPException(400, "No reviewable lines (E/M, psychotherapy or flagged) for this case")
    items = []
    for _, r in smp.iterrows():   # the synthetic record system answers the records request
        nt = CH.note(r.to_dict(), r.get("_scenario", "") if r.get("_truth", False) else "")
        items.append(dict(line_id=r.line_id, code=str(r.code), note=nt["text"], date=str(r.service_date.date()), provider_id=r.provider_id, paid=float(r.paid)))
    res = await asyncio.to_thread(LD.chart_review, items, b.get("use_llm", True))
    meta = {i["line_id"]: i for i in items}
    for row in res["rows"]: row.update(date=meta[row["line_id"]]["date"], provider_id=meta[row["line_id"]]["provider_id"], paid=meta[row["line_id"]]["paid"])
    c = db(); c.execute("INSERT INTO chart_reviews(case_id,ts,user_name,engine,result) VALUES(?,?,?,?,?)", (cid, time.strftime("%Y-%m-%d %H:%M:%S"), u["name"], res["engine"], json.dumps(res, default=str)))
    c.commit(); c.close()
    audit(u["name"], u["role"], "chart_review", cid, f"{res['engine']}: {res['summary']}")
    return J(res)


@app.post("/api/rules/draft")
async def rules_draft(req: Request):
    u = need(req, "run_models"); b = json.loads(await req.body() or b"{}")
    text = (b.get("text") or "").strip()
    if len(text) < 10: raise HTTPException(400, "Describe the rule (10+ characters)")
    from detection.rules import CUSTOM_FIELDS, CUSTOM_OPS
    res = await asyncio.to_thread(LD.draft_rule, text, CUSTOM_FIELDS, CUSTOM_OPS)
    audit(u["name"], u["role"], "rule_drafted", res.get("name", ""), text[:200])
    return J(res)


@app.post("/api/tips/{tid}/triage")
async def tip_triage(tid: int, req: Request):
    u = need(req, "assign"); b = json.loads(await req.body() or b"{}")
    act, note = b.get("action"), (b.get("note") or "").strip()
    if act not in ("link", "close", "watch") or len(note) < 5: raise HTTPException(400, "Choose an action and add a note")
    cid = b.get("case_id") if act == "link" else None
    if act == "link" and not _case_obj(S(), cid or ""): raise HTTPException(400, "Pick an existing case to link")
    c = db(); c.execute("UPDATE tips SET status=?, case_id=?, triaged_by=?, triage_note=? WHERE id=?", ({"link": "linked", "close": "closed", "watch": "watchlist"}[act], cid, u["name"], note, tid)); c.commit(); c.close()
    audit(u["name"], u["role"], "tip_triaged", str(tid), f"{act} {cid or ''}")
    return J(dict(ok=True))


@app.get("/api/data/public")
def public_list():
    ext = ROOT / "data" / "external"
    return J(dict(current=(STATE["S"] or {}).get("run", {}).get("dataset", "synthetic"), datasets=[
        dict(key="synpuf", name="CMS DE-SynPUF Sample 1", detail="Synthetic Medicare claims 2008–2010 · hospitals & outpatient facilities ↔ patients ↔ admissions (doctor IDs are scrambled by CMS, so not used)",
             available=(ext / "synpuf").exists() and any((ext / "synpuf").glob("*Inpatient*.csv"))),
        dict(key="synthea", name="Synthea sample", detail="Synthetic patient records · clinicians ↔ patients ↔ organisations · 108 patients",
             available=(ext / "synthea" / "patients.csv").exists())]))


@app.post("/api/data/public")
async def public_load(req: Request):
    u = need(req, "run_models"); b = json.loads(await req.body() or b"{}")
    from synthdata import importers as IM
    key = b.get("dataset"); ext = ROOT / "data" / "external"; ws = ROOT / "data" / "workspaces" / f"{key}-sample"
    try:
        if key == "synpuf": rep = IM.synpuf(ext / "synpuf", ws, n_benes=max(500, min(int(b.get("patients", 4000)), 20000)))
        elif key == "synthea": rep = IM.synthea(ext / "synthea", ws)
        else: raise HTTPException(400, "Unknown dataset")
    except FileNotFoundError: raise HTTPException(409, "Dataset files are not downloaded on this server")
    ok = start_run(data_dir=ws)
    audit(u["name"], u["role"], "dataset_switch", key, json.dumps(rep)[:300])
    return J(dict(started=ok, report=rep))


@app.get("/api/evaluation")
def evaluation_reports():
    d = ROOT / "data" / "evaluation"
    out = []
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            r = json.loads(f.read_text()); r.pop("per_provider", None); out.append(r)
        except Exception: pass
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
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("SPOTZI_PORT", "8000")))
