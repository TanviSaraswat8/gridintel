"""
Ensemble anomaly engine.

Components (all unsupervised, fit per substation on TRAINING days only):
  1. Isolation Forest                     (pipeline.model.SubstationModel)
  2. Dense autoencoder                    (sklearn MLP, reconstruction error)
  3. Temporal-window autoencoder (TW-AE)  (PCA-compressed hourly vectors, 4-hour windows within a day, MLP AE)
  4. Rule-based engineering signals       (pipeline.rules) — applied at scoring time

Each model score is calibrated against its own training-score distribution to 0–100, then combined:
  anomaly  = 0.45·IF + 0.30·AE + 0.25·TW-AE
  risk     = 0.7·max(anomaly, R) + 0.3·mean(anomaly, R)      R = 100 × rule severity
  confidence (0–100) = 50·model agreement + 30·data coverage + 20·training-size factor
Categories are a PROTOTYPE AI risk classification, not protection thresholds.
"""
from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.exceptions import ConvergenceWarning
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import RobustScaler

from .model import SubstationModel, fit_substation

ENSEMBLE_VERSION = "2.0.0"
WEIGHTS = {"iforest": 0.45, "autoencoder": 0.30, "temporal_ae": 0.25}
WINDOW = 4
CATEGORIES = [(30, "NORMAL"), (55, "WATCH"), (75, "WARNING"), (90, "HIGH RISK"), (100, "CRITICAL")]
ALERT_CATEGORIES = ("WARNING", "HIGH RISK", "CRITICAL")


def category(risk: float) -> str:
    for hi, name in CATEGORIES:
        if risk <= hi:
            return name
    return "CRITICAL"


def _calib_points(train_scores: np.ndarray) -> list[float]:
    s = np.asarray(train_scores, float)
    p975, pmax = np.percentile(s, 97.5), max(np.percentile(s, 99.5), s.max())
    return [float(s.min()), float(np.percentile(s, 50)), float(np.percentile(s, 90)), float(p975), float(pmax),
            float(pmax + 2 * (pmax - p975) + 1e-9)]


def calibrate(x, pts) -> np.ndarray:
    """Piecewise-linear map: min→0, median→15, p90→45, p97.5→72, max→88, beyond→100."""
    return np.clip(np.interp(np.asarray(x, float), pts, [0, 15, 45, 72, 88, 100]), 0, 100)


def _scale(scaler, X):
    return np.clip(scaler.transform(X), -10, 10)


def _mlp(hidden, seed):
    return MLPRegressor(hidden_layer_sizes=hidden, activation="tanh", alpha=1e-3, max_iter=2500,
                        learning_rate_init=3e-3, random_state=seed)


def _windows(Z: np.ndarray, days: np.ndarray, w: int = WINDOW) -> np.ndarray:
    """For each row, the flattened window of the previous w-1 rows + itself within the same day (left-padded)."""
    out = np.zeros((len(Z), w * Z.shape[1]))
    for i in range(len(Z)):
        idx = [i]
        j = i
        while len(idx) < w:
            if j - 1 >= 0 and days[j - 1] == days[i]:
                j -= 1
            idx.insert(0, j)
        out[i] = Z[idx].ravel()
    return out


@dataclass
class EnsembleBundle:
    substation: str
    features: list[str]
    iforest: SubstationModel
    scaler: RobustScaler
    ae: MLPRegressor
    pca: PCA
    twae: MLPRegressor
    calib: dict
    ref: dict
    meta: dict
    trained_days: list[str]
    n_train: int
    seed: int
    version: str = ENSEMBLE_VERSION
    holdout_day: str | None = None
    extra: dict = field(default_factory=dict)

    # ------------------------------------------------------------- component scores
    def raw_scores(self, feats: pd.DataFrame) -> dict[str, np.ndarray]:
        X = feats.reindex(columns=self.features).astype(float).fillna(
            pd.Series({f: self.iforest.baseline[f]["median"] for f in self.features})).values
        Xs = _scale(self.scaler, X)
        ae = ((self.ae.predict(Xs) - Xs) ** 2).mean(axis=1)
        days = feats.index.get_level_values("log_date").values
        W = _windows(self.pca.transform(Xs), days)
        tw = ((self.twae.predict(W) - W) ** 2).mean(axis=1)
        return {"iforest": self.iforest.anomaly_score(X), "autoencoder": ae, "temporal_ae": tw}

    def score(self, feats: pd.DataFrame) -> pd.DataFrame:
        raw = self.raw_scores(feats)
        out = pd.DataFrame(index=feats.index)
        for k, v in raw.items():
            out[f"{k}_raw"] = v
            out[k] = calibrate(v, self.calib[k])
        out["anomaly_score"] = sum(WEIGHTS[k] * out[k] for k in WEIGHTS)
        return out

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        h.update(("|".join(self.features) + self.version + str(self.seed) + ",".join(self.trained_days)).encode())
        h.update(np.round(self.scaler.center_, 6).tobytes())
        for c in self.ae.coefs_:
            h.update(np.round(c, 6).tobytes())
        return h.hexdigest()[:16]


