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
    ])


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


def dispatch_figure(w, gens):
    run_list = list(w["run"].unique())
    n = max(len(run_list), 1)
    disp = make_subplots(rows=n, cols=1, shared_xaxes=True, subplot_titles=run_list,
                         vertical_spacing=0.08, specs=[[{"secondary_y": True}]] * n)
    for i, run in enumerate(run_list, start=1):
        g = w[w["run"] == run]
        for gen in gens:
            disp.add_trace(go.Scatter(x=g["T"], y=g[gen], name=gen, stackgroup="r%d" % i,
                                      line=dict(width=0.5, color=config.GEN_COLOURS[gen]),
                                      legendgroup=gen, showlegend=(i == 1)),
                           row=i, col=1, secondary_y=False)
        disp.add_trace(go.Scatter(x=g["T"], y=g["demand"], name="Demand", mode="lines",
                                  line=dict(color="black", dash="dot"), legendgroup="Demand",
                                  showlegend=(i == 1)), row=i, col=1, secondary_y=False)
        disp.update_yaxes(title_text="MWh", row=i, col=1, secondary_y=False)
        # Price (DemandMarginal) on the right axis of every scenario panel
        disp.add_trace(go.Scatter(x=g["T"], y=g["price"], name="Price ($/MWh)", mode="lines",
                                  line_shape="hv", line=dict(color="red", width=1.5),
                                  legendgroup="Price", showlegend=(i == 1)),
                       row=i, col=1, secondary_y=True)
        disp.update_yaxes(title_text="$/MWh", row=i, col=1, secondary_y=True, showgrid=False)
    disp.update_xaxes(title_text="Hour", row=n, col=1)
    disp.update_layout(title="Dispatch by technology & price (DemandMarginal)", height=320 * n,
                       hovermode="x unified", margin=dict(t=70))
    return disp


def register_callbacks(app):
    @app.callback(
        Output("g-dispatch", "figure"), Output("g-cost", "figure"), Output("g-kpis", "children"),
        Input("hour-start", "value"), Input("scenario", "value"), Input("hours", "value"),
        Input("gens", "value"), Input("caps", "data"),
    )
    def update(start, scenario, hours, gens, caps):
        df, _ = access.load_selected(scenario, caps)
        if df.empty:
            empty = go.Figure()
            return empty, empty, "No data"
        gens = access.selected_gens(gens)
        w, _, _ = access.filter_window(df, start, hours)

        cost = go.Figure()
        for run, g in w.groupby("run", sort=False):
            y = g[["cost_" + x for x in gens]].sum(axis=1) if gens else g["total_cost"] * 0
            cost.add_trace(go.Scatter(x=g["T"], y=y, name=run, mode="lines"))
        cost.update_layout(title="Hourly cost of selected generators ($)", yaxis_title="$", xaxis_title="Hour",
                           hovermode="x unified", margin=dict(t=50))
        return dispatch_figure(w, gens), cost, _kpis(w, gens)
