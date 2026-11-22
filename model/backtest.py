"""Backtest: predict past races the model has not seen, then score.

For each test race: fit every parameter on races strictly before it, export
the parameters with that race's actual starting grid, then (web/scripts/
backtest-sim.ts) simulate it and (score_backtest.py) compare with the result.

Leakage notes (documented in docs/backtest.md):
* The 2022/2026 reset decisions (validation V1/V2) are taken from the
  full-data fit instead of being re-tested before every race.
* Structural choices (filters, model form) were made while looking at all data.
Everything numeric (pace, wear, skill, rates, ...) uses only earlier races.

    .venv/bin/python model/backtest.py fit     # fits, about 45 s per race
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import fit_all as F  # noqa: E402

OUT = C.ROOT / "data" / "backtest"
SEASONS = {2025: 5, 2026: 4}     # first round tested per season: every team needs earlier races that season


def test_races(races: pd.DataFrame, tracks_before) -> pd.DataFrame:
    rows = []
    for _, r in races.sort_values(["Year", "Round"]).iterrows():
        if r.Year not in SEASONS or r.Round < SEASONS[r.Year]:
            continue
        if r.WetCompoundUsed or (r.Year, r.Round) in C.EXCLUDE_RACES:
            continue                         # dry races only: the scenario is "dry"
        rows.append(r)
    return pd.DataFrame(rows)


def fixed_breaks():
    g = json.loads((C.ROOT / "data" / "params" / "global.json").read_text())   # the full fit
    return {"breaks": g["validation"]["breaks_used"], "skill": g["validation"]["V1_2026"]["skill"]["decision"]}


def fit_all_tests(season: int | None = None, redo: bool = False):
    laps, res, races = C.load()
    fb = fixed_breaks()
    tests = test_races(races, None)
    if season:
        tests = tests[tests["Year"] == season]
    print(f"{len(tests)} dry test races", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for _, r in tests.iterrows():
        key = r.RaceKey
        dest = OUT / key / "params"
        if (dest / "meta.json").exists() and not redo:
            continue
        (OUT / key / "predictions.json").unlink(missing_ok=True)
        before = (races["Year"] < r.Year) | ((races["Year"] == r.Year) & (races["Round"] < r.Round))
        keys = set(races.loc[before, "RaceKey"])
        data = (laps[laps.RaceKey.isin(keys)].copy(), res[res.RaceKey.isin(keys)].copy(), races[before].copy())
        if not ((data[2]["CircuitId"] == r.CircuitId) & ~data[2]["WetCompoundUsed"]).any():
            print(f"  {key} {r.Event}: no earlier dry race at this circuit, skipped", flush=True)
            continue
        dest.mkdir(parents=True, exist_ok=True)
        C.PARAMS = dest
        t = time.time()
        try:
            F.main(target=int(r.Year), data=data, fixed_breaks=fb, grid_res=res[res.RaceKey == key], write_fits=False)
            (OUT / key / "race.json").write_text(json.dumps({"key": key, "track": r.CircuitId, "event": r.Event,
                                                            "year": int(r.Year), "round": int(r.Round)}))
            print(f"  {key} {r.Event}: fitted in {time.time() - t:.0f}s", flush=True)
        except Exception as exc:
            print(f"  {key} {r.Event}: FAILED {exc!r}", flush=True)
            (dest / "meta.json").unlink(missing_ok=True)


if __name__ == "__main__":
    # fit [season] [--redo]: season limits to one year; --redo refits races already done
    if sys.argv[1:2] == ["fit"]:
        args = sys.argv[2:]
        fit_all_tests(season=next((int(a) for a in args if a.isdigit()), None), redo="--redo" in args)
