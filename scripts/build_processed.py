"""Combine per-race raw exports into analysis tables in data/processed/.

    laps.parquet / laps.csv.gz      every driver-lap, plus derived flags
    results.csv                     every classification row
    races.csv                       one row per race (summary below)

Only races whose _meta.json exists (complete exports) are included.
Nothing is filtered out here; derived flags mark rows that later fitting code
may exclude, so every exclusion stays visible and countable.

Usage: .venv/bin/python scripts/build_processed.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

WET_COMPOUNDS = {"INTERMEDIATE", "WET"}
# Pirelli's 2018 absolute dry range, softest to hardest.
ABSOLUTE_ORDER = ["HYPERSOFT", "ULTRASOFT", "SUPERSOFT", "SOFT", "MEDIUM", "HARD", "SUPERHARD"]
RELATIVE = ["SOFT", "MEDIUM", "HARD"]
# Pirelli switched to relative labels from 2019. SOFT/MEDIUM/HARD in 2018 are
# absolute names, so the season decides, not the label.
LAST_ABSOLUTE_YEAR = 2018


def load_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def status_events(info: dict) -> dict:
    """Count deployments from the session track-status timeline.

    A deployment is a transition INTO the status (consecutive repeats of the
    same code are not double counted). Codes: 4 SC, 5 red, 6 VSC deployed.
    """
    ts = info.get("track_status") or {}
    codes = [str(s) for s in ts.get("Status", [])]
    counts = {"4": 0, "5": 0, "6": 0}
    prev, last_flag = None, None
    for c in codes:
        # SC restart after a red flag. Descriptive count only: the model's
        # deployments (model/race_events.py) also check that no lap was
        # completed in between, so an SC after a standing restart counts.
        if c in counts and c != prev and not (c == "4" and last_flag == "5"):
            counts[c] += 1
        prev = c
        if c != "1":
            last_flag = c
    return {"SCDeployments": counts["4"], "RedFlags": counts["5"],
            "VSCDeployments": counts["6"],
            "TrackStatusTimelineAvailable": bool(codes)}


def race_window(info: dict) -> tuple[float | None, float | None]:
    st = info.get("session_status") or {}
    times, stat = st.get("Time", []), st.get("Status", [])
    start = next((t for t, s in zip(times, stat) if s == "Started"), None)
    end = next((t for t, s in zip(times, stat) if s in ("Finished", "Finalised")), None)
    return start, end


def weather_means(weather: dict, start, end) -> dict:
    """Mean temps over the race window from the raw ~1/min weather samples."""
    if not weather or start is None or end is None:
        return {}
    w = pd.DataFrame(weather)
    w = w[(pd.to_numeric(w["wT"], errors="coerce") >= start)
          & (pd.to_numeric(w["wT"], errors="coerce") <= end)]
    if w.empty:
        return {}
    rain = w["wR"].astype(str).str.lower().eq("true")
    return {
        "MeanTrackTemp": round(pd.to_numeric(w["wTT"], errors="coerce").mean(), 2),
        "MeanAirTemp": round(pd.to_numeric(w["wAT"], errors="coerce").mean(), 2),
        "RainfallSampleShare": round(rain.mean(), 4),
        "WeatherSamples": int(len(w)),
    }


def map_absolute_compounds(laps: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Relabel 2018-style absolute compound names to the relative SOFT/MEDIUM/HARD
    scale Pirelli has used since 2019 (assumption L6).

    Within each race the dry compounds actually used are ranked
    softest -> hardest and labelled SOFT, MEDIUM, HARD. A race is mapped only
    if exactly three absolute-named dry compounds appear. Otherwise its
    absolute-named laps get Compound = None and CompoundMappingOk = False,
    and nothing is guessed. The original label is kept in CompoundOriginal.
    """
    laps = laps.copy()
    laps["CompoundOriginal"] = laps["Compound"]
    comp = laps["Compound"].astype(str).str.upper()
    is_abs = comp.isin(ABSOLUTE_ORDER) & (laps["Year"] <= LAST_ABSOLUTE_YEAR)
    rows = []
    for (year, rnd), idx in laps[is_abs & ~laps["IsGhostLap"]].groupby(["Year", "Round"]).groups.items():
        used = [c for c in ABSOLUTE_ORDER if c in set(comp.loc[idx])]
        race_mask = (laps["Year"] == year) & (laps["Round"] == rnd) & is_abs
        ok = len(used) == 3
        if ok:
            laps.loc[race_mask, "Compound"] = comp[race_mask].map(dict(zip(used, RELATIVE)))
        else:
            laps.loc[race_mask, "Compound"] = None
        span = ABSOLUTE_ORDER[ABSOLUTE_ORDER.index(used[0]): ABSOLUTE_ORDER.index(used[-1]) + 1]
        rows.append({"Year": year, "Round": rnd,
                     "DryNomination": "/".join(used),
                     "NonAdjacentNomination": ok and len(span) > 3,
                     "CompoundMappingOk": ok})
    cols = ["Year", "Round", "DryNomination", "NonAdjacentNomination", "CompoundMappingOk"]
    return laps, pd.DataFrame(rows, columns=cols)


