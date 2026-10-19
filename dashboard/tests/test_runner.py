from pathlib import Path

import pandas as pd
import pytest

from dashboard import config
from dashboard.data import access, loader, lst_parser, runner

BASE = {"Solar": 500, "Wind": 500, "Coal": 100, "Gas": 600}


@pytest.fixture
def root(tmp_path):
    """Minimal project tree: models + input csvs (base case has no Wind)."""
    (tmp_path / "Inputs").mkdir()
    (tmp_path / "Results").mkdir()
    for sc in config.SCENARIOS.values():
        (tmp_path / sc["gms"]).write_text("* model")
        (tmp_path / sc["results"]).write_text("orig")
    (tmp_path / "Inputs" / "base_case.csv").write_text(
        "gen,cost,cap,eff ,vom\nSolar,0,500,1,1\nCoal,7.8,100,0.4,2\nGas,19.8 ,600,0.5,2\n")
    (tmp_path / "Inputs" / "Renewable_intermit.csv").write_text(
        "gen,cost,cap,eff,vom\nSolar,0,500,1,1\nCoal,7.8,100,0.4,2\nGas,19.8 ,600,0.5,2\nWind,0,500,1,0.5\n")
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
    assert base[1] == "My_First_DM.gms" and "--coalCap=200" in base
    assert not any(c.startswith("--windCap") for c in base)
    assert "--windCap=1000" in ramp and "--coalCap=200" in ramp
    assert not any(c.startswith(("--solarCap", "--gasCap")) for c in ramp)
    assert "--noxlsx=1" in ramp and "--outdir=%s" % Path(config.TMP_PREFIX + "x") in ramp


def test_runs_in_temp_dir_keeps_nothing_and_reuses_in_memory(root, fake_gams):
    caps = dict(BASE, Solar=750, Gas=1200)
    entry = runner.get_results(caps, root)
    assert set(entry) == set(config.SCENARIOS) and len(fake_gams) == 3
    assert runner.last_status.startswith("Solved 3 model(s)")
    assert _leftovers(root) == []
    assert not list(root.rglob("*.lst"))
    assert runner.get_results(caps, root) is entry and len(fake_gams) == 3
    assert runner.last_status == "Using results from this session"
    runner.clear_cache()  # e.g. dashboard restart -> runs again
    runner.get_results(caps, root)
    assert len(fake_gams) == 6


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
