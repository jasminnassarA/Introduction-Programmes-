"""Load the scenario(s) chosen in the sidebar, plus shared global filters (hours only)."""
import pandas as pd

from dashboard import config
from dashboard.data import loader, runner

MIN_HOURS = 24
MAX_HOURS = 744


def load_selected(scenario, caps=None):
    """Return (hourly df for the chosen scenario(s), {scenario label: gen_params}).

    caps = applied capacities {gen: MW}; non-base capacities are solved once per session in memory.
    """
    try:
        runner.get_results(caps)
    except (runner.GamsRunError, OSError) as e:
        runner.last_status = "Error: %s" % e
        return pd.DataFrame(), {}
    frames, params = [], {}
    for key in config.scenario_keys(scenario):
        try:
            frames.append(loader.load_scenario(key, caps=caps))
        except (OSError, KeyError):
            continue
        params[config.scenario_label(key)] = loader.load_gen_params(key, caps=caps)
    if not frames:
        return pd.DataFrame(), {}
    return pd.concat(frames, ignore_index=True), params


def clamp_hours(value):
    """Clamp to MIN_HOURS..MAX_HOURS; fall back to config.WINDOW_HOURS if missing/invalid."""
    try:
        h = int(value)
    except (TypeError, ValueError):
        return config.WINDOW_HOURS
    return min(max(h, MIN_HOURS), MAX_HOURS)


def clamp_start(start, hours, max_t):
    """Clamp start hour so it is in 1..max(1, max_t - hours + 1)."""
    try:
        s = int(start)
    except (TypeError, ValueError):
        s = 1
    return min(max(s, 1), max(1, int(max_t) - hours + 1))


def filter_window(df, start, hours):
    """Return (window df, start hour, last hour present in window or None)."""
    hours = clamp_hours(hours)
    try:
        s = int(start)
    except (TypeError, ValueError):
        s = 1
    w = df[(df["T"] >= s) & (df["T"] < s + hours)]
    last = int(w["T"].max()) if not w.empty else None
    return w, s, last


def range_label(s, last):
    if last is None:
        return "No data in window"
    return "Hour %d to Hour %d" % (s, last)


def selected_gens(gens):
    """Ticked generators in config.GENERATORS order (None -> all)."""
    if gens is None:
        return list(config.GENERATORS)
    return [g for g in config.GENERATORS if g in gens]
