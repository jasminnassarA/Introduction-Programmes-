"""Interconnectors page: results of models\\Interconnectors.gms (multi-region dispatch with trade).

The global sidebar is hidden on this page (see app.py). Own controls: 2 / 4 regions, hour range,
focus region and link, capacity multipliers per region and generator, link capacity and Re-run.
Base inputs read Results\\Interconnectors_<N>.gdx; modified capacities are solved in a temporary
folder and kept in memory only (dashboard.data.runner._IC_CACHE).
"""
import math

import dash
import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, dcc, html

from dashboard import config
from dashboard.data import access, runner
from dashboard.data import interconnectors as ic
from dashboard.pages.nodal import HEADER, _anim_controls, _empty, _fmt, _style, _with_frames

GENS = config.IC_GENERATORS
COL = config.IC_GEN_COLOURS
RCOL = config.IC_REGION_COLOURS
N_HOURS = 744

PLOTS = {
    "map": ("1. Interconnector map", "One frame per hour. Circle colour = regional price, line thickness = "
                                     "flow, arrow = direction, line colour = % of link capacity "
                                     "(green < 50%, yellow < 90%, red = full). Beside each region: green arrow = export, red arrow = import (MW). "
                                     "Play 10 s / 168 h shows a week in 10 seconds."),
    "trade": ("2. Imports and exports by region", "Energy sent (export) and received after losses (import) "
                                                  "over the selected hours, GWh."),
    "price": ("3. Regional prices", "Balance marginal per region ($/MWh). Prices converge while links have "
                                    "spare capacity and split when a link is full."),
    "gap": ("4. Price gap between regions", "Highest minus lowest regional price per hour."),
    "duration": ("5. Price duration curves", "Each region's prices sorted from highest to lowest."),
    "dispatch": ("6. Dispatch - focus region", "Generation stacked by type plus imports; exports drawn below "
                                               "zero; black dashed line = demand."),
    "mix": ("7. Generation mix by region", "Share of each generator in local generation over the selected hours."),
    "flow": ("8. Flow on the selected link", "Net flow (positive = first region exports to the second) "
                                             "with +/- link capacity."),
    "usage": ("9. Link usage heatmap", "Hours x links, colour = |net flow| / capacity."),
    "day": ("10. Average day", "Mean net export by hour of day (positive = exporting)."),
    "congest": ("11. Hours each link is full", "Bars = hours at the link limit, diamonds = mean price gap "
                                               "across the link ($/MWh)."),
}
SECTIONS = [
    ("The system at a glance", [("map", True), ("trade", False), ("mix", False)]),
    ("Prices", [("price", True), ("gap", False), ("duration", False)]),
    ("Focus region", [("dispatch", True), ("day", True)]),
    ("Interconnectors", [("flow", True), ("usage", True), ("congest", True)]),
]
FIG_KEYS = [k for _, items in SECTIONS for k, _ in items]
KPIS = [("total_cost", "Total cost (month)", "$%s", "#333333"),
        ("unserved", "Unserved energy (MWh)", "%s", "#d62728"),
        ("traded", "Energy traded (GWh)", "%s", "#1f77b4"),
        ("losses", "Link losses (MWh)", "%s", "#ff7f0e"),
        ("cong_hours", "Full link-hours", "%s", "#9467bd")]


# ---------------- layout ----------------

def _card(key):
    title, note = PLOTS[key]
    return dbc.Card([dbc.CardHeader([html.B(title), html.Div(note, className="text-muted small")]),
                     dbc.CardBody(dcc.Graph(id="ic-fig-" + key))], className="mb-3")


def _base_caps():
    try:
        return runner.ic_base_caps()
    except Exception:
        return {}


def _base_link():
    try:
        return runner.ic_base_link_cap()
    except Exception:
        return 200.0


