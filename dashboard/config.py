"""Central configuration for the dispatch dashboard."""
import os
from pathlib import Path

import pandas as pd

# Repository root (C:\Intro to GAMs) - "current" run is read from here.
ROOT = Path(os.environ.get("DM_ROOT", Path(__file__).resolve().parent.parent))
RUNS_DIR = ROOT / "runs"

# GAMS 25.1 install used by gdxpds (avoid picking up GAMS 41 from PATH).
GAMS_DIR = os.environ.get("GAMS_DIR", r"C:\GAMS\win64\25.1")

# File layout (relative to a run directory).
RESULTS_GDX = Path("Results") / "My_First_DM_results.gdx"
DEMAND_CSV = Path("Inputs") / "demand(in).csv"
GEN_CSV = Path("Inputs") / "base_case.csv"
GEN_GDX = Path("Inputs") / "base_case.gdx"
GEN_SYMBOL = "data_in"
LST_FILE = Path("My_First_DM.lst")
RESULTS_SYMBOL = "ExcelResults"

# Hour T=1 maps to this timestamp; any number of hours (e.g. 8760) is supported.
START_DATETIME = pd.Timestamp(os.environ.get("DM_START", "2024-01-01 00:00"))

WINDOW_DAYS = 5
CURRENT = "current"
GENERATORS = ["Solar", "Coal", "Gas"]
GEN_COLOURS = {"Solar": "#f4b400", "Coal": "#5f5f5f", "Gas": "#4285f4"}
