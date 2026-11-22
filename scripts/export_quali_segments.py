"""Qualifying times per segment (Q1, Q2, Q3) from Jolpica-F1, per season.

The model's qualifying gap (assumption I4) used each driver's best lap of
the whole session. Drivers knocked out in Q1 set it on a slower, greener
track than those in Q3, so their gap is inflated (review 2.4). This saves
the segment times so model/calibrate_pace.py can test segment-aware gaps.

    .venv/bin/python scripts/export_quali_segments.py
Writes data/raw/<year>/quali_segments.csv; seasons already saved are
skipped, except the current one, which is refreshed.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone

import pandas as pd

from export_races import RAW_DIR, get

JOLPICA = "https://api.jolpi.ca/ergast/f1"
PAUSE_S = 1.0
PAGE = 100


def to_s(t: str | None) -> float | None:
    if not t:
        return None
    m, _, s = t.rpartition(":")
    try:
        return (int(m) * 60 if m else 0) + float(s)
    except ValueError:
        return None


def season(year: int) -> pd.DataFrame:
    rows, offset = [], 0
    while True:
        r = get(f"{JOLPICA}/{year}/qualifying.json?limit={PAGE}&offset={offset}")
        data = r.json()["MRData"]
        for race in data["RaceTable"]["Races"]:
            for q in race.get("QualifyingResults", []):
                rows.append({"Year": year, "Round": int(race["round"]), "DriverId": q["Driver"]["driverId"],
                             "Abbreviation": q["Driver"].get("code"), "QualiPos": int(q["position"]),
                             "Q1": to_s(q.get("Q1")), "Q2": to_s(q.get("Q2")), "Q3": to_s(q.get("Q3"))})
        offset += PAGE
        time.sleep(PAUSE_S)
        if offset >= int(data["total"]):
            return pd.DataFrame(rows)


def main() -> int:
    now = datetime.now(timezone.utc).year
    for ydir in sorted(p for p in RAW_DIR.iterdir() if p.is_dir() and p.name.isdigit()):
        out = ydir / "quali_segments.csv"
        if out.exists() and int(ydir.name) < now:
            continue
        df = season(int(ydir.name))
        df.to_csv(out, index=False)
        print(f"  {ydir.name}: {len(df)} qualifying results in {df['Round'].nunique() if len(df) else 0} rounds", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
