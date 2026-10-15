"""Diagnostics page: GAMS solve health (.lst), inputs (base_case.gdx) and capacity/price diagnostics.

Sections 1-5, 9, 10 cover the whole run; 6-8 follow the global date window and generator filter.
"""
import datetime as dt
from pathlib import Path

import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, dash_table, dcc, html

from dashboard import config
from dashboard.data import access, diagnostics as D, loader, lst_parser, versions

SECTIONS = [
    ("health", "1. Run health"),
    ("objective", "2. Objective cross-check (.lst vs recomputed from .gdx + inputs)"),
    ("size", "3. Model size"),
    ("inputs", "4. Generator inputs (base_case)"),
    ("merit", "5. Merit order"),
    ("capacity", "6. Capacity checks (date window)"),
    ("capvalue", "7. Capacity value - $ saved per extra MW (Qcap marginals, date window)"),
    ("setter", "8. Price-setter (date window)"),
    ("compare", "9. Run comparison"),
    ("info", "10. Run info"),
]
INPUTS = [Input("run-store", "data"), Input("date-start", "date"), Input("days", "value"), Input("gens", "value")]


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


def _mtime(p):
    p = Path(p)
    if not p.exists():
        return "missing"
    return dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def _note(msg):
    return html.Div(msg, className="text-muted")


# ---------- sections ----------
def _health(s):
    if s is None:
        return _note("No .lst file for this run.")
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


def _objective(chk):
    if chk["objective"] is None:
        return _note("No objective in .lst - recomputed cost $%s" % _fmt(chk["recomputed"]))
    return dbc.Row([
        _stat("Check", "PASS" if chk["ok"] else "FAIL", "success" if chk["ok"] else "danger"),
        _stat(".lst objective ($)", _fmt(chk["objective"])),
        _stat("Recomputed ($)", _fmt(chk["recomputed"])),
        _stat("Difference ($)", _fmt(chk["diff"])),
        _stat("Difference (%)", _fmt(chk["diff_pct"], "{:.4f}%")),
    ])


def _size(s):
    if s is None:
        return _note("No .lst file for this run.")
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


def _capacity(run, w, params, gens):
    summ, per = D.capacity_checks(w, params, gens)
    cards = dbc.Row([
        _stat("Peak demand (MW)", _fmt(summ["peak_demand"], "{:,.1f}")),
        _stat("Min demand (MW)", _fmt(summ["min_demand"], "{:,.1f}")),
        _stat("Total capacity (MW)", _fmt(summ["total_capacity"], "{:,.0f}")),
        _stat("Reserve margin", _fmt(summ["reserve_margin_pct"], "{:.1f}%"),
              "success" if summ["adequate"] else "danger"),
        _stat("Adequate?", "yes" if summ["adequate"] else "NO", "success" if summ["adequate"] else "danger"),
    ])
    fig = px.bar(per, x="gen", y="hours_at_cap", color="gen", color_discrete_map=config.GEN_COLOURS,
                 text="hours_at_cap", labels={"hours_at_cap": "Hours at full capacity", "gen": ""})
    fig.update_layout(showlegend=False, height=260, margin=dict(t=10))
    return _run_block(run, [cards, dcc.Graph(figure=fig), _table(per.round(2))])


def _capvalue(run, qcap, w, gens):
    if qcap is None:
        return _run_block(run, [_note("No .lst file for this run.")])
    hourly, summ = D.capacity_value(qcap, w, gens)
    fig = go.Figure()
    for g in gens:
        h = hourly[hourly["gen"] == g]
        fig.add_trace(go.Scatter(x=h["datetime"], y=h["value"], name=g, mode="lines", line_shape="hv",
                                 line=dict(color=config.GEN_COLOURS.get(g))))
    fig.update_layout(yaxis_title="$/MW per hour", hovermode="x unified", height=300, margin=dict(t=10))
    return _run_block(run, [dcc.Graph(figure=fig), _table(summ)])


def _setter(run, w, params):
    d = D.price_setter(w, params)
    cmap = dict(config.GEN_COLOURS, **{D.OTHER: "#bbbbbb"})
    fig = px.bar(d, x="setter", y="hours", color="setter", color_discrete_map=cmap, text="hours",
                 labels={"setter": "", "hours": "Hours setting the price"})
    fig.update_layout(showlegend=False, height=260, margin=dict(t=10))
    return _run_block(run, [dcc.Graph(figure=fig)])


