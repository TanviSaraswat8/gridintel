# Models

Methodology and evaluation design: [research-methodology.md](research-methodology.md). Features: [features.md](features.md).

| Model | Status | Implementation | Key settings |
|---|---|---|---|
| Isolation Forest (IForest-v2.0) | trained | `pipeline/model.py` | 300 trees, `max_samples=auto`, RobustScaler(10–90), occlusion explanations |
| Dense autoencoder (DenseAE-v2.0) | trained | `pipeline/ensemble.py` | MLP (2h, h, 2h), tanh, α=1e-3, h = clip(n_features/8, 3, 10) |
| Temporal-window AE (TemporalWindowAE-v1.0) | trained | `pipeline/ensemble.py` | PCA ≤ 8 comps, 4-hour windows within a day, MLP AE |
| Engineering rules (v1.0.0) | active | `pipeline/rules.py` | R-V1/V2 voltage, R-L1/L2 loading, R-T1/T2 thermal, R-S1 rating, R-E1/E2 operator states |
| LSTM autoencoder | not trained | — | ≤ 24 consecutive hourly samples per day; would memorise |
| XGBoost / LightGBM classifier | not trained | — | no genuine fault labels |

Ensemble v2.0.0: anomaly = 0.45·IF + 0.30·AE + 0.25·TW-AE (each held-out calibrated to 0–100); risk = 0.7·max(anomaly, rules) + 0.3·mean(anomaly, rules); confidence = 50·agreement + 30·coverage + 20·training size. Categories NORMAL ≤ 30 < WATCH ≤ 55 < WARNING ≤ 75 < HIGH RISK ≤ 90 < CRITICAL — prototype AI risk classification.

Versioning: every training run writes `models/registry.json` (artifact SHA-256 + fingerprint, trained/held-out days, configs, status), `models/feature_schema.json`, per-model `metadata.json`, and `experiments/<run_id>.json` (dataset file hashes, features, hyper-parameters, seed, metrics, library versions). MLflow was not added to keep deployment simple; the experiment JSON follows the same fields and can be imported later.
