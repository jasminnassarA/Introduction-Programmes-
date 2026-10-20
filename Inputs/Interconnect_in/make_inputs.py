"""Generate the input CSVs for models/Interconnectors.gms.

Run from the repo root:  python Inputs\\Interconnect_in\\make_inputs.py
Deterministic (seed 42), so re-running reproduces the committed CSVs.

Regions
  R1  existing case: demand(in).csv + normalisedloads.csv + Renewable_intermit.csv
  R2  wind-heavy, demand ~ R1 shifted 30 min + noise
  R3  hot country: very high solar with long sun hours, demand peaks evening/night
  R4  France-like: nuclear baseload, little wind/solar, lower demand
"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
INPUTS = os.path.dirname(HERE)
rng = np.random.RandomState(42)

REGIONS = ["R1", "R2", "R3", "R4"]
GENS = ["Solar", "Wind", "Coal", "Gas", "Nuclear"]

# ---------------------------------------------------------------- R1 data
d1 = pd.read_csv(os.path.join(INPUTS, "demand(in).csv"))
d1 = d1.iloc[:, 1].values.astype(float)
nl = pd.read_csv(os.path.join(INPUTS, "normalisedloads.csv"))
wind1 = nl["Wind"].values.astype(float)
solar1 = nl["Solar"].values.astype(float)
T = len(d1)
hour = np.arange(T) % 24          # hour of day 0..23 (Hour 1 = 00:00-01:00)


def shift30(x):
    """Shift a series by 30 minutes: average of this hour and the previous."""
    prev = np.concatenate(([x[0]], x[:-1]))
    return 0.5 * (x + prev)


def noise(n, pct):
    return 1.0 + pct * rng.randn(n)


def clip01(x):
    return np.clip(x, 0.0, 1.0)


# ---------------------------------------------------------------- demand
d2 = shift30(d1) * 1.0 * noise(T, 0.03)

# R3: night/evening peak (max ~22:00, min ~10:00), day-to-day variation from R1
daily_mean1 = pd.Series(d1).groupby(np.arange(T) // 24).transform("mean").values
day_scale = daily_mean1 / d1.mean()
shape3 = 1.0 + 0.25 * np.cos(2 * np.pi * (hour - 22) / 24.0)
d3 = 1.1 * d1.mean() * shape3 * day_scale * noise(T, 0.03)

d4 = 0.6 * d1 * noise(T, 0.03)

demand = pd.DataFrame({"Hour": np.arange(1, T + 1),
                       "R1": d1, "R2": d2, "R3": d3, "R4": d4}).round(4)
demand.to_csv(os.path.join(HERE, "demand.csv"), index=False)

# ---------------------------------------------------------------- load factors
# R3 solar: sunrise ~05:00, sunset ~20:00, peak ~0.9, broad curve
sun = np.clip(np.sin(np.pi * (hour + 0.5 - 5.0) / 15.0), 0, None) ** 0.7
solar3 = clip01(0.9 * sun * noise(T, 0.05))
solar3[sun == 0] = 0.0

lf = {
    "R1": {"Solar": solar1, "Wind": wind1},
    "R2": {"Solar": clip01(shift30(solar1) * noise(T, 0.05)),
           "Wind": clip01(shift30(wind1) * 1.2 * noise(T, 0.05))},
    "R3": {"Solar": solar3,
           "Wind": clip01(0.5 * wind1 * noise(T, 0.05))},
    "R4": {"Solar": clip01(solar1 * noise(T, 0.05)),
           "Wind": clip01(wind1 * noise(T, 0.05))},
}
rows = []
for r in REGIONS:
    df = pd.DataFrame({"Hour": np.arange(1, T + 1), "region": r})
    for g in GENS:
        df[g] = lf[r].get(g, np.ones(T))
    rows.append(df)
loadf = pd.concat(rows, ignore_index=True)
loadf[GENS] = loadf[GENS].round(4)
loadf.to_csv(os.path.join(HERE, "loadfactors.csv"), index=False)

# ---------------------------------------------------------------- generators
base = pd.read_csv(os.path.join(INPUTS, "Renewable_intermit.csv"))
base.columns = [c.strip() for c in base.columns]
base["gen"] = base["gen"].str.strip()
base = base.set_index("gen").astype(float)
base.loc["Nuclear"] = [5, 0, 0.33, 2, 0.05, 10]   # cost,cap,eff,vom,ramp_L,ramp_cost
base["min_L"] = 0.0
base.loc["Nuclear", "min_L"] = 0.6

caps = {  # MW
    "R1": {"Solar": 500, "Wind": 500, "Coal": 100, "Gas": 600, "Nuclear": 0},
    "R2": {"Solar": 200, "Wind": 1500, "Coal": 50, "Gas": 700, "Nuclear": 0},
    "R3": {"Solar": 1800, "Wind": 150, "Coal": 100, "Gas": 600, "Nuclear": 0},
    "R4": {"Solar": 100, "Wind": 100, "Coal": 0, "Gas": 150, "Nuclear": 450},
}
gen_rows = []
for r in REGIONS:
    for g in GENS:
        row = base.loc[g].to_dict()
        row["cap"] = caps[r][g]
        gen_rows.append(dict(region=r, gen=g, **row))
gens = pd.DataFrame(gen_rows)[["region", "gen", "cost", "cap", "eff", "vom",
                               "ramp_L", "ramp_cost", "min_L"]]
gens.to_csv(os.path.join(HERE, "generators.csv"), index=False)

# ---------------------------------------------------------------- interconnectors
links = []
for i, a in enumerate(REGIONS):
    for b in REGIONS[i + 1:]:
        loss = 0.035 if "R3" in (a, b) else 0.025
        for f, t in ((a, b), (b, a)):
            links.append({"from": f, "to": t, "cap": 200, "loss": loss, "cost": 0.5})
pd.DataFrame(links).to_csv(os.path.join(HERE, "interconnectors.csv"), index=False)

print("demand avg:", demand[REGIONS].mean().round(1).to_dict())
print("demand max:", demand[REGIONS].max().round(1).to_dict())
print("wrote CSVs to", HERE)
