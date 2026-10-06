"""Data pipeline + ML unit tests (ingestion, features, rules, ensemble, pipeline outputs, leakage)."""
import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from pipeline import features as F
from pipeline import rules as R
from pipeline.ensemble import CATEGORIES, calibrate, category, combine
from pipeline.ingest import _hour_of, ingest_all, inventory, parse_cell


# ------------------------------------------------------------------ ingestion
def test_parse_cell_tokens_and_missing():
    assert parse_cell(234)[1] == 234.0
    assert parse_cell("11.5")[1] == 11.5
    assert parse_cell("54 C")[1] == 54.0
    raw, val, st, miss = parse_cell("-")
    assert val is None and miss is True                      # "-" is missing, never zero
    assert parse_cell("ON")[2] == "ON" and parse_cell("B/D")[2] == "BREAKDOWN" and parse_cell("PTW")[2] == "PTW"
    assert parse_cell("remarks text")[1] is None and parse_cell("")[3] is True


@pytest.mark.parametrize("v,h", [(dt.time(1, 0), 1), (dt.time(0, 0), 24), (dt.timedelta(days=1), 24), ("13:00:00", 13),
                                 (7, 7), ("Time", None), (None, None), (0.5, 12), (99, None)])
def test_hour_parsing(v, h):
    assert _hour_of(v) == h


def test_ingest_fixture(built):
    df = ingest_all(built / "data" / "raw")
    inv = inventory()
    assert set(df.substation) == {"220 Test-A"}                          # blank sheet yields no rows
    assert (inv[inv.substation == "66 Blank"].note == "blank template (no readings)").all()
    a = df[df.substation == "220 Test-A"]
    assert a.hour.nunique() == 24 and a.log_date.nunique() == 3          # footer rows excluded
    assert "VOLTAGE | 220 kV Bus-I" in set(a.parameter)                  # merged group header expanded
    assert "TRANSFORMER TEMPERATURE | 160 MVA T/F T- 1 | HV W" in set(a.parameter)
    assert a.is_missing.sum() >= 3 and (a.status == "PTW").sum() == 1


# ------------------------------------------------------------------ features
def test_classification_and_tags():
    assert F.classify("VOLTAGE | 220 kV Bus-I")["category"] == "bus_voltage"
    assert F.classify("TRANSFORMER TEMPERATURE | 160 MVA T/F T- 3 | HV W")["category"] == "transformer_winding_temperature"
    assert F.classify("OIL [col AS]")["category"] == "transformer_oil_temperature"
    assert F.classify("66 KV LOAD | T-1")["category"] == "transformer_current"
    assert F.classify("220 kV FEEDERS LOAD | LOAD IN MVA | 220/66KV 160MVA T/F T-3")["category"] == "transformer_load_mva"
    assert F.transformer_id("25/31.5 MVA T - I") == "T-1" and F.transformer_id("no tag") is None
    assert F.mva_rating("25/31.5 MVA T/F") == 31.5 and F.mva_rating("feeder") is None
    assert F.bus_pairs(["VOLTAGE | 220 kV Bus-I", "VOLTAGE | 220 kV Bus-II", "VOLTAGE | 11 kV T-I"]) == [("VOLTAGE | 220 kV Bus-I", "VOLTAGE | 220 kV Bus-II")]
    assert len(F.parallel_circuits(["X | 220KV A CKT - I", "X | 220KV A CKT - II", "X | Other"])) == 1


def test_imputation_is_causal():
    idx = pd.MultiIndex.from_tuples([("s", "d", h, f"t{h}") for h in range(1, 6)], names=["substation", "log_date", "hour", "timestamp"])
    v = pd.DataFrame({"p": [np.nan, 1.0, np.nan, np.nan, np.nan]}, index=idx)
    out = F.impute(v, medians=pd.Series({"p": 9.0}))
    assert out.p.tolist() == [9.0, 1.0, 1.0, 1.0, 9.0]   # no backward fill; forward fill limited to 2 h