def _compare_info(params, s, chk):
    info = {}
    costs = D.srmc(params)
    for g in params.index:
        for f in ("cap", "eff", "vom", "cost"):
            info["%s %s" % (g, f)] = params.loc[g, f]
        info[g + " SRMC"] = round(costs[g], 4)
    s = s or {}
    info["objective"] = s.get("objective")
    info["recomputed cost"] = round(chk["recomputed"], 2)
    info["model status"] = s.get("model_status")
    info["iterations"] = s.get("iterations")
    return info


def _info(run, path, s):
    lst = Path(path) / config.LST_FILE
    rows = [
        ("Run directory", str(path)),
        ("GAMS version", (s or {}).get("gams_version", "n/a")),
        ("Solve date (from .lst)", (s or {}).get("solve_date", "n/a")),
        (".lst", "%s (modified %s)" % (lst, _mtime(lst))),
        ("Results .gdx", "%s (modified %s)" % (Path(path) / config.RESULTS_GDX, _mtime(Path(path) / config.RESULTS_GDX))),
        ("Generator inputs", "%s (modified %s)" % (loader.gen_params_source(path), _mtime(loader.gen_params_source(path)))),
        ("Demand", "%s (modified %s)" % (Path(path) / config.DEMAND_CSV, _mtime(Path(path) / config.DEMAND_CSV))),
    ]
    note = versions.read_meta(path).get("note")
    if note:
        rows.append(("Snapshot note", note))
    return _run_block(run, [html.Table([html.Tr([html.Td(k, className="text-muted pe-3"), html.Td(v)])
                                        for k, v in rows], className="small")])


def register_callbacks(app):
    @app.callback([Output("d-window", "children")] + [Output("d-" + k, "children") for k, _ in SECTIONS], *INPUTS)
    def update(runs, start, days, gens):
        df, params = access.load_selected(runs)
        empty = [_note("No data")] * len(SECTIONS)
        if df.empty:
            return ["No data"] + empty
        gens = access.selected_gens(gens)
        w_all, s, last = access.filter_window(df, start, days)
        paths = dict(versions.list_runs())
        out = {k: [] for k, _ in SECTIONS}
        merit_runs, compare = [], {}
        for run in df["run"].unique():
            path = paths[run]
            lst = lst_parser.load_lst(path)
            summary, qcap = (lst if lst else (None, None))
            p = params[run]
            full, w = df[df["run"] == run], w_all[w_all["run"] == run]
            chk = D.objective_check(full, (summary or {}).get("objective"))
            out["health"].append(_run_block(run, [_health(summary)]))
            out["objective"].append(_run_block(run, [_objective(chk)]))
            out["size"].append(_run_block(run, [_size(summary)]))
            out["inputs"].append(_run_block(run, [_table(D.inputs_table(p)),
                                                  html.Small("SRMC = vom + cost / eff ($/MWh). Source: %s"
                                                             % loader.gen_params_source(path).name,
                                                             className="text-muted")]))
            merit_runs.append((run, p))
            out["capacity"].append(_capacity(run, w, p, gens))
            out["capvalue"].append(_capvalue(run, qcap, w, gens))
            out["setter"].append(_setter(run, w, p))
            out["info"].append(_info(run, path, summary))
            compare[run] = _compare_info(p, summary, chk)
        dem = (float(w_all["demand"].min()), float(w_all["demand"].max())) if not w_all.empty else (None, None)
        out["merit"] = [dcc.Graph(figure=_merit_fig(merit_runs, dem))]
        out["compare"] = ([_table(D.compare_runs(compare),
                                  style_data_conditional=[{"if": {"filter_query": '{changed} = "yes"'},
                                                           "backgroundColor": "#fff3cd"}])]
                          if len(compare) > 1 else [_note("Select 2 or more runs in the sidebar to compare.")])
        label = "Window (sections 6-8): " + access.range_label(s, last)
        return [label] + [out[k] for k, _ in SECTIONS]
