"""Aggregation functions for the summary page (pure pandas, unit-tested)."""
import pandas as pd

from dashboard import config

FREQS = {"M": "Month", "Y": "Year"}
PERCENTILES = (10, 50, 90)


def add_period(df, freq):
    out = df.copy()
    fmt = "%Y-%m" if freq == "M" else "%Y"
    out["period"] = out["datetime"].dt.strftime(fmt)
    return out


def price_stats(df, freq):
    d = add_period(df, freq)
    g = d.groupby(["run", "period"])["price"]
    out = g.agg(avg="mean", max="max", min="min")
    out["spread"] = out["max"] - out["min"]
    for q in PERCENTILES:
        out["p%d" % q] = g.quantile(q / 100.0)
    return out.reset_index()


def generation_mix(df, freq):
    d = add_period(df, freq)
    long = d.melt(id_vars=["run", "period"], value_vars=config.GENERATORS,
                  var_name="gen", value_name="mwh")
    out = long.groupby(["run", "period", "gen"], as_index=False)["mwh"].sum()
    tot = out.groupby(["run", "period"])["mwh"].transform("sum")
    out["share"] = (out["mwh"] / tot.where(tot != 0)).fillna(0.0) * 100
    return out


def cost_breakdown(df, freq):
    d = add_period(df, freq)
    cols = ["cost_" + g for g in config.GENERATORS]
    long = d.melt(id_vars=["run", "period"], value_vars=cols, var_name="gen", value_name="cost")
    long["gen"] = long["gen"].str.replace("cost_", "", regex=False)
    return long.groupby(["run", "period", "gen"], as_index=False)["cost"].sum()


def capacity_factor(df, params_by_run, freq):
    """CF = generation / (capacity * hours in period)."""
    gm = generation_mix(df, freq)
    hours = add_period(df, freq).groupby(["run", "period"]).size().rename("hours").reset_index()
    gm = gm.merge(hours, on=["run", "period"])
    gm["cap"] = [params_by_run[r].loc[g, "cap"] for r, g in zip(gm["run"], gm["gen"])]
    gm["cf"] = (gm["mwh"] / (gm["cap"] * gm["hours"]).where(gm["cap"] > 0)).fillna(0.0) * 100
    return gm[["run", "period", "gen", "cf"]]


def unserved_curtailed(df, params_by_run, freq):
    """Unserved = max(demand - generation, 0); curtailed solar proxy = solar cap - solar dispatch."""
    d = add_period(df, freq)
    d["unserved"] = (d["demand"] - d["generation"]).clip(lower=0)
    d["curtailed_solar"] = [
        max(params_by_run[r].loc["Solar", "cap"] - s, 0.0) for r, s in zip(d["run"], d["Solar"])
    ]
    return d.groupby(["run", "period"], as_index=False)[["unserved", "curtailed_solar"]].sum()


def summary_table(df, params_by_run, freq):
    ps = price_stats(df, freq)
    d = add_period(df, freq)
    agg = d.groupby(["run", "period"], as_index=False).agg(
        demand_mwh=("demand", "sum"), generation_mwh=("generation", "sum"),
        total_cost=("total_cost", "sum"))
    for g in config.GENERATORS:
        agg[g + "_mwh"] = d.groupby(["run", "period"])[g].sum().values
    uc = unserved_curtailed(df, params_by_run, freq)
    ren = {"avg": "avg_price", "max": "max_price", "min": "min_price"}
    ren.update({"p%d" % q: "p%d_price" % q for q in PERCENTILES})
    out = ps.rename(columns=ren)
    out = out.merge(agg, on=["run", "period"]).merge(uc, on=["run", "period"])
    return out.round(2)
