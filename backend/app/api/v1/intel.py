"""Alerts, anomalies, investigation workspace, analytics, fleet, model lab, data explorer, replay control."""
from __future__ import annotations

import csv
import io
from functools import lru_cache

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ...core.config import DISCLAIMER, RISK_NOTE, get_settings
from ...core.security import require
from ...db.models import Alert, Investigation
from ...db.session import session_scope
from ...services.investigation import DEMO_EVENTS
from ...services.investigation import build as build_investigation
from ...services.store import f, short_name
from ..deps import audit, replay, store, sub_or_404, sub_with_data, ts_or_404
from .grid import _alert

router = APIRouter()
viewer = [Depends(require("VIEWER"))]


# ------------------------------------------------------------------------------------------- alerts / anomalies
@router.get("/alerts", tags=["alerts"], dependencies=viewer)
def alerts(substation: str | None = None, category: str | None = None, page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200)):
    with session_scope() as db:
        q = select(Alert).order_by(Alert.id.desc())
        if substation:
            q = q.where(Alert.substation_id == substation)
        if category:
            q = q.where(Alert.risk_category == category)
        items = [_alert(a) for a in db.execute(q.offset((page - 1) * size).limit(size)).scalars()]
    return {"items": items, "page": page, "size": size, "replay": replay().status()}


@router.post("/alerts/{alert_id}/acknowledge", tags=["alerts"])
def acknowledge(alert_id: int, request: Request, user: dict = Depends(require("OPERATOR"))):
    with session_scope() as db:
        a = db.get(Alert, alert_id)
        if not a:
            raise HTTPException(404, "Alert not found")
        a.acknowledged_by = user["sub"]
    audit(request, user["sub"], "alert.acknowledge", {"alert_id": alert_id})
    return {"ok": True}


@router.get("/anomalies", tags=["anomalies"], dependencies=viewer)
def anomalies(substation: str | None = None, min_risk: float = Query(56, ge=0, le=100), start: str | None = None,
              end: str | None = None, page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200)):
    """Every scored historical hour (out-of-sample) at or above min_risk."""
    sc = store().scored
    if substation:
        sc = sc[sc.substation == sub_or_404(substation)["sheet"]]
    if start:
        sc = sc[sc.timestamp >= start]
    if end:
        sc = sc[sc.timestamp <= end]
    sc = sc[sc.risk_score >= min_risk].sort_values("risk_score", ascending=False)
    total = len(sc)
    items = []
    for r in sc.iloc[(page - 1) * size: page * size].itertuples():
        sid = store().by_sheet[r.substation]["id"]
        sig = [x for x in store().explain(sid, r.timestamp) if x["kind"] != "time"]
        top = store().primary_signal(sid, sig, r.rules)
        items.append({"substation_id": sid, "substation_name": store().by_sheet[r.substation]["name"], "record_timestamp": r.timestamp,
                      "risk_score": r.risk_score, "risk_category": r.risk_category, "anomaly_score": r.anomaly_score,
                      "confidence": r.confidence, "parameter": top.get("base_parameter"),
                      "parameter_label": r.rules[0]["title"] if r.rules else top.get("label"),
                      "rules": [x["rule"] for x in r.rules], "signals": [{"label": x["label"], "level": x["level"]} for x in sig[:3]]})
    return {"total": total, "page": page, "size": size, "items": items}


# ------------------------------------------------------------------------------------------- investigation
@router.get("/investigations/demo", tags=["investigation"], dependencies=viewer)
def demo_events():
    out = []
    for e in DEMO_EVENTS:
        r = store().infer(e["substation_id"], e["timestamp"])
        out.append({**e, "risk_score": r["risk_score"], "risk_category": r["risk_category"], "confidence": r["confidence"]})
    return {"items": out, "note": "Both events are real records from the supplied HVPNL files."}


@router.get("/investigations", tags=["investigation"], dependencies=viewer)
def investigation(substation: str, timestamp: str):
    sub_with_data(substation)
    out = build_investigation(store(), substation, ts_or_404(substation, timestamp))
    with session_scope() as db:
        notes = db.execute(select(Investigation).where(Investigation.substation_id == substation, Investigation.record_ts == timestamp)
                           .order_by(Investigation.id.desc())).scalars().all()
        out["notes"] = [{"id": n.id, "author": n.author, "status": n.status, "note": n.note, "created_at": n.created_at.isoformat()} for n in notes]
    return out