def _cap_panel():
    base = _base_caps()
    regions = sorted({k.split(".")[0] for k in base})
    opts = [{"label": "x%g" % m, "value": m} for m in config.IC_MULTIPLIERS]
    rows = [html.Tr([html.Th("Region")] + [html.Th(g) for g in GENS])]
    for r in regions:
        cells = [html.Td(config.IC_REGION_NAMES.get(r, r), className="small fw-bold")]
        for g in GENS:
            k = "%s.%s" % (r, g)
            if base.get(k, 0) > 0:
                cells.append(html.Td([
                    dcc.Dropdown(id={"type": "ic-mult", "key": k}, options=opts, value=1, clearable=False,
                                 style={"minWidth": "5rem"}),
                    html.Div("%d MW" % base[k], className="small text-muted")]))
            else:
                cells.append(html.Td("-", className="text-muted text-center"))
        rows.append(html.Tr(cells))
    link = _base_link()
    return dbc.Card(dbc.CardBody([
        html.B("Capacities"), html.Span("  (multiplier of the base MW in generators.csv; R3/R4 apply to the "
                                        "4-region case only)", className="small text-muted"),
        html.Table(rows, className="table table-sm mb-2"),
        dbc.Row([
            dbc.Col([html.Label("Link capacity (MW, every interconnector)", className="fw-bold small"),
                     dcc.Slider(id="ic-link", min=0, max=config.IC_LINK_MAX, step=25, value=link,
                                marks={v: str(v) for v in range(0, config.IC_LINK_MAX + 1, 100)},
                                tooltip={"placement": "bottom", "always_visible": True})], lg=8),
            dbc.Col(dbc.Button("Reset to base", id="ic-reset", color="secondary", outline=True, size="sm",
                               className="mt-4"), lg=4),
        ]),
    ]), className="mb-3")


def _controls():
    return dbc.Card(dbc.CardBody(dbc.Row([
        dbc.Col([html.Label("Regions", className="fw-bold"),
                 dbc.RadioItems(id="ic-regions", value=config.IC_DEFAULT_REGIONS, inline=True,
                                options=[{"label": "%d regions" % n, "value": n}
                                         for n in config.IC_REGION_COUNTS])], lg=2),
        dbc.Col([html.Label("Hours", className="fw-bold"),
                 dcc.RangeSlider(id="ic-hours", min=1, max=N_HOURS, step=1, value=[1, 168],
                                 marks={h: str(h) for h in (1, 168, 336, 504, 744)})], lg=4),
        dbc.Col([html.Label("Region (graph 6)", className="fw-bold"),
                 dcc.Dropdown(id="ic-region", clearable=False)], lg=2),
        dbc.Col([html.Label("Link (graph 8)", className="fw-bold"),
                 dcc.Dropdown(id="ic-linksel", clearable=False)], lg=2),
        dbc.Col([dbc.Button("Re-run", id="ic-rerun", color="primary", size="sm", className="mt-4 w-100")],
                lg=2),
    ])), className="mb-3", style={"backgroundColor": "#f8f9fa"})


def layout():
    body = [
        dcc.Link("\u2190 Back to dashboard", href="/", className="small"),
        html.H3("Interconnectors (Interconnectors.gms)", className="mt-1"),
        dcc.Store(id="ic-run", data={"key": None, "version": 0}),
        _controls(),
        _cap_panel(),
        dcc.Loading(html.Div(id="ic-status", className="small text-muted mb-2", style={"whiteSpace": "pre-wrap"}),
                    type="dot"),
        html.Div(id="ic-banner", className="mb-2"),
        html.Div(id="ic-window", className="fw-bold mb-2"),
        html.H4("At a glance", className=HEADER),
        html.Div(id="ic-kpis", className="mb-2"),
    ]
    for header, items in SECTIONS:
        body.append(html.H4(header, className=HEADER))
        body.append(dbc.Row([dbc.Col(_card(k), lg=12 if full else 6) for k, full in items]))
    return html.Div(body)


# ---------------- helpers ----------------

def hour_window(hours, n_hours=N_HOURS):
    lo, hi = (hours or [1, n_hours])[:2]
    lo, hi = max(1, int(lo)), min(n_hours, int(hi))
    return (lo, hi) if lo <= hi else (hi, lo)


