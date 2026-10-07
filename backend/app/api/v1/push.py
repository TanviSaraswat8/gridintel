"""Alert notifications: devices subscribe with Web Push and receive alerts even when the app is closed."""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ...core.security import require
from ...db.models import PushSubscription
from ...db.session import session_scope
from ...services import push
from ..deps import audit

router = APIRouter(prefix="/push", tags=["notifications"])


class Keys(BaseModel):
    p256dh: str = Field(min_length=80, max_length=128)
    auth: str = Field(min_length=16, max_length=64)


class Subscribe(BaseModel):
    endpoint: str = Field(min_length=20, max_length=1024)
    keys: Keys
    min_category: Literal["WARNING", "HIGH RISK", "CRITICAL"] = "HIGH RISK"
    lang: Literal["en", "hi", "hry", "pa"] = "en"


class Unsubscribe(BaseModel):
    endpoint: str = Field(min_length=20, max_length=1024)


@router.get("/config")
def config(user: dict = Depends(require("VIEWER"))):
    with session_scope() as db:
        mine = db.execute(select(PushSubscription).where(PushSubscription.username == user["sub"])).scalars().all()
        devices = [{"endpoint_host": s.endpoint.split("/")[2], "min_category": s.min_category, "lang": s.lang} for s in mine]
    return {"public_key": push.public_key_b64(), "categories": push.CATEGORY_ORDER, "devices": devices}


@router.post("/subscribe")
def subscribe(body: Subscribe, request: Request, user: dict = Depends(require("VIEWER"))):
    if not push.endpoint_allowed(body.endpoint):
        raise HTTPException(422, "Unsupported push service")
    try:
        push.ub64u(body.keys.p256dh), push.ub64u(body.keys.auth)
    except Exception:
        raise HTTPException(422, "Invalid subscription keys")
    with session_scope() as db:
        row = db.execute(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)).scalar_one_or_none()
        if row is None:
            row = PushSubscription(endpoint=body.endpoint, username=user["sub"], p256dh=body.keys.p256dh, auth=body.keys.auth,
                                   failures=0)
            db.add(row)
        row.username, row.p256dh, row.auth = user["sub"], body.keys.p256dh, body.keys.auth
        row.min_category, row.lang = body.min_category, body.lang
    audit(request, user["sub"], "push.subscribe", {"min_category": body.min_category, "host": body.endpoint.split("/")[2]})
    return {"ok": True, "min_category": body.min_category}


@router.post("/unsubscribe")
def unsubscribe(body: Unsubscribe, request: Request, user: dict = Depends(require("VIEWER"))):
    with session_scope() as db:
        row = db.execute(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint,
                                                        PushSubscription.username == user["sub"])).scalar_one_or_none()
        if row:
            db.delete(row)
    audit(request, user["sub"], "push.unsubscribe")
    return {"ok": True}


@router.post("/test")
async def test(request: Request, user: dict = Depends(require("VIEWER"))):
    out = await asyncio.to_thread(push.send_test, user["sub"])
    audit(request, user["sub"], "push.test", out)
    return out
