from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..core.config import get_settings


def _url(u: str) -> str:
    from ..core.config import ROOT
    if u.startswith("sqlite:///") and not u.startswith("sqlite:////") and ":" not in u[10:12]:
        u = f"sqlite:///{(ROOT / u[10:]).as_posix()}"   # relative SQLite paths are relative to the project root
    # Managed providers often hand out postgres:// URLs; SQLAlchemy needs the psycopg driver name.
    if u.startswith("postgres://"):
        u = "postgresql+psycopg://" + u[len("postgres://"):]
    elif u.startswith("postgresql://"):
        u = "postgresql+psycopg://" + u[len("postgresql://"):]
    return u


_s = get_settings()
URL = _url(_s.database_url)
engine = create_engine(URL, future=True, pool_pre_ping=True,
                       connect_args={"check_same_thread": False} if URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