def kpi_tiles(k):
    def val(key, pat):
        v = k[key]
        return "n/a" if v is None or (isinstance(v, float) and math.isnan(v)) else _fmt(v, pat)
    return dbc.Row([dbc.Col(dbc.Card(dbc.CardBody([
        html.Div(label, className="text-muted small text-uppercase"),
        html.Div(val(key, pat), style={"fontSize": "1.6rem", "fontWeight": 600, "color": col}),
    ], className="py-2"), style={"borderTop": "4px solid " + col}), xs=6, md=4, lg=True, className="mb-2")
        for key, label, pat, col in KPIS])


def _usage_colour(pct):
    return "#2ca02c" if pct < 50 else ("#f0ad00" if pct < 90 else "#d62728")


def _link_label(data, name):
    return name.replace("-", " \u2194 ")


# ---------------- figures ----------------

def map_figure(data, lo, hi):
    hours = ic.window(data, lo, hi)
    if not hours:
        return _empty("No hours selected")
    regions, links = data["regions"], data["links"]
    pos = config.IC_POSITIONS
    pr = data["price"].loc[hours]
    pmin, pmax = float(pr.values.min()), float(pr.values.max())
    if pmax - pmin < 1e-6:
        pmax = pmin + 1.0
    net, use = data["net"], ic.link_usage(data, lo, hi)

    def link_traces(t):
        out = []
        for _, l in links.iterrows():
            (x0, y0), (x1, y1) = pos[l.a], pos[l.b]
            mw = float(net.at[t, l["name"]])
            pct = float(use.at[t, l["name"]])
            out.append(dict(type="scatter", x=[x0, x1], y=[y0, y1], mode="lines", hoverinfo="skip",
                            line=dict(width=1.5 + 10.0 * min(abs(mw) / max(l.cap, 1), 1.0),
                                      color=_usage_colour(pct) if abs(mw) > 0.1 else "#cccccc"),
                            showlegend=False))
        xs, ys, ang, txt, cols = [], [], [], [], []
        for _, l in links.iterrows():
            (x0, y0), (x1, y1) = pos[l.a], pos[l.b]
            mw = float(net.at[t, l["name"]])
            src, dst = ((x0, y0), (x1, y1)) if mw >= 0 else ((x1, y1), (x0, y0))
            xs.append(0.5 * (x0 + x1))
            ys.append(0.5 * (y0 + y1))
            ang.append(math.degrees(math.atan2(dst[0] - src[0], dst[1] - src[1])))
            frm, to = (l.a, l.b) if mw >= 0 else (l.b, l.a)
            txt.append("%s \u2192 %s: %.0f MW (%.0f%% of %d MW)" % (frm, to, abs(mw), use.at[t, l["name"]], l.cap))
            cols.append("#333333" if abs(mw) > 0.1 else "rgba(0,0,0,0)")
        out.append(dict(type="scatter", x=xs, y=ys, mode="markers", text=txt, hoverinfo="text",
                        marker=dict(symbol="triangle-up", size=16, angle=ang, color=cols), showlegend=False))
        p = [float(pr.at[t, r]) for r in regions]
        out.append(dict(type="scatter", x=[pos[r][0] for r in regions], y=[pos[r][1] for r in regions],
                        mode="markers+text", text=["%s<br>$%.1f" % (r, v) for r, v in zip(regions, p)],
                        textposition="middle center", textfont=dict(color="white", size=12),
                        hovertext=["%s: $%.2f/MWh, demand %.0f MW" % (config.IC_REGION_NAMES.get(r, r), v,
                                                                       data["dispatch"][r].at[t, "Demand"])
                                   for r, v in zip(regions, p)], hoverinfo="text",
                        marker=dict(size=62, color=p, cmin=pmin, cmax=pmax, colorscale="RdYlGn_r",
                                    line=dict(color="#333", width=1.5),
                                    colorbar=dict(title="$/MWh", len=0.7)), showlegend=False))
        # per-region export (green, pointing out, right side) and import (red, pointing in, left side)
        for col, dx, colour, label in (("Export", 0.1, "#2ca02c", "Export"), ("Import", -0.1, "#d62728", "Import")):
            mw = [float(data["dispatch"][r].at[t, col]) for r in regions]
            out.append(dict(type="scatter", x=[pos[r][0] + dx for r in regions], y=[pos[r][1] for r in regions],
                            mode="markers+text", textposition="bottom center", textfont=dict(size=10, color=colour),
                            text=["%s %.0f MW" % (label, v) if v > 0.1 else "" for v in mw],
                            hovertext=["%s %s: %.0f MW" % (r, label.lower(), v) for r, v in zip(regions, mw)],
                            hoverinfo="text", showlegend=False,
                            marker=dict(symbol="triangle-right", color=colour,
                                        size=[8 + 22 * min(v / arrow_max, 1.0) if v > 0.1 else 0 for v in mw])))
        return out

    arrow_max = max([float(data["dispatch"][r].loc[hours, ["Import", "Export"]].values.max()) for r in regions]
                    + [1.0])

    first = link_traces(hours[0])
    fig = go.Figure()
    for tr in first:
        fig.add_trace(go.Scatter(**{k: v for k, v in tr.items() if k != "type"}))
    menus, sliders = _anim_controls(hours, redraw=True, speeds=[(int(10000 / 168), "10 s / 168 h"), (400, "fast"), (1000, "1 s/h")])
    fig.update_layout(updatemenus=menus, sliders=sliders)
    fig.update_xaxes(visible=False, range=[-0.05, 1.05])
    fig.update_yaxes(visible=False, range=[-0.08, 1.05], scaleanchor="x", scaleratio=1)
    _style(fig, 620)
    idx = list(range(len(first)))
    return _with_frames(fig, [(str(t), link_traces(t), idx) for t in hours])


