"""
Rule-based engineering signals evaluated on the RAW logged values of one hourly record.

Thresholds are prototype engineering heuristics for decision support. They are NOT utility protection
settings or statutory limits. Each rule returns a severity in [0, 1], a plain-language message, the
parameters involved, and what an engineer could check. Rules never assert a cause.
"""
from __future__ import annotations

import math

import pandas as pd

from .features import transformer_id

RULES_VERSION = "1.0.0"


def _num(x):
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def _short(p: str) -> str:
    return p.split("|")[-1].strip() if "|" in p else p


def evaluate(values: pd.DataFrame, states: pd.DataFrame, ts: str, meta: dict, ref: dict) -> list[dict]:
    """values/states: one substation, index = timestamp (sorted), values has a 'log_date' column."""
    if ts not in values.index:
        return []
    row = values.loc[ts]
    day = row.get("log_date")
    pos = values.index.get_loc(ts)
    prev = values.iloc[pos - 1] if pos > 0 and values.iloc[pos - 1].get("log_date") == day else None
    med = ref.get("medians", {})
    cat = lambda p: meta.get(p, {}).get("category")  # noqa: E731
    out: list[dict] = []

    def hit(rule, sev, title, msg, params, check):
        out.append({"rule": rule, "severity": round(sev, 2), "title": title, "message": msg,
                    "parameters": params, "investigate": check})

    cols = [c for c in values.columns if c not in ("log_date", "hour")]

    # R-V: bus voltage
    for p in [c for c in cols if cat(c) == "bus_voltage"]:
        v, m = _num(row[p]), med.get(p)
        if v is None or not m:
            continue
        if v < 0.5 * m:
            hit("R-V1", 0.9, "Bus voltage collapse or missing reading",
                f"{_short(p)} logged {v:g} kV against a typical {m:.4g} kV.", [p],
                "Confirm with the operator log whether the bus / transformer secondary was de-energised or the "
                "reading was not recorded; check related incomer currents at the same hour.")
        elif abs(v / m - 1) > 0.05:
            sev = 0.65 if abs(v / m - 1) > 0.08 else 0.5
            hit("R-V2", sev, "Bus voltage outside ±5 % of its typical level",
                f"{_short(p)} = {v:g} kV ({(v / m - 1) * 100:+.1f} % vs typical {m:.4g} kV).", [p],
                "Review tap positions and upstream supply voltage for this hour.")

    # R-L1: incomers / feeders dropping to zero
    if prev is not None:
        inc = [c for c in cols if cat(c) == "transformer_current" and (_num(prev[c]) or 0) > 0 and _num(row[c]) == 0]
        fdr = [c for c in cols if cat(c) == "feeder_current" and (_num(prev[c]) or 0) > 0 and _num(row[c]) == 0]
        if inc or len(fdr) >= 3:
            sev = 0.85 if inc and len(fdr) >= 2 else (0.75 if inc else 0.6)
            names = ", ".join(_short(c) for c in (inc + fdr)[:5])
            hit("R-L1", sev, "Incomer / feeder currents dropped to zero",
                f"{len(inc)} incomer(s) and {len(fdr)} feeder(s) went from >0 A to 0 A since the previous hour: {names}.",
                inc + fdr, "Check breaker operations, load transfers between transformers and the shift remarks for "
                           "this hour; compare with loading on the other transformers.")

        # R-L2: rapid transformer loading change
        for c in [c for c in cols if cat(c) in ("transformer_load_mva", "transformer_current")]:
            v, pv, m = _num(row[c]), _num(prev[c]), med.get(c) or 0
            if v is None or pv is None or m <= 0 or pv < 0.3 * m:
                continue
            rel = (v - pv) / pv
            if rel > 0.5:
                hit("R-L2", 0.7 if rel > 1.0 else 0.55, "Rapid transformer loading increase",
                    f"{_short(c)} rose from {pv:g} to {v:g} ({rel * 100:+.0f} %) within one hour.", [c],
                    f"Check whether load was transferred onto {transformer_id(c) or 'this transformer'} and monitor its "
                    "winding / oil temperature over the following hours.")

    # R-T: thermal
    for wt, fit in ref.get("thermal_fits", {}).items():
        v, lp = _num(row.get(wt)), fit["load_parameter"]
        lv = _num(row.get(lp))
        if v is None or lv is None:
            continue
        resid = v - (fit["slope"] * lv + fit["intercept"])
        mad = max(fit.get("resid_mad", 1.0), 0.5)
        if resid > 3 and resid > 3 * mad:
            hit("R-T1", 0.75 if resid > 5 * mad else 0.6, "Winding temperature above load-expected level",
                f"{_short(wt)} is {v:g} °C, {resid:.1f} °C above the temperature expected for the current loading "
                f"of {_short(lp)} ({lv:g}).", [wt, lp],
                "Check cooling (fans/pumps) status, oil temperature trend and ambient conditions.")
        if prev is not None:
            pv = _num(prev.get(wt))
            if pv is not None and v - pv >= 4:
                hit("R-T2", 0.5, "Fast winding temperature rise", f"{_short(wt)} rose {v - pv:.0f} °C in one hour.",
                    [wt], "Monitor the next readings; compare with loading and cooling-fan state.")

    # R-S1: loading vs nameplate rating
    for p, rating in ref.get("ratings", {}).items():
        v = _num(row.get(p))
        if v is not None and v / rating > 0.8:
            hit("R-S1", 0.8 if v / rating > 1.0 else 0.5, "Transformer loading high relative to rating",
                f"{_short(p)} at {v:g} MVA = {v / rating * 100:.0f} % of {rating:g} MVA rating.", [p],
                "Review loading plan and thermal margin for this transformer.")

    # R-E1: operator-logged equipment states
    if states is not None and ts in states.index:
        st = states.loc[ts].dropna()
        bd = [p for p, s in st.items() if s == "BREAKDOWN"]
        ptw = [p for p, s in st.items() if s == "PTW"]
        if bd:
            hit("R-E1", 0.45, "Breakdown logged by operator", f"Breakdown logged on: {', '.join(_short(p) for p in bd)}.",
                bd, "Refer to the breakdown report for this feeder.")
        if ptw:
            hit("R-E2", 0.3, "Permit-to-work logged (planned outage)",
                f"PTW logged on: {', '.join(_short(p) for p in ptw)}.", ptw,
                "Planned work — confirm the related readings are consistent with the outage.")
    out.sort(key=lambda r: -r["severity"])
    return out


def severity(rules: list[dict]) -> float:
    """Combined rule severity: strongest rule plus a small increment for each additional independent rule."""
    if not rules:
        return 0.0
    s = sorted((r["severity"] for r in rules), reverse=True)
    return min(1.0, s[0] + 0.05 * (len({r["rule"] for r in rules}) - 1))
