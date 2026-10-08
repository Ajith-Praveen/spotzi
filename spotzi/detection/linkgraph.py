"""SpotZⁱ link analysis: the entity graph investigators pivot through.

Entities  : providers by type (hospital / doctor / lab / pharmacy / ambulance / behavioral / home health / DME),
            patients (members, masked IDs only), ownership organisations, addresses, bank accounts.
Relations : billed (provider -> patient, aggregated over claim lines: lines, paid, flagged lines, rules),
            referred (doctor -> provider), admitted (patient -> hospital stays), owned_by / located_at / paid_to.
Patients are treated as people involved, not suspects: their score is "involvement" in flagged activity,
and identity misuse is always listed as a possible explanation."""
from __future__ import annotations

import math
from collections import defaultdict

import networkx as nx
import numpy as np
import pandas as pd

from detection.rules import RULES

TYPE_OF_FAMILY = {"FAC": "hospital", "PRO": "doctor", "LAB": "lab", "PHARM": "pharmacy", "AMB": "ambulance", "BH": "behavioral", "HH": "homehealth", "DME": "dme"}
ORDER_KIND = {"LAB": "ordered_tests", "PHARM": "prescribed", "DME": "ordered_equipment", "HH": "home_care", "BH": "behavioral_referral", "AMB": "transport", "PRO": "referred", "FAC": "referred"}
REL_LABEL = {"billed": "billed claims for", "referred": "referred to", "ordered_tests": "ordered tests at", "prescribed": "prescribed (filled at)", "ordered_equipment": "ordered equipment from",
             "home_care": "referred for home care to", "behavioral_referral": "referred for behavioral care to", "transport": "requested transport from", "admitted": "was admitted to",
             "primary_care": "is the primary-care physician of", "practices_at": "practises at", "shared_patients": "shares many patients with",
             "ownership": "shares an owner with", "address": "shares an address with", "bank": "shares a bank account with",
             "owned_by": "is owned by", "located_at": "is located at", "paid_to_account": "is paid into"}
TYPE_LABEL = {"hospital": "Hospital", "doctor": "Doctor / practice", "lab": "Laboratory", "pharmacy": "Pharmacy", "ambulance": "Ambulance", "behavioral": "Behavioral health",
              "homehealth": "Home health", "dme": "Equipment supplier", "patient": "Patient", "ownership": "Ownership", "address": "Address", "bank": "Bank account"}


def mask(mid):
    return f"Patient …{mid[-4:]}"


