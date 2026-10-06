"""Run public-benchmark method validation (writes reports/benchmarks.json). Usage: python scripts/run_benchmarks.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ml"))
from pipeline.benchmarks import run  # noqa: E402

if __name__ == "__main__":
    print(json.dumps({k: v["summary"] for k, v in run().items()}, indent=1))
