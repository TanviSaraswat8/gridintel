"""
In-memory read model + live ensemble inference.

Loads the artifacts produced by the training pipeline (scripts/build_pipeline.py): clean dataset, served
(out-of-sample) feature rows, ensemble bundles per substation/fold, model registry. All values shown in the UI
come from the supplied HVPNL records — nothing is synthesised. Sheets without readings are reported as
"NO SOURCE READINGS".
"""
from __future__ import annotations

import json
import math
import re
import time
from functools import lru_cache

import joblib
import numpy as np
import pandas as pd

from pipeline import rules as R
from pipeline.ensemble import ALERT_CATEGORIES, CATEGORIES, WEIGHTS, combine

from ..core.config import get_settings
from ..core.observability import INFERENCE_LATENCY

STATE_SUFFIX = " [state]"
LEVEL_RE = re.compile(r"(\d+)\s*kv", re.I)


def f(x, nd=2):
    try:
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else round(v, nd)
    except (TypeError, ValueError):
        return None


def short_name(param: str | None) -> str:
    if not param:
        return ""
    parts = [p.strip() for p in param.split("|")]
    leaf = parts[-1]
    if len(parts) >= 2 and leaf in {"O", "HV W", "LV W"}:
        return f"{parts[-2]} " + {"O": "Oil", "HV W": "HV Winding", "LV W": "LV Winding"}[leaf]
    return leaf if len(leaf) >= 2 else " ".join(parts[-2:])