def build(S):
    """Pre-aggregate everything once per analysis run."""
    L, PT, T = S["L"], S["PT"], S["T"]
    flag_cols = [f"f_{k}" for k in RULES]
    g = L.groupby(["provider_id", "member_id"])
    pm = g.agg(lines=("line_id", "size"), paid=("paid", "sum"), flagged=("any_flag", "sum"), first=("service_date", "min"), last=("service_date", "max")).reset_index()
    rule_hits = L[L.any_flag].groupby(["provider_id", "member_id"])[flag_cols].sum()
    pm = pm.join(rule_hits, on=["provider_id", "member_id"])
    pm[flag_cols] = pm[flag_cols].fillna(0)
    ref = L[L.referring_provider_id.notna()].groupby(["referring_provider_id", "provider_id"]).agg(n=("line_id", "size"), paid=("paid", "sum"), flagged=("any_flag", "sum")).reset_index()
    st = T["stays"]
    adm = st.groupby(["member_id", "facility_id"]).agg(stays=("stay_id", "size"), first=("admit_date", "min")).reset_index() if len(st) else pd.DataFrame(columns=["member_id", "facility_id", "stays", "first"])
    # patient involvement (not guilt): share of their claims that were flagged, services in stays / after coverage end, provider spread
    m = L.groupby("member_id").agg(lines=("line_id", "size"), paid=("paid", "sum"), flagged=("any_flag", "sum"), providers=("provider_id", "nunique"), phantom=("f_PHANTOM", "sum"),
                                   excess=("f_EXCESS", "sum"))
    m["share"] = m.flagged / m.lines.clip(lower=1)
    flagged_prov = L[L.any_flag].groupby("member_id").provider_id.nunique()
    m["flag_providers"] = flagged_prov.reindex(m.index).fillna(0)
    m["involvement"] = (100 * (1 - np.exp(-(m.flagged / 6))) * (.5 + .5 * m.share.clip(0, 1))).round(0)
    M = T["members"].set_index("member_id")
    rel = T["relationships"]
    shared = rel.groupby("entity_b").entity_a.nunique()
    rel = rel[rel.entity_b.map(shared) > 1]
    case_of = {p: c["case_id"] for c in S["cases"] for p in c["providers"]}
    fam = PT.family.to_dict()
    ref["kind"] = ref.provider_id.map(lambda x: ORDER_KIND.get(fam.get(x), "referred"))
    pcp = M.pcp.dropna() if "pcp" in M else pd.Series(dtype=object)
    pcp = pcp[pcp.isin(PT.index)]
    # doctors practising at a hospital: professional services billed in an inpatient / outpatient-hospital setting
    hos = L[(L.family == "PRO") & L.pos.isin(["21", "22", "23"]) & L.facility_id.notna()]
    practice = hos.groupby(["provider_id", "facility_id"]).agg(n=("line_id", "size"), patients=("member_id", "nunique")).reset_index()
    practice = practice[practice.facility_id.isin(PT.index)]
    # providers that share many patients (co-treatment)
    from scipy import sparse
    prov_ix = {p: i for i, p in enumerate(pm.provider_id.unique())}; mem_ix = {m_: i for i, m_ in enumerate(pm.member_id.unique())}
    X = sparse.csr_matrix((np.ones(len(pm)), (pm.provider_id.map(prov_ix), pm.member_id.map(mem_ix))), shape=(len(prov_ix), len(mem_ix)))
    C = (X @ X.T).tocoo(); size = np.asarray(X.sum(axis=1)).ravel(); inv = {i: p for p, i in prov_ix.items()}
    share = [(inv[i], inv[j], int(v), float(v / (size[i] + size[j] - v))) for i, j, v in zip(C.row, C.col, C.data) if i < j and v >= 12]
    shared_pat = pd.DataFrame(share, columns=["a", "b", "n", "jaccard"])
    shared_pat = shared_pat[shared_pat.jaccard >= .06]
    G = nx.Graph()   # for path finding
    for r in pm.itertuples(): G.add_edge(r.provider_id, r.member_id, kind="billed", w=1 / (1 + r.flagged))
    for r in ref.itertuples():
        if r.n >= 3: G.add_edge(r.referring_provider_id, r.provider_id, kind="referred", w=.5)
    for r in adm.itertuples(): G.add_edge(r.member_id, r.facility_id, kind="admitted", w=1)
    for r in rel.itertuples(): G.add_edge(r.entity_a, r.entity_b, kind=r.relationship_type, w=.3)
    for mid, d in pcp.items():
        if not G.has_edge(d, mid): G.add_edge(d, mid, kind="primary_care", w=.8)
    for r in practice.itertuples(): G.add_edge(r.provider_id, r.facility_id, kind="practices_at", w=.6)
    return dict(pm=pm, ref=ref, adm=adm, m=m, M=M, rel=rel, case_of=case_of, G=G, flag_cols=flag_cols, pcp=pcp, practice=practice, shared_pat=shared_pat)


def _ptype(PT, pid):
    return TYPE_OF_FAMILY.get(PT.at[pid, "family"], "doctor")


def provider_node(S, LG, pid, role="neighbor"):
    PT = S["PT"]; r = PT.loc[pid]
    return dict(id=pid, type=_ptype(PT, pid), label=r["name"], sub=TYPE_LABEL[_ptype(PT, pid)] + (f" · {LG['case_of'][pid]}" if pid in LG["case_of"] else ""),
                score=float(r["risk"]), score_kind="risk", case_id=LG["case_of"].get(pid), role=role, city=r["city"])


def patient_node(LG, mid, role="neighbor"):
    m = LG["m"]
    inv = float(m.at[mid, "involvement"]) if mid in m.index else 0.0
    return dict(id=mid, type="patient", label=mask(mid), sub=f"{int(m.at[mid, 'providers']) if mid in m.index else 0} providers · {int(m.at[mid, 'flagged']) if mid in m.index else 0} flagged", score=inv,
                score_kind="involvement", role=role)


