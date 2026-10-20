"""Nodal page: loader, figures, routing / sidebar hiding and the re-run command (no GAMS needed)."""
import math

import pandas as pd
import pytest

from dashboard import config
from dashboard.data import nodal, runner
from dashboard.pages import nodal as page

EPS = 2.220446049250313e-16


@pytest.fixture
def gens():
    return pd.DataFrame({"MC": [0, 50], "CAP": [100, 50], "NODE": ["10", "20"]},
                        index=pd.Index(["G1", "G2"], name="gen"))


@pytest.fixture
def dfs():
    hours = ["1", "2", "3"]
    dispatch = []
    for t, (g1, g2) in zip(hours, [(80, 0), (100, 20), (100, 40)]):
        dispatch += [(t, "G1", g1), (t, "G2", g2 or EPS), (t, "SystemPrice", 0 if t == "1" else 50),
                     (t, "TotalDemand", g1 + g2), (t, "Unserved", EPS)]
    lmp = [(t, n, v) for t in hours for n, v in (("10", 0 if t == "1" else 50), ("20", 50), ("30", 50 if t != "3" else 120))]
    lmp = [r for r in lmp if r[2] != 0]  # gdx drops zeros
    flowrep = [("L1", t, "Flow", f) for t, f in zip(hours, (40, 90, 100))]
    flowrep += [("L1", "3", "CongestionPrice", 70.0)]
    flowrep += [("L2", t, "Flow", -5.0) for t in hours]
    return {
        "Dispatch": pd.DataFrame(dispatch, columns=["T", "*", "Value"]),
        "LMP": pd.DataFrame(lmp, columns=["T", "n", "Value"]),
        "LMPrep": pd.DataFrame([r for r in lmp if r[1] in ("10", "20")], columns=["T", "n", "Value"]),
        "FlowRep": pd.DataFrame(flowrep, columns=["l", "T", "fcol", "Value"]),
        "rating": pd.DataFrame([("L1", 100.0), ("L2", math.inf)], columns=["l", "Value"]),
        "dem": pd.DataFrame([("1", "20", 80.0), ("2", "20", 120.0), ("3", "20", 140.0)], columns=["T", "n", "Value"]),
        "ptdf": pd.DataFrame([("L1", "10", 0.5), ("L1", "30", 0.2)], columns=["l", "n", "Value"]),
        "TOTCost": pd.DataFrame({"Level": [3000.0]}),
    }


@pytest.fixture
def data(dfs, gens):
    return nodal.build(dfs, gens)


def test_build_pivots_and_fills_zeros(data):
    d = data["dispatch"]
    assert list(d.index) == [1, 2, 3]
    assert d.loc[1, "G2"] == 0 and d.loc[1, "Unserved"] == 0   # EPS -> 0
    assert d.loc[3, "G2"] == 40
    assert data["lmp"].loc[1, "10"] == 0                        # dropped zero restored
    assert data["key_nodes"] == ["10", "20"]
    assert data["kpis"]["total_cost"] == 3000.0
    assert data["kpis"]["congested_line_hours"] == 1


def test_loading_blank_for_inf_lines(data):
    f = data["flows"].set_index(["l", "T"])
    assert f.loc[("L1", 3), "Loading"] == pytest.approx(100.0)
    assert f.loc[("L2", 1), "Loading"] != f.loc[("L2", 1), "Loading"]  # NaN
    assert math.isinf(f.loc[("L2", 1), "Rating"])


def test_line_ranking_puts_congested_first(data):
    assert list(nodal.line_ranking(data["flows"]).index)[0] == "L1"


@pytest.mark.parametrize("key", page.FIG_KEYS)
def test_every_figure_builds(data, key):
    fig = page.figure(key, data, 1, 3, page.SCOPE_KEY, None, "L1")
    traces = fig["data"] if isinstance(fig, dict) else fig.data
    assert len(traces) >= 1


def test_25_node_heatmap_removed():
    assert "heat_key" not in page.FIG_KEYS and "heat_all" in page.FIG_KEYS
    assert page.FIG_KEYS[:5] == ["dispatch", "network", "line_heat", "node_cong", "bars"]


def test_line_class_colours():
    from dashboard.data import topology as t
    assert t.line_class(0.05, 100) == "empty"
    assert t.line_class(0.05, math.inf) == "empty"
    assert t.line_class(5, math.inf) == "unlimited"
    assert t.line_class(-49, 100) == "low"
    assert t.line_class(50, 100) == "medium"
    assert t.line_class(-90, 100) == "high"


