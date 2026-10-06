"""Investigation workspace payload: WHAT happened, WHY flagged, WHICH signals, HOW unusual, WHAT to check.
Wording is non-causal by design ("contributing signals", "potential abnormal operating condition")."""
from __future__ import annotations

from pipeline.ensemble import ALERT_CATEGORIES

from ..core.config import DISCLAIMER, RISK_NOTE
from .store import Store, f, short_name

HEADLINE = {"NORMAL": "No abnormal operating condition indicated.",
            "WATCH": "Mild deviation from the learned operating pattern — keep under observation.",
            "WARNING": "Potential abnormal operating condition detected.",
            "HIGH RISK": "Potential abnormal operating condition detected (high AI risk indicator).",
            "CRITICAL": "Potential abnormal operating condition detected (critical AI risk indicator)."}
DEMO_EVENTS = [
    {"id": "sec46-2026-02-02-1000", "substation_id": "220-sec-46", "timestamp": "2026-02-02T10:00:00",
     "title": "11 kV T-I bus voltage logged 0 kV",
     "summary": "Real record, 220 kV Sector-46, 02 Feb 2026 10:00 — 11 kV T-I voltage reads 0 kV against a typical ≈11.1 kV."},
    {"id": "sec46-2026-02-10-0800", "substation_id": "220-sec-46", "timestamp": "2026-02-10T08:00:00",
     "title": "T-2 incomer and feeders at 0 A while T-4 loading rises",
     "summary": "Real record, 220 kV Sector-46, 10 Feb 2026 08:00 — T-2 11 kV incomer and several feeders read 0 A; T-4 loading increases over 07:00–09:00."},
]


def _fmt(v, unit=""):
    if v is None:
        return "n/a"
    return f"{f(v, 2):g} {unit}".strip()


def unusualness(z: float | None, share: float) -> str:
    az = abs(z or 0)
    if az >= 6 or share >= 0.35:
        return "extreme"
    if az >= 3 or share >= 0.2:
        return "strong"
    if az >= 2 or share >= 0.1:
        return "moderate"
    return "mild"


def observed(store: Store, sid: str, ts: str, sig: dict) -> str:
    return observed_i18n(store, sid, ts, sig)[0]


def observed_i18n(store: Store, sid: str, ts: str, sig: dict) -> tuple[str, list]:
    """English sentence plus [template key, args] so clients can render it in other languages."""
    kind, unit = sig["kind"], sig.get("unit") or ""
    v, med, p10, p90 = sig["value"], sig["baseline_median"], sig["baseline_p10"], sig["baseline_p90"]
    fm = store.bundle_for(sid, ts).iforest.feature_meta.get(sig["feature"], {})
    lab = sig.get("label", "")
    if kind == "thermal_residual":
        lp, base = fm.get("load_parameter"), fm.get("base_parameter")
        a = {"p": short_name(base), "v": _fmt(store.val(sid, ts, base), "°C"), "d": _fmt(abs(v), "°C"),
             "lp": short_name(lp), "lv": _fmt(store.val(sid, ts, lp), store.unit(lp))}
        key = "obs.thermal_above" if v > 0 else "obs.thermal_below"
        return (f"{a['p']} reads {a['v']}, {a['d']} {'above' if v > 0 else 'below'} the level expected for the current loading of "
                f"{a['lp']} ({a['lv']})."), [key, a]
    a = {"label": lab, "v": _fmt(v, unit), "p10": _fmt(p10, unit), "p90": _fmt(p90, unit), "med": _fmt(med, unit)}
    if kind in ("rate_of_change", "state_change"):
        return f"{lab}: {a['v']} this hour (typical {a['p10']} to {a['p90']}).", ["obs.change", a]
    if kind in ("deviation", "rolling_std", "rolling_mean", "rolling_max", "rolling_min", "imbalance", "stress"):
        return f"{lab}: {a['v']} (typical {a['p10']} to {a['p90']}).", ["obs.deviation", a]
    if kind == "equipment_state":
        a["v"], a["med"] = _fmt(v), _fmt(med)
        return f"{lab}: {a['v']} (typical {a['med']}).", ["obs.state", a]
    if v is not None and p10 is not None and p90 is not None and p10 <= v <= p90:
        return f"{lab} = {a['v']} is inside its usual range but contributes as part of an unusual combination.", ["obs.inside", a]
    key = "obs.below" if sig.get("direction") == "below" else "obs.above"
    return (f"{lab} = {a['v']} is {sig['direction']} its learned range {a['p10']} – {a['p90']} (median {a['med']})."), [key, a]


