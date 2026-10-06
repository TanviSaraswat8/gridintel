"""Relational schema (PostgreSQL in production, SQLite for local dev/tests). Migrations: backend/migrations."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="VIEWER")
    display_name: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))        # real_world_validation | public_benchmark
    license: Mapped[str | None] = mapped_column(String(128))
    url: Mapped[str | None] = mapped_column(Text)
    records: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict | None] = mapped_column(JSON)


class Substation(Base):
    __tablename__ = "substations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sheet: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    voltage_class_kv: Mapped[int] = mapped_column(Integer)
    data_status: Mapped[str] = mapped_column(String(32))  # AVAILABLE | NO SOURCE READINGS
    records: Mapped[int] = mapped_column(Integer, default=0)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("data_sources.id"))


class Equipment(Base):
    __tablename__ = "equipment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    substation_id: Mapped[str] = mapped_column(ForeignKey("substations.id"), index=True)
    tag: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))        # bus | transformer | feeder | coupler
    voltage_kv: Mapped[float | None] = mapped_column(Float)
    rating_mva: Mapped[float | None] = mapped_column(Float)
    parameters: Mapped[list | None] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("substation_id", "tag", "kind", name="uq_equipment"),)


class ScadaReading(Base):
    __tablename__ = "scada_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    substation_id: Mapped[str] = mapped_column(ForeignKey("substations.id"))
    ts: Mapped[str] = mapped_column(String(19))           # ISO local timestamp from the log sheet
    parameter: Mapped[str] = mapped_column(Text)
    raw_value: Mapped[str | None] = mapped_column(String(64))
    value: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(String(16))
    source_file: Mapped[str | None] = mapped_column(String(128))
    __table_args__ = (Index("ix_readings_sub_ts", "substation_id", "ts"),)


class FeatureRow(Base):
    __tablename__ = "features"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    substation_id: Mapped[str] = mapped_column(ForeignKey("substations.id"))
    ts: Mapped[str] = mapped_column(String(19))
    model_key: Mapped[str] = mapped_column(String(32))
    values: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (Index("ix_features_sub_ts", "substation_id", "ts"),)


class Anomaly(Base):
    __tablename__ = "anomalies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    substation_id: Mapped[str] = mapped_column(ForeignKey("substations.id"))
    ts: Mapped[str] = mapped_column(String(19))
    anomaly_score: Mapped[float] = mapped_column(Float)
    risk_score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    risk_category: Mapped[str] = mapped_column(String(16))
    components: Mapped[dict | None] = mapped_column(JSON)
    rules: Mapped[list | None] = mapped_column(JSON)
    model_key: Mapped[str | None] = mapped_column(String(32))
    evaluation: Mapped[str | None] = mapped_column(String(32))
    __table_args__ = (UniqueConstraint("substation_id", "ts", name="uq_anomaly"), Index("ix_anom_risk", "risk_score"))


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    substation_id: Mapped[str] = mapped_column(ForeignKey("substations.id"), index=True)
    substation_name: Mapped[str] = mapped_column(String(128))
    record_ts: Mapped[str] = mapped_column(String(19))
    risk_score: Mapped[float] = mapped_column(Float)
    risk_category: Mapped[str] = mapped_column(String(16))
    anomaly_score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    parameter: Mapped[str | None] = mapped_column(Text)
    parameter_label: Mapped[str | None] = mapped_column(Text)
    equipment: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    signals: Mapped[list | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(24), default="HISTORICAL_REPLAY")
    acknowledged_by: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("substation_id", "record_ts", name="uq_alert_record"),)


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    substation_id: Mapped[str] = mapped_column(ForeignKey("substations.id"))
    record_ts: Mapped[str] = mapped_column(String(19))
    author: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="OPEN")   # OPEN | REVIEWED | DISMISSED
    note: Mapped[str] = mapped_column(Text)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[str | None] = mapped_column(String(40))
    dataset: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict | None] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_version"),)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
