"""
Public-benchmark method validation (NOT HVPNL data, never used to fit HVPNL models).

ETT-small / ETTh1 (CC BY-ND 4.0): one real transformer, hourly load channels + oil temperature, 2016-07 → 2018-06.
Questions answered:
  1. Is a load→temperature linear model (the basis of the HVPNL thermal-residual feature) predictive out of time?
  2. How does the Isolation Forest score distribution behave on a later, unseen period (drift sensitivity)?
Chronological split: first 70 % train, last 30 % test. Run: python scripts/fetch_public_data.py && python scripts/run_benchmarks.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.preprocessing import RobustScaler

ROOT = Path(__file__).resolve().parents[2]


def ett(path: Path) -> dict:
    df = pd.read_csv(path, parse_dates=["date"])
    loads = ["HUFL", "HULL", "MUFL", "MULL", "LUFL", "LULL"]
    df["hour_sin"] = np.sin(2 * np.pi * df.date.dt.hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df.date.dt.hour / 24)
    df["load_3h"] = df["HUFL"].rolling(3, min_periods=1).mean()
    n = int(len(df) * 0.7)
    tr, te = df.iloc[:n], df.iloc[n:]
    X = loads + ["load_3h", "hour_sin", "hour_cos"]
    lr = LinearRegression().fit(tr[X], tr["OT"])
    pred_tr, pred_te = lr.predict(tr[X]), lr.predict(te[X])
    resid_te = te["OT"] - pred_te
    # anomaly-model drift check
    feats = loads + ["OT", "hour_sin", "hour_cos"]
    sc = RobustScaler(quantile_range=(10, 90)).fit(tr[feats])
    iso = IsolationForest(n_estimators=300, random_state=42).fit(sc.transform(tr[feats]))
    a_tr, a_te = -iso.score_samples(sc.transform(tr[feats])), -iso.score_samples(sc.transform(te[feats]))
    thr = np.percentile(a_tr, 97.5)
    res = {
        "dataset": "ETTh1 (ETT-small)", "license": "CC BY-ND 4.0", "records": int(len(df)),
        "split": f"chronological: train {tr.date.iloc[0]:%Y-%m-%d}→{tr.date.iloc[-1]:%Y-%m-%d}, test {te.date.iloc[0]:%Y-%m-%d}→{te.date.iloc[-1]:%Y-%m-%d}",
        "thermal_model": {"r2_train": round(r2_score(tr["OT"], pred_tr), 3), "r2_test": round(r2_score(te["OT"], pred_te), 3),
                          "mae_test_c": round(mean_absolute_error(te["OT"], pred_te), 2),
                          "residual_test_p95_abs_c": round(float(np.percentile(np.abs(resid_te), 95)), 2)},
        "iforest_drift": {"train_p97_5": round(float(thr), 4), "share_test_hours_above_train_p97_5": round(float((a_te > thr).mean()), 3)},
        "labels": "none — no accuracy reported",
    }
    tm, dr = res["thermal_model"], res["iforest_drift"]
    gen = tm["r2_test"] > 0.3
    drift = dr["share_test_hours_above_train_p97_5"]
    res["summary"] = (
        f"{res['records']} hourly records, chronological 70/30 split. Load→oil-temperature linear model: R² {tm['r2_train']} (train) / "
        f"{tm['r2_test']} (test), test MAE {tm['mae_test_c']} °C — "
        + ("the relationship generalises out of time." if gen else
           "a static load→temperature fit does NOT generalise across seasons (ambient temperature is unobserved). The HVPNL thermal "
           "residual is therefore fitted on same-month training days only and used as one contributing signal, never as a verdict.")
        + f" Isolation Forest: {drift * 100:.1f}% of later-period hours exceed the training 97.5th percentile (2.5% expected without drift) — "
        + ("no material score drift on this series." if drift <= 0.04 else "score drift present; held-out calibration and periodic retraining are required."))
    return res


def run() -> dict:
    out = {}
    p = ROOT / "data" / "external" / "ett" / "ETTh1.csv"
    if p.exists():
        out["ETTh1 — Electricity Transformer Temperature"] = ett(p)
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "benchmarks.json").write_text(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=1, default=str))
