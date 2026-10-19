"""Parse a GAMS .lst listing: solve summary, model statistics and per-element equation marginals."""
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from dashboard import config

_PATTERNS = {
    "model": (r"^\s+MODEL\s+(\S+)\s+OBJECTIVE\s+(\S+)", ("model", "objective_var")),
    "type": (r"^\s+TYPE\s+(\S+)\s+DIRECTION\s+(\S+)", ("model_type", "direction")),
    "solver": (r"^\s+SOLVER\s+(\S+)\s+FROM LINE\s+(\d+)", ("solver", "solve_line")),
    "solver_status": (r"\*\*\*\* SOLVER STATUS\s+(\d+)\s+(.+?)\s*$", ("solver_status_code", "solver_status")),
    "model_status": (r"\*\*\*\* MODEL STATUS\s+(\d+)\s+(.+?)\s*$", ("model_status_code", "model_status")),
    "objective": (r"\*\*\*\* OBJECTIVE VALUE\s+([-+0-9.Ee]+)", ("objective",)),
    "resource": (r"RESOURCE USAGE, LIMIT\s+([0-9.Ee+-]+)\s+([0-9.Ee+-]+)", ("resource_used", "resource_limit")),
    "iter": (r"ITERATION COUNT, LIMIT\s+(\d+)\s+(\d+)", ("iterations", "iteration_limit")),
    "equ": (r"BLOCKS OF EQUATIONS\s+([\d,]+)\s+SINGLE EQUATIONS\s+([\d,]+)", ("equation_blocks", "single_equations")),
    "var": (r"BLOCKS OF VARIABLES\s+([\d,]+)\s+SINGLE VARIABLES\s+([\d,]+)", ("variable_blocks", "single_variables")),
    "nz": (r"NON ZERO ELEMENTS\s+([\d,]+)", ("non_zeros",)),
    "gen_time": (r"GENERATION TIME\s+=\s+([0-9.]+)", ("generation_time",)),
    "infeas": (r"^\s+(\d+) INFEASIBLE", ("infeasible",)),
    "header": (r"^\f?GAMS (\S+)\s+.*?(\d\d/\d\d/\d\d \d\d:\d\d:\d\d)\s+Page", ("gams_version", "solve_date")),
}
_NUMERIC = {"solver_status_code", "model_status_code", "objective", "resource_used", "resource_limit",
            "iterations", "iteration_limit", "equation_blocks", "single_equations", "variable_blocks",
            "single_variables", "non_zeros", "generation_time", "infeasible", "solve_line"}
_EXEC_RE = re.compile(r"EXECUTION TIME\s+=\s+([0-9.]+)", re.M)
_SPECIAL = {".": 0.0, "EPS": 0.0, "+INF": float("inf"), "INF": float("inf"), "-INF": float("-inf")}


def _num(s):
    s = s.strip().replace(",", "")
    return _SPECIAL[s] if s in _SPECIAL else float(s)


def parse_summary(text):
    """Return dict of solve/model statistics (last SOLVE in the file wins)."""
    out = {}
    for _, (pat, names) in _PATTERNS.items():
        m = re.findall(pat, text, re.M)
        if not m:
            continue
        vals = m[0] if names[0] == "gams_version" else m[-1]  # header: first page
        vals = vals if isinstance(vals, tuple) else (vals,)
        for n, v in zip(names, vals):
            out[n] = _num(v) if n in _NUMERIC else v.strip()
    ex = _EXEC_RE.findall(text)
    if ex:
        out["execution_time"] = float(ex[-1])
    for k in ("solver_status_code", "model_status_code", "iterations", "infeasible", "single_equations",
              "single_variables", "non_zeros", "equation_blocks", "variable_blocks"):
        if k in out:
            out[k] = int(out[k])
    return out


def parse_equ_marginals(text, name):
    """Rows of '---- EQU <name>' table -> DataFrame(gen, T, level, upper, marginal)."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if re.match(r"^---- EQU %s\b" % re.escape(name), l)), None)
    cols = ["gen", "T", "level", "upper", "marginal"]
    if start is None:
        return pd.DataFrame(columns=cols)
    row_re = re.compile(r"^(\S+)\s*\.(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")
    rows = []
    for l in lines[start + 1:]:
        if l.startswith("---- "):
            break
        m = row_re.match(l)
        if m:
            g, t, _lo, lev, up, mar = m.groups()
            rows.append((g, int(t), _num(lev), _num(up), _num(mar)))
    return pd.DataFrame(rows, columns=cols)


def _parse(text):
    return parse_summary(text), parse_equ_marginals(text, "Qcap")


@lru_cache(maxsize=16)
def _load_cached(path, mtime):
    return _parse(Path(path).read_text(errors="ignore"))


def load_lst(key, root=None, caps=None):
    """(summary dict, Qcap DataFrame) for a scenario key, or None if no listing.

    Base capacities: the .lst file in ROOT (cached on mtime).  Otherwise the listing text kept in
    memory from the temporary GAMS run (never runs GAMS itself).
    """
    from dashboard.data import runner

    if not runner.is_default(caps, root):
        entry = runner.cached_results(caps, root)
        if entry is None:
            return None
        item = entry[key]
        if "lst_parsed" not in item:
            item["lst_parsed"] = _parse(item["lst"])
        s, q = item["lst_parsed"]
        return dict(s), q.copy()
    p = runner.lst_path(key, root)
    if not p.exists():
        return None
    s, q = _load_cached(str(p), p.stat().st_mtime)
    return dict(s), q.copy()
