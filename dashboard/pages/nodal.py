"""Nodal page: results of the Nodal_SC model (DC power flow with shift factors).

The global sidebar is hidden on this page (see app.py) - it has its own controls:
hour range, node scope / node selection, line selection and a Re-run Nodal_SC button.
"""
import dash
import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html

from dashboard import config
from dashboard.data import access, nodal, runner

HEADER = "mt-3 mb-2 border-bottom pb-1"
SCOPE_KEY, SCOPE_ALL = "key", "all"

# key -> (title, note). Order = order on the page.
PLOTS = {
    "dispatch": ("1. Dispatch stack", "Generation by generator (stacked) and total demand. Merit order: "
                                      "GEN_1/2 = 0, GEN_3 = 50, GEN_4 = 100, GEN_5 = 500 $/MWh."),
    "price": ("2. System price vs nodal prices", "Line = system energy price (dual of the energy balance). "
                                                 "Band = lowest to highest LMP over the 25 load/generator nodes. "
                                                 "A band wider than the line = congestion."),
    "heat_all": ("3. LMP heatmap - all 428 nodes", "Nodes sorted by average LMP so price zones group together."),
    "spread": ("4. Price spread per hour", "Max - min LMP over the 25 load/generator nodes. 0 = no congestion."),
    "congested": ("5. Most congested lines", "Top %d lines by hours at their limit (bars) and total congestion "
                                             "price ($/MWh, diamonds)." % config.NODAL_TOP_LINES),
    "loading": ("6. Line loading", "Flow on the selected line with its +/- rating. Lines rated inf show the "
                                   "flow only."),
    "util": ("8. Generator utilisation", "Average output / capacity over the selected hours (capacity factor)."),
    "duration": ("9. Price duration curve", "LMP of each selected node sorted from highest to lowest. "
                                            "No node selected = every node in the chosen scope."),
    "network": ("B. Network congestion film", "One frame per hour. Only lines carrying power that hour are drawn. "
                                              "Colour = % of rating (green -> red), cyan = unlimited (inf) line. "
                                              "Thicker = more MW, arrows = flow direction. Node colour = LMP. "
                                              "Play runs the whole week in about 10 s. Dashed thin lines = spur from a node that is not an end of any guessed line to the line it influences most (largest |shift factor|). Tick generators to draw their influence lines."),
    "bars": ("A. Line loading film", "Every line that carries power during the week. Left: rated lines, % of "
                                     "rating. Right: unlimited (inf) lines, MW. Same colours and controls as the "
                                     "network film. Scroll inside the chart to see all lines."),
    "line_heat": ("C1. Line loading heatmap", "Hours x rated lines that carry power, colour = % of rating."),
    "node_cong": ("C2. Nodal congestion heatmap", "Hours x 428 nodes, colour = LMP - system price ($/MWh). "
                                                  "0 (white) = no congestion effect at that node."),
}
NETWORK_NOTE = ("Illustrative only: line endpoints and node positions are estimated from the shift factor "
                "matrix because no topology data was provided. Do not read geography or real connections "
                "from this picture.")
SPEEDS = [(1000, "1 s"), (2000, "2 s"), (5000, "5 s")]  # ms per hour
# page rows: (header, [(key, full width)])
SECTIONS = [
    ("Dispatch", [("dispatch", True)]),
    ("Congestion", [("network", True), ("line_heat", True), ("node_cong", True), ("bars", True)]),
    ("Prices", [("price", True), ("heat_all", True), ("spread", True)]),
    ("Congested lines", [("congested", False), ("loading", False)]),
    ("Generators & price duration", [("util", False), ("duration", False)]),
]
FIG_KEYS = [k for _, items in SECTIONS for k, _ in items]
MAIN_KEYS = [k for k in FIG_KEYS if k != "network"]  # network has its own callback (influence controls)
INFL_GENS = [g for g in config.NODAL_GEN_COLOURS if g != "Unserved"]

KPIS = [("total_cost", "Total cost", "$%s", "#333333"), ("cost_per_hour", "Cost per hour", "$%s", "#1f77b4"),
        ("unserved", "Unserved energy (MWh)", "%s", "#d62728"),
        ("congested_line_hours", "Congested line-hours", "%s", "#ff7f0e"),
        ("max_spread", "Max price spread ($/MWh)", "%s", "#9467bd")]


# ---------------- layout ----------------

def _card(key):
    title, note = PLOTS[key]
    graph = dcc.Graph(id="n-fig-" + key)
    if key == "bars":
        graph = html.Div(graph, style={"maxHeight": "750px", "overflowY": "auto"})
    body = [graph]
    if key == "network":
        body.insert(0, dbc.Row([
            dbc.Col([html.Label("Show influence lines for:", className="fw-bold small"),
                     dbc.Checklist(id="n-infl-gens", value=[], inline=True,
                                   options=[{"label": g, "value": g} for g in INFL_GENS])], lg=7),
            dbc.Col([html.Label("|Shift factor| threshold", className="fw-bold small"),
                     dcc.Slider(id="n-sf", min=0.05, max=0.5, step=0.05, value=0.1,
                                marks={v: "%.2g" % v for v in (0.05, 0.1, 0.2, 0.3, 0.4, 0.5)})], lg=5),
        ], className="mb-2"))
        body.append(html.Div(NETWORK_NOTE, className="small text-muted fst-italic mt-1"))
    return dbc.Card([dbc.CardHeader([html.B(title), html.Div(note, className="text-muted small")]),
                     dbc.CardBody(body)], className="mb-3")


