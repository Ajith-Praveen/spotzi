"""Chart-documentation model (task model #2).

Purpose: read a clinical note and estimate the E/M level the documentation supports, so a chart-review sample can be
screened without an LLM (offline, free, instant) and so the LLM gets a second opinion it can disagree with.
Method: TF-IDF (word 1-2 grams + character 3-5 grams) of the note + parsed time features → multinomial logistic
regression over documented level (0 = no documentation, 1-5). Time is parsed deterministically (minutes, start/stop
clock times) because arithmetic is not something a text classifier should learn. Psychotherapy is judged on parsed minutes.
Training: synthetic notes rendered from independent training worlds."""

from __future__ import annotations

import re

import numpy as np
import scipy.sparse as sp

from ai import charts

ABSENT = re.compile(
    r"no encounter documentation|returned no|no record of|does not list the patient|not signed by the member", re.I
)


def minutes(text: str) -> int | None:
    t = text.lower()
    ms = [int(x) for x in re.findall(r"(\d{1,3})\s*(?:min\b|mins\b|minutes\b)", t)]
    for a, b, c, d in re.findall(r"(\d{1,2}):(\d{2})\D{1,30}?(\d{1,2}):(\d{2})", t):
        ms.append((int(c) * 60 + int(d)) - (int(a) * 60 + int(b)))
    if "full hour" in t:
        ms.append(60)
    ms = [m for m in ms if 0 < m < 600]
    return max(ms) if ms else None


def time_level(code: str, m: int | None) -> int:
    if m is None or code not in charts.EM_OFFICE:
        return 0
    return max([lv for lv, (lo, hi) in charts.TIME_BAND.items() if m >= lo], default=1)


class ChartModel:
    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression

        self.w = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
        self.c = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True, max_features=40000
        )
        self.clf = LogisticRegression(C=4.0, max_iter=2000)

    @staticmethod
    def _strip_time(t):  # MDM classifier must not read the minutes (time is handled separately)
        return re.sub(r"\d+", " ", t)

    def _X(self, notes, fit=False):
        txt = [self._strip_time(n) for n in notes]
        a = self.w.fit_transform(txt) if fit else self.w.transform(txt)
        b = self.c.fit_transform(txt) if fit else self.c.transform(txt)
        return sp.hstack([a, b]).tocsr()

    def fit(self, notes, mdm_levels):
        self.clf.fit(self._X(notes, fit=True), np.asarray(mdm_levels))
        return self

    def mdm_proba(self, notes):
        return self.clf.predict_proba(self._X(notes)), self.clf.classes_

    def review(self, code: str, note: str) -> dict:
        """Same output shape as llm_detect.review_heuristic."""
        if ABSENT.search(note):
            return dict(
                documented_code=None,
                supports_billed=False,
                basis="absent",
                quote=ABSENT.search(note).group(0),
                rationale="No documentation for the date.",
                confidence=0.95,
            )
        m = minutes(note)
        if code in charts.PSYCHO:
            if m is None:
                return dict(
                    documented_code=None,
                    supports_billed=False,
                    basis="insufficient",
                    quote="",
                    rationale="No session time found.",
                    confidence=0.6,
                )
            best = max(
                (c for c, mn in charts.PSYCHO_MIN.items() if m >= mn), key=lambda c: charts.PSYCHO_MIN[c], default=None
            )
            return dict(
                documented_code=best,
                supports_billed=m >= charts.PSYCHO_MIN[code],
                basis="time",
                quote=f"{m} minutes",
                rationale=f"{m} min documented; {code} needs {charts.PSYCHO_MIN[code]}+.",
                confidence=0.9,
            )
        billed = charts.EM_OFFICE.get(code) or charts.EM_ED.get(code)
        if not billed:
            return dict(
                documented_code=code,
                supports_billed=True,
                basis="record present",
                quote=note[:80],
                rationale="Service record on file.",
                confidence=0.6,
            )
        p, cls = self.mdm_proba([note])
        p = p[0]
        mdm = int(cls[int(np.argmax(p))])
        conf = float(p.max())
        tl = time_level(code, m)
        lv = max(mdm, tl)
        table = charts.EM_OFFICE if code in charts.EM_OFFICE else charts.EM_ED
        doc = next((c for c, v in table.items() if v == lv), None)
        p_support = float(p[cls >= billed].sum()) if tl < billed else 1.0
        return dict(
            documented_code=doc,
            supports_billed=lv >= billed,
            basis="time" if tl > mdm else "MDM",
            quote=(f"{m} minutes" if tl > mdm else ""),
            rationale=f"Model: MDM level {mdm} (p={conf:.2f}); time level {tl or '—'}; billed {billed}. P(supports) {p_support:.2f}.",
            confidence=round(conf, 3),
            p_support=round(p_support, 3),
        )
