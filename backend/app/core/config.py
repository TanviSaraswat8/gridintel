"""Typed settings from environment variables (12-factor). See .env.example."""
from __future__ import annotations

import os
import secrets
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "ml"))  # ML package (pipeline.*) is shared with the training code


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip()
                if v.startswith("#"):
                    v = ""
                if not (v.startswith('"') or v.startswith("'")):
                    v = v.split(" #", 1)[0].split("\t#", 1)[0].strip()   # inline comment
                v = v.strip('"').strip("'")
                if v:
                    os.environ.setdefault(k.strip(), v)


_load_dotenv()


def _path(var: str, default: Path) -> Path:
    v = os.getenv(var)
    if not v:
        return default
    p = Path(v)
    return p if p.is_absolute() else (ROOT / p).resolve()


class Settings(BaseModel):
    app_env: str = os.getenv("APP_ENV", "development")            # development | staging | production
    app_name: str = "GridIntel"
    version: str = "2.1.0"
    api_url: str = os.getenv("API_URL", "")
    data_root: Path = _path("DATA_ROOT", ROOT / "data")
    model_path: Path = _path("MODEL_PATH", ROOT / "models")
    reports_dir: Path = _path("REPORTS_DIR", ROOT / "reports")
    frontend_dir: Path = _path("FRONTEND_DIR", ROOT / "frontend")
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT / 'data' / 'gridintel.db').as_posix()}")
    redis_url: str = os.getenv("REDIS_URL", "")
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
    # CORS: explicit list, else the host's own public URL (Render sets RENDER_EXTERNAL_URL), else "*" outside production.
    # The web app is served from the API's own origin, so production needs no cross-origin access by default.
    cors_origins: list[str] = [o.strip() for o in (os.getenv("CORS_ORIGINS") or os.getenv("RENDER_EXTERNAL_URL")
                               or ("" if os.getenv("APP_ENV") == "production" else "*")).split(",") if o.strip()]
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "600"))
    login_rate_limit_per_minute: int = int(os.getenv("LOGIN_RATE_LIMIT_PER_MINUTE", "20"))
    auth_required: bool = os.getenv("AUTH_REQUIRED", "true").lower() == "true"
    primary_substation: str = os.getenv("PRIMARY_SUBSTATION", "220-sec-46")
    replay_base_interval_sec: float = float(os.getenv("REPLAY_BASE_INTERVAL_SEC", "3.0"))
    alert_min_risk: float = float(os.getenv("ALERT_MIN_RISK", "56"))
    demo_users_enabled: bool = os.getenv("DEMO_USERS_ENABLED", "true").lower() == "true"
    admin_username: str = os.getenv("ADMIN_USERNAME", "")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    # train from DATA_ROOT/raw at start when no artifacts exist (needs ~1 GB RAM; disable on small instances)
    train_on_start: bool = os.getenv("TRAIN_ON_START", "true").lower() == "true"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    # LOCAL REAL-DATA MODE: the private HVPNL workbooks are on this machine (raw cell text available).
    # PUBLIC DEMO MODE: only model artifacts + derived values from an uploaded bundle; raw cell text is never served.
    data_mode_env: str = os.getenv("DATA_MODE", "").lower()

    @property
    def data_mode(self) -> str:
        if self.data_mode_env in ("local", "public"):
            return self.data_mode_env
        return "local" if any((self.data_root / "raw").glob("*.xlsx")) else "public"

    @property
    def data_mode_label(self) -> str:
        return "LOCAL REAL-DATA MODE" if self.data_mode == "local" else "PUBLIC DEMO MODE"

    @property
    def processed_dir(self) -> Path:
        return self.data_root / "processed"

    @property
    def features_dir(self) -> Path:
        return self.data_root / "features"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


DISCLAIMER = ("This prototype is intended for research, monitoring and decision-support purposes. Risk scores and anomaly "
              "alerts are model-generated indicators and must not be treated as certified protection or fault-diagnosis outputs.")
RISK_NOTE = "Prototype AI risk classification — not certified protection thresholds."


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.jwt_secret:
        if s.is_production:
            raise RuntimeError("JWT_SECRET must be set in production")
        s.jwt_secret = secrets.token_urlsafe(48)  # ephemeral dev secret; tokens reset on restart
    if s.is_production and len(s.jwt_secret) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters in production")
    if s.is_production and "*" in s.cors_origins:
        raise RuntimeError("CORS_ORIGINS must list explicit origins in production")
    return s
