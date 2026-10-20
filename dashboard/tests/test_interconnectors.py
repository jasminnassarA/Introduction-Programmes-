"""Interconnectors page / loader / runner tests - no GAMS needed (except the optional real-data test)."""
import pandas as pd
import plotly.graph_objects as go
import pytest

from dashboard import config
from dashboard.data import interconnectors as ic
from dashboard.data import runner
from dashboard.pages import interconnectors as page

EPS = 5e-324  # gdxpds EPS


@pytest.fixture
def dfs():
    disp = []
    for t in (1, 2, 3):
        disp += [["R1", str(t), "Gas", 100.0], ["R1", str(t), "Demand", 150.0], ["R1", str(t), "Import", 50.0],
                 ["R2", str(t), "Wind", 260.0], ["R2", str(t), "Demand", 200.0], ["R2", str(t), "Export", 60.0]]
    disp.append(["R1", "3", "Unserved", EPS])
    return {
        "Dispatch": pd.DataFrame(disp, columns=["r", "T", "col", "Value"]),
        "Price": pd.DataFrame([["R1", "1", 40.0], ["R2", "1", 10.0], ["R1", "2", 20.0], ["R2", "2", 20.0],
                               ["R1", "3", EPS], ["R2", "3", 5.0]], columns=["r", "T", "Value"]),
        "FlowRep": pd.DataFrame([["R2", "R1", "1", 60.0], ["R2", "R1", "2", 60.0], ["R1", "R2", "3", 10.0]],
                                columns=["r", "rr", "T", "Value"]),
        "icdata": pd.DataFrame([["R1", "R2", "cap", 60.0], ["R1", "R2", "loss", 0.025],
                                ["R2", "R1", "cap", 60.0], ["R2", "R1", "loss", 0.025]],
                               columns=["r", "rr", "lf", "Value"]),
        "gdata": pd.DataFrame([["R1", "Gas", "cap", 600.0], ["R2", "Wind", "cap", 1500.0]],
                              columns=["r", "gen", "f", "Value"]),
        "TOTCost": pd.DataFrame([[1234.0, 0, 0, 0, 1]], columns=["Level", "Marginal", "Lower", "Upper", "Scale"]),
        "ra": pd.DataFrame([["R1", True], ["R2", True]], columns=["r", "Value"]),
    }


@pytest.fixture
def data(dfs):
    return ic.build(dfs)


def test_build(data):
    assert data["regions"] == ["R1", "R2"]
    assert list(data["dispatch"]["R1"].columns) == ic.COLS
    assert data["dispatch"]["R1"].at[3, "Unserved"] == 0.0  # EPS -> 0
    assert data["price"].at[1, "R1"] == 40.0 and data["price"].at[3, "R1"] == 0.0
    assert list(data["links"]["name"]) == ["R1-R2"]
    assert list(data["net"]["R1-R2"]) == [-60.0, -60.0, 10.0]  # positive = R1 exports
    assert data["caps"].at["R2", "Wind"] == 1500.0 and data["total_cost"] == 1234.0


def test_derived(data):
    assert list(ic.link_usage(data, 1, 3)["R1-R2"].round(1)) == [100.0, 100.0, 16.7]
    c = ic.congestion_table(data, 1, 3).iloc[0]
    assert c.hours == 2 and c.gap == pytest.approx((30 + 0 + 5) / 3)
    k = ic.kpis(data, 1, 3)
    assert k["traded"] == pytest.approx(0.13) and k["losses"] == pytest.approx(130 * 0.025)
    assert k["cong_hours"] == 2 and k["unserved"] == 0
    assert ic.avg_day(data, 1, 3).loc[0, "R2"] == 60.0


@pytest.mark.parametrize("key", page.FIG_KEYS)
def test_every_figure_builds(data, key):
    fig = page.figure(key, data, 1, 3, "R1", "R1-R2")
    assert isinstance(fig, (dict, go.Figure))


def test_map_has_frame_per_hour(data):
    fig = page.map_figure(data, 1, 3)
    assert [f["name"] for f in fig["frames"]] == ["1", "2", "3"]


def test_layout_and_routing():
    import dashboard.app as app_mod

    s = str(page.layout())
    for cid in ["ic-regions", "ic-hours", "ic-region", "ic-linksel", "ic-link", "ic-rerun", "ic-reset", "ic-run"]:
        assert cid in s
    assert app_mod.chrome_styles(config.INTERCONNECTORS_PATH)[0]["display"] == "none"
    assert "Interconnectors" in str(app_mod.sidebar.layout())


