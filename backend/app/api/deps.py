from __future__ import annotations

from fastapi import HTTPException, Request

from ..core.observability import request_id_var
from ..db.models import AuditLog
from ..db.session import session_scope

STATE: dict = {}


AWAITING = "No model artifacts loaded yet — an administrator must upload the trained bundle (POST /api/v1/admin/artifacts)."


def store():
    if "store" not in STATE:
        raise HTTPException(503, AWAITING)
    return STATE["store"]


def replay():
    if "replay" not in STATE:
        raise HTTPException(503, AWAITING)
    return STATE["replay"]


def sub_or_404(sid: str) -> dict:
    try:
        return store().sub(sid)
    except KeyError:
        raise HTTPException(404, f"Unknown substation '{sid}'")


def sub_with_data(sid: str) -> dict:
    s = sub_or_404(sid)
    if not s.get("has_model"):
        raise HTTPException(409, f"{s['name']}: NO SOURCE READINGS — data unavailable in supplied records")
    return s


def ts_or_404(sid: str, ts: str) -> str:
    if ts not in store().values[sid].index:
        raise HTTPException(404, f"No logged record for {sid} at {ts}")
    return ts


def audit(request: Request, user: str, action: str, detail: dict | None = None) -> None:
    with session_scope() as db:
        db.add(AuditLog(user=user, action=action, detail=detail, ip=request.client.host if request.client else None,
                        request_id=request_id_var.get()))
