"""Diagnostics page: GAMS solve health (.lst), inputs (base_case.gdx) and capacity/price diagnostics.

Sections 1-5, 9, 10 cover the whole scenario; 6-8 follow the global hour window and generator filter.
"""
from pathlib import Path

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, dash_table, dcc, html

from dashboard import config
from dashboard.data import access, diagnostics as D, loader, lst_parser, runner

SECTIONS = [
    ("health", "1. Run health"),
    ("size", "2. Model size"),
    ("inputs", "3. Generator inputs"),
    ("merit", "4. Merit order"),
    ("capacity", "5. Capacity checks (hour window)"),
    ("capvalue", "6. Capacity value - $ saved per extra MW (Qcap marginals, hour window)"),
    ("setter", "7. Price-setter (hour window)"),
    ("info", "8. Scenario files"),
]
INPUTS = [Input("scenario", "value"), Input("hour-start", "value"), Input("hours", "value"), Input("gens", "value"),
          Input("caps", "data")]


def layout():
    return html.Div([
        html.H3("Diagnostics"),
        html.Div(id="d-window", className="fw-bold mb-2"),
        *[dbc.Card([dbc.CardHeader(html.B(t)), dbc.CardBody(html.Div(id="d-" + k))], className="mb-3")
          for k, t in SECTIONS],
    ])


# ---------- helpers ----------
def _fmt(v, f="{:,.2f}"):
    if v is None:
        return "n/a"
    try:
        return f.format(v)
    except (ValueError, TypeError):
        return str(v)


def _stat(label, value, color=None):
    body = html.B(value, className=("text-" + color) if color else "")
    return dbc.Col(dbc.Card(dbc.CardBody([html.Small(label, className="text-muted d-block"), body]),
                            className="h-100"), md=2, className="mb-2")


def _table(df, **kw):
    return dash_table.DataTable(data=df.to_dict("records"), columns=[{"name": c, "id": c} for c in df.columns],
                                style_table={"overflowX": "auto"}, sort_action="native",
                                export_format="csv", **kw)


def _run_block(run, children):
    return html.Div([html.H6(run, className="mt-2")] + list(children))


def _exists(p):
    return "%s%s" % (p, "" if Path(p).exists() else " (missing)")


def _note(msg):
    return html.Div(msg, className="text-muted")


# ---------- sections ----------
def _health(s):
    if s is None:
        return _note("No .lst file for this scenario.")
    ok_solver, ok_model = s.get("solver_status_code") == 1, s.get("model_status_code") in (1, 2)
    infeas = s.get("infeasible")
    return dbc.Row([
        _stat("Solver status", "%s %s" % (s.get("solver_status_code", "?"), s.get("solver_status", "")),
              "success" if ok_solver else "danger"),
        _stat("Model status", "%s %s" % (s.get("model_status_code", "?"), s.get("model_status", "")),
              "success" if ok_model else "danger"),
        _stat("Objective ($)", _fmt(s.get("objective"))),
        _stat("Infeasibilities", _fmt(infeas, "{:d}"), "success" if infeas == 0 else "danger"),
        _stat("Iterations", _fmt(s.get("iterations"), "{:,d}")),
        _stat("Solve / total time (s)", "%s / %s" % (_fmt(s.get("resource_used"), "{:.3f}"),
                                                      _fmt(s.get("execution_time"), "{:.3f}"))),
    ])


RAMP_KEY = "ramping"


def _ramp_inputs(caps=None):
    """Generator inputs table for the ramping scenario - shown regardless of the selected scenario."""
    try:
        p = loader.load_gen_params(RAMP_KEY, caps=caps)
        src = loader.gen_params_source(RAMP_KEY).name
    except Exception as e:  # missing / unreadable input file
        return [_note("Could not load ramping inputs: %s" % e)]
    # ramp_cost always comes from Renewable_intermit.csv (the .gdx does not carry it)
    try:
        csv = pd.read_csv(loader._path(RAMP_KEY, "gen_csv"), skipinitialspace=True)
        csv.columns = [c.strip() for c in csv.columns]
        rc = pd.to_numeric(csv.set_index(csv["gen"].astype(str).str.strip())["ramp_cost"])
        p = p.assign(ramp_cost=rc.reindex(p.index).fillna(0.0).astype(float))
    except Exception:
        if "ramp_cost" not in p.columns:
            p = p.assign(ramp_cost=0.0)
    t = D.inputs_table(p)
    return [_table(t), html.Small("SRMC = vom + cost / eff ($/MWh); ramp_cost in $/MW change. Source: %s" % src,
                                  className="text-muted")]


BAT_KEY = "batteries"
BAT_ROWS = [("cap", "Capacity", "MWh"), ("power", "Power (charge / discharge)", "MW"),
            ("charg_eff", "Charging efficiency", "-"), ("discharge_eff", "Discharging efficiency", "-"),
            ("inita_charge", "Initial (= final) charge", "MWh")]