def entity_node(eid, kind, role="neighbor"):
    k = {"owned_by": "ownership", "located_at": "address", "paid_to_account": "bank"}[kind]
    return dict(id=eid, type=k, label=eid, sub=TYPE_LABEL[k], score=None, role=role)


def _rules_of(row, flag_cols):
    return [c[2:] for c in flag_cols if row.get(c, 0) > 0]


def neighborhood(S, LG, eid, flagged_only=False, kinds=None, limit=24):
    limit = max(6, min(int(limit), 200))
    PT = S["PT"]; pm, ref, adm, rel = LG["pm"], LG["ref"], LG["adm"], LG["rel"]
    kinds = set(kinds or ["billed", "referred", "admitted", "ownership", "address", "bank", "primary_care", "practices_at", "shared_patients"])
    nodes, edges, more = {}, [], {}
    is_provider = eid in PT.index
    is_patient = eid in LG["m"].index
    if is_provider: nodes[eid] = provider_node(S, LG, eid, "focus")
    elif is_patient: nodes[eid] = patient_node(LG, eid, "focus")
    elif eid in set(rel.entity_b):
        nodes[eid] = entity_node(eid, rel[rel.entity_b == eid].relationship_type.iloc[0], "focus")
    else:
        return None

    def add_edge(a, b, kind, **kw):
        edges.append(dict(source=a, target=b, kind=kind, **kw))

    if "billed" in kinds:
        if is_provider:
            sub = pm[pm.provider_id == eid]
            if flagged_only: sub = sub[sub.flagged > 0]
            sub = sub.sort_values(["flagged", "paid"], ascending=False)
            for r in sub.head(limit).itertuples():
                nodes[r.member_id] = patient_node(LG, r.member_id)
                add_edge(eid, r.member_id, "billed", lines=int(r.lines), paid=float(r.paid), flagged=int(r.flagged), rules=_rules_of(r._asdict(), LG["flag_cols"]),
                         first=str(r.first.date()), last=str(r.last.date()))
            if len(sub) > limit: more["patients"] = int(len(sub) - limit)
        if is_patient:
            sub = pm[pm.member_id == eid]
            if flagged_only: sub = sub[sub.flagged > 0]
            for r in sub.sort_values(["flagged", "paid"], ascending=False).head(limit).itertuples():
                nodes[r.provider_id] = provider_node(S, LG, r.provider_id)
                add_edge(r.provider_id, eid, "billed", lines=int(r.lines), paid=float(r.paid), flagged=int(r.flagged), rules=_rules_of(r._asdict(), LG["flag_cols"]),
                         first=str(r.first.date()), last=str(r.last.date()))
    if "referred" in kinds and is_provider:
        for col, other in (("provider_id", "referring_provider_id"), ("referring_provider_id", "provider_id")):
            sub = ref[(ref[col] == eid) & (ref.n >= 3)]
            if flagged_only: sub = sub[sub.flagged > 0]
            for r in sub.sort_values("n", ascending=False).head(10).itertuples():
                o = getattr(r, other)
                if o not in PT.index: continue
                nodes.setdefault(o, provider_node(S, LG, o))
                add_edge(r.referring_provider_id, r.provider_id, r.kind, lines=int(r.n), paid=float(r.paid), flagged=int(r.flagged))
    if "admitted" in kinds:
        if is_patient:
            for r in adm[adm.member_id == eid].itertuples():
                if r.facility_id in PT.index:
                    nodes.setdefault(r.facility_id, provider_node(S, LG, r.facility_id)); add_edge(eid, r.facility_id, "admitted", stays=int(r.stays))
        elif is_provider and PT.at[eid, "family"] == "FAC" and not flagged_only:
            sub = adm[adm.facility_id == eid].sort_values("stays", ascending=False).head(limit)
            for r in sub.itertuples():
                nodes.setdefault(r.member_id, patient_node(LG, r.member_id)); add_edge(r.member_id, eid, "admitted", stays=int(r.stays))
    if "primary_care" in kinds:
        pcp = LG["pcp"]
        if is_patient and eid in pcp.index:
            d = pcp[eid]; nodes.setdefault(d, provider_node(S, LG, d)); add_edge(d, eid, "primary_care")
        elif is_provider and not flagged_only:
            pts = pcp[pcp == eid].index
            shown = [x for x in pts if x in nodes]          # mark the PCP link on patients already shown
            for x in shown: add_edge(eid, x, "primary_care")
            if len(pts) and "patients_pcp" not in more: more["patients_pcp"] = int(len(pts))
    if "practices_at" in kinds and is_provider:
        pr = LG["practice"]
        for r in pr[(pr.provider_id == eid) | (pr.facility_id == eid)].sort_values("n", ascending=False).head(12).itertuples():
            o = r.facility_id if r.provider_id == eid else r.provider_id
            nodes.setdefault(o, provider_node(S, LG, o)); add_edge(r.provider_id, r.facility_id, "practices_at", lines=int(r.n), patients=int(r.patients))
    if "shared_patients" in kinds and is_provider and not flagged_only:
        sp = LG["shared_pat"]
        for r in sp[(sp.a == eid) | (sp.b == eid)].sort_values("jaccard", ascending=False).head(6).itertuples():
            o = r.b if r.a == eid else r.a
            nodes.setdefault(o, provider_node(S, LG, o)); add_edge(r.a, r.b, "shared_patients", patients=int(r.n), jaccard=float(r.jaccard))
    ent_kind = {"owned_by": "ownership", "located_at": "address", "paid_to_account": "bank"}
    if is_provider:
        for r in rel[rel.entity_a == eid].itertuples():
            k = ent_kind[r.relationship_type]
            if k not in kinds: continue
            nodes[r.entity_b] = entity_node(r.entity_b, r.relationship_type)
            add_edge(eid, r.entity_b, k)
            for o in rel[(rel.entity_b == r.entity_b) & (rel.entity_a != eid)].entity_a:
                if o in PT.index:
                    nodes.setdefault(o, provider_node(S, LG, o)); add_edge(o, r.entity_b, k)
    elif not is_patient:
        for r in rel[rel.entity_b == eid].itertuples():
            if r.entity_a in PT.index:
                nodes.setdefault(r.entity_a, provider_node(S, LG, r.entity_a)); add_edge(r.entity_a, eid, ent_kind[r.relationship_type])
    _radial(nodes, edges, eid)
    counts = {}
    for e in edges: counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return dict(focus=eid, nodes=list(nodes.values()), edges=edges, more=more, limit=limit, relation_counts=counts, relation_labels=REL_LABEL)


