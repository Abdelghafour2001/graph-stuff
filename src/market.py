"""Market references for branch assumptions: provider monthly price sheets, actual months only (knowledge/market_refs.yaml)."""
import datetime as dt
from pathlib import Path

import openpyxl
import yaml

from periods import FORECAST_FORMAT

REFS = yaml.safe_load((Path(__file__).parent.parent / "knowledge" / "market_refs.yaml").read_text(encoding="utf-8"))["references"]


def monthly_mid(path: Path, sheet: str, route: str) -> dict[str, float]:
    """{YYYY-MM: (low + high) / 2} for the route's actual months; forecast months (format "f") are left out."""
    ws = openpyxl.load_workbook(path, read_only=True)[sheet]
    rows = list(ws.iter_rows())
    name_row = next(r for r in rows[:15] if any(isinstance(c.value, str) and c.value.strip() == route for c in r))
    col = next(i for i, c in enumerate(name_row) if isinstance(c.value, str) and c.value.strip() == route)
    out = {}
    for r in rows:
        if not r or not isinstance(r[0].value, dt.datetime) or FORECAST_FORMAT.search(getattr(r[0], "number_format", "") or ""):
            continue
        pts = [r[i].value for i in (col, col + 1) if i < len(r) and isinstance(r[i].value, (int, float))]
        if pts:
            out[f"{r[0].value.year:04d}-{r[0].value.month:02d}"] = sum(pts) / len(pts)
    return out


def reference(concept: str, driver: str, market_dir: Path) -> tuple[dict, str] | None:
    """(monthly series, description) for a concept/driver, or None when no reference is configured or found."""
    ref = REFS.get(f"{concept}/{driver}")
    if not ref:
        return None
    files = sorted(market_dir.glob(ref["file"]))
    if not files:
        return None
    return monthly_mid(files[-1], ref["sheet"], ref["route"]), f"{files[-1].name} / {ref['sheet']} / {ref['route']} (actuals, mid of low-high)"
