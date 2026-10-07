"""Alert notifications: RFC 8291 encryption, VAPID signing, subscription API and audience filtering."""
import hashlib
import hmac
import struct

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.services import push


def _browser_keys():
    k = ec.generate_private_key(ec.SECP256R1())
    return k, push.b64u(push._raw_public(k)), push.b64u(b"0123456789abcdef")


def _decrypt(body: bytes, ua_key, auth_b64: str) -> bytes:
    """What the browser does (RFC 8291 §3.4) — independent of push.encrypt's helpers."""
    salt, rs, idlen = body[:16], *struct.unpack("!IB", body[16:21])
    as_public, ct = body[21:21 + idlen], body[21 + idlen:]
    assert rs == 4096 and idlen == 65
    ua_public = push._raw_public(ua_key)
    shared = ua_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))

    def hkdf(salt_, ikm, info, n):
        prk = hmac.new(salt_, ikm, hashlib.sha256).digest()
        return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:n]
    ikm = hkdf(push.ub64u(auth_b64), shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    pt = AESGCM(hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)).decrypt(hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12), ct, None)
    assert pt.endswith(b"\x02")
    return pt[:-1]


def test_encrypt_roundtrip():
    ua_key, p256dh, auth = _browser_keys()
    msg = '{"title":"उच्च जोखिम · 220 kV Sector-46"}'.encode()
    assert _decrypt(push.encrypt(msg, p256dh, auth), ua_key, auth) == msg


def test_rfc8291_vector():
    # RFC 8291 Appendix A test vector
    ua_priv = push._key_from_scalar(push.ub64u("q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"))
    as_priv = push._key_from_scalar(push.ub64u("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"))
    body = push.encrypt(b"When I grow up, I want to be a watermelon",
                        "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
                        "BTBZMqHH6r4Tts7J_aSIgg", salt=push.ub64u("DGv6ra1nlYgDCS1FRnbzlw"), server_key=as_priv)
    expected = ("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_"
                "yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")
    assert push.b64u(body) == expected
    assert _decrypt(body, ua_priv, "BTBZMqHH6r4Tts7J_aSIgg") == b"When I grow up, I want to be a watermelon"


def test_vapid_header_is_valid_es256(client):
    h = push.vapid_header("https://fcm.googleapis.com/fcm/send/abc")
    token = h.split("t=")[1].split(",")[0]
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.ub64u(push.public_key_b64()))
    claims = jwt.decode(token, pub, algorithms=["ES256"], audience="https://fcm.googleapis.com")
    assert claims["sub"].startswith("mailto:")


@pytest.mark.parametrize("url, ok", [
    ("https://fcm.googleapis.com/fcm/send/x", True), ("https://web.push.apple.com/QG", True),
    ("https://updates.push.services.mozilla.com/wpush/v2/x", True), ("https://wns2-bn3p.notify.windows.com/w/?token=x", True),
    ("http://fcm.googleapis.com/x", False), ("https://evil.example/fcm.googleapis.com", False),
    ("https://fcm.googleapis.com.evil.example/x", False), ("https://169.254.169.254/latest", False),
])
def test_endpoint_allowlist(url, ok):
    assert push.endpoint_allowed(url) is ok


def test_audience_filter():
    assert push.wants("HIGH RISK", "CRITICAL") and push.wants("HIGH RISK", "HIGH RISK")
    assert not push.wants("HIGH RISK", "WARNING") and push.wants("WARNING", "WARNING")
    assert not push.wants("CRITICAL", "HIGH RISK")


def test_alert_message_localised():
    a = {"risk_category": "HIGH RISK", "substation_name": "220 kV Sector-46", "substation_id": "220-sec-46",
         "parameter_label": "Bus voltage collapse or missing reading", "risk_score": 86.7, "record_ts": "2026-02-02T10:00:00"}
    en, hi = push.alert_message(a, "en"), push.alert_message(a, "hi")
    assert en["title"] == "HIGH RISK · 220 kV Sector-46" and "Potential abnormal operating condition" in en["body"]
    assert hi["title"] != en["title"] and "220 kV Sector-46" in hi["body"] and "87/100" in hi["body"]
    assert en["url"] == "/mobile/?inv=220-sec-46|2026-02-02T10:00:00"


def test_subscription_api(client, op, monkeypatch):
    _, p256dh, auth = _browser_keys()
    sub = {"endpoint": "https://fcm.googleapis.com/fcm/send/test-device-1", "keys": {"p256dh": p256dh, "auth": auth},
           "min_category": "HIGH RISK", "lang": "hi"}
    assert client.post("/api/v1/push/subscribe", json=sub).status_code == 401
    bad = {**sub, "endpoint": "https://attacker.example/collect"}
    assert client.post("/api/v1/push/subscribe", json=bad, headers=op).status_code == 422
    assert client.post("/api/v1/push/subscribe", json=sub, headers=op).json()["ok"]
    cfg = client.get("/api/v1/push/config", headers=op).json()
    assert len(push.ub64u(cfg["public_key"])) == 65 and cfg["devices"][0]["min_category"] == "HIGH RISK"
    sent = []
    monkeypatch.setattr(push, "send", lambda s, m, ttl=3600: sent.append(m) or 201)
    r = client.post("/api/v1/push/test", headers=op).json()
    assert r["sent"] == 1 and sent[0]["category"] == "TEST"
    monkeypatch.setattr(push, "send", lambda s, m, ttl=3600: 410)       # user revoked permission
    assert client.post("/api/v1/push/test", headers=op).json()["removed"] == 1
    assert client.get("/api/v1/push/config", headers=op).json()["devices"] == []
    client.post("/api/v1/push/subscribe", json=sub, headers=op)
    assert client.post("/api/v1/push/unsubscribe", json={"endpoint": sub["endpoint"]}, headers=op).json()["ok"]
    assert client.get("/api/v1/push/config", headers=op).json()["devices"] == []


def test_replay_alert_triggers_push(client, op, monkeypatch):
    from app.services import replay as replay_mod
    got = []
    monkeypatch.setattr(replay_mod.push, "notify_alert", lambda row: got.append(row))
    client.post("/api/v1/replay/stop", headers=op)
    for _ in range(30):                                   # step through the synthetic day until an alert is raised
        st = client.post("/api/v1/replay/next", headers=op).json()
        if got or st.get("mode") == "FINISHED":
            break
    alerts = client.get("/api/v1/alerts", headers=op).json()["items"]
    assert got, "the synthetic day should raise at least one replay alert"
    assert {a["id"] for a in alerts} >= {r["id"] for r in got}
    for row in got:
        assert row["risk_category"] in push.CATEGORY_ORDER and "id" in row