def battery_inputs_table(base, applied):
    rows = [{"parameter": lab, "unit": unit, "csv": base.get(k), "applied": applied.get(k)}
            for k, lab, unit in BAT_ROWS]
    rows.append({"parameter": "Round-trip efficiency", "unit": "-",
                 "csv": base["charg_eff"] * base["discharge_eff"],
                 "applied": applied["charg_eff"] * applied["discharge_eff"]})
    t = pd.DataFrame(rows)
    t[["csv", "applied"]] = t[["csv", "applied"]].astype(float).round(4)
    return t


def _bat_inputs(caps=None):
    try:
        base = loader.load_bat_params(BAT_KEY)
        applied = loader.load_bat_params(BAT_KEY, caps=runner.normalize(caps))
    except Exception as e:
        return [_note("Could not load battery inputs: %s" % e)]
    t = battery_inputs_table(base, applied)
    changed = [{"if": {"filter_query": "{csv} != {applied}"}, "backgroundColor": "#fff3cd"}]
    return [html.H6("Battery inputs", className="mt-4"), _table(t, style_data_conditional=changed),
            html.Small("csv = %s; applied = values from the sidebar (last Run models). Changed rows highlighted."
                       % config.SCENARIOS[BAT_KEY]["battery"], className="text-muted")]


def _size(s):
    if s is None:
        return _note("No .lst file for this scenario.")
    return dbc.Row([
        _stat("Equation blocks", _fmt(s.get("equation_blocks"), "{:,d}")),
        _stat("Single equations", _fmt(s.get("single_equations"), "{:,d}")),
        _stat("Variable blocks", _fmt(s.get("variable_blocks"), "{:,d}")),
        _stat("Single variables", _fmt(s.get("single_variables"), "{:,d}")),
        _stat("Non-zeros", _fmt(s.get("non_zeros"), "{:,d}")),
        _stat("Model / solver", "%s %s / %s" % (s.get("model", "?"), s.get("model_type", ""), s.get("solver", "?"))),
    ])


def _merit_fig(per_run, window_demand):
    fig = go.Figure()
    for run, params in per_run:
        m = D.merit_order(params)
        xs, ys, text = [], [], []
        for _, r in m.iterrows():
            xs += [r["cum_start"], r["cum_end"]]
            ys += [r["srmc"], r["srmc"]]
            text += [r["gen"], r["gen"]]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name=run, text=text,
                                 hovertemplate="%{text}: $%{y:.2f}/MWh up to %{x:,.0f} MW<extra>" + run + "</extra>"))
        for _, r in m.iterrows():
            fig.add_annotation(x=(r["cum_start"] + r["cum_end"]) / 2, y=r["srmc"], text=r["gen"],
                               showarrow=False, yshift=12)
    lo, hi = window_demand
    if hi is not None:
        fig.add_vrect(x0=lo, x1=hi, fillcolor="grey", opacity=0.15, line_width=0,
                      annotation_text="demand range (window)", annotation_position="top left")
        fig.add_vline(x=hi, line_dash="dot", line_color="red", annotation_text="peak %.0f MW" % hi)
    fig.update_layout(xaxis_title="Cumulative capacity (MW)", yaxis_title="SRMC ($/MWh)",
                      margin=dict(t=30), height=380)
    return fig


def _capacity(run, w, params, gens, bat=None):
    summ, per = D.capacity_checks(w, params, gens, bat=bat)
    cards = dbc.Row([
        _stat("Peak demand (MW)", _fmt(summ["peak_demand"], "{:,.1f}")),
        _stat("Min demand (MW)", _fmt(summ["min_demand"], "{:,.1f}")),
        _stat("Total capacity (MW)" + (" incl. battery power" if bat else ""),
              _fmt(summ["total_capacity"], "{:,.0f}")),
        _stat("Min available (MW)", _fmt(summ["min_available"], "{:,.0f}")),
        _stat("Shortfall hours", _fmt(summ["shortfall_hours"], "{:d}"),
              "success" if summ["shortfall_hours"] == 0 else "danger"),
        _stat("Reserve margin", _fmt(summ["reserve_margin_pct"], "{:.1f}%"),
              "success" if summ["adequate"] else "danger"),
        _stat("Adequate?", "yes" if summ["adequate"] else "NO", "success" if summ["adequate"] else "danger"),
    ])
    fig = px.bar(per, x="gen", y="hours_at_cap", color="gen", color_discrete_map=config.GEN_COLOURS_WITH_BATTERY,
                 text="hours_at_cap", labels={"hours_at_cap": "Hours at available capacity", "gen": ""})
    fig.update_layout(showlegend=False, height=260, margin=dict(t=10))
    extra = []
    if bat:
        extra.append(html.Small("Battery: capacity = %s MWh and power = %s MW from the sidebar. Its power is "
                                "added to the MW totals (upper bound - ignores state of charge); 'hours at "
                                "capacity' = hours discharging at full power." % (
                                    "{:,.0f}".format(bat["cap"]), "{:,.0f}".format(bat["power"])),
                                className="text-muted"))
    return _run_block(run, [cards, dcc.Graph(figure=fig), _table(per.round(2))] + extra)


