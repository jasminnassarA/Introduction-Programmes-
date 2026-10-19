"""Summary page: aggregated metrics for the global window, aggregation and generator filter."""
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, dash_table, dcc, html
from plotly.subplots import make_subplots

from dashboard import config
from dashboard.data import access, metrics
from dashboard.data import diagnostics as D

# key -> (card title, short explanation)
PLOTS = {
    "price": ("Hourly price vs percentiles & demand-weighted average",
              "Grey line = hourly price. Flat lines = p10 / p50 (median) / p90 and the "
              "demand-weighted average over the selected window."),
    "share": ("Generation share (whole selected window)",
              "Share of generation by technology, selected generators only."),
    "setter": ("Price-setting hours (whole selected window)",
               "Hours in which each generator's marginal cost set the price. "
               "'Other / tie' = no single generator matched."),
    "cost": ("Cost by technology", "Total generation cost over the selected hours ($)."),
    "cf": ("Capacity factor (%)", "Generation / available capacity (cap x hourly load factor) over the selected hours."),
}

# Rows of the page: (section header, [(key, full_width), ...])
SECTIONS = [
    ("Prices", [("price", True)]),
    ("Generation", [("share", False), ("setter", False)]),
    ("Cost & utilisation", [("cost", False), ("cf", False)]),
]

KPIS = [("min", "Min price"), ("avg", "Average price"), ("dw_avg", "Demand-weighted avg"),
        ("max", "Max price"), ("spread", "Spread (max - min)")]
KPI_COLOURS = {"min": "#2ca02c", "avg": "#333333", "dw_avg": "#1f77b4", "max": "#d62728", "spread": "#9467bd"}

LINES = [("p10", "p10", "#2ca02c", "dot"), ("p50", "p50 median", "#333333", "dash"),
         ("p90", "p90", "#d62728", "dot"), ("dw_avg", "Demand-weighted avg", "#1f77b4", "dashdot")]

SETTER_COLOURS = dict(config.GEN_COLOURS, **{D.OTHER: "#bbbbbb"})

GLOBAL_INPUTS = [Input("scenario", "value"), Input("hour-start", "value"),
                 Input("hours", "value"), Input("gens", "value"), Input("caps", "data")]

HEADER = "mt-3 mb-2 border-bottom pb-1"


def _card(key):
    title, note = PLOTS[key]
    return dbc.Card([
        dbc.CardHeader([html.B(title), html.Div(note, className="text-muted small")]),
        dbc.CardBody(dcc.Graph(id="s-fig-" + key)),
    ], className="mb-3")


def layout():
    body = [
        html.H3("Summary metrics"),
        html.Div(id="s-window", className="fw-bold mb-3"),
        html.H4("Price at a glance (whole selected window, $/MWh)", className=HEADER),
        html.Div(id="s-kpis", className="mb-2"),
    ]
    for header, items in SECTIONS:
        body.append(html.H4(header, className=HEADER))
        body.append(dbc.Row([dbc.Col(_card(k), lg=12 if full else 6) for k, full in items]))
    body.append(html.H4("Summary table", className=HEADER))
    body.append(dbc.Card(dbc.CardBody(dash_table.DataTable(
        id="s-table", export_format="csv", page_size=24,
        style_table={"overflowX": "auto"}, sort_action="native")), className="mb-3"))
    return html.Div(body)


# ---------- calculations ----------

def window_stats(df):
    """{run: {min, avg, dw_avg, max, spread, p10, p50, p90}} over the whole window."""
    out = {}
    for run, r in df.groupby("run", sort=False):
        p, dem = r["price"], r["demand"]
        dtot = dem.sum()
        out[run] = {
            "min": p.min(), "avg": p.mean(), "max": p.max(), "spread": p.max() - p.min(),
            "dw_avg": (p * dem).sum() / dtot if dtot else p.mean(),
            "p10": p.quantile(0.10), "p50": p.quantile(0.50), "p90": p.quantile(0.90),
        }
    return out


# ---------- KPI tiles ----------

def _tile(label, value, colour):
    return dbc.Col(dbc.Card(dbc.CardBody([
        html.Div(label, className="text-muted small text-uppercase"),
        html.Div("$%.2f" % value, style={"fontSize": "1.7rem", "fontWeight": 600, "color": colour}),
    ], className="py-2"), style={"borderTop": "4px solid " + colour}), xs=6, md=4, lg=True, className="mb-2")


