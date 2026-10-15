# PLAN.md — My_First_DM Dispatch Dashboard

## 1. Environment
- Python 3.6.8 64-bit (`C:\Program Files\Python36`) + GAMS 25.1 (`C:\GAMS\win64\25.1`).
- venv: `C:\Intro to GAMs\.venv` (built as `.venv36`, renamed after old 3.13 venv removed).
- GAMS 25.1 Python API installed from `apifiles\Python\api_36` (`python setup.py install`).
- `requirements.txt` pins (final versions confirmed during install — see bottom of file).
- `config.GAMS_DIR` (default `C:\GAMS\win64\25.1`) is passed to gdxpds so 25.1 is used, not GAMS 41.

## 2. Data model
- Source: `ExcelResults(T, outfield)`; outfield ∈ {DemandMarginal, Solar, Coal, Gas}.
- Load: `gdxpds.to_dataframes(path)['ExcelResults']` → pivot to one row per hour.
- Inputs: `Inputs\demand(in).csv`, `Inputs\base_case.csv` (headers/values stripped of whitespace).
- Hourly df: datetime = START + (T-1)h | T | price | Solar | Coal | Gas | demand | cost_<gen> | total_cost | run
- Cost per gen/hour: `U * (vom + cost/eff)`.
- GDX omits zeros → fill missing with 0.
- Cache per (path, mtime).

## 3. Runs / versions
- "Current" = repo root (`Results\` + `Inputs\`), default.
- Labelled = `runs\<label>\Results\*.gdx`, `runs\<label>\Inputs\*.csv`, `meta.json` (label, timestamp, objective from `.lst`, note).
- Create via CLI `python -m dashboard.snapshot --label base_v1 [--note ...] [--force]` or sidebar "Save" button. Both call `versions.snapshot()`. No overwrite without force.
- Source files (Results, Inputs, .gms, .lst) are only ever copied, never modified.

## 4. Code structure
```
dashboard\
  __init__.py, config.py, app.py, snapshot.py
  data\loader.py, versions.py, metrics.py
  components\sidebar.py
  pages\granular.py, summary.py
  tests\test_loader.py, test_metrics.py
requirements.txt
```
Routing via `dcc.Location` (no Dash pages API).

## 5. Sidebar (global)
- Multi-select run dropdown ("current" + labelled runs), default "current".
- Snapshot label + note + Save button + status.
- Nav links: Granular / Summary. Selection held in `dcc.Store`.

## 6. Granular page
- 5-day window: date picker + prev/next buttons.
- One callback updates: price line per run; dispatch stacked area + demand line per run; hourly total cost; KPI strip (avg/max/min price, total cost).

## 7. Summary page
Each plot has own Month/Year toggle; grouped by run.
| Plot | Metric |
|---|---|
| Price stats | avg / max / min price |
| Generation mix | MWh by tech (stacked) + share % |
| Cost | total and per-tech cost |
| Capacity factor | gen / (cap × hours) |
| Unserved / curtailed | demand − generation; solar cap − solar dispatch (proxy) |
Plus summary table with CSV export.

## 8. Testing
- pytest on loader and metrics.
- Run: `.venv\Scripts\python -m dashboard.app` → http://127.0.0.1:8050

## 9. Defaults / notes
- START_DATETIME = 2024-01-01 00:00 (config.py). Any number of hours (e.g. 8760) is supported.
- Unserved energy should be 0 (demand constraint is an equality) — sanity check only.
- Curtailed solar is a proxy (no availability profile in inputs).

## 10. Build status (implemented)
- Final pins: gdxpds 1.1.0, pandas 1.1.5, numpy 1.19.5, plotly 5.18.0, dash 2.9.3,
  dash-bootstrap-components 1.2.1 (1.4.x does not support Py3.6), pytest 7.0.1. pip 21.3.1.
- Verified: GDX loads 744 hours; summed total_cost = 3,100,391.58 = GAMS OBJECTIVE VALUE in .lst.
- Old Python 3.13 `.venv` removed; new 3.6 venv lives at `.venv` (activate scripts patched after rename).
- Note: the venv's `pip.exe` launcher still points at `.venv36`; use `.venv\Scripts\python -m pip ...`.

## Usage
```
cd "C:\Intro to GAMs"
.venv\Scripts\python -m dashboard.app                         # http://127.0.0.1:8050
.venv\Scripts\python -m dashboard.snapshot --label base_v1 --note "base case"
.venv\Scripts\python -m pytest dashboard\tests -q
```
Change the start date with `START_DATETIME` in `dashboard\config.py` (or env var `DM_START`).
