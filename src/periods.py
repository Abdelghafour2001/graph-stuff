"""Period labels and forecast markers shared by the spec executor and structure discovery (no database needed)."""
import re
from datetime import date, datetime

FORECAST_FORMAT = re.compile(r'"\s*f\s*"', re.IGNORECASE)  # number formats like mmm\-yy\ "f" (Argus forecasts)


def parse_period(v):
    """Start date of a period label: a date, a year (2026), a quarter (1Q26, Q1 2026) or a month (Oct-25, Oct 2025)."""
    if hasattr(v, "year") and hasattr(v, "month"):
        return date(v.year, v.month, getattr(v, "day", 1) if not hasattr(v, "hour") else v.day)
    if isinstance(v, (int, float)) and float(v).is_integer() and 1990 <= v <= 2100:
        return date(int(v), 1, 1)
    if not isinstance(v, str):
        return None
    t = v.strip()
    m = re.fullmatch(r"([1-4])Q(\d{2}|\d{4})|Q([1-4])\s*(\d{4})", t, re.IGNORECASE)
    if m:
        q, y = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        return date(int(y) if len(y) == 4 else 2000 + int(y), 3 * int(q) - 2, 1)
    if re.fullmatch(r"\d{4}", t):
        return date(int(t), 1, 1)
    for fmt in ("%b-%y", "%b %y", "%b-%Y", "%b %Y"):
        try:
            d = datetime.strptime(t, fmt)
            return date(d.year, d.month, 1)
        except ValueError:
            pass
    return None


