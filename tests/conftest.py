"""Session setup: synthetic fixture workbooks → full training pipeline → isolated DB/models/reports in a temp dir."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_TMP = Path(tempfile.mkdtemp(prefix="gridintel-test-"))
os.environ.update({
    "DATA_ROOT": str(_TMP / "data"), "MODEL_PATH": str(_TMP / "models"), "REPORTS_DIR": str(_TMP / "reports"),
    "EXPERIMENTS_DIR": str(_TMP / "experiments"), "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    "JWT_SECRET": "test-only-secret", "PRIMARY_SUBSTATION": "220-test-a", "REDIS_URL": "", "APP_ENV": "test",
    "LOGIN_RATE_LIMIT_PER_MINUTE": "50", "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "admin-test-pass",
})
sys.path.insert(0, str(ROOT / "ml"))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import make_dataset  # noqa: E402

make_dataset(_TMP / "data")


@pytest.fixture(scope="session")
def built():
    from pipeline.build import main
    main()
    return _TMP


@pytest.fixture(scope="session")
def client(built):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


def _login(client, user, pw):
    return {"Authorization": "Bearer " + client.post("/api/v1/auth/login", json={"username": user, "password": pw}).json()["access_token"]}


@pytest.fixture(scope="session")
def op(client):
    return _login(client, "operator", "hvpnl2026")


@pytest.fixture(scope="session")
def viewer(client):
    return _login(client, "viewer", "hvpnl2026")


@pytest.fixture(scope="session")
def eng(client):
    return _login(client, "engineer", "hvpnl2026")


@pytest.fixture(scope="session")
def admin(client):
    return _login(client, "admin", "admin-test-pass")
