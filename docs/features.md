# Feature reference

All features are computed per substation by `ml/pipeline/features.py::engineer`, using reference statistics from **training days only**. Rolling and rate features are computed within a day. "Median" means the training-days median of that parameter.

| Feature | Definition | Unit | Electrical meaning |
|---|---|---|---|
| *logged measurements* | every parameter with ≥ 60 % coverage, non-constant | as logged | raw operating state |
| `voltage_deviation_pct` | mean over bus voltages of (V / median) − 1, × 100 | % | system voltage level vs normal |
| `voltage_rate_of_change` | hour-to-hour change of the voltage index | % pts | sudden voltage movement |
| `voltage_rolling_min_3h` | 3-h minimum of the voltage index − 1 | % | recent sag / dropout |
| `<bus> :: bus_section_mismatch_pct` | \|V_I − V_II\| / mean, same kV level | % | bus sections diverging (not phase imbalance — logs are not per phase) |
| `load_index_deviation_pct` | mean over loading channels of (x / median) − 1 | % | overall loading vs normal |
| `load_change_pct` | hour-to-hour change of the loading index | % pts | load step / transfer |
| `load_rolling_mean_3h`, `load_rolling_max_3h` | 3-h rolling mean / max of the loading index | % | sustained / peak loading |
| `load_rolling_std_3h` | 3-h rolling std of the loading index | % pts | loading volatility |
| `current_deviation_pct` | mean over feeder + incomer currents of (I / median) − 1 | % | current level vs normal |
| `circuits_dropped_to_zero` | count of currents that went > 0 → 0 A since previous hour | circuits | trips / switching / load transfers (state change, not a fault label) |
| `<ckt> :: parallel_circuit_mismatch_pct` | \|I_CKT-I − I_CKT-II\| / mean | % | unequal sharing on parallel circuits |
| `<MVA> :: loading_pct_of_rating` | MVA / nameplate rating × 100 (rating parsed from header, e.g. "160MVA", "25/31.5 MVA" → 31.5) | % | transformer stress |
| `<winding> :: temperature_change` | hour-to-hour winding temperature change | °C/h | temperature rise rate |
| `<winding> :: temperature_vs_load` | T_winding − (a·L₃ₕ + b), linear fit on training days, L₃ₕ = 3-h mean of the same transformer's load | °C | hotter than its own loading explains |
| `<oil> :: temperature_change` | hour-to-hour oil temperature change | °C/h | oil temperature rise rate |
| `circuits_out_of_service` | circuits logged OFF / PTW / Breakdown / NBC | circuits | equipment availability |
| `ptw_or_breakdown_circuits` | circuits logged PTW or Breakdown | circuits | planned / unplanned outages (operator notes) |
| `equipment_state_transitions` | logged states that changed since previous hour | changes | switching activity |
| `hour_sin`, `hour_cos` | sin/cos of hour of day | – | daily load cycle |

Deliberately **not** created: per-phase imbalance (logs are not per phase), power-factor-derived reactive power (PF logged for few transformers, voltage/current not co-located), "health" percentages presented as condition assessments, and any feature whose only purpose would be to increase the feature count. A daily *load factor* (mean/max) is reported in analytics only — as an hourly feature it would use future hours of the same day.