class NoteIn(BaseModel):
    substation: str = Field(max_length=64)
    timestamp: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
    status: str = Field("OPEN", pattern="^(OPEN|REVIEWED|DISMISSED)$")
    note: str = Field(min_length=1, max_length=4000)


@router.post("/investigations/notes", tags=["investigation"])
def add_note(body: NoteIn, request: Request, user: dict = Depends(require("ENGINEER"))):
    sub_with_data(body.substation)
    ts_or_404(body.substation, body.timestamp)
    with session_scope() as db:
        n = Investigation(substation_id=body.substation, record_ts=body.timestamp, author=user["sub"], status=body.status, note=body.note)
        db.add(n)
        db.flush()
        nid = n.id
    audit(request, user["sub"], "investigation.note", {"id": nid, "substation": body.substation, "ts": body.timestamp})
    return {"id": nid}


# ------------------------------------------------------------------------------------------- analytics / fleet
@lru_cache(maxsize=128)
def _analytics(sid: str, start: str | None, end: str | None, param: str | None) -> dict:
    st = store()
    s = st.sub(sid)
    ser = st.series(sid, start=start, end=end, params=[param] if param else None)
    ts = ser["timestamps"]
    sc = st.scores[sid].loc[ts]
    k = s["key_signals"]

    def dist(p):
        v = st.values[sid].loc[ts, p].dropna().astype(float)
        if v.empty:
            return None
        h, e = np.histogram(v, bins=12)
        return {"parameter": p, "name": short_name(p), "unit": st.unit(p), "counts": h.tolist(), "edges": [round(x, 2) for x in e],
                "median": f(v.median()), "p10": f(v.quantile(.1)), "p90": f(v.quantile(.9))}
    agg: dict[str, float] = {}
    for t in sc[sc.risk_score > 30].index:
        for e in st.explain(sid, t):
            if e["kind"] != "time":
                agg[e["label"]] = agg.get(e["label"], 0) + e["contribution_share"]
    cols = {short_name(p): st.values[sid].loc[ts, p].astype(float) for p in (k["voltages"][:2] + k["transformer_loads"][:3] + k["transformer_temperature"][:3])}
    cols["Risk"] = sc["risk_score"].astype(float)
    cf = pd.DataFrame(cols)
    cf = cf.loc[:, cf.std() > 0]
    corr = cf.corr().round(2).fillna(0)
    eq = []
    for t in s["topology"]["transformers"]:
        loads = [p for p in t["params"] if st.meta(p)["category"] == "transformer_load_mva"]
        temps = [p for p in t["params"] if st.meta(p)["category"] == "transformer_winding_temperature"]
        lv = st.values[sid].loc[ts, loads[0]].astype(float) if loads else None
        tv = st.values[sid].loc[ts, temps].astype(float).max(axis=1) if temps else None
        eq.append({"equipment": t["tag"], "rating_mva": t.get("rating_mva"),
                   "peak_load_mva": f(lv.max()) if lv is not None else None,
                   "load_factor": f(lv.mean() / lv.max(), 3) if lv is not None and lv.max() else None,
                   "peak_loading_pct": f(lv.max() / t["rating_mva"] * 100, 1) if lv is not None and t.get("rating_mva") else None,
                   "max_winding_temp": f(tv.max()) if tv is not None else None})
    timeline = [{"timestamp": t, "risk": f(sc.at[t, "risk_score"], 1), "category": sc.at[t, "risk_category"],
                 "rules": [r["rule"] for r in sc.at[t, "rules"]]} for t in sc.index if sc.at[t, "risk_score"] > 55]
    return {"substation": st.brief(s), "series": ser,
            "risk_distribution": sc.risk_category.value_counts().reindex([c["category"] for c in st.categories()]).fillna(0).astype(int).to_dict(),
            "anomaly_histogram": dict(zip(["counts", "edges"], [x.tolist() for x in np.histogram(sc.anomaly_score, bins=10, range=(0, 100))])),
            "parameter_distributions": [d for d in (dist(p) for p in [k["voltage"], k["transformer_load"], *k["transformer_temperature"][:2]] if p) if d],
            "top_contributing_signals": [{"label": a, "weight": round(w, 3)} for a, w in sorted(agg.items(), key=lambda t: -t[1])[:10]],
            "correlation": {"labels": corr.columns.tolist(), "matrix": corr.values.tolist()},
            "equipment_health": eq, "anomaly_timeline": timeline,
            "parameters": [p for p in st.values[sid].columns[2:]],
            "evaluation": st.evaluation.get("substations", {}).get(s["sheet"], {})}


