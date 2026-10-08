"""Train every SpotZⁱ task model on independent synthetic training worlds and evaluate each on data it never saw.

  python3 -m ai.models.train_all            # from spotzi/
  python3 -m ai.models.train_all --quick    # 1 training world (faster; for CI)

Training worlds: gen.py with seeds 101-103 (the demo world is seed 7) → data/training/world-<seed>/.
Held-out tests: the demo world (seed 7) and independent held-out worlds (seeds 201-202) never used in training, plus unseen
wording for the text models. Synthetic data only. Every result is written into the model card."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ai import charts as CH# noqa: E402
from synthdata import gen# noqa: E402
from ai import llm_detect as LD# noqa: E402
from detection import pipeline as PL# noqa: E402
from ai.models import chart_model as CM, outcome_model as OM, prepay_model as PM, registry as R, tipgen as TG  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TRAIN_SEEDS = [101, 102, 103, 104, 105, 106]
HELDOUT_SEEDS = [201, 202]
CODE_MIN = {k: v[3] for k, v in gen.CODES.items()}
OUTCOME_FEATURES = OM.FEATURES


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


def world(seed):
    d = ROOT / "data" / "training" / f"world-{seed}" / "synthetic"
    if not (d / "claim_lines.csv").exists():
        gen.generate(seed=seed, n_members=2500, out_dir=d)
    return d


def run_world(d):
    S = PL.run_pipeline(data_dir=d)
    return S


# ---------------------------------------------------------------- 1. pre-payment line model
def prepay_xy(S, stats):
    L = S["L"]; T = S["T"]
    X = PM.features(L, T["members"], T["stays"], stats, CODE_MIN)
    return X, L["_truth"].astype(int).values, L.get("any_flag", pd.Series(False, index=L.index)).astype(int).values


def train_prepay(train_S, tests):
    Ltr = pd.concat([S["L"] for S in train_S]); stats = PM.code_stats(Ltr)
    Xs, ys = zip(*[prepay_xy(S, stats)[:2] for S in train_S])
    X, y = pd.concat(Xs), np.concatenate(ys)
    m = PM.fit(X, y); m._spotzi_median = X.median().to_dict()
    res = {}
    for name, S in tests.items():
        Xt, yt, rt = prepay_xy(S, stats)
        if yt.sum() == 0: continue
        p = m.predict_proba(Xt)[:, 1]
        k = max(1, int(rt.sum()))                                  # compare at the rules' own flag budget
        top = np.argsort(-p)[:k]
        res[name] = dict(lines=int(len(yt)), fraud_lines=int(yt.sum()), auc=round(float(roc_auc_score(yt, p)), 3), ap=round(float(average_precision_score(yt, p)), 3),
                         rules_flagged=k, rules_precision=round(float(yt[rt == 1].mean()), 3), rules_recall=round(float(rt[yt == 1].mean()), 3),
                         model_precision_same_budget=round(float(yt[top].mean()), 3), model_recall_same_budget=round(float(yt[top].sum() / yt.sum()), 3))
        log("prepay", name, res[name])
    card = dict(task="Pre-payment line risk", process="Pre-payment claim check (Operations → Pre-payment)", kind="Gradient-boosted trees (HistGradientBoosting), supervised",
                trained_on=f"{len(X):,} labelled lines: synthetic generator worlds (seeds {TRAIN_SEEDS})", features=PM.FEATURES,
                held_out=res, use="Adds a line-risk probability and its local drivers to every pre-payment check. Recommendation only; a human resolves every pended claim.",
                limitations=["Labels are synthetic scheme truth, not adjudicated outcomes.", "Training worlds share the generator's scheme templates; the public-data test is the stronger check."])
    return R.save("prepay_line_risk", dict(model=m, stats=stats), card)


# ---------------------------------------------------------------- 2. chart-documentation model
def chart_corpus(S, style, n=3000, seed=0):
    L = S["L"]
    em = L[L.code.isin(list(CH.EM_OFFICE) + list(CH.EM_ED))]
    t = em[em._truth]; f = em[~em._truth]
    smp = pd.concat([t.sample(min(len(t), n // 3), random_state=seed), f.sample(min(len(f), n - min(len(t), n // 3)), random_state=seed)])
    notes, lv, items = [], [], []
    for _, r in smp.iterrows():
        nt = CH.note(r.to_dict(), r._scenario if r._truth else "", style=style)
        if "level" not in nt: continue
        billed = CH.EM_OFFICE.get(str(r.code)) or CH.EM_ED.get(str(r.code))
        notes.append(nt["text"]); lv.append(nt["level"]); items.append((str(r.code), nt["text"], nt["level"] < billed))   # label: documentation supports less than billed
    return notes, lv, items


def train_chart(train_S, demo_S):
    notes, lv = [], []
    for i, S in enumerate(train_S):
        a, b, _ = chart_corpus(S, "A", seed=i); notes += a; lv += b
    res = {}
    mA = CM.ChartModel().fit(notes, lv)                                    # trained on wording A only
    for style in ("A", "B"):
        _, _, items = chart_corpus(demo_S, style, n=600, seed=9)
        y = np.array([t for *_, t in items])
        pm = np.array([not mA.review(c, n)["supports_billed"] for c, n, _ in items])
        ph = np.array([not LD.review_heuristic(c, n)["supports_billed"] for c, n, _ in items])
        res[f"demo world, wording {style}" + (" (unseen)" if style == "B" else "")] = dict(
            notes=int(len(y)), model_accuracy=round(float((pm == y).mean()), 3), model_f1=round(float(f1_score(y, pm)), 3),
            keyword_reviewer_accuracy=round(float((ph == y).mean()), 3), keyword_reviewer_f1=round(float(f1_score(y, ph)), 3))
        log("chart", style, res[list(res)[-1]])
    for i, S in enumerate(train_S):                                        # production model also learns wording B
        a, b, _ = chart_corpus(S, "B", seed=10 + i); notes += a; lv += b
    m = CM.ChartModel().fit(notes, lv)
    card = dict(task="Chart documentation review", process="Case → Chart review (offline reviewer and LLM second opinion)",
                kind="TF-IDF (word + character n-grams) → multinomial logistic regression over documented E/M level; parsed time rules",
                trained_on=f"{len(notes):,} synthetic notes from training worlds (wording A and B)", held_out=res,
                use="Screens chart-review samples without an LLM; when an LLM is configured, disagreements between the two are highlighted for the reviewer.",
                limitations=["Held-out score on unseen wording (B) was measured with a model trained on A only; the shipped model also saw B.",
                             "Synthetic notes are far more regular than real charts; an LLM is expected to generalise better to real wording."])
    return R.save("chart_documentation", m, card)


# ---------------------------------------------------------------- 3. tip-triage model
def train_tips(train_S, demo_S):
    from ai.models.tip_model import TipModel, export_encoder
    names_tr = sorted({n for S in train_S for n in S["PT"]["name"]}); names_te = list(demo_S["PT"]["name"])
    X1, y1, _ = TG.corpus(names_tr, "train", n=4000, seed=1)
    X, y, _ = TG.corpus_v2(names_tr, n=8000, seed=1)
    Xt, yt, _ = TG.corpus(names_te, "test", n=800, seed=2)
    v1 = TipModel(); v1.uses_encoder = False; v1.tfidf.fit(X1, y1); v1.classes_ = v1.tfidf.classes_   # v1 baseline: original templates, TF-IDF only
    tf = TipModel(); tf.tfidf.fit(X, y); tf.classes_ = tf.tfidf.classes_
    m = TipModel().fit(X, y)
    ps = m.predict(Xt)
    kw = [LD.triage_tip(t, demo_S["PT"], use_llm=False, use_model=False)["scheme"] for t in Xt[:300]]
    acc = lambda p: round(float(np.mean(np.asarray(p) == np.array(yt[:len(p)]))), 3)
    res = dict(test_tips=len(Xt), scheme_accuracy=acc(ps), scheme_macro_f1=round(float(f1_score(yt, ps, average="macro")), 3),
               tfidf_only_accuracy=acc(tf.tfidf.predict(Xt)), v1_accuracy=acc(v1.tfidf.predict(Xt)), keyword_baseline_scheme_accuracy=acc(kw),
               encoder_used=m.uses_encoder, note="Test tips use sentence templates and provider names never seen in training.")
    log("tips", res)
    if m.uses_encoder: export_encoder()
    card = dict(task="Tip triage", process="Tips & referrals in → automatic structuring of each new tip",
                kind=("Ensemble: TF-IDF (word + char n-grams) → logistic regression + local sentence encoder (bge-small-en-v1.5, frozen) → logistic regression"
                      if m.uses_encoder else "TF-IDF (word + character n-grams) → logistic regression") + "; 9 scheme types",
                trained_on=f"{len(X):,} synthetic tips (compositional generator + training templates)", classes=TG.SCHEMES, held_out=res,
                use="Classifies every new tip offline; an LLM (if enabled) adds entity extraction and summaries. Supervisors triage every tip.",
                limitations=["Synthetic tips are short and templated; real tips are messier.", "Urgency is keyword/LLM-based: a trained urgency model failed its held-out test (v1) and is not shipped.",
                             "Never decides anything — a tip is an allegation, not evidence."])
    return R.save("tip_triage", dict(scheme=m), card)


# ---------------------------------------------------------------- 4. case-outcome model
def outcome_xy(S):
    PT = S["PT"]; L = S["L"]
    X = OM.matrix(PT)
    tp = L[L._truth].groupby("provider_id").size() if "_truth" in L else pd.Series(dtype=int)
    y = PT.index.isin(tp[tp >= 20].index).astype(int)
    return X, y


def train_outcome(train_S, tests):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    Xs, ys = zip(*[outcome_xy(S) for S in train_S])
    X, y = pd.concat(Xs), np.concatenate(ys)
    m = make_pipeline(StandardScaler(), LogisticRegression(C=.5, max_iter=2000, class_weight="balanced")).fit(X, y)
    res = {}
    for name, S in tests.items():
        Xt, yt = outcome_xy(S)
        if yt.sum() == 0 or yt.sum() == len(yt): continue
        p = m.predict_proba(Xt)[:, 1]
        res[name] = dict(providers=int(len(yt)), positives=int(yt.sum()), auc=round(float(roc_auc_score(yt, p)), 3), ap=round(float(average_precision_score(yt, p)), 3),
                         brain_auc=round(float(roc_auc_score(yt, S["PT"].brain)), 3), brain_ap=round(float(average_precision_score(yt, S["PT"].brain)), 3),
                         risk_auc=round(float(roc_auc_score(yt, S["PT"].risk)), 3))
        log("outcome", name, res[name])
    coef = dict(zip(OUTCOME_FEATURES, np.round(m[-1].coef_[0], 3)))
    card = dict(task="Case substantiation likelihood", process="SIU queue → probability a case's providers are substantiated", kind="Logistic regression (standardised), class-balanced",
                trained_on=f"{len(X)} providers from synthetic generator worlds", features=OUTCOME_FEATURES, coefficients=coef, held_out=res,
                use="Shown on cases and providers as a learned estimate from simulated closed cases. Not used to rank or decide; Nexus Brain keeps learning from your real decisions.",
                limitations=["Trained on simulated outcomes. Replace with your closed SIU cases when available (same script)."])
    return R.save("case_outcome", m, card)


# ---------------------------------------------------------------- 5. fraud-type classifier, 6. calibration, 7. reference population
TYPE_FEATURES_DET = ["rule_score", "anomaly_pct", "graph_score", "twin_pct", "path_pct", "drift_pct", "mix_pct", "panel_pct", "temporal_pct", "peer_pct", "burst", "cusum", "trend"]


def entity_truth(S):
    from synthdata import truth as TRU
    d = S.get("data_dir")
    L = S["L"]
    lt = L.assign(truth=L["_truth"], scenario=L["_scenario"])[["provider_id", "service_date", "paid", "truth", "scenario"]] if "_truth" in L else None
    return TRU.build(lt, list(S["PT"].index), exclusions=S["T"].get("exclusions")).set_index("provider_id") if lt is not None else None


def type_xy(S):
    from detection.rules import RULES
    PT = S["PT"]; E = entity_truth(S)
    cols = [f"s_{k}" for k in RULES] + TYPE_FEATURES_DET
    X = PT.reindex(columns=cols).astype(float).fillna(0)
    if E is None: return X, None
    y = E.fraud_type.reindex(PT.index)
    keep = y.notna()
    return X[keep], y[keep]


def train_types(train_S, tests):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from detection.rules import RULES
    Xs, ys = zip(*[type_xy(S) for S in train_S])
    X, y = pd.concat(Xs), pd.concat(ys)
    m = make_pipeline(StandardScaler(), LogisticRegression(C=.5, max_iter=3000, class_weight="balanced")).fit(X, y)
    RULE_TYPE = {"DUP": "duplicate", "UPCODE": "upcoding", "MUE": "unit_inflation", "UNBUNDLE": "unbundling", "PHANTOM": "phantom", "TIMING": "impossible_timing",
                 "REPEAT": "excessive_services", "EXCESS": "excessive_services"}
    res = {}
    for name, S in tests.items():
        Xt, yt = type_xy(S)
        if yt is None or not len(yt): continue
        p = m.predict(Xt); P = m.predict_proba(Xt)
        top2 = np.array([yt.iat[i] in m.classes_[np.argsort(-P[i])[:2]] for i in range(len(yt))])
        base = [RULE_TYPE.get(max(RULES, key=lambda k: Xt.iloc[i][f"s_{k}"]), "recruitment") if Xt.iloc[i][[f"s_{k}" for k in RULES]].max() > 0 else "recruitment" for i in range(len(Xt))]
        res[name] = dict(fraud_providers=int(len(yt)), accuracy=round(float((p == yt.values).mean()), 3), top2_accuracy=round(float(top2.mean()), 3),
                         dominant_rule_baseline=round(float((np.array(base) == yt.values).mean()), 3), types_present=sorted(set(yt)),
                         unseen_types=sorted(set(yt) - set(m.classes_)))
        log("types", name, res[name])
    card = dict(task="Fraud-type classification", process="Cases → most likely scheme types (probability per type) → selects the evidence to collect",
                kind="Multinomial logistic regression on rule profiles, detector outputs and temporal features", trained_on=f"{len(X)} labelled fraudulent providers",
                classes=list(m.classes_), held_out=res, use="Backend: ranks likely scheme types for each case so the investigation plan targets the right evidence.",
                limitations=["Few labelled fraudulent providers; types never seen in training cannot be predicted (see unseen_types)."])
    return R.save("fraud_type", dict(model=m, cols=list(X.columns)), card)


def train_calibration(train_S, tests):
    from sklearn.isotonic import IsotonicRegression
    xs, ys = [], []
    for S in train_S:
        E = entity_truth(S)
        if E is None: continue
        xs.append(S["PT"].brain.values); ys.append((E.true_state.reindex(S["PT"].index) == "fraudulent").astype(int).values)
    x, y = np.concatenate(xs), np.concatenate(ys)
    iso = IsotonicRegression(y_min=.005, y_max=.97, out_of_bounds="clip").fit(x, y)
    res = {}
    for name, S in tests.items():
        E = entity_truth(S)
        if E is None: continue
        yt = (E.true_state.reindex(S["PT"].index) == "fraudulent").astype(int).values; raw = S["PT"].brain.values; p = iso.predict(raw)
        res[name] = dict(providers=int(len(yt)), positives=int(yt.sum()), ece_raw=round(_ece(yt, raw), 4), ece_calibrated=round(_ece(yt, p), 4),
                         brier_raw=round(float(np.mean((raw - yt) ** 2)), 4), brier_calibrated=round(float(np.mean((p - yt) ** 2)), 4))
        log("calibration", name, res[name])
    card = dict(task="Fraud-probability calibration", process="Nexus Brain suspicion → calibrated probability (p_fraud) used for tiers and thresholds",
                kind="Isotonic regression (monotone; ranking unchanged)", trained_on=f"{len(x):,} providers from training worlds", held_out=res,
                use="Backend: makes 'p = 0.9' mean roughly 9 in 10 under the evaluation distribution; tiers and capacity thresholds use it.",
                limitations=["Calibrated to synthetic base rates; real base rates differ — recalibrate on real outcomes."])
    return R.save("brain_calibrator", iso, card)


def _ece(y, p, bins=10):
    edges = np.quantile(p, np.linspace(0, 1, bins + 1)); idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, bins - 1)
    return float(sum(abs(y[idx == b].mean() - p[idx == b].mean()) * (idx == b).mean() for b in range(bins) if (idx == b).any()))


def train_reference(train_S):
    from detection import baselines as BLN
    from detection.pipeline import LOOKBACK
    F = []
    for S in train_S:
        L = S["L"] if isinstance(S, dict) else S; end = L.service_date.max(); W = L[L.service_date > end - pd.Timedelta(days=LOOKBACK)]
        f = BLN.features(W); F.append(f[f.n_lines >= 15][list(BLN.METRICS)])
    X = np.log1p(pd.concat(F).clip(lower=0).fillna(0))
    cov = np.cov(X.values, rowvar=False) + 1e-4 * np.eye(X.shape[1])
    hist = {}
    for c in X.columns:   # tie-safe bins (point masses such as 0% level-5 share get their own bin)
        e = np.unique(X[c].quantile(np.linspace(0, 1, 11)).values)
        e = np.concatenate([[-np.inf], (e[:-1] + e[1:]) / 2 if len(e) > 1 else e, [np.inf]])
        hist[c] = dict(edges=[float(x) for x in e], share=(np.histogram(X[c].values, e)[0] / len(X)).tolist())
    ref = dict(cols=list(X.columns), mean=X.mean().to_dict(), cov_inv=np.linalg.pinv(cov).tolist(), n=int(len(X)), hist=hist)
    card = dict(task="Reference population (OOD + drift)", process="Out-of-distribution checks and drift monitoring", kind="Log-space mean / covariance of provider behaviour profiles",
                trained_on=f"{len(X)} providers from training worlds", held_out={}, use="Backend: flags providers unlike anything the models were trained on; drift monitoring compares each run with it.",
                limitations=["Built from synthetic worlds: real data will look out-of-distribution until the reference is rebuilt from real history."])
    return R.save("reference_profile", ref, card)


def main(quick=False):
    seeds = TRAIN_SEEDS[:1] if quick else TRAIN_SEEDS
    train_S = []
    for s in seeds:
        log("training world", s); train_S.append(run_world(world(s)))
    gen_S = list(train_S)

    log("demo world"); demo = PL.run_pipeline()
    tests = {"demo world (seed 7)": demo}
    for s2 in HELDOUT_SEEDS[: 0 if quick else len(HELDOUT_SEEDS)]:   # independent held-out generator worlds (never trained on)
        log("held-out world", s2); tests[f"held-out world (seed {s2})"] = run_world(world(s2))
    cards = [train_reference(gen_S), train_prepay(train_S, tests), train_chart(gen_S, demo), train_tips(gen_S, demo), train_outcome(train_S, tests),
             train_types(train_S, tests), train_calibration(train_S, tests)]
    (R.DIR / "summary.txt").write_text(json.dumps([dict(name=c["name"], held_out=c["held_out"]) for c in cards], indent=1))
    log("done:", [c["name"] for c in cards])
    return cards


if __name__ == "__main__":
    main("--quick" in sys.argv)
