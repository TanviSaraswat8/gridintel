"""Multilingual UI: translation table integrity and the API's [template key, args] contract."""
import re
import subprocess
import sys
from pathlib import Path

from i18n.translations import LANGS, ROWS, table

ROOT = Path(__file__).resolve().parents[1]
PH = re.compile(r"\{(\w+)\}")
CODES = [c for c, _ in LANGS]


def test_languages():
    assert CODES == ["en", "hi", "hry", "pa"]


def test_every_row_has_all_languages():
    for row in ROWS:
        assert len(row) in (4, 5), row[0]
        assert all(isinstance(x, str) and x.strip() for x in row), row[0]


def test_placeholders_match_across_languages():
    for key, row in table().items():
        want = set(PH.findall(row["en"]))
        for code in CODES:
            assert set(PH.findall(row[code])) == want, (key, code)


def test_no_conflicting_duplicates():
    seen = {}
    for row in ROWS:
        k = row[0].lower()
        assert seen.setdefault(k, row[1:4]) == row[1:4], row[0]


def test_scripts():
    deva = re.compile(r"[ऀ-ॿ]")
    guru = re.compile(r"[਀-੿]")
    t = table()
    assert deva.search(t["Command Center"]["hi"]) and deva.search(t["Command Center"]["hry"])
    assert guru.search(t["Command Center"]["pa"])


def test_every_rule_has_templates():
    src = (ROOT / "ml/pipeline/rules.py").read_text(encoding="utf-8")
    t = table()
    for rule in set(re.findall(r'hit\(\s*"(R-[A-Z0-9]+)"', src)):
        assert f"rule.{rule}.msg" in t and f"rule.{rule}.check" in t, rule
    for key in re.findall(r'"((?:rule|obs|why|exp|msg|inv)\.[A-Za-z0-9_.-]+)"',
                          src + (ROOT / "backend/app/services/investigation.py").read_text(encoding="utf-8")):
        assert key in t, key


def test_generated_client_tables_are_current():
    r = subprocess.run([sys.executable, str(ROOT / "scripts/build_i18n.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def _pairs(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("i18n", "observed_i18n"):
                yield from _flatten(v)
            else:
                yield from _pairs(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _pairs(v)


def _flatten(v):
    if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], dict):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _flatten(x)
    elif isinstance(v, list):
        for x in v:
            yield from _flatten(x)


def test_investigation_i18n_contract(client, op):
    inv = client.get("/api/v1/investigations", params={"substation": "220-test-a", "timestamp": "2026-02-02T10:00:00"}, headers=op).json()
    if not inv.get("available"):
        demo = client.get("/api/v1/investigations/demo", headers=op).json()
        items = demo.get("items") or []
        if not items:
            return
        inv = client.get("/api/v1/investigations", params={"substation": items[0]["substation_id"], "timestamp": items[0]["timestamp"]},
                         headers=op).json()
    assert "i18n" in inv and {"message", "what", "why", "investigate"} <= set(inv["i18n"])
    t = table()
    pairs = list(_pairs(inv))
    assert pairs
    for key, args in pairs:
        assert key in t, key
        assert set(PH.findall(t[key]["en"])) <= set(args), (key, args)
