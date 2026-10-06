"""
Unsupervised anomaly model (Isolation Forest) per substation + risk scoring + explanations.

No fault labels exist in the source logs, so no accuracy/precision/recall is computed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

# Prototype thresholds on the 0-100 risk scale. NOT utility protection limits.
RISK_BANDS = [(30, "NORMAL"), (60, "WATCH"), (80, "WARNING"), (100, "HIGH RISK")]
ALERT_MIN_LEVEL = "WARNING"


def risk_category(risk: float) -> str:
    for upper, name in RISK_BANDS:
        if risk <= upper:
            return name
    return "HIGH RISK"


@dataclass
class SubstationModel:
    substation: str
    features: list[str]
    scaler: RobustScaler
    forest: IsolationForest
    calib: dict                      # anomaly-score calibration points (from training scores)
    feature_meta: dict
    baseline: dict                   # per feature: median, p10, p90, mad
    n_train: int
    low_confidence: bool = False
    extra: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- scoring
    def anomaly_score(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        Xs = self.scaler.transform(np.asarray(X, dtype=float))
        return -self.forest.score_samples(Xs)  # ~0.3 (very normal) .. ~0.8 (very anomalous)

    def risk(self, a: np.ndarray) -> np.ndarray:
        """Piecewise-linear map of anomaly score to 0-100.
        median training score -> 15, 90th pct -> 45, 97.5th pct -> 72, 99.5th/max -> 88, beyond extrapolates to 100.
        So on the training history roughly 10% of hours sit above NORMAL and a few % reach WARNING."""
        c = self.calib
        xp = [c["min"], c["p50"], c["p90"], c["p975"], c["pmax"], c["pmax"] + 2 * (c["pmax"] - c["p975"]) + 1e-6]
        fp = [0, 15, 45, 72, 88, 100]
        return np.clip(np.interp(a, xp, fp), 0, 100)

    # ---------------------------------------------------------------- explanation
    def explain(self, x: pd.Series, top_k: int = 6) -> list[dict]:
        """Occlusion attribution: replace each feature with its baseline median and measure how much the
        anomaly score drops. Combined with robust deviation (z) for display. These are contributing signals,
        not causes."""
        x = x[self.features].astype(float)
        base_a = float(self.anomaly_score(x.values.reshape(1, -1))[0])
        n = len(self.features)
        tiled = np.tile(x.values, (n, 1))
        meds = np.array([self.baseline[f]["median"] for f in self.features])
        tiled[np.arange(n), np.arange(n)] = meds
        occl = self.anomaly_score(tiled)
        delta = base_a - occl
        rows = []
        for i, f in enumerate(self.features):
            b = self.baseline[f]
            z = (x.iloc[i] - b["median"]) / (b["mad"] if b["mad"] > 0 else (b["std"] or 1.0))
            rows.append((f, float(delta[i]), float(z), float(x.iloc[i])))
        rows.sort(key=lambda r: r[1], reverse=True)
        pos_total = sum(max(r[1], 0) for r in rows) or 1e-9
        out = []
        for f, d, z, v in rows[:top_k]:
            if d <= 0:
                break
            share = d / pos_total
            m = self.feature_meta.get(f, {})
            b = self.baseline[f]
            level = "High" if share >= 0.25 or abs(z) >= 4 else ("Moderate" if share >= 0.10 or abs(z) >= 2 else "Low")
            out.append({
                "feature": f,
                "base_parameter": m.get("base_parameter", f),
                "kind": m.get("kind", "measurement"),
                "description": m.get("description", ""),
                "value": round(v, 3),
                "baseline_median": round(b["median"], 3),
                "baseline_p10": round(b["p10"], 3),
                "baseline_p90": round(b["p90"], 3),
                "deviation_z": round(z, 2),
                "direction": "above" if v > b["median"] else ("below" if v < b["median"] else "at"),
                "score_contribution": round(d, 4),
                "contribution_share": round(share, 3),
                "level": level,
            })
        return out


def fit_substation(sub: str, feats: pd.DataFrame, fmeta: dict, seed: int = 42, n_estimators: int = 300) -> SubstationModel:
    cols = [c for c in feats.columns if feats[c].std() > 0]
    X = feats[cols].values.astype(float)
    scaler = RobustScaler(quantile_range=(10, 90)).fit(X)
    forest = IsolationForest(n_estimators=n_estimators, max_samples="auto", contamination="auto",
                             random_state=seed).fit(scaler.transform(X))
    a = -forest.score_samples(scaler.transform(X))
    calib = {
        "min": float(a.min()), "p50": float(np.percentile(a, 50)), "p90": float(np.percentile(a, 90)),
        "p975": float(np.percentile(a, 97.5)), "pmax": float(max(np.percentile(a, 99.5), a.max())),
    }
    baseline = {}
    for c in cols:
        s = feats[c].astype(float)
        mad = float((s - s.median()).abs().median() * 1.4826)
        baseline[c] = {"median": float(s.median()), "p10": float(s.quantile(0.1)), "p90": float(s.quantile(0.9)),
                       "mad": mad, "std": float(s.std())}
    return SubstationModel(sub, cols, scaler, forest, calib, {c: fmeta[c] for c in cols}, baseline,
                           n_train=len(feats), low_confidence=len(feats) < 48)
