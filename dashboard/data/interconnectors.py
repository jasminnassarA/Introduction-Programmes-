"""Read the Interconnectors.gms results (Results\\Interconnectors_<N>.gdx) into plain DataFrames.

build(dfs) is pure (dict of gdxpds DataFrames -> data dict) so it can be tested without GAMS:
    regions   list of active regions, e.g. ["R1", "R2"]
    dispatch  {region: DataFrame T x COLS}   generation per gen, Demand, Import, Export, Unserved (MWh)
    price     DataFrame T x region           balance marginal ($/MWh)
    flows     long DataFrame [frm, to, T, Flow, Cap, Loss]   directed flows (MWh sent)
    links     DataFrame [a, b, cap, loss, name]   undirected links between active regions (a < b)
    net       DataFrame T x link name         net flow a -> b (positive = a exports to b)
    caps      DataFrame region x gen          installed capacity (MW)
    total_cost  float ($, TOTCost)
"""
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from dashboard import config

TINY = 1e-9
COLS = config.IC_GENERATORS + ["Demand", "Import", "Export", "Unserved"]


class IcMissing(FileNotFoundError):
    pass


def _clean(s):
    s = pd.to_numeric(s, errors="coerce").fillna(0.0)
    return s.where(s.abs() > TINY, 0.0)


def link_name(a, b):
    return "%s-%s" % (a, b)


def build(dfs):
    price_df = dfs["Price"].copy()
    price_df.columns = ["r", "T", "Value"]
    if "ra" in dfs and not dfs["ra"].empty:
        regions = sorted(dfs["ra"].iloc[:, 0].astype(str).unique())
    else:
        regions = sorted(price_df["r"].astype(str).unique())

    d = dfs["Dispatch"].copy()
    d.columns = ["r", "T", "col", "Value"]
    d["T"] = d["T"].astype(int)
    d["Value"] = _clean(d["Value"])
    hours = sorted(d["T"].unique())
    dispatch = {}
    for r in regions:
        p = d[d["r"] == r].pivot_table(index="T", columns="col", values="Value", aggfunc="sum")
        dispatch[r] = p.reindex(index=hours, columns=COLS).fillna(0.0)

    price_df["T"] = price_df["T"].astype(int)
    price_df["Value"] = _clean(price_df["Value"])
    price = price_df.pivot_table(index="T", columns="r", values="Value", aggfunc="sum")
    price = price.reindex(index=hours, columns=regions).fillna(0.0)

    ic = dfs["icdata"].copy()
    ic.columns = ["frm", "to", "lf", "Value"]
    ic = ic.pivot_table(index=["frm", "to"], columns="lf", values="Value", aggfunc="sum").fillna(0.0)
    for c in ("cap", "loss", "cost"):
        if c not in ic:
            ic[c] = 0.0

    rows = []
    for i, a in enumerate(regions):
        for b in regions[i + 1:]:
            cap = max(ic["cap"].get((a, b), 0.0), ic["cap"].get((b, a), 0.0))
            if cap > 0:
                rows.append({"a": a, "b": b, "cap": cap, "loss": ic["loss"].get((a, b), 0.0),
                             "name": link_name(a, b)})
    links = pd.DataFrame(rows, columns=["a", "b", "cap", "loss", "name"])

    f = dfs.get("FlowRep", pd.DataFrame(columns=["r", "rr", "T", "Value"])).copy()
    f.columns = ["frm", "to", "T", "Flow"]
    f["T"] = f["T"].astype(int)
    f["Flow"] = _clean(f["Flow"])
    f = f[f["frm"].isin(regions) & f["to"].isin(regions)]
    f["Cap"] = [ic["cap"].get((a, b), 0.0) for a, b in zip(f["frm"], f["to"])]
    f["Loss"] = [ic["loss"].get((a, b), 0.0) for a, b in zip(f["frm"], f["to"])]
    flows = f.reset_index(drop=True)

    net = pd.DataFrame(0.0, index=hours, columns=list(links["name"]))
    for _, l in links.iterrows():
        fwd = flows[(flows["frm"] == l.a) & (flows["to"] == l.b)].set_index("T")["Flow"]
        bwd = flows[(flows["frm"] == l.b) & (flows["to"] == l.a)].set_index("T")["Flow"]
        net[l["name"]] = fwd.reindex(hours).fillna(0.0) - bwd.reindex(hours).fillna(0.0)

    g = dfs["gdata"].copy()
    g.columns = ["r", "gen", "f", "Value"]
    caps = g[g["f"] == "cap"].pivot_table(index="r", columns="gen", values="Value", aggfunc="sum")
    caps = caps.reindex(index=regions, columns=config.IC_GENERATORS).fillna(0.0)

    tot = dfs.get("TOTCost")
    total_cost = float(tot["Level"].iloc[0]) if tot is not None and "Level" in tot and len(tot) else float("nan")

    return {"regions": regions, "dispatch": dispatch, "price": price, "flows": flows, "links": links,
            "net": net, "caps": caps, "total_cost": total_cost, "hours": hours}


def read_gdx(path):
    import gdxpds  # lazy: tests don't need GAMS

    return build(gdxpds.to_dataframes(str(path), gams_dir=config.GAMS_DIR))


def results_path(n, root=None):
    return Path(root or config.ROOT) / config.ic_path("results", n)


@lru_cache(maxsize=4)
def _load_cached(path, mtime):
    return read_gdx(path)


def load(n, root=None):
    path = results_path(n, root)
    if not path.exists():
        raise IcMissing("%s not found - run models\\Interconnectors.gms --regions=%d" % (path, n))
    return _load_cached(str(path), path.stat().st_mtime)


def clear_cache():
    _load_cached.cache_clear()


# ---------------- derived tables ----------------

def window(data, lo, hi):
    return [t for t in data["hours"] if lo <= t <= hi]


def link_usage(data, lo, hi):
    """DataFrame T x link name: |net flow| / cap in %."""
    net = data["net"].loc[lo:hi]
    caps = data["links"].set_index("name")["cap"]
    return net.abs().div(caps.reindex(net.columns), axis=1) * 100.0


def congestion_table(data, lo, hi):
    """Per link: hours at limit (>= 99.9% of cap) and mean |price gap| across it."""
    use = link_usage(data, lo, hi)
    pr = data["price"].loc[lo:hi]
    rows = []
    for _, l in data["links"].iterrows():
        gap = (pr[l.b] - pr[l.a]).abs().mean() if len(pr) else 0.0
        rows.append({"name": l["name"], "hours": int((use[l["name"]] >= 99.9).sum()), "gap": float(gap)})
    return pd.DataFrame(rows, columns=["name", "hours", "gap"])


def kpis(data, lo, hi):
    f = data["flows"]
    f = f[(f["T"] >= lo) & (f["T"] <= hi)]
    unserved = sum(data["dispatch"][r].loc[lo:hi, "Unserved"].sum() for r in data["regions"])
    cong = congestion_table(data, lo, hi)
    return {"total_cost": data["total_cost"], "unserved": float(unserved),
            "traded": float(f["Flow"].sum()) / 1000.0, "losses": float((f["Flow"] * f["Loss"]).sum()),
            "cong_hours": int(cong["hours"].sum()) if len(cong) else 0}


def avg_day(data, lo, hi):
    """DataFrame hour-of-day (0-23) x region: mean net export (MW)."""
    out = {}
    for r in data["regions"]:
        d = data["dispatch"][r].loc[lo:hi]
        net = d["Export"] - d["Import"]
        out[r] = net.groupby((np.asarray(net.index) - 1) % 24).mean()
    return pd.DataFrame(out).reindex(range(24))
