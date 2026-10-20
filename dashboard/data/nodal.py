"""Load the Nodal_SC results gdx into plot-ready tables (cached per file mtime).

Tables returned by load_nodal():
  dispatch  index T (int) x [generators..., SystemPrice, TotalDemand, Unserved]
  lmp       index T x all nodes (LMP in $/MWh)
  key_nodes nodes with demand or a generator (the 25 nodes in LMPrep)
  flows     long df [l, T, Flow, Rating, CongestionPrice, Loading] (Loading % NaN for inf lines)
  gens      df index generator [MC, CAP, NODE]
  kpis      dict of headline numbers
"""
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from dashboard import config

TINY = 1e-9  # gdx EPS comes back as ~2e-16


class NodalMissing(FileNotFoundError):
    pass


def _root(root=None):
    return Path(root or config.ROOT)


def results_path(root=None):
    return _root(root) / config.NODAL["results"]


def _clean(s):
    s = pd.to_numeric(s, errors="coerce").fillna(0.0)
    return s.where(s.abs() > TINY, 0.0)


def read_gens(path):
    df = pd.read_csv(path)
    df = df.rename(columns={df.columns[0]: "gen"}).set_index("gen")
    df.columns = [c.strip().upper() for c in df.columns]
    df["NODE"] = df["NODE"].astype(str)
    return df[["MC", "CAP", "NODE"]]


def _hour(s):
    return pd.to_numeric(s).astype(int)


def build(dfs, gens):
    """dfs: {symbol: DataFrame} as returned by gdxpds. Pure function (tested without GAMS)."""
    d = dfs["Dispatch"].copy()
    d.columns = ["T", "col", "Value"]
    d["T"], d["Value"] = _hour(d["T"]), _clean(d["Value"])
    dispatch = d.pivot_table(index="T", columns="col", values="Value", aggfunc="sum").fillna(0.0)
    for g in gens.index:
        if g not in dispatch:
            dispatch[g] = 0.0
    for c in ("SystemPrice", "TotalDemand", "Unserved"):
        if c not in dispatch:
            dispatch[c] = 0.0
    if "dem" in dfs and (dispatch["TotalDemand"] == 0).all():
        dm = dfs["dem"].copy()
        dispatch["TotalDemand"] = dm.assign(T=_hour(dm["T"])).groupby("T")["Value"].sum()
    dispatch = dispatch.sort_index()

    lm = dfs["LMP"].copy()
    lm["T"], lm["Value"] = _hour(lm["T"]), _clean(lm["Value"])
    lmp = lm.pivot_table(index="T", columns="n", values="Value", aggfunc="sum")
    # nodes missing from LMP (all-zero after EPS) still need a column
    if "ptdf" in dfs:
        for n in set(dfs["ptdf"]["n"]) - set(lmp.columns):
            lmp[n] = 0.0
    lmp = lmp.reindex(dispatch.index).fillna(0.0)

    key = set(dfs["LMPrep"]["n"]) if "LMPrep" in dfs else set()
    key |= set(gens["NODE"])
    if "dem" in dfs:
        key |= set(dfs["dem"]["n"])
    key_nodes = sorted(n for n in key if n in lmp.columns)

    fr = dfs["FlowRep"].copy()
    fr["T"], fr["Value"] = _hour(fr["T"]), _clean(fr["Value"])
    flows = fr.pivot_table(index=["l", "T"], columns="fcol", values="Value", aggfunc="sum").reset_index()
    flows.columns.name = None
    for c in ("Flow", "CongestionPrice"):
        if c not in flows:
            flows[c] = 0.0
    rating = dfs["rating"].set_index("l")["Value"].astype(float)
    flows["Rating"] = flows["l"].map(rating).fillna(np.inf)
    finite = np.isfinite(flows["Rating"]) & (flows["Rating"] > 0)
    flows["Loading"] = np.where(finite, flows["Flow"].abs() / flows["Rating"].where(finite, 1) * 100, np.nan)
    flows = flows[["l", "T", "Flow", "Rating", "CongestionPrice", "Loading"]]

    tot = dfs.get("TOTCost")
    total_cost = float(tot["Level"].iloc[0]) if tot is not None and len(tot) else float(
        sum(dispatch[g] * gens.loc[g, "MC"] for g in gens.index).sum())
    spread = lmp[key_nodes].max(axis=1) - lmp[key_nodes].min(axis=1) if key_nodes else pd.Series(dtype=float)
    kpis = {
        "total_cost": total_cost,
        "cost_per_hour": total_cost / max(len(dispatch), 1),
        "unserved": float(dispatch["Unserved"].sum()),
        "congested_line_hours": int((flows["CongestionPrice"] > 0).sum()),
        "congested_hours": int((spread > 1e-6).sum()),
        "max_spread": float(spread.max()) if len(spread) else 0.0,
        "hours": int(len(dispatch)),
    }
    return {"dispatch": dispatch, "lmp": lmp, "key_nodes": key_nodes, "flows": flows,
            "gens": gens, "kpis": kpis, "ptdf": dfs.get("ptdf"), "dem_nodes": sorted(set(dfs["dem"]["n"]))
            if "dem" in dfs else []}


@lru_cache(maxsize=4)
def _load_cached(path, gen_csv, mtime):
    import gdxpds

    from dashboard.data import topology

    dfs = gdxpds.to_dataframes(path, gams_dir=config.GAMS_DIR)
    data = build(dfs, read_gens(gen_csv))
    data["topology"] = topology.get_topology(data["ptdf"], data["lmp"].columns, Path(gen_csv).parent)
    return data


def load_nodal(root=None):
    path = results_path(root)
    if not path.exists():
        raise NodalMissing("%s not found - run Nodal_SC first." % path)
    return _load_cached(str(path), str(_root(root) / config.NODAL["gen_csv"]), path.stat().st_mtime)


def clear_cache():
    _load_cached.cache_clear()


def line_ranking(flows):
    """Lines ordered by number of congested hours, then total congestion price."""
    g = flows.groupby("l").agg(hours=("CongestionPrice", lambda s: int((s > 0).sum())),
                               price=("CongestionPrice", "sum"),
                               max_loading=("Loading", "max"))
    return g.sort_values(["hours", "price", "max_loading"], ascending=False)
