"""SpotZⁱ Knowledge layer — the second brain's persistent, linked memory.

INGEST   : every analysis run and every human decision produces *proposed* wiki updates (rule/policy pages,
           scheme pages, provider dossiers, case pages, decision records, lessons learned) with citations.
LINT     : each proposal is checked automatically (uncited facts, member identifiers, broken links,
           contradiction with the approved version, empty sections) before a human sees it.
REVIEW   : a human approves or rejects; approved pages are versioned (history kept, nothing silently overwritten).
QUERY    : TF-IDF retrieval over approved pages feeds the decision chain.
DECISION CHAIN: Retrieve → Interpret → Apply rules → Propose → Score → Cite, for every case.
Only approved knowledge is retrieved: "approved updates improve the wiki and strengthen the next decision".
"""
from __future__ import annotations

import hashlib
import json
import re
import time

import numpy as np
import pandas as pd

from rules import RULES

LINK = re.compile(r"\[\[([a-z0-9\-/]+)\]\]")
MEMBER = re.compile(r"\bM-\d{5}\b")


def _h(s): return hashlib.sha1(s.encode()).hexdigest()[:12]


def schema(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS wiki_pages(slug TEXT PRIMARY KEY, kind TEXT, title TEXT, body TEXT, citations TEXT, version INTEGER, updated TEXT, author TEXT, body_hash TEXT);
    CREATE TABLE IF NOT EXISTS wiki_history(id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT, version INTEGER, body TEXT, citations TEXT, author TEXT, ts TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS wiki_proposals(id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT, kind TEXT, title TEXT, body TEXT, citations TEXT, reason TEXT, lint TEXT,
        status TEXT, created TEXT, source TEXT, reviewer TEXT, review_note TEXT, body_hash TEXT);
    """)


# ------------------------------------------------------------------ page generators (ingest)
def rule_page(k, spec):
    body = f"""# {spec['name']}

**What it detects.** {spec['desc']}

## Legitimate explanations to test
""" + "\n".join(f"- {b}" for b in spec["benign"]) + f"""

## Distinguishing check
- {spec['check']}

## Policy notes
- Severity weight {spec['severity']:.2f} (source: rules.py {k}, ruleset rules-1.0)
- A rule hit is a pattern for review, never a finding of fraud (source: governance policy)

Related: [[policy/human-decision]] [[scheme/{k.lower()}]]
"""
    return dict(slug=f"rule/{k.lower()}", kind="rule", title=spec["name"], body=body, citations=[f"rules.py:{k}"])


SCHEMES = {
    "dup": ("Duplicate billing vs replacement claims", "Same service billed twice. Most look-alikes are corrected or replacement claims; lineage and reversals separate them."),
    "repeat": ("Repeat services and early refills", "Services repeated inside a policy interval. Chronic monitoring and dose changes are the common legitimate explanations."),
    "unbundle": ("Unbundling of panels", "Components billed alongside a panel that already includes them. Accession records decide it."),
    "upcode": ("Upcoding and level inflation", "Higher-level codes than documentation supports. Specialty case mix is the main confounder."),
    "phantom": ("Services not plausibly rendered", "Billing during inpatient stays or after coverage ended. Stay-date and eligibility feed errors are the main confounder."),
    "timing": ("Impossible hours", "More documented hours than one clinician can deliver. Group sessions and shared provider numbers are the confounders."),
    "excess": ("Excessive utilization", "Frequency far above clinical pathways. Intensive programmes are the confounder."),
    "behaviour-shift": ("Behaviour shift without rule hits", "Learned detectors see a sudden change in who is treated and how (e.g. recruitment mills). Expansion or new programmes are the confounder."),
}


def scheme_page(key, title, text, lessons=None):
    body = f"""# {title}

{text}

## How SpotZⁱ detects it
- Rules, Isolation Forest, Sentinel case-mix twin and care-pathway model, change-point detector (source: brain.py detector set)

## Lessons from approved decisions
""" + ("\n".join(f"- {l}" for l in lessons) if lessons else "- None yet (source: decision log)") + """

Related: [[policy/human-decision]]
"""
    return dict(slug=f"scheme/{key}", kind="scheme", title=title, body=body, citations=["brain.py", "decision log"])


POLICY = dict(slug="policy/human-decision", kind="policy", title="Human decision policy", citations=["idea/20", "server.py decision endpoint"], body="""# Human decision policy

- The system recommends; a named human decides every outcome (source: idea/20)
- Written rationale of at least 15 characters is required (source: server.py decision endpoint)
- Referral needs a second person with the supervisor role (four-eyes) (source: server.py decision endpoint)
- Cases below the evidence threshold cannot be referred; the system abstains (source: pipeline lanes)
- No payment hold, provider contact or external referral is ever automated (source: governance)

Related: [[rule/phantom]] [[rule/upcode]]
""")


def provider_page(S, pid):
    PT = S["PT"]; r = PT.loc[pid]; run = S["run"]["run_id"]
    cp = S.get("change_points", {}).get(pid, {})
    cases = [c["case_id"] for c in S["cases"] if pid in c["providers"]]
    hits = [f"- {RULES[k]['name']}: {int(r[f'n_{k}'])} lines in 180 days (source: claim_lines.csv, {run})" for k in RULES if r[f"n_{k}"] > 0]
    body = f"""# {r['name']}

**{r['family']} · {r['specialty']} · {r['city']}** (source: providers.csv {pid})

## Current assessment
- Rule-based risk {r['risk']:.0f}/100; Nexus Brain {r.get('brain', 0) * 100:.0f}/100 (source: {run})
- Isolation Forest {r['anomaly_pct'] * 100:.0f}th pct; case-mix twin {r['twin_pct'] * 100:.0f}th pct; care pathway {r['path_pct'] * 100:.0f}th pct (source: {run})
- Billed {r['oe_paid']:.1f}× what its patients' case mix predicts (source: sentinel.py, {run})
""" + (f"- {cp['text']} (source: brain.py change-point, {run})\n" if cp.get("text") and r.get("drift_pct", 0) >= .85 else "") + """
## Rule hits
""" + ("\n".join(hits) if hits else "- None (source: rules engine)") + f"""

## Context
- {r['context_note'] or 'No benign context recorded in master data'} (source: providers.csv)

## Cases
""" + ("\n".join(f"- [[case/{c.lower()}]] (source: {run})" for c in cases) if cases else "- None (source: case builder)") + "\n"
    return dict(slug=f"provider/{pid.lower()}", kind="provider", title=r["name"], body=body, citations=[f"providers.csv:{pid}", run])


def case_page(S, c):
    run = S["run"]["run_id"]
    body = f"""# {c['case_id']} — {c['title']}

**{c['type']}** · lane {c['lane']} (source: {run})

## Scope
""" + "\n".join(f"- [[provider/{p.lower()}]] {'(primary)' if p in c['primary'] else '(linked)'} (source: case builder, {run})" for p in c["providers"]) + f"""

## Evidence summary
- {c['flagged_lines']} flagged lines, ${c['exposure']:,.0f} gross exposure, {c['members']} members (source: claim_lines.csv, {run})
- Rules fired: {', '.join(c['rules']) or 'none — learned detectors only'} (source: rules.py, {run})
- Evidence strength {c['evidence']:.0f}/100 from {c['signals']} signal families (source: pipeline, {run})

Related: """ + " ".join(f"[[rule/{k.lower()}]]" for k in c["rules"]) + f" [[scheme/{_scheme_for(c)}]]\n"
    return dict(slug=f"case/{c['case_id'].lower()}", kind="case", title=f"{c['case_id']} {c['title']}", body=body, citations=[run])


def _scheme_for(c):
    if not c["rules"] or c.get("brain_lead"): return "behaviour-shift"
    return {"DUP": "dup", "REPEAT": "repeat", "UNBUNDLE": "unbundle", "UPCODE": "upcode", "PHANTOM": "phantom", "TIMING": "timing", "EXCESS": "excess", "MUE": "excess", "EXCLUDED": "phantom", "CUSTOM": "dup"}.get(c["rules"][0], "dup")


def decision_page(c, d):
    body = f"""# Decision on {c['case_id']}: {d['outcome']}

- Outcome: **{d['outcome']}** by {d['reviewer']} ({d['role']}) on {d['ts']} (source: decision log #{d['id']})
- Rationale: {d['reason']} (source: decision log #{d['id']})
- Evidence strength at decision time {d['evidence']:.0f}/100, confidence {d['confidence']} (source: decision log #{d['id']})
- Checks selected: {', '.join(json.loads(d.get('checks') or '[]')) or 'none'} (source: decision log #{d['id']})

Related: [[case/{c['case_id'].lower()}]] [[scheme/{_scheme_for(c)}]] [[policy/human-decision]]
"""
    return dict(slug=f"decision/{c['case_id'].lower()}-{d['id']}", kind="decision", title=f"{c['case_id']}: {d['outcome']}", body=body, citations=[f"decision:{d['id']}"])


# ------------------------------------------------------------------ lint
def lint(page, approved: dict, existing_slugs: set):
    issues = []
    lines = [l for l in page["body"].splitlines() if l.startswith("- ")]
    uncited = [l for l in lines if "(source:" not in l]
    if uncited: issues.append(dict(level="warn", check="Uncited facts", detail=f"{len(uncited)} bullet(s) without a source"))
    if MEMBER.search(page["body"]): issues.append(dict(level="block", check="Member identifier", detail="Member IDs must not be stored in the wiki (minimisation)"))
    broken = [s for s in LINK.findall(page["body"]) if s not in existing_slugs and not s.startswith(("case/", "decision/", "provider/"))]
    if broken: issues.append(dict(level="warn", check="Broken links", detail=", ".join(broken)))
    if re.search(r"##[^\n]*\n\s*\n##", page["body"]): issues.append(dict(level="warn", check="Empty section", detail="A heading has no content"))
    old = approved.get(page["slug"])
    if old:
        m_new = re.search(r"Rule-based risk (\d+)", page["body"]); m_old = re.search(r"Rule-based risk (\d+)", old["body"])
        if m_new and m_old and abs(int(m_new.group(1)) - int(m_old.group(1))) >= 20:
            issues.append(dict(level="review", check="Changes a prior conclusion", detail=f"Risk moved {m_old.group(1)} → {m_new.group(1)}"))
        if "fraud" in page["body"].lower() and "not a finding of fraud" not in page["body"].lower() and "never a finding of fraud" not in page["body"].lower():
            issues.append(dict(level="review", check="Language", detail="Mentions fraud; ensure it is not stated as a conclusion"))
    if not issues: issues.append(dict(level="ok", check="All checks passed", detail=""))
    return issues


# ------------------------------------------------------------------ store ops
def approved_pages(c):
    return {r["slug"]: dict(r) for r in c.execute("SELECT * FROM wiki_pages").fetchall()}


def propose(c, page, reason, source):
    h = _h(page["body"])
    if c.execute("SELECT 1 FROM wiki_pages WHERE slug=? AND body_hash=?", (page["slug"], h)).fetchone(): return None
    if c.execute("SELECT 1 FROM wiki_proposals WHERE slug=? AND body_hash=? AND status='pending'", (page["slug"], h)).fetchone(): return None
    c.execute("UPDATE wiki_proposals SET status='superseded' WHERE slug=? AND status='pending'", (page["slug"],))
    ap = approved_pages(c); slugs = set(ap) | {page["slug"]}
    li = lint(page, ap, slugs)
    cur = c.execute("INSERT INTO wiki_proposals(slug,kind,title,body,citations,reason,lint,status,created,source,body_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (page["slug"], page["kind"], page["title"], page["body"], json.dumps(page["citations"]), reason, json.dumps(li), "pending", time.strftime("%Y-%m-%d %H:%M:%S"), source, h))
    return cur.lastrowid


def apply(c, pid_, reviewer, note, author_note="approved"):
    p = dict(c.execute("SELECT * FROM wiki_proposals WHERE id=?", (pid_,)).fetchone())
    old = c.execute("SELECT * FROM wiki_pages WHERE slug=?", (p["slug"],)).fetchone()
    v = (old["version"] + 1) if old else 1
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT OR REPLACE INTO wiki_pages(slug,kind,title,body,citations,version,updated,author,body_hash) VALUES(?,?,?,?,?,?,?,?,?)",
              (p["slug"], p["kind"], p["title"], p["body"], p["citations"], v, ts, reviewer, p["body_hash"]))
    c.execute("INSERT INTO wiki_history(slug,version,body,citations,author,ts,note) VALUES(?,?,?,?,?,?,?)", (p["slug"], v, p["body"], p["citations"], reviewer, ts, note or author_note))
    c.execute("UPDATE wiki_proposals SET status='approved', reviewer=?, review_note=? WHERE id=?", (reviewer, note, pid_))
    return v


def bootstrap(c):
    """Governance-approved seed: rule, scheme and policy pages."""
    if c.execute("SELECT COUNT(*) FROM wiki_pages").fetchone()[0]: return 0
    pages = [rule_page(k, s) for k, s in RULES.items()] + [scheme_page(k, t, x) for k, (t, x) in SCHEMES.items()] + [POLICY]
    for pg in pages:
        i = propose(c, pg, "Initial knowledge base", "bootstrap")
        if i: apply(c, i, "governance (seed)", "initial approved knowledge base")
    return len(pages)


def ingest_run(c, S):
    n = 0
    for case in S["cases"]:
        if propose(c, case_page(S, case), f"Run {S['run']['run_id']} built or changed this case", S["run"]["run_id"]): n += 1
        for p in case["providers"]:
            if propose(c, provider_page(S, p), f"Run {S['run']['run_id']} assessed this provider", S["run"]["run_id"]): n += 1
    return n


def ingest_decision(c, case, d):
    n = 0
    if propose(c, decision_page(case, d), "New human decision recorded", f"decision:{d['id']}"): n += 1
    key = _scheme_for(case)
    ap = approved_pages(c).get(f"scheme/{key}")
    prior = re.findall(r"^- (.+)$", ap["body"].split("## Lessons from approved decisions")[1].split("Related:")[0], re.M) if ap else []
    prior = [l for l in prior if not l.startswith("None yet")]
    lesson = f"{case['case_id']} ({case['type'].lower()}): {d['outcome'].lower()} — {d['reason'][:160]} (source: decision log #{d['id']}, [[decision/{case['case_id'].lower()}-{d['id']}]])"
    t, x = SCHEMES[key]
    if propose(c, scheme_page(key, t, x, prior + [lesson]), "Lesson learned from a human decision", f"decision:{d['id']}"): n += 1
    return n


# ------------------------------------------------------------------ query
def search(c, q, k=6, kinds=None):
    pages = [dict(r) for r in c.execute("SELECT * FROM wiki_pages").fetchall()]
    if kinds: pages = [p for p in pages if p["kind"] in kinds]
    if not pages or not q.strip(): return []
    from sklearn.feature_extraction.text import TfidfVectorizer
    docs = [p["title"] + " " + p["title"] + " " + p["body"] for p in pages]
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1).fit(docs + [q])
    M = vec.transform(docs); qv = vec.transform([q])
    sims = (M @ qv.T).toarray().ravel()
    order = np.argsort(-sims)[:k]
    out = []
    for i in order:
        if sims[i] <= 0: continue
        p = pages[i]
        terms = [t for t in re.findall(r"\w+", q.lower()) if len(t) > 3]
        body_lines = [l for l in p["body"].splitlines() if l.strip() and not l.startswith("#")]
        snip = next((l for l in body_lines if any(t in l.lower() for t in terms)), body_lines[0] if body_lines else "")
        snip = re.sub(r"\(source: [^)]+\)", "", snip).replace("**", "").lstrip("- ")
        out.append(dict(slug=p["slug"], title=p["title"], kind=p["kind"], version=p["version"], score=float(sims[i]), snippet=snip[:240]))
    return out


# ------------------------------------------------------------------ decision chain
def decision_chain(c, S, case, detail, lab_state, prec):
    PT = S["PT"]; run = S["run"]["run_id"]
    q = " ".join([case["type"]] + [RULES[k]["name"] for k in case["rules"]] + [PT.at[p, "name"] for p in case["primary"]] + [PT.at[p, "family"] for p in case["primary"]])
    retrieved = search(c, q, 6)
    pol = [p for p in retrieved if p["kind"] in ("rule", "scheme", "policy")]
    mem = [p for p in retrieved if p["kind"] in ("decision", "case", "provider")]
    facts = [dict(text=f"{e['label']}: {e.get('n_lines', '')} {'lines' if e.get('n_lines') else ''}".strip(), kind="observed fact", ref=e["id"]) for e in detail["evidence"] if e["kind"] in ("rule", "drift")]
    hyps = [dict(text=h["title"], kind="hypothesis", support=h["support"]) for h in detail["hypotheses"]]
    gaps = [dict(text=l, kind="missing prerequisite") for l in detail["limitations"] if "lack" in l or "run-out" in l or "below" in l]
    applied = []
    for k in case["rules"]:
        applied.append(dict(rule=RULES[k]["name"], result=f"fired on {case['rule_counts'][k]} lines", exception=RULES[k]["benign"][0]))
    if not case["rules"]: applied.append(dict(rule="No billing rule fired", result="case opened by learned detectors only", exception="treated as a lead: validation before investigation"))
    ctx = [p for p in detail["providers"] if p["context"]]
    if ctx: applied.append(dict(rule="Benign-context exception", result=ctx[0]["context"], exception="lane set to validate context first"))
    if case["lane"] == "Needs more data": applied.append(dict(rule="Abstention policy", result="evidence below threshold", exception="referral blocked"))
    nxt = lab_state["ranking"][0] if lab_state["ranking"] else None
    ent = lab_state["entropy_bits"]
    best_prec = prec[0] if prec else None
    score = dict(evidence_strength=detail["metrics"]["evidence"], ambiguity_bits=ent, ambiguity_label="high" if ent > 1.2 else "moderate" if ent > .7 else "low",
                 impact=f"${detail['metrics']['exposure']:,.0f} · {detail['metrics']['members']} members ({detail['metrics']['vulnerable']} vulnerable)",
                 precedent_fit=(best_prec["similarity"] if best_prec else None), precedent=(best_prec["precedent"]["id"] if best_prec else None),
                 precedent_warnings=len(best_prec["differences"]) if best_prec else 0, confidence=detail["confidence"]["label"])
    propose_ = dict(recommendation=detail["action"], next_check=(nxt["name"] if nxt else None), next_check_value=(nxt["bits_per_hour"] if nxt else None),
                    alternatives=[r["name"] for r in lab_state["ranking"][1:3]], requires="Named investigator decision; referral needs supervisor approval")
    cites = [dict(kind="claim lines", ref=x["line_id"]) for e in detail["evidence"] if e["kind"] == "rule" for x in e["examples"][:2]]
    cites += [dict(kind="wiki", ref=f"{p['slug']} v{p['version']}") for p in retrieved]
    cites += [dict(kind="run", ref=f"{run} · {S['run']['ruleset']} · {S['run']['model']}")]
    if best_prec: cites.append(dict(kind="precedent", ref=best_prec["precedent"]["id"]))
    checkpoints = ["Investigator reviews evidence before precedents", "Evidence checks approved by a named human", "Decision with written rationale", "Supervisor approval for referral", "Wiki update reviewed before it becomes knowledge"]
    return dict(steps=[
        dict(n=1, key="retrieve", title="Retrieve", summary=f"{len(pol)} policy/scheme page(s), {len(mem)} memory page(s), {len(prec)} precedent(s)", policy=pol, memory=mem, query=q),
        dict(n=2, key="interpret", title="Interpret", summary=f"{len(facts)} observed fact(s), {len(hyps)} hypotheses, {len(gaps)} data gap(s)", facts=facts, hypotheses=hyps, gaps=gaps),
        dict(n=3, key="rules", title="Apply rules", summary=f"{len(applied)} rule/exception step(s)", applied=applied),
        dict(n=4, key="propose", title="Propose", summary=propose_["next_check"] or "Review flagged claims", **propose_),
        dict(n=5, key="score", title="Score", summary=f"evidence {score['evidence_strength']:.0f}/100 · ambiguity {score['ambiguity_label']} · confidence {score['confidence']}", **score),
        dict(n=6, key="cite", title="Cite", summary=f"{len(cites)} source(s) · {len(checkpoints)} human checkpoints", sources=cites, checkpoints=checkpoints)],
        output="A grounded recommendation with evidence, confidence, impact and a path to human approval. It never decides.")
