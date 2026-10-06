# Architecture

See the Mermaid diagrams in the [README](../README.md#architecture).

## Components
| Component | Path | Notes |
|---|---|---|
| Ingestion | `ml/pipeline/ingest.py` | merged headers, hourly block detection, cell parsing, sheet inventory |
| Features | `ml/pipeline/features.py` | classification, causal imputation, training-only references, engineered features |
| Rules | `ml/pipeline/rules.py` | engineering signals with severity, message, parameters, investigation hint |
| Models | `ml/pipeline/model.py`, `ensemble.py` | Isolation Forest + occlusion explanations; dense AE; temporal-window AE; held-out calibration; risk/confidence |
| Training | `ml/pipeline/build.py` | leave-one-day-out folds, production model, registry, experiment record |
| Evaluation | `ml/pipeline/evaluate.py`, `benchmarks.py` | label-free evaluation; public benchmark |
| API | `backend/app` | `core/` (config, security, cache, observability), `db/` (models, session), `services/` (store, replay, investigation, seed), `api/v1/` (auth, grid, intel) |
| Migrations | `backend/migrations` | Alembic; `alembic upgrade head` on container start |
| Web | `frontend/` | `index.html` landing, `app.html` + `assets/js/app/*` command center (ES modules, Chart.js vendored) |
| Mobile | `mobile/` | Expo SDK 57; `src/api.js`, `src/screens.js`, `App.js` |

## Data flow
`DATA_ROOT/raw` → `processed/` → `features/` → `models/ensemble/<sid>/fold-<day>.joblib` → API store → live inference per replayed record → alerts in PostgreSQL → web/mobile polling.

## Storage
PostgreSQL tables: `users`, `substations`, `equipment`, `scada_readings`, `features`, `anomalies`, `alerts`, `investigations`, `model_versions`, `data_sources`, `audit_log`. Reads for dashboards are served from an in-memory read model built from the pipeline artifacts (small dataset, sub-10 ms responses); the database holds readings, scores, users and all mutable state. Redis: rate-limit counters, replay status mirror, cache (in-memory fallback).

## Scaling notes
The replay engine is a single in-process task (run one API worker). Horizontal scaling would move the replay cursor and events to Redis streams. TimescaleDB would suit `scada_readings` once continuous historian data is ingested.
