"""Package trained artifacts (models, processed data, reports) into a bundle for upload to a deployed API.

The bundle is derived from private HVPNL data: keep it out of Git (dist/ is ignored) and upload it only to
your own deployment:

    python scripts/package_artifacts.py                      # -> dist/gridintel-artifacts.tar.gz
    python scripts/package_artifacts.py --upload https://<api> --username <admin>   # prompts for the password
"""
import argparse
import getpass
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "ml"))

from app.services import artifacts  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist" / "gridintel-artifacts.tar.gz"))
    ap.add_argument("--upload", help="base URL of the deployed API, e.g. https://gridintel-api.onrender.com")
    ap.add_argument("--username")
    ap.add_argument("--include-raw-cells", action="store_true", help="keep verbatim Excel cell text (local use only)")
    a = ap.parse_args()
    blob = artifacts.pack(ROOT, public=not a.include_raw_cells)
    man = artifacts.inspect(blob)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    print(f"bundle: {out} ({len(blob) / 2**20:.1f} MB, {man['files']} files, sha256 {man['sha256'][:12]})")
    if not a.upload:
        return
    base = a.upload.rstrip("/")
    user = a.username or input("admin username: ")
    pw = getpass.getpass("admin password: ")
    req = urllib.request.Request(f"{base}/api/v1/auth/login", data=json.dumps({"username": user, "password": pw}).encode(),
                                 headers={"Content-Type": "application/json"})
    token = json.load(urllib.request.urlopen(req, timeout=60))["access_token"]
    req = urllib.request.Request(f"{base}/api/v1/admin/artifacts", data=blob, method="POST",
                                 headers={"Content-Type": "application/gzip", "Authorization": f"Bearer {token}"})
    print(json.load(urllib.request.urlopen(req, timeout=600)))


if __name__ == "__main__":
    main()
