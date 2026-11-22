"""How well do the as-of tyre parameters forecast the race that follows?

For every backtest race (data/backtest/<race>/params, fitted on earlier
races only) the track's forecast of each tyre parameter, and the pooled
cross-track mean from the same fit, are compared with the value that race
then showed (its own stage A fit, data/processed/fits/race_fits.csv). All in
percent of the base lap time. "Noise" is the root mean square of the
realised value's own standard error: no forecast can beat it on average.
A standing metric for any change to the tyre model (review 2.2).

    .venv/bin/python model/param_forecast_check.py [tag]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

BT = C.ROOT / "data" / "backtest"
GROUPS = {"offsets": ["offset_SOFT", "offset_HARD"], "wear slopes": ["slope_SOFT", "slope_MEDIUM", "slope_HARD"],
          "curve": ["curve"]}


def rows() -> pd.DataFrame:
    rf = pd.read_csv(C.PROC / "fits" / "race_fits.csv").set_index("RaceKey")
    out = []
    for d in sorted(BT.glob("20*_*")):
        if not (d / "params" / "tracks.json").exists() or not (d / "race.json").exists():
            continue
        race = json.loads((d / "race.json").read_text())
        if race["key"] not in rf.index:
            continue
        real = rf.loc[race["key"]]
        tr = json.loads((d / "params" / "tracks.json").read_text()).get(race["track"], {}).get("pace", {})
        pool = json.loads((d / "params" / "global.json").read_text())["pooled"]["pace"]
        for p in sum(GROUPS.values(), []):
            if p not in tr or pd.isna(real[p]) or (p.startswith("offset_") and real["ref_compound"] != "MEDIUM"):
                continue
            out.append({"race": race["key"], "year": race["year"], "param": p,
                        "real": 100 * real[p] / real["base_s"], "se": 100 * real[p + "_se"] / real["base_s"],
                        "track": tr[p]["mean"], "track_sd": tr[p]["sd"], "source": tr[p].get("source"),
                        "pool": pool[p]["mean_pct"]})
    return pd.DataFrame(out)


def table(df: pd.DataFrame) -> pd.DataFrame:
    res = []
    for (year, grp), g in df.assign(grp=df.param.map({p: k for k, ps in GROUPS.items() for p in ps})).groupby(["year", "grp"]):
        rm = lambda e: float(np.sqrt(np.mean(e ** 2)))
        res.append({"year": year, "params": grp, "n": len(g), "rmse_track": rm(g.real - g.track), "rmse_pool": rm(g.real - g.pool),
                    "noise": rm(g.se), "coverage_2sd": float(((g.real - g.track).abs() <= 2 * np.sqrt(g.track_sd ** 2 + g.se ** 2)).mean())})
    # The race's overall wear level (mean slope over its compounds) decides one stop or two.
    s = df[df.param.str.startswith("slope_")].groupby(["year", "race"])[["real", "track", "pool"]].mean().reset_index()
    for year, g in s.groupby("year"):
        res.append({"year": year, "params": "race-mean wear", "n": len(g), "rmse_track": float(np.sqrt(np.mean((g.real - g.track) ** 2))),
                    "rmse_pool": float(np.sqrt(np.mean((g.real - g.pool) ** 2))), "noise": np.nan, "coverage_2sd": np.nan})
    return pd.DataFrame(res)


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "current"
    t = table(rows())
    print(t.round(3).to_string(index=False))
    (BT / f"param_forecast_{tag}.json").write_text(json.dumps(C._clean(t.to_dict("records")), indent=1))