def _controls():
    return dbc.Card(dbc.CardBody(dbc.Row([
        dbc.Col([html.Label("Hours", className="fw-bold"),
                 dcc.RangeSlider(id="n-hours", min=1, max=168, step=1, value=[1, 168],
                                 marks={h: str(h) for h in (1, 24, 48, 72, 96, 120, 144, 168)},
                                 tooltip={"placement": "bottom", "always_visible": False})], lg=4),
        dbc.Col([html.Label("Node scope (duration curve)", className="fw-bold"),
                 dbc.RadioItems(id="n-scope", value=SCOPE_KEY, inline=True,
                                options=[{"label": "25 load/gen nodes", "value": SCOPE_KEY},
                                         {"label": "All 428 nodes", "value": SCOPE_ALL}]),
                 dcc.Dropdown(id="n-nodes", multi=True, placeholder="All nodes in scope")], lg=3),
        dbc.Col([html.Label("Line (loading chart)", className="fw-bold"),
                 dcc.Dropdown(id="n-line", clearable=False)], lg=2),
        dbc.Col([dbc.Button("Re-run Nodal_SC", id="n-rerun", color="primary", size="sm", className="mt-4 w-100"),
                 dcc.Loading(html.Div(id="n-status", className="small text-muted mt-1",
                                      style={"whiteSpace": "pre-wrap"}), type="dot")], lg=3),
    ])), className="mb-3", style={"backgroundColor": "#f8f9fa"})


def layout():
    body = [
        dcc.Link("\u2190 Back to dashboard", href="/", className="small"),
        html.H3("Nodal pricing (Nodal_SC)", className="mt-1"),
        dcc.Store(id="n-version", data=0),
        _controls(),
        html.Div(id="n-window", className="fw-bold mb-2"),
        html.H4("Cost at a glance", className=HEADER),
        html.Div(id="n-kpis", className="mb-2"),
    ]
    for header, items in SECTIONS:
        body.append(html.H4(header, className=HEADER))
        body.append(dbc.Row([dbc.Col(_card(k), lg=12 if full else 6) for k, full in items]))
    return html.Div(body)


# ---------------- helpers ----------------

def _style(fig, height=420):
    fig.update_layout(template="plotly_white", height=height, margin=dict(t=40, b=40, l=60, r=20),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title_text=""))
    return fig


def _empty(msg):
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper")
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _style(fig, 250)


def hour_window(hours, n_hours=168):
    lo, hi = (hours or [1, n_hours])[:2]
    lo, hi = max(1, int(lo)), min(n_hours, int(hi))
    return (lo, hi) if lo <= hi else (hi, lo)


def _gens(data):
    return [g for g in data["gens"].index if g in data["dispatch"]]


def _fmt(v, pattern):
    return pattern % ("{:,.0f}".format(v) if abs(v) >= 100 or v == int(v) else "{:,.2f}".format(v))


def window_kpis(data, lo, hi):
    """KPIs over the selected hours (cost from MC x generation, which equals TOTCost when nothing is shed)."""
    d = data["dispatch"].loc[lo:hi]
    gens = data["gens"]
    cost = sum((d[g] * gens.loc[g, "MC"]).sum() for g in _gens(data))
    voll_cost = d["Unserved"].sum() * 10000.0
    f = data["flows"]
    f = f[(f["T"] >= lo) & (f["T"] <= hi)]
    lmp = data["lmp"].loc[lo:hi, data["key_nodes"]]
    spread = (lmp.max(axis=1) - lmp.min(axis=1)) if not lmp.empty else pd.Series([0.0])
    total = cost + voll_cost
    return {"total_cost": total, "cost_per_hour": total / max(len(d), 1), "unserved": d["Unserved"].sum(),
            "congested_line_hours": int((f["CongestionPrice"] > 0).sum()), "max_spread": float(spread.max())}


def kpi_tiles(k):
    return dbc.Row([dbc.Col(dbc.Card(dbc.CardBody([
        html.Div(label, className="text-muted small text-uppercase"),
        html.Div(_fmt(k[key], pat), style={"fontSize": "1.7rem", "fontWeight": 600, "color": col}),
    ], className="py-2"), style={"borderTop": "4px solid " + col}), xs=6, md=4, lg=True, className="mb-2")
        for key, label, pat, col in KPIS])


def node_options(data, scope):
    nodes = data["key_nodes"] if scope == SCOPE_KEY else list(data["lmp"].columns)
    gen_at = {n: g for g, n in data["gens"]["NODE"].items()}
    return [{"label": "%s (%s)" % (n, gen_at[n]) if n in gen_at else n, "value": n} for n in sorted(nodes)]