def trade_figure(data, lo, hi):
    regions = data["regions"]
    imp = [data["dispatch"][r].loc[lo:hi, "Import"].sum() / 1000 for r in regions]
    exp = [data["dispatch"][r].loc[lo:hi, "Export"].sum() / 1000 for r in regions]
    fig = go.Figure([go.Bar(name="Export", x=regions, y=exp, marker_color="#2ca02c"),
                     go.Bar(name="Import", x=regions, y=imp, marker_color="#d62728"),
                     go.Scatter(name="Net export", x=regions, y=np.array(exp) - np.array(imp), mode="markers",
                                marker=dict(symbol="diamond", size=12, color="#333"))])
    fig.update_layout(barmode="group", yaxis_title="GWh")
    return _style(fig)


def price_figure(data, lo, hi):
    pr = data["price"].loc[lo:hi]
    fig = go.Figure([go.Scatter(x=pr.index, y=pr[r], name=r, mode="lines", line=dict(shape="hv", color=RCOL.get(r)))
                     for r in data["regions"]])
    fig.update_layout(xaxis_title="Hour", yaxis_title="$/MWh")
    return _style(fig)


def gap_figure(data, lo, hi):
    pr = data["price"].loc[lo:hi]
    gap = pr.max(axis=1) - pr.min(axis=1)
    fig = go.Figure(go.Bar(x=gap.index, y=gap.values, marker_color="#9467bd", name="Max - min price"))
    fig.update_layout(xaxis_title="Hour", yaxis_title="$/MWh")
    return _style(fig)


def duration_figure(data, lo, hi):
    pr = data["price"].loc[lo:hi]
    fig = go.Figure()
    for r in data["regions"]:
        v = np.sort(pr[r].values)[::-1]
        fig.add_trace(go.Scatter(x=np.arange(1, len(v) + 1), y=v, name=r, mode="lines",
                                 line=dict(color=RCOL.get(r))))
    fig.update_layout(xaxis_title="Hours (sorted)", yaxis_title="$/MWh")
    return _style(fig)


def dispatch_figure(data, lo, hi, region):
    if region not in data["dispatch"]:
        return _empty("Pick a region")
    d = data["dispatch"][region].loc[lo:hi]
    fig = go.Figure()
    for g in GENS + ["Import", "Unserved"]:
        if d[g].abs().sum() > 0:
            fig.add_trace(go.Scatter(x=d.index, y=d[g], name=g, stackgroup="pos", mode="lines",
                                     line=dict(width=0), fillcolor=COL[g], line_color=COL[g]))
    if d["Export"].sum() > 0:
        fig.add_trace(go.Scatter(x=d.index, y=-d["Export"], name="Export", stackgroup="neg", mode="lines",
                                 line=dict(width=0), fillcolor=COL["Export"], line_color=COL["Export"]))
    fig.add_trace(go.Scatter(x=d.index, y=d["Demand"], name="Demand", mode="lines",
                             line=dict(color="black", dash="dash", width=1.5)))
    fig.update_layout(xaxis_title="Hour", yaxis_title="MW", title=config.IC_REGION_NAMES.get(region, region))
    return _style(fig, 460)