class Store:
    def __init__(self) -> None:
        s = get_settings()
        self.s = s
        proc, models = s.processed_dir, s.model_path
        self.substations: list[dict] = json.loads((models / "substations.json").read_text())
        self.by_id = {x["id"]: x for x in self.substations}
        self.by_sheet = {x["sheet"]: x for x in self.substations}
        self.registry = json.loads((models / "registry.json").read_text())
        self.param_meta: dict = json.loads((proc / "parameter_meta.json").read_text(encoding="utf-8"))
        self.dictionary = pd.read_csv(proc / "data_dictionary.csv")
        self.scored = pd.read_csv(proc / "scored_history.csv")
        self.scored["rules"] = self.scored["rules"].map(json.loads)
        ev = s.reports_dir / "evaluation.json"
        self.evaluation = json.loads(ev.read_text()) if ev.exists() else {}
        bench = s.reports_dir / "benchmarks.json"
        self.benchmarks = json.loads(bench.read_text()) if bench.exists() else {}
        clean = pd.read_csv(proc / "scada_clean.csv", low_memory=False)
        self.values, self.states, self.features, self.bundles, self.scores = {}, {}, {}, {}, {}
        for sub in self.substations:
            if not sub["has_model"]:
                continue
            sid = sub["id"]
            g = clean[clean.substation == sub["sheet"]].dropna(axis=1, how="all").set_index("timestamp").sort_index()
            scols = [c for c in g.columns if c.endswith(STATE_SUFFIX)]
            vcols = [c for c in g.columns if c not in scols and c not in ("substation", "log_date", "hour")]
            self.values[sid] = g[["log_date", "hour"] + vcols]
            self.states[sid] = g[scols].rename(columns=lambda c: c[: -len(STATE_SUFFIX)])
            fe = pd.read_csv(s.features_dir / f"features_{sid}.csv").sort_values("timestamp")
            self.features[sid] = fe.set_index(["substation", "log_date", "hour", "timestamp"])
            self.bundles[sid] = {p.stem: joblib.load(p) for p in (models / "ensemble" / sid).glob("*.joblib")}
            self.scores[sid] = self.scored[self.scored.substation == sub["sheet"]].set_index("timestamp").sort_index()
            sub["key_signals"] = self._key_signal_defs(sid)
            sub["topology"] = self._equipment(sid)
        self.timeline: list[str] = sorted({t for v in self.values.values() for t in v.index})
        self.latency_ms: list[float] = []

    # ------------------------------------------------------------------ lookup
    def meta(self, p: str) -> dict:
        return self.param_meta.get(p, {"category": "other", "unit": "", "transformer": None})

    def unit(self, p: str | None) -> str:
        return self.meta(p).get("unit", "") if p else ""

    def sub(self, sid: str) -> dict:
        if sid in self.by_id:
            return self.by_id[sid]
        if sid in self.by_sheet:
            return self.by_sheet[sid]
        raise KeyError(sid)

    def brief(self, s: dict) -> dict:
        return {k: s.get(k) for k in ("id", "sheet", "name", "voltage_class_kv", "days", "records", "parameters_logged",
                                      "model_features", "low_confidence", "validation", "has_model", "data_status", "note")}

    def params(self, sid, *cats):
        return [c for c in self.values[sid].columns[2:] if self.meta(c)["category"] in cats]

    def val(self, sid, ts, p):
        v = self.values[sid]
        return f(v.at[ts, p]) if (p and ts in v.index and p in v.columns) else None

    def latest_ts(self, sid: str, cursor_ts: str | None) -> str | None:
        idx = self.values[sid].index
        if cursor_ts is None:
            return idx[0]
        prior = idx[idx <= cursor_ts]
        return prior[-1] if len(prior) else None

    # ------------------------------------------------------------------ inference
    def bundle_for(self, sid: str, ts: str):
        key = self.features[sid].xs(ts, level="timestamp")["model_key"].iloc[0]
        return self.bundles[sid][key]

    @lru_cache(maxsize=8192)
    def infer(self, sid: str, ts: str) -> dict:
        """Live ensemble inference for one record (uses the model that did NOT see this record's day)."""
        t0 = time.perf_counter()
        b = self.bundle_for(sid, ts)
        fe = self.features[sid]
        day = fe.xs(ts, level="timestamp").index.get_level_values("log_date")[0]
        day_rows = fe[(fe.index.get_level_values("log_date") == day) & (fe.index.get_level_values("timestamp") <= ts)]
        comp = b.score(day_rows.drop(columns="model_key")).iloc[-1]
        rules = R.evaluate(self.values[sid], self.states[sid], ts, b.meta, b.ref)
        usable = b.extra.get("usable", [])
        cov = float(self.values[sid].loc[ts, [u for u in usable if u in self.values[sid].columns]].notna().mean()) if usable else 0.0
        res = combine(float(comp["anomaly_score"]), R.severity(rules), {k: comp[k] for k in WEIGHTS}, cov, b.n_train)
        dt_ = time.perf_counter() - t0
        INFERENCE_LATENCY.observe(dt_)
        self.latency_ms = (self.latency_ms + [dt_ * 1000])[-500:]
        return {"anomaly_score": round(float(comp["anomaly_score"]), 1),
                "components": {k: round(float(comp[k]), 1) for k in WEIGHTS}, **res,
                "rules": rules, "model_key": b.extra.get("key"), "model_version": b.version,
                "evaluation": "out-of-sample" if b.holdout_day else "in-sample", "data_coverage": round(cov, 3)}

    @lru_cache(maxsize=4096)
    def _explain(self, sid: str, ts: str) -> str:
        b = self.bundle_for(sid, ts)
        row = self.features[sid].xs(ts, level="timestamp").iloc[0]
        sig = b.iforest.explain(row.reindex(b.iforest.features).fillna(0), top_k=8)
        for e in sig:
            e["label"] = self.feature_label(e["feature"])
            e["unit"] = b.iforest.feature_meta.get(e["feature"], {}).get("unit") or self.unit(e["base_parameter"])
        return json.dumps(sig, default=float)

    def explain(self, sid: str, ts: str) -> list[dict]:
        return json.loads(self._explain(sid, ts))

    def primary_signal(self, sid: str, sigs: list[dict], rules: list[dict] | None = None) -> dict:
        cols = set(self.values[sid].columns)
        if rules:  # an engineering rule that fired points at concrete parameters — prefer it
            for p in rules[0]["parameters"]:
                for x in sigs:
                    if x["base_parameter"] == p:
                        return x
        real = [x for x in sigs if x["base_parameter"] in cols and x["kind"] != "time"]
        return (real or [x for x in sigs if x["kind"] != "time"] or sigs or [{}])[0]

    def feature_label(self, feat: str) -> str:
        labels = {"voltage_deviation_pct": "Bus voltage deviation", "voltage_rate_of_change": "Bus voltage rate of change",
                  "voltage_rolling_min_3h": "Bus voltage 3 h minimum", "load_index_deviation_pct": "Loading deviation",
                  "load_change_pct": "Loading change vs previous hour", "load_rolling_std_3h": "Loading volatility (3 h)",
                  "load_rolling_mean_3h": "Loading 3 h mean", "load_rolling_max_3h": "Loading 3 h max",
                  "current_deviation_pct": "Current deviation", "circuits_dropped_to_zero": "Circuits dropped to 0 A",
                  "circuits_out_of_service": "Circuits logged OFF/PTW/Breakdown", "ptw_or_breakdown_circuits": "Circuits under PTW / Breakdown",
                  "equipment_state_transitions": "Equipment state transitions", "hour_sin": "Time-of-day pattern",
                  "hour_cos": "Time-of-day pattern"}
        if feat in labels:
            return labels[feat]
        if " :: " in feat:
            base, kind = feat.split(" :: ")
            return f"{short_name(base)} — " + {"temperature_change": "temperature rise rate",
                                                "temperature_vs_load": "temperature vs load residual",
                                                "loading_pct_of_rating": "loading % of rating",
                                                "bus_section_mismatch_pct": "bus-section voltage mismatch",
                                                "parallel_circuit_mismatch_pct": "parallel-circuit current mismatch"}.get(kind, kind)
        return short_name(feat)

    # ------------------------------------------------------------------ snapshots
    def _key_signal_defs(self, sid: str) -> dict:
        v = self.values[sid]
        med = v.iloc[:, 2:].median(numeric_only=True)
        cov = v.iloc[:, 2:].notna().mean()
        good = lambda cols: [c for c in cols if cov.get(c, 0) >= 0.6]  # noqa: E731
        best = lambda cols: max(good(cols), key=lambda c: med.get(c, 0) or 0) if good(cols) else None  # noqa: E731
        kv = self.sub(sid)["voltage_class_kv"]
        tcur = self.params(sid, "transformer_current")
        volts = sorted(good(self.params(sid, "bus_voltage")), key=lambda c: -(med.get(c, 0) or 0))
        feeders = good(self.params(sid, "feeder_current"))
        f11 = [c for c in feeders if re.search(r"11\s*kv", c, re.I)]
        return {"voltage": volts[0] if volts else None,
                "transformer_load": best(self.params(sid, "transformer_load_mva")) or best(tcur),
                "current": best([c for c in tcur if c.lower().replace(" ", "").startswith(f"{kv}kv")]) or best(tcur) or best(feeders),
                "transformer_temperature": good(self.params(sid, "transformer_winding_temperature")),
                "oil_temperature": good(self.params(sid, "transformer_oil_temperature")),
                "feeder_load": f11 if len(f11) >= 3 else feeders, "voltages": volts,
                "transformer_loads": good(self.params(sid, "transformer_load_mva")) or good(tcur)}

    def cards(self, sid: str, ts: str) -> dict:
        k = self.sub(sid)["key_signals"]
        st = self.states[sid].loc[ts] if ts in self.states[sid].index else pd.Series(dtype=object)
        st = st[[c for c in st.index if self.meta(c)["category"] != "weather"]].dropna()

        def card(label, p):
            return {"label": label, "parameter": p, "name": short_name(p) if p else "not logged", "value": self.val(sid, ts, p),
                    "unit": self.unit(p)}
        temps = [(p, self.val(sid, ts, p)) for p in k["transformer_temperature"]]
        temps = [t for t in temps if t[1] is not None]
        tmax = max(temps, key=lambda t: t[1]) if temps else (None, None)
        fl = [x for x in (self.val(sid, ts, p) for p in k["feeder_load"]) if x is not None]
        return {"voltage": card("Bus voltage", k["voltage"]), "current": card("Current", k["current"]),
                "transformer_load": card("Transformer load", k["transformer_load"]),
                "transformer_temperature": {"label": "Winding temp (max)", "parameter": tmax[0],
                                            "name": short_name(tmax[0]) if tmax[0] else "not logged", "value": tmax[1], "unit": "°C"},
                "feeder_load": {"label": "Feeder load Σ", "parameter": None, "name": f"{len(fl)} feeders reporting",
                                "value": f(sum(fl), 1) if fl else None, "unit": "A"},
                "breaker_state": {"label": "Breaker / circuit state", "counts": st.value_counts().to_dict(),
                                  "abnormal": {p: x for p, x in st.items() if x in ("PTW", "BREAKDOWN")}}}

    def snapshot(self, sid: str, ts: str, with_groups: bool = True) -> dict:
        s = self.sub(sid)
        v = self.values[sid]
        if ts not in v.index:
            return {"substation": self.brief(s), "timestamp": ts, "available": False}
        out = {"substation": self.brief(s), "timestamp": ts, "log_date": v.at[ts, "log_date"], "hour": int(v.at[ts, "hour"]),
               "available": True, **self.infer(sid, ts), "cards": self.cards(sid, ts)}
        if with_groups:
            groups: dict[str, list] = {}
            for p in v.columns[2:]:
                x = f(v.at[ts, p])
                if x is not None:
                    groups.setdefault(self.meta(p)["category"], []).append(
                        {"parameter": p, "name": short_name(p), "value": x, "unit": self.unit(p), "transformer": self.meta(p).get("transformer")})
            st = self.states[sid].loc[ts].dropna() if ts in self.states[sid].index else pd.Series(dtype=object)
            out["groups"] = groups
            out["states"] = [{"parameter": p, "name": short_name(p), "state": x} for p, x in st.items()]
        return out

    # ------------------------------------------------------------------ series
    def series(self, sid: str, upto: str | None = None, start: str | None = None, end: str | None = None,
               last: int | None = None, params: list[str] | None = None) -> dict:
        v = self.values[sid]
        ts = [t for t in v.index if (not upto or t <= upto) and (not start or t >= start) and (not end or t <= end)]
        if last:
            ts = ts[-last:]
        sc = self.scores[sid]
        k = self.sub(sid)["key_signals"]
        col = lambda p: [f(v.at[t, p]) if p in v.columns else None for t in ts]  # noqa: E731
        out = {"timestamps": ts, "risk": [f(sc.at[t, "risk_score"], 1) for t in ts],
               "anomaly": [f(sc.at[t, "anomaly_score"], 1) for t in ts], "confidence": [f(sc.at[t, "confidence"], 1) for t in ts],
               "category": [sc.at[t, "risk_category"] for t in ts], "signals": {}}
        for group in ("voltages", "transformer_loads", "transformer_temperature", "oil_temperature"):
            out["signals"][group] = [{"parameter": p, "name": short_name(p), "unit": self.unit(p), "values": col(p)} for p in k[group]]
        out["signals"]["feeder_total"] = [{"parameter": "Σ feeders", "name": "Σ logged feeder currents", "unit": "A",
                                           "values": [f(np.nansum([v.at[t, p] for p in k["feeder_load"]]), 1) for t in ts]}]
        if params:
            out["signals"]["selected"] = [{"parameter": p, "name": short_name(p), "unit": self.unit(p), "values": col(p)}
                                          for p in params if p in v.columns]
        return out

    # ------------------------------------------------------------------ digital substation
    def _equipment(self, sid: str) -> dict:
        """Equipment model derived from the sheet's parameter names (buses, transformers, feeders, couplers)."""
        v = self.values[sid]
        kv_cls = self.sub(sid)["voltage_class_kv"]
        buses, trafos, feeders, couplers = {}, {}, [], []

        def level(p):
            m = LEVEL_RE.search(p)
            return int(m.group(1)) if m else None
        for p in v.columns[2:]:
            m = self.meta(p)
            cat, tid = m["category"], m.get("transformer")
            if cat == "bus_voltage":
                lv = level(p) or kv_cls
                if "bus" in p.lower():
                    buses.setdefault(lv, []).append(p)
                elif tid:
                    trafos.setdefault(tid, {"tag": tid, "params": []})["params"].append(p)
            elif cat == "bus_coupler_load":
                couplers.append({"tag": short_name(p), "parameter": p, "voltage_kv": level(p)})
            elif tid and cat in ("transformer_current", "transformer_load_mva", "transformer_winding_temperature",
                                 "transformer_oil_temperature", "tap_position", "power_factor"):
                t = trafos.setdefault(tid, {"tag": tid, "params": []})
                t["params"].append(p)
                if m.get("rating_mva"):
                    t["rating_mva"] = max(t.get("rating_mva") or 0, m["rating_mva"])
            elif cat == "feeder_current":
                feeders.append({"tag": short_name(p), "parameter": p, "voltage_kv": level(p) or 11})
        for t in trafos.values():
            levels = sorted({lv for p in t["params"] for lv in [level(p)] if lv}, reverse=True)
            t["hv_kv"] = levels[0] if levels else kv_cls
            t["lv_kv"] = levels[-1] if len(levels) > 1 else (66 if t.get("rating_mva", 0) >= 100 else 11)
        return {"buses": [{"tag": f"{lv} kV Bus", "voltage_kv": lv, "params": ps} for lv, ps in sorted(buses.items(), reverse=True)],
                "transformers": sorted(trafos.values(), key=lambda t: t["tag"]), "feeders": feeders, "couplers": couplers}

    def topology(self, sid: str, ts: str) -> dict:
        topo = self.sub(sid)["topology"]
        rec = self.infer(sid, ts)
        sigs = self.explain(sid, ts)
        st = self.states[sid].loc[ts] if ts in self.states[sid].index else pd.Series(dtype=object)
        flagged: dict[str, float] = {}
        for x in sigs:
            flagged[x["base_parameter"]] = max(flagged.get(x["base_parameter"], 0), x["contribution_share"])
        for r in rec["rules"]:
            for p in r["parameters"]:
                flagged[p] = max(flagged.get(p, 0), r["severity"])
        rec_cat = rec["risk_category"]

        def status(params):
            hit = max((flagged.get(p, 0) for p in params), default=0)
            if hit <= 0:
                return "NORMAL"
            if rec_cat in ALERT_CATEGORIES and hit >= 0.15:
                return rec_cat
            return "WATCH"

        def node(kind, tag, params, **extra):
            vals = [{"parameter": p, "name": short_name(p), "value": self.val(sid, ts, p), "unit": self.unit(p),
                     "state": (st.get(p) if p in st.index and isinstance(st.get(p), str) else None)} for p in params]
            return {"kind": kind, "tag": tag, "status": status(params), "values": vals,
                    "signals": [x for x in sigs if x["base_parameter"] in params][:3],
                    "rules": [r for r in rec["rules"] if set(r["parameters"]) & set(params)], **extra}
        return {"substation": self.brief(self.sub(sid)), "timestamp": ts, "risk_category": rec_cat, "risk_score": rec["risk_score"],
                "buses": [node("bus", b["tag"], b["params"], voltage_kv=b["voltage_kv"]) for b in topo["buses"]],
                "transformers": [node("transformer", t["tag"], t["params"], hv_kv=t["hv_kv"], lv_kv=t["lv_kv"], rating_mva=t.get("rating_mva"))
                                 for t in topo["transformers"]],
                "feeders": [node("feeder", x["tag"], [x["parameter"]], voltage_kv=x["voltage_kv"]) for x in topo["feeders"]],
                "couplers": [node("coupler", x["tag"], [x["parameter"]], voltage_kv=x["voltage_kv"]) for x in topo["couplers"]],
                "note": "Topology derived from the log-sheet parameter names; equipment status reflects record-level contributing signals."}

    # ------------------------------------------------------------------ health indices
    def health(self, sid: str, ts: str) -> dict:
        fe = self.features[sid].xs(ts, level="timestamp").iloc[0]
        g = lambda k: f(fe.get(k)) if k in fe.index else None  # noqa: E731
        vd, ld = g("voltage_deviation_pct"), g("load_index_deviation_pct")
        resid = [f(fe[c]) for c in fe.index if c.endswith(":: temperature_vs_load") and f(fe[c]) is not None]
        return {"voltage_health": None if vd is None else round(max(0.0, 100 - 10 * abs(vd)), 1),
                "load_health": None if ld is None else round(max(0.0, 100 - 0.8 * max(0.0, abs(ld) - 15)), 1),
                "temperature_health": None if not resid else round(max(0.0, 100 - 12 * max(0.0, max(resid))), 1),
                "note": "Indicators derived from deviations vs the learned baseline (not equipment condition assessments)."}

    def categories(self):
        lo, out = 0, []
        for hi, name in CATEGORIES:
            out.append({"category": name, "min": lo, "max": hi})
            lo = hi + 1
        return out
