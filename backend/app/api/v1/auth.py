from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ...core.cache import cache
from ...core.config import get_settings
from ...core.security import ROLES, create_token, current_user, require, verify_password
from ...db.models import AuditLog, User
from ...db.session import session_scope
from ..deps import audit

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request):
    ip = request.client.host if request.client else "?"
    if cache().incr_window(f"rl:login:{ip}", 60) > get_settings().login_rate_limit_per_minute:
        raise HTTPException(429, "Too many login attempts; try again in a minute")
    with session_scope() as db:
        u = db.execute(select(User).where(User.username == body.username, User.is_active.is_(True))).scalar_one_or_none()
        ok = bool(u and verify_password(body.password, u.password_hash))
        role, name = (u.role, u.display_name) if u else (None, None)
    audit(request, body.username, "login.success" if ok else "login.failure")
    if not ok:
        raise HTTPException(401, "Invalid username or password")
    token, exp = create_token(body.username, role)
    return {"access_token": token, "expires_in": exp, "user": {"username": body.username, "role": role, "display_name": name}}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return {"username": user["sub"], "role": user["role"], "roles": ROLES}


@router.get("/audit", dependencies=[Depends(require("ADMIN"))])
def audit_log(limit: int = 100):
    with session_scope() as db:
        rows = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))).scalars().all()
        return {"items": [{"at": r.at.isoformat(), "user": r.user, "action": r.action, "detail": r.detail, "ip": r.ip} for r in rows]}
