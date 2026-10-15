"""Labelled run versions: list and snapshot. Source files are only copied, never modified."""
import datetime as dt
import json
import re
import shutil
from pathlib import Path

from dashboard import config

_LABEL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_OBJ_RE = re.compile(r"OBJECTIVE VALUE\s+([-+0-9.Ee]+)")


def list_runs(root=None, runs_dir=None):
    """Return ordered dict-like list of (label, path). 'current' (repo root) first."""
    root = Path(root or config.ROOT)
    runs_dir = Path(runs_dir or config.RUNS_DIR)
    runs = [(config.CURRENT, root)]
    if runs_dir.exists():
        for d in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
            if (d / config.RESULTS_GDX).exists():
                runs.append((d.name, d))
    return runs


def run_path(label, root=None, runs_dir=None):
    return dict(list_runs(root, runs_dir))[label]


def read_meta(path):
    f = Path(path) / "meta.json"
    return json.loads(f.read_text()) if f.exists() else {}


def parse_objective(lst_path):
    lst_path = Path(lst_path)
    if not lst_path.exists():
        return None
    m = _OBJ_RE.findall(lst_path.read_text(errors="ignore"))
    return float(m[-1]) if m else None


def snapshot(label, note="", force=False, root=None, runs_dir=None):
    """Copy current Results + Inputs (+ .lst) into runs/<label>/ and write meta.json."""
    label = (label or "").strip()
    if not _LABEL_RE.match(label) or label == config.CURRENT:
        raise ValueError("Label must be letters/digits/_ . - and not 'current'.")
    root = Path(root or config.ROOT)
    runs_dir = Path(runs_dir or config.RUNS_DIR)
    src_gdx = root / config.RESULTS_GDX
    if not src_gdx.exists():
        raise FileNotFoundError(str(src_gdx))

    dest = runs_dir / label
    if dest.exists():
        if not force:
            raise FileExistsError("Run '%s' already exists (use force to overwrite)." % label)
        shutil.rmtree(str(dest))

    (dest / "Results").mkdir(parents=True)
    (dest / "Inputs").mkdir(parents=True)
    for f in (root / "Results").glob("*"):
        if f.is_file():
            shutil.copy2(str(f), str(dest / "Results" / f.name))
    for pattern in ("*.csv", "*.gdx"):
        for f in (root / "Inputs").glob(pattern):
            shutil.copy2(str(f), str(dest / "Inputs" / f.name))
    if (root / config.LST_FILE).exists():
        shutil.copy2(str(root / config.LST_FILE), str(dest / config.LST_FILE.name))

    meta = {
        "label": label,
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "objective": parse_objective(root / config.LST_FILE),
        "note": note,
    }
    (dest / "meta.json").write_text(json.dumps(meta, indent=2))
    return dest
