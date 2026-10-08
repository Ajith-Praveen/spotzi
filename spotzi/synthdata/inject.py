"""Labelled evaluation scenarios injected into an imported public dataset (DE-SynPUF or Synthea).

Background claims stay exactly as published; we add (or alter) claims for a few providers following known FWA schemes,
each starting at a random month and continuing to the end of the data, and write hidden labels to <workspace>/hidden/.
We also add BENIGN look-alikes (legitimate growth) that a good system should not escalate.
Labels are used only for evaluation and forecast training — never for detection.

Schemes
  dup        duplicate submissions of existing services
  units      unit inflation on lab / therapy services
  repeat     panels re-billed within a few days
  upcode     office/clinic visits shifted to the highest level
  deceased   services billed after the patient's death
  influx     wave of new out-of-area patients, each receiving one identical service bundle (patient recruitment).
             Was held out until v2; the patient-panel detector now targets this typology, so it is no longer a blind test.
  scope      HELD-OUT (no rule or detector designed for it): the provider starts billing a costly service it has never
             billed before, for its own existing patients
Benign
  growth     legitimate expansion: more patients, normal service mix (labelled NOT fraud)"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

LAB_LIKE = ("80", "81", "82", "83", "84", "85", "86", "87", "97")


def inject(ws: Path, seed=21, n_per_scheme=3, n_benign=4, min_lines=200):
    ws = Path(ws); rng = np.random.default_rng(seed)
    L = pd.read_csv(ws / "claim_lines.csv", dtype={"code": str, "pos": str, "modifier": str, "dx": str, "facility_id": str, "referring_provider_id": str}, low_memory=False)
    M = pd.read_csv(ws / "members.csv")
    for c in ("service_date", "service_end_date", "paid_date"): L[c] = pd.to_datetime(L[c])
    L["truth"] = False; L["scenario"] = ""
    end = L.service_date.max(); start = L.service_date.min()
    span = (end - start).days
    vol = L.groupby("provider_id").size()
    eligible = list(vol[vol >= min_lines].sample(frac=1, random_state=seed).index)
    schemes = ["dup", "units", "repeat", "upcode", "deceased", "influx", "scope"]
    need = n_per_scheme * len(schemes) + n_benign
    if len(eligible) < need: raise ValueError(f"Only {len(eligible)} providers with ≥{min_lines} lines; need {need}")
    assign, k = {}, 0
    for s in schemes:
        for _ in range(n_per_scheme): assign[eligible[k]] = s; k += 1
    benign = eligible[k:k + n_benign]
    new_rows, new_members, log = [], [], []
    nid = [0]

    def onset():
        return start + pd.Timedelta(days=int(span * rng.uniform(.55, .8)))

    def add(rows, scen, truth=True):
        if rows is None or len(rows) == 0: return
        rows = rows.copy(); rows["truth"] = truth; rows["scenario"] = scen
        nid[0] += len(rows)
        rows["line_id"] = [f"INJ-{scen}-{nid[0] - len(rows) + i}" for i in range(len(rows))]
        rows["claim_id"] = [x.replace("INJ-", "INJC-") for x in rows.line_id]
        rows["line_no"] = 1
        new_rows.append(rows)

    for pid, s in assign.items():
        t0 = onset(); mine = L[(L.provider_id == pid) & (L.service_date >= t0)]
        if s == "dup":
            add(mine.sample(n=min(len(mine), max(30, int(len(mine) * .3))), random_state=1, replace=False).assign(paid_date=lambda x: x.paid_date + pd.Timedelta(days=14)), "dup")
        elif s == "units":
            pool_ = mine[mine.code.str.startswith(LAB_LIKE)]
            pool_ = pool_ if len(pool_) >= 30 else mine
            idx = pool_.sample(n=min(len(pool_), max(30, int(len(pool_) * .5))), random_state=2).index
            L.loc[idx, "units"] = L.loc[idx, "units"] * 4; L.loc[idx, "paid"] = L.loc[idx, "paid"] * 4
            L.loc[idx, "truth"] = True; L.loc[idx, "scenario"] = "units"
        elif s == "repeat":
            base = mine[mine.code.isin(["80053", "85025", "80048", "80061", "85610"])]
            base = base if len(base) >= 10 else mine
            rep = base.sample(n=60, random_state=3, replace=len(base) < 60).copy()
            rep["service_date"] = rep.service_date + pd.to_timedelta(rng.integers(2, 5, len(rep)), unit="D"); rep["service_end_date"] = rep.service_date
            add(rep[rep.service_date <= end], "repeat")
        elif s == "upcode":
            em = mine[mine.code.isin(["99211", "99212", "99213", "99214", "G0463", "OP-VISIT"])]
            if len(em) >= 30:
                idx = em.sample(frac=.8, random_state=4).index
                L.loc[idx, "code"] = "99215"; L.loc[idx, "paid"] = L.loc[idx, "paid"] * 1.9; L.loc[idx, "truth"] = True; L.loc[idx, "scenario"] = "upcode"
            else:  # practice with few office visits: its patients now get level-5 visits throughout the scheme period
                pts = L[L.provider_id == pid].member_id.unique()
                if len(pts):
                    n_v = 60
                    v = L[L.provider_id == pid].sample(n_v, replace=True, random_state=4).copy()
                    v["member_id"] = rng.choice(pts, n_v); v["code"] = "99215"; v["units"] = 1; v["paid"] = 140.0; v["pos"] = "22"
                    v["service_date"] = t0 + pd.to_timedelta(rng.integers(0, max(1, (end - t0).days), n_v), unit="D"); v["service_end_date"] = v.service_date
                    add(v, "upcode")
        elif s == "deceased":
            t0 = end - pd.Timedelta(days=int(rng.integers(90, 160)))       # inside the review window
            last_seen = L.groupby("member_id").service_date.max()
            quiet = last_seen[last_seen < t0 - pd.Timedelta(days=45)].index        # no genuine care after the synthetic death
            cand = M[M.death_date.isna() & M.member_id.isin(quiet)]
            pool = cand.sample(min(12, len(cand)), random_state=5) if len(cand) else M.sample(0)
            tmpl = L[L.provider_id == pid].sample(min(40, int(vol[pid])), random_state=6).copy()
            pts = pool.sample(min(len(pool), 12), random_state=7, replace=False)
            rows = []
            for _, m in pts.iterrows():
                dd = t0 - pd.Timedelta(days=30)
                M.loc[M.member_id == m.member_id, "death_date"] = str(dd.date())
                for j in range(3):
                    r = tmpl.sample(1, random_state=int(rng.integers(1e6))).copy()
                    r["member_id"] = m.member_id; r["service_date"] = min(end, dd + pd.Timedelta(days=int(rng.integers(20, 110)))); r["service_end_date"] = r.service_date
                    rows.append(r)
            if rows: add(pd.concat(rows), "deceased")
        elif s == "influx":
            tmpl = L[L.provider_id == pid].drop_duplicates("code").head(3)
            if len(tmpl) == 0: continue
            regions = M.region.value_counts()
            far = regions.index[-1]
            rows = []
            for i in range(120):
                mid = f"{M.member_id.iloc[0][:2]}INJ{i:04d}{pid[-3:]}"
                new_members.append(dict(member_id=mid, age=int(rng.integers(66, 90)), sex=rng.choice(["F", "M"]), plan=M.plan.iloc[0], region=far,
                                        death_date=None, term_date=None, vulnerable=True))
                d = t0 + pd.Timedelta(days=int(rng.integers(0, max(1, (end - t0).days))))
                b = tmpl.copy(); b["member_id"] = mid; b["service_date"] = d; b["service_end_date"] = d; b["units"] = 1
                rows.append(b)
            add(pd.concat(rows), "influx")
        elif s == "scope":
            own = set(L.loc[L.provider_id == pid, "code"])
            costly = L[~L.code.isin(own)].groupby("code").paid.agg(["median", "size"])
            costly = costly[costly["size"] >= 5].sort_values("median", ascending=False).head(25)
            pts = L.loc[(L.provider_id == pid) & (L.service_date < t0), "member_id"].unique()
            if len(costly) == 0 or len(pts) == 0: continue
            codes = rng.choice(costly.index, size=min(2, len(costly)), replace=False)
            n_s = max(30, min(80, int(len(mine) * .3)))
            v = L[L.provider_id == pid].sample(n_s, replace=True, random_state=8).copy()
            v["member_id"] = rng.choice(pts, n_s); v["code"] = rng.choice(codes, n_s); v["units"] = 1
            v["paid"] = v.code.map(costly["median"]).astype(float)
            v["service_date"] = t0 + pd.to_timedelta(rng.integers(0, max(1, (end - t0).days), n_s), unit="D"); v["service_end_date"] = v.service_date
            add(v, "scope")
        log.append(dict(provider_id=pid, scheme=s, onset=str(t0.date())))
    for pid in benign:  # legitimate growth: copy COMPLETE real patient episodes (all of a patient's services) to new local patients
        t0 = onset(); mine = L[(L.provider_id == pid) & (L.service_date < t0)]
        pts = mine.member_id.unique()
        if len(pts) < 5: continue
        local = M.region.mode().iat[0]; reps = []
        for i, src_m in enumerate(rng.choice(pts, size=min(len(pts) * 2, 150), replace=len(pts) * 2 > len(pts))):
            ep = L[(L.member_id == src_m)].copy()                   # the source patient's whole journey (all providers) keeps pathways realistic
            if ep.empty: continue
            shift = t0 + pd.Timedelta(days=int(rng.integers(0, max(1, (end - t0).days)))) - ep.service_date.min()
            ep["service_date"] = ep.service_date + shift; ep["service_end_date"] = ep.service_end_date.fillna(ep.service_date) + shift
            ep = ep[ep.service_date <= end]
            if ep.empty: continue
            mid = f"{M.member_id.iloc[0][:2]}GRW{i:04d}{pid[-3:]}"
            src_row = M[M.member_id == src_m].iloc[0].to_dict()
            new_members.append({**src_row, "member_id": mid, "region": local, "death_date": None})
            ep["member_id"] = mid; reps.append(ep)
        if reps: add(pd.concat(reps), "benign-growth", truth=False)
        log.append(dict(provider_id=pid, scheme="benign-growth", onset=str(t0.date())))
    if new_rows: L = pd.concat([L] + new_rows, ignore_index=True)
    if new_members: M = pd.concat([M, pd.DataFrame(new_members)], ignore_index=True)
    L["paid_date"] = L.service_end_date.fillna(L.service_date) + pd.Timedelta(days=21)
    L["billed"] = L.billed.fillna(L.paid * 1.8)
    truth = L[["line_id", "truth", "scenario"]]
    hid = ws / "hidden"; hid.mkdir(exist_ok=True)
    truth.to_csv(hid / "scenario_truth.csv", index=False)
    pd.DataFrame(log).to_csv(hid / "scenario_providers.csv", index=False)
    from synthdata import truth as TR
    P = pd.read_csv(ws / "providers.csv")
    lg = pd.DataFrame([dict(provider_id=r["provider_id"], legitimate=True) for r in log if r["scheme"] == "benign-growth"])
    TR.build(L[["provider_id", "service_date", "paid", "truth", "scenario"]], list(P.provider_id), lg if len(lg) else None).to_csv(hid / "entity_truth.csv", index=False)
    L.drop(columns=["truth", "scenario"]).to_csv(ws / "claim_lines.csv", index=False)
    M.to_csv(ws / "members.csv", index=False)
    return dict(bad_providers=len(assign), benign_providers=len(benign), injected_lines=int(sum(len(r) for r in new_rows)), labelled_fraud_lines=int(truth.truth.sum()),
                schemes={s: n_per_scheme for s in schemes})