def test_key_and_capfile(tmp_path):
    root = tmp_path
    d = root / "Inputs" / "Interconnect_in"
    d.mkdir(parents=True)
    (d / "generators.csv").write_text("region,gen,cost,cap\nR1,Gas,19.8,600\nR2,Wind,0,1500\n")
    (d / "interconnectors.csv").write_text("from,to,cap,loss,cost\nR1,R2,200,0.025,0.5\n")
    assert runner.ic_key(2, {"R1.Gas": 1, "R2.Wind": 1}, 200, root) is None
    assert runner.ic_key(2, {"R2.Wind": 1.5}, 100, root) == "2|R2.Wind x1.5, links 100 MW"
    caps, link = runner.ic_changes({"R2.Wind": 0.5}, 200, root)
    assert caps == {"R2.Wind": 750.0} and link is None
    assert "gdata('R2','Wind','cap') = 750;" in runner.ic_capfile_text(caps)


def _fake_run(status, root, calls, write_gdx=True):
    def fake(cmd, cwd=None, **kw):
        calls.append((cmd, cwd))
        lst = [a for a in cmd if a.startswith("o=")][0][2:]
        outdir = [a for a in cmd if a.startswith("--outdir=")][0][9:]
        n = [a for a in cmd if a.startswith("--regions=")][0][10:]
        (root / lst).parent.mkdir(parents=True, exist_ok=True)
        (root / lst).write_text("**** MODEL STATUS      %d Optimal\n" % status)
        if write_gdx:
            (root / outdir).mkdir(parents=True, exist_ok=True)
            (root / outdir / ("Interconnectors_%s.gdx" % n)).write_text("x")

        class P:
            returncode = 0
            stderr = ""
        return P()
    return fake


def test_run_base_and_modified(tmp_path, monkeypatch):
    root = tmp_path
    d = root / "Inputs" / "Interconnect_in"
    d.mkdir(parents=True)
    (d / "generators.csv").write_text("region,gen,cost,cap\nR1,Gas,19.8,600\nR2,Wind,0,1500\n")
    (d / "interconnectors.csv").write_text("from,to,cap,loss,cost\nR1,R2,200,0.025,0.5\n")
    calls = []
    monkeypatch.setattr(runner.subprocess, "run", _fake_run(1, root, calls))
    monkeypatch.setattr(ic, "read_gdx", lambda p: {"fake": str(p)})
    runner._IC_CACHE.clear()

    msg, key = runner.run_interconnectors(2, {"R2.Wind": 1}, 200, root)
    assert key is None and "base inputs" in msg
    assert "--outdir=Results" in calls[-1][0] and calls[-1][1] == str(root)

    msg, key = runner.run_interconnectors(2, {"R2.Wind": 2}, 150, root)
    cmd = calls[-1][0]
    assert key == "2|R2.Wind x2, links 150 MW" and runner.ic_cached(key) is not None
    assert "--linkCap=150" in cmd and any(a.startswith("--capfile=.tmp_run_") for a in cmd)
    assert not list(root.glob(config.TMP_PREFIX + "*"))  # temp folder removed
    n = len(calls)
    runner.run_interconnectors(2, {"R2.Wind": 2}, 150, root)
    assert len(calls) == n  # cached


def test_run_failure(tmp_path, monkeypatch):
    root = tmp_path
    d = root / "Inputs" / "Interconnect_in"
    d.mkdir(parents=True)
    (d / "generators.csv").write_text("region,gen,cost,cap\nR1,Gas,19.8,600\n")
    (d / "interconnectors.csv").write_text("from,to,cap,loss,cost\nR1,R2,200,0.025,0.5\n")
    monkeypatch.setattr(runner.subprocess, "run", _fake_run(4, root, []))
    with pytest.raises(runner.GamsRunError):
        runner.run_interconnectors(2, {}, 200, root)


def test_real_results():
    pytest.importorskip("gdxpds")
    path = ic.results_path(4)
    if not path.exists():
        pytest.skip("no Interconnectors_4.gdx")
    data = ic.load(4)
    assert data["regions"] == ["R1", "R2", "R3", "R4"] and len(data["hours"]) == 744
    assert ic.kpis(data, 1, 744)["unserved"] < 1e-6
