from pathlib import Path

import pandas as pd
import pytest

from dashboard import config
from dashboard.data import access, loader, lst_parser, runner

BASE = {"Solar": 500, "Wind": 500, "Coal": 100, "Gas": 600, "BatCap": 500, "BatPower": 50, "BatChEff": 0.95, "BatDisEff": 0.95}


@pytest.fixture
def root(tmp_path):
    """Minimal project tree: models + input csvs (base case has no Wind)."""
    (tmp_path / "Inputs").mkdir()
    (tmp_path / "Results").mkdir()
    for sc in config.SCENARIOS.values():
        (tmp_path / sc["gms"]).parent.mkdir(exist_ok=True)
        (tmp_path / sc["gms"]).write_text("* model")
        (tmp_path / sc["results"]).write_text("orig")
    (tmp_path / "Inputs" / "base_case.csv").write_text(
        "gen,cost,cap,eff ,vom\nSolar,0,500,1,1\nCoal,7.8,100,0.4,2\nGas,19.8 ,600,0.5,2\n")
    (tmp_path / "Inputs" / "Renewable_intermit.csv").write_text(
        "gen,cost,cap,eff,vom\nSolar,0,500,1,1\nCoal,7.8,100,0.4,2\nGas,19.8 ,600,0.5,2\nWind,0,500,1,0.5\n")
    (tmp_path / "Inputs" / "Battery_in.csv").write_text(
        "battery,cap,power,charg_eff,discharge_eff,inita_charge\nbat_1,500,50,0.95,0.95,0\n")
    (tmp_path / "Inputs" / "demand(in).csv").write_text("T,d\n1,100\n")
    (tmp_path / "Inputs" / "normalisedloads.csv").write_text("Hour,Solar\n1,1\n")
    runner.clear_cache()
    yield tmp_path
    runner.clear_cache()


def _arg(cmd, prefix):
    return [c for c in cmd if c.startswith(prefix)][0][len(prefix):]


@pytest.fixture
def fake_gams(monkeypatch):
    """Replace subprocess.run (writes results gdx + optimal .lst) and the gdx reader."""
    calls = []

    def run(cmd, cwd, **kw):
        calls.append(cmd)
        out = Path(cwd) / _arg(cmd, "--outdir=")
        key = next(k for k, s in config.SCENARIOS.items() if str(s["gms"]) == cmd[1])
        (out / Path(config.SCENARIOS[key]["results"]).name).write_text("gdx")
        (Path(cwd) / _arg(cmd, "o=")).write_text("**** MODEL STATUS      1 Optimal\n")
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setattr(loader, "read_results_gdx",
                        lambda p: pd.DataFrame({"T": [1], "outfield": ["Solar"], "Value": [100.0]}))
    return calls


def _leftovers(root):
    return list(root.glob(config.TMP_PREFIX + "*")) + list(root.glob("runs"))


def test_default_caps_and_options(root):
    assert runner.default_caps(root) == BASE  # Wind from Renewable_intermit.csv
    assert runner.cap_options("Coal", root) == [100, 150, 200, 250, 300]
    assert runner.cap_options("Gas", root) == [600, 900, 1200, 1500, 1800]
    assert runner.is_default(None, root) and runner.is_default(dict(BASE), root)
    assert not runner.is_default({"Gas": 900}, root)


def test_base_never_runs(root, fake_gams):
    assert runner.get_results(dict(BASE), root) is None
    assert fake_gams == []


def test_command_passes_only_changed_caps_and_base_ignores_wind(root):
    caps = dict(BASE, Wind=1000, Coal=200)
    tmp = root / (config.TMP_PREFIX + "x")
    base = runner.gams_command("base", caps, tmp, root)
    ramp = runner.gams_command("ramping", caps, tmp, root)
    assert base[1] == str(Path("models") / "My_First_DM.gms") and "--coalCap=200" in base
    assert not any(c.startswith("--windCap") for c in base)
    assert "--windCap=1000" in ramp and "--coalCap=200" in ramp
    assert not any(c.startswith(("--solarCap", "--gasCap")) for c in ramp)
    assert "--noxlsx=1" in ramp and "--outdir=%s" % Path(config.TMP_PREFIX + "x") in ramp