def fit_ensemble(sub: str, feats: pd.DataFrame, fmeta: dict, ref: dict, meta: dict, seed: int = 42,
                 holdout_day: str | None = None, calibrate_held_out: bool = True) -> EnsembleBundle:
    cols = [c for c in feats.columns if feats[c].std() > 0]
    feats = feats[cols]
    iforest = fit_substation(sub, feats, fmeta, seed=seed)
    X = feats.values.astype(float)
    scaler = RobustScaler(quantile_range=(10, 90)).fit(X)
    Xs = _scale(scaler, X)
    h = max(3, min(10, len(cols) // 8))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        ae = _mlp((2 * h, h, 2 * h), seed).fit(Xs, Xs)
        k = max(2, min(8, len(cols) - 1, len(X) - 2))
        pca = PCA(n_components=k, random_state=seed).fit(Xs)
        days = feats.index.get_level_values("log_date").values
        W = _windows(pca.transform(Xs), days)
        twae = _mlp((max(4, W.shape[1] // 2), max(2, k // 2), max(4, W.shape[1] // 2)), seed).fit(W, W)
    b = EnsembleBundle(sub, cols, iforest, scaler, ae, pca, twae, {}, ref, meta,
                       sorted(set(days)), len(X), seed, holdout_day=holdout_day)
    raw = b.raw_scores(feats)
    b.calib = {k: _calib_points(v) for k, v in raw.items()}
    b.extra["calibration"] = "in-sample"
    if calibrate_held_out:
        b.extra["calibration"] = cross_calibrate(b, feats, fmeta, ref, meta)
    return b


def cross_calibrate(b: EnsembleBundle, feats: pd.DataFrame, fmeta: dict, ref: dict, meta: dict) -> str:
    """Replace in-sample calibration with held-out calibration: for each training day, fit an inner ensemble on the
    other training days and score that day; the pooled held-out raw scores define the calibration curve
    (split-conformal style). Falls back to in-sample calibration when only one training day exists."""
    days = sorted(set(feats.index.get_level_values("log_date")))
    if len(days) < 2:
        return "in-sample (single training day)"
    pooled: dict[str, list] = {k: [] for k in WEIGHTS}
    for d in days:
        tr = feats[feats.index.get_level_values("log_date") != d]
        te = feats[feats.index.get_level_values("log_date") == d]
        inner = fit_ensemble(b.substation, tr, fmeta, ref, meta, seed=b.seed, calibrate_held_out=False)
        for k, v in inner.raw_scores(te).items():
            pooled[k].extend(v.tolist())
    b.calib = {k: _calib_points(np.array(v)) for k, v in pooled.items()}
    return f"held-out (inner leave-one-day-out over {len(days)} training days)"


def combine(anomaly: float, rule_sev: float, components: dict, coverage: float, n_train: int) -> dict:
    R = 100.0 * rule_sev
    risk = 0.7 * max(anomaly, R) + 0.3 * (anomaly + R) / 2
    # agreement across all evidence sources: the three models, plus the rule engine when a rule fired
    comp = np.array([components[k] for k in WEIGHTS] + ([R] if R > 0 else []), float)
    agreement = float(np.clip(1 - comp.std() / 40.0, 0, 1))
    size = float(min(1.0, n_train / 48.0))
    conf = float(np.clip(100 * (0.5 * agreement + 0.3 * coverage + 0.2 * size), 5, 99))
    return {"risk_score": round(float(np.clip(risk, 0, 100)), 1), "confidence": round(conf, 1),
            "risk_category": category(risk), "rule_score": round(R, 1), "model_agreement": round(agreement, 3)}