def mix_figure(data, lo, hi):
    regions = data["regions"]
    tot = {r: data["dispatch"][r].loc[lo:hi, GENS].sum() for r in regions}
    fig = go.Figure()
    for g in GENS:
        share = [100 * tot[r][g] / tot[r].sum() if tot[r].sum() > 0 else 0 for r in regions]
        if any(share):
            fig.add_trace(go.Bar(name=g, x=regions, y=share, marker_color=COL[g]))
    fig.update_layout(barmode="stack", yaxis_title="% of local generation", yaxis_range=[0, 100])
    return _style(fig)


def flow_figure(data, lo, hi, link):
    links = data["links"].set_index("name")
    if link not in links.index:
        return _empty("No interconnector between the active regions")
    s = data["net"].loc[lo:hi, link]
    cap = links.at[link, "cap"]
    a, b = links.at[link, "a"], links.at[link, "b"]
    fig = go.Figure([
        go.Scatter(x=s.index, y=s.clip(lower=0), name="%s \u2192 %s" % (a, b), fill="tozeroy", mode="lines",
                   line=dict(color=RCOL.get(a, "#1f77b4"))),
        go.Scatter(x=s.index, y=s.clip(upper=0), name="%s \u2192 %s" % (b, a), fill="tozeroy", mode="lines",
                   line=dict(color=RCOL.get(b, "#ff7f0e"))),
    ])
    for y in (cap, -cap):
        fig.add_hline(y=y, line_dash="dash", line_color="#d62728")
    fig.update_layout(xaxis_title="Hour", yaxis_title="MW (positive = %s exports)" % a)
    return _style(fig)


def usage_figure(data, lo, hi):
    use = ic.link_usage(data, lo, hi)
    if use.empty or use.shape[1] == 0:
        return _empty("No interconnectors")
    fig = go.Figure(go.Heatmap(z=use.T.values, x=list(use.index), y=[_link_label(data, c) for c in use.columns],
                               zmin=0, zmax=100, colorbar=dict(title="%"),
                               colorscale=[[0, "#2ca02c"], [0.5, "#2ca02c"], [0.5, "#f0ad00"], [0.9, "#f0ad00"],
                                           [0.9, "#d62728"], [1, "#d62728"]]))
    fig.update_layout(xaxis_title="Hour")
    return _style(fig, 160 + 40 * use.shape[1])


def day_figure(data, lo, hi):
    day = ic.avg_day(data, lo, hi)
    fig = go.Figure([go.Scatter(x=day.index, y=day[r], name=r, mode="lines+markers", line=dict(color=RCOL.get(r)))
                     for r in day.columns])
    fig.add_hline(y=0, line_color="#999")
    fig.update_layout(xaxis_title="Hour of day (0 = 00:00-01:00)", yaxis_title="Net export (MW)",
                      xaxis=dict(dtick=2))
    return _style(fig)


def congest_figure(data, lo, hi):
    c = ic.congestion_table(data, lo, hi)
    if c.empty:
        return _empty("No interconnectors")
    labels = [_link_label(data, n) for n in c["name"]]
    fig = go.Figure([go.Bar(x=labels, y=c["hours"], name="Hours at limit", marker_color="#d62728"),
                     go.Scatter(x=labels, y=c["gap"], name="Mean price gap ($/MWh)", yaxis="y2", mode="markers",
                                marker=dict(symbol="diamond", size=13, color="#333"))])
    fig.update_layout(yaxis_title="Hours", yaxis2=dict(title="$/MWh", overlaying="y", side="right"))
    return _style(fig)


