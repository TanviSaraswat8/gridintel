"""Password hashing (PBKDF2-SHA256), JWT access tokens, role-based access."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import os

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings

ROLES = ["VIEWER", "OPERATOR", "ENGINEER", "ADMIN"]   # ascending privilege
PBKDF2_ITERATIONS = 240_000
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except (ValueError, TypeError):
        return False


def create_token(username: str, role: str) -> tuple[str, int]:
    s = get_settings()
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=s.jwt_expire_minutes)
    token = jwt.encode({"sub": username, "role": role, "exp": exp, "iat": dt.datetime.now(dt.timezone.utc),
                        "iss": "gridintel"}, s.jwt_secret, algorithm="HS256")
    return token, s.jwt_expire_minutes * 60


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], issuer="gridintel")
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


def current_user(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    s = get_settings()
    if cred is None:
        if not s.auth_required:
            return {"sub": "anonymous", "role": "VIEWER"}
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    claims = decode_token(cred.credentials)
    request.state.user = claims["sub"]
    return claims


def require(min_role: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        if ROLES.index(user.get("role", "VIEWER")) < ROLES.index(min_role):
            raise HTTPException(403, f"Requires role {min_role} or higher")
        return user
    return dep
