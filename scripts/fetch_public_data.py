"""Download public benchmark datasets listed in data/sources/dataset_registry.yaml into data/external/ (not committed)."""
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "ett/ETTh1.csv": "https://raw.githubusercontent.com/zhouhaoyi/ETDataset/main/ETT-small/ETTh1.csv",  # CC BY-ND 4.0
}

for rel, url in SOURCES.items():
    dest = ROOT / "data" / "external" / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"exists: {dest}")
        continue
    print(f"downloading {url}")
    urllib.request.urlretrieve(url, dest)
    print(f"saved: {dest} ({dest.stat().st_size // 1024} KB)")
