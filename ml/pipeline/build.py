"""
GridIntel training pipeline (Dataset A: HVPNL Faridabad real-world records).

  raw Excel (DATA_ROOT/raw, read-only) → long table → clean wide dataset → per-substation features
  → leave-one-day-out (LODO) ensemble models → out-of-sample scores → model registry + experiment record
  → label-free evaluation report.

Validation protocol: for substations with ≥2 logged days, each day is scored ONLY by a model fitted on the other
days (reference statistics, feature selection, scaling, calibration all from training days). A production model fitted
on all days is also saved for scoring future data. Single-day substations are scored in-sample and flagged.

Run from the project root:  python scripts/build_pipeline.py
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import platform
import re
import time
import uuid
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

from . import features as F
from . import rules as R
from .ensemble import ENSEMBLE_VERSION, WEIGHTS, combine, fit_ensemble
from .ingest import ingest_all, inventory

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.getenv("DATA_ROOT") or ROOT / "data")
if not DATA_ROOT.is_absolute():
    DATA_ROOT = (ROOT / DATA_ROOT).resolve()
RAW = DATA_ROOT / "raw"
PROC = DATA_ROOT / "processed"
FEAT = DATA_ROOT / "features"
MODELS = Path(os.getenv("MODEL_PATH") or ROOT / "models")
REPORTS = Path(os.getenv("REPORTS_DIR") or ROOT / "reports")
EXPERIMENTS = Path(os.getenv("EXPERIMENTS_DIR") or ROOT / "experiments")
SEED = 42
DATASET_ID = "hvpnl-faridabad-2026-02"


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def display_name(sheet: str) -> str:
    m = re.match(r"^(\d+)\s*(kv)?\s*(.*)$", sheet.strip(), flags=re.I)
    if not m:
        return sheet
    return f"{m.group(1)} kV {m.group(3).strip().replace('Sec-46', 'Sector-46')}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare_fold(vsub: pd.DataFrame, ssub, train_days: list[str], meta: dict):
    """Fit references on training days only; build features for ALL rows of this substation."""
    train = vsub[vsub.index.get_level_values("log_date").isin(train_days)]
    usable = F.usable_parameters(train)
    train_imp = F.impute(train[usable])
    med = train_imp.median()
    all_imp = F.impute(vsub[usable], medians=med)
    ref = F.fit_reference(train_imp, meta)
    feats, fmeta = F.engineer(all_imp, ssub, meta, ref)
    return feats, fmeta, ref, usable


def score_rows(bundle, feats_rows: pd.DataFrame, vraw: pd.DataFrame, sraw: pd.DataFrame, meta: dict, usable: list[str]):
    comp = bundle.score(feats_rows)
    rows = []
    for (sub, day, hour, ts), c in comp.iterrows():
        rl = R.evaluate(vraw, sraw, ts, meta, bundle.ref)
        cov = float(vraw.loc[ts, usable].notna().mean()) if usable else 0.0
        comb = combine(c["anomaly_score"], R.severity(rl), {k: c[k] for k in WEIGHTS}, cov, bundle.n_train)
        rows.append({"substation": sub, "log_date": day, "hour": int(hour), "timestamp": ts,
                     "anomaly_score": round(float(c["anomaly_score"]), 1),
                     **{f"{k}_score": round(float(c[k]), 1) for k in WEIGHTS},
                     "iforest_raw": round(float(c["iforest_raw"]), 5), **comb, "data_coverage": round(cov, 3),
                     "rules": json.dumps(rl), "model_key": bundle.extra["key"],
                     "evaluation": "out-of-sample (LODO)" if bundle.holdout_day else "in-sample (single day)"})
    return rows


def main() -> None:
    t0 = time.time()
    run_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    for d in (PROC, FEAT, MODELS, REPORTS, EXPERIMENTS, DATA_ROOT / "registry"):
        d.mkdir(parents=True, exist_ok=True)

    print(f"[1/6] Ingesting Excel workbooks from {RAW} (read-only) ...")
    long = ingest_all(RAW)
    inv = inventory()
    long.to_csv(PROC / "scada_long.csv", index=False)
    inv.to_csv(PROC / "sheet_inventory.csv", index=False)
    raw_files = [{"file": p.name, "sha256": _sha256(p)} for p in sorted(RAW.glob("*.xlsx"))]

    print("[2/6] Clean wide dataset ...")
    values, states, kept = F.build_wide(long)
    meta = {p: F.classify(p) for p in long["parameter"].unique()}
    st_suffixed = states.add_suffix(" [state]") if not states.empty else states
    values.join(st_suffixed, how="left").reset_index().to_csv(PROC / "scada_clean.csv", index=False)

    print("[3/6] Leave-one-day-out ensemble training ...")
    substations, dictionary, scored, registry_models = [], [], [], []
    model_dir = MODELS / "ensemble"
    model_dir.mkdir(parents=True, exist_ok=True)
    for sub, vsub in values.groupby(level="substation"):
        vsub = vsub.dropna(axis=1, how="all")
        sid = slug(sub)
        ssub = states.loc[states.index.get_level_values("substation") == sub].dropna(axis=1, how="all") if not states.empty else None
        days = sorted(vsub.index.get_level_values("log_date").unique())
        vraw = vsub.reset_index(level=["substation", "log_date", "hour"]).drop(columns="substation")
        vraw = vraw.sort_index()
        sraw = ssub.reset_index(level=["substation", "log_date", "hour"], drop=True).sort_index() if ssub is not None else pd.DataFrame()
        (model_dir / sid).mkdir(exist_ok=True)
        served_feats = []

        folds = [(d, [x for x in days if x != d]) for d in days] if len(days) >= 2 else [(None, days)]
        for hold, train_days in folds:
            feats, fmeta, ref, usable = prepare_fold(vsub, ssub, train_days, meta)
            tr = feats[feats.index.get_level_values("log_date").isin(train_days)]
            b = fit_ensemble(sub, tr, fmeta, ref, meta, seed=SEED, holdout_day=hold)
            key = f"fold-{hold}" if hold else "full"
            b.extra.update({"key": key, "usable": usable})
            path = model_dir / sid / f"{key}.joblib"
            joblib.dump(b, path)
            rows = feats[feats.index.get_level_values("log_date") == hold] if hold else feats
            scored += score_rows(b, rows, vraw, sraw, meta, usable)
            served_feats.append(rows.assign(model_key=key))
            registry_models.append({"substation": sid, "key": key, "path": str(path.relative_to(MODELS)),
                                    "sha256": _sha256(path), "fingerprint": b.fingerprint(),
                                    "trained_days": b.trained_days, "holdout_day": hold, "n_train": b.n_train,
                                    "n_features": len(b.features)})
        # production model on all days (for future data); identical to the single fold when only one day exists
        if len(days) >= 2:
            feats, fmeta, ref, usable = prepare_fold(vsub, ssub, days, meta)
            b = fit_ensemble(sub, feats, fmeta, ref, meta, seed=SEED)
            b.extra.update({"key": "full", "usable": usable})
            path = model_dir / sid / "full.joblib"
            joblib.dump(b, path)
            registry_models.append({"substation": sid, "key": "full", "path": str(path.relative_to(MODELS)),
                                    "sha256": _sha256(path), "fingerprint": b.fingerprint(), "trained_days": days,
                                    "holdout_day": None, "n_train": b.n_train, "n_features": len(b.features)})
        pd.concat(served_feats).reset_index().to_csv(FEAT / f"features_{sid}.csv", index=False)

        sub_long = kept[kept.substation == sub]
        usable_all = F.usable_parameters(vsub)
        for p, g in sub_long.groupby("parameter"):
            n, nnum, nstat = len(g), int(g["value"].notna().sum()), int(g["status"].notna().sum())
            ptype = "numeric" if nnum and not nstat else ("status" if nstat and not nnum else ("mixed numeric+status" if nnum else "text"))
            if p in usable_all:
                treat, usage = (f"forward-fill within day (≤{F.GAP_FILL_LIMIT} h), else training-days median",
                                "model input (ensemble)")
            elif nstat:
                treat, usage = "status kept as category; not imputed", "equipment-state features + rule R-E"
            else:
                treat = "kept in clean dataset as NaN; not imputed"
                usage = "excluded from model (coverage <60% or constant)" if nnum else "display only"
            dictionary.append({"substation": sub, "parameter": p, "unit": meta[p]["unit"] + (" (inferred)" if meta[p]["unit"] != "-" else ""),
                               "category": meta[p]["category"], "transformer": F.transformer_id(p) or "", "type": ptype,
                               "records": n, "numeric_pct": round(100 * nnum / n, 1), "status_pct": round(100 * nstat / n, 1),
                               "missing_pct": round(100 * (n - nnum - nstat) / n, 1), "dash_or_blank_cells": int(g["is_missing"].sum()),
                               "missing_value_treatment": treat, "ml_usage": usage,
                               "excel_columns": ",".join(sorted(g["excel_column"].unique()))})
        substations.append({"id": sid, "sheet": sub, "name": display_name(sub),
                            "voltage_class_kv": int(re.match(r"\d+", sub).group(0)), "days": days, "records": int(len(vsub)),
                            "parameters_logged": int(vsub.shape[1]), "model_features": len(b.features),
                            "low_confidence": len(days) < 2, "validation": "LODO out-of-sample" if len(days) >= 2 else "in-sample (1 day)",
                            "has_model": True, "data_status": "AVAILABLE"})
        print(f"    {sub:14s} days={len(days)} records={len(vsub):3d} params={vsub.shape[1]:3d} features={len(b.features)}")

    with_data = {s["sheet"] for s in substations}
    for s in sorted(inv["substation"].unique()):
        if s not in with_data:
            substations.append({"id": slug(s), "sheet": s, "name": display_name(s), "voltage_class_kv": int(re.match(r"\d+", s).group(0)),
                                "days": [], "records": 0, "parameters_logged": 0, "model_features": 0, "low_confidence": True,
                                "validation": None, "has_model": False, "data_status": "NO SOURCE READINGS",
                                "note": "Data unavailable in supplied records (sheet is a blank template in all three files)."})

    sc = pd.DataFrame(scored).sort_values(["timestamp", "substation"])
    sc.to_csv(PROC / "scored_history.csv", index=False)
    pd.DataFrame(dictionary).to_csv(PROC / "data_dictionary.csv", index=False)
    param_meta = {p: {**meta[p], "transformer": F.transformer_id(p), "rating_mva": F.mva_rating(p)} for p in meta}
    (PROC / "parameter_meta.json").write_text(json.dumps(param_meta, indent=1, ensure_ascii=False), encoding="utf-8")
    (MODELS / "substations.json").write_text(json.dumps(substations, indent=1))

    print("[4/6] Evaluation ...")
    from .evaluate import evaluate
    ev = evaluate(values, states, sc, meta)
    (REPORTS / "evaluation.json").write_text(json.dumps(ev, indent=1, default=float))

    print("[5/6] Model registry + experiment record ...")
    created = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    common = {"version": ENSEMBLE_VERSION, "created_at": created, "dataset": DATASET_ID, "run_id": run_id,
              "validation": "leave-one-day-out on HVPNL Faridabad (Dataset A)", "seed": SEED}
    registry = {
        "registry_version": 1, "updated_at": created, "dataset": DATASET_ID, "raw_files": raw_files,
        "ensemble": {**common, "name": f"GridIntel-Ensemble-v{ENSEMBLE_VERSION}", "weights": WEIGHTS,
                     "rules_version": R.RULES_VERSION, "artifacts": registry_models},
        "models": {
            "isolation_forest": {**common, "name": "IForest-v2.0", "status": "trained",
                                 "config": {"n_estimators": 300, "max_samples": "auto", "contamination": "auto", "scaler": "RobustScaler(10,90)"}},
            "autoencoder": {**common, "name": "DenseAE-v2.0", "status": "trained",
                            "config": {"type": "MLPRegressor", "activation": "tanh", "hidden": "(2h, h, 2h), h=clip(n_features/8,3,10)", "alpha": 1e-3}},
            "temporal_autoencoder": {**common, "name": "TemporalWindowAE-v1.0", "status": "trained",
                                     "config": {"pca_components": "≤8", "window_hours": 4, "type": "MLPRegressor"}},
            "lstm_autoencoder": {"name": "LSTM-AE", "status": "not trained",
                                 "reason": "≤24 consecutive hourly samples per day and 3 non-consecutive days; an LSTM would memorise "
                                           "the sequences. Reserved for continuous historian data."},
            "supervised": {"name": "XGBoost/LightGBM classifier", "status": "not trained",
                           "reason": "No genuine fault labels in the supplied records. Operator PTW/Breakdown notes are not fault labels."},
        },
        "evaluation_summary": ev.get("summary", {}),
    }
    (MODELS / "registry.json").write_text(json.dumps(registry, indent=1, default=float))
    for name, m in registry["models"].items():
        d = MODELS / name
        d.mkdir(exist_ok=True)
        (d / "metadata.json").write_text(json.dumps(m, indent=1, default=float))
    feature_schema = {sid: sorted(set().union(*[set(joblib.load(MODELS / r["path"]).features) for r in registry_models if r["substation"] == sid]))
                      for sid in {r["substation"] for r in registry_models}}
    (MODELS / "feature_schema.json").write_text(json.dumps(feature_schema, indent=1, ensure_ascii=False))
    exp = {"run_id": run_id, "created_at": created, "dataset": {"id": DATASET_ID, "files": raw_files},
           "features": {k: len(v) for k, v in feature_schema.items()}, "model": f"GridIntel-Ensemble-v{ENSEMBLE_VERSION}",
           "hyperparameters": {"weights": WEIGHTS, **{k: v.get("config") for k, v in registry["models"].items() if "config" in v}},
           "random_seed": SEED, "metrics": ev.get("summary", {}), "artifacts": [r["path"] for r in registry_models],
           "environment": {"python": platform.python_version(), "scikit_learn": sklearn.__version__,
                           "pandas": pd.__version__, "numpy": np.__version__}}
    (EXPERIMENTS / f"{run_id}.json").write_text(json.dumps(exp, indent=1, default=float))
    print(f"[6/6] Done in {time.time() - t0:.1f}s · run {run_id}")


if __name__ == "__main__":
    main()
