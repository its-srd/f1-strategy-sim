"""Race-weekend automation: forecast, score, retrain. Safe to run any time;
it only does what is due.

1. Score: every saved forecast whose race result is now published is
   compared with what happened (and with the grid-only baseline).
2. Retrain: if a race has finished that the model has not learned from yet,
   run scripts/update.sh (new race + qualifying, refit, rebuild the site).
3. Forecast: for the next race, once the OFFICIAL starting grid (penalties
   applied, from OpenF1) is published and before the race starts, simulate it
   with the current model and save the forecast untouched in data/forecasts/.
   The qualifying order alone is never used: penalties may still change it.
4. Rewrite docs/live_record.md (shown on the site's Track record tab).

    .venv/bin/python scripts/weekend.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
import score_backtest as SB  # noqa: E402  (actual(), grid_baseline())

PARAMS = ROOT / "data" / "params"
FORECASTS = ROOT / "data" / "forecasts"
JOLPICA = "https://api.jolpi.ca/ergast/f1"
OPENF1 = "https://api.openf1.org/v1"
NODE = Path.home() / ".local" / "node" / "bin" / "node"
HTTP = requests.Session()
HTTP.headers["User-Agent"] = "f1-strategy-sim (personal research)"


def get(url: str):
    r = HTTP.get(url, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def load(name: str):
    return json.loads((PARAMS / name).read_text())


def season_races(year: int) -> list[dict]:
    races = json.loads((ROOT / "data" / "raw" / str(year) / "_jolpica_season.json").read_text())["races"]
    out = []
    for rnd, r in sorted(races.items(), key=lambda kv: int(kv[0])):
        start = datetime.fromisoformat(f"{r['date']}T{r.get('time', '12:00:00Z').replace('Z', '')}").replace(tzinfo=timezone.utc)
        out.append({"year": year, "round": int(rnd), "key": f"{year}_{int(rnd):02d}", "name": r["raceName"],
                    "circuit": r["Circuit"]["circuitId"], "start": start})
    return out


# ------------------------------------------------------------------ forecast
def official_grid(race: dict):
    """OpenF1 starting grid (penalties applied) for the race weekend's
    qualifying session, or None if not published yet."""
    d = race["start"].date()
    sessions = get(f"{OPENF1}/sessions?session_name=Qualifying"
                   f"&date_start%3E={d - timedelta(days=4)}&date_start%3C={d + timedelta(days=1)}")
    if not sessions:
        return None
    grid = get(f"{OPENF1}/starting_grid?session_key={sessions[0]['session_key']}")
    return grid or None


def build_grid(race: dict) -> dict | None:
    sg = official_grid(race)
    if not sg:
        return None
    qj = get(f"{JOLPICA}/{race['year']}/{race['round']}/qualifying.json")
    quali = (qj or {}).get("MRData", {}).get("RaceTable", {}).get("Races", [{}])
    quali = quali[0].get("QualifyingResults", []) if quali else []
    drivers, grid_now = load("drivers.json"), load("grid_2026.json")["grid"]
    code_to_id = {}
    for did, d in sorted(drivers.items(), key=lambda kv: kv[1]["last_season"]):
        code_to_id[d["code"]] = did
    number_to_code = {int(g["number"]): g["code"] for g in grid_now if g["number"]}
    best, qpos = {}, {}
    for q in quali:
        number_to_code[int(q["number"])] = q["Driver"]["code"]
        times = [SB_to_s(q.get(k)) for k in ("Q1", "Q2", "Q3")]
        times = [t for t in times if t]
        if times:
            best[q["Driver"]["code"]] = min(times)
        qpos[q["Driver"]["code"]] = int(q["position"])
    team_now = {g["driver_id"]: g["team_id"] for g in grid_now}
    entries, problems = [], []
    for row in sorted(sg, key=lambda x: x["position"]):
        code = number_to_code.get(row["driver_number"])
        did = code_to_id.get(code or "")
        if not did:
            problems.append(f"car #{row['driver_number']} not matched to a driver")
            continue
        lap = best.get(code) or row.get("lap_duration")
        entries.append({"driver_id": did, "code": code, "name": drivers[did]["name"],
                        "team_id": team_now.get(did, drivers[did]["last_team"]), "number": str(row["driver_number"]),
                        "lap": lap})
    if problems:
        print("  grid problems:", "; ".join(problems))
        return None
    pole = min(e["lap"] for e in entries if e["lap"])
    for e in entries:
        e["quali_gap_pct"] = 100 * (e["lap"] / pole - 1) if e["lap"] else None
        e["quali_wet"] = False
    penalties = [f"{e['code']} qualified P{qpos[e['code']]}, starts P{i + 1}"
                 for i, e in enumerate(entries) if e["code"] in qpos and i + 1 > qpos[e["code"]]]
    return {"entries": entries, "penalties": penalties}


def SB_to_s(t: str | None) -> float | None:
    if not t:
        return None
    m, _, s = t.rpartition(":")
    return (int(m) * 60 if m else 0) + float(s)


def forecast_next(races: list[dict], now: datetime, data_through: dict) -> str | None:
    for race in races:
        if race["start"] <= now:
            continue
        path = FORECASTS / f"{race['key']}.json"
        if path.exists():
            return f"{race['name']}: forecast already saved"
        if (race["year"], race["round"]) <= (data_through["year"], data_through["round"]):
            return f"{race['name']}: model already contains this race, no genuine forecast possible"
        grid = build_grid(race)
        if not grid:
            return f"{race['name']}: official starting grid not published yet (checked {now:%Y-%m-%d %H:%M} UTC)"
        FORECASTS.mkdir(parents=True, exist_ok=True)
        tmp_in, tmp_out = FORECASTS / f"{race['key']}_input.json", FORECASTS / f"{race['key']}_pred.json"
        tmp_in.write_text(json.dumps({"track": race["circuit"], "grid": [
            {k: e[k] for k in ("driver_id", "code", "name", "team_id", "number", "quali_gap_pct", "quali_wet")} for e in grid["entries"]]}))
        subprocess.run([str(NODE), "--experimental-strip-types", "scripts/forecast.ts", str(tmp_in), str(tmp_out), "10000"],
                       cwd=ROOT / "web", check=True)
        pred = json.loads(tmp_out.read_text())
        path.write_text(json.dumps({
            "race": race["name"], "key": race["key"], "year": race["year"], "round": race["round"], "track": race["circuit"],
            "race_start_utc": race["start"].isoformat(), "created_utc": now.isoformat(),
            "grid_source": "OpenF1 official starting grid (penalties applied); lap times from Jolpica-F1 qualifying",
            "penalties": grid["penalties"], **pred}, indent=1))
        tmp_in.unlink(); tmp_out.unlink()
        fav = max(pred["drivers"], key=lambda d: d["win"])
        return f"{race['name']}: forecast saved; favourite {fav['code']} {fav['win']:.0%}"
    return "no upcoming race this season"


# ------------------------------------------------------------------ score
def score_pending() -> list[str]:
    done = []
    res_hist = pd.read_csv(ROOT / "data" / "processed" / "results.csv", dtype={"ClassifiedPosition": str})
    res_hist["RaceKey"] = res_hist["Year"].astype(str) + "_" + res_hist["Round"].astype(str).str.zfill(2)
    for path in sorted(FORECASTS.glob("20??_??.json")):
        f = json.loads(path.read_text())
        if "score" in f:
            continue
        rj = get(f"{JOLPICA}/{f['year']}/{f['round']}/results.json")
        races = (rj or {}).get("MRData", {}).get("RaceTable", {}).get("Races", [])
        if not races:
            continue
        rows = pd.DataFrame([{"DriverId": None, "Abbreviation": r["Driver"]["code"], "Position": int(r["position"]),
                              "ClassifiedPosition": r["positionText"], "Status": r["status"],
                              "GridPosition": int(r["grid"])} for r in races[0]["Results"]])
        act = SB.actual(rows.assign(DriverId=rows["Abbreviation"]))
        pred = pd.DataFrame(f["drivers"]).set_index("code")
        n = len(pred)
        before = res_hist[(res_hist.Year < f["year"]) | ((res_hist.Year == f["year"]) & (res_hist.Round < f["round"]))]
        base = SB.grid_baseline(before, set(before.RaceKey), n)
        common = [c for c in pred.index if c in act.index]
        m = {}
        for o in ("win", "podium", "points"):
            y = act.loc[common, o].astype(float).values
            pm = pred.loc[common, o].values
            pg = base.loc[pred.loc[common, "grid"].clip(upper=n).values, o].values
            if o == "win":
                pg = pg / pg.sum()
            m[o] = {"brier_model": float(np.mean((pm - y) ** 2)), "brier_grid": float(np.mean((pg - y) ** 2))}
        winner = act.index[act["win"]][0] if act["win"].any() else None
        actual_pos = {c: (int(act.loc[c, "Position"]) if not act.loc[c, "dnf"] else n + 1) for c in common}
        rank = pd.Series({c: pred.loc[c, "exp_pos"] for c in common}).corr(pd.Series(actual_pos), method="spearman")
        fav = pred["win"].idxmax()
        f["score"] = {"winner": winner, "p_winner": float(pred.loc[winner, "win"]) if winner in pred.index else None,
                      "favourite": fav, "favourite_won": fav == winner, "rank_corr": float(rank), "metrics": m,
                      "actual": {c: actual_pos[c] for c in common}, "scored_utc": datetime.now(timezone.utc).isoformat()}
        path.write_text(json.dumps(f, indent=1))
        done.append(f"{f['race']}: scored; winner {winner} (forecast {f['score']['p_winner']:.0%}), favourite {fav} "
                    f"{'won' if fav == winner else 'did not win'}")
    return done


def write_live_record() -> bool:
    rows = [json.loads(p.read_text()) for p in sorted(FORECASTS.glob("20??_??.json"))]
    L = ["# Live track record", "",
         "Forecasts saved automatically **before** each race, from the official starting grid, by a model "
         "that had not seen the race. Each forecast is scored once the result is published, and never changed "
         "afterwards. Unlike the backtest, this cannot be tuned after the fact.", ""]
    if not rows:
        L += ["No forecasts saved yet. The first one is made once the next race's official starting grid is published.", ""]
    else:
        L += ["| Race | Saved (UTC) | Favourite | Winner | Forecast for the winner | Win / podium / points vs grid | Order match (model / grid) |",
              "|---|---|---|---|---|---|---|"]
        sk = {o: [] for o in ("win", "podium", "points")}
        for f in rows:
            fav = max(f["drivers"], key=lambda d: d["win"])
            s = f.get("score")
            if not s:
                L.append(f"| {f['race']} {f['year']} | {f['created_utc'][:16]} | {fav['code']} {fav['win']:.0%} | pending | – | – | – |")
                continue
            for o in sk:
                sk[o].append(s["metrics"][o])
            skill = " / ".join(f"{1 - s['metrics'][o]['brier_model'] / s['metrics'][o]['brier_grid']:+.0%}" for o in ("win", "podium", "points"))
            L.append(f"| {f['race']} {f['year']} | {f['created_utc'][:16]} | {fav['code']} {fav['win']:.0%} | {s['winner']} | "
                     f"{s['p_winner']:.0%} | {skill} | {s['rank_corr']:.2f} |")
        scored = [f for f in rows if f.get("score")]
        if scored:
            tot = " / ".join(f"{1 - np.mean([x['brier_model'] for x in sk[o]]) / np.mean([x['brier_grid'] for x in sk[o]]):+.0%}" for o in sk)
            L += ["", f"**So far:** {len(scored)} race(s) scored; favourite won {sum(f['score']['favourite_won'] for f in scored)} of {len(scored)}; "
                  f"win / podium / points vs grid baseline: {tot}. Positive = better than the grid baseline. "
                  "A handful of races says little either way; read this together with the backtest below."]
        L += [""]
    out = ROOT / "docs" / "live_record.md"
    text = "\n".join(L) + "\n"
    changed = not out.exists() or out.read_text() != text
    out.write_text(text)
    return changed


def main() -> int:
    now = datetime.now(timezone.utc)
    meta = load("meta.json")
    year = meta["target_season"]
    races = season_races(year)
    report = [f"weekend run {now:%Y-%m-%d %H:%M} UTC"]
    FORECASTS.mkdir(parents=True, exist_ok=True)

    report += score_pending()

    # Retrain when a race has finished (result published) that the model lacks.
    dt = meta["data_through"]
    finished = [r for r in races if r["start"] + timedelta(hours=6) < now and (r["year"], r["round"]) > (dt["year"], dt["round"])]
    published = finished and ((get(f"{JOLPICA}/{year}/{finished[0]['round']}/results.json") or {})
                              .get("MRData", {}).get("RaceTable", {}).get("Races"))
    if published:
        report.append(f"retraining with {', '.join(r['name'] for r in finished)}")
        subprocess.run(["./scripts/update.sh"], cwd=ROOT, check=True)
        meta = load("meta.json")
        rebuilt = True
    else:
        rebuilt = False

    report.append(forecast_next(races, now, meta["data_through"]))

    if write_live_record() and not rebuilt:
        subprocess.run([str(NODE.parent / "npm"), "run", "build"], cwd=ROOT / "web", check=True,
                       env={**os.environ, "PATH": f"{NODE.parent}:{os.environ.get('PATH', '/usr/bin:/bin')}"}, stdout=subprocess.DEVNULL)
        report.append("live record updated, site rebuilt")
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
