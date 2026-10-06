# Research methodology

## 1. Research question
Can unsupervised models, combined with simple engineering rules, surface *potential abnormal operating conditions* in hourly substation log data early enough, and explain them clearly enough, to support an operator's investigation — without fault labels and without fabricating data?

## 2. Data roles — training vs validation vs real-world data

| Term | Meaning in this project |
|---|---|
| **Real-world data** | Dataset A, HVPNL Faridabad daily log sheets (02, 10, 27 Feb 2026). Private, never committed, never mixed with public data. |
| **Training data** | For each scored day *d* of a substation: the *other* HVPNL days of that same substation. All reference statistics (medians, feature selection, scaler, thermal fit, ratings, calibration curve) come from these days only. |
| **Validation data** | The held-out day *d* — scored by models that never saw it (leave-one-day-out, LODO). These out-of-sample scores are what the product displays and replays. |
| **Calibration data** | Inside each training set, an inner leave-one-day-out produces held-out scores used to calibrate the 0–100 scale (split-conformal style). |
| **Public benchmark data** | ETTh1 (CC BY-ND 4.0). Used only to test methods (thermal residual generalisation, score drift). Never used to fit or tune HVPNL models. |
| **Test fixtures** | A synthetic workbook generated inside the test suite to exercise parsing and the API in CI. Never shipped, never shown in the UI. |

Single-day sheets (220 Palla) cannot be held out; they are scored in-sample and flagged *low confidence* everywhere they appear.

### Leakage controls
- Causal imputation only (forward-fill ≤ 2 h, then training median) — no backward fill.
- Rolling and rate features are computed within a day; days are non-consecutive.
- Feature selection (coverage ≥ 60 %, non-constant) on training days only.
- Calibration on inner held-out days, not on the scored day.
- The production ("full") model, trained on all days, is saved for future data but **never** used to score historical HVPNL records shown in the product.
- Tests assert that each fold's held-out day is absent from its training days.

## 3. Dataset construction
Workbook ingestion (`ml/pipeline/ingest.py`) expands merged header cells, builds parameter names from up to four header rows, detects the hourly block as the longest run of hour-stamped rows (handles `HH:MM`, Excel time, `24:00` timedelta and integer hours), excludes footer blocks, and parses each cell into raw text, numeric value, status token (ON, OFF, AUTO ON, PTW, B/D, NBC …) and a missing flag. Sheet-days with fewer than 10 populated parameters are treated as blank templates. Output: a long table (every cell, raw text preserved), a wide clean table, a data dictionary, and a sheet inventory.

## 4. Data preprocessing
Units are inferred from header groups and labelled "(inferred)". Status tokens are kept as categorical states, never coerced to numbers. Parameters are classified (bus voltage, feeder/transformer current, transformer MVA, oil/winding temperature, tap, PF, frequency, DC battery, coupler, capacitor bank) by header text — including bare headers such as "OIL", "HV", "T-1" used on some sheets.

## 5. Feature engineering
See [features.md](features.md). Every engineered feature has an electrical meaning and is computed from training-day references. Examples: bus-voltage deviation and 3-hour minimum, loading deviation/change/volatility, current deviation, circuits dropped to 0 A, bus-section mismatch (same kV level), parallel-circuit current mismatch, transformer loading as % of nameplate rating (parsed from headers), winding temperature rise rate and temperature-vs-load residual, equipment-state transitions.

## 6. Anomaly detection
Three unsupervised detectors per substation and fold: Isolation Forest (tree isolation depth), a dense autoencoder (reconstruction error of the scaled hourly vector) and a temporal-window autoencoder (reconstruction error of 4-hour windows of PCA-compressed vectors, within a day). Rule-based engineering signals (`ml/pipeline/rules.py`) add explicit checks: bus voltage collapse or > 5 % deviation, incomer/feeder drop-outs, rapid transformer loading increase, winding temperature above the load-expected level or rising fast, loading vs rating, operator-logged PTW/breakdown.

## 7. Temporal modelling
Hourly logs give at most 24 consecutive samples per day and the three days are not consecutive. A recurrent model (LSTM autoencoder) would memorise such short sequences, so it is registered as *not trained*. Temporal structure is captured by within-day rate/rolling features and the temporal-window autoencoder.

## 8. Risk scoring
Each detector's raw score is mapped to 0–100 by a piecewise-linear curve fitted on held-out calibration scores (median → 15, p90 → 45, p97.5 → 72, max → 88). Anomaly score = 0.45·IF + 0.30·AE + 0.25·TW-AE. Rule score R = 100 × combined rule severity. Operational risk = 0.7·max(anomaly, R) + 0.3·mean(anomaly, R). Confidence = 50·(agreement across detectors and rules) + 30·(fraction of model inputs actually logged this hour) + 20·(training-size factor). Categories: 0–30 NORMAL, 31–55 WATCH, 56–75 WARNING, 76–90 HIGH RISK, 91–100 CRITICAL — a **prototype AI risk classification**, not protection settings. Alerts at WARNING and above.

## 9. Evaluation methodology
No fault labels exist, so no accuracy, precision, recall or F1 is reported for HVPNL. The evaluation (`reports/evaluation.md`) reports: out-of-sample category distributions; rank agreement between out-of-sample and in-sample scores (how much a model depends on having seen the day); seed stability; agreement between detectors; manually reviewed real events; mean scores in operator-logged PTW/breakdown hours (a weak reference — those states are also model inputs). Public benchmark: chronological 70/30 split on ETTh1 for the load→temperature relationship and Isolation Forest drift.

## 10. Results (current run)
- Both reviewed Sector-46 events are HIGH RISK out-of-sample. The 0 kV event is caught by rules and models; the T-2 drop-out is caught by the rule engine while the ML detectors score the unseen day low — the hybrid design matters.
- Out-of-sample WARNING-or-above share: Sector-46, 66KV USA and Sector 64 ≈ 4 % of hours; A4 11 %; Escort I 0 %.
- An earlier run flagged most unseen hours at Escort I and Sector 64. Investigation showed this was **not** day-to-day drift but header/unit errors: currents under a merged "LOAD IN MVA" header (confirmed by √3·V·I matching the logged MVA to 0.1 %) and a load-like column headed as a 66 kV bus voltage. The fix was a physics-based plausibility layer (`ml/pipeline/plausibility.py`), not threshold tuning; the corrected classifications are listed in `reports/data_quality.md`.
- 220 A4 on 27 Feb: every transformer runs ~15 °C above the other days' load→temperature relation. With no ambient data this is reported as a WATCH-level sustained offset (R-T3); only excursions beyond the day's own offset escalate (R-T1).
- ETTh1: static load→temperature fit R² 0.34 train / negative test across seasons; Isolation Forest shows no material drift. Conclusion: the thermal residual must be fitted on recent, same-season data and used only as a contributing signal.

## 11. Limitations
Small, non-consecutive sample; manual hourly logs with inferred units; no labels; blank sheets; single-day Palla scored in-sample; weights and thresholds set by engineering judgement, not optimised; explanations are model attributions, not causal analysis.
