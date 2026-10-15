"""Sidebar: global run selector, snapshot controls, navigation."""
import dash_bootstrap_components as dbc
from dash import dcc, html

from dashboard import config
from dashboard.data import access, metrics, versions


def run_options():
    opts = []
    for label, path in versions.list_runs():
        if label == config.CURRENT:
            opts.append({"label": "Current (repo root)", "value": label})
        else:
            note = versions.read_meta(path).get("note", "")
            opts.append({"label": label + (" - " + note if note else ""), "value": label})
    return opts


def layout():
    return html.Div(
        [
            html.H4("Dispatch Model", className="mb-3"),
            dbc.Nav(
                [
                    dbc.NavLink("Granular prices", href="/", active="exact"),
                    dbc.NavLink("Summary metrics", href="/summary", active="exact"),
                    dbc.NavLink("Diagnostics", href="/diagnostics", active="exact"),
                ],
                vertical=True, pills=True, className="mb-4",
            ),
            html.Label("Runs to display", className="fw-bold"),
            dcc.Dropdown(id="run-select", options=run_options(), value=[config.CURRENT],
                         multi=True, clearable=False, persistence=True),
            dcc.Store(id="run-store", data=[config.CURRENT]),
            html.Hr(),
            html.Label("Days shown", className="fw-bold"),
            dcc.Slider(id="days", min=access.MIN_DAYS, max=access.MAX_DAYS, step=1,
                       value=config.WINDOW_DAYS, persistence=True,
                       marks={d: str(d) for d in (1, 7, 14, 21, 28, 35)},
                       tooltip={"placement": "bottom", "always_visible": True}),
            html.Label("Start date", className="fw-bold mt-4"),
            html.Div([
                dbc.Button("<", id="date-prev", outline=True, size="sm", className="me-1"),
                dcc.DatePickerSingle(id="date-start", display_format="YYYY-MM-DD", persistence=True),
                dbc.Button(">", id="date-next", outline=True, size="sm", className="ms-1"),
            ], className="d-flex align-items-center"),
            html.Div(id="date-range", className="small text-muted mt-1"),
            html.Label("Aggregation", className="fw-bold mt-3"),
            dbc.RadioItems(id="freq", value="M", inline=True, persistence=True,
                           options=[{"label": v, "value": k} for k, v in metrics.FREQS.items()]),
            html.Label("Generators", className="fw-bold mt-3"),
            dbc.Checklist(id="gens", value=list(config.GENERATORS), inline=True, persistence=True,
                          options=[{"label": g, "value": g} for g in config.GENERATORS]),
            html.Hr(),
            html.Label("Save current outputs as...", className="fw-bold"),
            dbc.Input(id="snap-label", placeholder="label e.g. base_v1", className="mb-2"),
            dbc.Input(id="snap-note", placeholder="note (optional)", className="mb-2"),
            dbc.Checkbox(id="snap-force", label="Overwrite if exists", value=False),
            dbc.Button("Save snapshot", id="snap-btn", color="primary", size="sm", className="mt-2"),
            html.Div(id="snap-status", className="small mt-2"),
            html.Hr(),
            html.Div("Hour 1 = " + str(config.START_DATETIME), className="small text-muted"),
        ],
        style={"position": "fixed", "top": 0, "left": 0, "bottom": 0, "width": "18rem",
               "padding": "1.5rem 1rem", "backgroundColor": "#f8f9fa", "overflowY": "auto"},
    )
