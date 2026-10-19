import numpy as np
import pandas as pd
import pytest

from dashboard import config
from dashboard.data import access, loader, metrics


@pytest.fixture
def params():
    return pd.DataFrame({"cost": [0, 7.8, 19.8], "cap": [500, 100, 600],
                         "eff": [1, 0.4, 0.5], "vom": [1, 2, 2]},
                        index=pd.Index(["Solar", "Coal", "Gas"], name="gen"))


@pytest.fixture
def hourly(params):
    # 48 hours; Gas omitted (GDX drops zeros) for hour 1; no Wind at all.
    rows = []
    for t in range(1, 49):
        rows += [(t, "DemandMarginal", float(t)), (t, "Solar", 100.0), (t, "Coal", 50.0)]
        if t > 1:
            rows.append((t, "Gas", 10.0))
    long = pd.DataFrame(rows, columns=["T", "outfield", "Value"])
    demand = pd.Series([150.0] + [160.0] * 47, index=range(1, 49))
    return loader.build_hourly(long, demand, params, run="r1")


def test_build_hourly_shape_zero_fill_no_dates(hourly):
    assert len(hourly) == 48
    assert hourly.loc[0, "Gas"] == 0.0
    assert "datetime" not in hourly.columns
    assert list(hourly["T"]) == list(range(1, 49))
    assert (hourly["Wind"] == 0).all() and (hourly["avail_Wind"] == 0).all()
    assert (hourly["avail_Solar"] == 500).all()


def test_costs(hourly):
    r = hourly.loc[1]
    assert r["cost_Solar"] == pytest.approx(100 * 1)
    assert r["cost_Coal"] == pytest.approx(50 * (2 + 7.8 / 0.4))
    assert r["cost_Gas"] == pytest.approx(10 * (2 + 19.8 / 0.5))
    assert r["total_cost"] == pytest.approx(r["cost_Solar"] + r["cost_Coal"] + r["cost_Gas"])


def test_load_factor_avail(params):
    p = params.copy()
    p.loc["Wind"] = [0, 500, 1, 0.5]
    long = pd.DataFrame([(1, "Wind", 200.0), (2, "Wind", 100.0)], columns=["T", "outfield", "Value"])
    demand = pd.Series([200.0, 100.0], index=[1, 2])
    lf = pd.DataFrame({"Wind": [0.5, 0.2], "Solar": [0.0, 1.0]}, index=[1, 2])
    df = loader.build_hourly(long, demand, p, load_factor=lf)
    assert list(df["avail_Wind"]) == [250.0, 100.0]
    assert list(df["avail_Solar"]) == [0.0, 500.0]
    assert list(df["avail_Coal"]) == [100.0, 100.0]  # not in lf -> full cap
    assert df["cost_Wind"].tolist() == [100.0, 50.0]
    cf = metrics.capacity_factor(df).set_index("gen")["cf"]
    assert cf["Wind"] == pytest.approx(300 / 350 * 100)
    uc = metrics.unserved_curtailed(df).iloc[0]
    assert uc["curtailed_wind"] == pytest.approx(50)


def test_read_gen_params_strips(tmp_path):
    f = tmp_path / "b.csv"
    f.write_text("gen,cost,cap,eff ,vom\nSolar,0,500,1,1\nGas,19.8 ,600,0.5,2\n")
    p = loader.read_gen_params(f)
    assert p.loc["Gas", "cost"] == 19.8 and "eff" in p.columns
    full = loader.complete_params(p)
    assert set(config.GENERATORS) <= set(full.index) and full.loc["Wind", "cap"] == 0


def test_read_load_factor(tmp_path):
    f = tmp_path / "lf.csv"
    f.write_text("Hour,Wind,Solar,Gas,Coal\n1,0.7,0,1,1\n2,0.6,0.5,1,1\n")
    lf = loader.read_load_factor(f)
    assert list(lf.index) == [1, 2] and lf.loc[2, "Solar"] == 0.5


def test_price_stats_whole_window(hourly):
    ps = metrics.price_stats(hourly).iloc[0]
    assert "period" not in metrics.price_stats(hourly).columns
    assert (ps["min"], ps["max"], ps["spread"]) == (1, 48, 47)
    for q in (10, 50, 90):
        assert ps["p%d" % q] == pytest.approx(np.percentile(np.arange(1, 49), q))
    t = metrics.summary_table(hourly)
    assert len(t) == 1 and t.loc[0, "hours"] == 48
    for c in ("spread", "p10_price", "p50_price", "p90_price", "Wind_mwh"):
        assert c in t.columns