@router.get("/analytics", tags=["analytics"], dependencies=viewer)
def analytics(substation: str, start: str | None = None, end: str | None = None, parameter: str | None = None):
    sub_with_data(substation)
    if parameter and parameter not in store().values[substation].columns:
        raise HTTPException(422, f"Unknown parameter for {substation}")
    return _analytics(substation, start, end, parameter)


@router.get("/fleet", tags=["analytics"], dependencies=viewer)
def fleet(sort: str = Query("risk", pattern="^(risk|newest|temperature|loading)$")):
    st = store()
    items = []
    for s in st.substations:
        if not s["has_model"]:
            items.append({"substation_id": s["id"], "name": s["name"], "data_status": "NO SOURCE READINGS", "available": False})
            continue
        ts = st.latest_ts(s["id"], replay().current_ts)
        h = st.scores[s["id"]]
        events = h[h.risk_score > 55]
        last_event = events[events.index <= (ts or "")].index.max() if ts else None
        row = {"substation_id": s["id"], "name": s["name"], "data_status": "AVAILABLE", "available": ts is not None,
               "records": s["records"], "low_confidence": s["low_confidence"], "validation": s["validation"],
               "history_mean_risk": f(h.risk_score.mean(), 1), "history_counts": h.risk_category.value_counts().to_dict(),
               "last_event": None if (last_event is None or (isinstance(last_event, float) and np.isnan(last_event))) else last_event}
        if ts:
            r = st.infer(s["id"], ts)
            c = st.cards(s["id"], ts)
            row.update({"timestamp": ts, "risk_score": r["risk_score"], "risk_category": r["risk_category"],
                        "anomaly_score": r["anomaly_score"], "confidence": r["confidence"], **st.health(s["id"], ts),
                        "temperature": c["transformer_temperature"]["value"], "loading": c["transformer_load"]["value"],
                        "loading_unit": c["transformer_load"]["unit"]})
        items.append(row)
    key = {"risk": lambda r: -(r.get("risk_score") or -1), "newest": lambda r: r.get("last_event") or "",
           "temperature": lambda r: -(r.get("temperature") or -1), "loading": lambda r: -(r.get("loading") or -1)}[sort]
    av = sorted([r for r in items if r["available"]], key=key, reverse=(sort == "newest"))
    return {"items": av + [r for r in items if not r["available"]], "sort": sort}


# ------------------------------------------------------------------------------------------- data explorer
@router.get("/explorer", tags=["data"], dependencies=viewer)
def explorer(substation: str, parameter: str, date: str | None = None, hour: int | None = Query(None, ge=1, le=24),
             page: int = Query(1, ge=1), size: int = Query(100, ge=1, le=500)):
    rows = _explorer_rows(substation, parameter, date, hour)
    return {"total": len(rows), "page": page, "size": size, "items": rows[(page - 1) * size: page * size],
            "unit": store().unit(parameter), "note": "raw = cell text in the Excel log; cleaned = parsed numeric value (missing kept as null)."}


def _explorer_rows(sid: str, p: str, date: str | None, hour: int | None) -> list[dict]:
    sub_with_data(sid)
    st = store()
    v = st.values[sid]
    if p not in v.columns:
        raise HTTPException(422, f"Parameter not logged at {sid}")
    raw = _raw_cells(st.sub(sid)["sheet"], p)
    s = v[p].astype(float)
    day = v["log_date"]
    rmean = s.groupby(day).transform(lambda x: x.rolling(3, min_periods=1).mean())
    rstd = s.groupby(day).transform(lambda x: x.rolling(3, min_periods=2).std())
    out = []
    for t in v.index:
        if date and not t.startswith(date) and day[t] != date:
            continue
        if hour and int(v.at[t, "hour"]) != hour:
            continue
        sc = st.scores[sid]
        out.append({"timestamp": t, "log_date": day[t], "hour": int(v.at[t, "hour"]), "raw_value": raw.get(t),
                    "cleaned_value": f(s[t], 3), "rolling_mean_3h": f(rmean[t], 3), "rolling_std_3h": f(rstd[t], 3),
                    "anomaly_score": f(sc.at[t, "anomaly_score"], 1), "risk_score": f(sc.at[t, "risk_score"], 1),
                    "risk_category": sc.at[t, "risk_category"]})
    return out


@lru_cache(maxsize=1)
def _long():
    return pd.read_csv(get_settings().processed_dir / "scada_long.csv", low_memory=False, usecols=["substation", "timestamp", "parameter", "raw_value"])


