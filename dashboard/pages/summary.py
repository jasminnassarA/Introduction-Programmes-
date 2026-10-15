"""Summary page: aggregated metrics for the global window, aggregation and generator filter."""
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, dash_table, dcc, html
from plotly.subplots import make_subplots

from dashboard import config
from dashboard.data import access, metrics

PLOTS = [
    ("price", "Price statistics (incl. spread = max - min, p10/p50/p90)"),
    ("pricebox", "Price distribution (box: p25-p75, line: p50, whiskers: p10-p90)"),
    ("mix", "Generation mix"),
    ("share", "Generation share (% of all generation)"),
    ("cost", "Cost by technology"),
    ("cf", "Capacity factor (%)"),
    ("uc", "Unserved energy & curtailed solar (proxy)"),
]

GLOBAL_INPUTS = [Input("run-store", "data"), Input("date-start", "date"),
                 Input("days", "value"), Input("freq", "value"), Input("gens", "value")]


def _card(key, title):
    return dbc.Card([
        dbc.CardHeader(html.B(title)),
        dbc.CardBody(dcc.Graph(id="s-fig-" + key)),
    ], className="mb-3")


def layout():
    return html.Div([
        html.H3("Summary metrics"),
        html.Div(id="s-window", className="fw-bold mb-1"),
        html.P("Curtailed solar = solar capacity - solar dispatch (no availability profile in inputs). "
               "Unserved = demand - generation (expected 0).", className="text-muted small"),
        dbc.Row([dbc.Col(_card(k, t), lg=6) for k, t in PLOTS]),
        dbc.Card([
            dbc.CardHeader(html.B("Summary table")),
            dbc.CardBody(dash_table.DataTable(id="s-table", export_format="csv", page_size=24,
                                              style_table={"overflowX": "auto"},
                                              sort_action="native")),
        ], className="mb-3"),
    ])


def _facet(fig):
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    fig.update_layout(margin=dict(t=40), legend_title_text="")
    return fig


def _figure(key, df, params, freq, gens):
    if df.empty:
        return go.Figure()
    xlab = metrics.FREQS.get(freq, "Period")
    cmap = config.GEN_COLOURS
    if key == "price":
        d = metrics.price_stats(df, freq).melt(id_vars=["run", "period"], var_name="stat", value_name="$/MWh")
        fig = px.bar(d, x="period", y="$/MWh", color="stat", barmode="group", facet_col="run")
    elif key == "pricebox":
        return _price_box(df, freq, xlab)
    elif key in ("mix", "share"):
        d = metrics.generation_mix(df, freq)
        d = d[d["gen"].isin(gens)]
        y, lab = ("mwh", "MWh") if key == "mix" else ("share", "%")
        fig = px.bar(d, x="period", y=y, color="gen", facet_col="run",
                     color_discrete_map=cmap, labels={y: lab})
    elif key == "cost":
        d = metrics.cost_breakdown(df, freq)
        d = d[d["gen"].isin(gens)]
        fig = px.bar(d, x="period", y="cost", color="gen", facet_col="run",
                     color_discrete_map=cmap, labels={"cost": "$"})
    elif key == "cf":
        d = metrics.capacity_factor(df, params, freq)
        d = d[d["gen"].isin(gens)]
        fig = px.bar(d, x="period", y="cf", color="gen", barmode="group", facet_col="run",
                     color_discrete_map=cmap, labels={"cf": "%"})
    else:
        d = metrics.unserved_curtailed(df, params, freq).melt(
            id_vars=["run", "period"], var_name="metric", value_name="MWh")
        fig = px.bar(d, x="period", y="MWh", color="metric", barmode="group", facet_col="run")
    fig.update_xaxes(title_text=xlab, type="category")
    return _facet(fig)


def _price_box(df, freq, xlab):
    """Box per period/run from hourly prices; whiskers at p10/p90 (not Tukey fences)."""
    d = metrics.add_period(df, freq)
    q = d.groupby(["run", "period"])["price"].quantile([0.10, 0.25, 0.50, 0.75, 0.90]).unstack()
    runs = list(d["run"].unique())
    fig = make_subplots(rows=1, cols=len(runs), shared_yaxes=True, subplot_titles=runs)
    for i, run in enumerate(runs, start=1):
        r = q.loc[run]
        x = list(r.index)
        fig.add_trace(go.Box(x=x, q1=list(r[0.25]), median=list(r[0.50]), q3=list(r[0.75]),
                             lowerfence=list(r[0.10]), upperfence=list(r[0.90]),
                             name=run, marker_color="#d62728", showlegend=False,
                             hovertemplate="%{x}<extra>" + run + "</extra>"),
                      row=1, col=i)
    fig.update_xaxes(title_text=xlab, type="category")
    fig.update_yaxes(title_text="$/MWh", col=1)
    fig.update_layout(margin=dict(t=40))
    return fig


def _windowed(runs, start, days):
    df, params = access.load_selected(runs)
    if df.empty or not start:
        return df.iloc[0:0] if not df.empty else df, params
    w, _, _ = access.filter_window(df, start, days)
    return w, params


def register_callbacks(app):
    for key, _ in PLOTS:
        def make(k):
            @app.callback(Output("s-fig-" + k, "figure"), *GLOBAL_INPUTS)
            def _cb(runs, start, days, freq, gens):
                w, params = _windowed(runs, start, days)
                return _figure(k, w, params, freq or "M", access.selected_gens(gens))
        make(key)

    @app.callback(Output("s-table", "data"), Output("s-table", "columns"), Output("s-window", "children"),
                  *GLOBAL_INPUTS)
    def table(runs, start, days, freq, gens):
        df, params = access.load_selected(runs)
        if df.empty or not start:
            return [], [], "No data"
        w, s, last = access.filter_window(df, start, days)
        label = "Metrics for " + access.range_label(s, last)
        if w.empty:
            return [], [], label
        t = metrics.summary_table(w, params, freq or "M")
        keep = access.selected_gens(gens)
        t = t.drop(columns=[g + "_mwh" for g in config.GENERATORS if g not in keep])
        return t.to_dict("records"), [{"name": c, "id": c} for c in t.columns], label