def line_options(data):
    rank = nodal.line_ranking(data["flows"])
    return [{"label": "%s (%d h congested)" % (l, r.hours) if r.hours else l, "value": l}
            for l, r in rank.iterrows()]


# ---------------- figures ----------------

def figure(key, data, lo, hi, scope=SCOPE_KEY, nodes=None, line=None, infl_gens=None, sf_threshold=0.1):
    if key == "network":
        return network_figure(data, lo, hi, infl_gens, sf_threshold)
    if key in EXTRA_FIGS:
        return EXTRA_FIGS[key](data, lo, hi)
    disp = data["dispatch"].loc[lo:hi]
    lmp = data["lmp"].loc[lo:hi]
    key_nodes = data["key_nodes"]
    flows = data["flows"]
    flows = flows[(flows["T"] >= lo) & (flows["T"] <= hi)]
    colours = config.NODAL_GEN_COLOURS
    x = disp.index

    if key == "dispatch":
        fig = go.Figure()
        for g in _gens(data) + (["Unserved"] if disp["Unserved"].sum() > 0 else []):
            fig.add_trace(go.Scatter(x=x, y=disp[g], name=g, stackgroup="gen", mode="lines",
                                     line=dict(width=0.5, color=colours.get(g))))
        fig.add_trace(go.Scatter(x=x, y=disp["TotalDemand"], name="Demand", mode="lines",
                                 line=dict(color="black", width=2, dash="dash")))
        fig.update_layout(xaxis_title="Hour", yaxis_title="MW")
        return _style(fig)

    if key == "price":
        k = lmp[key_nodes]
        fig = go.Figure([
            go.Scatter(x=x, y=k.max(axis=1), name="Max LMP", mode="lines", line=dict(width=0, color="#d62728")),
            go.Scatter(x=x, y=k.min(axis=1), name="LMP range", mode="lines", fill="tonexty",
                       fillcolor="rgba(214,39,40,0.2)", line=dict(width=0, color="#d62728")),
            go.Scatter(x=x, y=disp["SystemPrice"], name="System price", mode="lines",
                       line=dict(color="#1f77b4", width=2, shape="hv")),
        ])
        fig.update_layout(xaxis_title="Hour", yaxis_title="$/MWh")
        return _style(fig)

    if key == "heat_all":
        cols = list(lmp.mean().sort_values().index)
        z = lmp[cols]
        fig = go.Figure(go.Heatmap(x=z.index, y=[str(c) for c in cols], z=z.T.values, colorscale="RdYlGn_r",
                                   colorbar=dict(title="$/MWh"),
                                   hovertemplate="Hour %{x}<br>Node %{y}<br>LMP %{z:.2f}<extra></extra>"))
        fig.update_layout(xaxis_title="Hour", yaxis_title="Node", yaxis_type="category")
        fig.update_yaxes(showticklabels=False)
        return _style(fig, 800)

    if key == "spread":
        k = lmp[key_nodes]
        s = k.max(axis=1) - k.min(axis=1)
        fig = go.Figure(go.Bar(x=x, y=s, marker_color="#9467bd", name="Spread"))
        fig.update_layout(xaxis_title="Hour", yaxis_title="$/MWh")
        return _style(fig, 320)

    if key == "congested":
        rank = nodal.line_ranking(flows)
        rank = rank[rank["hours"] > 0].head(config.NODAL_TOP_LINES)
        if rank.empty:
            return _empty("No line is at its limit in the selected hours")
        fig = go.Figure([
            go.Bar(x=rank.index, y=rank["hours"], name="Hours at limit", marker_color="#ff7f0e"),
            go.Scatter(x=rank.index, y=rank["price"], name="Total congestion price ($/MWh)", yaxis="y2",
                       mode="markers", marker=dict(symbol="diamond", size=10, color="#d62728")),
        ])
        fig.update_layout(xaxis_title="Line", yaxis_title="Hours",
                          yaxis2=dict(title="$/MWh", overlaying="y", side="right", showgrid=False))
        return _style(fig)

    if key == "loading":
        if not line:
            return _empty("Select a line")
        f = flows[flows["l"] == line].sort_values("T")
        if f.empty:
            return _empty("No data for %s" % line)
        fig = go.Figure(go.Scatter(x=f["T"], y=f["Flow"], name="Flow", mode="lines", line=dict(color="#1f77b4")))
        rating = f["Rating"].iloc[0]
        if np.isfinite(rating):
            for sign, name in ((1, "+Rating"), (-1, "-Rating")):
                fig.add_trace(go.Scatter(x=f["T"], y=[sign * rating] * len(f), name=name, mode="lines",
                                         line=dict(color="#d62728", dash="dash")))
            title = "%s - rating %.1f MW, max loading %.1f%%" % (line, rating, f["Loading"].max())
        else:
            title = "%s - rating inf (unlimited)" % line
        fig.update_layout(title=dict(text=title, font=dict(size=13)), xaxis_title="Hour", yaxis_title="MW")
        return _style(fig)

    if key == "util":
        gens = data["gens"]
        g = _gens(data)
        cf = [disp[n].mean() / gens.loc[n, "CAP"] * 100 if gens.loc[n, "CAP"] else 0 for n in g]
        fig = go.Figure(go.Bar(x=g, y=cf, marker_color=[colours.get(n, "#7f7f7f") for n in g],
                               text=["%.1f%%" % v for v in cf], textposition="outside",
                               customdata=[gens.loc[n, "MC"] for n in g],
                               hovertemplate="%{x}<br>CF %{y:.1f}%<br>MC %{customdata} $/MWh<extra></extra>"))
        fig.update_layout(yaxis_title="Capacity factor (%)", yaxis_range=[0, 110])
        return _style(fig)

    if key == "duration":
        pool = key_nodes if scope == SCOPE_KEY else list(lmp.columns)
        sel = [n for n in (nodes or []) if n in lmp.columns] or pool
        rank = np.arange(1, len(lmp) + 1)
        many = len(sel) > 30
        fig = go.Figure()
        for n in sel:
            fig.add_trace(go.Scatter(x=rank, y=np.sort(lmp[n].values)[::-1], name=str(n), mode="lines",
                                     line=dict(width=1 if many else 2), showlegend=not many))
        fig.update_layout(xaxis_title="Hours (sorted)", yaxis_title="LMP ($/MWh)")
        return _style(fig)

    raise KeyError(key)


