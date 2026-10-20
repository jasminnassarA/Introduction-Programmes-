"""Run the GAMS models for a chosen set of generator capacities - results are never saved to disk.

caps is a dict {gen: MW} for config.CAP_GENERATORS (missing gens = base value from the input csvs).
- All capacities at base: the original Results/ files are used and GAMS never runs.
- Otherwise every scenario is solved in a temporary folder inside ROOT, the results gdx and .lst are
  read into memory and the folder is deleted (also on failure).  Results are kept in memory for the
  rest of the dashboard session only, so picking the same combination again doesn't re-run GAMS.
- Wind only exists in the renewable / ramping models: the base case ignores the Wind capacity.
"""
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path

import pandas as pd

from dashboard import config

_LOCK = threading.Lock()
_STATUS_RE = re.compile(r"\*\*\*\* MODEL STATUS\s+(\d+)")
OK_MODEL_STATUS = {1, 2}  # optimal / locally optimal

last_status = ""  # human readable summary of the last run (shown in the sidebar)
_CACHE = OrderedDict()  # caps key -> {scenario key: {"results": long df, "lst": text}}


class GamsRunError(RuntimeError):
    pass


def _root(root=None):
    return Path(root or config.ROOT)


def _csv_caps(path):
    df = pd.read_csv(path, skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    return {str(g).strip(): int(float(str(c).strip())) for g, c in zip(df["gen"], df["cap"])}


def scenario_gens(key, root=None):
    """Generators present in a scenario's input csv (e.g. no Wind in the base case)."""
    try:
        return list(_csv_caps(_root(root) / config.SCENARIOS[key]["gen_csv"]))
    except Exception:
        return []


def _bat_csv(root=None):
    """Base battery values {BatCap: .., ...} from the first scenario that has a battery csv."""
    for sc in config.SCENARIOS.values():
        if "battery" not in sc:
            continue
        try:
            df = pd.read_csv(_root(root) / sc["battery"], skipinitialspace=True)
            df.columns = [c.strip() for c in df.columns]
            row = df.iloc[0]
            return {k: _round(k, float(str(row[col]).strip())) for k, (col, _, _) in config.BAT_PARAMS.items()}
        except Exception:
            continue
    return {}


def _round(name, v):
    dec = config.BAT_PARAMS[name][2] if name in config.BAT_PARAMS else 0
    return int(round(v)) if dec == 0 else round(v, dec)


def has_battery(key):
    return "battery" in config.SCENARIOS[key]


def default_caps(root=None):
    """Base capacity per generator: base_case.csv first, then the other scenarios' csvs (Wind).
    Battery settings come from Battery_in.csv."""
    caps = {}
    for key in [config.DEFAULT_SCENARIO] + [k for k in config.SCENARIOS if k != config.DEFAULT_SCENARIO]:
        try:
            for g, c in _csv_caps(_root(root) / config.SCENARIOS[key]["gen_csv"]).items():
                caps.setdefault(g, c)
        except Exception:
            continue
    out = {g: caps.get(g, 0) for g in config.CAP_GENERATORS}
    out.update(_bat_csv(root))
    return out


def cap_options(gen, root=None):
    base = default_caps(root)[gen]
    return [int(round(base * m)) for m in config.CAP_MULTIPLIERS]


def normalize(caps, root=None):
    """Full {name: value} dict; None / missing entries -> base value."""
    out = default_caps(root)
    for g, v in (caps or {}).items():
        if g in out and v is not None:
            out[g] = _round(g, float(v))
    return out


def is_default(caps, root=None):
    return normalize(caps, root) == default_caps(root)


def changed_caps(key, caps, root=None):
    """Settings that differ from base and exist in this scenario's model."""
    base, full, gens = default_caps(root), normalize(caps, root), scenario_gens(key, root)
    out = {g: full[g] for g in config.CAP_GENERATORS if g in gens and full[g] != base[g]}
    if has_battery(key):
        out.update({b: full[b] for b in config.BAT_PARAMS if b in full and full[b] != base.get(b)})
    return out


def _flag(name, value):
    if name in config.BAT_PARAMS:
        _, flag, dec = config.BAT_PARAMS[name]
        return "--%s=%s" % (flag, ("%d" % value) if dec == 0 else ("%.*f" % (dec, value)))
    return "--%sCap=%d" % (name.lower(), value)


def cache_key(caps, root=None):
    return (str(_root(root)),) + tuple(sorted(normalize(caps, root).items()))


def results_path(key, root=None):
    """Original results gdx for a scenario (base capacities)."""
    return _root(root) / config.SCENARIOS[key]["results"]


def lst_path(key, root=None):
    return _root(root) / config.SCENARIOS[key]["lst"]


def gams_command(key, caps, tmpdir, root=None):
    # Paths relative to ROOT (the cwd): GAMS rejects arguments containing spaces ("Intro to GAMs").
    rel = Path(tmpdir).relative_to(_root(root))
    cmd = [config.GAMS_EXE, str(config.SCENARIOS[key]["gms"])]
    cmd += [_flag(g, c) for g, c in changed_caps(key, caps, root).items()]
    cmd += ["--outdir=%s" % rel, "--noxlsx=1", "o=%s" % (rel / Path(config.SCENARIOS[key]["lst"]).name), "lo=0"]
    return cmd


def _model_status(text):
    m = _STATUS_RE.findall(text or "")
    return int(m[-1]) if m else None


BAT_LABELS = {"BatCap": "Battery %d MWh", "BatPower": "%d MW", "BatChEff": "charge eff %.2f",
              "BatDisEff": "discharge eff %.2f"}


def _caps_label(caps, root=None):
    return ", ".join((BAT_LABELS[g] % c) if g in BAT_LABELS else "%s %d MW" % (g, c)
                     for g, c in normalize(caps, root).items())


def run_scenario(key, caps, tmpdir, root=None):
    """Solve one scenario in tmpdir; return {"results": long df, "lst": text} or raise GamsRunError."""
    from dashboard.data import loader

    sc = config.SCENARIOS[key]
    res = Path(tmpdir) / Path(sc["results"]).name
    lst = Path(tmpdir) / Path(sc["lst"]).name
    proc = subprocess.run(gams_command(key, caps, tmpdir, root), cwd=str(_root(root)),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    text = lst.read_text(errors="ignore") if lst.exists() else ""
    status = _model_status(text)
    if proc.returncode != 0 or not res.exists() or status not in OK_MODEL_STATUS:
        tail = "\n".join(text.splitlines()[-15:]) or (getattr(proc, "stderr", "") or "")[-1000:]
        raise GamsRunError("GAMS failed for %s at %s (return code %s, model status %s).\n%s"
                           % (config.scenario_label(key), _caps_label(caps, root), proc.returncode, status, tail))
    return {"results": loader.read_results_gdx(res), "plant_cost": loader.read_plant_cost_gdx(res),
            "lst": text}


def run_all(caps, root=None):
    """Solve every scenario in a temporary folder that is always deleted afterwards."""
    tmp = tempfile.mkdtemp(prefix=config.TMP_PREFIX, dir=str(_root(root)))
    try:
        return {key: run_scenario(key, caps, tmp, root) for key in config.SCENARIOS}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cleanup_tmp(root=None):
    """Remove leftover temporary run folders (e.g. from an interrupted dashboard)."""
    for d in _root(root).glob(config.TMP_PREFIX + "*"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)


def get_results(caps, root=None):
    """In-memory results for caps (solving if needed), or None for the base capacities."""
    global last_status
    if is_default(caps, root):
        last_status = "Base inputs (Results folder)"
        return None
    k = cache_key(caps, root)
    with _LOCK:
        if k in _CACHE:
            _CACHE.move_to_end(k)
            last_status = "Using results from this session"
            return _CACHE[k]
        t0 = time.time()
        entry = run_all(caps, root)
        _CACHE[k] = entry
        while len(_CACHE) > config.RESULT_CACHE_SIZE:
            _CACHE.popitem(last=False)
        last_status = "Solved %d model(s) in %.1fs" % (len(entry), time.time() - t0)
        return entry


def cached_results(caps, root=None):
    """In-memory results if already solved (never runs GAMS); None for base or not yet run."""
    if is_default(caps, root):
        return None
    return _CACHE.get(cache_key(caps, root))


def clear_cache():
    _CACHE.clear()


# ---------------- Nodal_SC (own page, overwrites Results\Nodal_SC.gdx) ----------------
_NODAL_LOCK = threading.Lock()


def nodal_command():
    sc = config.NODAL
    return [config.GAMS_EXE, str(sc["gms"]), "--outdir=%s" % Path(sc["results"]).parent,
            "--noxlsx=1", "o=%s" % sc["lst"], "lo=0"]


def run_nodal(root=None):
    """Re-solve Nodal_SC from the csvs in Inputs\\Nodes_in; returns a status string or raises GamsRunError."""
    from dashboard.data import nodal

    if not _NODAL_LOCK.acquire(blocking=False):
        raise GamsRunError("Nodal_SC is already running.")
    try:
        t0 = time.time()
        proc = subprocess.run(nodal_command(), cwd=str(_root(root)),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        lst = _root(root) / config.NODAL["lst"]
        text = lst.read_text(errors="ignore") if lst.exists() else ""
        status = _model_status(text)
        if proc.returncode != 0 or status not in OK_MODEL_STATUS:
            tail = "\n".join(text.splitlines()[-15:]) or (getattr(proc, "stderr", "") or "")[-1000:]
            raise GamsRunError("Nodal_SC failed (return code %s, model status %s).\n%s"
                               % (proc.returncode, status, tail))
        nodal.clear_cache()
        return "Solved Nodal_SC in %.1fs - model status %d (Optimal) at %s" % (
            time.time() - t0, status, time.strftime("%H:%M:%S"))
    finally:
        _NODAL_LOCK.release()


# ---------------- Interconnectors (own page) ----------------
# Base inputs: re-solve and overwrite Results\Interconnectors_<N>.gdx.
# Changed capacities: solve in a temporary folder, keep the result in memory only (_IC_CACHE).
_IC_LOCK = threading.Lock()
_IC_CACHE = OrderedDict()  # key string -> data dict (dashboard.data.interconnectors.build)


def ic_base_caps(root=None):
    """{"R1.Solar": MW, ...} from Inputs\\Interconnect_in\\generators.csv."""
    df = pd.read_csv(_root(root) / config.INTERCONNECTORS["gen_csv"])
    return {"%s.%s" % (r, g): float(c) for r, g, c in zip(df["region"], df["gen"], df["cap"])}


def ic_base_link_cap(root=None):
    df = pd.read_csv(_root(root) / config.INTERCONNECTORS["link_csv"])
    return float(df["cap"].max())


def ic_changes(mults, link_cap, root=None):
    """(changed caps {"R2.Wind": MW}, link cap or None) relative to the base inputs."""
    base = ic_base_caps(root)
    caps = {k: base[k] * float(m) for k, m in (mults or {}).items()
            if k in base and m is not None and float(m) != 1.0}
    link = None if link_cap is None or float(link_cap) == ic_base_link_cap(root) else float(link_cap)
    return caps, link


def ic_key(regions, mults, link_cap, root=None):
    """Cache key string; None when everything is at base."""
    caps, link = ic_changes(mults, link_cap, root)
    if not caps and link is None:
        return None
    parts = ["%s x%g" % (k, float(mults[k])) for k in sorted(caps)]
    if link is not None:
        parts.append("links %d MW" % link)
    return "%d|%s" % (int(regions), ", ".join(parts))


def ic_capfile_text(caps):
    lines = ["* written by the dashboard - capacity overrides"]
    for k, v in sorted(caps.items()):
        r, g = k.split(".", 1)
        lines.append("gdata('%s','%s','cap') = %g;" % (r, g, v))
    return "\n".join(lines) + "\n"


def ic_command(regions, outdir, lst, capfile=None, link_cap=None):
    cmd = [config.GAMS_EXE, str(config.INTERCONNECTORS["gms"]), "--regions=%d" % int(regions),
           "--outdir=%s" % outdir, "--noxlsx=1"]
    if capfile:
        cmd.append("--capfile=%s" % capfile)
    if link_cap is not None:
        cmd.append("--linkCap=%g" % link_cap)
    return cmd + ["o=%s" % lst, "lo=0"]


def _ic_solve(cmd, res, lst, root, label):
    proc = subprocess.run(cmd, cwd=str(_root(root)), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)
    text = lst.read_text(errors="ignore") if lst.exists() else ""
    status = _model_status(text)
    if proc.returncode != 0 or not res.exists() or status not in OK_MODEL_STATUS:
        tail = "\n".join(text.splitlines()[-15:]) or (getattr(proc, "stderr", "") or "")[-1000:]
        raise GamsRunError("Interconnectors failed (%s; return code %s, model status %s).\n%s"
                           % (label, proc.returncode, status, tail))
    return status


def ic_cached(key):
    return _IC_CACHE.get(key) if key else None


def run_interconnectors(regions, mults=None, link_cap=None, root=None):
    """Solve the interconnector model. Returns (status message, key); key None = base results file."""
    from dashboard.data import interconnectors

    regions = int(regions)
    key = ic_key(regions, mults, link_cap, root)
    if key and key in _IC_CACHE:
        _IC_CACHE.move_to_end(key)
        return "Using results from this session (%s)" % key.split("|", 1)[1], key
    if not _IC_LOCK.acquire(blocking=False):
        raise GamsRunError("Interconnectors is already running.")
    t0 = time.time()
    try:
        if key is None:
            res = _root(root) / config.ic_path("results", regions)
            lst = _root(root) / config.ic_path("lst", regions)
            cmd = ic_command(regions, res.parent.relative_to(_root(root)), config.ic_path("lst", regions))
            status = _ic_solve(cmd, res, lst, root, "base inputs")
            interconnectors.clear_cache()
            return ("Solved Interconnectors (%d regions, base inputs) in %.1fs - model status %d at %s"
                    % (regions, time.time() - t0, status, time.strftime("%H:%M:%S"))), None
        caps, link = ic_changes(mults, link_cap, root)
        tmp = Path(tempfile.mkdtemp(prefix=config.TMP_PREFIX, dir=str(_root(root))))
        try:
            rel = tmp.relative_to(_root(root))
            capfile = None
            if caps:
                (tmp / "caps.gms").write_text(ic_capfile_text(caps))
                capfile = rel / "caps.gms"
            res = tmp / config.ic_path("results", regions).name
            lst = tmp / config.ic_path("lst", regions).name
            status = _ic_solve(ic_command(regions, rel, rel / lst.name, capfile, link), res, lst, root,
                               key.split("|", 1)[1])
            _IC_CACHE[key] = interconnectors.read_gdx(res)
            while len(_IC_CACHE) > config.RESULT_CACHE_SIZE:
                _IC_CACHE.popitem(last=False)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
        return ("Solved modified case (%s) in %.1fs - model status %d"
                % (key.split("|", 1)[1], time.time() - t0, status)), key
    finally:
        _IC_LOCK.release()
