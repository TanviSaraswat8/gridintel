"""Administration: upload / inspect the trained-artifact bundle (ADMIN only)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from ...core.security import require
from ...services import artifacts
from ..deps import STATE, audit

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/artifacts")
def artifacts_status(user: dict = Depends(require("ADMIN"))):
    return {"data": "LOADED" if "store" in STATE else "AWAITING DATA", "latest_bundle": artifacts.latest_info()}


@router.post("/artifacts")
async def upload_artifacts(request: Request, user: dict = Depends(require("ADMIN"))):
    """Body: the .tar.gz bundle from scripts/package_artifacts.py (Content-Type: application/gzip).
    Validated, extracted, stored in the database for restarts, then loaded without downtime."""
    declared = int(request.headers.get("content-length") or 0)
    if declared > artifacts.MAX_BUNDLE_BYTES:
        raise HTTPException(413, "bundle too large")
    blob = bytearray()
    async for chunk in request.stream():
        blob += chunk
        if len(blob) > artifacts.MAX_BUNDLE_BYTES:
            raise HTTPException(413, "bundle too large")
    blob = bytes(blob)
    try:
        manifest = await asyncio.to_thread(artifacts.extract, blob)
    except artifacts.BundleError as e:
        raise HTTPException(422, f"invalid bundle: {e}")

    def load():
        from ...services.runtime import install_store
        from ...services.store import Store
        st = Store()
        install_store(st)
        return st
    try:
        st = await asyncio.to_thread(load)
    except Exception as e:
        raise HTTPException(422, f"bundle extracted but the model store failed to load: {type(e).__name__}: {e}")
    bundle_id = await asyncio.to_thread(artifacts.save, blob, manifest, user["sub"])
    audit(request, user["sub"], "artifacts.upload", {"bundle_id": bundle_id, "sha256": manifest["sha256"], "files": manifest["files"]})
    return {"ok": True, "bundle_id": bundle_id, "manifest": manifest,
            "substations_with_data": sum(1 for s in st.substations if s.get("has_model"))}