# ---------------- congestion films / heatmaps ----------------

WIDTHS = [(50.0, 1.5), (200.0, 3.0), (np.inf, 5.5)]  # (MW upper bound, line width)


def _with_frames(fig, frames):
    """Figure dict with animation frames attached as plain dicts (skips slow plotly validation).
    frames: [(name, [trace dicts], [trace indices])]."""
    out = fig.to_dict()
    out["frames"] = [{"name": n, "data": d, "traces": t} for n, d, t in frames]
    return out


def _segments(a, b):
    """[a0, b0, None, a1, b1, None, ...] for drawing many separate line segments in one trace."""
    out = np.empty(len(a) * 3, dtype=object)
    out[0::3], out[1::3], out[2::3] = a, b, None
    return list(out)


def _flow_table(flows, lo, hi):
    f = flows[(flows["T"] >= lo) & (flows["T"] <= hi)]
    flow = f.pivot_table(index="l", columns="T", values="Flow", aggfunc="sum").fillna(0.0)
    rating = f.groupby("l")["Rating"].first().reindex(flow.index)
    return flow, rating


def _anim_controls(hours, redraw=True, speeds=None):
    """speeds: [(ms per hour, label)]; default SPEEDS with "<label>/h" button labels."""
    def play(ms, label):
        return dict(label=label, method="animate",
                    args=[None, {"frame": {"duration": ms, "redraw": redraw}, "fromcurrent": True,
                                 "transition": {"duration": 0}, "mode": "immediate"}])
    if speeds is None:
        buttons = [play(ms, "\u25B6 %s/h" % lab) for ms, lab in SPEEDS]
    else:
        buttons = [play(ms, "\u25B6 %s" % lab) for ms, lab in speeds]
    buttons.append(dict(label="\u275A\u275A Pause", method="animate",
                        args=[[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}]))
    menus = [dict(type="buttons", direction="left", showactive=True, buttons=buttons,
                  x=0, y=1.0, xanchor="left", yanchor="bottom", pad=dict(t=0, b=10))]
    slider = [dict(active=0, currentvalue=dict(prefix="Hour "), pad=dict(t=30),
                   steps=[dict(label=str(t), method="animate",
                               args=[[str(t)], {"frame": {"duration": 0, "redraw": redraw},
                                                "mode": "immediate", "transition": {"duration": 0}}])
                          for t in hours])]
    return menus, slider


def _topology(data):
    from dashboard.data import topology
    return data.get("topology") or topology.get_topology(data["ptdf"], data["lmp"].columns)


INFL_WIDTHS = [(0.3, 1.5), (0.6, 2.5), (np.inf, 4.0)]  # (|SF| upper bound, width)


def _short(g):
    return g.replace("GENERATOR_", "GEN_")


def _classify(A, R):
    """Vectorised topology.line_class for flows A (lines x hours) and ratings R."""
    from dashboard.data import topology as topo
    finite = np.isfinite(R) & (R > 0)
    pct = np.where(finite[:, None], np.abs(A) / np.where(finite, R, 1)[:, None] * 100, np.nan)
    with np.errstate(invalid="ignore"):
        cls = np.where(np.abs(A) < topo.EMPTY_MW, 0, np.where(~finite[:, None], 1,
                       np.where(pct < topo.GREEN_MAX, 2, np.where(pct < topo.YELLOW_MAX, 3, 4))))
    return cls, pct, finite