# ------------------------------------------------------------------ rules
def test_rules_fire_on_planted_events(built):
    from pipeline.build import prepare_fold  # noqa
    sc = pd.read_csv(built / "data" / "processed" / "scored_history.csv")
    r1 = sc[(sc.timestamp == "2026-02-02T10:00:00")].iloc[0]
    assert "R-V1" in [x["rule"] for x in json.loads(r1.rules)]
    r2 = sc[(sc.timestamp == "2026-02-10T08:00:00")].iloc[0]
    assert "R-L1" in [x["rule"] for x in json.loads(r2.rules)]
    assert r1.risk_category in ("WARNING", "HIGH RISK", "CRITICAL") and r2.risk_category in ("WARNING", "HIGH RISK", "CRITICAL")


def test_rule_severity_combination():
    assert R.severity([]) == 0
    assert R.severity([{"rule": "A", "severity": .6}, {"rule": "B", "severity": .5}]) == pytest.approx(.65)


# ------------------------------------------------------------------ ensemble maths
def test_categories_and_calibration():
    assert [category(x) for x in (0, 30, 31, 55, 56, 75, 76, 90, 91)] == ["NORMAL", "NORMAL", "WATCH", "WATCH", "WARNING", "WARNING", "HIGH RISK", "HIGH RISK", "CRITICAL"]
    assert CATEGORIES[-1][1] == "CRITICAL"
    pts = [0.1, 0.2, 0.3, 0.4, 0.5, 0.7]
    y = calibrate(np.linspace(0, 1, 50), pts)
    assert (np.diff(y) >= 0).all() and y.min() == 0 and y.max() == 100


def test_confidence_drops_when_sources_disagree():
    agree = combine(80, 0.8, {"iforest": 80, "autoencoder": 82, "temporal_ae": 78}, 1.0, 48)
    disagree = combine(20, 0.8, {"iforest": 5, "autoencoder": 60, "temporal_ae": 10}, 1.0, 48)
    assert agree["confidence"] > disagree["confidence"]
    assert disagree["risk_score"] >= 0.7 * 80                       # a strong rule still raises risk


# ------------------------------------------------------------------ pipeline outputs & leakage
def test_pipeline_outputs_and_registry(built):
    proc, models = built / "data" / "processed", built / "models"
    for f in ("scada_long.csv", "scada_clean.csv", "data_dictionary.csv", "sheet_inventory.csv", "scored_history.csv", "parameter_meta.json"):
        assert (proc / f).exists(), f
    reg = json.loads((models / "registry.json").read_text())
    assert reg["models"]["supervised"]["status"] == "not trained"         # no labels → no supervised model
    assert reg["models"]["lstm_autoencoder"]["status"] == "not trained"
    arts = [a for a in reg["ensemble"]["artifacts"] if a["holdout_day"]]
    assert len(arts) == 3
    for a in arts:
        assert a["holdout_day"] not in a["trained_days"]                  # leave-one-day-out: no leakage
        assert len(a["sha256"]) == 64
    sc = pd.read_csv(proc / "scored_history.csv")
    assert sc.risk_score.between(0, 100).all() and sc.confidence.between(0, 100).all()
    assert (sc.evaluation == "out-of-sample (LODO)").all()
    dd = pd.read_csv(proc / "data_dictionary.csv")
    assert {"parameter", "unit", "substation", "type", "missing_value_treatment", "ml_usage"} <= set(dd.columns)
    assert list((built / "experiments").glob("*.json"))


def test_evaluation_has_no_accuracy_claims(built):
    ev = json.loads((built / "reports" / "evaluation.json").read_text())
    text = json.dumps(ev).lower()
    assert "precision" not in text.replace("accuracy/precision/recall/f1 are not reported", "")
    assert ev["summary"]["substations_scored"] == 1
