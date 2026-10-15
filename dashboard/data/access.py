"""Load and combine runs selected in the sidebar, plus shared global filters."""
import pandas as pd

from dashboard import config
from dashboard.data import loader, versions

MIN_DAYS = 1
MAX_DAYS = 35


def load_selected(labels):
    """Return (hourly df for all labels, {label: gen_params})."""
    labels = labels or [config.CURRENT]
    paths = dict(versions.list_runs())
    frames, params = [], {}
    for lab in labels:
        if lab not in paths:
            continue
        frames.append(loader.load_run(paths[lab], run=lab))
        params[lab] = loader.load_gen_params(paths[lab])
    if not frames:
        return pd.DataFrame(), {}
    return pd.concat(frames, ignore_index=True), params


def clamp_days(value):
    """Clamp to MIN_DAYS..MAX_DAYS; fall back to config.WINDOW_DAYS if missing/invalid."""
    try:
        d = int(value)
    except (TypeError, ValueError):
        return config.WINDOW_DAYS
    return min(max(d, MIN_DAYS), MAX_DAYS)


def filter_window(df, start, days):
    """Return (window df, start, last hour actually present in the window or None)."""
    days = clamp_days(days)
    s = pd.Timestamp(start) if start else df["datetime"].min().normalize()
    e = s + pd.Timedelta(days=days)
    w = df[(df["datetime"] >= s) & (df["datetime"] < e)]
    last = w["datetime"].max() if not w.empty else None
    return w, s, last


def range_label(s, last):
    if last is None:
        return "No data in window"
    return "%s to %s" % (s.strftime("%Y-%m-%d %H:%M"), last.strftime("%Y-%m-%d %H:%M"))


def selected_gens(gens):
    """Ticked generators in config.GENERATORS order (None -> all)."""
    if gens is None:
        return list(config.GENERATORS)
    return [g for g in config.GENERATORS if g in gens]
