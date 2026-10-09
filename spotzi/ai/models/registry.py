"""Model registry: every SpotZⁱ task model is a versioned artifact (joblib) with a model card (JSON) holding its purpose,
training data, features, held-out metrics and limitations. Artifacts live in data/models/ and are produced only by
ai/models/train_all.py — never at request time — so what runs in production is exactly what was evaluated."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import joblib

DIR = Path(__file__).resolve().parents[2] / "data" / "models"
_cache: dict = {}


def save(name: str, obj, card: dict):
    DIR.mkdir(parents=True, exist_ok=True)
    p = DIR / f"{name}.joblib"
    joblib.dump(obj, p)
    card = dict(
        card,
        name=name,
        trained=time.strftime("%Y-%m-%d %H:%M:%S"),
        artifact=p.name,
        sha256=hashlib.sha256(p.read_bytes()).hexdigest()[:16],
    )
    (DIR / f"{name}.json").write_text(json.dumps(card, indent=1, default=str))
    _cache.pop(name, None)
    return card


def load(name: str):
    """Returns the fitted object, or None when the model has not been trained."""
    p = DIR / f"{name}.joblib"
    if not p.exists():
        return None
    m = p.stat().st_mtime
    if name not in _cache or _cache[name][0] != m:
        try:
            _cache[name] = (m, joblib.load(p))
        except Exception as e:  # stale artifact (code moved / changed): treat as untrained until retrained
            print(
                f"SpotZⁱ: model {name} could not be loaded ({type(e).__name__}); retrain with python3 -m ai.models.train_all"
            )
            _cache[name] = (m, None)
    return _cache[name][1]


def card(name: str) -> dict | None:
    p = DIR / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def cards() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(DIR.glob("*.json"))] if DIR.exists() else []
