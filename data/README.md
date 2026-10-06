# Data layers

```
data/
  raw/          PRIVATE — HVPNL Faridabad workbooks (Dataset A). Read-only input. Git-ignored.
  processed/    derived from raw: scada_long.csv, scada_clean.csv, data_dictionary.csv, sheet_inventory.csv, scored_history.csv
  features/     feature store: features_<substation>.csv (out-of-sample rows + model key)
  external/     public benchmark downloads (ETT). Git-ignored; fetched by scripts/fetch_public_data.py
  validation/   reserved for labelled event records if they become available
  registry/     run-time registry outputs
  sources/      dataset_registry.yaml — every dataset, its role, licence and purpose (committed)
```

## Adding the real HVPNL files locally
1. Copy the three workbooks into `data/raw/` (or any folder and set `DATA_ROOT=/path/to/data` so that `$DATA_ROOT/raw/` contains them):
   - `02.02.2026 -TS Faridabad.xlsx`
   - `10.02.2026 -TS Faridabad.xlsx`
   - `27.02.2026 -TS Faridabad.xlsx`
   The log date is read from the file name (`DD.MM.YYYY`); more days can be added the same way.
2. Run `python scripts/build_pipeline.py`.
3. Start the API. If models are missing it will build them automatically from `raw/`.

Everything under `raw/`, `processed/`, `features/` and the trained models is derived from private operational records and must **not** be committed or published. `.gitignore` and `.dockerignore` exclude them.
