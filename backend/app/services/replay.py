"""Historical SCADA replay engine — feeds logged hourly records through the ensemble one timestamp at a time.
Explicitly a REPLAY of supplied historical data; live ingestion is not connected."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from sqlalchemy import select

from pipeline.ensemble import ALERT_CATEGORIES

from ..core.cache import set_json
from ..core.config import get_settings
from ..core.observability import ALERTS_RAISED, REPLAY_CURSOR
from ..db.models import Alert
from ..db.session import session_scope
from . import push
from .store import Store, short_name

SPEEDS = (1, 2, 5, 10)
log = logging.getLogger("gridintel.replay")


class ReplayEngine:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.timeline = store.timeline
        self.cursor = 0
        self.mode = "IDLE"            # IDLE | RUNNING | PAUSED | STOPPED | FINISHED
        self.speed = 1
        self.started_at: str | None = None
        self.processed: set[int] = set()
        self.events: list[dict] = []
        self._task: asyncio.Task | None = None

    @property
    def current_ts(self) -> str:
        return self.timeline[self.cursor]

    def status(self) -> dict:
        st = {"mode": self.mode, "data_mode": "HISTORICAL REPLAY", "live_ingestion": "NOT CONNECTED",
              "speed": self.speed, "speeds": list(SPEEDS), "cursor": self.cursor, "total": len(self.timeline),
              "timestamp": self.current_ts, "first_timestamp": self.timeline[0], "last_timestamp": self.timeline[-1],
              "dates": sorted({t[:10] for t in self.timeline}),
              "interval_seconds": round(get_settings().replay_base_interval_sec / self.speed, 2),
              "started_at": self.started_at, "recent_events": self.events[-12:],
              "label": "Historical SCADA replay — HVPNL Faridabad daily logs (not a live feed)"}
        set_json("replay:status", {k: st[k] for k in ("mode", "cursor", "timestamp", "speed")})
        REPLAY_CURSOR.set(self.cursor)
        return st

    def process(self, i: int) -> list[dict]:
        if i in self.processed:
            return []
        self.processed.add(i)
        ts = self.timeline[i]
        raised = []
        for s in self.store.substations:
            sid = s["id"]
            if not s.get("has_model") or ts not in self.store.values[sid].index:
                continue
            r = self.store.infer(sid, ts)
            if r["risk_category"] not in ALERT_CATEGORIES or r["risk_score"] < get_settings().alert_min_risk:
                continue
            sigs = self.store.explain(sid, ts)
            top = self.store.primary_signal(sid, sigs, r["rules"])
            base = top.get("base_parameter")
            label = r["rules"][0]["title"] if r["rules"] else top.get("label")
            row = {"substation_id": sid, "substation_name": s["name"], "record_ts": ts, "risk_score": r["risk_score"],
                   "risk_category": r["risk_category"], "anomaly_score": r["anomaly_score"], "confidence": r["confidence"],
                   "parameter": base, "parameter_label": label,
                   "equipment": self.store.meta(base).get("transformer") if base in self.store.param_meta else None,
                   "message": f"Potential abnormal operating condition detected at {s['name']}.",
                   "signals": [{"label": x["label"], "level": x["level"], "value": x["value"], "unit": x.get("unit")} for x in sigs[:4]],
                   "source": "HISTORICAL_REPLAY"}
            with session_scope() as db:
                exists = db.execute(select(Alert.id).where(Alert.substation_id == sid, Alert.record_ts == ts)).first()
                if exists:
                    continue
                a = Alert(**row)
                db.add(a)
                db.flush()
                row["id"] = a.id
            ALERTS_RAISED.labels(r["risk_category"]).inc()
            raised.append(row)
            push.notify_alert(row)             # phones that opted in get it even with the app closed
            self.events.append({"type": "ALERT", "alert_id": row["id"], "substation_id": sid, "substation_name": s["name"],
                                "timestamp": ts, "risk_category": r["risk_category"], "risk_score": r["risk_score"],
                                "confidence": r["confidence"], "message": row["message"], "parameter_label": label,
                                "equipment": row["equipment"]})
            log.info("alert raised", extra={"event": "alert", "detail": {"sub": sid, "ts": ts, "risk": r["risk_score"]}})
        self.events = self.events[-60:]
        return raised

    async def _loop(self) -> None:
        try:
            while self.mode == "RUNNING":
                await asyncio.sleep(get_settings().replay_base_interval_sec / self.speed)
                if self.mode != "RUNNING":
                    break
                if self.cursor >= len(self.timeline) - 1:
                    self.mode = "FINISHED"
                    break
                self.cursor += 1
                await asyncio.to_thread(self.process, self.cursor)
        except asyncio.CancelledError:  # pragma: no cover
            pass

    def _reset(self, date: str | None):
        with session_scope() as db:
            db.query(Alert).delete()
        self.processed.clear()
        self.events.clear()
        self.cursor = next((i for i, t in enumerate(self.timeline) if date and t.startswith(date)), 0)
        self.started_at = dt.datetime.now().isoformat(timespec="seconds")

    async def start(self, date: str | None = None, speed: int | None = None, reset: bool = False) -> dict:
        if speed:
            self.set_speed(speed)
        if self.mode in ("IDLE", "STOPPED", "FINISHED") or reset or date:
            self._reset(date)
            self.process(self.cursor)
        self.mode = "RUNNING"
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._loop())
        return self.status()

    def pause(self) -> dict:
        if self.mode == "RUNNING":
            self.mode = "PAUSED"
        return self.status()

    def stop(self) -> dict:
        self.mode = "STOPPED"
        self.cursor = 0
        return self.status()

    def next(self) -> dict:
        if self.mode in ("IDLE", "STOPPED", "FINISHED") and not self.processed:
            self.started_at = dt.datetime.now().isoformat(timespec="seconds")
            self.process(self.cursor)
        elif self.cursor < len(self.timeline) - 1:
            self.cursor += 1
            self.process(self.cursor)
        self.mode = "PAUSED" if self.mode != "FINISHED" else self.mode
        return self.status()

    def seek(self, timestamp: str) -> dict:
        idx = [i for i, t in enumerate(self.timeline) if t >= timestamp]
        self.cursor = idx[0] if idx else len(self.timeline) - 1
        self.process(self.cursor)
        if self.mode in ("IDLE", "STOPPED", "FINISHED"):
            self.mode = "PAUSED"
        return self.status()

    def set_speed(self, speed: int) -> dict:
        self.speed = speed if speed in SPEEDS else 1
        return self.status()


__all__ = ["ReplayEngine", "SPEEDS", "short_name"]
