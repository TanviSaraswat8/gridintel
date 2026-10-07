"""Web Push for alert notifications — standards-only, no third-party push SDK.

* Encryption: RFC 8291 (aes128gcm content coding, RFC 8188) with an ephemeral P-256 key per message.
* Sender identity: RFC 8292 VAPID (ES256 JWT). The key pair is generated once and kept in the database
  (``app_secrets``), or supplied as ``VAPID_PRIVATE_KEY`` (base64url raw 32-byte scalar).
* Delivery: HTTPS POST to the subscription endpoint, which must belong to a known browser push service
  (no arbitrary URLs — the server never POSTs to a host chosen by a client).

Notifications carry no measurements: substation, category, the rule/parameter label and the risk score.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select

from ..db.models import AppSecret, PushSubscription, utcnow
from ..db.session import session_scope

log = logging.getLogger("gridintel.push")

CATEGORY_ORDER = ["WARNING", "HIGH RISK", "CRITICAL"]
ALLOWED_PUSH_HOSTS = ("fcm.googleapis.com", "android.googleapis.com", "updates.push.services.mozilla.com",
                      ".push.services.mozilla.com", ".push.apple.com", ".notify.windows.com")
SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:alerts@gridintel.invalid")
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="push")
_vapid: ec.EllipticCurvePrivateKey | None = None


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def ub64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _raw_public(key: ec.EllipticCurvePrivateKey | ec.EllipticCurvePublicKey) -> bytes:
    pub = key.public_key() if isinstance(key, ec.EllipticCurvePrivateKey) else key
    return pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def _key_from_scalar(raw: bytes) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


def vapid_key() -> ec.EllipticCurvePrivateKey:
    """The server's VAPID key: env var, else the one stored in the database, else a new one (stored)."""
    global _vapid
    if _vapid is not None:
        return _vapid
    env = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    if env:
        _vapid = _key_from_scalar(ub64u(env))
        return _vapid
    with session_scope() as db:
        row = db.get(AppSecret, "vapid_private_key")
        if row is None:
            k = ec.generate_private_key(ec.SECP256R1())
            row = AppSecret(key="vapid_private_key", value=b64u(k.private_numbers().private_value.to_bytes(32, "big")))
            db.add(row)
        value = row.value
    _vapid = _key_from_scalar(ub64u(value))
    return _vapid


def public_key_b64() -> str:
    return b64u(_raw_public(vapid_key()))


def endpoint_allowed(endpoint: str) -> bool:
    u = urlparse(endpoint)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == h or (h.startswith(".") and host.endswith(h)) for h in ALLOWED_PUSH_HOSTS)


# ------------------------------------------------------------------------------------- RFC 8291 encryption
def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None,
            server_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """aes128gcm body for one push message (single record)."""
    ua_public = ub64u(p256dh)
    auth_secret = ub64u(auth)
    as_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(as_key)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = as_key.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!IB", 4096, len(as_public)) + as_public + ciphertext


def vapid_header(endpoint: str) -> str:
    u = urlparse(endpoint)
    token = jwt.encode({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": SUBJECT},
                       vapid_key(), algorithm="ES256")
    return f"vapid t={token}, k={public_key_b64()}"


def send(sub: dict, message: dict, ttl: int = 3600) -> int:
    """POST one message. Returns the push service's HTTP status (0 = network error)."""
    if not endpoint_allowed(sub["endpoint"]):
        return 400
    body = encrypt(json.dumps(message, ensure_ascii=False).encode(), sub["p256dh"], sub["auth"])
    urgency = "high" if message.get("category") in ("HIGH RISK", "CRITICAL") else "normal"
    req = urllib.request.Request(sub["endpoint"], data=body, method="POST", headers={
        "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": str(ttl),
        "Urgency": urgency, "Authorization": vapid_header(sub["endpoint"])})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001 - network failures are counted, never raised into the replay loop
        return 0


# ------------------------------------------------------------------------------------- messages
def _i18n():
    try:
        root = str(Path(__file__).resolve().parents[3])
        if root not in sys.path:
            sys.path.insert(0, root)
        from i18n.translations import table
        return table()
    except Exception:  # pragma: no cover - fall back to English
        return {}


_T = None


def _tr(text: str, lang: str, **args) -> str:
    global _T
    if _T is None:
        _T = {k.lower(): v for k, v in _i18n().items()}
    row = _T.get(text.lower())
    out = (row.get(lang) or row.get("en")) if row else text
    for k, v in args.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def alert_message(alert: dict, lang: str) -> dict:
    cat, name = alert["risk_category"], alert["substation_name"]
    label = alert.get("parameter_label") or ""
    body = _tr("msg.detected_at", lang, name=name)
    if label:
        body += "\n" + _tr(label, lang)
    body += f"\n{_tr('risk', lang).upper()} {round(alert['risk_score'])}/100 · {alert['record_ts'][:16].replace('T', ' ')}"
    return {"title": f"{_tr(cat, lang)} · {name}", "body": body, "category": cat,
            "tag": f"gi-{alert['substation_id']}-{alert['record_ts']}",
            "url": f"/mobile/?inv={alert['substation_id']}|{alert['record_ts']}"}


def wants(sub_min: str, category: str) -> bool:
    try:
        return CATEGORY_ORDER.index(category) >= CATEGORY_ORDER.index(sub_min)
    except ValueError:
        return False


def _deliver(targets: list[dict], make) -> dict:
    sent, removed, failed = 0, 0, 0
    for t in targets:
        status = send(t, make(t))
        with session_scope() as db:
            row = db.get(PushSubscription, t["id"])
            if row is None:
                continue
            if 200 <= status < 300:
                sent += 1
                row.failures, row.last_sent_at = 0, utcnow()
            elif status in (404, 410):          # subscription expired or revoked by the user
                removed += 1
                db.delete(row)
            else:
                failed += 1
                row.failures += 1
                if row.failures >= 5:
                    db.delete(row)
    log.info("push delivered", extra={"event": "push", "detail": {"sent": sent, "removed": removed, "failed": failed}})
    return {"sent": sent, "removed": removed, "failed": failed}


def _rows(where) -> list[dict]:
    with session_scope() as db:
        return [{"id": r.id, "endpoint": r.endpoint, "p256dh": r.p256dh, "auth": r.auth, "lang": r.lang,
                 "min_category": r.min_category} for r in db.execute(select(PushSubscription).where(where)).scalars()]


def notify_alert(alert: dict) -> None:
    """Queue notifications for a newly raised alert (non-blocking)."""
    def job():
        try:
            targets = [t for t in _rows(PushSubscription.id.isnot(None)) if wants(t["min_category"], alert["risk_category"])]
            if targets:
                _deliver(targets, lambda t: alert_message(alert, t["lang"]))
        except Exception:  # pragma: no cover
            log.exception("push job failed")
    _pool.submit(job)


def send_test(username: str) -> dict:
    targets = _rows(PushSubscription.username == username)
    if not targets:
        return {"sent": 0, "removed": 0, "failed": 0, "subscriptions": 0}
    out = _deliver(targets, lambda t: {"title": _tr("GridIntel test notification", t["lang"]),
                                       "body": _tr("Alert notifications are working on this device.", t["lang"]),
                                       "category": "TEST", "tag": "gi-test", "url": "/mobile/"})
    return {**out, "subscriptions": len(targets)}
