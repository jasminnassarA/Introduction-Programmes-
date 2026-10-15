import pandas as pd
import pytest

from dashboard import config
from dashboard.data import loader, metrics, versions


@pytest.fixture
def params():
    return pd.DataFrame({"cost": [0, 7.8, 19.8], "cap": [500, 100, 600],
                         "eff": [1, 0.4, 0.5], "vom": [1, 2, 2]},
                        index=pd.Index(["Solar", "Coal", "Gas"], name="gen"))


@pytest.fixture
def hourly(params):
    # 48 hours spanning two months; Gas omitted (GDX drops zeros) for hour 1.
    rows = []
    for t in range(1, 49):
        rows += [(t, "DemandMarginal", float(t)), (t, "Solar", 100.0), (t, "Coal", 50.0)]
        if t > 1:
            rows.append((t, "Gas", 10.0))
    long = pd.DataFrame(rows, columns=["T", "outfield", "Value"])
    demand = pd.Series([150.0] + [160.0] * 47, index=range(1, 49))
    return loader.build_hourly(long, demand, params, start="2024-01-31 00:00", run="r1")


def test_build_hourly_shape_and_zero_fill(hourly):
    assert len(hourly) == 48
    assert hourly.loc[0, "Gas"] == 0.0
    assert hourly.loc[0, "datetime"] == pd.Timestamp("2024-01-31 00:00")
    assert hourly.loc[47, "datetime"] == pd.Timestamp("2024-02-01 23:00")


def test_costs(hourly):
    r = hourly.loc[1]
    assert r["cost_Solar"] == pytest.approx(100 * 1)
    assert r["cost_Coal"] == pytest.approx(50 * (2 + 7.8 / 0.4))
    assert r["cost_Gas"] == pytest.approx(10 * (2 + 19.8 / 0.5))
    assert r["total_cost"] == pytest.approx(r["cost_Solar"] + r["cost_Coal"] + r["cost_Gas"])


def test_read_gen_params_strips(tmp_path):
    f = tmp_path / "b.csv"
    f.write_text("gen,cost,cap,eff ,vom\nSolar,0,500,1,1\nGas,19.8 ,600,0.5,2\n")
    p = loader.read_gen_params(f)
    assert p.loc["Gas", "cost"] == 19.8 and "eff" in p.columns


def test_monthly_grouping(hourly, params):
    ps = metrics.price_stats(hourly, "M")
    assert list(ps["period"]) == ["2024-01", "2024-02"]
    assert ps.loc[0, "max"] == 24 and ps.loc[1, "min"] == 25
    assert len(metrics.price_stats(hourly, "Y")) == 1


def test_spread_and_percentiles(hourly, params):
    import numpy as np
    ps = metrics.price_stats(hourly, "M")
    assert (ps["spread"] == ps["max"] - ps["min"]).all()
    for i, prices in enumerate([np.arange(1, 25), np.arange(25, 49)]):
        for q in (10, 50, 90):
            assert ps.loc[i, "p%d" % q] == pytest.approx(np.percentile(prices, q))
    t = metrics.summary_table(hourly, {"r1": params}, "M")
    for c in ("spread", "p10_price", "p50_price", "p90_price"):
        assert c in t.columns


def test_summary_price_box(hourly):
    from dashboard.pages import summary
    assert "s-fig-pricebox" in str(summary.layout())
    fig = summary._figure("pricebox", hourly, {}, "M", ["Solar"])
    b = fig.data[0]
    assert list(b.lowerfence) == pytest.approx([3.3, 27.3]) and list(b.upperfence) == pytest.approx([21.7, 45.7])


def test_mix_share_and_cf(hourly, params):
    mix = metrics.generation_mix(hourly, "Y")
    assert mix["share"].sum() == pytest.approx(100)
    cf = metrics.capacity_factor(hourly, {"r1": params}, "Y").set_index("gen")["cf"]
    assert cf["Solar"] == pytest.approx(100 / 500 * 100)


def test_unserved_curtailed(hourly, params):
    uc = metrics.unserved_curtailed(hourly, {"r1": params}, "Y").iloc[0]
    assert uc["unserved"] == 0
    assert uc["curtailed_solar"] == pytest.approx(48 * 400)


def test_snapshot(tmp_path):
    root, runs = tmp_path / "root", tmp_path / "runs"
    (root / "Results").mkdir(parents=True)
    (root / "Inputs").mkdir()
    (root / config.RESULTS_GDX).write_bytes(b"x")
    (root / "Inputs" / "a.csv").write_text("1")
    (root / "My_First_DM.lst").write_text("**** OBJECTIVE VALUE         123.5000\n")
    dest = versions.snapshot("v1", "note", root=root, runs_dir=runs)
    assert (dest / config.RESULTS_GDX).exists()
    assert versions.read_meta(dest)["objective"] == 123.5
    assert [l for l, _ in versions.list_runs(root, runs)] == ["current", "v1"]
    with pytest.raises(FileExistsError):
        versions.snapshot("v1", root=root, runs_dir=runs)
    with pytest.raises(ValueError):
        versions.snapshot("bad label!", root=root, runs_dir=runs)


def test_clamp_days():
    from dashboard.data import access
    assert access.clamp_days(0) == 1
    assert access.clamp_days(99) == 35
    assert access.clamp_days("7") == 7
    assert access.clamp_days(None) == config.WINDOW_DAYS
    assert access.clamp_days("x") == config.WINDOW_DAYS


def test_filter_window_end_clamped_to_data(hourly):
    from dashboard.data import access
    w, s, last = access.filter_window(hourly, "2024-01-31", 35)
    assert len(w) == 48
    assert last == pd.Timestamp("2024-02-01 23:00")
    assert access.range_label(s, last) == "2024-01-31 00:00 to 2024-02-01 23:00"
    w1, _, last1 = access.filter_window(hourly, "2024-02-01", 1)
    assert len(w1) == 24 and last1 == pd.Timestamp("2024-02-01 23:00")
    _, _, none = access.filter_window(hourly, "2025-01-01", 1)
    assert none is None


def test_selected_gens():
    from dashboard.data import access
    assert access.selected_gens(None) == config.GENERATORS
    assert access.selected_gens(["Gas", "Solar"]) == ["Solar", "Gas"]
    assert access.selected_gens([]) == []


def test_dispatch_figure_and_no_price_graph(hourly):
    from dashboard.pages import granular
    fig = granular.dispatch_figure(hourly, ["Solar", "Gas"])
    names = [t.name for t in fig.data]
    assert names == ["Solar", "Gas", "Demand", "Price ($/MWh)"]
    assert fig.data[-1].yaxis == "y2"
    assert "g-price" not in str(granular.layout())
