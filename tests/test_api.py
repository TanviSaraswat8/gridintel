"""API, security and service tests (FastAPI TestClient over the synthetic-fixture models)."""
import time

import jwt
import pytest

from app.core.security import hash_password, verify_password

SID = "220-test-a"


def test_health_ready_metrics(client):
    assert client.get("/health").json()["status"] == "ok"
    r = client.get("/ready").json()
    assert r["ready"] and r["checks"]["database"] and r["checks"]["model_store"]
    m = client.get("/metrics")
    assert m.status_code == 200 and "gridintel_http_requests_total" in m.text


def test_security_headers_and_request_id(client):
    r = client.get("/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"


def test_auth_required_and_login(client):
    assert client.get("/api/v1/substations").status_code == 401
    bad = client.post("/api/v1/auth/login", json={"username": "operator", "password": "wrong"})
    assert bad.status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "bad user!", "password": "x"}).status_code == 422
    assert client.get("/api/v1/substations", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_expired_token_rejected(client):
    tok = jwt.encode({"sub": "operator", "role": "OPERATOR", "exp": int(time.time()) - 10, "iss": "gridintel"}, "test-only-secret", algorithm="HS256")
    r = client.get("/api/v1/substations", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401 and "expired" in r.json()["detail"].lower()


def test_password_hashing():
    h = hash_password("s3cret")
    assert h.startswith("pbkdf2_sha256$") and "s3cret" not in h
    assert verify_password("s3cret", h) and not verify_password("nope", h) and not verify_password("x", "garbage")


def test_rbac(client, viewer, op, admin):
    assert client.post("/api/v1/replay/next", headers=viewer).status_code == 403
    assert client.get("/api/v1/auth/audit", headers=op).status_code == 403
    assert client.get("/api/v1/auth/audit", headers=admin).status_code == 200
    assert client.get("/api/v1/auth/me", headers=viewer).json()["role"] == "VIEWER"


def test_substations_and_no_data(client, op):
    d = client.get("/api/v1/substations", headers=op).json()
    ids = {s["id"]: s for s in d["items"]}
    assert ids[SID]["has_model"] and ids["66-blank"]["data_status"] == "NO SOURCE READINGS"
    assert client.get("/api/v1/scada/latest", params={"substation": "66-blank"}, headers=op).status_code == 409
    assert client.get("/api/v1/substations/does-not-exist", headers=op).status_code == 404
    assert client.get("/api/v1/scada/record", params={"substation": SID, "timestamp": "2030-01-01T01:00:00"}, headers=op).status_code == 404


def test_replay_raises_alert_and_investigation(client, op):
    client.post("/api/v1/replay/stop", headers=op)
    assert client.post("/api/v1/replay/seek", json={"timestamp": "not-a-time"}, headers=op).status_code == 422
    client.post("/api/v1/replay/seek", json={"timestamp": "2026-02-02T09:00:00"}, headers=op)
    st = client.post("/api/v1/replay/next", headers=op).json()
    assert st["timestamp"] == "2026-02-02T10:00:00" and st["data_mode"] == "HISTORICAL REPLAY" and st["live_ingestion"] == "NOT CONNECTED"
    alerts = client.get("/api/v1/alerts", params={"substation": SID}, headers=op).json()["items"]
    assert any(a["record_timestamp"] == "2026-02-02T10:00:00" for a in alerts)
    inv = client.get("/api/v1/investigations", params={"substation": SID, "timestamp": "2026-02-02T10:00:00"}, headers=op).json()
    for k in ("what", "why", "how_unusual", "investigate", "contributing_signals", "evidence", "confidence", "risk_category", "trend"):
        assert k in inv
    assert inv["title"] == "ANOMALY DETECTED" and "11 kV T-I" in inv["affected_parameter"] and inv["current_value"] == 0
    text = str(inv).lower()
    assert "will definitely" not in text and "caused the fault" not in text and "not confirmed causes" in text
    assert client.post("/api/v1/replay/speed", json={"speed": 5}, headers=op).json()["speed"] == 5
    assert client.post("/api/v1/replay/pause", headers=op).status_code == 200


def test_replay_start_async(client, op):
    st = client.post("/api/v1/replay/start", json={"date": "2026-02-10", "speed": 10}, headers=op).json()
    assert st["mode"] == "RUNNING" and st["timestamp"].startswith("2026-02-10")
    client.post("/api/v1/replay/pause", headers=op)


def test_topology_and_command_center(client, op):
    t = client.get(f"/api/v1/substations/{SID}/topology", params={"timestamp": "2026-02-10T08:00:00"}, headers=op).json()
    assert t["available"] and t["transformers"] and t["buses"] and t["feeders"]
    cc = client.get("/api/v1/command-center", headers=op).json()
    assert cc["model_status"] == "ONLINE" and cc["sheets_total"] == 2 and "grid_health" in cc


def test_analytics_fleet_models_explorer(client, op, eng):
    a = client.get("/api/v1/analytics", params={"substation": SID}, headers=op).json()
    assert sum(a["risk_distribution"].values()) == 72
    assert client.get("/api/v1/analytics", params={"substation": SID, "parameter": "nope"}, headers=op).status_code == 422
    f = client.get("/api/v1/fleet", params={"sort": "loading"}, headers=op).json()
    assert f["items"][-1]["data_status"] == "NO SOURCE READINGS"
    assert client.get("/api/v1/fleet", params={"sort": "bogus"}, headers=op).status_code == 422
    m = client.get("/api/v1/models", headers=op).json()
    assert m["evaluation_mode"].startswith("Unsupervised") and m["models"]["supervised"]["status"] == "not trained"
    p = "VOLTAGE | 11 kV T-I"
    ex = client.get("/api/v1/explorer", params={"substation": SID, "parameter": p, "date": "2026-02-02"}, headers=op).json()
    assert ex["total"] == 24 and {"raw_value", "cleaned_value", "rolling_mean_3h", "anomaly_score"} <= set(ex["items"][0])
    csv = client.get("/api/v1/explorer/export.csv", params={"substation": SID, "parameter": p}, headers=op)
    assert csv.status_code == 200 and csv.text.startswith("timestamp,")
    assert client.get("/api/v1/explorer", params={"substation": SID, "parameter": "bogus"}, headers=op).status_code == 422
    an = client.get("/api/v1/anomalies", params={"min_risk": 0, "size": 5}, headers=op).json()
    assert an["total"] == 72 and len(an["items"]) == 5
    assert client.get("/api/v1/parameters", params={"substation": SID, "q": "VOLTAGE"}, headers=op).json()["total"] >= 3


def test_notes_and_ack(client, op, eng, viewer):
    body = {"substation": SID, "timestamp": "2026-02-02T10:00:00", "note": "Checked with shift log.", "status": "REVIEWED"}
    assert client.post("/api/v1/investigations/notes", json=body, headers=op).status_code == 403
    assert client.post("/api/v1/investigations/notes", json=body, headers=eng).status_code == 200
    assert client.post("/api/v1/investigations/notes", json={**body, "status": "BAD"}, headers=eng).status_code == 422
    alerts = client.get("/api/v1/alerts", headers=op).json()["items"]
    if alerts:
        assert client.post(f"/api/v1/alerts/{alerts[0]['id']}/acknowledge", headers=op).json()["ok"]
        assert client.post(f"/api/v1/alerts/{alerts[0]['id']}/acknowledge", headers=viewer).status_code == 403
    assert client.post("/api/v1/alerts/999999/acknowledge", headers=op).status_code == 404


def test_public_stats_and_static(client):
    s = client.get("/api/v1/public/stats").json()
    assert s["substations_monitored"] == 1 and "disclaimer" in s
    assert client.get("/").status_code == 200 and client.get("/app").status_code == 200
    assert "GRIDINTEL_CONFIG" in client.get("/config.js").text


def test_login_rate_limit(client):
    codes = [client.post("/api/v1/auth/login", json={"username": "x", "password": "y"}).status_code for _ in range(60)]
    assert 429 in codes


@pytest.mark.parametrize("path", ["/api/v1/demo-not-real", "/api/v1/investigations?substation=220-test-a"])
def test_errors_are_structured(client, op, path):
    r = client.get(path, headers=op)
    assert r.status_code in (404, 422) and "request_id" in r.json()


def test_every_replay_control_is_audited(client, op, admin):
    client.post("/api/v1/replay/stop", headers=op)
    client.post("/api/v1/replay/seek", json={"timestamp": "2026-02-02T03:00"}, headers=op)
    client.post("/api/v1/replay/next", headers=op)
    client.post("/api/v1/replay/speed", json={"speed": 5}, headers=op)
    client.post("/api/v1/replay/pause", headers=op)
    rows = client.get("/api/v1/auth/audit", headers=admin).json()
    rows = rows.get("items", rows) if isinstance(rows, dict) else rows
    actions = {r["action"] for r in rows}
    assert {"replay.stop", "replay.seek", "replay.next", "replay.speed", "replay.pause"} <= actions


def test_docs_csp_allows_swagger_but_app_stays_strict(client):
    docs = client.get("/docs").headers["content-security-policy"]
    assert "https://cdn.jsdelivr.net" in docs and "'unsafe-inline'" in docs.split("script-src")[1].split(";")[0]
    app_csp = client.get("/app").headers["content-security-policy"]
    assert "script-src 'self';" in app_csp and "jsdelivr" not in app_csp


def test_health_reports_demo_login_setting(client):
    assert isinstance(client.get("/health").json()["demo_logins"], bool)