ORDER = ["hospital", "doctor", "lab", "pharmacy", "ambulance", "behavioral", "homehealth", "dme", "ownership", "address", "bank", "patient"]


def _radial(nodes, edges, focus):
    """Focus in the centre; providers / entities on an inner ring, patients on an outer ring; grouped by type."""
    nodes[focus]["x"], nodes[focus]["y"] = 0.0, 0.0
    others = [n for k, n in nodes.items() if k != focus]
    inner = sorted([n for n in others if n["type"] != "patient"], key=lambda n: (ORDER.index(n["type"]), -(n["score"] or 0)))
    outer = sorted([n for n in others if n["type"] == "patient"], key=lambda n: -(n["score"] or 0))
    if not inner or not outer:  # single ring
        ring = inner or outer
        R = max(2.6, .55 * len(ring))
        for i, n in enumerate(ring):
            a = -math.pi / 2 + 2 * math.pi * i / max(1, len(ring)); n["x"], n["y"] = R * math.cos(a), R * math.sin(a)
        return
    R1 = max(3.0, .55 * len(inner) + 1.6); R2 = R1 + max(2.6, .17 * len(outer) + 1.4)
    for i, n in enumerate(inner):
        a = -math.pi / 2 + 2 * math.pi * i / len(inner); n["x"], n["y"] = R1 * math.cos(a), R1 * math.sin(a)
    for i, n in enumerate(outer):
        a = -math.pi / 2 + 2 * math.pi * (i + .5) / len(outer); n["x"], n["y"] = R2 * math.cos(a), R2 * math.sin(a)