def _raw_cells(sheet: str, p: str) -> dict:
    d = _long()
    d = d[(d.substation == sheet) & (d.parameter == p)]
    return {r.timestamp: (None if pd.isna(r.raw_value) else str(r.raw_value)) for r in d.itertuples()}


@router.get("/explorer/export.csv", tags=["data"])
def export_csv(substation: str, parameter: str, request: Request, date: str | None = None, hour: int | None = Query(None, ge=1, le=24),
               user: dict = Depends(require("VIEWER"))):
    rows = _explorer_rows(substation, parameter, date, hour)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["timestamp"])
    w.writeheader()
    w.writerows(rows)
    audit(request, user["sub"], "data.export", {"substation": substation, "parameter": parameter, "rows": len(rows)})
    name = f"{substation}_{''.join(c if c.isalnum() else '_' for c in short_name(parameter))[:40]}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/parameters", tags=["data"], dependencies=viewer)
def parameters(substation: str | None = None, q: str | None = None, page: int = Query(1, ge=1), size: int = Query(100, ge=1, le=500)):
    d = store().dictionary
    if substation:
        d = d[d.substation == sub_or_404(substation)["sheet"]]
    if q:
        d = d[d.parameter.str.contains(q, case=False, regex=False)]
    return {"total": len(d), "items": d.iloc[(page - 1) * size: page * size].fillna("").to_dict(orient="records")}


# ------------------------------------------------------------------------------------------- model lab
@router.get("/models", tags=["models"], dependencies=viewer)
def models():
    st = store()
    lat = st.latency_ms
    sc = st.scored
    comp = {k: {"mean": f(sc[f"{k}_score"].mean(), 1), "p90": f(sc[f"{k}_score"].quantile(.9), 1)} for k in ("iforest", "autoencoder", "temporal_ae")}
    return {"ensemble": {k: v for k, v in st.registry["ensemble"].items() if k != "artifacts"},
            "artifacts": st.registry["ensemble"]["artifacts"], "models": st.registry["models"],
            "raw_files": st.registry.get("raw_files", []),
            "inference_latency_ms": {"p50": f(np.percentile(lat, 50), 2) if lat else None,
                                     "p95": f(np.percentile(lat, 95), 2) if lat else None, "samples": len(lat)},
            "anomaly_distribution": dict(zip(["counts", "edges"], [x.tolist() for x in np.histogram(sc.anomaly_score, bins=10, range=(0, 100))])),
            "component_score_summary": comp, "evaluation": st.evaluation, "benchmarks": st.benchmarks,
            "evaluation_mode": "Unsupervised evaluation — no fault labels in Dataset A", "categories": st.categories(),
            "risk_note": RISK_NOTE, "disclaimer": DISCLAIMER}


# ------------------------------------------------------------------------------------------- replay
class ReplayStart(BaseModel):
    date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    speed: int | None = Field(None, ge=1, le=10)
    reset: bool = False


class Speed(BaseModel):
    speed: int = Field(ge=1, le=10)


class Seek(BaseModel):
    timestamp: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$")


@router.get("/replay/status", tags=["replay"], dependencies=viewer)
def replay_status():
    return replay().status()


@router.post("/replay/start", tags=["replay"])
async def replay_start(request: Request, body: ReplayStart | None = None, user: dict = Depends(require("OPERATOR"))):
    b = body or ReplayStart()
    audit(request, user["sub"], "replay.start", b.model_dump())
    return await replay().start(date=b.date, speed=b.speed, reset=b.reset)


@router.post("/replay/pause", tags=["replay"], dependencies=[Depends(require("OPERATOR"))])
def replay_pause():
    return replay().pause()


@router.post("/replay/stop", tags=["replay"], dependencies=[Depends(require("OPERATOR"))])
def replay_stop():
    return replay().stop()


@router.post("/replay/next", tags=["replay"], dependencies=[Depends(require("OPERATOR"))])
def replay_next():
    return replay().next()


@router.post("/replay/speed", tags=["replay"], dependencies=[Depends(require("OPERATOR"))])
def replay_speed(body: Speed):
    return replay().set_speed(body.speed)


@router.post("/replay/seek", tags=["replay"], dependencies=[Depends(require("OPERATOR"))])
def replay_seek(body: Seek):
    return replay().seek(body.timestamp if len(body.timestamp) == 19 else body.timestamp + ":00")
