"""Substations, SCADA records, topology (digital substation), command-center summary, public stats."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from ...core.config import DISCLAIMER, RISK_NOTE, get_settings
from ...core.security import require
from ...db.models import Alert
from ...db.session import session_scope
from ..deps import replay, store, sub_or_404, sub_with_data, ts_or_404

router = APIRouter(tags=["grid"])
viewer = [Depends(require("VIEWER"))]


def _current(sid: str, full: bool = False):
    ts = store().latest_ts(sid, replay().current_ts)
    return store().snapshot(sid, ts, with_groups=full) if ts else None


@router.get("/public/stats", tags=["public"])
def public_stats():
    """Unauthenticated, aggregate-only statistics for the landing page (no measurements)."""
    st = store()
    with_data = [s for s in st.substations if s["has_model"]]
    return {"product": "GridIntel", "substations_monitored": len(with_data), "sheets_in_source": len(st.substations),
            "hourly_records": int(len(st.scored)), "parameters_ingested": int(len(st.dictionary)),
            "models": ["Isolation Forest", "Dense autoencoder", "Temporal-window autoencoder", "Engineering rules"],
            "validation": "Leave-one-day-out on HVPNL Faridabad records", "replay_mode": replay().mode,
            "disclaimer": DISCLAIMER}


@router.get("/substations", dependencies=viewer)
def substations():
    out = []
    for s in store().substations:
        b = store().brief(s)
        if s["has_model"]:
            cur = _current(s["id"])
            if cur and cur.get("available"):
                b.update({k: cur[k] for k in ("timestamp", "risk_score", "risk_category", "anomaly_score", "confidence")})
                b["cards"] = {k: cur["cards"][k] for k in ("voltage", "transformer_load", "transformer_temperature")}
                b["health"] = store().health(s["id"], cur["timestamp"])
        out.append(b)
    out.sort(key=lambda b: (not b["has_model"], b["id"] != get_settings().primary_substation, -b["voltage_class_kv"], b["name"]))
    return {"primary": get_settings().primary_substation, "items": out}


@router.get("/substations/{sid}", dependencies=viewer)
def substation(sid: str):
    s = sub_or_404(sid)
    if not s["has_model"]:
        return {"substation": store().brief(s), "available": False}
    with session_scope() as db:
        alerts = db.execute(select(Alert).where(Alert.substation_id == sid).order_by(Alert.id.desc()).limit(20)).scalars().all()
        al = [_alert(a) for a in alerts]
    return {"substation": store().brief(s), "available": True, "current": _current(sid, full=True),
            "series": store().series(sid, upto=replay().current_ts), "alerts": al,
            "transformers": [t["tag"] for t in s["topology"]["transformers"]]}


@router.get("/substations/{sid}/topology", dependencies=viewer)
def topology(sid: str, timestamp: str | None = None):
    sub_with_data(sid)
    ts = ts_or_404(sid, timestamp) if timestamp else store().latest_ts(sid, replay().current_ts)
    if ts is None:
        return {"available": False}
    return {"available": True, **store().topology(sid, ts)}


@router.get("/scada/latest", dependencies=viewer)
def scada_latest(substation: str = Query(default=None)):
    sid = substation or get_settings().primary_substation
    sub_with_data(sid)
    return {"replay": replay().status(), "record": _current(sid, full=True)}


@router.get("/scada/record", dependencies=viewer)
def scada_record(substation: str, timestamp: str):
    sub_with_data(substation)
    return store().snapshot(substation, ts_or_404(substation, timestamp))


@router.get("/scada/history", dependencies=viewer)
def scada_history(substation: str, start: str | None = None, end: str | None = None, upto_cursor: bool = False,
                  last: int | None = Query(default=None, ge=1, le=500), params: list[str] | None = Query(default=None)):
    sub_with_data(substation)
    return store().series(substation, upto=replay().current_ts if upto_cursor else None, start=start, end=end, last=last, params=params)


def _alert(a: Alert) -> dict:
    return {"id": a.id, "created_at": a.created_at.isoformat() if a.created_at else None, "substation_id": a.substation_id,
            "substation_name": a.substation_name, "record_timestamp": a.record_ts, "risk_score": a.risk_score,
            "risk_category": a.risk_category, "anomaly_score": a.anomaly_score, "confidence": a.confidence,
            "parameter": a.parameter, "parameter_label": a.parameter_label, "equipment": a.equipment, "message": a.message,
            "signals": a.signals, "source": a.source, "acknowledged_by": a.acknowledged_by}


@router.get("/command-center", dependencies=viewer)
def command_center():
    """First-screen summary: grid health, active substations, alerts, model status."""
    st = store()
    rows, cats = [], {}
    for s in st.substations:
        if not s["has_model"]:
            continue
        cur = _current(s["id"])
        if not cur or not cur.get("available"):
            rows.append({"substation_id": s["id"], "name": s["name"], "available": False})
            continue
        cats[cur["risk_category"]] = cats.get(cur["risk_category"], 0) + 1
        rows.append({"substation_id": s["id"], "name": s["name"], "available": True, "timestamp": cur["timestamp"],
                     "risk_score": cur["risk_score"], "risk_category": cur["risk_category"], "anomaly_score": cur["anomaly_score"],
                     "confidence": cur["confidence"], "voltage_class_kv": s["voltage_class_kv"],
                     "transformers": [t["tag"] for t in s["topology"]["transformers"]], "health": st.health(s["id"], cur["timestamp"])})
    live = [r for r in rows if r["available"]]
    with session_scope() as db:
        n_alerts = db.scalar(select(func.count()).select_from(Alert)) or 0
        n_high = db.scalar(select(func.count()).select_from(Alert).where(Alert.risk_category.in_(["HIGH RISK", "CRITICAL"]))) or 0
        recent = [_alert(a) for a in db.execute(select(Alert).order_by(Alert.id.desc()).limit(8)).scalars()]
    grid_health = round(100 - sum(r["risk_score"] for r in live) / len(live), 1) if live else None
    return {"grid_health": grid_health, "grid_health_note": "Grid health index = 100 − mean AI risk across substations with a record at the replay time.",
            "active_substations": len(live), "substations_with_data": len(rows), "sheets_total": len(st.substations),
            "active_alerts": n_alerts, "high_risk_events": n_high, "category_counts": cats,
            "model_status": "ONLINE", "model_version": st.registry["ensemble"]["name"], "replay": replay().status(),
            "substations": rows, "recent_alerts": recent, "risk_note": RISK_NOTE}
