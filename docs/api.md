# API reference (v1)

Base: `https://<host>/api/v1` · OpenAPI UI: `/docs` · schema: `/api/v1/openapi.json`. All endpoints require `Authorization: Bearer <token>` unless marked *public*. Errors: `{"error", "detail", "request_id"}`.

| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/auth/login` | public | `{username, password}` → `{access_token, expires_in, user}` (rate-limited) |
| GET | `/auth/me` | any | current user and role |
| GET | `/auth/audit` | ADMIN | audit log |
| GET | `/public/stats` | public | aggregate counts for the landing page (no measurements) |
| GET | `/command-center` | VIEWER | grid health index, active substations, alerts, high-risk events, model status, per-substation risk, recent alerts |
| GET | `/substations` | VIEWER | all sheets; current risk/health for those with readings; `NO SOURCE READINGS` otherwise |
| GET | `/substations/{id}` | VIEWER | current snapshot (all parameters), series to replay cursor, alerts, transformers |
| GET | `/substations/{id}/topology?timestamp=` | VIEWER | digital substation: buses, transformers, feeders, couplers with values, status, signals, rules |
| GET | `/scada/latest?substation=` | VIEWER | replay status + current record |
| GET | `/scada/record?substation=&timestamp=` | VIEWER | any historical record |
| GET | `/scada/history?substation=&start=&end=&last=&upto_cursor=&params=` | VIEWER | time series (key signals, selected params, anomaly, risk, confidence) |
| GET | `/alerts?substation=&category=&page=&size=` | VIEWER | replay alerts (paginated) |
| POST | `/alerts/{id}/acknowledge` | OPERATOR | acknowledge (audited) |
| GET | `/anomalies?substation=&min_risk=&start=&end=&page=&size=` | VIEWER | scored historical hours (out-of-sample) |
| GET | `/investigations?substation=&timestamp=` | VIEWER | what / why / how unusual / what to investigate, contributing signals, rules, evidence, trend, notes |
| GET | `/investigations/demo` | VIEWER | the two reviewed real events |
| POST | `/investigations/notes` | ENGINEER | add note `{substation, timestamp, status, note}` (audited) |
| GET | `/analytics?substation=&start=&end=&parameter=` | VIEWER | distributions, trends, equipment health, top signals, correlation, anomaly timeline, evaluation |
| GET | `/fleet?sort=risk\|newest\|temperature\|loading` | VIEWER | fleet table |
| GET | `/models` | VIEWER | registry, artifacts, latency, evaluation, benchmarks |
| GET | `/parameters?substation=&q=` | VIEWER | data dictionary |
| GET | `/explorer?substation=&parameter=&date=&hour=&page=&size=` | VIEWER | raw vs cleaned values, rolling stats, scores |
| GET | `/explorer/export.csv` | VIEWER | CSV export (audited) |
| GET | `/replay/status` | VIEWER | mode, cursor, timestamp, speed, recent events |
| POST | `/replay/start` `{date?, speed?, reset?}` · `/pause` · `/stop` · `/next` · `/speed {speed}` · `/seek {timestamp}` | OPERATOR | replay control |

System (public): `GET /health` (liveness), `GET /ready` (model store + database), `GET /metrics` (Prometheus: request counts/latency, model inference latency, alerts raised, replay cursor, errors).
