"""Load GAMS results (via gdxpds / GAMS 25.1) and inputs into a tidy hourly DataFrame (hour T only)."""
from functools import lru_cache
from pathlib import Path

import pandas as pd

from dashboard import config

PARAM_FIELDS = ["cost", "cap", "eff", "vom"]
OPTIONAL_FIELDS = ["ramp_cost"]  # kept when present in the inputs (ramping scenario)
BAT_COLUMNS = {"Bat_Charge": "bat_charge", "Bat_Discharge": "bat_discharge", "Bat_SOC": "bat_soc"}


def _fields(cols):
    return PARAM_FIELDS + [c for c in OPTIONAL_FIELDS if c in cols]


def complete_params(params):
    """Ensure every config generator exists (missing -> cap 0, eff 1, costs 0)."""
    missing = [g for g in config.GENERATORS if g not in params.index]
    if not missing:
        return params[_fields(params.columns)].astype(float)
    fields = _fields(params.columns)
    extra = pd.DataFrame({"cost": 0.0, "cap": 0.0, "eff": 1.0, "vom": 0.0, "ramp_cost": 0.0}, index=missing)[fields]
    p = pd.concat([params[fields], extra])
    p.index.name = "gen"
    return p.astype(float)


def read_gen_params(path):
    """Generator csv -> DataFrame indexed by gen with cost, cap, eff, vom (whitespace stripped)."""
    df = pd.read_csv(path, skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    df["gen"] = df["gen"].astype(str).str.strip()
    df = df.set_index("gen")
    return df.apply(lambda s: pd.to_numeric(s.astype(str).str.strip()))[_fields(df.columns)]


def read_demand(path):
    """demand csv -> Series indexed by integer hour T."""
    df = pd.read_csv(path)
    df.columns = ["T", "demand"]
    return df.set_index("T")["demand"].astype(float)


def read_load_factor(path):
    """normalisedloads.csv (Hour, gen columns) -> DataFrame indexed by T, one column per gen."""
    df = pd.read_csv(path, skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns={df.columns[0]: "T"}).set_index("T")
    df.index = df.index.astype(int)
    return df.astype(float)


def read_results_gdx(path):
    """Return long DataFrame (T, outfield, Value) for ExcelResults."""
    import gdxpds  # imported lazily so pure functions are testable without GAMS

    dfs = gdxpds.to_dataframes(str(path), gams_dir=config.GAMS_DIR)
    df = dfs[config.RESULTS_SYMBOL]
    df.columns = ["T", "outfield", "Value"]
    return df


def plant_cost_from_long(long_df):
    """Long (gen, T, Value) PlantCost -> wide DataFrame indexed by T, one column per generator."""
    d = long_df.copy()
    d = d.iloc[:, :3]
    d.columns = ["gen", "T", "Value"]
    d["gen"] = d["gen"].astype(str).str.strip()
    d["T"] = d["T"].astype(int)
    return d.pivot_table(index="T", columns="gen", values="Value", aggfunc="sum").astype(float)


def read_plant_cost_gdx(path):
    """PlantCost levels (T x gen) from a results gdx, or None if the gdx does not contain it."""
    import gdxpds

    try:
        dfs = gdxpds.to_dataframes(str(path), gams_dir=config.GAMS_DIR)
    except Exception:
        return None
    df = dfs.get(config.PLANTCOST_SYMBOL)
    if df is None or df.empty:
        return None
    # Variables come with Level/Marginal/... columns; keep the level.
    level = [c for c in df.columns if str(c).lower() == "level"]
    if level:
        df = df[[df.columns[0], df.columns[1], level[0]]]
    return plant_cost_from_long(df)


def build_hourly(results_long, demand, gen_params, run="base", load_factor=None, ramp=False,
                 plant_cost=None):
    """Combine long results, demand, generator params and optional load factors into one hourly frame.

    plant_cost (T x gen, GAMS PlantCost levels) is used as the generator cost when given, so the
    dashboard shows exactly what GAMS optimised (total_cost = Cost(T), summing to TOTCost).
    Without it the cost is recomputed: vom*U + cost*U/eff, and with ramp=True also
    ramp_cost * |U(t) - U(t-1)| for t > 1 (no ramp cost in hour 1, matching QPlant's $(ord(T)>1)).
    """
    params = complete_params(gen_params)
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
    # Battery (only the batteries model writes these; zeros elsewhere)
    for src, dst in BAT_COLUMNS.items():
        df[dst] = wide[src] if src in wide.columns else 0.0
    df["net_battery"] = df["bat_discharge"] - df["bat_charge"]

    for g in config.GENERATORS:
        p = params.loc[g]
        fuel = p["cost"] / p["eff"] if p["eff"] else 0.0
        df["cost_" + g] = df[g] * (p["vom"] + fuel)
        if ramp:
            rc = float(p.get("ramp_cost", 0.0) or 0.0)
            df["ramp_" + g] = df[g].diff().fillna(0.0).abs()
            df["cost_" + g] += rc * df["ramp_" + g]
        if plant_cost is not None:
            gams = plant_cost[g] if g in plant_cost.columns else pd.Series(0.0, index=plant_cost.index)
            # GDX omits zero levels -> missing hours are 0 cost.
            df["cost_" + g] = gams.reindex(df.index).fillna(0.0).astype(float)
        lf = 1.0
        if load_factor is not None and g in load_factor.columns:
            lf = load_factor[g].reindex(df.index).fillna(0.0)
        df["avail_" + g] = p["cap"] * lf
    df["total_cost"] = df[["cost_" + g for g in config.GENERATORS]].sum(axis=1)

    df = df.reset_index()
    df["run"] = run
    return df


def gen_params_from_long(long_df):
    """Long (gen, field, Value) -> DataFrame indexed by gen with cost, cap, eff, vom (missing -> 0)."""
    d = long_df.copy()
    d.columns = ["gen", "field", "Value"]
    wide = d.pivot_table(index="gen", columns="field", values="Value", aggfunc="sum")
    for c in PARAM_FIELDS:
        if c not in wide.columns:
            wide[c] = 0.0
    wide = wide[_fields(wide.columns)].fillna(0.0).astype(float)
    wide.index = wide.index.astype(str).str.strip()
    wide.index.name = "gen"
    wide.columns.name = None
    return wide


def read_gen_params_gdx(path):
    import gdxpds

    return gen_params_from_long(gdxpds.to_dataframes(str(path), gams_dir=config.GAMS_DIR)[config.GEN_SYMBOL])


def _path(key, item, root=None):
    rel = config.SCENARIOS[key][item]
    return None if rel is None else Path(root or config.ROOT) / rel


def gen_params_source(key, root=None):
    """Inputs file used for a scenario (gdx preferred, csv fallback)."""
    gdx = _path(key, "gen_gdx", root)
    return gdx if gdx.exists() else _path(key, "gen_csv", root)


def load_gen_params(key, root=None, caps=None):
    """Generator params for a scenario with capacities from caps applied ({gen: MW} or None)."""
    src = gen_params_source(key, root)
    raw = None
    if src.suffix.lower() == ".gdx":
        try:
            raw = read_gen_params_gdx(src)
        except Exception:
            raw = None
    if raw is None:
        raw = read_gen_params(_path(key, "gen_csv", root))
    return with_caps(complete_params(raw), caps, gens=list(raw.index))


def with_caps(params, caps, gens=None):
    """Return params with each generator's cap replaced by caps[gen].

    Only generators in gens (those the scenario's model actually has) are changed, so e.g. the
    base case keeps Wind at 0 whatever the Wind capacity. caps None -> unchanged.
    """
    if not caps:
        return params
    p = params.copy()
    for g, c in caps.items():
        if c is not None and g in p.index and (gens is None or g in gens):
            p.loc[g, "cap"] = float(c)
    return p


def load_bat_params(key, root=None, caps=None):
    """Battery settings {cap, power, charg_eff, discharge_eff, inita_charge} with caps applied,
    or None if the scenario has no battery."""
    rel = config.SCENARIOS[key].get("battery")
    if rel is None:
        return None
    df = pd.read_csv(Path(root or config.ROOT) / rel, skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    row = df.iloc[0]
    out = {c: float(str(row[c]).strip()) for c in df.columns[1:]}
    for name, (col, _, _) in config.BAT_PARAMS.items():
        if caps and caps.get(name) is not None:
            out[col] = float(caps[name])
    return out


def _build(key, root, results_long, caps, plant_cost=None):
    lf_path = _path(key, "load_factor", root)
    return build_hourly(
        results_long,
        read_demand(_path(key, "demand", root)),
        load_gen_params(key, root, caps),
        run=config.scenario_label(key),
        load_factor=read_load_factor(lf_path) if lf_path is not None else None,
        ramp=config.SCENARIOS[key].get("ramp", False),
        plant_cost=plant_cost,
    )


@lru_cache(maxsize=32)
def _load_cached(key, root, results, mtime):
    return _build(key, root, read_results_gdx(results), None, read_plant_cost_gdx(results))


def load_scenario(key, root=None, caps=None):
    """Hourly frame for a scenario key at the given capacities.

    Base capacities: original Results/ gdx (cached on path + mtime).  Otherwise the in-memory
    results of a temporary GAMS run (solved on first use, see runner.get_results).
    """
    from dashboard.data import runner

    root = str(root or config.ROOT)
    entry = runner.get_results(caps, root)
    if entry is None:
        results = runner.results_path(key, root)
        return _load_cached(key, root, str(results), results.stat().st_mtime).copy()
    item = entry[key]
    if "hourly" not in item:
        item["hourly"] = _build(key, root, item["results"], runner.normalize(caps, root),
                                item.get("plant_cost"))
    return item["hourly"].copy()