def flag_ghost_laps(laps: pd.DataFrame) -> pd.Series:
    """Rows after a driver's last lap with a recorded position, carrying no lap
    time and no position (the car had already stopped)."""
    last_pos = (laps[laps["Position"].notna()]
                .groupby(["Year", "Round", "Driver"])["LapNumber"].max()
                .rename("LastPositionedLap"))
    j = laps.join(last_pos, on=["Year", "Round", "Driver"])
    return (j["LapNumber"] > j["LastPositionedLap"].fillna(0)) \
        & j["LapTimeS"].isna() & j["Position"].isna()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    metas = sorted(RAW.glob("*/*_meta.json"))
    lap_frames, res_frames, race_rows = [], [], []

    for mp in metas:
        meta = json.loads(mp.read_text())
        stem = str(mp)[: -len("_meta.json")]
        src = Path(f"{stem}_source")
        laps = pd.read_csv(f"{stem}_laps.csv", dtype={
            "TrackStatus": str, "DriverNumber": str, "DeletedReason": str,
            "MiniSectors1": str, "MiniSectors2": str, "MiniSectors3": str,
            "LapStartDate": str})
        res = pd.read_csv(f"{stem}_results.csv", dtype={
            "ClassifiedPosition": str, "DriverNumber": str})
        info = load_json(src / "session_info.json")
        weather = load_json(src / "weather.json")

        # Rain on a lap = any car's lap weather sample reported rainfall.
        rain_by_lap = (laps.assign(R=laps["Rainfall"].astype(str).str.lower().eq("true"))
                       .groupby("LapNumber")["R"].any())
        comp = laps["Compound"].astype(str).str.upper()
        start, end = race_window(info)
        v = meta.get("validation", {})
        winner = res.loc[res["Position"] == 1]

        row = {
            "Year": meta["year"], "Round": meta["round"], "Event": meta["event"],
            "CircuitId": meta["circuit_id"], "CircuitName": meta["circuit_name"],
            "Location": meta["location"], "Country": meta["country"],
            "Lat": meta["lat"], "Lon": meta["lon"], "EventDate": meta["event_date"],
            "TotalLaps": info.get("total_laps") or (int(winner["Laps"].iloc[0]) if len(winner) else None),
            "WinnerLaps": int(winner["Laps"].iloc[0]) if len(winner) else None,
            "Drivers": int(laps["Driver"].nunique()),
            "LapRows": int(len(laps)),
            "RainfallLaps": int(rain_by_lap.sum()),
            "IntermediateDriverLaps": int((comp == "INTERMEDIATE").sum()),
            "WetDriverLaps": int((comp == "WET").sum()),
            "WetCompoundUsed": bool(comp.isin(WET_COMPOUNDS).any()),
            "SCLaps": int(laps.loc[laps["TrackStatusSC"], "LapNumber"].nunique()),
            "VSCLaps": int(laps.loc[laps["TrackStatusVSC"], "LapNumber"].nunique()),
            **status_events(info),
            **weather_means(weather, start, end),
            "ValidationOk": v.get("ok"),
            "ValidationIssues": json.dumps(v.get("lap_count_mismatches") or {}),
            "LapSource": meta.get("source_laps"),
        }
        row["MixedOrWetRace"] = bool(row["WetCompoundUsed"] or row["RainfallLaps"] > 0)
        race_rows.append(row)
        lap_frames.append(laps)
        res_frames.append(res)

    laps = pd.concat(lap_frames, ignore_index=True)
    laps["IsGhostLap"] = flag_ghost_laps(laps)
    laps, nominations = map_absolute_compounds(laps)
    laps["IsWetCompound"] = laps["Compound"].astype(str).str.upper().isin(WET_COMPOUNDS)
    results = pd.concat(res_frames, ignore_index=True)
    races = (pd.DataFrame(race_rows)
             .merge(nominations, on=["Year", "Round"], how="left")
             .sort_values(["Year", "Round"]))
    races["CompoundMappingOk"] = races["CompoundMappingOk"].astype("boolean").fillna(True).astype(bool)

    quali = []
    for mp in metas:
        stem = str(mp)[: -len("_meta.json")]
        qp = Path(f"{stem}_quali.csv")
        if qp.exists():
            meta = json.loads(mp.read_text())
            quali.append(pd.read_csv(qp).assign(Year=meta["year"], Round=meta["round"]))
    if quali:
        pd.concat(quali, ignore_index=True).to_csv(OUT / "quali.csv", index=False)

    laps.to_parquet(OUT / "laps.parquet", index=False)
    laps.to_csv(OUT / "laps.csv.gz", index=False, compression="gzip")
    results.to_csv(OUT / "results.csv", index=False)
    races.to_csv(OUT / "races.csv", index=False)

    print(f"races {len(races)}  laps {len(laps):,}  results {len(results):,}")
    print(f"ghost laps flagged {int(laps['IsGhostLap'].sum())}")
    print(f"races failing validation: {int((~races['ValidationOk'].astype(bool)).sum())}")
    print(f"mixed/wet races: {int(races['MixedOrWetRace'].sum())} "
          f"(wet compound used: {int(races['WetCompoundUsed'].sum())}, "
          f"rainfall reported: {int((races['RainfallLaps'] > 0).sum())})")
    print("\nper season:")
    print(races.groupby("Year").agg(
        races=("Round", "count"), wet=("MixedOrWetRace", "sum"),
        sc=("SCDeployments", "sum"), vsc=("VSCDeployments", "sum"),
        red=("RedFlags", "sum")).to_string())


if __name__ == "__main__":
    main()
