"""Strategy check, part 1: teammates who ran different strategies.

Same car, same race, different plans is the closest real-world test of the
simulator's "what if" advice. For every backtest race this finds teammate
pairs where both finished on the lead lap, neither had a stint of 2 laps or
less (damage), and their plans differ: other compounds or stop count, or the
same compounds with stops at least MIN_STOP_SHIFT laps apart (the cleanest
test of stop timing, review 4.6).

Each pair also carries what the review asked for (section 4):
* reactive: a stop of either driver was made under SC/VSC/red flag, so the
  real plan was partly a reaction; scored separately from clean pairs
* status: the race's real track status per lap, so the engine can replay
  the real neutralisations instead of random ones
* oracle: the tyre parameters this race actually showed (its own stage A
  fit), for the oracle run that tells a tyre-forecast problem from a
  problem in the race mechanics

web/scripts/strategy-check.ts simulates the pairs; model/score_strategy.py
scores them.

    .venv/bin/python model/strategy_pairs.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

OUT = C.ROOT / "data" / "backtest"
FINISHED = r"^(Finished|Lapped|\+\d+ Laps?)$"
MIN_STOP_SHIFT = 3
GREEN, SC, VSC, RED = 0, 1, 2, 3          # engine status codes (web/src/engine/race.ts)
ORACLE = ["offset_SOFT", "offset_HARD", "slope_SOFT", "slope_MEDIUM", "slope_HARD", "curve"]


def stints(laps: pd.DataFrame) -> list[dict]:
    """Stints of one driver in one race, from the lap table, with the track
    status of the stint's last lap (the in-lap of the stop that ends it)."""
    g = laps[~laps["IsGhostLap"]].sort_values("LapNumber")
    out = []
    for _, s in g.groupby("Stint", sort=True):
        out.append({"compound": s["Compound"].mode().iloc[0] if s["Compound"].notna().any() else None,
                    "laps": int(s["LapNumber"].max() - s["LapNumber"].min() + 1),
                    "end_status": str(s["TrackStatus"].iloc[-1])})
    return out


def stop_laps(st: list[dict]) -> list[int]:
    return [sum(x["laps"] for x in st[:i + 1]) for i in range(len(st) - 1)]


def status_trace(dep: pd.DataFrame, key: str, total: int) -> list[int]:
    """Real track status per lap, coded like the engine: a red flag is its
    lap plus one SC restart lap (assumption R3)."""
    st = [GREEN] * total
    for r in dep[dep.RaceKey == key].sort_values("lap").itertuples():
        lap = int(r.lap)
        if r.type == "RED":
            if 1 <= lap <= total:
                st[lap - 1] = RED
            if lap + 1 <= total and st[lap] == GREEN:
                st[lap] = SC
            continue
        code = SC if r.type == "SC" else VSC
        for L in range(lap, min(total, lap + int(max(1, r.duration_laps)) - 1) + 1):
            if st[L - 1] == GREEN:
                st[L - 1] = code
    return st


def oracle(rf: pd.DataFrame, key: str) -> dict:
    """The race's own tyre parameters (seconds) and their standard errors;
    offsets only when MEDIUM was the reference compound."""
    if key not in rf.index:
        return {}
    r = rf.loc[key]
    out = {}
    for p in ORACLE:
        if pd.isna(r[p]) or (p.startswith("offset_") and r["ref_compound"] != "MEDIUM"):
            continue
        out[p] = {"mean_s": float(r[p]), "sd_s": float(r[p + "_se"])}
    return out


def main():
    laps, res, races = C.load()
    dep = pd.read_csv(C.PROC / "fits" / "deployments.csv")
    rf = pd.read_csv(C.PROC / "fits" / "race_fits.csv").set_index("RaceKey")
    pairs = []
    for d in sorted(OUT.glob("20*_*")):
        if not (d / "race.json").exists() or d.name[:4] not in ("2025", "2026"):
            continue                           # practice and exam races only
        key = d.name
        r = res[(res.RaceKey == key) & res["Status"].astype(str).str.match(FINISHED)]
        race_laps = laps[laps.RaceKey == key]
        total = int(races.loc[races.RaceKey == key, "TotalLaps"].iloc[0])
        for team, g in r.groupby("TeamId"):
            if len(g) != 2:
                continue
            a, b = g.sort_values("Position").itertuples()
            if a.Laps != total or b.Laps != total:
                continue                       # both on the lead lap, so race times compare
            sa = stints(race_laps[race_laps.Driver == a.Abbreviation])
            sb = stints(race_laps[race_laps.Driver == b.Abbreviation])
            ok = all(s["compound"] in C.DRY and s["laps"] > 2 for s in sa + sb)
            if not ok:
                continue
            same_plan = [s["compound"] for s in sa] == [s["compound"] for s in sb]
            if same_plan:
                if len(sa) == 1:
                    continue                   # both no-stop on the same tyre: nothing to test
                shift = max(abs(x - y) for x, y in zip(stop_laps(sa), stop_laps(sb)))
                if shift < MIN_STOP_SHIFT:
                    continue
            reactive = any(any(c in s["end_status"] for c in "4567") for s in (sa[:-1] + sb[:-1]))
            pairs.append({"race": key, "team": team, "kind": "stop_timing" if same_plan else "plan",
                          "reactive": bool(reactive), "status": status_trace(dep, key, total), "oracle": oracle(rf, key),
                          "a": {"driver": a.DriverId, "grid": int(a.GridPosition), "time": a.RaceTimeS, "pos": int(a.Position), "stints": sa},
                          "b": {"driver": b.DriverId, "grid": int(b.GridPosition), "time": b.RaceTimeS, "pos": int(b.Position), "stints": sb}})
    (OUT / "strategy_pairs.json").write_text(json.dumps(pairs, indent=1))
    for y in ("2025", "2026"):
        ps = [p for p in pairs if p["race"].startswith(y)]
        print(f"{y}: {len(ps)} teammate pairs ({sum(p['kind'] == 'stop_timing' for p in ps)} same compounds, other stop laps; "
              f"{sum(p['reactive'] for p in ps)} with a stop under SC/VSC/red) in {len({p['race'] for p in ps})} races")


if __name__ == "__main__":
    main()
