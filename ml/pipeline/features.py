"""
Parameter classification, wide-table construction, missing-value handling and feature engineering.

Design rules
- Original parameter names are preserved exactly as built from the Excel header rows.
- Units are INFERRED from the header group (e.g. "VOLTAGE" -> kV, "FEEDERS LOAD" -> A) and flagged as inferred.
- Missing values are never blindly set to zero (see impute()).
- Every reference statistic used by a feature (medians, thermal fits, ratings) is computed from the
  TRAINING rows only and passed in as `ref`, so held-out days never leak into the features.
- Engineered features are limited to ones with an operational/electrical meaning (see docs/features.md).
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

MIN_COVERAGE = 0.60          # a parameter must be recorded in >=60% of a substation's hours to enter the model
MIN_PARAMS_FOR_DATA = 10     # a sheet-day with fewer populated parameters is treated as a blank template
GAP_FILL_LIMIT = 2           # max consecutive hours bridged by carry-forward/backward within one day

ENERGISED = {"ON", "AUTO_ON"}
DE_ENERGISED = {"OFF", "PTW", "BREAKDOWN", "NBC"}
EVENT_STATES = {"PTW", "BREAKDOWN"}


# --------------------------------------------------------------------------- classification
def classify(param: str) -> dict:
    p = param.lower()
    leaf = p.split("|")[-1].strip()
    bare = re.sub(r"\s*\[col \w+\]$", "", leaf)          # e.g. "oil [col AS]" -> "oil"
    if bare in {"oil", "o", "oti"}:
        return {"category": "transformer_oil_temperature", "unit": "°C"}
    if bare in {"hv", "lv", "hv w", "lv w", "wti", "w1", "w2"}:
        return {"category": "transformer_winding_temperature", "unit": "°C"}
    if re.fullmatch(r"t\s*-?\s*(\d|i{1,3}|iv|v|vi)", bare):     # bare transformer column under a LOAD group
        return {"category": "transformer_current", "unit": "A"}
    if "temperature" in p or leaf in {"o", "hv w", "lv w", "oti", "wti", "hv", "lv"} or "wti" in p or "oti" in p:
        if "room" in p:
            return {"category": "ambient_temperature", "unit": "°C"}
        sub = "oil" if leaf in {"o", "oti"} or "oil" in leaf else ("winding" if "w" in leaf or "wti" in p else "temperature")
        return {"category": f"transformer_{sub}_temperature", "unit": "°C"}
    if "battery" in p:
        return {"category": "dc_battery_voltage", "unit": "V"}
    if "l. t. voltage" in p or "lt voltage" in p:
        return {"category": "lt_voltage", "unit": "V"}
    if "frequency" in p:
        return {"category": "frequency", "unit": "Hz"}
    if "power factor" in p:
        return {"category": "power_factor", "unit": "pf"}
    if "tap" in p:
        return {"category": "tap_position", "unit": "step"}
    if "weather" in p:
        return {"category": "weather", "unit": "-"}
    if "cooling fan" in p or "fan" == leaf:
        return {"category": "cooling_fan", "unit": "-"}
    if "remark" in p:
        return {"category": "remarks", "unit": "-"}
    if "cap. bank" in p or "cap bank" in p or "capacitor" in p:
        return {"category": "capacitor_bank", "unit": "A"}
    if "mva" in p and "load" in p and ("load in mva" in p or "load in  mva" in p or p.startswith("load in mva")):
        return {"category": "transformer_load_mva", "unit": "MVA"}
    if "voltage" in p or (("bus" in leaf) and "coupler" not in leaf and "load" not in p):
        return {"category": "bus_voltage", "unit": "kV"}
    if "coupler" in p:
        return {"category": "bus_coupler_load", "unit": "A"}
    if "load" in p or "ckt" in p or "feeder" in p or "line" in p or "i/c" in p or "incomer" in p:
        # the column's own label decides first: an outgoing feeder listed under a "... T/F T-3" group is still a feeder
        if re.search(r"t\s*/\s*f|transformer|incomer|i/c", leaf):
            return {"category": "transformer_current", "unit": "A"}
        if "outgoing" in p or "feeders of" in p:
            return {"category": "feeder_current", "unit": "A"}
        if re.search(r"t\s*/\s*f|transformer|incomer|i/c", p):
            return {"category": "transformer_current", "unit": "A"}
        return {"category": "feeder_current", "unit": "A"}
    return {"category": "feeder_current", "unit": "A"}  # 11 kV outgoing feeder columns named by locality


_ROMAN = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6"}


def transformer_id(param: str) -> str | None:
    """Extract a transformer tag like 'T-3' from a parameter name."""
    m = re.search(r"\bT\s*[-/]?\s*(IV|VI|V|III|II|I|\d)\b", param.replace("T/F", " "), flags=re.I)
    if not m:
        return None
    tok = m.group(1).upper()
    return "T-" + _ROMAN.get(tok, tok)


def mva_rating(param: str) -> float | None:
    """Nameplate rating from names like '160MVA', '25/31.5 MVA', '12.5/16 MVA' (top rating of ONAN/ONAF pair)."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:/\s*(\d+(?:\.\d+)?))?\s*MVA", param, flags=re.I)
    if not m:
        return None
    vals = [float(x) for x in m.groups() if x]
    return max(vals) if vals else None


