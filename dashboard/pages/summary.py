"""Summary page: aggregated metrics for the global window, aggregation and generator filter."""
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, dash_table, dcc, html
from plotly.subplots import make_subplots

from dashboard import config
from dashboard.data import access, loader, metrics
from dashboard.data import diagnostics as D

# key -> (card title, short explanation)
PLOTS = {
    "price": ("Hourly price vs percentiles & demand-weighted average",
              "Grey line = hourly price. Flat lines = p10 / p50 (median) / p90 and the "
              "demand-weighted average over the selected window."),
    "share": ("Generation share (whole selected window)",
              "Share of generation by technology, selected generators only. Battery = energy discharged. "
              "Percentages on the slices, names in the legend below."),
    "setter": ("Price-setting hours (whole selected window)",
               "Price setter = the most expensive generator that is partly loaded in that hour (includes "
               "hours where a ramp cost is added). Hours supplied by the battery are credited to the generator "
               "that set the price when it charged. The battery itself has no cost and never sets the price."),
    "cost": ("Cost by technology", "Total generation cost over the selected hours ($). "
                                   "The model gives batteries no operating cost (assumption A4), so Battery = $0."),
    "cf": ("Capacity factor (%)", "Generation / available capacity (cap x hourly load factor) over the selected hours. "
                                  "Battery = MWh discharged / (battery power MW x hours)."),
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

SETTER_COLOURS = config.GEN_COLOURS

GLOBAL_INPUTS = [Input("scenario", "value"),
                 Input("hours", "value"), Input("gens", "value"), Input("caps", "data")]

HEADER = "mt-3 mb-2 border-bottom pb-1"


def _card(key):
    title, note = PLOTS[key]
    body = [dcc.Graph(id="s-fig-" + key)]
    return dbc.Card([
        dbc.CardHeader([html.B(title), html.Div(note, className="text-muted small")]),
        dbc.CardBody(body),
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
        body.append(dbc.Row([dbc.Col(_card(k), id="s-col-" + k, lg=12 if full else 6) for k, full in items]))
    body.append(html.H4("Battery (whole selected window)", className=HEADER))
    body.append(html.Div(id="s-battery", className="mb-2"))
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


SMALL_SLICE = 0.03  # slices below 3% show their label on hover / in the legend only


def _spread_small(labels, vals):
    """Reorder so small slices sit between big ones (keeps outside labels of small slices apart)."""
    order = sorted(range(len(vals)), key=lambda i: -vals[i])
    big, small = order[:(len(order) + 1) // 2], order[(len(order) + 1) // 2:][::-1]
    idx = [i for pair in zip(big, small + [None] * len(big)) for i in pair if i is not None]
    return [labels[i] for i in idx], [vals[i] for i in idx]


def _donuts(runs, labels_vals, colours, unit, centre_fmt, label_all=False):
    """label_all=True labels every non-zero slice (small ones outside, spread apart).
    Compare mode (>1 run): 2-column grid, larger donuts; a number stays inside its slice when it fits,
    otherwise Plotly puts it outside with a connector line to the slice."""
    n = len(runs)
    multi = n > 1
    cols = 2 if multi else 1
    rows = (n + cols - 1) // cols
    fig = make_subplots(rows=rows, cols=cols, specs=[[{"type": "domain"}] * cols] * rows,
                        horizontal_spacing=0.2, vertical_spacing=0.2 if multi else 0.0)
    for i, run in enumerate(runs):
        labels, vals = labels_vals[run]
        if label_all:
            labels, vals = _spread_small(labels, vals)
        tot = float(sum(vals)) or 1.0
        if multi:
            # "auto": inside if the number fits, else outside with a line to the slice; zero slices: no text
            pos = ["auto" if v > 0 else "none" for v in vals]
        else:
            small = 0.0 if label_all else SMALL_SLICE
            # big slices: label inside; mid slices: outside; tiny slices: no text (hover + legend)
            pos = ["inside" if v / tot >= 0.12 else "outside" if v / tot > small or (label_all and v > 0)
                   else "none" for v in vals]
        fig.add_trace(go.Pie(labels=labels, values=vals, hole=0.5 if multi else 0.55, sort=False, name=run,
                             marker=dict(colors=[colours.get(l, "#999999") for l in labels],
                                         line=dict(color="white", width=2)),
                             texttemplate="%{percent:.1%}", textposition=pos,
                             insidetextorientation="horizontal", textfont=dict(size=13 if multi else 12),
                             outsidetextfont=dict(color="#333333"),
                             automargin=True, insidetextfont=dict(color="white"),
                             hovertemplate="<b>%{label}</b><br>%{value:,.0f} " + unit
                                           + "<br>%{percent}<extra>" + run + "</extra>"),
                      row=i // cols + 1, col=i % cols + 1)
        dom = fig.data[-1].domain
        fig.add_annotation(text=centre_fmt % _compact(sum(vals)), showarrow=False,
                           x=sum(dom.x) / 2, y=sum(dom.y) / 2, xref="paper", yref="paper",
                           xanchor="center", yanchor="middle", font=dict(size=13 if multi else 11))
        fig.add_annotation(text="<b>%s</b>" % run, showarrow=False, x=sum(dom.x) / 2,
                           y=dom.y[0] - (0.04 if multi else 0.06),
                           xref="paper", yref="paper", xanchor="center", yanchor="top",
                           font=dict(size=14 if multi else 13))
    if multi:
        _style(fig, height=450 * rows + 100)
        fig.update_layout(margin=dict(t=60, b=120, l=80, r=80),
                          legend=dict(orientation="h", yanchor="top", y=-0.1, x=0.5, xanchor="center",
                                      title_text=""))
        return fig
    _style(fig, height=480)
    # legend (coloured square + name) in a row under the donuts; slices only carry the percentage
    fig.update_layout(margin=dict(t=50, b=110, l=50, r=50), uniformtext=dict(minsize=10, mode="show"),
                      legend=dict(orientation="h", yanchor="top", y=-0.18, x=0.5, xanchor="center",
                                  title_text=""))
    return fig


def _compact(v):
    """Short number so it fits inside the donut hole (e.g. 12.3k, 1.2M)."""
    a = abs(v)
    if a >= 1e6:
        return "%.1fM" % (v / 1e6)
    if a >= 1e4:
        return "%.1fk" % (v / 1e3)
    return "{:,.0f}".format(v)


def share_values(df, gens, battery=True):
    """{run: (labels, MWh)} - selected generators plus Battery (MWh discharged) for battery scenarios."""
    gens = [g for g in config.GENERATORS if g in gens]
    out = {}
    for run in df["run"].unique():
        r = df[df["run"] == run]
        labels, vals = list(gens), [float(r[g].sum()) for g in gens]
        if battery and run in metrics.battery_runs() and "bat_discharge" in r.columns:
            labels.append(metrics.BATTERY)
            vals.append(float(r["bat_discharge"].sum()))
        out[run] = (labels, vals)
    return out


def _share_pie(df, gens, battery=True):
    lv = share_values(df, gens, battery)
    return _donuts(list(lv), lv, config.GEN_COLOURS_WITH_BATTERY, "MWh", "<b>%s</b><br>MWh", label_all=True)


def _setter_pie(df, params):
    runs = list(df["run"].unique())
    lv = {}
    for run in runs:
        d = D.price_setter(df[df["run"] == run], params[run])
        d = d[d["hours"] > 0]
        lv[run] = (list(d["setter"]), [int(h) for h in d["hours"]])
    return _donuts(runs, lv, SETTER_COLOURS, "hours", "<b>%s</b><br>hours", label_all=True)


def _figure(key, df, params, gens, battery=True, bat_power=None):
    if df.empty:
        return go.Figure()
    if key == "price":
        return _price_lines(df)
    if key == "share":
        return _share_pie(df, gens, battery)
    if key == "setter":
        return _setter_pie(df, params)
    if key == "cost":
        d = metrics.cost_breakdown(df)
        d = d[d["gen"].isin(list(gens) + ([metrics.BATTERY] if battery else []))]
        fig = px.bar(d, x="run", y="cost", color="gen", color_discrete_map=config.GEN_COLOURS_WITH_BATTERY,
                     labels={"cost": "$", "run": ""})
        for tr in fig.data:
            if tr.name == metrics.BATTERY:  # zero-height bar: label it so it's visible
                tr.update(text=["$0"] * len(tr.x), textposition="outside", cliponaxis=False)
    else:
        d = metrics.capacity_factor(df, bat_power if battery else None)
        d = d[d["gen"].isin(list(gens) + ([metrics.BATTERY] if battery else []))]
        fig = px.bar(d, x="run", y="cf", color="gen", barmode="group",
                     color_discrete_map=config.GEN_COLOURS_WITH_BATTERY, labels={"cf": "%", "run": ""})
    fig.update_xaxes(type="category")
    return _style(fig)


def _short_labels(df, params):
    """Compare-all mode: shorten long scenario names (e.g. 'Renewable int.') so labels don't overlap."""
    ren = config.compare_labels()
    if not df.empty:
        df = df.assign(run=df["run"].replace(ren))
    return df, {ren.get(k, k): v for k, v in (params or {}).items()}


def _bat_power(df, caps=None):
    """{run: battery power MW} for battery scenarios present in df."""
    out = {}
    for k, s in config.SCENARIOS.items():
        if "battery" in s and not df.empty and config.scenario_label(k) in set(df["run"]):
            out[config.scenario_label(k)] = loader.load_bat_params(k, caps=caps)["power"]
    return out


def _windowed(scenario, hours, caps=None):
    df, params = access.load_selected(scenario, caps)
    if df.empty:
        return df, params
    w, _, _ = access.filter_window(df, 1, hours)
    if scenario == config.BOTH:
        w, params = _short_labels(w, params)
    return w, params


BAT_KPIS = [("charged", "Charged (MWh)", "{:,.0f}"), ("discharged", "Discharged (MWh)", "{:,.0f}"),
            ("losses", "Losses (MWh)", "{:,.0f}"), ("cycles", "Equivalent full cycles", "{:.1f}"),
            ("peak_soc", "Peak SOC (MWh)", "{:,.0f}"), ("charge_hours", "Charging hours", "{:d}"),
            ("discharge_hours", "Discharging hours", "{:d}")]


def battery_tiles(df, caps=None):
    keys = [k for k, s in config.SCENARIOS.items() if "battery" in s]
    runs = {config.scenario_label(k): k for k in keys}
    present = [r for r in df["run"].unique() if r in runs] if not df.empty else []
    if not present:
        return html.Div("Select the Batteries scenario (or All) to see battery results.", className="text-muted")
    out = []
    for run in present:
        bat = loader.load_bat_params(runs[run], caps=caps)
        s = metrics.battery_summary(df[df["run"] == run], bat)
        out.append(html.Div("%s - %s MWh, %s MW, charge eff %.2f, discharge eff %.2f (round trip %.0f%%)" % (
            run, "{:,.0f}".format(bat["cap"]), "{:,.0f}".format(bat["power"]), bat["charg_eff"],
            bat["discharge_eff"], 100 * bat["charg_eff"] * bat["discharge_eff"]), className="small text-muted mb-1"))
        out.append(dbc.Row([dbc.Col(dbc.Card(dbc.CardBody([
            html.Div(lab, className="text-muted small text-uppercase"),
            html.Div(fmt.format(s[k]), style={"fontSize": "1.4rem", "fontWeight": 600,
                                              "color": config.BAT_COLOURS["soc"]}),
        ], className="py-2")), xs=6, md=3, lg=True, className="mb-2") for k, lab, fmt in BAT_KPIS]))
    return html.Div(out)


def register_callbacks(app):
    @app.callback(Output("s-battery", "children"), *GLOBAL_INPUTS)
    def battery(scenario, hours, gens, caps):
        w, _ = _windowed(scenario, hours, caps)
        return battery_tiles(w, caps)

    for key in PLOTS:
        def make(k):
            @app.callback(Output("s-fig-" + k, "figure"), *GLOBAL_INPUTS)
            def _cb(scenario, hours, gens, caps):
                w, params = _windowed(scenario, hours, caps)
                bp = _bat_power(w, caps) if k == "cf" else None
                with access.PLOT_LOCK:  # plotly express is not thread-safe (shared template)
                    return _figure(k, w, params, access.selected_gens(gens), access.show_battery(gens), bp)
        make(key)

    @app.callback(Output("s-col-share", "lg"), Output("s-col-setter", "lg"), Input("scenario", "value"))
    def pie_widths(scenario):
        # compare-all: each pie card gets the full row so the 2x2 donut grid is large enough
        w = 12 if scenario == config.BOTH else 6
        return w, w

    @app.callback(Output("s-kpis", "children"), *GLOBAL_INPUTS)
    def kpis(scenario, hours, gens, caps):
        w, _ = _windowed(scenario, hours, caps)
        return kpi_tiles(w)

    @app.callback(Output("s-table", "data"), Output("s-table", "columns"), Output("s-window", "children"),
                  *GLOBAL_INPUTS)
    def table(scenario, hours, gens, caps):
        df, params = access.load_selected(scenario, caps)
        if df.empty:
            return [], [], "No data"
        w, s, last = access.filter_window(df, 1, hours)
        label = "Metrics for " + access.range_label(s, last)
        if w.empty:
            return [], [], label
        t = metrics.summary_table(w)
        if scenario == config.BOTH:
            t["run"] = t["run"].replace(config.compare_labels())
        keep = access.selected_gens(gens)
        t = t.drop(columns=[g + "_mwh" for g in config.GENERATORS if g not in keep])
        return t.to_dict("records"), [{"name": c, "id": c} for c in t.columns], label
