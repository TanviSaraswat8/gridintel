"""
Physical plausibility checks on header-inferred units.

Log-sheet headers are merged across columns, so a column can inherit a group label that does not describe it
(e.g. currents in amps sitting under a merged "LOAD IN MVA" header). Before any electrical rule or display card
uses a parameter, its logged magnitudes are checked against physics:

- bus voltage columns must sit within ±20 % of the nominal kV written in their own name;
  auxiliary 240 V AC / DC battery columns are recognised and moved to their own categories;
- "MVA" columns must not exceed 1.5x the transformer's nameplate rating; when a sibling MVA column exists for
  the same transformer, a column is re-classified as current only if sqrt(3)*V*I reproduces that MVA (±20 %).

A parameter that cannot be verified is re-labelled `unverified` (unit unknown). Its readings are kept in the
clean dataset and in the anomaly models (which are unit-agnostic) but excluded from engineering rules, physical
cards and unit-bearing displays. Nothing is deleted and no value is altered; every decision is reported.
"""
from __future__ import annotations

import math
import re

import pandas as pd

from .features import mva_rating, transformer_id

PLAUSIBILITY_VERSION = "1.0.0"
SQRT3 = math.sqrt(3)


def nominal_kv(param: str) -> float | None:
    m = re.findall(r"(\d+(?:\.\d+)?)\s*kv", param.lower())
    return float(m[-1]) if m else None


def _median(values: pd.DataFrame, p: str) -> float | None:
    if p not in values.columns:
        return None
    s = pd.to_numeric(values[p], errors="coerce").dropna()
    s = s[s > 0]
    return float(s.median()) if len(s) else None


def validate(meta: dict, values_by_sub: dict[str, pd.DataFrame]) -> tuple[dict, list[dict]]:
    """Return (updated meta, findings). `values_by_sub`: substation -> wide numeric frame (raw, not imputed)."""
    meta = {p: dict(m) for p, m in meta.items()}
    findings: list[dict] = []

    def record(sub, p, old, new, unit, reason, evidence):
        findings.append({"substation": sub, "parameter": p, "from_category": old, "to_category": new,
                         "unit": unit, "reason": reason, "evidence": evidence})

    for sub, v in values_by_sub.items():
        cols = [c for c in v.columns if c in meta]
        mva_cols = [c for c in cols if meta[c]["category"] == "transformer_load_mva"]
        mva_by_tag: dict[str, float] = {}
        for c in mva_cols:
            t, med = transformer_id(c), _median(v, c)
            name = c.lower()
            looks_like_level = re.search(r"\b(11|33|66|132|220)\s*kv\s*load\b", name)
            if t and med is not None and not looks_like_level:
                mva_by_tag.setdefault(t, med)

        for p in cols:
            m, low, med = meta[p], p.lower(), _median(v, p)
            if med is None:
                continue
            cat = m["category"]

            if cat == "bus_voltage":
                if "batt" in low or "d. c." in low or "d.c" in low or re.search(r"\bdc\b", low):
                    meta[p] = {"category": "dc_battery_voltage", "unit": "V"}
                    record(sub, p, cat, "dc_battery_voltage", "V", "DC auxiliary supply, not a power bus",
                           f"median {med:g}")
                    continue
                if re.search(r"a\.?\s*c\.?\s*voltage", low):
                    meta[p] = {"category": "lt_voltage", "unit": "V"}
                    record(sub, p, cat, "lt_voltage", "V", "AC auxiliary (LT) supply, not a power bus", f"median {med:g}")
                    continue
                kv = nominal_kv(p)
                if kv is None or not (0.8 * kv <= med <= 1.2 * kv):
                    meta[p] = {"category": "unverified", "unit": "unknown"}
                    why = (f"median {med:g} is outside ±20 % of the {kv:g} kV nominal in its name"
                           if kv else f"median {med:g} with no nominal kV in its name")
                    record(sub, p, cat, "unverified", "unknown", "logged magnitudes inconsistent with a bus voltage", why)

            elif cat == "transformer_load_mva":
                t, rating = transformer_id(p), mva_rating(p)
                kv = nominal_kv(p)
                ref_mva = mva_by_tag.get(t) if t else None
                if kv and ref_mva:
                    implied = SQRT3 * kv * med / 1000.0          # MVA implied if the column were amps
                    if abs(implied / ref_mva - 1) <= 0.20:
                        meta[p] = {"category": "transformer_current", "unit": "A"}
                        record(sub, p, cat, "transformer_current", "A",
                               "values are currents under a merged 'LOAD IN MVA' header",
                               f"√3 × {kv:g} kV × {med:g} A = {implied:.2f} MVA ≈ {ref_mva:.2f} MVA logged for {t}")
                        continue
                limit = 1.5 * rating if rating else 300.0
                if med > limit:
                    meta[p] = {"category": "unverified", "unit": "unknown"}
                    record(sub, p, cat, "unverified", "unknown", "too large to be MVA for this transformer",
                           f"median {med:g} > {limit:g}")
    return meta, findings


def report_markdown(findings: list[dict]) -> str:
    lines = ["# Data-quality report — unit plausibility", "",
             "Generated by `ml/pipeline/plausibility.py`. Header-inferred units were checked against physics. "
             "No values were changed; only the category/unit label used by rules and displays.", ""]
    if not findings:
        return "\n".join(lines + ["No inconsistencies found."]) + "\n"
    lines += ["| Substation | Parameter | Was | Now | Reason | Evidence |", "|---|---|---|---|---|---|"]
    for f in findings:
        lines.append(f"| {f['substation']} | {f['parameter']} | {f['from_category']} | {f['to_category']} ({f['unit']}) | "
                     f"{f['reason']} | {f['evidence']} |")
    return "\n".join(lines) + "\n"