def bus_pairs(volts: list[str]) -> list[tuple[str, str]]:
    """Pairs of bus-section voltages at the same kV level (e.g. 220 kV Bus-I / Bus-II)."""
    groups: dict[str, list[str]] = {}
    for p in volts:
        low = p.lower()
        if "bus" not in low:
            continue
        kv = re.search(r"(\d+)\s*kv", low)
        if kv:
            groups.setdefault(kv.group(1), []).append(p)
    return [(g[0], g[1]) for g in groups.values() if len(g) == 2]


def parallel_circuits(feeders: list[str]) -> list[tuple[str, str]]:
    """Pairs of parallel circuits on the same route (… CKT-I / … CKT-II)."""
    groups: dict[str, list[str]] = {}
    for p in feeders:
        low = p.lower()
        if not re.search(r"ckt", low):
            continue
        key = re.sub(r"ckt\s*-?\s*(iii|ii|i|\d)\b", "ckt", low)
        key = re.sub(r"\s+", " ", key).strip()
        groups.setdefault(key, []).append(p)
    return [(g[0], g[1]) for g in groups.values() if len(g) == 2]


# --------------------------------------------------------------------------- wide tables
def build_wide(long: pd.DataFrame):
    """Return (values_wide, states_wide, kept_long). Template/blank sheet-days are dropped."""
    pop = long[~long["is_missing"]].groupby(["substation", "log_date"])["parameter"].nunique()
    good = pop[pop >= MIN_PARAMS_FOR_DATA].index
    kept = long.set_index(["substation", "log_date"]).loc[lambda d: d.index.isin(good)].reset_index()
    idx = ["substation", "log_date", "hour", "timestamp"]
    values = kept.pivot_table(index=idx, columns="parameter", values="value", aggfunc="first")
    states = kept.dropna(subset=["status"]).pivot_table(index=idx, columns="parameter", values="status", aggfunc="first")
    return values, states, kept


def usable_parameters(values: pd.DataFrame) -> list[str]:
    cov = values.notna().mean()
    return [p for p in values.columns if cov[p] >= MIN_COVERAGE and values[p].std(skipna=True) > 0]


def impute(values: pd.DataFrame, medians: pd.Series | None = None) -> pd.DataFrame:
    """Causal imputation. Within each day carry the last reading forward for up to GAP_FILL_LIMIT hours (an hourly
    log reading is a held value; no backward fill, so no future information is used); anything still missing ->
    training-set median (passed in) for that parameter."""
    out = values.groupby(level="log_date", group_keys=False).apply(lambda g: g.ffill(limit=GAP_FILL_LIMIT))
    med = medians if medians is not None else out.median()
    return out.fillna(med)


