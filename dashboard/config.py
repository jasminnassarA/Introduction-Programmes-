"""Central configuration for the dispatch dashboard."""
import os
from pathlib import Path

# Repository root (C:\Intro to GAMs) - all scenarios are read from here.
ROOT = Path(os.environ.get("DM_ROOT", Path(__file__).resolve().parent.parent))

# GAMS 25.1 install used by gdxpds (avoid picking up GAMS 41 from PATH).
GAMS_DIR = os.environ.get("GAMS_DIR", r"C:\GAMS\win64\25.1")

GEN_SYMBOL = "data_in"
RESULTS_SYMBOL = "ExcelResults"

# Scenario key -> file layout (paths relative to ROOT). load_factor None = always full capacity.
SCENARIOS = {
    "base": {
        "label": "Base case",
        "results": Path("Results") / "My_First_DM_results.gdx",
        "gen_gdx": Path("Inputs") / "base_case.gdx",
        "gen_csv": Path("Inputs") / "base_case.csv",
        "demand": Path("Inputs") / "demand(in).csv",
        "load_factor": None,
        "lst": Path("My_First_DM.lst"),
    },
    "renewable": {
        "label": "Renewable intermittency",
        "results": Path("Results") / "Renewable_intermit.gdx",
        "gen_gdx": Path("Inputs") / "Renewable_intermit.gdx",
        "gen_csv": Path("Inputs") / "Renewable_intermit.csv",
        "demand": Path("Inputs") / "demand(in).csv",
        "load_factor": Path("Inputs") / "normalisedloads.csv",
        "lst": Path("RenewbaleInt.lst"),
    },
    "ramping": {
        "label": "Ramping",
        "results": Path("Results") / "ramping.gdx",
        "gen_gdx": Path("Inputs") / "Renewable_intermit.gdx",
        "gen_csv": Path("Inputs") / "Renewable_intermit.csv",
        "demand": Path("Inputs") / "demand(in).csv",
        "load_factor": Path("Inputs") / "normalisedloads.csv",
        "lst": Path("DM_w_ramping.lst"),
        "ramp": True,  # add ramp_cost * |U(t) - U(t-1)| to generator costs
    },
}
BOTH = "both"  # dropdown value meaning "all scenarios"
DEFAULT_SCENARIO = "base"

# GAMS model file per scenario (run from ROOT when capacities are changed).
SCENARIOS["base"]["gms"] = Path("My_First_DM.gms")
SCENARIOS["renewable"]["gms"] = Path("RenewbaleInt.gms")
SCENARIOS["ramping"]["gms"] = Path("DM_w_ramping.gms")

GAMS_EXE = os.environ.get("GAMS_EXE", str(Path(GAMS_DIR) / "gams.exe"))
# Capacity dropdowns: options = base capacity (from the input csv) x these multipliers.
CAP_GENERATORS = ["Solar", "Wind", "Coal", "Gas"]
CAP_MULTIPLIERS = [1, 1.5, 2, 2.5, 3]
# GAMS can't take paths with spaces, so temporary run folders live inside ROOT (deleted after each run).
TMP_PREFIX = ".tmp_run_"
RESULT_CACHE_SIZE = 16  # capacity combinations kept in memory per dashboard session

WINDOW_HOURS = 120
GENERATORS = ["Solar", "Wind", "Coal", "Gas"]
GEN_COLOURS = {"Solar": "#f4b400", "Wind": "#17a2b8", "Coal": "#5f5f5f", "Gas": "#4285f4"}


def scenario_keys(value):
    """Dropdown value -> list of scenario keys."""
    if value == BOTH:
        return list(SCENARIOS)
    return [value] if value in SCENARIOS else [DEFAULT_SCENARIO]


def scenario_label(key):
    return SCENARIOS[key]["label"]