def test_guess_line_ends():
    from dashboard.data import topology as t
    ptdf = pd.DataFrame([("LA", "a", 0.6), ("LA", "b", -0.4),       # normal: max -> min
                         ("LB", "a", 0.3), ("LB", "b", 0.1),        # no negative -> reference bus
                         ("LC", "c", 1.0)],                         # radial -> most similar column
                        columns=["l", "n", "Value"])
    ends = t.guess_line_ends(ptdf, ["a", "b", "c", "ref"]).set_index("l")
    assert tuple(ends.loc["LA"]) == ("a", "b")
    assert tuple(ends.loc["LB"]) == ("a", "ref")
    assert ends.loc["LC", "from"] == "c" and ends.loc["LC", "to"] != "c"


def test_layout_deterministic_and_cached(tmp_path):
    from dashboard.data import topology as t
    ptdf = pd.DataFrame([("LA", "a", 0.6), ("LA", "b", -0.4), ("LB", "b", 0.5), ("LB", "c", -0.5)],
                        columns=["l", "n", "Value"])
    p1 = t.force_layout(["a", "b", "c"], [("a", "b"), ("b", "c")])
    p2 = t.force_layout(["a", "b", "c"], [("a", "b"), ("b", "c")])
    assert p1.equals(p2)
    topo = t.get_topology(ptdf, ["a", "b", "c"], tmp_path)
    assert (tmp_path / "lines_guess.csv").exists() and (tmp_path / "layout_guess.csv").exists()
    assert topo["guessed"]
    (tmp_path / "lines(in).csv").write_text("LINE_ID,FROM,TO\nLA,c,a\n")
    real = t.get_topology(ptdf, ["a", "b", "c"], tmp_path)
    assert not real["guessed"] and tuple(real["lines"].iloc[0]) == ("LA", "c", "a")


def test_films_have_frames_and_speeds(data):
    for key in ("network", "bars"):
        fig = page.figure(key, data, 1, 3)
        assert [f["name"] for f in fig["frames"]] == ["1", "2", "3"]
        labels = [b["label"] for b in fig["layout"]["updatemenus"][0]["buttons"]]
        assert labels[:3] == ["\u25B6 1 s/h", "\u25B6 2 s/h", "\u25B6 5 s/h"]
        assert fig["layout"]["updatemenus"][0]["buttons"][0]["args"][1]["frame"]["duration"] == 1000
        assert len(fig["layout"]["sliders"][0]["steps"]) == 3
    assert len(page.figure("network", data, 2, 3)["frames"]) == 2   # follows the hour range


def test_network_colours_by_hour(data):
    from dashboard.data import topology as t
    fig = page.figure("network", data, 1, 3)
    red = t.CLASS_COLOURS["high"]

    def has_red(traces):
        return any(tr.get("line", {}).get("color") == red and tr["x"] for tr in traces)
    frames = {f["name"]: f["data"] for f in fig["frames"]}
    assert has_red(frames["2"]) and has_red(frames["3"]) and not has_red(frames["1"])  # L1 90% / 100%
    assert page.NETWORK_NOTE.startswith("Illustrative only")
    assert "Illustrative only" in str(page.layout())


def test_bar_film_and_heatmaps(data):
    from dashboard.data import topology as t
    bars = page.figure("bars", data, 1, 3)
    assert bars["data"][0]["y"] == ["L1"] and bars["data"][1]["y"] == ["L2"]   # rated | inf
    f3 = {f["name"]: f["data"] for f in bars["frames"]}["3"]
    assert f3[0]["marker_color" if "marker_color" in f3[0] else "marker"] in ([t.CLASS_COLOURS["high"]],
                                                                             {"color": [t.CLASS_COLOURS["high"]]})
    assert f3[1]["marker_color"] == [t.CLASS_COLOURS["unlimited"]]
    lh = page.figure("line_heat", data, 1, 3)
    assert list(lh.data[0].y) == ["L1"]
    nc = page.figure("node_cong", data, 1, 3)
    assert nc.data[0].zmid == 0
    assert list(nc.data[0].y)[-1] == "30"   # most positive congestion last


def test_figure_details(data):
    assert [t.name for t in page.figure("dispatch", data, 1, 3).data] == ["G1", "G2", "Demand"]
    assert list(page.figure("spread", data, 1, 3).data[0].y) == [50, 0, 0]
    assert len(page.figure("loading", data, 1, 3, line="L1").data) == 3   # flow + two ratings
    assert len(page.figure("loading", data, 1, 3, line="L2").data) == 1   # inf: flow only
    assert len(page.figure("duration", data, 1, 3, page.SCOPE_ALL).data) == 3
    assert len(page.figure("duration", data, 1, 3, page.SCOPE_KEY, ["20"]).data) == 1
    heat_all = page.figure("heat_all", data, 1, 3)
    assert list(heat_all.data[0].y)[-1] == "30"   # sorted by average LMP


def test_window_kpis_and_hour_window(data):
    assert page.hour_window([5, 2]) == (2, 5)
    assert page.hour_window(None, 3) == (1, 3)
    k = page.window_kpis(data, 2, 3)
    assert k["total_cost"] == 50 * 60 and k["max_spread"] == 0