# --------------------------------------------------------------------------- reference statistics
def fit_reference(values: pd.DataFrame, meta: dict) -> dict:
    """Statistics learned from TRAINING rows only (imputed values)."""
    cats = {p: meta[p]["category"] for p in values.columns}
    ref = {"medians": values.median().to_dict(), "thermal_fits": {}, "ratings": {}}
    tloads = [p for p, c in cats.items() if c in {"transformer_load_mva", "transformer_current"}]
    for wt in [p for p, c in cats.items() if c == "transformer_winding_temperature"]:
        lp = _matching_load(wt, tloads, cats)
        if lp is not None and values[lp].std() > 0 and values[wt].std() > 0:
            load_smooth = _daily(values[lp]).transform(lambda s: s.rolling(3, min_periods=1).mean())
            b = np.polyfit(load_smooth, values[wt], 1)
            resid = values[wt] - np.polyval(b, load_smooth)
            ref["thermal_fits"][wt] = {"load_parameter": lp, "slope": float(b[0]), "intercept": float(b[1]),
                                       "resid_mad": float((resid - resid.median()).abs().median() * 1.4826) or 1.0}
    # nameplate ratings by transformer tag, from any parameter name carrying "xx MVA"
    by_tag: dict[str, float] = {}
    for p in values.columns:
        r, t = mva_rating(p), transformer_id(p)
        if r and t:
            by_tag.setdefault(t, r)
    for p, c in cats.items():
        if c == "transformer_load_mva":
            r = mva_rating(p) or by_tag.get(transformer_id(p) or "")
            if r:
                ref["ratings"][p] = r
    return ref


def _daily(s: pd.Series):
    return s.groupby(s.index.get_level_values("log_date"))


def _matching_load(wt: str, tloads: list[str], cats: dict) -> str | None:
    tid = transformer_id(wt)
    match = [p for p in tloads if transformer_id(p) == tid] if tid else []
    mva = [p for p in match if cats[p] == "transformer_load_mva"]
    return (mva or match or [None])[0]


