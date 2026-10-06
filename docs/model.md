# Models

Methodology and evaluation design: [research-methodology.md](research-methodology.md). Features: [features.md](features.md).

| Model | Status | Implementation | Key settings |
|---|---|---|---|
| Isolation Forest (IForest-v2.1) | trained | `pipeline/model.py` | 300 trees, `max_samples=auto`, RobustScaler(10–90), occlusion explanations |
| Dense autoencoder (DenseAE-v2.1) | trained | `pipeline/ensemble.py` | MLP (2h, h, 2h), tanh, α=1e-3, h = clip(n_features/8, 3, 10) |
| Temporal-window AE (TemporalWindowAE-v1.0) | trained | `pipeline/ensemble.py` | PCA ≤ 8 comps, 4-hour windows within a day, MLP AE |
| Engineering rules (v1.2.0) | active | `pipeline/rules.py` | R-V1/V2 voltage, R-L1/L2 loading, R-T1/T2/T3 thermal, R-S1 rating, R-E1/E2 operator states |
| Unit plausibility (v1.0.0) | active | `pipeline/plausibility.py` | √3·V·I and nominal-kV checks on header-inferred units before rules/displays use them |
| LSTM autoencoder | not trained | — | ≤ 24 consecutive hourly samples per day; would memorise |
| XGBoost / LightGBM classifier | not trained | — | no genuine fault labels |

Ensemble v2.1.0: anomaly = 0.45·IF + 0.30·AE + 0.25·TW-AE (each held-out calibrated to 0–100); risk = 0.7·max(anomaly, rules) + 0.3·mean(anomaly, rules); confidence = 50·agreement + 30·coverage + 20·training size. Categories NORMAL ≤ 30 < WATCH ≤ 55 < WARNING ≤ 75 < HIGH RISK ≤ 90 < CRITICAL — prototype AI risk classification.

Versioning: every training run writes `models/registry.json` (artifact SHA-256 + fingerprint, trained/held-out days, configs, status), `models/feature_schema.json`, per-model `metadata.json`, and `experiments/<run_id>.json` (dataset file hashes, features, hyper-parameters, seed, metrics, library versions). MLflow was not added to keep deployment simple; the experiment JSON follows the same fields and can be imported later.


## Thermal rules (v1.2.0)
The load→winding-temperature line is fitted on the training days only. Ambient temperature is not logged, so a held-out day that is uniformly warmer shows a constant positive residual. The rules therefore separate:

| Rule | Condition (residual > 3 °C and > 3·MAD) | Severity |
|---|---|---|
| R-T1 | residual exceeds the same day's earlier-hours median residual by ≥ 3·MAD — an hour-level excursion | 0.60 / 0.75 |
| R-T1 (early day) | fewer than 3 earlier readings that day — cannot yet tell excursion from offset | 0.45 |
| R-T3 | residual explained by a day-long offset (≥ 3 earlier hours) — reported with an explicit ambient caveat | 0.35 (WATCH level) |

Only same-day **earlier** hours are used, so the rule stays causal in replay.

## Unit plausibility (v1.0.0)
Before rules or displays use a parameter, `pipeline/plausibility.py` checks its logged magnitudes:
- bus-voltage columns must lie within ±20 % of the nominal kV in their own name; 240 V AC / DC battery columns are moved to auxiliary categories;
- an "MVA" column for which a sibling MVA column of the same transformer exists is re-classified as a current only if √3 × V × I reproduces that MVA within ±20 %; an MVA column above 1.5 × nameplate is marked unverified.
Unverified parameters stay in the clean dataset and the (unit-agnostic) anomaly models but are excluded from engineering rules and physical cards. Every decision is written to `reports/data_quality.{md,json}`.
