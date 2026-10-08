"""Tip-triage model (task model #3): ensemble of
  (a) TF-IDF word + character n-grams → logistic regression, and
  (b) a local sentence encoder (BAAI/bge-small-en-v1.5, 33M params, MIT licence, runs offline on CPU/Apple GPU) → logistic regression.
Probabilities are averaged. If the encoder files are absent the model falls back to (a) alone.
The encoder is a frozen, general-purpose open model; only the classifier heads are trained by SpotZⁱ, on synthetic tips."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

ENCODER = "BAAI/bge-small-en-v1.5"
LOCAL = Path(__file__).resolve().parents[2] / "data" / "models" / "encoders" / "bge-small-en-v1.5"
_enc = {}


def _encoder():
    if "m" not in _enc:
        try:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            import torch
            from transformers import AutoModel, AutoTokenizer
            src = str(LOCAL) if LOCAL.exists() else ENCODER
            tok = AutoTokenizer.from_pretrained(src); m = AutoModel.from_pretrained(src).eval()
            _enc["m"] = (tok, m, torch)
        except Exception:
            _enc["m"] = None
    return _enc["m"]


def export_encoder():
    """Copy the encoder into data/models/encoders so the product runs fully offline without the HF cache."""
    e = _encoder()
    if e is None: return False
    LOCAL.mkdir(parents=True, exist_ok=True); e[0].save_pretrained(LOCAL); e[1].save_pretrained(LOCAL)
    return True


def embed(texts):
    e = _encoder()
    if e is None: return None
    tok, m, torch = e; out = []
    with torch.no_grad():
        for i in range(0, len(texts), 64):
            b = tok(list(texts[i:i + 64]), padding=True, truncation=True, max_length=128, return_tensors="pt")
            out.append(torch.nn.functional.normalize(m(**b).last_hidden_state[:, 0], dim=-1).numpy())
    return np.vstack(out)


class TipModel:
    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline, make_union
        self.tfidf = make_pipeline(make_union(TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=2),
                                              TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2)),
                                   LogisticRegression(C=6, max_iter=3000))
        self.emb = LogisticRegression(C=10, max_iter=3000)
        self.uses_encoder = False

    def fit(self, X, y):
        self.tfidf.fit(X, y); self.classes_ = self.tfidf.classes_
        E = embed(X)
        if E is not None: self.emb.fit(E, y); self.uses_encoder = True
        return self

    def predict_proba(self, X):
        p = self.tfidf.predict_proba(X)
        if self.uses_encoder:
            E = embed(X)
            if E is not None: p = (p + self.emb.predict_proba(E)) / 2
        return p

    def predict(self, X):
        return self.classes_[self.predict_proba(X).argmax(1)]