def figure(key, data, lo, hi, region=None, link=None):
    if key == "map":
        return map_figure(data, lo, hi)
    if key == "dispatch":
        return dispatch_figure(data, lo, hi, region)
    if key == "flow":
        return flow_figure(data, lo, hi, link)
    return {"trade": trade_figure, "price": price_figure, "gap": gap_figure, "duration": duration_figure,
            "mix": mix_figure, "usage": usage_figure, "day": day_figure, "congest": congest_figure}[key](data, lo, hi)


# ---------------- callbacks ----------------

def get_data(regions, run):
    """(data, label, error). Modified results come from the in-memory cache, otherwise the base gdx."""
    key = (run or {}).get("key")
    if key and key.startswith("%d|" % int(regions)):
        d = runner.ic_cached(key)
        if d is not None:
            return d, "Modified: " + key.split("|", 1)[1], None
    try:
        return ic.load(int(regions)), "Base inputs", None
    except Exception as e:
        return None, "", str(e)


def banner(label):
    if not label:
        return ""
    colour = "secondary" if label == "Base inputs" else "warning"
    return dbc.Alert(label, color=colour, className="py-1 mb-0 small")


def update(regions, hours, region, link, run):
    data, label, err = get_data(regions, run)
    if data is None:
        msg = "No Interconnectors results: %s" % err
        return [banner(""), msg, html.Div(msg, className="text-danger")] + [_empty("No results") for _ in FIG_KEYS]
    lo, hi = hour_window(hours, len(data["hours"]))
    figs = [figure(k, data, lo, hi, region, link) for k in FIG_KEYS]
    return [banner(label), "Hours %d - %d of %d, %d regions" % (lo, hi, len(data["hours"]), len(data["regions"])),
            kpi_tiles(ic.kpis(data, lo, hi))] + figs


def register_callbacks(app):
    @app.callback(Output("ic-region", "options"), Output("ic-region", "value"),
                  Output("ic-linksel", "options"), Output("ic-linksel", "value"),
                  Input("ic-regions", "value"), Input("ic-run", "data"),
                  State("ic-region", "value"), State("ic-linksel", "value"))
    def _options(regions, run, region, link):
        data, _, _ = get_data(regions, run)
        if data is None:
            return [], None, [], None
        ropts = [{"label": config.IC_REGION_NAMES.get(r, r), "value": r} for r in data["regions"]]
        lnames = list(data["links"]["name"])
        lopts = [{"label": _link_label(data, n), "value": n} for n in lnames]
        return (ropts, region if region in data["regions"] else data["regions"][0],
                lopts, link if link in lnames else (lnames[0] if lnames else None))

    @app.callback([Output("ic-banner", "children"), Output("ic-window", "children"), Output("ic-kpis", "children")]
                  + [Output("ic-fig-" + k, "figure") for k in FIG_KEYS],
                  Input("ic-regions", "value"), Input("ic-hours", "value"), Input("ic-region", "value"),
                  Input("ic-linksel", "value"), Input("ic-run", "data"))
    def _update(regions, hours, region, link, run):
        with access.PLOT_LOCK:
            return update(regions, hours, region, link, run)

    @app.callback(Output({"type": "ic-mult", "key": ALL}, "value"), Output("ic-link", "value"),
                  Input("ic-reset", "n_clicks"), State({"type": "ic-mult", "key": ALL}, "value"),
                  prevent_initial_call=True)
    def _reset(_n, values):
        return [1 for _ in values], _base_link()

    @app.callback(Output("ic-status", "children"), Output("ic-run", "data"),
                  Input("ic-rerun", "n_clicks"), State("ic-regions", "value"),
                  State({"type": "ic-mult", "key": ALL}, "value"), State({"type": "ic-mult", "key": ALL}, "id"),
                  State("ic-link", "value"), State("ic-run", "data"), prevent_initial_call=True)
    def _rerun(_n, regions, values, ids, link_cap, run):
        active = {"R%d" % i for i in range(1, int(regions) + 1)}
        mults = {i["key"]: v for i, v in zip(ids, values) if i["key"].split(".")[0] in active}
        try:
            msg, key = runner.run_interconnectors(regions, mults, link_cap)
        except (runner.GamsRunError, OSError) as e:
            return "Error: %s" % e, dash.no_update
        return msg, {"key": key, "version": (run or {}).get("version", 0) + 1}