def kpi_tiles(df):
    if df.empty:
        return html.Div("No data", className="text-muted")
    stats = window_stats(df)
    multi = len(stats) > 1
    rows = []
    for run, s in stats.items():
        if multi:
            rows.append(html.H6(run, className="mt-2"))
        rows.append(dbc.Row([_tile(lab, s[k], KPI_COLOURS[k]) for k, lab in KPIS]))
    return html.Div(rows)


# ---------- figures ----------

def _style(fig, height=420):
    fig.update_layout(template="plotly_white", height=height, margin=dict(t=40, b=40, l=60, r=20),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title_text=""))
    return fig


def _spread_labels(st, lo, hi, gap_frac=0.09):
    """Label positions sorted by value and pushed apart so none overlap (centred on the originals)."""
    items = sorted(((st[k], name, col) for k, name, col, _ in LINES), key=lambda t: t[0])
    gap = max(hi - lo, 1e-6) * gap_frac
    ys = [items[0][0]]
    for v, _, _ in items[1:]:
        ys.append(max(v, ys[-1] + gap))
    shift = (sum(v for v, _, _ in items) - sum(ys)) / len(ys)
    ys = [y + shift for y in ys]
    # keep any label from dropping below its predecessor after the shift
    for j in range(1, len(ys)):
        ys[j] = max(ys[j], ys[j - 1] + gap)
    return [(v, y, name, col) for (v, name, col), y in zip(items, ys)]


def _price_lines(df):
    """Hourly price per run with flat p10/p50/p90/demand-weighted-average lines; one panel per run."""
    stats = window_stats(df)
    runs = list(stats)
    n = len(runs)
    fig = make_subplots(rows=n, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                        subplot_titles=runs if n > 1 else None)
    for i, run in enumerate(runs, start=1):
        r = df[df["run"] == run]
        x0, x1 = r["T"].min(), r["T"].max()
        fig.add_trace(go.Scatter(x=r["T"], y=r["price"], mode="lines", line_shape="hv",
                                 line=dict(color="#9e9e9e", width=1.2), name="Hourly price",
                                 legendgroup="price", showlegend=(i == 1),
                                 hovertemplate="Hour %{x}<br>$%{y:.2f}/MWh<extra></extra>"),
                      row=i, col=1)
        for key, name, col, dash in LINES:
            v = stats[run][key]
            fig.add_trace(go.Scatter(x=[x0, x1], y=[v, v], mode="lines", name=name,
                                     line=dict(color=col, width=2.5, dash=dash),
                                     legendgroup=key, showlegend=(i == 1),
                                     hovertemplate=name + ": $%.2f<extra></extra>" % v),
                          row=i, col=1)
        yref = "y" if i == 1 else "y%d" % i
        lo = min([float(r["price"].min())] + [stats[run][k] for k, *_ in LINES])
        hi = max([float(r["price"].max())] + [stats[run][k] for k, *_ in LINES])
        for v, ly, name, col in _spread_labels(stats[run], lo, hi):
            fig.add_annotation(x=1.0, xref="paper", y=v, yref=yref, ax=24, axref="pixel",
                               ay=ly, ayref=yref, text="<b>%s $%.2f</b>" % (name, v),
                               showarrow=True, arrowhead=0, arrowwidth=1, arrowcolor=col,
                               xanchor="left", font=dict(color=col, size=11))
        fig.update_yaxes(title_text="$/MWh", row=i, col=1)
    fig.update_xaxes(title_text="Hour", row=n, col=1)
    _style(fig, height=max(420, 340 * n))
    fig.update_layout(margin=dict(t=50, b=40, l=60, r=190), hovermode="closest")
    return fig


