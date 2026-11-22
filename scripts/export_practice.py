"""Export the weekend's long-run sessions (review 2.2: the only information
before a race about that weekend's tyre wear).

For every exported race since 2022 (18-inch tyres) this downloads, from the
same TracingInsights commit as the race laps:
  * Practice 2 on a normal weekend (the long-run session), and
  * Practice 1 and the Sprint on a sprint weekend (no Practice 2 there; the
    sprint is a short race on the same tyres).
Each session is saved as data/raw/<year>/<race>_<session>.csv with the same
lap columns as the race export. Resumable: files already saved are skipped.

    .venv/bin/python scripts/export_practice.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

from export_races import RAW_DIR, TI_RAW, build_laps, get

PAUSE_S = 1.0
FIRST_YEAR = 2022
SESSIONS = {"Practice 2": "fp2", "Practice 1": "fp1", "Sprint": "sprint"}
COLS = ["Year", "Round", "Event", "CircuitId", "Driver", "DriverNumber", "Team", "LapNumber", "LapTimeS",
        "Compound", "TyreLife", "Stint", "FreshTyre", "PitIn", "PitOut", "TrackStatus", "Deleted",
        "IsAccurate", "LapStartSessionTimeS", "TrackTemp", "Rainfall"]


def fetch(meta: dict, ref: str, session: str):
    url = TI_RAW.format(year=meta["year"], ref=ref, path=f"{quote(meta['ti_folder'])}/{quote(session)}/session_laptimes.json")
    r = get(url, ok404=True)
    time.sleep(PAUSE_S)
    return r


def main() -> int:
    done = skipped = missing = 0
    for meta_path in sorted(RAW_DIR.glob("*/*_meta.json")):
        meta = json.loads(meta_path.read_text())
        if meta["year"] < FIRST_YEAR:
            continue
        stem = str(meta_path)[: -len("_meta.json")]
        if Path(f"{stem}_fp2.csv").exists() or Path(f"{stem}_sprint.csv").exists() or Path(f"{stem}_nolongrun").exists():
            skipped += 1
            continue
        ref = meta["source_laps"].rsplit("@", 1)[1]
        ev = {"year": meta["year"], "round": meta["round"], "event": meta["event"],
              "circuit_id": meta["circuit_id"], "location": meta["location"]}
        # Practice 2 if the weekend had one (raw files, no API listing: the
        # listing API allows only 60 calls an hour); else Practice 1 + Sprint.
        got = {}
        r = fetch(meta, ref, "Practice 2")
        if r is not None:
            got["fp2"] = r
        else:
            for session in ("Practice 1", "Sprint"):
                r = fetch(meta, ref, session)
                if r is not None:
                    got[SESSIONS[session]] = r
        if not got:
            missing += 1
            Path(f"{stem}_nolongrun").write_text("")
            print(f"  {Path(stem).name}: no long-run session found", flush=True)
            continue
        for tag, r in got.items():
            laps = build_laps(r.json(), ev)
            laps[[c for c in COLS if c in laps.columns]].to_csv(f"{stem}_{tag}.csv", index=False)
            done += 1
    print(f"long-run sessions exported {done}, weekends already done {skipped}, without one {missing}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
