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
    """Cost per run and generator; battery scenarios get a Battery row at $0 (no battery cost in the model)."""
    cols = ["cost_" + g for g in config.GENERATORS]
    long = df.melt(id_vars=["run"], value_vars=cols, var_name="gen", value_name="cost")
    long["gen"] = long["gen"].str.replace("cost_", "", regex=False)
    out = long.groupby(["run", "gen"], as_index=False, sort=False)["cost"].sum()
    bat_runs = [r for r in df["run"].unique() if r in battery_runs()]
    if bat_runs:
        out = pd.concat([out, pd.DataFrame({"run": bat_runs, "gen": BATTERY, "cost": 0.0})], ignore_index=True)
    return out


BATTERY = "Battery"


def battery_runs():
    return {config.scenario_label(k) for k, s in config.SCENARIOS.items() if "battery" in s}


def capacity_factor(df, bat_power=None):
    """CF = generation / available energy (cap x load factor, summed over window hours).
    bat_power {run: MW}: adds a Battery row = MWh discharged / (power MW x hours in window)."""
    rows = []
    for run, r in df.groupby("run", sort=False):
        for g in config.GENERATORS:
            avail = r["avail_" + g].sum()
            rows.append({"run": run, "gen": g, "cf": 100.0 * r[g].sum() / avail if avail > 0 else 0.0})
        if bat_power is not None and run in bat_power:
            avail = float(bat_power[run]) * len(r)
            dis = float(r["bat_discharge"].sum()) if "bat_discharge" in r.columns else 0.0
            rows.append({"run": run, "gen": BATTERY, "cf": 100.0 * dis / avail if avail > 0 else 0.0})
    return pd.DataFrame(rows, columns=["run", "gen", "cf"])


BAT_CHARGE = "Battery charge"
BAT_DISCHARGE = "Battery discharge"


def _weighted_price(price, mwh):
    tot = float(mwh.sum())
    return float((price * mwh).sum()) / tot if tot > 1e-9 else float("nan")


def capture_price(df, gens=None, battery=False):
    """Capture price per run and technology = sum(price x MWh) / sum(MWh) ($/MWh); NaN if no output.
    capture_rate = capture price / time-weighted average price (%).
    battery=True adds 'Battery charge' / 'Battery discharge' rows (average price paid / earned) for runs
    that have battery flows."""
    gens = [g for g in config.GENERATORS if gens is None or g in gens]
    rows = []
    for run, r in df.groupby("run", sort=False):
        p = r["price"]
        avg = float(p.mean()) if len(p) else float("nan")
        items = [(g, r[g]) for g in gens]
        if battery and "bat_charge" in r.columns and float(r["bat_charge"].abs().sum() + r["bat_discharge"].abs().sum()) > 1e-9:
            items += [(BAT_CHARGE, r["bat_charge"]), (BAT_DISCHARGE, r["bat_discharge"])]
        for name, mwh in items:
            cp = _weighted_price(p, mwh)
            rate = 100.0 * cp / avg if avg and avg == avg else float("nan")
            rows.append({"run": run, "gen": name, "capture_price": cp, "avg_price": avg,
                         "capture_rate": rate, "mwh": float(mwh.sum())})
    return pd.DataFrame(rows, columns=["run", "gen", "capture_price", "avg_price", "capture_rate", "mwh"])


def battery_prices(df):
    """Average charge / discharge price and arbitrage spread ($/MWh) for one run's battery flows."""
    ch = _weighted_price(df["price"], df["bat_charge"])
    dis = _weighted_price(df["price"], df["bat_discharge"])
    return {"charge_price": ch, "discharge_price": dis, "arbitrage": dis - ch}


def unserved_curtailed(df):
    """Unserved = max(demand - generation, 0); curtailed = available - dispatched for Solar and Wind."""
    d = df.copy()
    supply = d["generation"] + (d["net_battery"] if "net_battery" in d.columns else 0.0)
    d["unserved"] = (d["demand"] - supply).clip(lower=0)
    d["curtailed_solar"] = (d["avail_Solar"] - d["Solar"]).clip(lower=0)
    d["curtailed_wind"] = (d["avail_Wind"] - d["Wind"]).clip(lower=0)
    return d.groupby("run", as_index=False, sort=False)[["unserved", "curtailed_solar", "curtailed_wind"]].sum()


def battery_summary(df, bat):
    """Battery KPIs over the window: charged, discharged, losses, equivalent full cycles, peak SOC."""
    ch, dis = float(df["bat_charge"].sum()), float(df["bat_discharge"].sum())
    cap = float((bat or {}).get("cap", 0.0))
    return {
        "charged": ch, "discharged": dis, "losses": ch - dis,
        "cycles": dis / cap if cap else 0.0,
        "peak_soc": float(df["bat_soc"].max()) if len(df) else 0.0,
        "charge_hours": int((df["bat_charge"] > 1e-6).sum()),
        "discharge_hours": int((df["bat_discharge"] > 1e-6).sum()),
    }


def summary_table(df):
    ps = price_stats(df)
    agg = df.groupby("run", as_index=False, sort=False).agg(
        hours=("T", "count"), demand_mwh=("demand", "sum"), generation_mwh=("generation", "sum"),
        total_cost=("total_cost", "sum"))
    for g in config.GENERATORS:
        agg[g + "_mwh"] = df.groupby("run", sort=False)[g].sum().values
    if "bat_discharge" in df.columns:
        agg["bat_charge_mwh"] = df.groupby("run", sort=False)["bat_charge"].sum().values
        agg["bat_discharge_mwh"] = df.groupby("run", sort=False)["bat_discharge"].sum().values
    ren = {"avg": "avg_price", "max": "max_price", "min": "min_price"}
    ren.update({"p%d" % q: "p%d_price" % q for q in PERCENTILES})
    out = ps.rename(columns=ren).merge(agg, on="run")
    return out.round(2)
