"""
Excel ingestion for HVPNL Faridabad daily log sheets.

Each workbook = one day. Each worksheet = one substation.
Each sheet has: title rows -> 1-3 header rows (merged group cells) -> 24 hourly rows -> footer blocks
(shift checks, energy-meter tables). Only the contiguous hourly block is extracted.

Output is a LONG table: one row per (date, substation, hour, parameter) with the raw cell text
preserved next to the parsed numeric value and any parsed equipment-state token.
The raw Excel files are opened read-only and never modified.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import openpyxl
import pandas as pd

STATUS_TOKENS = {
    "ON": "ON",
    "AUTO ON": "AUTO_ON",
    "OFF": "OFF",
    "PTW": "PTW",          # permit-to-work (planned shutdown)
    "B/D": "BREAKDOWN",    # breakdown recorded by operator
    "BD": "BREAKDOWN",
    "NBC": "NBC",          # no-bus-charge / not charged (as logged)
    "OK": "OK",
    "CLEAR": "CLEAR",      # weather
    "CLOUDY": "CLOUDY",
    "FOGGY": "FOGGY",
    "FOG": "FOGGY",
    "RAINY": "RAINY",
}
MISSING_TOKENS = {"", "-", "--", "—", "NA", "N/A", "NAN", "NONE", "NIL", "X"}

FILE_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def _hour_of(v) -> int | None:
    """Return hour 1..24 if the cell looks like an hourly time stamp, else None."""
    if v is None:
        return None
    if isinstance(v, dt.time):
        h = v.hour
        return 24 if h == 0 else h
    if isinstance(v, dt.datetime):
        h = v.hour
        return 24 if h == 0 else h
    if isinstance(v, dt.timedelta):
        h = round(v.total_seconds() / 3600)
        return h if 1 <= h <= 24 else None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if float(v).is_integer() and 1 <= int(v) <= 24:
            return int(v)
        # Excel fraction-of-day time
        if 0 < float(v) < 1.0001:
            h = round(float(v) * 24)
            return h if 1 <= h <= 24 else None
        return None
    s = str(v).strip()
    m = re.match(r"^(\d{1,2})[:.](\d{2})", s)
    if m:
        h = int(m.group(1))
        h = 24 if h == 0 else h
        return h if 1 <= h <= 24 else None
    m = re.match(r"^(\d{1,2})$", s)
    if m and 1 <= int(s) <= 24:
        return int(s)
    return None


def _clean_text(v) -> str:
    if v is None:
        return ""
    s = str(v).replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", s).strip()


def parse_cell(v):
    """Return (raw_text, numeric_value or None, status_token or None, is_missing)."""
    raw = _clean_text(v)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return raw, float(v), None, False
    up = raw.upper()
    if up in MISSING_TOKENS:
        return raw, None, None, True
    if up in STATUS_TOKENS:
        return raw, None, STATUS_TOKENS[up], False
    num = re.match(r"^[-+]?\d+(\.\d+)?$", raw)
    if num:
        return raw, float(raw), None, False
    # e.g. "54 C", "11.2kV"
    m = re.match(r"^([-+]?\d+(\.\d+)?)\s*[A-Za-z°%/]*$", raw)
    if m:
        return raw, float(m.group(1)), None, False
    return raw, None, None, False  # free text (remarks etc.)


def _sheet_grid(ws):
    """Materialise sheet as list-of-lists with merged cells filled by their top-left value."""
    max_r, max_c = ws.max_row, ws.max_column
    grid = [[ws.cell(r, c).value for c in range(1, max_c + 1)] for r in range(1, max_r + 1)]
    for rng in ws.merged_cells.ranges:
        top = ws.cell(rng.min_row, rng.min_col).value
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                if r - 1 < len(grid) and c - 1 < len(grid[0]):
                    grid[r - 1][c - 1] = top
    return grid


def _find_hour_block(grid):
    """Longest run of consecutive rows whose first column is an hour stamp."""
    best, cur_start, cur_len = (None, 0), None, 0
    for i, row in enumerate(grid):
        h = _hour_of(row[0] if row else None)
        if h is not None:
            if cur_start is None:
                cur_start, cur_len = i, 1
            else:
                cur_len += 1
            if cur_len > best[1]:
                best = (cur_start, cur_len)
        else:
            cur_start, cur_len = None, 0
    return best


def _header_names(grid, data_start):
    """Build column names from up to 4 header rows above the data block."""
    # header region begins at the nearest row above data_start whose col0 mentions 'time'
    top = max(0, data_start - 4)
    for r in range(data_start - 1, max(-1, data_start - 6), -1):
        if r >= 0 and "time" in _clean_text(grid[r][0]).lower():
            top = r
            # sheets with a two-row 'TIME' label (e.g. A4/Ford) -> include the upper label row too
            if r - 1 >= 0 and "time" in _clean_text(grid[r - 1][0]).lower():
                top = r - 1
    ncols = len(grid[0])
    names = []
    for c in range(ncols):
        parts = []
        for r in range(top, data_start):
            t = _clean_text(grid[r][c])
            low = t.lower()
            if "log sheet" in low or "logsheet" in low or "registered office" in low:
                continue  # title banner merged across the sheet, not a header
            if t and (not parts or parts[-1].lower() != t.lower()):
                parts.append(t)
        names.append(" | ".join(parts))
    return names


INVENTORY: list[dict] = []


def ingest_file(path: Path) -> pd.DataFrame:
    m = FILE_DATE_RE.search(path.name)
    if not m:
        raise ValueError(f"Cannot read log date from file name: {path.name}")
    day = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    rows = []
    for ws in wb.worksheets:
        grid = _sheet_grid(ws)
        if not grid:
            continue
        start, length = _find_hour_block(grid)
        inv = {"source_file": path.name, "log_date": day.isoformat(), "substation": ws.title.strip(),
               "hourly_rows": int(length) if start is not None else 0, "filled_cells": 0, "parameters": 0}
        INVENTORY.append(inv)
        if start is None or length < 12:
            inv["note"] = "no hourly block detected"
            continue
        names = _header_names(grid, start)
        seen = {}
        for c in range(1, len(names)):
            if not names[c]:
                continue
            # skip columns with no content in the data block at all
            col_vals = [grid[r][c] for r in range(start, start + length)]
            if all(_clean_text(v) == "" for v in col_vals):
                continue
            inv["parameters"] += 1
            inv["filled_cells"] += sum(_clean_text(v) != "" for v in col_vals)
            pname = names[c]
            if pname in seen:  # duplicated header text -> disambiguate by column letter
                seen[pname] += 1
                pname = f"{pname} [col {openpyxl.utils.get_column_letter(c + 1)}]"
            else:
                seen[pname] = 1
            for r in range(start, start + length):
                hour = _hour_of(grid[r][0])
                raw, num, status, missing = parse_cell(grid[r][c])
                rows.append(
                    {
                        "source_file": path.name,
                        "log_date": day.isoformat(),
                        "substation": ws.title.strip(),
                        "hour": hour,
                        "timestamp": (dt.datetime.combine(day, dt.time(0)) + dt.timedelta(hours=hour)).isoformat(),
                        "excel_column": openpyxl.utils.get_column_letter(c + 1),
                        "parameter": pname,
                        "raw_value": raw,
                        "value": num,
                        "status": status,
                        "is_missing": missing or (raw == ""),
                    }
                )
    wb.close()
    for inv in INVENTORY:
        if inv["source_file"] == path.name and "note" not in inv:
            inv["note"] = "blank template (no readings)" if inv["filled_cells"] < 30 else "data present"
    return pd.DataFrame(rows)


def ingest_all(raw_dir: Path) -> pd.DataFrame:
    files = sorted(p for p in Path(raw_dir).glob("*.xlsx") if not p.name.startswith("~$"))
    if not files:
        raise FileNotFoundError(f"No .xlsx files in {raw_dir}")
    INVENTORY.clear()
    df = pd.concat([ingest_file(p) for p in files], ignore_index=True)
    return df


def inventory() -> pd.DataFrame:
    return pd.DataFrame(INVENTORY)
