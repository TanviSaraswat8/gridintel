"""Regression tests for unit-plausibility and rule fixes (header/value mismatches found in the HVPNL sheets)."""
import numpy as np
import pandas as pd

from pipeline import features as F
from pipeline import plausibility as PL
from pipeline import rules as R


def _meta(cols):
    return {c: F.classify(c) for c in cols}


def test_currents_under_mva_header_are_reclassified_by_sqrt3_vi():
    # T-1 logs 7.81 MVA; the "11KV LOAD" and "66KV LOAD" columns under the same merged MVA header are amps.
    cols = ["LOAD IN MVA | T/F T-1 LOAD IN MVA", "LOAD IN MVA | 11KV LOAD T-1 T/F", "LOAD IN MVA | 66KV LOAD T-1 T/F"]
    v = pd.DataFrame({cols[0]: [7.81] * 4, cols[1]: [410.0] * 4, cols[2]: [68.33] * 4})
    meta, findings = PL.validate(_meta(cols), {"S": v})
    assert meta[cols[0]]["category"] == "transformer_load_mva"
    assert meta[cols[1]] == {"category": "transformer_current", "unit": "A"}
    assert meta[cols[2]] == {"category": "transformer_current", "unit": "A"}
    assert all("√3" in f["evidence"] for f in findings)


def test_implausible_mva_without_sibling_becomes_unverified():
    col = "LOAD IN MVA | 25/31.5 MVA T/F T-2"
    meta, findings = PL.validate(_meta([col]), {"S": pd.DataFrame({col: [480.0, 500.0]})})
    assert meta[col]["category"] == "unverified" and findings[0]["to_category"] == "unverified"


def test_bus_voltage_must_match_nominal_kv():
    good, bad = "VOLTAGE | 66 kV Bus-I", "66 KV Bus I"
    v = pd.DataFrame({good: [67.0, 68.0], bad: [90.8, 121.7]})
    meta, _ = PL.validate(_meta([good, bad]), {"S": v})
    assert meta[good]["category"] == "bus_voltage"
    assert meta[bad]["category"] == "unverified"


def test_auxiliary_supplies_are_not_power_buses():
    ac, dc, batt = "A.C Voltage", "D. C. Voltage", "Battry Voltage/ Current"
    v = pd.DataFrame({ac: [240.0], dc: [230.0], batt: [240.0]})
    meta, _ = PL.validate(_meta([ac, dc, batt]), {"S": v})
    assert meta[ac]["category"] == "lt_voltage"
    assert meta[dc]["category"] == "dc_battery_voltage"
    assert meta[batt]["category"] == "dc_battery_voltage"


def test_no_values_are_changed_by_validation():
    col = "LOAD IN MVA | 11KV LOAD T-1 T/F"
    v = pd.DataFrame({"LOAD IN MVA | T/F T-1 LOAD IN MVA": [7.81], col: [410.0]})
    before = v.copy()
    PL.validate(_meta(list(v.columns)), {"S": v})
    pd.testing.assert_frame_equal(v, before)


def test_outgoing_feeder_under_transformer_group_is_a_feeder():
    assert F.classify("Load of 11KV Outgoing feeders of 25/31.5 MVA, 66/11KV T/F T-3 | 11 kv Bharat colony")["category"] == "feeder_current"
    assert F.classify("T/F T-1 | 11KV MAHAVIR COLONY")["category"] == "feeder_current"
    # incomers stay transformer currents (needed for the 10 Feb 08:00 Sector-46 event)
    assert F.classify("11 kV FEEDERS LOAD | 25/31.5 MVA T/F T- 1 I/C -I")["category"] == "transformer_current"


def _thermal_case(temps, loads):
    wt, lp = "TEMP | 100 MVA T/F T-1 | HV Winding", "66 KV Incomer 100 MVA T/F T-1"
    idx = [f"2026-02-27T{h:02d}:00:00" for h in range(1, len(temps) + 1)]
    values = pd.DataFrame({"log_date": "2026-02-27", "hour": range(1, len(temps) + 1), wt: temps, lp: loads}, index=idx)
    meta = {wt: {"category": "transformer_winding_temperature"}, lp: {"category": "transformer_current"}}
    ref = {"medians": {}, "thermal_fits": {wt: {"load_parameter": lp, "slope": 0.0, "intercept": 40.0, "resid_mad": 1.0}}}
    return values, meta, ref, idx


def test_day_long_thermal_offset_is_watch_level_not_warning():
    # every hour ~14 °C above the training-days relationship: reported once-per-hour as a sustained offset (R-T3)
    values, meta, ref, idx = _thermal_case([54, 54, 53, 54, 54, 55], [220] * 6)
    rules = R.evaluate(values, pd.DataFrame(), idx[5], meta, ref)
    assert [r["rule"] for r in rules] == ["R-T3"]
    assert rules[0]["severity"] < 0.5 and "ambient" in rules[0]["message"].lower()


def test_thermal_excursion_beyond_day_offset_is_flagged():
    values, meta, ref, idx = _thermal_case([44, 44, 44, 45, 44, 56], [220] * 6)
    rules = R.evaluate(values, pd.DataFrame(), idx[5], meta, ref)
    assert rules and rules[0]["rule"] == "R-T1" and rules[0]["severity"] >= 0.6


def test_early_day_thermal_flag_is_tempered():
    values, meta, ref, idx = _thermal_case([54], [220])
    rules = R.evaluate(values, pd.DataFrame(), idx[0], meta, ref)
    assert rules[0]["rule"] == "R-T1" and rules[0]["severity"] < 0.5


def test_unverified_parameters_never_trigger_voltage_rules():
    p = "66 KV Bus I"
    idx = ["2026-02-02T01:00:00", "2026-02-02T02:00:00"]
    values = pd.DataFrame({"log_date": "2026-02-02", "hour": [1, 2], p: [60.0, 138.0]}, index=idx)
    meta = {p: {"category": "unverified", "unit": "unknown"}}
    assert R.evaluate(values, pd.DataFrame(), idx[1], meta, {"medians": {p: 90.0}}) == []


def test_report_lists_every_finding():
    md = PL.report_markdown([{"substation": "S", "parameter": "x", "from_category": "a", "to_category": "b",
                              "unit": "A", "reason": "r", "evidence": "e"}])
    assert "| S | x | a | b (A) | r | e |" in md
    assert "No inconsistencies" in PL.report_markdown([])
    assert np.isclose(PL.nominal_kv("VOLTAGE | 11 kV T-I"), 11.0)
