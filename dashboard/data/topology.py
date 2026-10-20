"""Guessed network layout for the Nodal page - ILLUSTRATIVE ONLY.

The inputs contain no from/to bus list and no coordinates, so:
  * line ends are estimated from the shift factor matrix (PTDF):
      from = node with the largest shift factor, to = node with the most negative one;
      no negative value -> to = reference bus (all-zero PTDF column, e.g. 1483);
      radial line (one non-zero entry) -> to = node with the most similar PTDF column.
  * node positions come from a seeded force-directed layout (numpy, deterministic).
A real Inputs\\Nodes_in\\lines(in).csv (LINE_ID,FROM,TO) replaces the guessed line ends.
The guess is cached in Inputs\\Nodes_in\\lines_guess.csv and layout_guess.csv.
"""
from pathlib import Path

import numpy as np
import pandas as pd

EMPTY_MW = 0.1
GREEN_MAX, YELLOW_MAX = 50.0, 90.0
CLASSES = ["empty", "unlimited", "low", "medium", "high"]
CLASS_COLOURS = {"empty": "#c8c8c8", "unlimited": "#1f77b4", "low": "#2ca02c",
                 "medium": "#f2c200", "high": "#d62728"}
CLASS_LABELS = {"empty": "Empty (< 0.1 MW)", "unlimited": "Unlimited line (inf) with flow",
                "low": "< 50% of rating", "medium": "50-90% of rating", "high": ">= 90% of rating"}


def line_class(flow, rating):
    """Colour class of a line in one hour."""
    if abs(flow) < EMPTY_MW:
        return "empty"
    if not np.isfinite(rating) or rating <= 0:
        return "unlimited"
    pct = abs(flow) / rating * 100
    return "low" if pct < GREEN_MAX else "medium" if pct < YELLOW_MAX else "high"


def guess_line_ends(ptdf, nodes):
    """ptdf: long df [l, n, Value]; nodes: all node names. Returns df [l, from, to]."""
    mat = ptdf.pivot_table(index="l", columns="n", values="Value", aggfunc="sum")
    mat = mat.reindex(columns=sorted(set(nodes) | set(mat.columns))).fillna(0.0)
    zero_cols = [n for n in mat.columns if (mat[n].abs() < 1e-12).all()]
    ref = zero_cols[0] if zero_cols else mat.columns[0]
    cols = mat.values.T  # node x line
    names = list(mat.columns)
    rows = []
    for l, r in mat.iterrows():
        fr = r.idxmax()
        if r.min() < -1e-9:
            to = r.idxmin()
        elif (r.abs() > 1e-9).sum() == 1:  # radial: nearest node by PTDF column
            i = names.index(fr)
            d = np.abs(cols - cols[i]).sum(axis=1)
            d[i] = np.inf
            to = names[int(np.argmin(d))]
        else:
            to = ref
        if to == fr:
            to = ref if fr != ref else names[0]
        rows.append((l, fr, to))
    return pd.DataFrame(rows, columns=["l", "from", "to"])


def force_layout(nodes, edges, iterations=300, seed=7):
    """Fruchterman-Reingold layout. Returns df [n, x, y] scaled to [0, 1]."""
    nodes = list(nodes)
    idx = {n: i for i, n in enumerate(nodes)}
    n = len(nodes)
    rng = np.random.RandomState(seed)
    pos = rng.rand(n, 2)
    e = np.array([(idx[a], idx[b]) for a, b in edges if a in idx and b in idx and a != b], dtype=int).reshape(-1, 2)
    k = np.sqrt(1.0 / max(n, 1))
    t = 0.1
    for _ in range(iterations):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.sqrt((delta ** 2).sum(-1)) + 1e-9
        disp = (delta * (k * k / dist ** 2)[..., None]).sum(1)
        if len(e):
            d = pos[e[:, 0]] - pos[e[:, 1]]
            dl = np.sqrt((d ** 2).sum(-1))[:, None] + 1e-9
            f = d * dl / k
            np.add.at(disp, e[:, 0], -f)
            np.add.at(disp, e[:, 1], f)
        length = np.sqrt((disp ** 2).sum(-1))[:, None] + 1e-9
        pos += disp / length * np.minimum(length, t)
        t = max(t * 0.985, 0.002)
    return pd.DataFrame({"n": nodes, "x": pos[:, 0], "y": pos[:, 1]})


