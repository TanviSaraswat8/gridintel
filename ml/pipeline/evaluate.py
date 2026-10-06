"""
Label-free evaluation of the ensemble on Dataset A (HVPNL Faridabad). No fault labels exist, so no
accuracy / precision / recall / F1 is computed for HVPNL. Reported instead:

  1. Out-of-sample (LODO) score distribution and risk-category counts per substation
  2. Leakage check: rank agreement between out-of-sample scores and an all-days (in-sample) model
  3. Seed stability of the all-days ensemble
  4. Component agreement (Isolation Forest vs autoencoder vs temporal-window AE)
  5. Manually reviewed real events: category assigned out-of-sample
  6. Operator-state reference (PTW / Breakdown hours) — weak reference, not labels
Public-benchmark results (ETT, NAB) are produced separately by pipeline.benchmarks and appended if present.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .ensemble import fit_ensemble
from .features import EVENT_STATES

ROOT = Path(__file__).resolve().parents[2]
REPORTS = Path(os.getenv("REPORTS_DIR") or ROOT / "reports")
REVIEWED_EVENTS = [
    ("220 Sec-46", "2026-02-02T10:00:00", "11 kV T-I bus voltage logged 0 kV (baseline ≈11.1 kV)"),
    ("220 Sec-46", "2026-02-10T08:00:00", "T-2 11 kV incomer and several feeders logged 0 A while T-4 loading rose"),
]


def _rho(a, b):
    r = spearmanr(a, b)[0]
    return None if np.isnan(r) else round(float(r), 3)


def evaluate(values: pd.DataFrame, states: pd.DataFrame, scored: pd.DataFrame, meta: dict) -> dict:
    from .build import prepare_fold  # local import to avoid a cycle
    out = {"note": "No fault labels in Dataset A; accuracy/precision/recall/F1 are not reported for HVPNL.",
           "substations": {}, "reviewed_events": [], "summary": {}}
    md = ["# Evaluation — GridIntel ensemble (label-free)\n",
          "Dataset A (HVPNL Faridabad) has **no fault labels**: no accuracy, precision, recall or F1 is reported for it.",
          "Scores below are **out-of-sample**: each day is scored by models fitted on the other days (leave-one-day-out).\n"]
    seed_rhos, leak_rhos = [], []
    for sub, g in scored.groupby("substation"):
        vsub = values.xs(sub, level="substation", drop_level=False).dropna(axis=1, how="all")
        ssub = states.loc[states.index.get_level_values("substation") == sub].dropna(axis=1, how="all") if not states.empty else None
        days = sorted(g.log_date.unique())
        res = {"records": int(len(g)), "days": days, "validation": g.evaluation.iloc[0],
               "risk_category_counts": g.risk_category.value_counts().to_dict(),
               "anomaly_score": {k: round(float(v), 1) for k, v in zip(["median", "p90", "max"], np.percentile(g.anomaly_score, [50, 90, 100]))},
               "mean_confidence": round(float(g.confidence.mean()), 1)}
        res["component_agreement"] = {"iforest_vs_autoencoder": _rho(g.iforest_score, g.autoencoder_score),
                                      "iforest_vs_temporal_ae": _rho(g.iforest_score, g.temporal_ae_score),
                                      "autoencoder_vs_temporal_ae": _rho(g.autoencoder_score, g.temporal_ae_score)}
        # all-days model: leakage check + seed stability
        feats, fmeta, ref, _ = prepare_fold(vsub, ssub, days, meta)
        full_scores = []
        for seed in (42, 7, 123):
            b = fit_ensemble(sub, feats, fmeta, ref, meta, seed=seed, calibrate_held_out=False)
            full_scores.append(b.score(feats)["anomaly_score"].values)
        order = feats.index.get_level_values("timestamp")
        oos = g.set_index("timestamp").reindex(order)["anomaly_score"].values
        if len(days) >= 2:
            res["lodo_vs_in_sample_spearman"] = _rho(oos, full_scores[0])
            leak_rhos.append(res["lodo_vs_in_sample_spearman"])
        res["seed_stability_spearman"] = round(float(np.mean([_rho(full_scores[0], s) for s in full_scores[1:]])), 3)
        seed_rhos.append(res["seed_stability_spearman"])
        # operator-state reference
        if ssub is not None and not ssub.empty:
            ev_ts = set(ssub[ssub.isin(EVENT_STATES).any(axis=1)].index.get_level_values("timestamp"))
            m = g.timestamp.isin(ev_ts)
            if m.any() and (~m).any():
                res["operator_state_reference"] = {"hours_with_PTW_or_breakdown": int(m.sum()),
                                                   "mean_anomaly_event_hours": round(float(g[m].anomaly_score.mean()), 1),
                                                   "mean_anomaly_other_hours": round(float(g[~m].anomaly_score.mean()), 1),
                                                   "caveat": "equipment-state counts are model inputs; weak reference only"}
        top = g.sort_values("risk_score", ascending=False).head(5)
        res["top_windows"] = [{"timestamp": r.timestamp, "risk": r.risk_score, "category": r.risk_category,
                               "confidence": r.confidence} for r in top.itertuples()]
        out["substations"][sub] = res
        md += [f"\n## {sub} — {len(g)} hourly records, {res['validation']}\n",
               f"- Risk categories: {res['risk_category_counts']}",
               f"- Anomaly score (0–100): median {res['anomaly_score']['median']}, p90 {res['anomaly_score']['p90']}, max {res['anomaly_score']['max']}; mean confidence {res['mean_confidence']}",
               f"- Component agreement (Spearman): {res['component_agreement']}",
               f"- Seed stability of all-days ensemble (Spearman, 3 seeds): {res['seed_stability_spearman']}"]
        if "lodo_vs_in_sample_spearman" in res:
            md.append(f"- Out-of-sample vs in-sample ranking (Spearman): {res['lodo_vs_in_sample_spearman']}")
        if "operator_state_reference" in res:
            o = res["operator_state_reference"]
            md.append(f"- PTW/Breakdown hours: {o['hours_with_PTW_or_breakdown']} — mean anomaly {o['mean_anomaly_event_hours']} vs {o['mean_anomaly_other_hours']} (weak reference)")
        md.append("- Highest-risk hours: " + "; ".join(f"{w['timestamp']} ({w['category']}, {w['risk']:.0f})" for w in res["top_windows"]))

    md.append("\n## Manually reviewed real events (out-of-sample)\n")
    for sub, ts, desc in REVIEWED_EVENTS:
        r = scored[(scored.substation == sub) & (scored.timestamp == ts)]
        if r.empty:
            continue
        r = r.iloc[0]
        rules = [x["rule"] for x in json.loads(r.rules)]
        item = {"substation": sub, "timestamp": ts, "observation": desc, "risk": r.risk_score, "category": r.risk_category,
                "anomaly_score": r.anomaly_score, "confidence": r.confidence, "rules": rules, "model": r.model_key}
        out["reviewed_events"].append(item)
        md.append(f"- **{sub} {ts}** — {desc}: {r.risk_category} (risk {r.risk_score}, anomaly {r.anomaly_score}, "
                  f"confidence {r.confidence}); rules {rules}; scored by `{r.model_key}`")

    bench = REPORTS / "benchmarks.json"
    if bench.exists():
        b = json.loads(bench.read_text())
        out["public_benchmarks"] = b
        md.append("\n## Public benchmarks (method validation — NOT HVPNL data)\n")
        for name, r in b.items():
            md.append(f"- **{name}**: {r.get('summary', '')}")
    out["summary"] = {"substations_scored": len(out["substations"]), "hourly_records_scored": int(len(scored)),
                      "mean_seed_stability": round(float(np.mean(seed_rhos)), 3),
                      "mean_lodo_vs_in_sample": round(float(np.mean([x for x in leak_rhos if x is not None])), 3) if leak_rhos else None,
                      "reviewed_events_flagged_warning_or_above": sum(e["category"] in ("WARNING", "HIGH RISK", "CRITICAL") for e in out["reviewed_events"]),
                      "reviewed_events_total": len(out["reviewed_events"])}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "evaluation.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out
