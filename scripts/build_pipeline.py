"""Build the clean dataset, train models and write evaluation reports.

Usage (from project root):  python scripts/build_pipeline.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ml"))

from pipeline.build import main  # noqa: E402

if __name__ == "__main__":
    main()
