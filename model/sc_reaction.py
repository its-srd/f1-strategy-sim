"""Who pits when a safety car or VSC comes out? (review section 3: A2 was a
hand rule, "pit if the planned stop is within max(3 laps, 35% of the
stint)").

For every SC and VSC deployment in a dry race since 2022, every car running
on the deployment lap is one observation: did it pit on that lap or the next
(the cheap stop)? A logistic regression on what a team knows at that moment:

  wear       tyre age / the stint cap for that compound at the track
  left       share of the race still to run
  owes       1 if the car has used only one dry compound (it still owes a
             compound change), else 0
  vsc        1 for a VSC (a shorter, less certain neutralisation)

The engine (web/src/engine/race.ts) draws each car's decision from these
probabilities when a neutralisation starts.

    .venv/bin/python model/sc_reaction.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

FROM_YEAR = 2022
FEATURES = ["wear", "left", "owes", "vsc"]


def observations(laps: pd.DataFrame, races: pd.DataFrame, dep: pd.DataFrame, caps: dict, track_key: dict) -> pd.DataFrame:
    dry = races[~races["WetCompoundUsed"] & (races["Year"] >= FROM_YEAR)].set_index("RaceKey")
    rows = []
    for r in dep[dep["type"].isin(["SC", "VSC"]) & dep["RaceKey"].isin(dry.index)].itertuples():
        L = int(r.lap)
        g = laps[laps.RaceKey == r.RaceKey]
        total = int(dry.loc[r.RaceKey, "TotalLaps"])
        if L >= total - 1 or L < 2:
            continue
        cap = caps.get(track_key.get(r.RaceKey, r.CircuitId), {})
        on = g[g.LapNumber == L]
        for c in on.itertuples():
            if c.Compound not in C.DRY or pd.isna(c.TyreLife) or c.PitOut:
                continue
            past = g[(g.Driver == c.Driver) & (g.LapNumber <= L)]
            used = set(past["Compound"].dropna()) & set(C.DRY)
            pitted = bool(g[(g.Driver == c.Driver) & g.LapNumber.isin([L, L + 1])]["PitIn"].any())
            rows.append({"RaceKey": r.RaceKey, "type": r.type, "lap": L, "driver": c.Driver, "pitted": pitted,
                         "wear": float(c.TyreLife) / cap.get(c.Compound, 35), "left": (total - L) / total,
                         "owes": float(len(used) < 2), "vsc": float(r.type == "VSC")})
    return pd.DataFrame(rows)


def fit(d: pd.DataFrame) -> dict:
    X = np.column_stack([np.ones(len(d))] + [d[f].values for f in FEATURES])
    y = d["pitted"].values.astype(float)
    def nll(b):
        z = X @ b
        return np.sum(np.logaddexp(0, z) - y * z)
    res = minimize(nll, np.zeros(X.shape[1]), method="BFGS")
    p = 1 / (1 + np.exp(-X @ res.x))
    H = (X * (p * (1 - p))[:, None]).T @ X
    se = np.sqrt(np.diag(np.linalg.inv(H)))
    names = ["intercept"] + FEATURES
    # Calibration by predicted-probability bins (in sample).
    bins = pd.cut(p, [0, .1, .25, .5, .75, 1.0001], right=False)
    cal = pd.DataFrame({"p": p, "y": y}).groupby(bins, observed=True).agg(n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean"))
    return {"coef": {n: {"beta": float(b), "se": float(s)} for n, b, s in zip(names, res.x, se)},
            "n_cars": int(len(d)), "n_deployments": int(d.groupby(["RaceKey", "lap"]).ngroups), "share_pitted": float(y.mean()),
            "calibration": [{"bin": str(k), "n": int(v.n), "predicted": float(v.predicted), "observed": float(v.observed)} for k, v in cal.iterrows()]}


def run(laps, races, dep, caps, track_key) -> dict:
    d = observations(laps, races, dep, caps, track_key)
    return fit(d) if len(d) >= 50 else {}


if __name__ == "__main__":
    import json
    import sim_inputs as SI
    import track_pace as T
    laps, res, races = C.load()
    rf = pd.read_csv(C.PROC / "fits" / "race_fits.csv")
    tk = dict(zip(rf.RaceKey, T.track_keys(rf)))
    caps = json.loads((C.ROOT / "data" / "params" / "tracks.json").read_text())
    caps = {k: (v.get("max_stint") or {}) for k, v in caps.items()}
    dep = pd.read_csv(C.PROC / "fits" / "deployments.csv")
    out = run(laps, races, dep, caps, tk)
    print(json.dumps({k: v for k, v in out.items() if k != "calibration"}, indent=1))
    for c in out["calibration"]:
        print(c)