def inspect(S, LG, eid):
    PT, L = S["PT"], S["L"]
    if eid in PT.index:
        r = PT.loc[eid]; pm = LG["pm"]; sub = pm[pm.provider_id == eid]
        refs_in = LG["ref"][LG["ref"].provider_id == eid].sort_values("n", ascending=False)
        top_ref = refs_in.iloc[0] if len(refs_in) else None
        tot_in = refs_in.n.sum() if len(refs_in) else 0
        return dict(kind="provider", id=eid, type=_ptype(PT, eid), title=r["name"], subtitle=f"{TYPE_LABEL[_ptype(PT, eid)]} · {r['specialty']} · {r['city']}",
                    case_id=LG["case_of"].get(eid), score=float(r["risk"]), score_kind="risk",
                    facts=[("Patients billed (180d)", int(r["members"])), ("Claim lines (180d)", int(r["n_lines"])), ("Paid (180d)", float(r["paid"])),
                           ("Flagged lines (180d)", int(r["flagged_lines"])), ("Patients with flagged claims", int((sub.flagged > 0).sum())),
                           ("Top referral source share", float(top_ref.n / tot_in) if top_ref is not None and tot_in else None)],
                    signals=[dict(name=RULES[k]["name"], lines=int(r[f"n_{k}"])) for k in RULES if r[f"n_{k}"] > 0],
                    relations=_profile(S, LG, eid),
                    models=dict(rules=float(r["rule_score"]), anomaly=float(r["anomaly_pct"]), graph=float(r["graph_score"]), brain=float(r["brain"]) if "brain" in r else None,
                                sentinel=float(r["sentinel"]) if "sentinel" in r else None),
                    note=r["context_note"] or None)
    if eid in LG["m"].index:
        m = LG["m"].loc[eid]; M = LG["M"].loc[eid] if eid in LG["M"].index else None
        stays = S["T"]["stays"]; ns = int((stays.member_id == eid).sum()) if len(stays) else 0
        age = int(M["age"]) if M is not None else None
        explanations = ["Identity or member-ID misuse by a provider (the patient may never have received these services)",
                        "Legitimate complex care across several providers", "Data or eligibility errors"]
        if m.phantom > 0: explanations.insert(0, "Services billed while the patient was in hospital or after coverage ended — check whether the patient actually received them")
        return dict(kind="patient", id=eid, type="patient", title=mask(eid),
                    subtitle=f"{('age band ' + str(age // 10 * 10) + 's') if age is not None else ''} · {M['plan'] if M is not None else ''}".strip(" ·"),
                    score=float(m.involvement), score_kind="involvement",
                    facts=[("Providers seen", int(m.providers)), ("Providers with flagged claims", int(m.flag_providers)), ("Claim lines", int(m.lines)), ("Flagged lines", int(m.flagged)),
                           ("Billed during stay / after coverage end", int(m.phantom)), ("Hospital stays", ns),
                           ("Coverage ended", str(M["death_date"] if pd.notna(M["death_date"]) else M["term_date"])[:10] if M is not None and (pd.notna(M["death_date"]) or pd.notna(M["term_date"])) else None)],
                    explanations=explanations,
                    note="Patients are shown as people involved, not suspects. Masked ID only; contact with a patient requires an approved, human-initiated process.")
    rel = LG["rel"]
    if eid in set(rel.entity_b):
        sub = rel[rel.entity_b == eid]
        provs = [p for p in sub.entity_a if p in PT.index]
        return dict(kind="entity", id=eid, type={"owned_by": "ownership", "located_at": "address", "paid_to_account": "bank"}[sub.relationship_type.iloc[0]], title=eid,
                    subtitle=TYPE_LABEL[{"owned_by": "ownership", "located_at": "address", "paid_to_account": "bank"}[sub.relationship_type.iloc[0]]],
                    score=float(max(PT.loc[provs, "risk"])) if provs else None, score_kind="max linked risk",
                    facts=[("Providers sharing it", len(provs)), ("Combined paid (180d)", float(PT.loc[provs, "paid"].sum()) if provs else 0)],
                    note="Shared ownership, address or bank is common (chains, shared buildings). It matters only when linked providers also show risky behaviour.")
    return None


