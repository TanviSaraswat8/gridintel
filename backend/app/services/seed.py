"""Idempotent database seeding from pipeline artifacts + environment-configured users."""
from __future__ import annotations

import json
import logging

import pandas as pd
import yaml
from sqlalchemy import func, select

from ..core.config import ROOT, get_settings
from ..core.security import hash_password
from ..db.models import Anomaly, DataSource, Equipment, ModelVersion, ScadaReading, Substation, User
from ..db.session import session_scope
from .store import Store

log = logging.getLogger("gridintel.seed")
DEMO_USERS = [("operator", "hvpnl2026", "OPERATOR", "Demo Operator"),
              ("engineer", "hvpnl2026", "ENGINEER", "Demo Engineer"),
              ("viewer", "hvpnl2026", "VIEWER", "Demo Viewer")]


def seed_users() -> None:
    s = get_settings()
    with session_scope() as db:
        have = {u for (u,) in db.execute(select(User.username))}
        if s.demo_users_enabled:
            for u, p, r, n in DEMO_USERS:
                if u not in have:
                    db.add(User(username=u, password_hash=hash_password(p), role=r, display_name=n, is_demo=True))
        if s.admin_username and s.admin_password and s.admin_username not in have:
            db.add(User(username=s.admin_username, password_hash=hash_password(s.admin_password), role="ADMIN", display_name="Administrator"))


def seed_reference(store: Store) -> None:
    with session_scope() as db:
        if db.scalar(select(func.count()).select_from(Substation)):
            return
        reg = ROOT / "data" / "sources" / "dataset_registry.yaml"
        sources = yaml.safe_load(reg.read_text(encoding="utf-8"))["datasets"] if reg.exists() else []
        for d in sources:
            db.add(DataSource(id=d["id"], name=d["name"], role=d.get("role", ""), license=d.get("license"), url=d.get("url"),
                              records=d.get("records") if isinstance(d.get("records"), int) else None, details=d))
        db.flush()
        hv = next((d["id"] for d in sources if d.get("role") == "real_world_validation"), None)
        for s in store.substations:
            db.add(Substation(id=s["id"], sheet=s["sheet"], name=s["name"], voltage_class_kv=s["voltage_class_kv"],
                              data_status=s["data_status"], records=s["records"], source_id=hv))
        db.flush()
        for s in store.substations:
            if not s["has_model"]:
                continue
            t = s["topology"]
            used: dict[tuple, int] = {}

            def uniq(tag: str, kind: str) -> str:
                tag = tag[:56]
                n = used.get((tag, kind), 0)
                used[(tag, kind)] = n + 1
                return tag if n == 0 else f"{tag} #{n + 1}"
            for b in t["buses"]:
                db.add(Equipment(substation_id=s["id"], tag=uniq(b["tag"], "bus"), kind="bus", voltage_kv=b["voltage_kv"], parameters=b["params"]))
            for x in t["transformers"]:
                db.add(Equipment(substation_id=s["id"], tag=uniq(x["tag"], "transformer"), kind="transformer", voltage_kv=x["hv_kv"],
                                 rating_mva=x.get("rating_mva"), parameters=x["params"]))
            for x in t["feeders"]:
                db.add(Equipment(substation_id=s["id"], tag=uniq(x["tag"], "feeder"), kind="feeder", voltage_kv=x["voltage_kv"], parameters=[x["parameter"]]))
            for x in t["couplers"]:
                db.add(Equipment(substation_id=s["id"], tag=uniq(x["tag"], "coupler"), kind="coupler", voltage_kv=x["voltage_kv"], parameters=[x["parameter"]]))
        long = pd.read_csv(store.s.processed_dir / "scada_long.csv", low_memory=False)
        ids = {s["sheet"]: s["id"] for s in store.substations if s["has_model"]}
        long = long[long.substation.isin(ids)]
        rows = [{"substation_id": ids[r.substation], "ts": r.timestamp, "parameter": r.parameter,
                 "raw_value": None if pd.isna(r.raw_value) else str(r.raw_value)[:64],
                 "value": None if pd.isna(r.value) else float(r.value), "status": None if pd.isna(r.status) else r.status,
                 "source_file": r.source_file} for r in long.itertuples()]
        db.bulk_insert_mappings(ScadaReading, rows)
        an = [{"substation_id": store.by_sheet[r.substation]["id"], "ts": r.timestamp, "anomaly_score": r.anomaly_score,
               "risk_score": r.risk_score, "confidence": r.confidence, "risk_category": r.risk_category,
               "components": {"iforest": r.iforest_score, "autoencoder": r.autoencoder_score, "temporal_ae": r.temporal_ae_score},
               "rules": r.rules, "model_key": r.model_key, "evaluation": r.evaluation} for r in store.scored.itertuples()]
        db.bulk_insert_mappings(Anomaly, an)
        for name, m in store.registry["models"].items():
            db.add(ModelVersion(name=name, version=str(m.get("version", "-")), status=m.get("status", ""),
                                created_at=m.get("created_at"), dataset=m.get("dataset"), details=json.loads(json.dumps(m, default=str))))
        log.info("seeded", extra={"event": "seed", "detail": {"readings": len(rows), "anomalies": len(an)}})
