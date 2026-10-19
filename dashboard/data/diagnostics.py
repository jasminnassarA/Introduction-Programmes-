"""Pure calculations for the Diagnostics page (no GAMS / Dash needed)."""
import pandas as pd



def srmc(params):
    """Short-run marginal cost $/MWh = vom + fuel cost / eff."""
    eff = params["eff"].where(params["eff"] != 0)
    return (params["vom"] + (params["cost"] / eff).fillna(0.0)).rename("srmc")


def active(params):
    """Generators that actually exist in a scenario (cap > 0)."""
    return params[params["cap"] > 0]


def inputs_table(params):
    params = active(params)
    t = params.copy()
    t["srmc"] = srmc(params)
    return t.reset_index().round(4)


def merit_order(params):
    params = active(params)
    m = params[["cap"]].copy()
    m["srmc"] = srmc(params)
    m = m.sort_values("srmc", kind="mergesort")
    m["cum_end"] = m["cap"].cumsum()
    m["cum_start"] = m["cum_end"] - m["cap"]
    return m.reset_index()


def objective_check(df_run, objective, tol_pct=0.01):
    """Compare .lst objective with total cost recomputed from the .gdx + inputs (whole run)."""
    recomputed = float(df_run["total_cost"].sum())
    if objective is None:
        return {"recomputed": recomputed, "objective": None, "diff": None, "diff_pct": None, "ok": None}
    diff = recomputed - objective
    pct = 100.0 * diff / objective if objective else 0.0
    return {"recomputed": recomputed, "objective": objective, "diff": diff, "diff_pct": pct,
            "ok": abs(pct) <= tol_pct}


def _avail(w, params, g):
    """Hourly available capacity (cap x load factor) - falls back to nameplate cap."""
    col = "avail_" + g
    if col in w.columns:
        return w[col]
    return pd.Series(float(params.loc[g, "cap"]) if g in params.index else 0.0, index=w.index)


BATTERY = "Battery"


def capacity_checks(w, params, gens=None, tol=1e-6, bat=None):
    """Adequacy vs nameplate and vs hourly available capacity; hours each gen ran at its available limit.

    bat = battery settings {cap (MWh), power (MW), ...}: its power (MW) is added to the MW totals and a
    Battery row (capacity in MWh, hours at full discharge power / empty / full) is appended.
    """
    gens = list(active(params).index) if gens is None else [g for g in gens if g in active(params).index]
    power = float(bat["power"]) if bat else 0.0
    cap_total = float(params["cap"].sum()) + power
    peak = float(w["demand"].max()) if not w.empty else 0.0
    low = float(w["demand"].min()) if not w.empty else 0.0
    avail_total = (sum(_avail(w, params, g) for g in params.index) + power
                   if not w.empty else pd.Series(dtype=float))
    short = int((avail_total < w["demand"] - tol).sum()) if not w.empty else 0
    summary = {"peak_demand": peak, "min_demand": low, "total_capacity": cap_total,
               "min_available": float(avail_total.min()) if not w.empty else 0.0,
               "shortfall_hours": short,
               "reserve_margin_pct": 100.0 * (cap_total - peak) / peak if peak else None,
               "adequate": cap_total >= peak and short == 0}
    rows = []
    for g in gens:
        cap = float(params.loc[g, "cap"])
        av = _avail(w, params, g)
        full = int(((w[g] >= av - tol) & (av > 0)).sum()) if cap > 0 else 0
        rows.append({"gen": g, "cap": cap, "avg_available": float(av.mean()) if len(av) else 0.0,
                     "hours_at_cap": full,
                     "pct_hours": 100.0 * full / len(w) if len(w) else 0.0,
                     "max_output": float(w[g].max()) if not w.empty else 0.0})
    if bat:
        n = len(w)
        dis = w["bat_discharge"] if "bat_discharge" in w.columns else pd.Series(0.0, index=w.index)
        soc = w["bat_soc"] if "bat_soc" in w.columns else pd.Series(0.0, index=w.index)
        full = int((dis >= power - tol).sum()) if power > 0 else 0
        rows.append({"gen": BATTERY, "cap": power, "avg_available": power, "hours_at_cap": full,
                     "pct_hours": 100.0 * full / n if n else 0.0,
                     "max_output": float(dis.max()) if n else 0.0,
                     "energy_cap_mwh": float(bat["cap"]),
                     "hours_empty": int((soc <= tol).sum()),
                     "hours_full": int((soc >= float(bat["cap"]) - 1e-3).sum())})
    return summary, pd.DataFrame(rows)


def capacity_value(qcap, w, gens):
    """Value of +1 MW per gen/hour = -Qcap marginal, restricted to window hours and ticked gens."""
    if qcap is None or qcap.empty or w.empty:
        return pd.DataFrame(columns=["gen", "T", "value"]), pd.DataFrame(
            columns=["gen", "binding_hours", "avg_value_when_binding", "total_value_per_mw"])
    q = qcap[qcap["gen"].isin(gens)].copy()
    q["value"] = -q["marginal"]
    hourly = q.merge(w[["T"]].drop_duplicates(), on="T", how="inner")
    rows = []
    for g in gens:
        v = hourly.loc[hourly["gen"] == g, "value"]
        b = v[v > 1e-9]
        rows.append({"gen": g, "binding_hours": int(len(b)),
                     "avg_value_when_binding": float(b.mean()) if len(b) else 0.0,
                     "total_value_per_mw": float(v.sum())})
    return hourly[["gen", "T", "value"]], pd.DataFrame(rows).round(2)


def price_setter(w, params, tol=1e-6):
    """Hours per price-setting generator (marginal unit rule; the battery never sets the price).

    1. Most expensive generator that is partly loaded (0 < output < available) - includes ramp-cost hours.
    2. All running gens at their limit and the battery discharging: the setter of the battery's
       charging hours (most expensive marginal unit among window hours where it charges).
    3. Fallback: most expensive generator running that hour (cheapest active gen if none run).
    """
    costs = srmc(active(params))
    order = list(costs.sort_values(ascending=False, kind="mergesort").index)  # expensive first
    counts = {g: 0 for g in costs.sort_values(kind="mergesort").index}
    if w.empty or not order:
        return pd.DataFrame({"setter": list(counts), "hours": list(counts.values())})
    out = {g: (w[g] if g in w.columns else pd.Series(0.0, index=w.index)) for g in order}
    av = {g: _avail(w, params, g) for g in order}
    zero = pd.Series(0.0, index=w.index)
    charge = w["bat_charge"] if "bat_charge" in w.columns else zero
    discharge = w["bat_discharge"] if "bat_discharge" in w.columns else zero

    def marginal(i):
        return next((g for g in order if tol < out[g].loc[i] < av[g].loc[i] - tol), None)

    def running(i):
        return next((g for g in order if out[g].loc[i] > tol), order[-1])

    marg = {i: marginal(i) for i in w.index}
    ch_setters = [marg[i] for i in w.index if charge.loc[i] > tol and marg[i] is not None]
    bat_setter = next((g for g in order if g in ch_setters), None)
    for i in w.index:
        g = marg[i]
        if g is None:
            g = bat_setter if (discharge.loc[i] > tol and bat_setter) else running(i)
        counts[g] += 1
    return pd.DataFrame({"setter": list(counts), "hours": list(counts.values())})


def compare_runs(info):
    """info: {run: {metric: value}} -> DataFrame metric x run plus 'changed' flag."""
    df = pd.DataFrame(info)
    df.index.name = "metric"
    df["changed"] = df.apply(lambda r: "yes" if r.astype(str).nunique() > 1 else "", axis=1)
    return df.reset_index()