def _profile(S, LG, pid):
    """Every relationship type this provider has, with counts (the full picture, not just what is drawn)."""
    pm, ref, rel = LG["pm"], LG["ref"], LG["rel"]
    out = []
    n_pat = int((pm.provider_id == pid).sum()); n_fl = int(((pm.provider_id == pid) & (pm.flagged > 0)).sum())
    if n_pat: out.append(dict(rel="Patients billed", count=n_pat, note=f"{n_fl} with flagged claims"))
    for k, g in ref[ref.referring_provider_id == pid].groupby("kind"):
        out.append(dict(rel=REL_LABEL[k].capitalize() + " …", count=int(len(g)), note=f"{int(g.n.sum())} orders/referrals"))
    inc = ref[ref.provider_id == pid]
    if len(inc): out.append(dict(rel="Receives orders/referrals from", count=int(len(inc)), note=f"top source {inc.n.max() / inc.n.sum():.0%} of {int(inc.n.sum())}"))
    pcp = LG["pcp"]; n_pcp = int((pcp == pid).sum())
    if n_pcp: out.append(dict(rel="Primary-care physician of", count=n_pcp, note="patients"))
    pr = LG["practice"]
    if (pr.provider_id == pid).any(): out.append(dict(rel="Practises at hospitals", count=int((pr.provider_id == pid).sum()), note=""))
    if (pr.facility_id == pid).any(): out.append(dict(rel="Doctors practising here", count=int((pr.facility_id == pid).sum()), note=""))
    sp = LG["shared_pat"]; n_sp = int(((sp.a == pid) | (sp.b == pid)).sum())
    if n_sp: out.append(dict(rel="Shares many patients with", count=n_sp, note="providers"))
    adm = LG["adm"]
    if (adm.facility_id == pid).any(): out.append(dict(rel="Inpatient admissions", count=int(adm[adm.facility_id == pid].stays.sum()), note=""))
    for k, lbl in (("owned_by", "Shared owner with"), ("located_at", "Shared address with"), ("paid_to_account", "Shared bank account with")):
        ents = rel[(rel.entity_a == pid) & (rel.relationship_type == k)].entity_b
        n = int(rel[rel.entity_b.isin(ents) & (rel.entity_a != pid)].entity_a.nunique())
        if n: out.append(dict(rel=lbl, count=n, note="providers"))
    return out


def path(S, LG, a, b, max_len=6):
    G = LG["G"]
    if a not in G or b not in G: return None
    try:
        p = nx.shortest_path(G, a, b, weight="w")
    except nx.NetworkXNoPath:
        return dict(found=False, steps=[])
    if len(p) - 1 > max_len: return dict(found=False, steps=[], note=f"Only connected through {len(p) - 1} steps — too indirect to be meaningful.")
    PT = S["PT"]
    def label(x): return PT.at[x, "name"] if x in PT.index else mask(x) if x in LG["m"].index else x
    steps = [dict(a=label(x), b=label(y), a_id=x, b_id=y, kind=G[x][y]["kind"]) for x, y in zip(p, p[1:])]
    return dict(found=True, length=len(p) - 1, ids=p, steps=steps)


def search(S, LG, q, k=12):
    q = q.strip().lower()
    if not q: return []
    PT = S["PT"]; out = []
    for pid, r in PT.iterrows():
        if q in r["name"].lower() or q in pid.lower():
            out.append(dict(id=pid, label=r["name"], type=_ptype(PT, pid), score=float(r["risk"]), score_kind="risk"))
    if q.startswith("m-") or q.isdigit():
        for mid in LG["m"].index:
            if q in mid.lower():
                out.append(dict(id=mid, label=mask(mid), type="patient", score=float(LG["m"].at[mid, "involvement"]), score_kind="involvement"))
                if len(out) > k * 2: break
    for e in LG["rel"].entity_b.unique():
        if q in e.lower(): out.append(dict(id=e, label=e, type="ownership", score=None))
    return sorted(out, key=lambda x: -(x["score"] or 0))[:k]


def starting_points(S, LG):
    PT = S["PT"]
    provs = PT.sort_values("risk", ascending=False).head(10)
    hosp = PT[PT.family == "FAC"].sort_values("risk", ascending=False).head(4)
    pats = LG["m"].sort_values("involvement", ascending=False).head(8)
    f = lambda pid: dict(id=pid, label=PT.at[pid, "name"], type=_ptype(PT, pid), score=float(PT.at[pid, "risk"]), case_id=LG["case_of"].get(pid))
    return dict(providers=[f(p) for p in provs.index], hospitals=[f(p) for p in hosp.index],
                patients=[dict(id=m, label=mask(m), type="patient", score=float(r.involvement), flagged=int(r.flagged), providers=int(r.providers)) for m, r in pats.iterrows()])
