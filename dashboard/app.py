"""Dash entry point: python -m dashboard.app  ->  http://127.0.0.1:8050"""
import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dcc, html

from dashboard import config
from dashboard.components import sidebar
from dashboard.data import access, runner
from dashboard.pages import diagnostics, granular, interconnectors, nodal, summary

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP],
                suppress_callback_exceptions=True, title="Dispatch Dashboard")

PAGE_STYLE = {"marginLeft": "19rem", "padding": "1.5rem"}
FULL_PAGE_STYLE = {"marginLeft": "0", "padding": "1.5rem"}

app.layout = html.Div([
    dcc.Location(id="url"),
    sidebar.layout(),
    dcc.Loading(html.Div(id="page", style=PAGE_STYLE), type="circle", fullscreen=False),
])


@app.callback(Output("page", "children"), Input("url", "pathname"))
def route(path):
    if path == "/summary":
        return summary.layout()
    if path == "/diagnostics":
        return diagnostics.layout()
    if path == config.NODAL_PATH:
        return nodal.layout()
    if path == config.INTERCONNECTORS_PATH:
        return interconnectors.layout()
    return granular.layout()


def chrome_styles(path):
    """(sidebar style, page style): the nodal page hides the sidebar and uses the full width."""
    if path in (config.NODAL_PATH, config.INTERCONNECTORS_PATH):
        return dict(sidebar.STYLE, display="none"), FULL_PAGE_STYLE
    return sidebar.STYLE, PAGE_STYLE


@app.callback(Output("sidebar", "style"), Output("page", "style"), Input("url", "pathname"))
def toggle_sidebar(path):
    return chrome_styles(path)


BAT_CONTROLS = {"BatCap": "bat-cap", "BatPower": "bat-power", "BatChEff": "bat-ch-eff", "BatDisEff": "bat-dis-eff"}
CONTROL_NAMES = list(config.CAP_GENERATORS) + list(BAT_CONTROLS)


@app.callback(
    Output("caps", "data"), Output("run-status", "children"),
    Input("run-models", "n_clicks"),
    [State("cap-" + g.lower(), "value") for g in config.CAP_GENERATORS]
    + [State(cid, "value") for cid in BAT_CONTROLS.values()],
    prevent_initial_call=True,
)
def run_models(_n, *values):
    """Solve the chosen capacities / battery settings (in memory, nothing saved) and apply them."""
    caps = runner.normalize(dict(zip(CONTROL_NAMES, values)))
    try:
        runner.get_results(caps)
    except (runner.GamsRunError, OSError) as e:
        return dash.no_update, "Error: %s" % e
    return caps, runner.last_status


@app.callback(Output("hour-range", "children"),
              Input("hours", "value"), Input("scenario", "value"), Input("caps", "data"))
def show_range(hours, scenario, caps):
    df, _ = access.load_selected(scenario, caps)
    if df.empty:
        return ""
    _, s, last = access.filter_window(df, 1, hours)
    return access.range_label(s, last)


runner.cleanup_tmp()


granular.register_callbacks(app)
summary.register_callbacks(app)
diagnostics.register_callbacks(app)
nodal.register_callbacks(app)
interconnectors.register_callbacks(app)

if __name__ == "__main__":
    import os

    # DASH_DEBUG=0 (set by setup_and_run.bat) runs without the reloader so the app starts once.
    debug = os.environ.get("DASH_DEBUG", "1") != "0"
    app.run_server(debug=debug, host="127.0.0.1", port=8050)