def test_layout_ids_and_sidebar_order():
    text = str(page.layout())
    for i in ["n-hours", "n-scope", "n-nodes", "n-line", "n-rerun", "n-status", "n-kpis"] + \
             ["n-fig-" + k for k in page.FIG_KEYS]:
        assert i in text
    assert "Back to dashboard" in text
    from dashboard.components import sidebar
    s = str(sidebar.layout())
    order = [s.index(x) for x in ("Granular prices", "Summary metrics", "Diagnostics", "'Nodal'")]
    assert order == sorted(order)


def test_sidebar_hidden_only_on_nodal():
    from dashboard import app as app_mod
    side, pg = app_mod.chrome_styles(config.NODAL_PATH)
    assert side["display"] == "none" and pg["marginLeft"] == "0"
    side, pg = app_mod.chrome_styles("/summary")
    assert side.get("display") != "none" and pg["marginLeft"] == "19rem"


def test_run_nodal_command_and_cache(monkeypatch, tmp_path):
    lst = tmp_path / config.NODAL["lst"]
    lst.parent.mkdir(parents=True)
    calls = []

    class Proc:
        returncode, stderr = 0, ""

    def fake_run(cmd, cwd, **kw):
        calls.append((cmd, cwd))
        lst.write_text("**** MODEL STATUS      1 Optimal\n")
        return Proc()

    cleared = []
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(nodal, "clear_cache", lambda: cleared.append(1))
    msg = runner.run_nodal(tmp_path)
    cmd, cwd = calls[0]
    assert cmd[1] == str(config.NODAL["gms"]) and "--outdir=Results" in cmd and "--noxlsx=1" in cmd
    assert cwd == str(tmp_path) and "Optimal" in msg and cleared


def test_run_nodal_failure(monkeypatch, tmp_path):
    (tmp_path / "outputs").mkdir()
    (tmp_path / config.NODAL["lst"]).write_text("**** MODEL STATUS      4 Infeasible\n")

    class Proc:
        returncode, stderr = 0, ""

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(runner.GamsRunError):
        runner.run_nodal(tmp_path)


def test_spurs_link_every_node_but_reference():
    from dashboard.data import topology as t
    ptdf = pd.DataFrame([("LA", "a", 0.6), ("LA", "b", -0.4), ("LA", "g", 0.3),
                         ("LB", "b", 0.5), ("LB", "c", -0.5), ("LB", "g", -0.45)],
                        columns=["l", "n", "Value"])
    nodes = ["a", "b", "c", "g", "ref"]
    lines = t.guess_line_ends(ptdf, nodes)
    sp = t.spurs(ptdf, lines, nodes)
    linked = set(lines["from"]) | set(lines["to"]) | set(sp["n"])
    assert "g" in set(sp["n"]) and sp.set_index("n").loc["g", "l"] == "LB"   # largest |SF|
    assert set(nodes) - linked <= {"ref"}


def test_real_data_every_generator_linked():
    from dashboard.data import nodal as nd
    try:
        d = nd.load_nodal()
    except Exception:
        pytest.skip("Nodal_SC results / gdxpds not available")
    tp = d["topology"]
    linked = set(tp["lines"]["from"]) | set(tp["lines"]["to"]) | set(tp["spurs"]["n"])
    assert set(d["gens"]["NODE"]) <= linked
    assert set(d["lmp"].columns) - linked <= {"1483"}


def test_generator_hover_and_influence_lines(data):
    from dashboard.data import topology as t
    data = dict(data, gens=data["gens"].rename(index={"G1": "GENERATOR_1", "G2": "GENERATOR_3"}))
    data["ptdf"] = pd.DataFrame([("L1", "10", 0.5), ("L2", "10", -0.2), ("L1", "20", 0.05), ("L2", "20", 0.3)],
                                columns=["l", "n", "Value"])
    data["topology"] = t.get_topology(data["ptdf"], data["lmp"].columns)
    none = page.figure("network", data, 1, 3)
    assert not any(str(tr.get("name", "")).endswith("lines)") for tr in none["data"])
    fig = page.figure("network", data, 1, 3, infl_gens=["GENERATOR_1", "GENERATOR_3"], sf_threshold=0.1)
    hov = [tr for tr in fig["data"] if tr.get("hoverinfo") == "text" and "\u2192" in str(tr.get("text"))]
    texts = sorted(x for tr in hov for x in tr["text"])
    assert texts == ["GEN_1 \u2192 L1: SF 0.50", "GEN_1 \u2192 L2: SF -0.20", "GEN_3 \u2192 L2: SF 0.30"]
    gen = [tr for tr in fig["data"] if tr.get("name") == "GEN_1"][0]
    assert "Top lines by shift factor: L1 0.50, L2 -0.20" in gen["hovertext"][0]
