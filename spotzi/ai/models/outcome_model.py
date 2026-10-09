"""Case-substantiation model (task model #4): learned mapping from detector outputs to simulated closed-case outcomes."""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES = [
    "rule_score",
    "anomaly_pct",
    "graph_score",
    "twin_pct",
    "path_pct",
    "drift_pct",
    "mix_pct",
    "panel_pct",
    "any_share",
    "log_lines",
]  # no forecast input: it is trained on the same labels


def matrix(PT: pd.DataFrame) -> pd.DataFrame:
    X = PT.assign(log_lines=np.log1p(PT.n_lines)).reindex(columns=FEATURES).astype(float)
    return X.fillna(0.5)


def score(PT: pd.DataFrame, m) -> pd.Series:
    return pd.Series(m.predict_proba(matrix(PT))[:, 1], index=PT.index)
