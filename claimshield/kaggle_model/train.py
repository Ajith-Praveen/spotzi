"""Train the provider-level fraud model on the Kaggle Healthcare Provider Fraud dataset."""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
import features as F

HERE = Path(__file__).parent
DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "data" / "kaggle"


def pick(pattern):
    fs = sorted(glob.glob(str(DATA / "**" / pattern), recursive=True))
    if not fs: raise SystemExit(f"Missing file matching {pattern} under {DATA}. See kaggle_model/README.md")
    return fs[0]


def load():
    ben = pd.read_csv(pick("Train_Beneficiarydata*.csv"))
    inp = pd.read_csv(pick("Train_Inpatientdata*.csv"))
    out = pd.read_csv(pick("Train_Outpatientdata*.csv"))
    lab = [f for f in glob.glob(str(DATA / "**" / "Train*.csv"), recursive=True) if all(k not in Path(f).name for k in ("Beneficiary", "Inpatient", "Outpatient"))]
    if not lab: raise SystemExit("Missing provider label file (Train-*.csv with Provider, PotentialFraud)")
    y = pd.read_csv(lab[0]).set_index("Provider").PotentialFraud.eq("Yes").astype(int)
    return ben, inp, out, y


def main():
    ben, inp, out, y = load()
    X = F.rank_norm(F.from_kaggle(ben, inp, out))
    y = y.reindex(X.index).dropna().astype(int); X = X.loc[y.index]
    print(f"{len(X)} providers, fraud rate {y.mean():.3f}")
    lr = make_pipeline(StandardScaler(), LogisticRegression(C=.5, max_iter=1000, class_weight="balanced"))
    gb = HistGradientBoostingClassifier(max_depth=3, learning_rate=.05, max_iter=250, l2_regularization=1.0, random_state=0)
    cv = StratifiedKFold(5, shuffle=True, random_state=0)
    p_lr = cross_val_predict(lr, X, y, cv=cv, method="predict_proba")[:, 1]
    p_gb = cross_val_predict(gb, X, y, cv=cv, method="predict_proba")[:, 1]
    p = .5 * p_lr + .5 * p_gb
    base = F.rank_norm(F.from_kaggle(ben, inp, out))["log_claims"].loc[y.index]
    m = dict(providers=int(len(X)), fraud_rate=float(y.mean()), cv_folds=5,
             auc_logistic=float(roc_auc_score(y, p_lr)), auc_gboost=float(roc_auc_score(y, p_gb)), auc_ensemble=float(roc_auc_score(y, p)),
             ap_ensemble=float(average_precision_score(y, p)), brier_ensemble=float(brier_score_loss(y, p)), auc_volume_only_baseline=float(roc_auc_score(y, base)),
             features=F.SHARED, dataset="Kaggle: Healthcare Provider Fraud Detection Analysis")
    gb.fit(X, y); lr.fit(X, y)
    imp = permutation_importance(gb, X, y, n_repeats=8, random_state=0, scoring="roc_auc")
    m["importance"] = sorted([dict(feature=f, label=F.LABELS[f], importance=float(v)) for f, v in zip(X.columns, imp.importances_mean)], key=lambda r: -r["importance"])
    joblib.dump(dict(lr=lr, gb=gb, features=F.SHARED), HERE / "model.joblib")
    (HERE / "metrics.json").write_text(json.dumps(m, indent=1))
    print(json.dumps({k: v for k, v in m.items() if k not in ("features", "importance")}, indent=1))
    print("top features:", [r["label"] for r in m["importance"][:5]])


if __name__ == "__main__":
    main()