def test_runs_in_temp_dir_keeps_nothing_and_reuses_in_memory(root, fake_gams):
    caps = dict(BASE, Solar=750, Gas=1200)
    entry = runner.get_results(caps, root)
    assert set(entry) == set(config.SCENARIOS) and len(fake_gams) == 4
    assert runner.last_status.startswith("Solved 4 model(s)")
    assert _leftovers(root) == []
    assert not list(root.rglob("*.lst"))
    assert runner.get_results(caps, root) is entry and len(fake_gams) == 4
    assert runner.last_status == "Using results from this session"
    runner.clear_cache()  # e.g. dashboard restart -> runs again
    runner.get_results(caps, root)
    assert len(fake_gams) == 8


def test_failed_run_removes_temp_and_is_not_cached(root, monkeypatch):
    def run(cmd, cwd, **kw):
        (Path(cwd) / _arg(cmd, "o=")).write_text("**** MODEL STATUS      4 Infeasible\n")
        (Path(cwd) / _arg(cmd, "--outdir=") / "My_First_DM_results.gdx").write_text("bad")
        return type("P", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(runner.subprocess, "run", run)
    caps = dict(BASE, Coal=300)
    with pytest.raises(runner.GamsRunError, match="Infeasible"):
        runner.get_results(caps, root)
    assert _leftovers(root) == []
    assert runner.cached_results(caps, root) is None


def test_cleanup_tmp(root):
    (root / (config.TMP_PREFIX + "old")).mkdir()
    runner.cleanup_tmp(root)
    assert _leftovers(root) == []


def test_load_scenario_and_lst_from_memory(root, fake_gams):
    caps = dict(BASE, Solar=1000, Wind=1500)
    df = loader.load_scenario("renewable", root, caps)
    assert df["avail_Solar"].iloc[0] == 1000
    base = loader.load_gen_params("base", root, caps)
    assert base.loc["Wind", "cap"] == 0  # base case ignores Wind
    assert loader.load_gen_params("ramping", root, caps).loc["Wind", "cap"] == 1500
    s, _ = lst_parser.load_lst("base", root, caps)
    assert s["model_status_code"] == 1


def test_with_caps():
    p = loader.complete_params(pd.DataFrame({"cost": [0.0], "cap": [500.0], "eff": [1.0], "vom": [1.0]},
                                            index=pd.Index(["Solar"], name="gen")))
    assert loader.with_caps(p, {"Solar": 1500}).loc["Solar", "cap"] == 1500
    assert loader.with_caps(p, None).loc["Solar", "cap"] == 500
    assert loader.with_caps(p, {"Wind": 900}, gens=["Solar"]).loc["Wind", "cap"] == 0


def test_load_selected_reports_gams_error(monkeypatch):
    def boom(caps):
        raise runner.GamsRunError("nope")

    monkeypatch.setattr(runner, "get_results", boom)
    df, p = access.load_selected("base", {"Solar": 750})
    assert df.empty and p == {}
    assert runner.last_status == "Error: nope"


def test_battery_flags_only_for_battery_scenario(root):
    caps = dict(BASE, BatCap=10000, BatPower=1000, BatChEff=0.9, BatDisEff=0.85, Coal=200)
    tmp = root / (config.TMP_PREFIX + "x")
    bat = runner.gams_command("batteries", caps, tmp, root)
    assert bat[1] == str(Path("models") / "Adding_Batteries.gms")
    for f in ("--batCap=10000", "--batPower=1000", "--batChEff=0.90", "--batDisEff=0.85", "--coalCap=200"):
        assert f in bat
    for key in ("base", "renewable", "ramping"):
        assert not any(c.startswith("--bat") for c in runner.gams_command(key, caps, tmp, root))


def test_battery_base_never_runs_and_eff_rounding(root, fake_gams):
    assert runner.get_results(dict(BASE, BatChEff=0.9500001), root) is None
    assert fake_gams == []
    assert runner.normalize({"BatChEff": 0.7000000001}, root)["BatChEff"] == 0.7
    only_bat = runner.changed_caps("ramping", dict(BASE, BatPower=500), root)
    assert only_bat == {}


def test_build_hourly_battery_columns():
    p = pd.DataFrame({"cost": [0.0], "cap": [500.0], "eff": [1.0], "vom": [1.0]}, index=pd.Index(["Solar"], name="gen"))
    dem = pd.Series([100.0, 100.0], index=[1, 2])
    plain = loader.build_hourly(pd.DataFrame({"T": [1, 2], "outfield": ["Solar"] * 2, "Value": [100.0, 100.0]}), dem, p)
    assert (plain["bat_soc"] == 0).all() and (plain["net_battery"] == 0).all()
    r = pd.DataFrame({"T": [1, 1, 2, 2], "outfield": ["Solar", "Bat_Charge", "Bat_Discharge", "Bat_SOC"],
                      "Value": [120.0, 20.0, 18.0, 1.0]})
    df = loader.build_hourly(r, dem, p)
    assert df.loc[0, "bat_charge"] == 20 and df.loc[1, "bat_discharge"] == 18 and df.loc[1, "net_battery"] == 18


def test_load_bat_params_and_summary(root):
    from dashboard.data import metrics
    b = loader.load_bat_params("batteries", root, {"BatCap": 2000, "BatChEff": 0.8})
    assert b["cap"] == 2000 and b["charg_eff"] == 0.8 and b["power"] == 50
    assert loader.load_bat_params("base", root) is None
    df = pd.DataFrame({"bat_charge": [100.0, 0.0], "bat_discharge": [0.0, 81.0], "bat_soc": [80.0, 0.0]})
    s = metrics.battery_summary(df, b)
    assert s["losses"] == 19 and s["cycles"] == 81 / 2000 and s["peak_soc"] == 80


def _bat_df(run="Batteries"):
    return pd.DataFrame({"run": run, "T": [1, 2], "price": [10.0, 20.0], "demand": [100.0, 120.0],
                         "Solar": [80.0, 0.0], "Wind": [0.0, 0.0], "Coal": [20.0, 20.0], "Gas": [20.0, 50.0],
                         "cost_Solar": 0.0, "cost_Wind": 0.0, "cost_Coal": 100.0, "cost_Gas": 800.0,
                         "avail_Solar": [500.0, 0.0], "avail_Wind": 0.0, "avail_Coal": 100.0, "avail_Gas": 600.0,
                         "bat_charge": [20.0, 0.0], "bat_discharge": [0.0, 50.0], "bat_soc": [19.0, 0.0]})


def test_battery_in_share_and_cost():
    from dashboard.data import metrics
    from dashboard.pages import summary
    df = pd.concat([_bat_df(), _bat_df("Ramping")])
    lv = summary.share_values(df, ["Solar", "Gas"])
    assert lv["Batteries"] == (["Solar", "Gas", "Battery"], [80.0, 70.0, 50.0])
    assert "Battery" not in lv["Ramping"][0]
    c = metrics.cost_breakdown(df)
    bat = c[c["gen"] == "Battery"]
    assert list(bat["run"]) == ["Batteries"] and (bat["cost"] == 0).all()


def test_capacity_checks_with_battery():
    from dashboard.data import diagnostics as D
    p = pd.DataFrame({"cost": [0.0, 7.8, 19.8], "cap": [500.0, 100.0, 600.0], "eff": [1, 0.4, 0.5],
                      "vom": [1, 2, 2]}, index=pd.Index(["Solar", "Coal", "Gas"], name="gen"))
    w = _bat_df()
    s0, per0 = D.capacity_checks(w, p)
    s, per = D.capacity_checks(w, p, bat={"cap": 40000.0, "power": 50.0})
    assert s["total_capacity"] == s0["total_capacity"] + 50 and len(per) == len(per0) + 1
    b = per[per["gen"] == "Battery"].iloc[0]
    assert b["cap"] == 50 and b["energy_cap_mwh"] == 40000 and b["hours_at_cap"] == 1 and b["hours_empty"] == 1


def test_battery_inputs_table():
    from dashboard.pages import diagnostics as pg
    base = {"cap": 500.0, "power": 50.0, "charg_eff": 0.95, "discharge_eff": 0.95, "inita_charge": 0.0}
    t = pg.battery_inputs_table(dict(base, cap=40000.0, charg_eff=0.8))
    assert list(t.columns) == ["parameter", "applied"]
    assert t.loc[0, "applied"] == 40000 and t.iloc[-1]["applied"] == round(0.8 * 0.95, 4)


def test_battery_toggle_hides_battery():
    from dashboard.pages import granular, summary
    df = _bat_df()
    assert "Battery" not in summary.share_values(df, ["Solar", "Gas"], battery=False)["Batteries"][0]
    names = [t.name for t in granular.dispatch_figure(df, ["Solar"]).data]
    assert any(n.startswith("Battery") for n in names)
    names = [t.name for t in granular.dispatch_figure(df, ["Solar"], battery=False).data]
    assert not any(n.startswith("Battery") for n in names)
