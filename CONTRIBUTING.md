# Contributing

1. Create a branch from `main`.
2. `pip install -r requirements-dev.txt`; for mobile `cd mobile && npm install`.
3. Keep the data rules: never commit private data or anything derived from it; never add synthetic measurements to the product (tests may use the synthetic fixture in `tests/fixtures.py`); keep non-causal wording ("contributing signals", "potential abnormal operating condition").
4. Before opening a pull request: `ruff check backend ml tests scripts` and `pytest -q`.
5. Model changes: run `python scripts/build_pipeline.py`, review `reports/evaluation.md`, and describe the change in the PR (no accuracy claims without labels).
6. Use conventional commit messages (`feat:`, `fix:`, `docs:`, `test:`, `ci:`).
