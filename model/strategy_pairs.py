"""Strategy check, part 1: teammates who ran different strategies.

Same car, same race, different plans is the closest real-world test of the
simulator's "what if" advice. For every backtest race this finds teammate
pairs where both finished, neither had a stint of 2 laps or less (damage),
and their compound sequences or stop counts differ. It writes each pair's
actual stints and finishing times; web/scripts/strategy-check.ts then asks
the engine what the strategy difference alone should be worth.

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


def stints(laps: pd.DataFrame) -> list[dict]:
    """Stints of one driver in one race, from the lap table."""
    g = laps[~laps["IsGhostLap"]].sort_values("LapNumber")
    out = []
    for _, s in g.groupby("Stint", sort=True):
        out.append({"compound": s["Compound"].mode().iloc[0] if s["Compound"].notna().any() else None,
                    "laps": int(s["LapNumber"].max() - s["LapNumber"].min() + 1)})
    return out


def main():
    laps, res, races = C.load()
    pairs = []
    for d in sorted(OUT.glob("20*_*")):
        if not (d / "predictions.json").exists():
            continue
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
            if not ok or [s["compound"] for s in sa] == [s["compound"] for s in sb] and len(sa) == len(sb):
                continue
            pairs.append({"race": key, "team": team,
                          "a": {"driver": a.DriverId, "grid": int(a.GridPosition), "time": a.RaceTimeS, "pos": int(a.Position), "stints": sa},
                          "b": {"driver": b.DriverId, "grid": int(b.GridPosition), "time": b.RaceTimeS, "pos": int(b.Position), "stints": sb}})
    (OUT / "strategy_pairs.json").write_text(json.dumps(pairs, indent=1))
    print(f"{len(pairs)} teammate pairs with different strategies "
          f"({sum(p['race'].startswith('2025') for p in pairs)} in 2025, {sum(p['race'].startswith('2026') for p in pairs)} in 2026)")


if __name__ == "__main__":
    main()
