"""Dash entry point: python -m dashboard.app  ->  http://127.0.0.1:8050"""
import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, State, callback_context, dcc, html

from dashboard import config
from dashboard.components import sidebar
from dashboard.data import access, versions
from dashboard.pages import diagnostics, granular, summary

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP],
                suppress_callback_exceptions=True, title="Dispatch Dashboard")

app.layout = html.Div([
    dcc.Location(id="url"),
    sidebar.layout(),
    html.Div(id="page", style={"marginLeft": "19rem", "padding": "1.5rem"}),
])


@app.callback(Output("page", "children"), Input("url", "pathname"))
def route(path):
    if path == "/summary":
        return summary.layout()
    if path == "/diagnostics":
        return diagnostics.layout()
    return granular.layout()


@app.callback(Output("run-store", "data"), Input("run-select", "value"))
def sync_runs(value):
    return value or [config.CURRENT]


@app.callback(
    Output("date-start", "date"), Output("date-start", "min_date_allowed"),
    Output("date-start", "max_date_allowed"),
    Input("run-store", "data"), Input("date-prev", "n_clicks"), Input("date-next", "n_clicks"),
    Input("days", "value"),
    State("date-start", "date"),
)
def set_start(runs, _p, _n, days, current):
    days = access.clamp_days(days)
    df, _ = access.load_selected(runs)
    if df.empty:
        return None, None, None
    lo = df["datetime"].min().normalize()
    hi = max(lo, df["datetime"].max().normalize() - pd.Timedelta(days=days - 1))
    cur = pd.Timestamp(current) if current else lo
    trig = callback_context.triggered[0]["prop_id"].split(".")[0] if callback_context.triggered else ""
    step = pd.Timedelta(days=days)
    if trig == "date-prev":
        cur -= step
    elif trig == "date-next":
        cur += step
    cur = min(max(cur, lo), hi)
    return cur.date().isoformat(), lo.date().isoformat(), hi.date().isoformat()


@app.callback(Output("date-range", "children"),
              Input("date-start", "date"), Input("days", "value"), Input("run-store", "data"))
def show_range(start, days, runs):
    df, _ = access.load_selected(runs)
    if df.empty or not start:
        return ""
    _, s, last = access.filter_window(df, start, days)
    return access.range_label(s, last)


@app.callback(
    Output("snap-status", "children"), Output("run-select", "options"),
    Input("snap-btn", "n_clicks"),
    State("snap-label", "value"), State("snap-note", "value"), State("snap-force", "value"),
    prevent_initial_call=True,
)
def save_snapshot(_n, label, note, force):
    try:
        dest = versions.snapshot(label, note or "", bool(force))
        msg = html.Span("Saved to " + str(dest), className="text-success")
    except Exception as e:  # show any error to the user
        msg = html.Span(str(e), className="text-danger")
    return msg, sidebar.run_options()


granular.register_callbacks(app)
summary.register_callbacks(app)
diagnostics.register_callbacks(app)

if __name__ == "__main__":
    app.run_server(debug=True, host="127.0.0.1", port=8050)
