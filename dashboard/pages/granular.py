"""Granular page: hourly dispatch (with price on right axis) and cost for the global window."""
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import Input, Output, dcc, html
from plotly.subplots import make_subplots

from dashboard import config
from dashboard.data import access


def layout():
    return html.Div([
        html.H3("Granular prices"),
        html.Div(id="g-kpis", className="mb-3"),
        dcc.Graph(id="g-dispatch"),
        dcc.Graph(id="g-cost"),
        dcc.Graph(id="g-soc"),
    ])


BAT_RUNS = {config.scenario_label(k) for k, s in config.SCENARIOS.items() if "battery" in s}


def soc_figure(w):
    fig = go.Figure()
    for run, g in w.groupby("run", sort=False):
        if run not in BAT_RUNS:
            continue
        fig.add_trace(go.Scatter(x=g["T"], y=g["bat_soc"], name="SOC - %s" % run, mode="lines", fill="tozeroy",
                                 line=dict(color=config.BAT_COLOURS["soc"])))
    if not fig.data:
        fig.update_layout(title="Battery state of charge - select the Batteries scenario", height=200,
                          xaxis_visible=False, yaxis_visible=False)
        return fig
    fig.update_layout(title="Battery state of charge (MWh)", yaxis_title="MWh", xaxis_title="Hour",
                      hovermode="x unified", margin=dict(t=50), height=320)
    return fig


def _kpis(w, gens):
    cols = []
    for run, g in w.groupby("run", sort=False):
        cost = g[["cost_" + x for x in gens]].sum().sum() if gens else 0.0
        items = [("Avg price", "$%.2f" % g["price"].mean()), ("Max price", "$%.2f" % g["price"].max()),
                 ("Min price", "$%.2f" % g["price"].min()), ("Cost (selected gens)", "$%s" % format(cost, ",.0f"))]
        cols.append(dbc.Card(dbc.CardBody([
            html.H6(run, className="card-title"),
            html.Div([html.Span([html.Small(k + ": ", className="text-muted"), html.B(v)], className="me-3")
                      for k, v in items]),
        ]), className="mb-2"))
    return cols


def dispatch_figure(w, gens, battery=True):
    """Per scenario: dispatch panel with its price (DemandMarginal) panel directly underneath."""
    run_list = list(w["run"].unique())
    n = max(len(run_list), 1)
    titles = [t for run in run_list for t in ("%s - dispatch" % run, "%s - price" % run)] or None
    disp = make_subplots(rows=2 * n, cols=1, shared_xaxes=True, subplot_titles=titles,
                         vertical_spacing=0.03 if n > 1 else 0.06, row_heights=[0.65, 0.35] * n)
    for i, run in enumerate(run_list):
        g = w[w["run"] == run]
        dr, pr, first = 2 * i + 1, 2 * i + 2, i == 0
        for gen in gens:
            disp.add_trace(go.Scatter(x=g["T"], y=g[gen], name=gen, stackgroup="r%d" % i,
                                      line=dict(width=0.5, color=config.GEN_COLOURS[gen]),
                                      legendgroup=gen, showlegend=first), row=dr, col=1)
        if battery and run in BAT_RUNS:
            disp.add_trace(go.Scatter(x=g["T"], y=g["bat_discharge"], name="Battery discharge",
                                      stackgroup="r%d" % i, line=dict(width=0.5, color=config.BAT_COLOURS["discharge"]),
                                      legendgroup="bat_dis", showlegend=True), row=dr, col=1)
            disp.add_trace(go.Scatter(x=g["T"], y=-g["bat_charge"], name="Battery charge", fill="tozeroy",
                                      line=dict(width=0.5, color=config.BAT_COLOURS["charge"]),
                                      legendgroup="bat_ch", showlegend=True), row=dr, col=1)
        disp.add_trace(go.Scatter(x=g["T"], y=g["demand"], name="Demand", mode="lines",
                                  line=dict(color="black", dash="dot"), legendgroup="Demand",
                                  showlegend=first), row=dr, col=1)
        disp.update_yaxes(title_text="MWh", row=dr, col=1)
        # Price (DemandMarginal) in its own panel directly under the dispatch
        disp.add_trace(go.Scatter(x=g["T"], y=g["price"], name="Price ($/MWh)", mode="lines",
                                  line_shape="hv", line=dict(color="red", width=1.5),
                                  legendgroup="Price", showlegend=first), row=pr, col=1)
        disp.update_yaxes(title_text="$/MWh", row=pr, col=1)
    disp.update_xaxes(title_text="Hour", row=2 * n, col=1)
    disp.update_layout(title="Dispatch by technology & price (DemandMarginal)", height=450 * n,
                       hovermode="x unified", margin=dict(t=70))
    return disp


def register_callbacks(app):
    @app.callback(
        Output("g-dispatch", "figure"), Output("g-cost", "figure"), Output("g-kpis", "children"),
        Output("g-soc", "figure"),
        Input("scenario", "value"), Input("hours", "value"),
        Input("gens", "value"), Input("caps", "data"),
    )
    def update(scenario, hours, gens, caps):
        df, _ = access.load_selected(scenario, caps)
        if df.empty:
            empty = go.Figure()
            return empty, empty, "No data", empty
        bat = access.show_battery(gens)
        gens = access.selected_gens(gens)
        w, _, _ = access.filter_window(df, 1, hours)

        cost = go.Figure()
        for run, g in w.groupby("run", sort=False):
            y = g[["cost_" + x for x in gens]].sum(axis=1) if gens else g["total_cost"] * 0
            cost.add_trace(go.Scatter(x=g["T"], y=y, name=run, mode="lines"))
        cost.update_layout(title="Hourly cost of selected generators ($)", yaxis_title="$", xaxis_title="Hour",
                           hovermode="x unified", margin=dict(t=50))
        return dispatch_figure(w, gens, bat), cost, _kpis(w, gens), soc_figure(w) if bat else go.Figure()
