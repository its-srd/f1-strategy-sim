"""When each team switches tyres in changing conditions (W10).

For every real transition (the field going onto wet tyres, or back to
slicks), each driver's switch lap is compared with the field's median switch
lap. The spread of those offsets is what the simulation gives rival teams, so
the field does not all switch on the same lap. Also measured: did drivers who
switched earlier than the field gain places over the transition? That is the
only real-world check available for the site's wet-weather call.

    .venv/bin/python model/wet_switch.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

WINDOW = 8          # laps either side of the field's crossing lap
MIN_SWITCHERS = 6   # a transition needs at least this many drivers switching
MAX_OFFSET = 5      # offsets beyond this are reactive (damage, SC), not timing calls


def transitions(race_laps: pd.DataFrame) -> list[dict]:
    """Field-level transitions: laps where the share on wet tyres crosses 50%."""
    rl = race_laps[~race_laps.IsGhostLap]
    share = rl.groupby("LapNumber")["IsWetCompound"].mean()
    out, wet = [], share.iloc[0] >= 0.5
    for lap, s in share.items():
        if not wet and s >= 0.5:
            out.append({"lap": int(lap), "to_wet": True}); wet = True
        elif wet and s < 0.5:
            out.append({"lap": int(lap), "to_wet": False}); wet = False
    return out


def switch_rows(race_laps: pd.DataFrame, key: str) -> list[dict]:
    rows = []
    rl = race_laps[~race_laps.IsGhostLap].sort_values(["Driver", "LapNumber"])
    pos = rl.pivot_table(index="Driver", columns="LapNumber", values="Position", aggfunc="first")
    for tr in transitions(race_laps):
        lo, hi = tr["lap"] - WINDOW, tr["lap"] + WINDOW
        sw = {}
        for drv, g in rl[(rl.LapNumber >= lo - 1) & (rl.LapNumber <= hi)].groupby("Driver"):
            fam = g["IsWetCompound"].astype(bool).values
            laps = g["LapNumber"].values
            for j in range(1, len(fam)):
                if fam[j - 1] != fam[j] and fam[j] == tr["to_wet"]:
                    sw[drv] = int(laps[j - 1])          # in-lap: last lap on the old family
                    break
        if len(sw) < MIN_SWITCHERS:
            continue
        med = float(np.median(list(sw.values())))
        first, last = min(sw.values()), max(sw.values())
        for drv, lap in sw.items():
            before = pos.loc[drv].get(first - 1) if drv in pos.index else None
            after = pos.loc[drv].get(last + 2) if drv in pos.index else None
            rows.append({"race": key, "to_wet": tr["to_wet"], "driver": drv, "offset": lap - med,
                         "gain": (before - after) if before is not None and after is not None
                         and not (np.isnan(before) or np.isnan(after)) else np.nan})
    return rows


def run(laps: pd.DataFrame, races: pd.DataFrame) -> dict:
    rows = []
    for key in races.loc[races.WetCompoundUsed, "RaceKey"]:
        rows += switch_rows(laps[laps.RaceKey == key], key)
    df = pd.DataFrame(rows)
    if df.empty:
        return {"n_transitions": 0}
    df = df[df.offset.abs() <= MAX_OFFSET]
    off = np.round(df.offset).astype(int)
    hist = off.value_counts().sort_index()
    # Places gained vs switch offset (negative offset = earlier than the field).
    d = df.dropna(subset=["gain"])
    slope, ci = np.nan, [np.nan, np.nan]
    if len(d) >= 20:
        def fit(x):
            return np.polyfit(x.offset, x.gain, 1)[0]
        slope = float(fit(d))
        keys = d.race.unique()
        rng = np.random.default_rng(0)
        bs = [fit(pd.concat([d[d.race == k] for k in rng.choice(keys, len(keys))])) for _ in range(1000)]
        ci = np.percentile(bs, [2.5, 97.5]).tolist()
    return {"offsets": {int(k): int(v) for k, v in hist.items()},
            "offset_sd_laps": float(df.offset.std()),
            "n_transitions": int(df.groupby(["race", "to_wet"]).ngroups), "n_races": int(df.race.nunique()),
            "n_driver_switches": int(len(df)),
            "places_gained_per_lap_later": slope, "places_gained_per_lap_later_ci95": ci,
            "n_with_positions": int(len(d))}


if __name__ == "__main__":
    laps, res, races = C.load()
    import json
    print(json.dumps(run(laps, races), indent=1))
