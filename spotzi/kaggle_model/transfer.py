"""Score ClaimShield providers with the Kaggle-trained model (relative-feature transfer)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import features as F

HERE = Path(__file__).parent


def available() -> bool:
    return (HERE / "model.joblib").exists()


def metrics():
    p = HERE / "metrics.json"
    return json.loads(p.read_text()) if p.exists() else None


def score(L, members, providers) -> tuple[pd.Series, pd.DataFrame]:
    bundle = joblib.load(HERE / "model.joblib")
    f, fam = F.from_claimshield(L, members, providers)
    Xn = F.rank_norm(f, fam)[bundle["features"]]
    p = .5 * bundle["lr"].predict_proba(Xn)[:, 1] + .5 * bundle["gb"].predict_proba(Xn)[:, 1]
    return pd.Series(p, index=Xn.index), Xn
