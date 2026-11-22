"""Export every F1 Grand Prix (race session) from 2018 to today.

Sources (no F1 TV login needed):
  * Lap timing: TracingInsights season repos (github.com/TracingInsights/<year>).
    These are files generated with FastF1 by TracingInsights and published on
    GitHub. Each season is pinned to one git commit, recorded in the metadata.
  * Results and calendar: Jolpica-F1 (the Ergast successor), api.jolpi.ca.
  * Event names (needed to build TracingInsights folder paths): FastF1's
    schedule, fetched once per season into data/cache/.

Per race, written into data/raw/<year>/:
    <year>_<round>_<circuit>_laps.csv      one row per driver-lap, with weather
    <year>_<round>_<circuit>_results.csv   classification (Jolpica)
    <year>_<round>_<circuit>_source/       untouched source JSON (session info
                                           with track status timeline, race
                                           control messages, weather, drivers)
    <year>_<round>_<circuit>_meta.json     metadata + cross-source validation;
                                           written LAST, marks the race complete

Resumable: a race whose meta.json exists is skipped. Failures go to
data/raw/_failures.json and are retried on the next run. Pauses PAUSE_S seconds
after each race that hit the network.

Usage (from the project root):
    .venv/bin/python scripts/export_races.py
    .venv/bin/python scripts/export_races.py --years 2023 --rounds 1 2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "cache"
RAW_DIR = ROOT / "data" / "raw"
FAIL_FILE = RAW_DIR / "_failures.json"

# Keep all library caches inside the project. Must be set before fastf1 import.
CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ["FASTF1_CACHE"] = str(CACHE_DIR)
os.environ["MPLCONFIGDIR"] = str(CACHE_DIR / "matplotlib")

import warnings  # noqa: E402

warnings.filterwarnings("ignore", message=".*OpenSSL.*")

import fastf1  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402

fastf1.Cache.enable_cache(str(CACHE_DIR))
fastf1.set_log_level("ERROR")

FIRST_YEAR = 2018
PAUSE_S = 3.0
DATA_DELAY = timedelta(hours=6)
TI_REPO = "TracingInsights/{year}"
TI_RAW = "https://raw.githubusercontent.com/TracingInsights/{year}/{ref}/{path}"
JOLPICA = "https://api.jolpi.ca/ergast/f1"
SOURCE_FILES = ["session_info.json", "rcm.json", "weather.json", "drivers.json"]
HTTP = requests.Session()
HTTP.headers["User-Agent"] = "f1-strategy-sim (personal research export)"

# TracingInsights short keys -> our column names.
LAP_KEYS = {
    "drv": "Driver", "dNum": "DriverNumber", "team": "Team", "lap": "LapNumber",
    "time": "LapTimeS", "stint": "Stint", "compound": "Compound",
    "life": "TyreLife", "fresh": "FreshTyre", "pin": "PitInTimeS",
    "pout": "PitOutTimeS", "status": "TrackStatus", "pos": "Position",
    "iacc": "IsAccurate", "del": "Deleted", "delR": "DeletedReason",
    "ff1G": "FastF1Generated", "pb": "IsPersonalBest",
    "sesT": "LapEndSessionTimeS", "lST": "LapStartSessionTimeS",
    "lSD": "LapStartDate", "s1": "Sector1S", "s2": "Sector2S", "s3": "Sector3S",
    "s1T": "Sector1SessionTimeS", "s2T": "Sector2SessionTimeS",
    "s3T": "Sector3SessionTimeS", "vi1": "SpeedI1", "vi2": "SpeedI2",
    "vfl": "SpeedFL", "vst": "SpeedST", "ms1": "MiniSectors1",
    "ms2": "MiniSectors2", "ms3": "MiniSectors3",
    "wT": "WeatherSampleTimeS", "wAT": "AirTemp", "wTT": "TrackTemp",
    "wR": "Rainfall", "wH": "Humidity", "wP": "Pressure",
    "wWS": "WindSpeed", "wWD": "WindDirection",
}


# ---------------------------------------------------------------- helpers
def get(url: str, *, retries: int = 4, ok404: bool = False):
    """GET with backoff on 429/5xx/network errors. Returns None on 404 if ok404."""
    for attempt in range(retries):
        try:
            r = HTTP.get(url, timeout=60)
        except requests.RequestException as exc:
            err = exc
        else:
            if r.status_code == 200:
                return r
            if r.status_code == 404 and ok404:
                return None
            if r.status_code not in (429, 500, 502, 503, 504):
                r.raise_for_status()
            err = RuntimeError(f"HTTP {r.status_code} for {url}")
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 30)))
        time.sleep(5 * 2 ** attempt)
    raise err


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(c for c in t.lower() if c.isalnum())


def load_failures() -> dict:
    return json.loads(FAIL_FILE.read_text()) if FAIL_FILE.exists() else {}


def save_failures(failures: dict) -> None:
    FAIL_FILE.parent.mkdir(parents=True, exist_ok=True)
    FAIL_FILE.write_text(json.dumps(failures, indent=2, sort_keys=True))


# ---------------------------------------------------------- season-level
def ti_commit(year: int) -> str:
    """Pin a season to the current commit of its repo (falls back to 'main')."""
    try:
        r = get(f"https://api.github.com/repos/{TI_REPO.format(year=year)}/commits/main")
        return r.json()["sha"]
    except Exception as exc:
        print(f"  [{year}] could not pin commit ({exc}); using 'main'", flush=True)
        return "main"


def jolpica_season(year: int) -> tuple[dict, dict]:
    """Return ({round: race_info}, {round: [results]}) for a season."""
    cache = RAW_DIR / str(year) / "_jolpica_season.json"
    races = get(f"{JOLPICA}/{year}/races.json?limit=100").json()
    races = {int(r["round"]): r for r in races["MRData"]["RaceTable"]["Races"]}
    results: dict[int, list] = {}
    offset, total = 0, 1
    while offset < total:
        time.sleep(1.0)
        page = get(f"{JOLPICA}/{year}/results.json?limit=100&offset={offset}").json()
        md = page["MRData"]
        total = int(md["total"])
        for race in md["RaceTable"]["Races"]:
            # A race can be split across pages; merge its result rows.
            results.setdefault(int(race["round"]), []).extend(race["Results"])
        offset += int(md["limit"])
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"races": races, "results": results}))
    return races, results


def season_events(year: int, now: datetime) -> list[dict]:
    """Rounds whose race has happened and has Jolpica results."""
    races, results = jolpica_season(year)
    ff1 = fastf1.get_event_schedule(year, include_testing=False)
    ff1 = {int(r["RoundNumber"]): r for _, r in ff1.iterrows() if int(r["RoundNumber"]) > 0}
    events = []
    for rnd, race in sorted(races.items()):
        start = datetime.fromisoformat(
            f"{race['date']}T{race.get('time', '12:00:00Z').replace('Z', '')}"
        ).replace(tzinfo=timezone.utc)
        if start + DATA_DELAY > now or rnd not in results:
            continue
        ff = ff1.get(rnd)
        # TracingInsights folders use FastF1's EventName. Prefer it when the
        # date agrees with Jolpica; otherwise fall back to Jolpica's race name.
        folder, name_source = race["raceName"], "jolpica"
        if ff is not None and abs((pd.Timestamp(ff["EventDate"]).date()
                                   - start.date()).days) <= 1:
            folder, name_source = ff["EventName"], "fastf1"
        loc = race["Circuit"]["Location"]
        events.append({
            "year": year, "round": rnd, "event": race["raceName"],
            "ti_folder": folder, "ti_folder_source": name_source,
            "circuit_id": race["Circuit"]["circuitId"],
            "circuit_name": race["Circuit"]["circuitName"],
            "location": loc["locality"], "country": loc["country"],
            "lat": float(loc["lat"]), "lon": float(loc["long"]),
            "event_date": race["date"], "race_start_utc": start.isoformat(),
            "results": results[rnd],
        })
    return events


# ------------------------------------------------------------ race-level
def stem_for(ev: dict) -> Path:
    return RAW_DIR / str(ev["year"]) / f"{ev['year']}_{ev['round']:02d}_{ev['circuit_id']}"


def track_flags(status: pd.Series) -> pd.DataFrame:
    """TrackStatus string holds every code seen on the lap:
    1 green, 2 yellow, 4 SC, 5 red, 6 VSC deployed, 7 VSC ending."""
    s = status.fillna("").astype(str)
    return pd.DataFrame({
        "TrackStatusYellow": s.str.contains("2"),
        "TrackStatusSC": s.str.contains("4"),
        "TrackStatusRed": s.str.contains("5"),
        "TrackStatusVSC": s.str.contains("6") | s.str.contains("7"),
    })


def build_laps(raw: dict, ev: dict) -> pd.DataFrame:
    n = len(raw["lap"])
    bad = [k for k, v in raw.items() if not isinstance(v, list) or len(v) != n]
    if bad:
        raise RuntimeError(f"ragged lap columns: {bad}")
    df = pd.DataFrame(raw).replace({"None": None, "nan": None, "NaN": None})
    unknown = [k for k in df.columns if k not in LAP_KEYS]
    df = df.rename(columns=LAP_KEYS)
    for c in ("LapTimeS", "PitInTimeS", "PitOutTimeS", "Sector1S", "Sector2S",
              "Sector3S", "LapEndSessionTimeS", "LapStartSessionTimeS",
              "TyreLife", "Position", "Stint", "LapNumber", "AirTemp",
              "TrackTemp", "Humidity", "Pressure", "WindSpeed", "WindDirection"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["DriverNumber"] = df["DriverNumber"].astype(str)
    df["TrackStatus"] = df["TrackStatus"].astype("string")
    df["PitIn"] = df["PitInTimeS"].notna()
    df["PitOut"] = df["PitOutTimeS"].notna()
    df = pd.concat([df, track_flags(df["TrackStatus"])], axis=1)
    front = pd.DataFrame({"Year": ev["year"], "Round": ev["round"],
                          "Event": ev["event"], "CircuitId": ev["circuit_id"],
                          "Location": ev["location"]}, index=df.index)
    df = pd.concat([front, df], axis=1)
    if unknown:
        print(f"    note: kept unknown source columns {unknown}", flush=True)
    return df.sort_values(["Driver", "LapNumber"]).reset_index(drop=True)


def build_results(ev: dict) -> pd.DataFrame:
    rows = []
    for r in ev["results"]:
        d, c = r["Driver"], r["Constructor"]
        rows.append({
            "Year": ev["year"], "Round": ev["round"], "Event": ev["event"],
            "CircuitId": ev["circuit_id"], "EventDate": ev["event_date"],
            "DriverNumber": r.get("number"), "Abbreviation": d.get("code"),
            "FullName": f"{d.get('givenName', '')} {d.get('familyName', '')}".strip(),
            "DriverId": d.get("driverId"), "TeamName": c.get("name"),
            "TeamId": c.get("constructorId"),
            "GridPosition": int(r["grid"]),       # 0 = pit lane start
            "Position": int(r["position"]),
            "ClassifiedPosition": r.get("positionText"),  # R/D/W/N/E/F = not classified
            "Status": r.get("status"), "Points": float(r.get("points", 0)),
            "Laps": int(r.get("laps", 0)),
            "RaceTimeS": int(r["Time"]["millis"]) / 1000 if "Time" in r else None,
        })
    return pd.DataFrame(rows)


def validate(laps: pd.DataFrame, res: pd.DataFrame, info: dict) -> dict:
    """Cross-check TracingInsights laps against Jolpica results."""
    out: dict = {}
    # After a car stops, the lap data can carry trailing "ghost" laps with no
    # lap time and no position. Count completed laps as the last lap that has
    # a recorded position.
    timed = laps[laps["Position"].notna()]
    max_lap = timed.groupby("Driver")["LapNumber"].max()
    ghost = laps.groupby("Driver")["LapNumber"].max() - max_lap.reindex(
        laps["Driver"].unique()).fillna(0)
    out["ghost_laps_after_last_position"] = int(ghost.clip(lower=0).sum())
    joined = res.set_index("Abbreviation")["Laps"].to_frame("jolpica_laps")
    joined["ti_laps"] = max_lap
    # "Finished", "+1 Lap" (older Jolpica) or "Lapped" (2026 Jolpica) mean the
    # car took the chequered flag. Those must match exactly. Any retiree,
    # including one classified under the 90% rule, has a final (in-)lap in the
    # timing data that the official count leaves out, so +1 is expected.
    status = res.set_index("Abbreviation")["Status"].astype(str)
    joined["finished"] = status.str.match(r"^(Finished|Lapped|\+\d+ Laps?)$")
    started = joined[joined["jolpica_laps"] > 0]
    diff = started["ti_laps"].fillna(-1) - started["jolpica_laps"]
    fin = started["finished"].fillna(False).astype(bool)
    bad = (fin & (diff != 0)) | (~fin & ~diff.isin([0, 1]))
    out["retiree_plus_one_laps"] = int((~fin & (diff == 1)).sum())
    mism = started[bad]
    out["drivers_in_results"] = int(len(res))
    out["drivers_in_laps"] = int(laps["Driver"].nunique())
    out["lap_count_mismatches"] = {
        k: [None if pd.isna(v.ti_laps) else int(v.ti_laps), int(v.jolpica_laps)]
        for k, v in mism.iterrows()}
    winner = res.loc[res["Position"] == 1, "Abbreviation"]
    winner = winner.iloc[0] if len(winner) else None
    last = timed[timed["LapNumber"] == timed["LapNumber"].max()]
    ti_leader = last.loc[last["Position"] == 1, "Driver"]
    out["winner_jolpica"] = winner
    out["winner_laps_data"] = ti_leader.iloc[0] if len(ti_leader) else None
    out["winner_match"] = bool(winner is not None and winner == out["winner_laps_data"])
    out["total_laps_session_info"] = info.get("total_laps")
    out["total_laps_winner_jolpica"] = int(res.loc[res["Position"] == 1, "Laps"].iloc[0]) if winner else None
    out["ok"] = bool(out["winner_match"] and not out["lap_count_mismatches"])
    return out


def export_race(ev: dict, ref: str) -> dict:
    base = f"{quote(ev['ti_folder'])}/Race"
    url = lambda name: TI_RAW.format(year=ev["year"], ref=ref, path=f"{base}/{name}")  # noqa: E731

    r = get(url("session_laptimes.json"), ok404=True)
    if r is None:
        raise FileNotFoundError(f"not published on TracingInsights: {ev['ti_folder']}/Race")
    laps = build_laps(r.json(), ev)

    stem = stem_for(ev)
    src_dir = Path(f"{stem}_source")
    src_dir.mkdir(parents=True, exist_ok=True)
    info: dict = {}
    for name in SOURCE_FILES:
        rr = get(url(name), ok404=True)
        if rr is None:
            continue
        (src_dir / name).write_bytes(rr.content)
        if name == "session_info.json":
            info = rr.json()

    res = build_results(ev)
    laps.to_csv(f"{stem}_laps.csv", index=False)
    res.to_csv(f"{stem}_results.csv", index=False)

    meta = {k: v for k, v in ev.items() if k != "results"}
    meta.update({
        "source_laps": f"github.com/{TI_REPO.format(year=ev['year'])}@{ref}",
        "source_results": "api.jolpi.ca (Jolpica-F1)",
        "lap_rows": int(len(laps)), "max_lap": int(laps["LapNumber"].max()),
        "drivers": int(laps["Driver"].nunique()),
        "source_files": sorted(p.name for p in src_dir.iterdir()),
        "validation": validate(laps, res, info),
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    Path(f"{stem}_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return meta


def revalidate() -> int:
    flagged = 0
    for mp in sorted(RAW_DIR.glob("*/*_meta.json")):
        stem = str(mp)[: -len("_meta.json")]
        meta = json.loads(mp.read_text())
        laps = pd.read_csv(f"{stem}_laps.csv", dtype={"TrackStatus": str, "DriverNumber": str})
        res = pd.read_csv(f"{stem}_results.csv", dtype={"ClassifiedPosition": str})
        info_p = Path(f"{stem}_source") / "session_info.json"
        info = json.loads(info_p.read_text()) if info_p.exists() else {}
        meta["validation"] = validate(laps, res, info)
        mp.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        v = meta["validation"]
        if not v["ok"]:
            flagged += 1
            print(f"  {mp.name[:7]} {meta['event']:<28} winner {v['winner_jolpica']} vs "
                  f"{v['winner_laps_data']}  laps {v['lap_count_mismatches']}")
    print(f"flagged {flagged}")
    return 0


# -------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="*")
    ap.add_argument("--rounds", type=int, nargs="*")
    ap.add_argument("--revalidate", action="store_true",
                    help="recompute validation from saved files (no network)")
    args = ap.parse_args()
    if args.revalidate:
        return revalidate()

    now = datetime.now(timezone.utc)
    years = args.years or list(range(FIRST_YEAR, now.year + 1))
    failures = load_failures()
    done = skipped = failed = flagged = 0
    t0 = time.time()

    for year in years:
        try:
            events = season_events(year, now)
        except Exception as exc:
            print(f"[{year}] season lookup failed: {exc!r}", flush=True)
            failures[f"{year}_season"] = repr(exc)
            save_failures(failures)
            continue
        failures.pop(f"{year}_season", None)
        if args.rounds:
            events = [e for e in events if e["round"] in args.rounds]
        todo = [e for e in events if not Path(f"{stem_for(e)}_meta.json").exists()]
        skipped += len(events) - len(todo)
        print(f"[{year}] {len(events)} completed races, {len(todo)} to export", flush=True)
        if not todo:
            continue
        ref = ti_commit(year)

        for ev in todo:
            key = f"{ev['year']}_{ev['round']:02d}"
            t = time.time()
            try:
                meta = export_race(ev, ref)
                done += 1
                failures.pop(key, None)
                v = meta["validation"]
                flag = "" if v["ok"] else "  CHECK: " + (
                    "winner mismatch " if not v["winner_match"] else "") + (
                    f"lap counts differ {v['lap_count_mismatches']}" if v["lap_count_mismatches"] else "")
                flagged += 0 if v["ok"] else 1
                print(f"  {key} {ev['event']:<28} ok  {meta['lap_rows']:>5} laps "
                      f"{meta['drivers']:>2} drv {time.time() - t:4.1f}s{flag}", flush=True)
            except Exception as exc:
                failed += 1
                failures[key] = f"{ev['event']}: {exc!r}"
                print(f"  {key} {ev['event']:<28} FAIL {exc!r}", flush=True)
            save_failures(failures)
            time.sleep(PAUSE_S)

    print(f"\nexported {done} (flagged {flagged}), already done {skipped}, "
          f"failed {failed}, {(time.time() - t0) / 60:.1f} min", flush=True)
    if failures:
        print("failures (rerun to retry):\n" + json.dumps(failures, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
