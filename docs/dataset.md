# Dataset

## Source
HVPNL (Haryana Vidyut Prasaran Nigam Ltd.) "TS Faridabad" daily log sheets — three workbooks:

| File | Log date |
|---|---|
| `02.02.2026 -TS Faridabad.xlsx` | 2 Feb 2026 |
| `10.02.2026 -TS Faridabad.xlsx` | 10 Feb 2026 |
| `27.02.2026 -TS Faridabad.xlsx` | 27 Feb 2026 |

The files are stored unmodified in `data/raw/` and opened read-only.

## Sheet structure
Each workbook has the same 24 worksheets (one per substation). A typical sheet (e.g. `220 Sec-46`):

| Rows | Content |
|---|---|
| 1–3 | Organisation banner, registered office, sheet title ("Daily Log Sheet of 220 kV Sub-Station, Sector-46, Faridabad") |
| 4–6 | Three-level merged header: group (VOLTAGE, 220 kV FEEDERS LOAD, 66 kV FEEDERS LOAD, 11 kV FEEDERS LOAD, TAP POSITION, TRANSFORMER TEMPERATURE …) → equipment (e.g. `160 MVA T/F T- 3`) → leaf (`O`, `HV W`, `LV W`) |
| 7–30 | 24 hourly rows, 01:00 … 24:00 |
| 31+ | Footer blocks: shift checks (silica gel, oil level, DC leakage, trip circuits, hot spots), energy-meter readings — **excluded** from the time series |

Variants handled: time stored as Excel time, as text `HH:MM:SS`, as a timedelta (`24:00` = `1 day, 0:00`), or as integer hours 1–24 (66KV USA, 220 A4, 66 Escort I, 66 Ford); header blocks of 1–3 rows; a title banner merged across the header (66 Sector 64).

The "24:00" reading is stored as `<next day>T00:00:00` in timestamps and displayed as "24:00" of the log day.

## Sheet inventory (all 24 × 3)
See `data/processed/sheet_inventory.csv`.

- **Data present:** 220 Sec-46, 220 A4, 66 Sector 64, 66KV USA, 66 Escort I (all three days); 220 Palla (10 Feb only).
- **Blank templates in all three files** (time column only): 220 A5, 220 Pali, 220 Sector-58, 66 NH3, 66 FCI, 66 Northern India, 66 Idgah, 66 Escort 2, 66 SECTOR-31, 66 Ford, 66 Globe Steel, 66 Partap Steel, 66 Dabriwala, 66 A2, 66 Oswal Steel, 66 Hyderabad, 66 Dhauj, 66 Jharnsetly.

These 18 sheets contain no hourly readings in any of the three files (220 Sector-58 has a single isolated value; a spot check of several sheets found no formulas either). They are kept in the substation list with `has_model: false`.

## Primary case study: 220 kV Sector-46
73 parameters, 72 hourly records:

| Category | Count | Examples |
|---|---|---|
| Bus voltage (kV) | 6 | 220 kV Bus-I/II, 66 kV Bus-I/II, 11 kV T-I/T-2 |
| Feeder current (A) | 28 | 220 kV Pali/Palla circuits, 66 kV NH-3/Palla/DMRC circuits, 11 kV outgoing feeders |
| Transformer current (A) | 10 | 160 MVA T-3/T-4 HV & 66 kV incomers, 25/31.5 MVA T-1/T-2 incomers |
| Transformer load (MVA) | 4 | 220/66 kV 160 MVA T-3/T-4; 25/31.5 MVA T-1/T-2 |
| Winding temperature (°C) | 8 | T-3/T-4/T-1/T-2 HV W and LV W (T-1 HV W is always "-") |
| Oil temperature (°C) | 4 | T-3/T-4/T-1/T-2 `O` |
| Tap position | 4 | T-3, T-4, T-1, T-2 |
| Other | 9 | Frequency, PF T-1/T-2, DC battery voltage, bus couplers, cooling fan, weather |

## Values and tokens
Across all ingested cells (24,720): 1,208 cells are `-` or blank. Status tokens found inside measurement columns:

| Token | Meaning (as used in HVPNL logs) | Count |
|---|---|---|
| ON / AUTO ON | circuit energised, reading not written | 969 / 72 |
| OFF | circuit de-energised | 955 |
| PTW | permit-to-work (planned shutdown) | 34 |
| B/D, BD | breakdown | 16 |
| NBC | as logged (circuit not in service) | 72 |
| CLEAR, OK | weather / cooling-fan condition | 232 / 24 |

**No fault labels exist.** PTW/Breakdown are operator notes about individual circuits; they are used as equipment-state inputs and as a weak reference in evaluation, never as ground-truth fault labels.

## Units
Units are inferred from the header group (VOLTAGE → kV, FEEDERS LOAD → A, LOAD IN MVA → MVA, TEMPERATURE → °C, Frequency → Hz, Battery → V) and marked "(inferred)" in the data dictionary.

## Missing-value strategy
| Situation | Treatment |
|---|---|
| `-` / blank | missing (NaN) — never zero |
| status token in numeric column | value NaN, token kept in `<param> [state]` column |
| model input gap ≤ 2 h within a day | carry forward, then backward (held hourly reading) |
| remaining model-input gaps | substation median |
| parameter coverage < 60 % or constant | kept in clean data, excluded from model |
| status-only parameters | not imputed; aggregated into equipment-state counts |

## Processed outputs
| File | Content |
|---|---|
| `scada_long.csv` | one row per (file, substation, hour, parameter): raw text, numeric value, status, missing flag, Excel column |
| `scada_clean.csv` | wide ML dataset: substation, log_date, hour, timestamp, every parameter (NaN preserved), `[state]` columns |
| `features_<id>.csv` | model-ready engineered features per substation |
| `scored_history.csv` | anomaly score, risk score, category for every record |
| `data_dictionary.csv` | parameter, unit, substation, category, type, coverage, missing-value treatment, ML usage, Excel columns |
| `sheet_inventory.csv` | every sheet × date with detected hourly rows and filled-cell counts |