def _donuts(runs, labels_vals, colours, unit, centre_fmt):
    n = len(runs)
    fig = make_subplots(rows=1, cols=n, specs=[[{"type": "domain"}] * n])
    for i, run in enumerate(runs, start=1):
        labels, vals = labels_vals[run]
        fig.add_trace(go.Pie(labels=labels, values=vals, hole=0.62, sort=False, name=run,
                             marker=dict(colors=[colours[l] for l in labels],
                                         line=dict(color="white", width=2)),
                             textinfo="label+percent", textposition="outside",
                             hovertemplate="<b>%{label}</b><br>%{value:,.0f} " + unit
                                           + "<br>%{percent}<extra>" + run + "</extra>"),
                      row=1, col=i)
        dom = fig.data[-1].domain
        fig.add_annotation(text=centre_fmt % _compact(sum(vals)), showarrow=False,
                           x=sum(dom.x) / 2, y=sum(dom.y) / 2, xref="paper", yref="paper",
                           xanchor="center", yanchor="middle", font=dict(size=11))
        fig.add_annotation(text="<b>%s</b>" % run, showarrow=False, x=sum(dom.x) / 2, y=-0.12,
                           xref="paper", yref="paper", xanchor="center", yanchor="top",
                           font=dict(size=13))
    _style(fig)
    fig.update_layout(margin=dict(t=70, b=70, l=30, r=30))
    return fig


def _compact(v):
    """Short number so it fits inside the donut hole (e.g. 12.3k, 1.2M)."""
    a = abs(v)
    if a >= 1e6:
        return "%.1fM" % (v / 1e6)
    if a >= 1e4:
        return "%.1fk" % (v / 1e3)
    return "{:,.0f}".format(v)


def _share_pie(df, gens):
    runs = list(df["run"].unique())
    gens = [g for g in config.GENERATORS if g in gens]
    lv = {run: (gens, [float(df.loc[df["run"] == run, g].sum()) for g in gens]) for run in runs}
    return _donuts(runs, lv, config.GEN_COLOURS, "MWh", "<b>%s</b><br>MWh")


def _setter_pie(df, params):
    runs = list(df["run"].unique())
    lv = {}
    for run in runs:
        d = D.price_setter(df[df["run"] == run], params[run])
        d = d[d["hours"] > 0]
        lv[run] = (list(d["setter"]), [int(h) for h in d["hours"]])
    return _donuts(runs, lv, SETTER_COLOURS, "hours", "<b>%s</b><br>hours")


def _figure(key, df, params, gens):
    if df.empty:
        return go.Figure()
    cmap = config.GEN_COLOURS
    if key == "price":
        return _price_lines(df)
    if key == "share":
        return _share_pie(df, gens)
    if key == "setter":
        return _setter_pie(df, params)
    if key == "cost":
        d = metrics.cost_breakdown(df)
        d = d[d["gen"].isin(gens)]
        fig = px.bar(d, x="run", y="cost", color="gen", color_discrete_map=cmap,
                     labels={"cost": "$", "run": ""})
    else:
        d = metrics.capacity_factor(df)
        d = d[d["gen"].isin(gens)]
        fig = px.bar(d, x="run", y="cf", color="gen", barmode="group", color_discrete_map=cmap,
                     labels={"cf": "%", "run": ""})
    fig.update_xaxes(type="category")
    return _style(fig)


def _windowed(scenario, start, hours, caps=None):
    df, params = access.load_selected(scenario, caps)
    if df.empty:
        return df, params
    w, _, _ = access.filter_window(df, start, hours)
    return w, params


def register_callbacks(app):
    for key in PLOTS:
        def make(k):
            @app.callback(Output("s-fig-" + k, "figure"), *GLOBAL_INPUTS)
            def _cb(scenario, start, hours, gens, caps):
                w, params = _windowed(scenario, start, hours, caps)
                return _figure(k, w, params, access.selected_gens(gens))
        make(key)

    @app.callback(Output("s-kpis", "children"), *GLOBAL_INPUTS)
    def kpis(scenario, start, hours, gens, caps):
        w, _ = _windowed(scenario, start, hours, caps)
        return kpi_tiles(w)

    @app.callback(Output("s-table", "data"), Output("s-table", "columns"), Output("s-window", "children"),
                  *GLOBAL_INPUTS)
    def table(scenario, start, hours, gens, caps):
        df, params = access.load_selected(scenario, caps)
        if df.empty:
            return [], [], "No data"
        w, s, last = access.filter_window(df, start, hours)
        label = "Metrics for " + access.range_label(s, last)
        if w.empty:
            return [], [], label
        t = metrics.summary_table(w)
        keep = access.selected_gens(gens)
        t = t.drop(columns=[g + "_mwh" for g in config.GENERATORS if g not in keep])
        return t.to_dict("records"), [{"name": c, "id": c} for c in t.columns], label
