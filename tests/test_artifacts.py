"""Artifact bundle upload: validation, RBAC, restore-from-database."""
import io
import tarfile

import pytest

from app.services import artifacts


def _tar(members: dict[str, bytes], link: str | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
        if link:
            ti = tarfile.TarInfo(link)
            ti.type = tarfile.SYMTYPE
            ti.linkname = "/etc/passwd"
            t.addfile(ti)
    return buf.getvalue()


OK = {"models/substations.json": b"[]", "models/registry.json": b"{}"}


@pytest.mark.parametrize("bad, msg", [
    ({**OK, "../evil.py": b"x"}, "unsafe path"),
    ({**OK, "/etc/cron.d/x": b"x"}, "unsafe path"),
    ({**OK, "backend/app/main.py": b"x"}, "outside allowed roots"),
    ({"models/substations.json": b"[]"}, "missing"),
])
def test_bundle_validation_rejects(bad, msg):
    with pytest.raises(artifacts.BundleError, match=msg):
        artifacts.inspect(_tar(bad))


def test_bundle_rejects_links_and_garbage():
    with pytest.raises(artifacts.BundleError, match="unsupported member"):
        artifacts.inspect(_tar(OK, link="models/link"))
    with pytest.raises(artifacts.BundleError, match="not a gzip"):
        artifacts.inspect(b"not a tarball")


def test_upload_requires_admin(client, op):
    assert client.post("/api/v1/admin/artifacts", content=b"x", headers=op).status_code == 403
    assert client.get("/api/v1/admin/artifacts", headers=op).status_code == 403
    assert client.post("/api/v1/admin/artifacts", content=b"x").status_code == 401


def test_upload_invalid_bundle_is_422_and_store_untouched(client, admin, op):
    r = client.post("/api/v1/admin/artifacts", content=_tar({**OK, "../x": b"1"}), headers={**admin, "Content-Type": "application/gzip"})
    assert r.status_code == 422
    assert client.get("/api/v1/substations", headers=op).status_code == 200


def _member(blob: bytes, name: str) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as t:
        return t.extractfile(name).read()


def test_public_bundle_strips_verbatim_cells(built):
    import pandas as pd
    pub = pd.read_csv(io.BytesIO(_member(artifacts.pack(built), "data/processed/scada_long.csv")), low_memory=False)
    priv = pd.read_csv(io.BytesIO(_member(artifacts.pack(built, public=False), "data/processed/scada_long.csv")), low_memory=False)
    assert pub["raw_value"].isna().all() and priv["raw_value"].notna().any()
    assert pub["value"].equals(priv["value"])           # parsed values (used by the models) are unchanged
    with tarfile.open(fileobj=io.BytesIO(artifacts.pack(built)), mode="r:gz") as t:
        assert not [n for n in t.getnames() if n.lower().endswith((".xlsx", ".xls")) or n.startswith("data/raw")]


def test_health_reports_data_mode(client):
    h = client.get("/health").json()
    assert h["data_mode"] in ("LOCAL REAL-DATA MODE", "PUBLIC DEMO MODE")


def test_upload_real_bundle_roundtrip(client, admin, built):
    blob = artifacts.pack(built)
    r = client.post("/api/v1/admin/artifacts", content=blob, headers={**admin, "Content-Type": "application/gzip"})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["substations_with_data"] >= 1
    st = client.get("/api/v1/admin/artifacts", headers=admin).json()
    assert st["data"] == "LOADED" and st["latest_bundle"]["sha256"] == r.json()["manifest"]["sha256"]
    # restore from DB onto a wiped disk
    import shutil

    from app.core.config import get_settings
    shutil.rmtree(get_settings().model_path / "ensemble")
    assert artifacts.restore_latest() and (get_settings().model_path / "ensemble").exists()
