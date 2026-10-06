"""
Trained-artifact bundles: package, validate, store in the database, restore.

A bundle is a .tar.gz whose members live under four allowed roots:
    models/  data/processed/  data/features/  reports/
They are extracted into MODEL_PATH, DATA_ROOT/processed, DATA_ROOT/features and REPORTS_DIR respectively.
Extraction rejects absolute paths, '..', links, devices and unknown roots, and caps total size.
"""
from __future__ import annotations

import hashlib
import io
import logging
import shutil
import tarfile
import tempfile
from pathlib import Path

from sqlalchemy import select

from ..core.config import get_settings
from ..db.models import ArtifactBundle
from ..db.session import session_scope

log = logging.getLogger("gridintel.artifacts")

MAX_BUNDLE_BYTES = 200 * 1024 * 1024          # compressed upload limit
MAX_EXTRACTED_BYTES = 600 * 1024 * 1024
REQUIRED = ("models/substations.json", "models/registry.json")


class BundleError(ValueError):
    pass


def _targets() -> dict[str, Path]:
    s = get_settings()
    return {"models/": s.model_path, "data/processed/": s.data_root / "processed",
            "data/features/": s.data_root / "features", "reports/": s.reports_dir}


PRIVATE_COLUMNS = {"data/processed/scada_long.csv": ["raw_value"]}   # verbatim Excel cell text stays local


def pack(root: Path, public: bool = True) -> bytes:
    """Build a bundle from a project checkout (used by scripts/package_artifacts.py).

    public=True (default, for any hosted deployment) blanks verbatim Excel cell text, keeping only parsed values,
    model artifacts and derived metadata. The workbooks themselves are never part of a bundle.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for prefix in ("models", "data/processed", "data/features", "reports"):
            d = root / prefix
            if d.exists():
                for f in sorted(d.rglob("*")):
                    if not f.is_file() or "__pycache__" in f.parts or f.suffix.lower() in (".xlsx", ".xls"):
                        continue
                    arc = f.relative_to(root).as_posix()
                    if public and arc in PRIVATE_COLUMNS:
                        import pandas as pd
                        df = pd.read_csv(f, low_memory=False)
                        for c in PRIVATE_COLUMNS[arc]:
                            if c in df.columns:
                                df[c] = None
                        data = df.to_csv(index=False).encode()
                        info = tarfile.TarInfo(arc)
                        info.size, info.mtime = len(data), int(f.stat().st_mtime)
                        tar.addfile(info, io.BytesIO(data))
                    else:
                        tar.add(f, arcname=arc)
    return buf.getvalue()


def inspect(blob: bytes) -> dict:
    """Validate a bundle without extracting it. Returns a manifest."""
    if len(blob) > MAX_BUNDLE_BYTES:
        raise BundleError(f"bundle larger than {MAX_BUNDLE_BYTES // 2**20} MB")
    try:
        tar = tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz")
    except (tarfile.TarError, OSError, EOFError) as e:
        raise BundleError(f"not a gzip tar archive: {e}") from None
    names, total, roots = [], 0, {}
    with tar:
        for m in tar.getmembers():
            n = m.name
            if m.isdir():
                continue
            if not m.isfile():
                raise BundleError(f"unsupported member type: {n}")
            if n.startswith("/") or ".." in Path(n).parts or "\\" in n:
                raise BundleError(f"unsafe path: {n}")
            root = next((r for r in _targets() if n.startswith(r)), None)
            if root is None:
                raise BundleError(f"path outside allowed roots: {n}")
            total += m.size
            if total > MAX_EXTRACTED_BYTES:
                raise BundleError("bundle expands beyond the size limit")
            names.append(n)
            roots[root] = roots.get(root, 0) + 1
    missing = [r for r in REQUIRED if r not in names]
    if missing:
        raise BundleError(f"bundle is missing {', '.join(missing)}")
    return {"files": len(names), "extracted_bytes": total, "roots": roots, "sha256": hashlib.sha256(blob).hexdigest()}


def extract(blob: bytes) -> dict:
    """Validate, then extract into a staging dir and swap each target directory in place."""
    manifest = inspect(blob)
    targets = _targets()
    with tempfile.TemporaryDirectory(prefix="gi-bundle-") as tmp:
        tmp = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            for m in tar.getmembers():
                if not m.isfile():
                    continue
                root = next(r for r in targets if m.name.startswith(r))
                dest = tmp / root / m.name[len(root):]
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(m) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
        for root, target in targets.items():
            staged = tmp / root
            if not staged.exists():
                continue
            target.mkdir(parents=True, exist_ok=True)
            for child in target.iterdir():
                shutil.rmtree(child) if child.is_dir() else child.unlink()
            for child in staged.iterdir():
                shutil.move(str(child), str(target / child.name))
    return manifest


def save(blob: bytes, manifest: dict, user: str) -> int:
    with session_scope() as db:
        row = ArtifactBundle(uploaded_by=user, sha256=manifest["sha256"], size_bytes=len(blob), manifest=manifest, data=blob)
        db.add(row)
        db.flush()
        return row.id


def latest() -> tuple[bytes, dict] | None:
    with session_scope() as db:
        row = db.execute(select(ArtifactBundle).order_by(ArtifactBundle.id.desc()).limit(1)).scalar_one_or_none()
        return (row.data, {"id": row.id, "created_at": row.created_at.isoformat(), "uploaded_by": row.uploaded_by,
                           **(row.manifest or {})}) if row else None


def latest_info() -> dict | None:
    with session_scope() as db:
        row = db.execute(select(ArtifactBundle.id, ArtifactBundle.created_at, ArtifactBundle.uploaded_by, ArtifactBundle.size_bytes,
                                ArtifactBundle.sha256).order_by(ArtifactBundle.id.desc()).limit(1)).first()
        return dict(row._mapping) if row else None


def restore_latest() -> bool:
    """Restore the newest stored bundle onto local disk. Returns True if one was restored."""
    found = latest()
    if not found:
        return False
    blob, meta = found
    extract(blob)
    log.info("artifacts restored from database", extra={"event": "artifacts.restore", "detail": {"id": meta["id"], "files": meta.get("files")}})
    return True
