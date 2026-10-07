"""
GridIntel API — AI-powered grid intelligence for substation monitoring (research prototype).

Run (from backend/):  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
import mimetypes
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException

from .api.deps import STATE
from .api.v1 import admin, auth, grid, intel, push
from .core.cache import cache, init_cache
from .core.config import DISCLAIMER, ROOT, get_settings
from .core.observability import ERRORS, HTTP_LATENCY, HTTP_REQUESTS, metrics_payload, request_id_var, setup_logging
from .db.models import Base
from .db.session import engine

settings = get_settings()
setup_logging(settings.log_level)
log = logging.getLogger("gridintel.api")


def _load_store():
    """Local artifacts → newest bundle stored in the database → train from raw workbooks → None (awaiting data)."""
    from .services import artifacts
    from .services.store import Store
    try:
        return Store()
    except FileNotFoundError as e:
        log.warning(f"model artifacts missing locally ({e})")
    except Exception as e:  # version mismatch etc.
        log.warning(f"model artifacts unusable ({type(e).__name__}: {e})")
    try:
        if artifacts.restore_latest():
            return Store()
    except Exception as e:
        log.error(f"stored artifact bundle could not be restored ({type(e).__name__}: {e})")
    raw = settings.data_root / "raw"
    if settings.train_on_start and raw.exists() and any(raw.glob("*.xlsx")):
        log.warning("training pipeline from raw workbooks")
        from pipeline.build import main as build
        build()
        return Store()
    log.warning("no model artifacts and no raw data: API running in AWAITING DATA mode "
                "(an ADMIN can upload a bundle at POST /api/v1/admin/artifacts)")
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .services.runtime import install_store
    from .services.seed import seed_users
    init_cache(settings.redis_url)
    Base.metadata.create_all(engine)          # no-op when Alembic migrations already created the schema
    seed_users()
    store = _load_store()
    if store is not None:
        install_store(store)
    log.info("startup complete", extra={"event": "startup", "detail": {"env": settings.app_env, "cache": cache().name,
                                                                       "data": "LOADED" if store is not None else "AWAITING DATA"}})
    yield


app = FastAPI(title="GridIntel API", version=settings.version, lifespan=lifespan,
              description="AI-powered grid intelligence for predictive substation monitoring — research prototype. " + DISCLAIMER,
              docs_url="/docs", redoc_url="/redoc", openapi_url="/api/v1/openapi.json")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-Request-ID"])

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()", "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                                "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self' *; frame-ancestors 'none'"),
}
DOCS_PATHS = {"/docs", "/redoc", "/docs/oauth2-redirect"}
DOCS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly; worker-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'")


@app.middleware("http")
async def observability(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    request_id_var.set(rid)
    ip = request.client.host if request.client else "?"
    path = request.url.path
    if path.startswith("/api/") and cache().incr_window(f"rl:{ip}:{int(time.time() // 60)}", 60) > settings.rate_limit_per_minute:
        return JSONResponse({"error": "rate_limited", "detail": "Too many requests", "request_id": rid}, status_code=429)
    t0 = time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception as e:  # pragma: no cover - safety net
        ERRORS.labels(type(e).__name__).inc()
        log.exception("unhandled error", extra={"path": path})
        resp = JSONResponse({"error": "internal_error", "detail": "Internal server error", "request_id": rid}, status_code=500)
    dur = time.perf_counter() - t0
    route = request.scope.get("route").path if request.scope.get("route") else path.split("?")[0][:60]
    HTTP_REQUESTS.labels(request.method, route, resp.status_code).inc()
    HTTP_LATENCY.labels(request.method, route).observe(dur)
    resp.headers["X-Request-ID"] = rid
    resp.headers["Server-Timing"] = f"app;dur={dur * 1000:.1f}"
    if path in DOCS_PATHS:   # Swagger UI / ReDoc load from jsdelivr with an inline bootstrap; the app pages stay strict
        resp.headers.setdefault("Content-Security-Policy", DOCS_CSP)
    for k, v in SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    if settings.is_production:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if path.startswith("/api/") or path in ("/health", "/ready"):
        log.info("request", extra={"method": request.method, "path": path, "status": resp.status_code,
                                   "duration_ms": round(dur * 1000, 1), "client": ip})
    return resp


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse({"error": "http_error", "detail": exc.detail, "request_id": request_id_var.get()},
                        status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse({"error": "validation_error", "detail": exc.errors(), "request_id": request_id_var.get()}, status_code=422)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": "gridintel-api", "version": settings.version, "env": settings.app_env,
            "data_mode": settings.data_mode_label, "demo_logins": settings.demo_users_enabled}


@app.get("/ready", tags=["system"])
def ready():
    checks = {"model_store": "store" in STATE, "cache": cache().name, "data": "LOADED" if "store" in STATE else "AWAITING DATA"}
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False
    ok = checks["model_store"] and checks["database"]
    return JSONResponse({"ready": ok, "checks": checks}, status_code=200 if ok else 503)


@app.get("/metrics", tags=["system"], include_in_schema=False)
def metrics():
    body, ctype = metrics_payload()
    return Response(body, media_type=ctype)


for r in (auth.router, grid.router, intel.router, admin.router, push.router):
    app.include_router(r, prefix="/api/v1")

mimetypes.add_type("application/manifest+json", ".webmanifest")  # slim images lack /etc/mime.types

# ---- static web app (also deployable separately to Vercel) and mobile web build
FE = settings.frontend_dir
MOBILE_WEB = ROOT / "mobile" / "dist"
if MOBILE_WEB.exists():
    app.mount("/mobile", StaticFiles(directory=MOBILE_WEB, html=True), name="mobile")
if FE.exists():
    app.mount("/assets", StaticFiles(directory=FE / "assets"), name="assets")

    @app.get("/config.js", include_in_schema=False)
    def runtime_config():
        return Response(f'window.GRIDINTEL_CONFIG={{"API_URL":"{settings.api_url}"}};', media_type="application/javascript")

    @app.get("/", include_in_schema=False)
    def landing():
        return FileResponse(FE / "index.html")

    @app.get("/app", include_in_schema=False)
    @app.get("/app/{rest:path}", include_in_schema=False)
    def spa(rest: str = ""):
        return FileResponse(FE / "app.html")