def test_summary_page(hourly, params):
    from dashboard.pages import summary
    lay = str(summary.layout())
    for k in ("s-fig-price", "s-fig-share", "s-fig-setter", "s-kpis"):
        assert k in lay
    prices, demand = np.arange(1, 49), np.array([150.0] + [160.0] * 47)
    s = summary.window_stats(hourly)["r1"]
    assert s["avg"] == pytest.approx(24.5)
    assert s["dw_avg"] == pytest.approx((prices * demand).sum() / demand.sum())
    pr = {t.name: t for t in summary._figure("price", hourly, {}, ["Solar"]).data}
    assert list(pr["Hourly price"].x) == list(range(1, 49))
    pie = summary._figure("share", hourly, {}, ["Solar", "Coal"]).data[0]
    assert list(pie.labels) == ["Solar", "Coal"] and list(pie.values) == [4800.0, 2400.0]
    full = loader.complete_params(params)
    sp = summary._figure("setter", hourly, {"r1": full}, ["Solar"]).data[0]
    assert dict(zip(sp.labels, sp.values)) == {"Solar": 1, summary.D.OTHER: 47}
    cf = summary._figure("cf", hourly, {}, ["Solar"]).data[0]
    assert list(cf.x) == ["r1"] and cf.y[0] == pytest.approx(20)


def test_mix_share(hourly):
    mix = metrics.generation_mix(hourly)
    assert mix["share"].sum() == pytest.approx(100)


def test_clamp_hours_and_start():
    assert access.clamp_hours(0) == access.MIN_HOURS
    assert access.clamp_hours(9999) == access.MAX_HOURS
    assert access.clamp_hours("48") == 48
    assert access.clamp_hours(None) == config.WINDOW_HOURS
    assert access.clamp_start(700, 120, 744) == 625
    assert access.clamp_start(-5, 120, 744) == 1


def test_filter_window_hours(hourly):
    w, s, last = access.filter_window(hourly, 1, 744)
    assert len(w) == 48 and last == 48
    assert access.range_label(s, last) == "Hour 1 to Hour 48"
    w1, _, last1 = access.filter_window(hourly, 25, 24)
    assert len(w1) == 24 and last1 == 48
    _, _, none = access.filter_window(hourly, 500, 24)
    assert none is None


def test_scenario_keys():
    assert config.scenario_keys("base") == ["base"]
    assert config.scenario_keys(config.BOTH) == ["base", "renewable", "ramping"]
    assert config.scenario_keys(None) == [config.DEFAULT_SCENARIO]


def test_load_selected_both(monkeypatch, hourly, params):
    monkeypatch.setattr(loader, "load_scenario",
                        lambda k, caps=None: hourly.assign(run=config.scenario_label(k)))
    monkeypatch.setattr(loader, "load_gen_params", lambda k, caps=None: loader.complete_params(params))
    df, p = access.load_selected(config.BOTH)
    assert list(df["run"].unique()) == ["Base case", "Renewable intermittency", "Ramping"]
    assert set(p) == {"Base case", "Renewable intermittency", "Ramping"}


def test_selected_gens():
    assert access.selected_gens(None) == config.GENERATORS
    assert access.selected_gens(["Gas", "Solar"]) == ["Solar", "Gas"]
    assert access.selected_gens([]) == []


def test_dispatch_figure(hourly):
    from dashboard.pages import granular
    fig = granular.dispatch_figure(hourly, ["Solar", "Gas"])
    names = [t.name for t in fig.data]
    assert names == ["Solar", "Gas", "Demand", "Price ($/MWh)"]
    assert fig.data[-1].yaxis == "y2"
    assert list(fig.data[0].x) == list(range(1, 49))


def test_sidebar_has_scenario_only():
    from dashboard.components import sidebar
    lay = str(sidebar.layout())
    assert "scenario" in lay and "hour-start" in lay
    for gone in ("run-select", "snap-btn", "date-start", "freq"):
        assert gone not in lay
    assert [o["value"] for o in sidebar.scenario_options()] == ["base", "renewable", "ramping", "both"]
