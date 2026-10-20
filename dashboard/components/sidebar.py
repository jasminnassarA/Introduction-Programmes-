"""Sidebar: scenario selector, hour window, generator filter, navigation."""
import dash_bootstrap_components as dbc
from dash import dcc, html

from dashboard import config
from dashboard.data import access, runner


STYLE = {"position": "fixed", "top": 0, "left": 0, "bottom": 0, "width": "18rem",
         "padding": "1.5rem 1rem", "backgroundColor": "#f8f9fa", "overflowY": "auto"}


def scenario_options():
    opts = [{"label": s["label"], "value": k} for k, s in config.SCENARIOS.items()]
    opts.append({"label": "All (compare)", "value": config.BOTH})
    return opts


def _with_base(options, base):
    """Dropdown options, making sure the csv base value is selectable."""
    return sorted(set(options) | ({base} if base is not None else set()))


def layout():
    base = runner.default_caps()
    return html.Div(
        [
            html.H4("Dispatch Model", className="mb-3"),
            dbc.Nav(
                [
                    dbc.NavLink("Granular prices", href="/", active="exact"),
                    dbc.NavLink("Summary metrics", href="/summary", active="exact"),
                    dbc.NavLink("Diagnostics", href="/diagnostics", active="exact"),
                    dbc.NavLink("Nodal", href=config.NODAL_PATH, active="exact"),
                    dbc.NavLink("Interconnectors", href=config.INTERCONNECTORS_PATH, active="exact"),
                ],
                vertical=True, pills=True, className="mb-4",
            ),
            html.Label("Scenario", className="fw-bold"),
            dcc.Dropdown(id="scenario", options=scenario_options(), value=config.DEFAULT_SCENARIO,
                         clearable=False, persistence=True),
            html.Label("Capacities (MW)", className="fw-bold mt-3"),
            *[html.Div([
                html.Span(g, className="small", style={"width": "3.5rem"}),
                html.Div(dcc.Dropdown(id="cap-" + g.lower(), options=[{"label": str(c), "value": c}
                                                                      for c in runner.cap_options(g)],
                                      value=base[g], clearable=False), style={"flex": 1}),
            ], className="d-flex align-items-center mb-1") for g in config.CAP_GENERATORS],
            html.Div("Wind applies to the renewable, ramping and batteries scenarios.", className="small text-muted"),
            html.Label("Battery", className="fw-bold mt-3"),
            *[html.Div([
                html.Span(lab, className="small", style={"width": "5.5rem"}),
                html.Div(dcc.Dropdown(id=cid, options=[{"label": "{:,}".format(v), "value": v} for v in opts],
                                      value=base.get(name, opts[0]), clearable=False), style={"flex": 1}),
            ], className="d-flex align-items-center mb-1") for lab, cid, name, opts in [
                ("Capacity MWh", "bat-cap", "BatCap", _with_base(config.BAT_CAP_OPTIONS, base.get("BatCap"))),
                ("Power MW", "bat-power", "BatPower", _with_base(config.BAT_POWER_OPTIONS, base.get("BatPower"))),
            ]],
            *[html.Div([
                html.Span(lab, className="small"),
                dcc.Slider(id=cid, min=config.BAT_EFF_MIN, max=config.BAT_EFF_MAX, step=config.BAT_EFF_STEP,
                           value=base.get(name, 0.95),
                           marks={v: "%.1f" % v for v in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)},
                           tooltip={"placement": "bottom", "always_visible": True}),
            ], className="mb-3") for lab, cid, name in [("Charging efficiency", "bat-ch-eff", "BatChEff"),
                                                        ("Discharging efficiency", "bat-dis-eff", "BatDisEff")]],
            html.Div("Battery settings apply to the Batteries scenario only.", className="small text-muted"),
            dbc.Button("Run models", id="run-models", color="primary", size="sm", className="mt-2 w-100"),
            dcc.Store(id="caps", data=base),
            dcc.Loading(html.Div(id="run-status", className="small text-muted mt-1",
                                 style={"whiteSpace": "pre-wrap"}), type="dot"),
            html.Hr(),
            html.Label("Hours shown", className="fw-bold"),
            dcc.Slider(id="hours", min=access.MIN_HOURS, max=access.MAX_HOURS, step=24,
                       value=config.WINDOW_HOURS, persistence=True,
                       marks={h: str(h) for h in (24, 168, 336, 504, 744)},
                       tooltip={"placement": "bottom", "always_visible": True}),
            html.Div(id="hour-range", className="small text-muted mt-4"),
            html.Label("Generators", className="fw-bold mt-3"),
            # persistence key bumped so saved selections from before Battery existed are reset once
            dbc.Checklist(id="gens", value=list(config.CHECKLIST_ITEMS), inline=True, persistence="gens-v2",
                          options=[{"label": g, "value": g} for g in config.CHECKLIST_ITEMS]),
        ],
        id="sidebar", style=STYLE,
    )
