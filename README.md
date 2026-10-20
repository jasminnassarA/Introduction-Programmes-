# Power System Dispatch Models (GAMS) + Interactive Dashboard

This repository has two parts:

- **Six GAMS dispatch models.** Four single-region models find the lowest-cost way to meet electricity demand in every hour of one month (744 hours) using Solar, Wind, Coal and Gas (the last one adds a battery). `Nodal_SC.gms` adds transmission limits and nodal prices (168 hours), and `Interconnectors.gms` links 2 or 4 regions (wind-heavy, solar-heavy, nuclear-heavy) through interconnectors with losses.
- **A Python Dash dashboard.** It lets you explore the model results, compare scenarios, change generator capacities and re-run the models from your browser.

> **Branch:** this README describes the **`AI-Dashboard`** branch. The dashboard only exists on this branch.

---

## Quick start

Before you start, you need **Windows** and **GAMS 25.1 with a MOSEK license** (in `C:\GAMS\win64\25.1`, or set `GAMS_DIR`).

**Step 1 - Get the code.** Open PowerShell in the folder where you want the project (for example Documents) and run:

```powershell
git clone -b AI-Dashboard https://github.com/jasminnassarA/Introduction-Programmes-.git
```

This creates a new folder called **`Introduction-Programmes-`** inside the folder you were in, e.g. `C:\Users\<you>\Documents\Introduction-Programmes-`.
*No Git?* On GitHub pick the **AI-Dashboard** branch, click **Code -> Download ZIP** and unzip it anywhere. The folder can have any name; below, "the project folder" means the `Introduction-Programmes-` folder (or wherever you unzipped it).

**Step 2 - Start the dashboard.** Open the project folder in File Explorer. `setup_and_run.bat` is directly inside it, next to `README.md` and `run_models.bat`. **Double-click `setup_and_run.bat`.** The first run takes a few minutes. It:

1. Finds Python 3.6-3.9 (Python 3.6 preferred, since GAMS 25.1's Python API only supports 3.6). If none is installed it installs Python 3.9.13 for the current user (winget, or the python.org installer).
2. Creates `.venv` and installs `requirements.txt` (only again when that file changes).
3. Installs the GAMS Python API into `.venv` and opens **http://127.0.0.1:8050** in your browser.

Keep that window open - closing it stops the dashboard.

**Step 3 - Check the models run.** Once the dashboard is open in your browser, go back to the same project folder and **double-click `run_models.bat`**. It solves every model (including Interconnectors with 2 and 4 regions) and prints `MODEL STATUS 1 Optimal` for each one. If every model shows status 1, GAMS and MOSEK work, so the dashboard's **Run models** and **Re-run** buttons will work when you change capacities. If you see an error, see [10. Troubleshooting](#10-troubleshooting).

**Step 4 - Use the dashboard.** Refresh the browser to load the new results, then try changing a capacity and pressing **Run models**, or **Re-run** on the Interconnectors page.

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

All four models are **linear programs (LPs)** solved with **MOSEK**. Each runs over hours `T = 1..744`.

- **Objective:** minimise the total generation cost. For each generator and hour this is `generation × (fuel cost / efficiency + variable O&M cost)`.
- **Constraints:**
  - Total generation must equal demand in every hour.
  - Each generator's output must stay at or below its capacity.

| Model file | Scenario | Generators | What it adds |
|---|---|---|---|
| `My_First_DM.gms` | **Base case** | Solar, Coal, Gas | The basic dispatch model |
| `RenewbaleInt.gms` | **Renewable intermittency** | Solar, Wind, Coal, Gas | Each hour, available capacity = capacity × hourly load factor (from `normalisedloads.csv`), so Wind and Solar vary over time |
| `DM_w_ramping.gms` | **Ramping** | Solar, Wind, Coal, Gas | Everything in the renewable model, plus ramp limits (`ramp_L × cap` per hour) and a ramping cost in the objective |
| `Adding_Batteries.gms` | **Batteries** | Solar, Wind, Coal, Gas + Battery | Everything in the ramping model, plus a battery (state of charge, charge/discharge power limits and efficiencies from `Battery_in.csv`). The battery has no operating cost |
| `Nodal_SC.gms` | **Nodal pricing** (own page `/nodal`) | GENERATOR_1-5 at 5 nodes | Separate 168-hour model: minimises dispatch cost (MC x output) under transmission limits using a DC power flow with shift factors (532 lines, 428 nodes, 20 demand nodes). Flows are tracked on all lines; only lines with a finite rating are limited. Unserved energy is allowed at 10,000 $/MWh. Writes `Dispatch`, `LMP` (nodal prices), `FlowRep` (flow, rating, congestion price) and `TOTCost` |
| `Interconnectors.gms` | **Interconnectors** (own page `/interconnectors`) | Solar, Wind, Coal, Gas, Nuclear in R1-R4 | 744-hour dispatch of 2 or 4 regions (`--regions=N`) linked by interconnectors (transport model: MW limit, % loss, wheeling cost). Ramping as in `DM_w_ramping`, nuclear minimum output 60%, unserved energy at 10,000 $/MWh. Inputs in `Inputs\Interconnect_in` (generated by `make_inputs.py`). Optional `--capfile=<gms>` and `--linkCap=<MW>`. Writes `Results\Interconnectors_<N>.gdx` with `Dispatch`, `Price`, `FlowRep`, `Summary`, `TOTCost` |

Each model writes the parameter `ExcelResults(T, field)` to a GDX file. Its fields are:

- `DemandMarginal`: the electricity price (the shadow price of the demand constraint).
- `Demand`
- Generation for each generator.
- For the battery model: charge, discharge and state of charge.

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
│   ├── Adding_Batteries.gms      Ramping + battery storage model
│   ├── Nodal_SC.gms              Nodal pricing model (transmission constraints)
│   └── Interconnectors.gms       Multi-region model with interconnectors (2 or 4 regions)
│
├── outputs/                      GAMS listing files (solver logs); read by the
│   └── *.lst                     dashboard's Diagnostics page
│
├── Inputs/
│   ├── base_case.csv             Generator data, base case
│   ├── Renewable_intermit.csv    Generator data incl. Wind and ramp parameters
│   ├── Battery_in.csv            Battery size (MWh), power (MW), efficiencies, initial charge
│   ├── demand(in).csv            Hourly demand (744 h)
│   ├── normalisedloads.csv       Hourly availability factors per generator
│   ├── base_case.gdx             GDX copies of the generator data
│   ├── Renewable_intermit.gdx    (created by the models, read by the dashboard)
│   ├── Nodes_in/                 Nodal model inputs (see section 5)
│   └── Interconnect_in/          Interconnector inputs + make_inputs.py (see section 6)
│
├── Results/
│   ├── My_First_DM_results.gdx   Base-case results
│   ├── Renewable_intermit.gdx    Renewable-scenario results
│   ├── ramping.gdx               Ramping-scenario results (+ PlantCost, TOTCost)
│   ├── Batteries.gdx             Battery-scenario results (+ PlantCost, TOTCost)
│   ├── Nodal_SC.gdx              Nodal results (read by the Nodal page)
│   └── Interconnectors_2/_4.gdx  Interconnector results (read by the Interconnectors page)
│
└── dashboard/
    ├── app.py                    Entry point (Dash app, routing)
    ├── config.py                 Paths, scenarios, GAMS location, settings
    ├── components/sidebar.py     Sidebar controls
    ├── pages/                    granular.py, summary.py, diagnostics.py, nodal.py,
    │                             interconnectors.py
    ├── data/                     loader, access, metrics, diagnostics,
    │                             lst_parser, runner (re-runs GAMS),
    │                             nodal (Nodal_SC results), topology (guessed layout),
    │                             interconnectors (Interconnectors results)
    └── tests/                    pytest test suite
```

---

## 3. Prerequisites

| Requirement | Needed for | Notes |
|---|---|---|
| **Windows** | Everything | The paths and GAMS setup assume Windows |
| **GAMS 25.1** | Running the models, the **Run models** button the Nodal page's **Re-run Nodal_SC** button and the Interconnectors page's **Re-run** button (both pages show the committed results gdx files without solving) | Default location is `C:\GAMS\win64\25.1`; other locations can be set (see [4.4](#44-tell-the-dashboard-where-gams-is-only-if-needed)) |
| **MOSEK license** (in GAMS) | Solving the models | The models use `option lp = mosek` |
| **Python 3.6** | The dashboard | The versions in `requirements.txt` are pinned for Python 3.6 |
| **GAMS Python API** (`api_36`) | Reading GDX files in the dashboard | Required by `gdxpds` |
| Microsoft Excel | *Optional* | Only needed if you want `.xlsx` copies of the results (via `gdxxrw`) |

---

## 4. Installation (step by step)

### 4.1 Get the code

```powershell
git clone -b AI-Dashboard https://github.com/jasminnassarA/Introduction-Programmes-.git
cd Introduction-Programmes-
```

The clone creates the `Introduction-Programmes-` folder inside the folder your terminal was in. Without Git, download the ZIP of the **AI-Dashboard** branch from GitHub and unzip it anywhere (any folder name works). Run every command below from inside the project folder.

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

> Always run the models from the **repository root** (they use relative paths such as `Inputs\...` and `Results\...`) and send the listing to `outputs\`. `run_models.bat` does this for all models (Interconnectors with 2 and 4 regions).

```powershell
gams models\My_First_DM.gms o=outputs\My_First_DM.lst
gams models\RenewbaleInt.gms o=outputs\RenewbaleInt.lst
gams models\DM_w_ramping.gms o=outputs\DM_w_ramping.lst
gams models\Adding_Batteries.gms o=outputs\Adding_Batteries.lst
gams models\Nodal_SC.gms o=outputs\Nodal_SC.lst
gams models\Interconnectors.gms --regions=2 o=outputs\Interconnectors_2.lst
gams models\Interconnectors.gms --regions=4 o=outputs\Interconnectors_4.lst
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
| `Adding_Batteries.gms` | `Renewable_intermit.csv`, `Battery_in.csv`, `demand(in).csv`, `normalisedloads.csv` | `Results\Batteries.gdx` |
| `Nodal_SC.gms` | `Nodes_in\generators(in).csv`, `hourlydemandbynode(in).csv`, `shiftfactormatrix(in).csv`, `lineratings(in).csv` | `Results\Nodal_SC.gdx` |
| `Interconnectors.gms` | `Interconnect_in\generators.csv`, `demand.csv`, `loadfactors.csv`, `interconnectors.csv` | `Results\Interconnectors_<N>.gdx` (N = number of regions) |

**Nodal inputs (`Inputs\Nodes_in`)**

| File | Contents |
|---|---|
| `generators(in).csv` | Generator, marginal cost `MC` ($/MWh), capacity `CAP` (MW), `NODE` |
| `hourlydemandbynode(in).csv` | Demand (MWh) for 168 hours x 20 nodes |
| `shiftfactormatrix(in).csv` | Shift factors (PTDF), 532 lines x 428 nodes. Node 1483 is the reference bus (all zeros) |
| `lineratings(in).csv` | Line rating (MW); `inf` = unlimited |
| `lines_guess.csv`, `layout_guess.csv` | Cached **guessed** network layout for the Nodal page (illustrative only; rebuilt automatically if deleted) |
| `lines(in).csv` *(optional)* | Real topology `LINE_ID,FROM,TO`; replaces the guessed line ends if present |

### Optional command-line flags

| Flag | Effect |
|---|---|
| `--solarCap=<MW>` | Override Solar capacity |
| `--windCap=<MW>` | Override Wind capacity (renewable, ramping and battery models) |
| `--batCap=<MWh>` / `--batPower=<MW>` | Override battery size / power (battery model) |
| `--batChEff=<0-1>` / `--batDisEff=<0-1>` | Override battery charge / discharge efficiency (battery model) |
| `--coalCap=<MW>` | Override Coal capacity |
| `--gasCap=<MW>` | Override Gas capacity |
| `--outdir=<folder>` | Write results to another folder (default `Results`) |
| `--noxlsx=1` | Skip the Excel export (no Excel needed) |
| `--regions=<1-4>` | Interconnectors: number of active regions R1..RN (default 2) |
| `--capfile=<file.gms>` | Interconnectors: capacity overrides as GAMS lines, e.g. `gdata('R2','Wind','cap') = 750;` |
| `--linkCap=<MW>` | Interconnectors: same MW limit on every link |

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

**`Inputs/Battery_in.csv`** has one row per battery: `battery, cap` (MWh), `power` (MW), `charg_eff`, `discharge_eff`, `inita_charge` (MWh at hour 1).

**`Inputs/Interconnect_in/`** (Interconnectors model, regions R1-R4; R1 = the existing data above):

| File | Contents |
|---|---|
| `generators.csv` | `region, gen, cost, cap, eff, vom, ramp_L, ramp_cost, min_L` for Solar, Wind, Coal, Gas, Nuclear (`min_L` = minimum output share, 0.6 for Nuclear) |
| `demand.csv` | `Hour, R1, R2, R3, R4` demand (MWh), 744 hours |
| `loadfactors.csv` | `Hour, region, Solar, Wind, Coal, Gas, Nuclear` availability factors (0-1) |
| `interconnectors.csv` | `from, to, cap` (MW), `loss` (fraction), `cost` ($/MWh), one row per direction |
| `make_inputs.py` | Regenerates the four CSVs (fixed seed): `.venv\Scripts\python Inputs\Interconnect_in\make_inputs.py` |

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
| **Nodal** (`/nodal`) | Nodal pricing model (`Nodal_SC`). **Congestion:** network film (B) and line-loading film (A), one frame per hour with play buttons at 1 / 2 / 5 s per hour (grey = empty, green < 50%, yellow 50-90%, red >= 90% of rating, blue = unlimited line with flow), a line-loading heatmap (C1) and a nodal congestion heatmap (LMP - system price, C2). Nodes that are not an end of any guessed line get a dotted spur to the line they influence most; tick generators above the network film to draw their influence lines (|shift factor| >= slider, default 0.1). The network layout is **guessed** from the shift factor matrix and is for visual purposes only (cached in `Inputs\Nodes_in\lines_guess.csv` / `layout_guess.csv`; a real `Inputs\Nodes_in\lines(in).csv` with `LINE_ID,FROM,TO` replaces the guessed line ends; delete `layout_guess.csv` to recompute positions). Also: dispatch, system price vs LMPs, LMP heatmap of all 428 nodes, price spread, congested lines, line loading, generator utilisation and price duration curves. The sidebar is hidden on this page; it has its own controls (hours 1-168, nodes, line) and a **Re-run Nodal_SC** button that re-solves from `Inputs\Nodes_in` and overwrites `Results\Nodal_SC.gdx` (no `.xlsx`; use `run_models.bat` for that). |
| **Interconnectors** (`/interconnectors`) | Multi-region model (`Interconnectors.gms`). Choose 2 or 4 regions (reads `Results\Interconnectors_2.gdx` / `_4.gdx`). Graphs: animated region map (price-coloured regions, flow-scaled links with direction arrows), imports/exports by region, regional prices, price gap, price duration curves, focus-region dispatch (imports stacked, exports below zero), generation mix by region, flow on a selected link, link usage heatmap, average-day net export and hours each link is full vs. price gap. The capacity panel sets a multiplier per region and generator plus one MW limit for every link. **Re-run** with base values re-solves and overwrites the results gdx; with changed values it solves in a temporary folder and keeps the result in memory only (a yellow banner shows what was changed). |

### Sidebar controls

| Control | What it does |
|---|---|
| **Scenario** dropdown | Choose **Base case**, **Renewable intermittency**, **Ramping**, **Batteries** or **All (compare)** to view all four side by side |
| **Capacities (MW)** dropdowns | One dropdown each for **Solar, Wind, Coal and Gas**. The options are the base capacity from the input CSV × **1, 1.5, 2, 2.5 or 3**. *Wind applies to the Renewable, Ramping and Batteries scenarios.* |
| **Battery** controls | Capacity (MWh), power (MW) and charge/discharge efficiencies. *Batteries scenario only.* |
| **Run models** button | Re-solves the models in GAMS with the selected capacities (see below) |
| **Hours shown** slider | Shows hours 1 to N of the month (N = 24–744, in steps of 24). The window always starts at hour 1 |
| **Generators** checklist | Shows or hides individual generators in the charts |

### How "Run models" works

1. Choose capacities in the dropdowns and click **Run models**.
2. If every capacity is at its base value, the pre-computed results in `Results/` are used and GAMS does not run.
3. Otherwise, the dashboard runs `gams.exe` for each scenario, passing the `--solarCap`, `--windCap`, `--coalCap`, `--gasCap` (and battery `--bat*`) flags. Each run happens in a temporary `.tmp_run_*` folder inside the repo, which is deleted afterwards. The status message under the button shows progress.
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
| Dashboard shows no data | Check that `Results\*.gdx` exists, or run the four models (section 5) |
| Leftover `.tmp_run_*` or `225a`-style folders | These are temporary GAMS folders and are safe to delete |
| Port 8050 already in use | Stop the other process, or change `port=` at the bottom of `dashboard/app.py` |
