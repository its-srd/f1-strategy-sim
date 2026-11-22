"""Export qualifying pace for every exported race (TracingInsights, same pinned
commit as the race laps).

Per race, writes data/raw/<year>/<stem>_quali.csv: each driver's best valid
qualifying lap (deleted laps excluded) and its gap to the fastest, in percent.
A session where any car ran intermediates or wets is flagged Wet; the model
does not use wet qualifying gaps as a pace signal.

Resumable (existing files are skipped); pauses PAUSE_S between downloads.

    .venv/bin/python scripts/export_quali.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from export_races import RAW_DIR, TI_RAW, get

PAUSE_S = 1.0


def best_laps(raw: dict) -> pd.DataFrame:
    df = pd.DataFrame({k: raw[k] for k in ("drv", "time", "del", "compound")})
    wet = df["compound"].isin(["INTERMEDIATE", "WET"]).any()
    df["time"] = pd.to_numeric(df["time"].replace("None", None), errors="coerce")
    df = df[df["time"].notna() & ~df["del"].astype(str).str.lower().eq("true")]
    best = df.groupby("drv")["time"].min().rename("BestLapS").reset_index().rename(columns={"drv": "Driver"})
    best["GapPct"] = 100 * (best["BestLapS"] / best["BestLapS"].min() - 1)
    best["Wet"] = bool(wet)
    return best.sort_values("BestLapS")


def main() -> None:
    done = skipped = missing = 0
    for meta_path in sorted(RAW_DIR.glob("*/*_meta.json")):
        stem = str(meta_path)[: -len("_meta.json")]
        out = Path(f"{stem}_quali.csv")
        if out.exists():
            skipped += 1
            continue
        meta = json.loads(meta_path.read_text())
        ref = meta["source_laps"].rsplit("@", 1)[1]
        url = TI_RAW.format(year=meta["year"], ref=ref, path=f"{quote(meta['ti_folder'])}/Qualifying/session_laptimes.json")
        r = get(url, ok404=True)
        if r is None:
            missing += 1
            print(f"  {meta_path.name[:7]} no qualifying file", flush=True)
        else:
            best_laps(r.json()).to_csv(out, index=False)
            done += 1
        time.sleep(PAUSE_S)
    print(f"qualifying exported {done}, already done {skipped}, missing {missing}", flush=True)


if __name__ == "__main__":
    main()