def influence_traces(data, pos, mids, gens_sel, threshold):
    """Static traces: generator -> midpoint of every line with |SF| >= threshold, per ticked generator."""
    from dashboard.data import topology as topo
    out = []
    gens = data["gens"]
    for g in gens_sel or []:
        if g not in gens.index or data.get("ptdf") is None:
            continue
        n = gens.loc[g, "NODE"]
        if n not in pos.index:
            continue
        tl = topo.top_lines(data["ptdf"], n, k=None, threshold=threshold)
        tl = tl[tl["l"].isin(mids.index)]
        gx, gy = pos.loc[n, "x"], pos.loc[n, "y"]
        col = config.NODAL_GEN_COLOURS.get(g, "#7f7f7f")
        first = True
        for sign, dash in ((1, "solid"), (-1, "dash")):
            for i, (ub, w) in enumerate(INFL_WIDTHS):
                lo_b = INFL_WIDTHS[i - 1][0] if i else 0
                m = tl[(np.sign(tl["sf"]) == sign) & (tl["sf"].abs() >= lo_b) & (tl["sf"].abs() < ub)]
                if m.empty:
                    continue
                mx, my = mids.loc[m["l"], "x"].values, mids.loc[m["l"], "y"].values
                out.append(go.Scatter(x=_segments(np.full(len(m), gx), mx), y=_segments(np.full(len(m), gy), my),
                                      mode="lines", opacity=0.45, hoverinfo="skip", legendgroup="infl-" + g,
                                      name="%s influence (|SF| >= %.2g, %d lines)" % (_short(g), threshold, len(tl)),
                                      showlegend=first, line=dict(color=col, width=w, dash=dash)))
                first = False
        if len(tl):
            out.append(go.Scatter(x=mids.loc[tl["l"], "x"], y=mids.loc[tl["l"], "y"], mode="markers",
                                  legendgroup="infl-" + g, showlegend=False, hoverinfo="text",
                                  text=["%s \u2192 %s: SF %.2f" % (_short(g), l, s) for l, s in zip(tl["l"], tl["sf"])],
                                  marker=dict(size=6, color=col, opacity=0.7)))
    return out


PLAY_MS = 59  # ms per hour: 168 h in < 10 s
NET_BG = "#0f1419"
NET_FG = "#e5e7eb"
NET_EDGES = [30.0, 50.0, 70.0, 90.0]  # % of rating bin edges
NET_BINS = [("Unlimited (inf) line", "#22d3ee"), ("< 30% of rating", "#22c55e"), ("30-50%", "#a3e635"),
            ("50-70%", "#facc15"), ("70-90%", "#fb923c"), (">= 90% of rating", "#ff3b3b")]


