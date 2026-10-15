"""Load GAMS results (via gdxpds / GAMS 25.1) and inputs into a tidy hourly DataFrame."""
from functools import lru_cache
from pathlib import Path

import pandas as pd

from dashboard import config


def read_gen_params(path):
    """base_case.csv -> DataFrame indexed by gen with cost, cap, eff, vom (whitespace stripped)."""
    df = pd.read_csv(path, skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    df["gen"] = df["gen"].astype(str).str.strip()
    df = df.set_index("gen")
    return df.apply(lambda s: pd.to_numeric(s.astype(str).str.strip()))


def read_demand(path):
    """demand(in).csv -> Series indexed by integer hour T."""
    df = pd.read_csv(path)
    df.columns = ["T", "demand"]
    return df.set_index("T")["demand"].astype(float)


def read_results_gdx(path):
    """Return long DataFrame (T, outfield, Value) for ExcelResults."""
    import gdxpds  # imported lazily so pure functions are testable without GAMS

    dfs = gdxpds.to_dataframes(str(path), gams_dir=config.GAMS_DIR)
    df = dfs[config.RESULTS_SYMBOL]
    df.columns = ["T", "outfield", "Value"]
    return df


def build_hourly(results_long, demand, gen_params, start=None, run="current"):
    """Combine long results, demand and generator params into one hourly frame."""
    start = config.START_DATETIME if start is None else pd.Timestamp(start)
    r = results_long.copy()
    r["T"] = r["T"].astype(int)
    wide = r.pivot_table(index="T", columns="outfield", values="Value", aggfunc="sum")
    # GDX omits zeros: make sure every hour and every column exists.
    hours = range(1, int(max(wide.index.max(), demand.index.max())) + 1)
    wide = wide.reindex(hours)
    for col in ["DemandMarginal"] + config.GENERATORS:
        if col not in wide.columns:
            wide[col] = 0.0
    wide = wide.fillna(0.0)

    df = pd.DataFrame(index=wide.index)
    df.index.name = "T"
    df["price"] = wide["DemandMarginal"]
    for g in config.GENERATORS:
        df[g] = wide[g]
    df["demand"] = demand.reindex(df.index).fillna(0.0)
    df["generation"] = df[config.GENERATORS].sum(axis=1)

    for g in config.GENERATORS:
        p = gen_params.loc[g]
        df["cost_" + g] = df[g] * (p["vom"] + p["cost"] / p["eff"])
    df["total_cost"] = df[["cost_" + g for g in config.GENERATORS]].sum(axis=1)

    df = df.reset_index()
    df.insert(0, "datetime", start + pd.to_timedelta(df["T"] - 1, unit="h"))
    df["run"] = run
    return df


@lru_cache(maxsize=32)
def _load_cached(run_dir, mtime, run, start):
    run_dir = Path(run_dir)
    return build_hourly(
        read_results_gdx(run_dir / config.RESULTS_GDX),
        read_demand(run_dir / config.DEMAND_CSV),
        load_gen_params(run_dir),
        start=start,
        run=run,
    )


def gen_params_from_long(long_df):
    """Long (gen, field, Value) -> DataFrame indexed by gen with cost, cap, eff, vom (missing -> 0)."""
    d = long_df.copy()
    d.columns = ["gen", "field", "Value"]
    wide = d.pivot_table(index="gen", columns="field", values="Value", aggfunc="sum")
    for c in ("cost", "cap", "eff", "vom"):
        if c not in wide.columns:
            wide[c] = 0.0
    wide = wide[["cost", "cap", "eff", "vom"]].fillna(0.0).astype(float)
    wide.index = wide.index.astype(str).str.strip()
    wide.index.name = "gen"
    wide.columns.name = None
    return wide


def read_gen_params_gdx(path):
    """base_case.gdx (symbol data_in) -> same frame as read_gen_params."""
    import gdxpds

    return gen_params_from_long(gdxpds.to_dataframes(str(path), gams_dir=config.GAMS_DIR)[config.GEN_SYMBOL])


def gen_params_source(run_dir):
    """Path of the inputs file load_gen_params uses (gdx preferred, csv fallback)."""
    gdx = Path(run_dir) / config.GEN_GDX
    return gdx if gdx.exists() else Path(run_dir) / config.GEN_CSV


def load_gen_params(run_dir):
    src = gen_params_source(run_dir)
    if src.suffix.lower() == ".gdx":
        try:
            return read_gen_params_gdx(src)
        except Exception:
            pass
    return read_gen_params(Path(run_dir) / config.GEN_CSV)


def load_run(run_dir, run="current"):
    """Load a run directory (repo root or runs/<label>). Cached on gdx mtime."""
    run_dir = Path(run_dir)
    mtime = (run_dir / config.RESULTS_GDX).stat().st_mtime
    return _load_cached(str(run_dir), mtime, run, str(config.START_DATETIME)).copy()
