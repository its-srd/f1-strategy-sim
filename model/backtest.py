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
SEASONS = {2024: 4, 2025: 5, 2026: 4}   # first round tested per season: every team needs earlier races that season (2024: only for fitting the pace blend on as-of priors, never scored)


def test_races(races: pd.DataFrame) -> pd.DataFrame:
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
    tests = test_races(races)
    if season:
        tests = tests[tests["Year"] == season]
    print(f"{len(tests)} dry test races", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for _, r in tests.iterrows():
        key = r.RaceKey
        dest = OUT / key / "params"
        if (OUT / key / "race.json").exists() and (dest / "meta.json").exists() and not redo:
            continue                         # race.json is written only after a complete fit
        (OUT / key / "predictions.json").unlink(missing_ok=True)
        (OUT / key / "race.json").unlink(missing_ok=True)
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
            import traceback
            print(f"  {key} {r.Event}: FAILED {exc!r}\n{traceback.format_exc(limit=-3)}", flush=True)
            (dest / "meta.json").unlink(missing_ok=True)


# ------------------------------------------------------------------ wet races
WET_OUT = OUT / "wet"


def wet_races(races: pd.DataFrame) -> pd.DataFrame:
    """Wet races since 2022 (18-inch tyres) that can be tested: not a season
    opener (teams need earlier races that season) and an earlier dry race at
    the circuit exists (dry reference pace)."""
    rows = []
    for _, r in races[races.WetCompoundUsed & (races.Year >= 2022)].sort_values(["Year", "Round"]).iterrows():
        before = (races.Year < r.Year) | ((races.Year == r.Year) & (races.Round < r.Round))
        if r.Round < 3 or not ((races.CircuitId == r.CircuitId) & ~races.WetCompoundUsed & before).any():
            continue
        rows.append(r)
    return pd.DataFrame(rows)


def wet_trace(race_laps: pd.DataFrame, track: dict) -> dict:
    """The race's real conditions, lap by lap: the best tyre family's median
    green-lap time divided by the dry reference (base + fuel terms from the
    as-of fit). This is the "best-tyre ratio" the wet model is built on.
    Neutralised laps carry the previous value. Also the real switch laps:
    first lap with a majority on wet tyres, and the first lap after that with
    a majority back on slicks."""
    pc = track["pace"]
    base, f1, f2 = track["base_lap"]["base_s"], pc["fuel"]["mean_s"], pc["fuel2"]["mean_s"]
    # Same lap filter as the wet model (model/wet.py lap_table): green laps,
    # not the first lap, no pit laps, not the lap after a neutralisation.
    rl = race_laps.sort_values(["Driver", "LapNumber"])
    prev = rl.groupby("Driver")["TrackStatus"].shift(1).fillna("1")
    ok = (rl.LapNumber > 1) & ~rl.IsGhostLap & rl.LapTimeS.notna() & ~rl.PitIn & ~rl.PitOut \
        & (rl.TrackStatus.fillna("") == "1") & ~prev.str.contains("[4567]", regex=True)
    green = rl[ok].copy()
    green["fam"] = green["Compound"].where(green["Compound"].isin(["INTERMEDIATE", "WET"]), "SLICK")
    med = green.groupby(["LapNumber", "fam"])["LapTimeS"].median().unstack()
    n = int(race_laps.LapNumber.max())
    best, last = [], None
    for lap in range(1, n + 1):
        if lap in med.index and med.loc[lap].notna().any():
            ref = base + f1 * lap + f2 * lap * lap
            last = float(med.loc[lap].min() / ref)
        best.append(last)
    first = next((v for v in best if v is not None), 1.0)
    best = [first if v is None else v for v in best]
    share = race_laps[~race_laps.IsGhostLap].groupby("LapNumber")["IsWetCompound"].mean()
    wet_laps = share.index[share >= 0.5]
    onto = int(wet_laps.min()) if len(wet_laps) else None
    back = None
    if onto is not None:
        after = share[(share.index > onto) & (share < 0.5)]
        back = int(after.index.min()) if len(after) else None
    started = bool(share.iloc[0] >= 0.5)
    # The rain window a user would enter: the main spell of rain falling
    # (weather station flag, as in model/wet.py; gaps of up to 2 laps joined).
    # The model dries the track after the window by itself, so the window
    # must end when the rain stops, not when cars go back to slicks. A race
    # that started on wet tyres starts the window on lap 1; with no rain
    # falling early on, the track was wet from earlier rain: window [1, 1].
    rain = race_laps.groupby("LapNumber")["Rainfall"].mean() > 0.5
    laps_r = sorted(int(x) for x in rain.index[rain])
    spells = []
    for lap in laps_r:
        if spells and lap - spells[-1][1] <= 3:
            spells[-1][1] = lap
        else:
            spells.append([lap, lap])
    if started:
        early = [s for s in spells if s[0] <= 3]
        window = [1, early[0][1]] if early else [1, 1]
    else:
        window = spells[0] if spells else None
    # Real stops per classified finisher and swaps between inters and wets
    # (a stint = consecutive laps on one compound).
    st = race_laps[~race_laps.IsGhostLap].sort_values(["Driver", "LapNumber"])
    seq = st.groupby(["Driver", "Stint"])["Compound"].agg(lambda s: s.mode().iloc[0] if s.notna().any() else None)
    finishers = set(race_laps.loc[race_laps.LapNumber == race_laps.LapNumber.max(), "Driver"])
    n_stops = n_swaps = n_cars = 0
    for drv, comps in seq.groupby(level=0):
        if drv not in finishers:
            continue
        c = [x for x in comps.tolist() if x]
        n_cars += 1
        n_stops += len(comps) - 1
        n_swaps += sum({a, b} == {"INTERMEDIATE", "WET"} for a, b in zip(c, c[1:]))
    return {"best_ratio": best, "real_onto_wet_lap": onto, "real_back_to_slicks_lap": back,
            "started_on_wet": started, "window": window,
            "real_stops_per_finisher": n_stops / max(n_cars, 1), "real_inter_wet_swaps_per_finisher": n_swaps / max(n_cars, 1)}


def fit_wet_tests():
    laps, res, races = C.load()
    fb = fixed_breaks()
    tests = wet_races(races)
    print(f"{len(tests)} wet test races", flush=True)
    for _, r in tests.iterrows():
        key = r.RaceKey
        dest = WET_OUT / key / "params"
        if (dest / "meta.json").exists() and (WET_OUT / key / "race.json").exists():
            continue
        before = (races["Year"] < r.Year) | ((races["Year"] == r.Year) & (races["Round"] < r.Round))
        keys = set(races.loc[before, "RaceKey"])
        data = (laps[laps.RaceKey.isin(keys)].copy(), res[res.RaceKey.isin(keys)].copy(), races[before].copy())
        dest.mkdir(parents=True, exist_ok=True)
        C.PARAMS = dest
        t = time.time()
        try:
            F.main(target=int(r.Year), data=data, fixed_breaks=fb, grid_res=res[res.RaceKey == key], write_fits=False)
            track = json.loads((dest / "tracks.json").read_text())[r.CircuitId]
            tr = wet_trace(laps[laps.RaceKey == key], track)
            (WET_OUT / key / "race.json").write_text(json.dumps({"key": key, "track": r.CircuitId, "event": r.Event,
                "year": int(r.Year), "round": int(r.Round), **tr}))
            print(f"  {key} {r.Event}: fitted in {time.time() - t:.0f}s; real switch onto wet lap {tr['real_onto_wet_lap']}, back {tr['real_back_to_slicks_lap']}", flush=True)
        except Exception as exc:
            import traceback
            print(f"  {key} {r.Event}: FAILED {exc!r}\n{traceback.format_exc(limit=-3)}", flush=True)
            (dest / "meta.json").unlink(missing_ok=True)


def refresh_wet_races():
    """Rewrite race.json for fitted wet tests and refresh the W10 switch
    timing in their parameters (measured on earlier races only), no refit."""
    import wet_switch as WS
    laps, res, races = C.load()
    for d in sorted(WET_OUT.glob("20*_*")):
        if not (d / "params" / "tracks.json").exists():
            continue
        r = races[races.RaceKey == d.name].iloc[0]
        track = json.loads((d / "params" / "tracks.json").read_text())[r.CircuitId]
        tr = wet_trace(laps[laps.RaceKey == d.name], track)
        before = (races.Year < r.Year) | ((races.Year == r.Year) & (races.Round < r.Round))
        gp = d / "params" / "global.json"
        g = json.loads(gp.read_text())
        g["wet"]["switch_timing"] = WS.run(laps[laps.RaceKey.isin(set(races.loc[before, "RaceKey"]))], races[before])
        gp.write_text(json.dumps(C._clean(g)))
        (d / "race.json").write_text(json.dumps({"key": d.name, "track": r.CircuitId, "event": r.Event,
            "year": int(r.Year), "round": int(r.Round), **tr}))
        print(d.name, r.Event, "window", tr["window"], "onto", tr["real_onto_wet_lap"], "back", tr["real_back_to_slicks_lap"])


if __name__ == "__main__":
    if sys.argv[1:2] == ["wet"]:
        fit_wet_tests()
    elif sys.argv[1:2] == ["wet-races"]:
        refresh_wet_races()
    # fit [season] [--redo]: season limits to one year; --redo refits races already done
    if sys.argv[1:2] == ["fit"]:
        args = sys.argv[2:]
        fit_all_tests(season=next((int(a) for a in args if a.isdigit()), None), redo="--redo" in args)