def _capvalue(run, qcap, w, gens):
    if qcap is None:
        return _run_block(run, [_note("No .lst file for this scenario.")])
    hourly, summ = D.capacity_value(qcap, w, gens)
    fig = go.Figure()
    for g in gens:
        h = hourly[hourly["gen"] == g]
        fig.add_trace(go.Scatter(x=h["T"], y=h["value"], name=g, mode="lines", line_shape="hv",
                                 line=dict(color=config.GEN_COLOURS.get(g))))
    fig.update_layout(yaxis_title="$/MW per hour", xaxis_title="Hour", hovermode="x unified", height=300, margin=dict(t=10))
    return _run_block(run, [dcc.Graph(figure=fig), _table(summ)])


def _setter(run, w, params):
    d = D.price_setter(w, params)
    cmap = config.GEN_COLOURS
    fig = px.bar(d, x="setter", y="hours", color="setter", color_discrete_map=cmap, text="hours",
                 labels={"setter": "", "hours": "Hours setting the price"})
    fig.update_layout(showlegend=False, height=260, margin=dict(t=10))
    return _run_block(run, [dcc.Graph(figure=fig)])


def _info(run, key, s, caps=None):
    root = config.ROOT
    sc = config.SCENARIOS[key]
    src = loader.gen_params_source(key)
    full, gens = runner.normalize(caps), runner.scenario_gens(key)
    cap_text = ", ".join("%s %d" % (g, full[g]) if g in gens else "%s n/a (not in this model)" % g
                         for g in config.CAP_GENERATORS)
    if runner.is_default(caps):
        lst, gdx = _exists(runner.lst_path(key)), _exists(runner.results_path(key))
    else:
        lst = gdx = "in memory (temporary run, not saved)"
    rows = [
        ("Scenario folder", str(root)),
        ("Capacities (MW)", cap_text),
        ("GAMS version", (s or {}).get("gams_version", "n/a")),
        (".lst", lst),
        ("Results .gdx", gdx),
        ("Generator inputs", _exists(src)),
        ("Demand", _exists(root / sc["demand"])),
    ]
    if sc["load_factor"] is not None:
        rows.append(("Load factors", _exists(root / sc["load_factor"])))
    if "battery" in sc:
        try:
            b = loader.load_bat_params(key, caps=full)
            rows.append(("Battery", "%s MWh, %s MW, charge eff %.2f, discharge eff %.2f, initial charge %s MWh"
                         % ("{:,.0f}".format(b["cap"]), "{:,.0f}".format(b["power"]), b["charg_eff"],
                            b["discharge_eff"], "{:,.0f}".format(b.get("inita_charge", 0)))))
        except Exception as e:
            rows.append(("Battery", "could not load: %s" % e))
        rows.append(("Battery inputs", _exists(root / sc["battery"])))
    return _run_block(run, [html.Table([html.Tr([html.Td(k, className="text-muted pe-3"), html.Td(v)])
                                        for k, v in rows], className="small")])


def register_callbacks(app):
    @app.callback([Output("d-window", "children")] + [Output("d-" + k, "children") for k, _ in SECTIONS], *INPUTS)
    def update(scenario, start, hours, gens, caps):
        df, params = access.load_selected(scenario, caps)
        empty = [_note("No data")] * len(SECTIONS)
        if df.empty:
            return ["No data"] + empty
        gens = access.selected_gens(gens)
        w_all, s, last = access.filter_window(df, start, hours)
        keys = {config.scenario_label(k): k for k in config.SCENARIOS}
        out = {k: [] for k, _ in SECTIONS}
        merit_runs = []
        for run in df["run"].unique():
            key = keys[run]
            lst = lst_parser.load_lst(key, caps=caps)
            summary, qcap = (lst if lst else (None, None))
            p = params[run]
            w = w_all[w_all["run"] == run]
            out["health"].append(_run_block(run, [_health(summary)]))
            out["size"].append(_run_block(run, [_size(summary)]))
            merit_runs.append((run, p))
            bat = loader.load_bat_params(key, caps=runner.normalize(caps)) if "battery" in config.SCENARIOS[key] else None
            out["capacity"].append(_capacity(run, w, p, gens, bat))
            out["capvalue"].append(_capvalue(run, qcap, w, gens))
            out["setter"].append(_setter(run, w, p))
            out["info"].append(_info(run, key, summary, caps))
        out["inputs"] = _ramp_inputs(caps) + _bat_inputs(caps)
        dem = (float(w_all["demand"].min()), float(w_all["demand"].max())) if not w_all.empty else (None, None)
        out["merit"] = [dcc.Graph(figure=_merit_fig(merit_runs, dem))]
        label = "Window (sections 5-7): " + access.range_label(s, last)
        return [label] + [out[k] for k, _ in SECTIONS]