# --------------------------------------------------------------------------- engineered features
def engineer(values: pd.DataFrame, states: pd.DataFrame | None, meta: dict, ref: dict) -> tuple[pd.DataFrame, dict]:
    """values: imputed wide table for ONE substation (rows=hours, cols=usable params).
    Returns (features, feature_meta). All rolling / rate features are computed within a day (days are not consecutive)."""
    cols: dict[str, pd.Series] = {}
    fmeta: dict[str, dict] = {}

    def add(name, series, base, kind, desc, unit=""):
        cols[name] = pd.Series(series, index=values.index).astype(float)
        fmeta[name] = {"base_parameter": base, "kind": kind, "description": desc, "unit": unit}

    for p in values.columns:
        add(p, values[p], p, "measurement", f"Logged value of '{p}'", meta[p]["unit"])

    by_day = lambda s: s.groupby(s.index.get_level_values("log_date"))  # noqa: E731
    roll = lambda s, fn: by_day(s).transform(lambda x: getattr(x.rolling(3, min_periods=1), fn)())  # noqa: E731
    cats = {p: meta[p]["category"] for p in values.columns}
    med = pd.Series(ref["medians"]).reindex(values.columns).replace(0, np.nan)
    volts = [p for p, c in cats.items() if c == "bus_voltage"]
    feeders = [p for p, c in cats.items() if c == "feeder_current"]
    loads = [p for p, c in cats.items() if c in {"transformer_load_mva", "transformer_current", "feeder_current"}]
    currents = [p for p, c in cats.items() if c in {"transformer_current", "feeder_current"}]
    wtemps = [p for p, c in cats.items() if c == "transformer_winding_temperature"]
    otemps = [p for p, c in cats.items() if c == "transformer_oil_temperature"]

    def pu(cols):
        return (values[cols] / med[cols]).mean(axis=1)

    # -- voltage
    if volts:
        vidx = pu(volts)
        add("voltage_deviation_pct", (vidx - 1) * 100, "Bus voltages", "deviation",
            "Mean bus-voltage deviation from the learned median level", "%")
        add("voltage_rate_of_change", by_day(vidx).diff().fillna(0) * 100, "Bus voltages", "rate_of_change",
            "Hour-to-hour change of the bus-voltage index", "% pts")
        add("voltage_rolling_min_3h", (roll(vidx, "min") - 1) * 100, "Bus voltages", "rolling_min",
            "Lowest bus-voltage index over the last 3 h, relative to median", "%")
        for a, b in bus_pairs(volts):
            m = (values[a] + values[b]) / 2
            add(f"{a} :: bus_section_mismatch_pct", ((values[a] - values[b]).abs() / m.replace(0, np.nan) * 100).fillna(0),
                a, "imbalance", f"Voltage mismatch between bus sections '{a}' and '{b}' (same kV level)", "%")
    # -- loading
    if loads:
        lidx = pu(loads)
        add("load_index_deviation_pct", (lidx - 1) * 100, "Feeder / transformer loading", "deviation",
            "Mean loading deviation from the learned median level", "%")
        add("load_change_pct", by_day(lidx).diff().fillna(0) * 100, "Feeder / transformer loading", "rate_of_change",
            "Hour-to-hour change of the loading index", "% pts")
        add("load_rolling_mean_3h", (roll(lidx, "mean") - 1) * 100, "Feeder / transformer loading", "rolling_mean",
            "3-hour rolling mean of the loading index, relative to median", "%")
        add("load_rolling_max_3h", (roll(lidx, "max") - 1) * 100, "Feeder / transformer loading", "rolling_max",
            "3-hour rolling max of the loading index, relative to median", "%")
        add("load_rolling_std_3h", roll(lidx, "std").fillna(0) * 100, "Feeder / transformer loading", "rolling_std",
            "3-hour rolling std of the loading index (volatility)", "% pts")
    if currents:
        cidx = pu(currents)
        add("current_deviation_pct", (cidx - 1) * 100, "Feeder / incomer currents", "deviation",
            "Mean current deviation (feeders + incomers) from learned median", "%")
        prev = by_day(values[currents]).shift(1)
        dropped = ((prev > 0) & (values[currents] == 0)).sum(axis=1)
        add("circuits_dropped_to_zero", dropped, "Feeder / incomer currents", "state_change",
            "Number of feeders/incomers whose current went from >0 to 0 A since the previous hour", "circuits")
    for a, b in parallel_circuits(feeders):
        m = (values[a] + values[b]) / 2
        add(f"{a} :: parallel_circuit_mismatch_pct", ((values[a] - values[b]).abs() / m.replace(0, np.nan) * 100).fillna(0),
            a, "imbalance", f"Current mismatch between parallel circuits '{a}' and '{b}'", "%")
    # -- transformer stress
    for p, rating in ref["ratings"].items():
        if p in values.columns:
            add(f"{p} :: loading_pct_of_rating", values[p] / rating * 100, p, "stress",
                f"Loading of '{p}' as % of {rating:g} MVA nameplate rating (rating parsed from sheet header)", "%")
    for wt in wtemps:
        add(f"{wt} :: temperature_change", by_day(values[wt]).diff().fillna(0), wt, "rate_of_change",
            "Winding temperature rise rate", "°C/h")
        fit = ref["thermal_fits"].get(wt)
        if fit and fit["load_parameter"] in values.columns:
            lp = fit["load_parameter"]
            load_smooth = by_day(values[lp]).transform(lambda s: s.rolling(3, min_periods=1).mean())
            expected = fit["slope"] * load_smooth + fit["intercept"]
            add(f"{wt} :: temperature_vs_load", values[wt] - expected, wt, "thermal_residual",
                f"Winding temperature minus the temperature expected for the current loading of '{lp}' "
                f"(linear fit on training days)", "°C")
            fmeta[f"{wt} :: temperature_vs_load"].update({"load_parameter": lp, "fit": [fit["slope"], fit["intercept"]]})
    for ot in otemps:
        add(f"{ot} :: temperature_change", by_day(values[ot]).diff().fillna(0), ot, "rate_of_change",
            "Oil temperature rise rate", "°C/h")
    # -- equipment state
    if states is not None and not states.empty:
        st = states.reindex(values.index)
        add("circuits_out_of_service", st.isin(DE_ENERGISED).sum(axis=1), "Equipment status", "equipment_state",
            "Circuits logged OFF / PTW / Breakdown / NBC in this hour", "circuits")
        add("ptw_or_breakdown_circuits", st.isin(EVENT_STATES).sum(axis=1), "Equipment status", "equipment_state",
            "Circuits logged under PTW or Breakdown in this hour", "circuits")
        prev = st.groupby(st.index.get_level_values("log_date")).shift(1)
        trans = ((st != prev) & st.notna() & prev.notna()).sum(axis=1)
        add("equipment_state_transitions", trans, "Equipment status", "state_change",
            "Number of logged equipment states that changed since the previous hour", "changes")
    # -- time of day
    hour = values.index.get_level_values("hour").astype(float)
    add("hour_sin", np.sin(2 * np.pi * hour / 24), "Time of day", "time", "Hour of day (sin)")
    add("hour_cos", np.cos(2 * np.pi * hour / 24), "Time of day", "time", "Hour of day (cos)")
    return pd.DataFrame(cols, index=values.index), fmeta