def build(store: Store, sid: str, ts: str) -> dict:
    s = store.sub(sid)
    snap = store.snapshot(sid, ts)
    if not snap.get("available"):
        return {"available": False, "substation": snap["substation"], "timestamp": ts}
    sigs = [x for x in store.explain(sid, ts) if x["kind"] != "time"]
    rules = snap["rules"]
    primary = store.primary_signal(sid, sigs, rules) if sigs else None
    if rules and rules[0]["parameters"]:
        # an engineering rule fired: the affected parameter is the first measurement named by the strongest rule
        p0 = rules[0]["parameters"][0]
        col = store.values[sid][p0].astype(float)
        match = next((x for x in sigs if x["base_parameter"] == p0), None)
        primary = match or {"feature": p0, "base_parameter": p0, "kind": "measurement", "label": short_name(p0),
                            "unit": store.unit(p0), "value": store.val(sid, ts, p0), "baseline_median": f(col.median()),
                            "baseline_p10": f(col.quantile(.1)), "baseline_p90": f(col.quantile(.9)), "deviation_z": None,
                            "contribution_share": 0.0, "direction": "below" if (store.val(sid, ts, p0) or 0) < (col.median() or 0) else "above",
                            "level": "High", "description": rules[0]["title"]}
        if match is None:
            primary["observed"], primary["observed_i18n"] = observed_i18n(store, sid, ts, primary)
            primary["unusualness"] = "strong" if rules[0]["severity"] >= 0.6 else "moderate"
            primary["is_primary"] = True
    for x in sigs:
        x["observed"], x["observed_i18n"] = observed_i18n(store, sid, ts, x)
        x["unusualness"] = unusualness(x.get("deviation_z"), x.get("contribution_share", 0))
        x["is_primary"] = primary is not None and x["feature"] == primary.get("feature")
    cat = snap["risk_category"]
    # evidence: the actual source measurements behind the signals and rules
    ev_params: list[str] = []
    for r in rules:
        ev_params += r["parameters"]
    ev_params += [x["base_parameter"] for x in sigs]
    evidence, seen = [], set()
    for p in ev_params:
        if p in seen or p not in store.values[sid].columns:
            continue
        seen.add(p)
        evidence.append({"parameter": p, "name": short_name(p), "unit": store.unit(p), "value": store.val(sid, ts, p),
                         "median": f(store.values[sid][p].median()), "transformer": store.meta(p).get("transformer"),
                         "source": f"HVPNL log sheet '{s['sheet']}', {ts[:10]} hour {int(store.values[sid].at[ts, 'hour']):02d}:00"})
    # trend window: up to 12 preceding replayed hours + 3 following hours (if logged) for context
    tl = list(store.values[sid].index)
    i = tl.index(ts)
    window = tl[max(0, i - 12): i + 4]
    trend = {"timestamps": window, "focus": ts,
             "risk": [f(store.scores[sid].at[t, "risk_score"], 1) for t in window],
             "anomaly": [f(store.scores[sid].at[t, "anomaly_score"], 1) for t in window], "series": []}
    for p in [e["parameter"] for e in evidence][:5]:
        trend["series"].append({"parameter": p, "name": short_name(p), "unit": store.unit(p),
                                "values": [store.val(sid, t, p) for t in window], "baseline_median": f(store.values[sid][p].median())})
    investigate = [r["investigate"] for r in rules]
    investigate_i18n = [r.get("i18n", {}).get("check") for r in rules]
    if not investigate and primary:
        investigate = [f"Review {short_name(primary['base_parameter'])} against operator remarks and adjacent equipment for this hour."]
        investigate_i18n = [["inv.review", {"p": short_name(primary["base_parameter"])}]]
    tid = store.meta(primary["base_parameter"]).get("transformer") if primary and primary["base_parameter"] in store.param_meta else None
    return {
        "available": True, "substation": snap["substation"], "timestamp": ts, "log_date": snap["log_date"], "hour": snap["hour"],
        "title": "ANOMALY DETECTED" if cat in ALERT_CATEGORIES else ("UNDER OBSERVATION" if cat == "WATCH" else "NORMAL OPERATION"),
        "headline": HEADLINE[cat],
        "message": f"Potential abnormal operating condition detected at {s['name']}." if cat in ALERT_CATEGORIES else HEADLINE[cat],
        "what": (rules[0]["message"] if rules else (primary["observed"] if primary else HEADLINE[cat])),
        "why": (f"The AI risk indicator is {snap['risk_score']:.0f}/100 ({cat}). Model anomaly score {snap['anomaly_score']:.0f}/100 "
                f"(Isolation Forest {snap['components']['iforest']:.0f}, autoencoder {snap['components']['autoencoder']:.0f}, "
                f"temporal AE {snap['components']['temporal_ae']:.0f}); engineering rules {snap['rule_score']:.0f}/100."),
        "how_unusual": (primary["unusualness"] if primary else "mild"),
        "investigate": investigate,
        # i18n: [template key, args] pairs; clients rebuild the sentences above in the viewer's language
        "i18n": {
            "message": ["msg.detected_at", {"name": s["name"]}] if cat in ALERT_CATEGORIES else [HEADLINE[cat], {}],
            "what": (rules[0].get("i18n", {}).get("msg") if rules else (primary.get("observed_i18n") if primary else [HEADLINE[cat], {}])),
            "why": ["why.summary", {"risk": f"{snap['risk_score']:.0f}", "cat": cat, "anomaly": f"{snap['anomaly_score']:.0f}",
                                    "if": f"{snap['components']['iforest']:.0f}", "ae": f"{snap['components']['autoencoder']:.0f}",
                                    "tw": f"{snap['components']['temporal_ae']:.0f}", "rules": f"{snap['rule_score']:.0f}"}],
            "expected": (["exp.baseline", {"med": _fmt(primary["baseline_median"], primary.get("unit", "")),
                                           "p10": _fmt(primary["baseline_p10"], primary.get("unit", "")),
                                           "p90": _fmt(primary["baseline_p90"], primary.get("unit", ""))}] if primary else None),
            "investigate": investigate_i18n,
        },
        "anomaly_score": snap["anomaly_score"], "risk_score": snap["risk_score"], "confidence": snap["confidence"],
        "risk_category": cat, "components": snap["components"], "rule_score": snap["rule_score"], "rules": rules,
        "model_key": snap["model_key"], "evaluation": snap["evaluation"],
        "affected_parameter": primary["label"] if primary else None, "primary": primary,
        "current_value": primary["value"] if primary else None,
        "expected_behaviour": (f"Learned baseline (training days only): median {_fmt(primary['baseline_median'], primary.get('unit', ''))}, "
                               f"typical {_fmt(primary['baseline_p10'], primary.get('unit', ''))} – {_fmt(primary['baseline_p90'], primary.get('unit', ''))}")
                              if primary else None,
        "contributing_signals": sigs, "evidence": evidence, "related_equipment": tid,
        "equipment_state": snap["states"], "cards": snap["cards"], "trend": trend,
        "method": ("Contributing signals: occlusion attribution on the Isolation Forest (each input replaced by its baseline "
                   "median; larger drop in anomaly score = stronger signal) plus rule-based engineering checks. These are "
                   "contributing signals — not confirmed causes."),
        "data_note": "Historical HVPNL log readings, replayed (not a live SCADA feed).",
        "risk_note": RISK_NOTE, "disclaimer": DISCLAIMER,
    }
