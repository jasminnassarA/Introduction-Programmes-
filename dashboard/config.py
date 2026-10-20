"""Central configuration for the dispatch dashboard."""
import os
from pathlib import Path

# Repository root (C:\Intro to GAMs) - all scenarios are read from here.
ROOT = Path(os.environ.get("DM_ROOT", Path(__file__).resolve().parent.parent))

# GAMS 25.1 install used by gdxpds (avoid picking up GAMS 41 from PATH).
GAMS_DIR = os.environ.get("GAMS_DIR", r"C:\GAMS\win64\25.1")

GEN_SYMBOL = "data_in"
RESULTS_SYMBOL = "ExcelResults"
# Per-generator hourly cost straight from the GAMS QPlant equation (ramping/batteries models).
PLANTCOST_SYMBOL = "PlantCost"

# Scenario key -> file layout (paths relative to ROOT). load_factor None = always full capacity.
SCENARIOS = {
    "base": {
        "label": "Base case",
        "results": Path("Results") / "My_First_DM_results.gdx",
        "gen_gdx": Path("Inputs") / "base_case.gdx",
        "gen_csv": Path("Inputs") / "base_case.csv",
        "demand": Path("Inputs") / "demand(in).csv",
        "load_factor": None,
        "lst": Path("outputs") / "My_First_DM.lst",
    },
    "renewable": {
        "label": "Renewable intermittency",
        "short_label": "Renewable int.",  # used when all scenarios are compared (avoids label overlap)
        "results": Path("Results") / "Renewable_intermit.gdx",
        "gen_gdx": Path("Inputs") / "Renewable_intermit.gdx",
        "gen_csv": Path("Inputs") / "Renewable_intermit.csv",
        "demand": Path("Inputs") / "demand(in).csv",
        "load_factor": Path("Inputs") / "normalisedloads.csv",
        "lst": Path("outputs") / "RenewbaleInt.lst",
    },
    "ramping": {
        "label": "Ramping",
        "results": Path("Results") / "ramping.gdx",
        "gen_gdx": Path("Inputs") / "Renewable_intermit.gdx",
        "gen_csv": Path("Inputs") / "Renewable_intermit.csv",
        "demand": Path("Inputs") / "demand(in).csv",
        "load_factor": Path("Inputs") / "normalisedloads.csv",
        "lst": Path("outputs") / "DM_w_ramping.lst",
        "ramp": True,  # add ramp_cost * |U(t) - U(t-1)| to generator costs
    },
}
SCENARIOS["batteries"] = {
    "label": "Batteries",
    "results": Path("Results") / "Batteries.gdx",
    "gen_gdx": Path("Inputs") / "Renewable_intermit.gdx",
    "gen_csv": Path("Inputs") / "Renewable_intermit.csv",
    "demand": Path("Inputs") / "demand(in).csv",
    "load_factor": Path("Inputs") / "normalisedloads.csv",
    "lst": Path("outputs") / "Adding_Batteries.lst",
    "ramp": True,
    "battery": Path("Inputs") / "Battery_in.csv",
}
BOTH = "both"  # dropdown value meaning "all scenarios"
DEFAULT_SCENARIO = "base"

# GAMS model file per scenario (run from ROOT when capacities are changed).
SCENARIOS["base"]["gms"] = Path("models") / "My_First_DM.gms"
SCENARIOS["renewable"]["gms"] = Path("models") / "RenewbaleInt.gms"
SCENARIOS["ramping"]["gms"] = Path("models") / "DM_w_ramping.gms"
SCENARIOS["batteries"]["gms"] = Path("models") / "Adding_Batteries.gms"

# Battery settings (only passed to scenarios with a "battery" csv).
# caps key -> (Battery_in.csv column, GAMS --flag, decimals)
BAT_PARAMS = {
    "BatCap": ("cap", "batCap", 0),
    "BatPower": ("power", "batPower", 0),
    "BatChEff": ("charg_eff", "batChEff", 2),
    "BatDisEff": ("discharge_eff", "batDisEff", 2),
}
BAT_CAP_OPTIONS = [500, 1000, 2000, 5000, 10000, 20000, 30000, 40000]  # MWh
BAT_POWER_OPTIONS = [50, 100, 250, 500, 1000, 1500, 2000, 2500, 3000, 3500, 4000]  # MW
BAT_EFF_MIN, BAT_EFF_MAX, BAT_EFF_STEP = 0.5, 1.0, 0.05
BAT_COLOURS = {"discharge": "#2ca02c", "charge": "#9467bd", "soc": "#8c564b"}

GAMS_EXE = os.environ.get("GAMS_EXE", str(Path(GAMS_DIR) / "gams.exe"))
# Capacity dropdowns: options = base capacity (from the input csv) x these multipliers.
CAP_GENERATORS = ["Solar", "Wind", "Coal", "Gas"]
CAP_MULTIPLIERS = [1, 1.5, 2, 2.5, 3]
# GAMS can't take paths with spaces, so temporary run folders live inside ROOT (deleted after each run).
TMP_PREFIX = ".tmp_run_"
RESULT_CACHE_SIZE = 16  # capacity combinations kept in memory per dashboard session

WINDOW_HOURS = 120
GENERATORS = ["Solar", "Wind", "Coal", "Gas"]
# Generators checklist in the sidebar: the generators plus a Battery toggle.
BATTERY_ITEM = "Battery"
CHECKLIST_ITEMS = GENERATORS + [BATTERY_ITEM]
GEN_COLOURS = {"Solar": "#f4b400", "Wind": "#17a2b8", "Coal": "#5f5f5f", "Gas": "#4285f4"}
GEN_COLOURS_WITH_BATTERY = dict(GEN_COLOURS, Battery=BAT_COLOURS["discharge"])


def scenario_keys(value):
    """Dropdown value -> list of scenario keys."""
    if value == BOTH:
        return list(SCENARIOS)
    return [value] if value in SCENARIOS else [DEFAULT_SCENARIO]


def scenario_label(key):
    return SCENARIOS[key]["label"]


def compare_labels():
    """{full label: short label} applied on the summary page when all scenarios are compared."""
    return {s["label"]: s["short_label"] for s in SCENARIOS.values() if "short_label" in s}