def spread_even(pos):
    """Keep each node's direction from the centre but re-space radii by rank so the nodes fill a
    disc evenly (no dense core, no empty rim). Result scaled to [0, 1]."""
    p = pos[["x", "y"]].values.astype(float)
    c = np.median(p, axis=0)
    d = p - c
    ang = np.arctan2(d[:, 1], d[:, 0])
    r = np.sqrt((d ** 2).sum(1))
    ranks = r.argsort().argsort()
    n = max(len(p), 1)
    rr = np.sqrt((ranks + 0.5) / n)            # equal-area rings
    out = np.column_stack([rr * np.cos(ang), rr * np.sin(ang)]) * 0.5 + 0.5
    return pd.DataFrame({"n": pos["n"].values, "x": out[:, 0], "y": out[:, 1]})


def spurs(ptdf, lines, nodes):
    """Nodes that are not an end of any line -> the line where |SF| is largest.
    df [n, l, sf]. Nodes with an all-zero column (reference bus) get no spur."""
    linked = set(lines["from"]) | set(lines["to"])
    p = ptdf[ptdf["n"].isin(set(nodes) - linked) & (ptdf["Value"].abs() > 1e-9)]
    p = p[p["l"].isin(set(lines["l"]))]
    if p.empty:
        return pd.DataFrame(columns=["n", "l", "sf"])
    best = p.loc[p["Value"].abs().groupby(p["n"]).idxmax()]
    return best.rename(columns={"Value": "sf"})[["n", "l", "sf"]].reset_index(drop=True)


def top_lines(ptdf, node, k=5, threshold=0.0):
    """Lines most influenced by node: df [l, sf] sorted by |sf| (k=None -> all above threshold)."""
    p = ptdf[(ptdf["n"] == node) & (ptdf["Value"].abs() >= max(threshold, 1e-9))]
    p = p.reindex(p["Value"].abs().sort_values(ascending=False).index)
    p = p.rename(columns={"Value": "sf"})[["l", "sf"]]
    return p if k is None else p.head(k)


def get_topology(ptdf, nodes, cache_dir=None):
    """{"lines", "pos", "spurs", "guessed"}; line ends and layout cached as csv in cache_dir."""
    nodes = sorted(set(nodes))
    real = Path(cache_dir) / "lines(in).csv" if cache_dir else None
    lines_csv = Path(cache_dir) / "lines_guess.csv" if cache_dir else None
    pos_csv = Path(cache_dir) / "layout_guess.csv" if cache_dir else None
    guessed = True
    lines = None
    if real is not None and real.exists():
        df = pd.read_csv(real, dtype=str)
        df.columns = [c.strip().upper() for c in df.columns]
        lines = df.rename(columns={"LINE_ID": "l", "FROM": "from", "TO": "to"})[["l", "from", "to"]]
        guessed = False
    elif lines_csv is not None and lines_csv.exists():
        lines = pd.read_csv(lines_csv, dtype=str)
    if lines is None:
        lines = guess_line_ends(ptdf, nodes)
        if lines_csv is not None:
            lines.to_csv(lines_csv, index=False)
    sp = spurs(ptdf, lines, nodes) if ptdf is not None else pd.DataFrame(columns=["n", "l", "sf"])
    pos = None
    if pos_csv is not None and pos_csv.exists():
        pos = pd.read_csv(pos_csv, dtype={"n": str})
        if set(pos["n"]) != set(nodes) or "v" not in pos or (pos["v"] != LAYOUT_VERSION).any():
            pos = None
    if pos is None:
        ends = lines.set_index("l")
        edges = list(zip(lines["from"], lines["to"]))
        # spur nodes are pulled towards both ends of the line they influence most
        edges += [(n, ends.at[l, e]) for n, l in zip(sp["n"], sp["l"]) if l in ends.index for e in ("from", "to")]
        pos = spread_even(force_layout(nodes, edges, iterations=400))
        pos["v"] = LAYOUT_VERSION
        if pos_csv is not None:
            pos.to_csv(pos_csv, index=False)
    return {"lines": lines, "pos": pos[["n", "x", "y"]], "spurs": sp, "guessed": guessed}


LAYOUT_VERSION = 2  # bump to force layout_guess.csv to be recomputed
