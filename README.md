# Power System Dispatch Models (GAMS) + Interactive Dashboard

This repository has two parts:

- **Three GAMS dispatch models.** Each one finds the lowest-cost way to meet electricity demand in every hour of one month (744 hours) using Solar, Wind, Coal and Gas generators.
- **A Python Dash dashboard.** It lets you explore the model results, compare scenarios, change generator capacities and re-run the models from your browser.

> **Branch:** this README describes the **`AI-Dashboard`** branch. The dashboard only exists on this branch.

---

## Quick start

Before you start, you need **Windows** and **GAMS 25.1 with a MOSEK license** (in `C:\GAMS\win64\25.1`, or set `GAMS_DIR`).

```powershell
git clone https://github.com/jasminnassarA/Introduction-Programmes-.git
cd Introduction-Programmes-
git checkout AI-Dashboard
```

Then **double-click `setup_and_run.bat`**. It:

1. Finds Python 3.6–3.9 (Python 3.6 preferred, since GAMS 25.1's Python API only supports 3.6). If none is installed it installs Python 3.9.13 for the current user (winget, or the python.org installer).
2. Creates `.venv` and installs `requirements.txt` (only again when that file changes).
3. Installs the GAMS Python API into `.venv` and opens **http://127.0.0.1:8050** in your browser.

Close the window to stop the dashboard. To re-solve all models, double-click `run_models.bat`.

Pre-computed results are included in `Results/`, so the dashboard shows data straight away. You only need GAMS to run the models yourself or to use the **Run models** button.

---

## Table of contents

1. [What the models do](#1-what-the-models-do)
2. [Repository structure](#2-repository-structure)
3. [Prerequisites](#3-prerequisites)
4. [Installation (step by step)](#4-installation-step-by-step)
5. [Running the GAMS models](#5-running-the-gams-models)
6. [Input data reference](#6-input-data-reference)
7. [Running the dashboard](#7-running-the-dashboard)
8. [Using the dashboard](#8-using-the-dashboard)
9. [Running the tests](#9-running-the-tests)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. What the models do

All three models are **linear programs (LPs)** solved with **MOSEK**. Each runs over hours `T = 1..744`.

- **Objective:** minimise the total generation cost. For each generator and hour this is `generation × (fuel cost / efficiency + variable O&M cost)`.
- **Constraints:**
  - Total generation must equal demand in every hour.
  - Each generator's output must stay at or below its capacity.

| Model file | Scenario | Generators | What it adds |
|---|---|---|---|
| `My_First_DM.gms` | **Base case** | Solar, Coal, Gas | The basic dispatch model |
| `RenewbaleInt.gms` | **Renewable intermittency** | Solar, Wind, Coal, Gas | Each hour, available capacity = capacity × hourly load factor (from `normalisedloads.csv`), so Wind and Solar vary over time |
| `DM_w_ramping.gms` | **Ramping** | Solar, Wind, Coal, Gas | Everything in the renewable model, plus ramp limits (`ramp_L × cap` per hour) and a ramping cost in the objective |

Each model writes the parameter `ExcelResults(T, field)` to a GDX file. Its fields are:

- `DemandMarginal`: the electricity price (the shadow price of the demand constraint).
- `Demand`
- Generation for each generator.

---

## 2. Repository structure

```
.
├── README.md
├── requirements.txt              Python dependencies
├── setup_and_run.bat             One-click install + launch of the dashboard
├── run_models.bat                Re-solve all models (listings -> outputs\)
├── .gitignore
│
├── models/
│   ├── My_First_DM.gms           Base-case model
│   ├── RenewbaleInt.gms          Renewable intermittency model
│   ├── DM_w_ramping.gms          Ramping model
│   └── Adding_Batteries.gms      Ramping + battery storage model
│
├── outputs/                      GAMS listing files (solver logs); read by the
│   └── *.lst                     dashboard's Diagnostics page
│
├── Inputs/
│   ├── base_case.csv             Generator data, base case
│   ├── Renewable_intermit.csv    Generator data incl. Wind and ramp parameters
│   ├── Battery_in.csv            Battery size, power and efficiencies
│   ├── demand(in).csv            Hourly demand (744 h)
│   ├── normalisedloads.csv       Hourly availability factors per generator
│   ├── base_case.gdx             GDX copies of the generator data
│   └── Renewable_intermit.gdx    (created by the models, read by the dashboard)
│
├── Results/
│   ├── My_First_DM_results.gdx   Base-case results
│   ├── Renewable_intermit.gdx    Renewable-scenario results
│   ├── ramping.gdx               Ramping-scenario results (+ PlantCost, TOTCost)
│   └── Batteries.gdx             Battery-scenario results (+ PlantCost, TOTCost)
│
└── dashboard/
    ├── app.py                    Entry point (Dash app, routing)
    ├── config.py                 Paths, scenarios, GAMS location, settings
    ├── components/sidebar.py     Sidebar controls
    ├── pages/                    granular.py, summary.py, diagnostics.py
    ├── data/                     loader, access, metrics, diagnostics,
    │                             lst_parser, runner (re-runs GAMS)
    └── tests/                    pytest test suite
```

---

## 3. Prerequisites

| Requirement | Needed for | Notes |
|---|---|---|
| **Windows** | Everything | The paths and GAMS setup assume Windows |
| **GAMS 25.1** | Running the models and the **Run models** button | Default location is `C:\GAMS\win64\25.1`; other locations can be set (see [4.4](#44-tell-the-dashboard-where-gams-is-only-if-needed)) |
| **MOSEK license** (in GAMS) | Solving the models | The models use `option lp = mosek` |
| **Python 3.6** | The dashboard | The versions in `requirements.txt` are pinned for Python 3.6 |
| **GAMS Python API** (`api_36`) | Reading GDX files in the dashboard | Required by `gdxpds` |
| Microsoft Excel | *Optional* | Only needed if you want `.xlsx` copies of the results (via `gdxxrw`) |

---

## 4. Installation (step by step)

### 4.1 Get the code

```powershell
git clone https://github.com/jasminnassarA/Introduction-Programmes-.git
cd Introduction-Programmes-
git checkout AI-Dashboard
```

### 4.2 Create a virtual environment and install packages

```powershell
py -3.6 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
```

This installs `dash`, `dash-bootstrap-components`, `plotly`, `pandas`, `numpy`, `gdxpds` and `pytest`.

### 4.3 Install the GAMS Python API into the virtual environment

`gdxpds` uses the GAMS Python API to read `.gdx` files. Install it from your GAMS folder:

```powershell
cd C:\GAMS\win64\25.1\apifiles\Python\api_36
<path-to-repo>\.venv\Scripts\python setup.py install
cd <path-to-repo>
```

### 4.4 Tell the dashboard where GAMS is (only if needed)

If GAMS 25.1 is installed in `C:\GAMS\win64\25.1`, skip this step. Otherwise, set these environment variables in the terminal before starting the dashboard:

| Variable | Default | Meaning |
|---|---|---|
| `GAMS_DIR` | `C:\GAMS\win64\25.1` | GAMS installation folder |
| `GAMS_EXE` | `%GAMS_DIR%\gams.exe` | GAMS executable used by **Run models** |
| `DM_ROOT` | the repository folder | Where the models, `Inputs/` and `Results/` live |

```powershell
$env:GAMS_DIR = "D:\GAMS\25.1"
```

> If a newer GAMS (for example GAMS 41) is on your `PATH`, still set `GAMS_DIR` so the dashboard uses the version that matches the Python 3.6 API.

---

## 5. Running the GAMS models

> Always run the models from the **repository root** (they use relative paths such as `Inputs\...` and `Results\...`) and send the listing to `outputs\`. `run_models.bat` does this for all four models.

```powershell
gams models\My_First_DM.gms o=outputs\My_First_DM.lst
gams models\RenewbaleInt.gms o=outputs\RenewbaleInt.lst
gams models\DM_w_ramping.gms o=outputs\DM_w_ramping.lst
gams models\Adding_Batteries.gms o=outputs\Adding_Batteries.lst
```

(Use the full path, for example `C:\GAMS\win64\25.1\gams.exe`, if `gams` is not on your `PATH`.)

Each run:

1. Converts the input CSVs to GDX (with `csv2gdx`).
2. Solves the LP with MOSEK.
3. Writes the results to `Results\*.gdx` and the solver log to `outputs\<model>.lst`.
4. Also writes `Results\*.xlsx` with `gdxxrw`. This step needs Excel; skip it with `--noxlsx=1`.

| Model | Inputs | Output |
|---|---|---|
| `My_First_DM.gms` | `base_case.csv`, `demand(in).csv` | `Results\My_First_DM_results.gdx` |
| `RenewbaleInt.gms` | `Renewable_intermit.csv`, `demand(in).csv`, `normalisedloads.csv` | `Results\Renewable_intermit.gdx` |
| `DM_w_ramping.gms` | `Renewable_intermit.csv`, `demand(in).csv`, `normalisedloads.csv` | `Results\ramping.gdx` |

### Optional command-line flags

| Flag | Effect |
|---|---|
| `--solarCap=<MW>` | Override Solar capacity |
| `--windCap=<MW>` | Override Wind capacity (renewable and ramping models) |
| `--coalCap=<MW>` | Override Coal capacity |
| `--gasCap=<MW>` | Override Gas capacity |
| `--outdir=<folder>` | Write results to another folder (default `Results`) |
| `--noxlsx=1` | Skip the Excel export (no Excel needed) |

Example: double the Solar capacity and skip the Excel output.

```powershell
gams models\RenewbaleInt.gms o=outputs\RenewbaleInt.lst --solarCap=1000 --noxlsx=1
```

---

## 6. Input data reference

**`Inputs/base_case.csv`** has one row per generator: Solar, Coal and Gas.

| Column | Meaning |
|---|---|
| `gen` | Generator name |
| `cost` | Fuel cost |
| `cap` | Capacity (MW) |
| `eff` | Efficiency (fuel cost is divided by this) |
| `vom` | Variable operating & maintenance cost |

**`Inputs/Renewable_intermit.csv`** has the same columns plus Wind, and two ramping columns:

| Column | Meaning |
|---|---|
| `ramp_L` | Maximum change in output per hour, as a fraction of capacity |
| `ramp_cost` | Cost per MW of change in output (used by the ramping model) |

**`Inputs/demand(in).csv`** contains `Hour` and `Demand in region 1 (MWh)` for 744 hours.

**`Inputs/normalisedloads.csv`** contains `Hour, Wind, Solar, Gas, Coal`. Each value is an availability factor between 0 and 1.

To build your own scenario, edit these CSVs (keeping the column layout) and re-run the models.

---

## 7. Running the dashboard

From the repository root:

```powershell
.venv\Scripts\python -m dashboard.app
```

Open **http://127.0.0.1:8050** in your browser. Press `Ctrl+C` in the terminal to stop the server.

> Start it with `python -m dashboard.app` from the repo root, **not** `python dashboard\app.py`. Otherwise the `dashboard` package imports fail.

The dashboard reads:

- `Results\*.gdx` for the results.
- `Inputs\*` for the generator data, demand and load factors.
- The `outputs\*.lst` files for the Diagnostics page.
- For the ramping and battery scenarios, generator costs come straight from the GAMS `PlantCost` variable in the results GDX (so totals equal `TOTCost`).

---

## 8. Using the dashboard

### Pages (top of the sidebar)

| Page | Shows |
|---|---|
| **Granular prices** (`/`) | Hour-by-hour electricity price, demand and generation for each generator |
| **Summary metrics** (`/summary`) | Totals and averages (cost, generation mix, prices) for each scenario |
| **Diagnostics** (`/diagnostics`) | Solver status and information read from the GAMS `.lst` files |

### Sidebar controls

| Control | What it does |
|---|---|
| **Scenario** dropdown | Choose **Base case**, **Renewable intermittency**, **Ramping** or **All (compare)** to view all three side by side |
| **Capacities (MW)** dropdowns | One dropdown each for **Solar, Wind, Coal and Gas**. The options are the base capacity from the input CSV × **1, 1.5, 2, 2.5 or 3**. *Wind applies to the Renewable and Ramping scenarios only.* |
| **Run models** button | Re-solves the models in GAMS with the selected capacities (see below) |
| **Hours shown** slider | Length of the time window displayed (24–744 hours, in steps of 24) |
| **Start hour** with **<** / **>** | Moves the time window through the month |
| **Generators** checklist | Shows or hides individual generators in the charts |

### How "Run models" works

1. Choose capacities in the dropdowns and click **Run models**.
2. If every capacity is at its base value, the pre-computed results in `Results/` are used and GAMS does not run.
3. Otherwise, the dashboard runs `gams.exe` for each scenario, passing the `--solarCap`, `--windCap`, `--coalCap` and `--gasCap` flags. Each run happens in a temporary `.tmp_run_*` folder inside the repo, which is deleted afterwards. The status message under the button shows progress.
4. Results for up to **16** capacity combinations are kept in memory. Switching back to a combination you already ran is instant.
5. These runs never overwrite your files in `Results/`.

> GAMS + MOSEK must be installed for **Run models** to work. Every other part of the dashboard works without GAMS.

---

## 9. Running the tests

```powershell
.venv\Scripts\python -m pytest dashboard\tests -q
```

---

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: dashboard` | Run `python -m dashboard.app` from the **repo root** |
| `gdxpds` / `gdxcc` import error | Install the GAMS Python API (step 4.3) into `.venv`, and check that `GAMS_DIR` points to GAMS 25.1 |
| Wrong GAMS version is picked up | Set `$env:GAMS_DIR` and `$env:GAMS_EXE` to your GAMS 25.1 install |
| **Run models** fails with "gams.exe not found" | Set `GAMS_EXE` to the full path of `gams.exe` |
| Solver / license error in the `.lst` file | Check that your GAMS license includes **MOSEK** |
| GAMS errors when the path contains spaces | Clone the repo to a path **without spaces** if possible, for example `C:\GAMS_models\...`. The dashboard already works around this for its own runs. |
| `gdxxrw` error when running a model | Excel is missing. Add `--noxlsx=1` |
| Dashboard shows no data | Check that `Results\*.gdx` exists, or run the three models (section 5) |
| Leftover `.tmp_run_*` or `225a`-style folders | These are temporary GAMS folders and are safe to delete |
| Port 8050 already in use | Stop the other process, or change `port=` at the bottom of `dashboard/app.py` |
