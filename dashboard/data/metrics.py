"""Aggregation functions for the summary page (whole selected window, per scenario)."""
import pandas as pd

from dashboard import config

PERCENTILES = (10, 50, 90)


def price_stats(df):
    g = df.groupby("run", sort=False)["price"]
    out = g.agg(avg="mean", max="max", min="min")
    out["spread"] = out["max"] - out["min"]
    for q in PERCENTILES:
        out["p%d" % q] = g.quantile(q / 100.0)
    return out.reset_index()


def generation_mix(df):
    long = df.melt(id_vars=["run"], value_vars=config.GENERATORS, var_name="gen", value_name="mwh")
    out = long.groupby(["run", "gen"], as_index=False, sort=False)["mwh"].sum()
    tot = out.groupby("run")["mwh"].transform("sum")
    out["share"] = (out["mwh"] / tot.where(tot != 0)).fillna(0.0) * 100
    return out


def cost_breakdown(df):
    cols = ["cost_" + g for g in config.GENERATORS]
    long = df.melt(id_vars=["run"], value_vars=cols, var_name="gen", value_name="cost")
    long["gen"] = long["gen"].str.replace("cost_", "", regex=False)
    return long.groupby(["run", "gen"], as_index=False, sort=False)["cost"].sum()


def capacity_factor(df):
    """CF = generation / available energy (cap x load factor, summed over window hours)."""
    rows = []
    for run, r in df.groupby("run", sort=False):
        for g in config.GENERATORS:
            avail = r["avail_" + g].sum()
            rows.append({"run": run, "gen": g, "cf": 100.0 * r[g].sum() / avail if avail > 0 else 0.0})
    return pd.DataFrame(rows, columns=["run", "gen", "cf"])


def unserved_curtailed(df):
    """Unserved = max(demand - generation, 0); curtailed = available - dispatched for Solar and Wind."""
    d = df.copy()
    d["unserved"] = (d["demand"] - d["generation"]).clip(lower=0)
    d["curtailed_solar"] = (d["avail_Solar"] - d["Solar"]).clip(lower=0)
    d["curtailed_wind"] = (d["avail_Wind"] - d["Wind"]).clip(lower=0)
    return d.groupby("run", as_index=False, sort=False)[["unserved", "curtailed_solar", "curtailed_wind"]].sum()


def summary_table(df):
    ps = price_stats(df)
    agg = df.groupby("run", as_index=False, sort=False).agg(
        hours=("T", "count"), demand_mwh=("demand", "sum"), generation_mwh=("generation", "sum"),
        total_cost=("total_cost", "sum"))
    for g in config.GENERATORS:
        agg[g + "_mwh"] = df.groupby("run", sort=False)[g].sum().values
    ren = {"avg": "avg_price", "max": "max_price", "min": "min_price"}
    ren.update({"p%d" % q: "p%d_price" % q for q in PERCENTILES})
    out = ps.rename(columns=ren).merge(agg, on="run")
    return out.round(2)
