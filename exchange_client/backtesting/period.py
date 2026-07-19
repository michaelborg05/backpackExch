"""
backtesting/period.py
=====================
Shared parsing for the ``--days`` argument used by the backtest runners.

Accepts either a plain lookback or an explicit days-ago range so that
successive windows can be tested without overlapping:

    --days 30       -> the last 30 days            (0 .. 30 days ago)
    --days 0-30     -> same as above
    --days 30-60    -> the 30 days ending 30 days ago (no overlap with 0-30)

The range form is inclusive of the older bound and exclusive of the newer one
in the sense that consecutive ranges (0-30, 30-60, 60-90) tile the timeline
without double-counting any candle.
"""

from datetime import datetime, timedelta, timezone


def parse_period(spec, now=None):
    """Parse a --days spec into (start, end, label).

    ``spec`` may be an int/str lookback ("30") or a days-ago range ("30-60").
    Returns UTC datetimes plus a short label suitable for filenames/printing.
    """
    now = now or datetime.now(tz=timezone.utc)
    text = str(spec).strip()

    if "-" in text:
        parts = text.split("-")
        if len(parts) != 2:
            raise ValueError(f"Invalid --days range '{spec}'. Expected e.g. 30-60.")
        try:
            a, b = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError(f"Invalid --days range '{spec}'. Expected e.g. 30-60.")
        newer, older = min(a, b), max(a, b)
        if newer == older:
            raise ValueError(f"Invalid --days range '{spec}': window is zero-length.")
        if newer < 0:
            raise ValueError(f"Invalid --days range '{spec}': days ago cannot be negative.")
        label = f"{newer}-{older}d"
    else:
        try:
            older = int(text)
        except ValueError:
            raise ValueError(f"Invalid --days value '{spec}'. Expected e.g. 30 or 30-60.")
        if older <= 0:
            raise ValueError(f"Invalid --days value '{spec}': must be positive.")
        newer = 0
        label = f"{older}d"

    end   = now - timedelta(days=newer)
    start = now - timedelta(days=older)
    return start, end, label


def print_period(start, end, label):
    print(f"Period: {start.strftime('%Y-%m-%d %H:%M')} -> "
          f"{end.strftime('%Y-%m-%d %H:%M')} UTC ({label})")


DAYS_HELP = ("Lookback window in days, or a days-ago range for a "
             "non-overlapping slice: 30 | 0-30 | 30-60")