def network_figure(data, lo, hi, infl_gens=None, sf_threshold=0.1):
    from dashboard.data import topology as topo

    tp = _topology(data)
    pos = tp["pos"].set_index("n")
    lines = tp["lines"]
    lines = lines[lines["from"].isin(pos.index) & lines["to"].isin(pos.index)].reset_index(drop=True)
    flow, rating = _flow_table(data["flows"], lo, hi)
    hours = list(flow.columns)
    flow = flow.reindex(lines["l"]).fillna(0.0)
    rating = rating.reindex(lines["l"]).fillna(np.inf)
    coords = np.round(np.column_stack([pos.loc[lines["from"], ["x", "y"]].values,
                                       pos.loc[lines["to"], ["x", "y"]].values]), 3)
    # lines that never carry power in the window are not drawn at all
    active = (flow.abs() >= topo.EMPTY_MW).any(axis=1).values
    A = flow.values[active]
    names = list(lines["l"].values[active])
    R = rating.values[active].astype(float)
    C = coords[active]
    mx, my = (C[:, 0] + C[:, 2]) / 2, (C[:, 1] + C[:, 3]) / 2
    mids = pd.DataFrame({"x": mx, "y": my}, index=names)
    finite = np.isfinite(R) & (R > 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        pct = np.where(finite[:, None], np.abs(A) / np.where(finite, R, 1)[:, None] * 100, np.nan)
    on = np.abs(A) >= topo.EMPTY_MW  # line visible in that hour
    b = np.where(~on, -1, np.where(~finite[:, None], 0, 1 + np.digitize(np.nan_to_num(pct), NET_EDGES)))
    wb = np.digitize(np.abs(A), [ub for ub, _ in WIDTHS[:-1]])
    base = np.degrees(np.arctan2(C[:, 2] - C[:, 0], C[:, 3] - C[:, 1]))  # from->to, clockwise from up
    ang = np.where(A >= 0, base[:, None], base[:, None] + 180.0)
    bin_cols = np.array([c for _, c in NET_BINS])
    rtxt = ["inf" if not f else "%.0f MW" % r for f, r in zip(finite, R)]

    # spurs (node -> nearer end of the line it influences most), only to lines that carry power
    sp = tp.get("spurs")
    sp = sp[sp["n"].isin(pos.index) & sp["l"].isin(names)] if sp is not None and len(sp) else \
        pd.DataFrame(columns=["n", "l", "sf"])
    li = {l: i for i, l in enumerate(names)}
    S, sp_on = np.zeros((0, 4)), np.zeros((0, len(hours)), dtype=bool)
    if len(sp):
        idx = np.array([li[l] for l in sp["l"]])
        nxy = pos.loc[sp["n"], ["x", "y"]].values
        e0, e1 = C[idx, 0:2], C[idx, 2:4]
        near = np.where((((nxy - e0) ** 2).sum(1) <= ((nxy - e1) ** 2).sum(1))[:, None], e0, e1)
        S, sp_on = np.column_stack([nxy, near]), on[idx]

    # nodes: generators/demand always; others only if they touch a line that carries power
    gens = data["gens"]
    gen_nodes = {n: g for g, n in gens["NODE"].items() if n in pos.index}
    dem = set(n for n in data.get("dem_nodes", []) if n in pos.index and n not in gen_nodes)
    used = set(lines["from"].values[active]) | set(lines["to"].values[active]) | set(sp["n"])
    nodes = [n for n in pos.index if n not in gen_nodes and (n in dem or n in used)]
    nx, ny = pos.loc[nodes, "x"].values, pos.loc[nodes, "y"].values
    lmp = data["lmp"].reindex(index=hours, columns=nodes).values.astype(float) if hours else np.zeros((0, 0))
    finite_lmp = lmp[np.isfinite(lmp)] if lmp.size else np.zeros(0)
    cmin, cmax = (np.percentile(finite_lmp, [2, 98]) if finite_lmp.size else (0.0, 1.0))
    if cmax <= cmin:
        cmax = cmin + 1.0
    nsize = [10 if n in dem else 6 for n in nodes]
    nline = [1.2 if n in dem else 0 for n in nodes]
    nkind = ["Demand node " if n in dem else "Node " for n in nodes]

    def frame_traces(j):
        out = []
        for bi, (label, col) in enumerate(NET_BINS):
            for w in range(len(WIDTHS)):
                m = (b[:, j] == bi) & (wb[:, j] == w)
                out.append(dict(type="scatter", x=_segments(C[m, 0], C[m, 2]), y=_segments(C[m, 1], C[m, 3]),
                                mode="lines", hoverinfo="skip", name=label, legendgroup="bin%d" % bi,
                                showlegend=(w == 0), opacity=0.9,
                                line=dict(color=col, width=WIDTHS[w][1])))
        m = sp_on[:, j] if len(S) else np.zeros(0, dtype=bool)
        out.append(dict(type="scatter", x=_segments(S[m, 0], S[m, 2]), y=_segments(S[m, 1], S[m, 3]),
                        mode="lines", hoverinfo="skip", legendgroup="spur", showlegend=True,
                        name="Spur: strongest influence (from shift factors)",
                        line=dict(color="#6b7280", width=1, dash="dot")))
        m = on[:, j]
        text = ["%s: %.0f MW / %s%s" % (n, a, r, "" if p != p else " (%.0f%%)" % p)
                for n, a, r, p, k in zip(names, A[:, j], rtxt, pct[:, j], m) if k]
        out.append(dict(type="scatter", x=mx[m], y=my[m], mode="markers", text=text, hoverinfo="text",
                        showlegend=False, marker=dict(symbol="arrow", size=10, angle=ang[m, j],
                                                      color=list(bin_cols[b[m, j]]),
                                                      line=dict(width=0))))
        vals = lmp[j] if lmp.size else []
        out.append(dict(type="scatter", x=nx, y=ny, mode="markers", showlegend=False, hoverinfo="text",
                        text=["%s%s: %.2f $/MWh" % (k, n, v) for k, n, v in zip(nkind, nodes, vals)],
                        marker=dict(size=nsize, color=vals, colorscale="Plasma", cmin=cmin, cmax=cmax,
                                    line=dict(color="white", width=nline), showscale=True,
                                    colorbar=dict(title=dict(text="LMP<br>$/MWh", font=dict(color=NET_FG)),
                                                  tickfont=dict(color=NET_FG), thickness=12, len=0.6,
                                                  x=1.0, outlinewidth=0))))
        return out

    statics = []
    if len(S):  # invisible hover points at spur midpoints
        statics.append(go.Scatter(x=(S[:, 0] + S[:, 2]) / 2, y=(S[:, 1] + S[:, 3]) / 2, mode="markers",
                                  text=["%s \u2192 %s, SF %.2f" % (n, l, s) for n, l, s in
                                        zip(sp["n"], sp["l"], sp["sf"])],
                                  hoverinfo="text", showlegend=False,
                                  marker=dict(size=6, color="#000000", opacity=0.01)))
    statics += influence_traces(data, pos, mids, infl_gens, sf_threshold)
    for n, g in gen_nodes.items():
        top = topo.top_lines(data["ptdf"], n, k=5) if data.get("ptdf") is not None else pd.DataFrame(columns=["l", "sf"])
        hover = "%s at node %s (MC %s $/MWh)<br>Top lines by shift factor: %s" % (
            g, n, gens.loc[g, "MC"], ", ".join("%s %.2f" % (l, s) for l, s in zip(top["l"], top["sf"])) or "none")
        statics.append(go.Scatter(x=[pos.loc[n, "x"]], y=[pos.loc[n, "y"]], mode="markers+text", name=_short(g),
                                  text=[_short(g)], textposition="top center",
                                  textfont=dict(size=13, color=NET_FG),
                                  hovertext=[hover], hoverinfo="text",
                                  marker=dict(size=18, symbol="square", color=config.NODAL_GEN_COLOURS.get(g, "#7f7f7f"),
                                              line=dict(color="white", width=1.5))))
    first = frame_traces(0) if hours else []
    n_dyn = len(first)
    fig = go.Figure(data=first + statics)
    menus, slider = _anim_controls(hours, redraw=False, speeds=[(PLAY_MS, "Play")])
    menus[0].update(bgcolor="#1f2937", bordercolor="#374151", font=dict(color=NET_FG))
    slider[0].update(bgcolor="#1f2937", activebgcolor="#22d3ee", bordercolor="#374151", font=dict(color=NET_FG),
                     currentvalue=dict(prefix="Hour ", font=dict(color=NET_FG)))
    fig.update_layout(updatemenus=menus, sliders=slider)
    fig.update_xaxes(visible=False, range=[-0.03, 1.03])
    fig.update_yaxes(visible=False, range=[-0.03, 1.06], scaleanchor="x")
    _style(fig, 900)
    fig.update_layout(template="plotly_dark", paper_bgcolor=NET_BG, plot_bgcolor=NET_BG, font=dict(color=NET_FG),
                      hoverlabel=dict(bgcolor="#111827", font=dict(color=NET_FG)),
                      legend=dict(y=-0.02, yanchor="top", bgcolor="rgba(0,0,0,0)", font=dict(color=NET_FG)),
                      margin=dict(t=60, b=140, l=10, r=10))
    return _with_frames(fig, [(str(t), frame_traces(j), list(range(n_dyn))) for j, t in enumerate(hours)])


def bars_figure(data, lo, hi):
    from dashboard.data import topology as topo
    from plotly.subplots import make_subplots

    flow, rating = _flow_table(data["flows"], lo, hi)
    hours = list(flow.columns)
    active = flow.index[(flow.abs() >= topo.EMPTY_MW).any(axis=1)]
    rated = [l for l in active if np.isfinite(rating[l]) and rating[l] > 0]
    unlim = [l for l in active if l not in rated]
    load = flow.loc[rated].abs().div(rating[rated], axis=0) * 100 if rated else pd.DataFrame(columns=hours)
    rated = list(load.max(axis=1).sort_values(ascending=False).index) if rated else []
    unlim = list(flow.loc[unlim].abs().max(axis=1).sort_values(ascending=False).index) if unlim else []

    def traces(t):
        rc = [topo.CLASS_COLOURS[topo.line_class(flow.at[l, t], rating[l])] for l in rated]
        uc = [topo.CLASS_COLOURS[topo.line_class(flow.at[l, t], np.inf)] for l in unlim]
        return [dict(type="bar", y=rated, x=[load.at[l, t] for l in rated], orientation="h", marker_color=rc,
                       name="Rated lines (% of rating)", hovertemplate="%{y}: %{x:.1f}%<extra></extra>"),
                dict(type="bar", y=unlim, x=[abs(flow.at[l, t]) for l in unlim], orientation="h", marker_color=uc,
                       name="Unlimited lines (MW)", xaxis="x2", yaxis="y2",
                       hovertemplate="%{y}: %{x:.1f} MW<extra></extra>")]

    fig = make_subplots(rows=1, cols=2, column_widths=[0.55, 0.45], horizontal_spacing=0.12,
                        subplot_titles=("Rated lines - %% of rating (%d)" % len(rated),
                                        "Unlimited (inf) lines - MW (%d)" % len(unlim)))
    first = traces(hours[0]) if hours else []
    for i, tr in enumerate(first):
        tr.update(xaxis=None, yaxis=None)
        fig.add_trace(tr, row=1, col=i + 1)
    umax = float(flow.loc[unlim].abs().values.max()) * 1.05 if unlim else 1
    fig.update_xaxes(range=[0, 110], title_text="% of rating", row=1, col=1)
    fig.update_xaxes(range=[0, umax], title_text="MW", row=1, col=2)
    fig.update_yaxes(categoryorder="array", categoryarray=rated[::-1], tickfont=dict(size=9), row=1, col=1)
    fig.update_yaxes(categoryorder="array", categoryarray=unlim[::-1], tickfont=dict(size=9), row=1, col=2)
    for x in (GREEN_LINE, YELLOW_LINE):
        fig.add_vline(x=x, line=dict(color="#888888", dash="dot", width=1), row=1, col=1)
    menus, slider = _anim_controls(hours, redraw=True)
    fig.update_layout(updatemenus=menus, sliders=slider, showlegend=False)
    _style(fig, max(len(rated), len(unlim), 10) * 14 + 260)
    fig.update_layout(margin=dict(t=90, b=60, l=70, r=20))
    return _with_frames(fig, [(str(t), traces(t), [0, 1]) for t in hours])


GREEN_LINE, YELLOW_LINE = 50, 90


def line_heat_figure(data, lo, hi):
    from dashboard.data import topology as topo

    flow, rating = _flow_table(data["flows"], lo, hi)
    rated = [l for l in flow.index if np.isfinite(rating[l]) and rating[l] > 0
             and (flow.loc[l].abs() >= topo.EMPTY_MW).any()]
    if not rated:
        return _empty("No rated line carries power in the selected hours")
    load = flow.loc[rated].abs().div(rating[rated], axis=0) * 100
    load = load.where(flow.loc[rated].abs() >= topo.EMPTY_MW)  # empty -> grey background
    load = load.loc[load.max(axis=1).sort_values().index]
    g, y, r = topo.CLASS_COLOURS["low"], topo.CLASS_COLOURS["medium"], topo.CLASS_COLOURS["high"]
    a, b = GREEN_LINE / 110, YELLOW_LINE / 110
    scale = [[0, g], [a, g], [a, y], [b, y], [b, r], [1, r]]
    fig = go.Figure(go.Heatmap(x=list(load.columns), y=list(load.index), z=load.values, zmin=0, zmax=110,
                               colorscale=scale, colorbar=dict(title="% of rating"),
                               hovertemplate="Hour %{x}<br>%{y}<br>%{z:.1f}%<extra></extra>"))
    fig.update_layout(xaxis_title="Hour", yaxis_title="Line", yaxis_type="category",
                      plot_bgcolor=topo.CLASS_COLOURS["empty"])
    fig.update_yaxes(tickfont=dict(size=8))
    return _style(fig, max(400, len(rated) * 6 + 150))


def node_congestion_figure(data, lo, hi):
    lmp = data["lmp"].loc[lo:hi]
    cong = lmp.sub(data["dispatch"].loc[lo:hi, "SystemPrice"], axis=0)
    cols = list(cong.mean().sort_values().index)
    fig = go.Figure(go.Heatmap(x=list(cong.index), y=[str(c) for c in cols], z=cong[cols].T.values,
                               colorscale="RdBu_r", zmid=0, colorbar=dict(title="$/MWh"),
                               hovertemplate="Hour %{x}<br>Node %{y}<br>LMP - system %{z:.2f}<extra></extra>"))
    fig.update_layout(xaxis_title="Hour", yaxis_title="Node (sorted by average congestion)", yaxis_type="category")
    fig.update_yaxes(showticklabels=False)
    return _style(fig, 800)


EXTRA_FIGS = {"bars": bars_figure, "line_heat": line_heat_figure,
              "node_cong": node_congestion_figure}


# ---------------- callbacks ----------------

def _load():
    try:
        return nodal.load_nodal(), None
    except Exception as e:  # missing gdx / gdxpds problems -> message on the page
        return None, str(e)


def update(hours, scope, nodes, line):
    data, err = _load()
    if data is None:
        msg = "No Nodal_SC results: %s" % err
        return [msg, html.Div(msg, className="text-danger")] + [_empty("No results") for _ in FIG_KEYS]
    lo, hi = hour_window(hours, len(data["dispatch"]))
    figs = [figure(k, data, lo, hi, scope, nodes, line) for k in MAIN_KEYS]
    window = "Hours %d - %d of %d" % (lo, hi, len(data["dispatch"]))
    return [window, kpi_tiles(window_kpis(data, lo, hi))] + figs


def register_callbacks(app):
    @app.callback(Output("n-nodes", "options"), Output("n-line", "options"), Output("n-line", "value"),
                  Input("n-scope", "value"), Input("n-version", "data"), State("n-line", "value"))
    def _options(scope, _v, line):
        data, _ = _load()
        if data is None:
            return [], [], None
        lines = line_options(data)
        values = [o["value"] for o in lines]
        return node_options(data, scope), lines, line if line in values else (values[0] if values else None)

    @app.callback([Output("n-window", "children"), Output("n-kpis", "children")]
                  + [Output("n-fig-" + k, "figure") for k in MAIN_KEYS],
                  Input("n-hours", "value"), Input("n-scope", "value"), Input("n-nodes", "value"),
                  Input("n-line", "value"), Input("n-version", "data"))
    def _update(hours, scope, nodes, line, _v):
        with access.PLOT_LOCK:
            return update(hours, scope, nodes, line)

    @app.callback(Output("n-fig-network", "figure"),
                  Input("n-hours", "value"), Input("n-infl-gens", "value"), Input("n-sf", "value"),
                  Input("n-version", "data"))
    def _network(hours, gens_sel, sf, _v):
        data, _ = _load()
        if data is None:
            return _empty("No results")
        lo, hi = hour_window(hours, len(data["dispatch"]))
        with access.PLOT_LOCK:
            return network_figure(data, lo, hi, gens_sel, sf or 0.1)

    @app.callback(Output("n-status", "children"), Output("n-version", "data"),
                  Input("n-rerun", "n_clicks"), State("n-version", "data"), prevent_initial_call=True)
    def _rerun(_n, version):
        try:
            msg = runner.run_nodal()
        except (runner.GamsRunError, OSError) as e:
            return "Error: %s" % e, dash.no_update
        return msg, (version or 0) + 1
