"""Run every fit and export the parameters the simulator uses.

    .venv/bin/python model/fit_all.py

Writes data/params/*.json (consumed by web/) and refreshes the auto-generated
results section of docs/assumptions.md. Every number in the JSON comes from
the data. Structural choices (filters, model forms) live in docs/assumptions.md.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import car_form as CF  # noqa: E402
import common as C  # noqa: E402
import overtaking as O  # noqa: E402
import race_events as E  # noqa: E402
import race_fit as RF  # noqa: E402
import sim_inputs as SI  # noqa: E402
import skill as S  # noqa: E402
import track_pace as T  # noqa: E402
import validation as V  # noqa: E402
import wet as W  # noqa: E402
import wet_switch as WS  # noqa: E402

TARGET = 2026


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:6.0f}s] {msg}", flush=True)


def combined_breaks(v1, v2):
    out = {}
    for p in T.PARAMS + ["sigma"]:
        b = []
        if v2["track_params"][p]["decision"] == "break":
            b.append(2022)
        if v1["track_params"][p]["decision"] == "break":
            b.append(2026)
        out[p] = tuple(b)
    return out


def main(target: int = 2026, data=None, fixed_breaks: dict | None = None, grid_res=None,
         write_fits: bool = True):
    """target: season the parameters describe. data: (laps, res, races) to fit
    on (default: everything). fixed_breaks: skip validation and use these
    per-parameter breaks (backtest). grid_res: results rows of the race to
    predict; its actual starting grid becomes grid_2026.json (backtest)."""
    global TARGET
    TARGET = target
    T.TARGET_YEAR = target
    E.TARGET_YEAR = target
    laps, res, races = data if data is not None else C.load()
    laps = C.add_gaps(laps)
    clean, removed = C.clean_mask(laps, races)
    log(f"clean laps {int(clean.sum())} of {len(laps)}")

    rf, dr = RF.run(laps, clean, races)
    if write_fits:
        (C.PROC / "fits").mkdir(exist_ok=True)
        rf.to_csv(C.PROC / "fits" / "race_fits.csv", index=False)
        dr.to_csv(C.PROC / "fits" / "driver_race_pace.csv", index=False)
    log(f"stage A: {len(rf)} races, {len(dr)} driver-races")

    if fixed_breaks is None:
        v1 = {"track_params": V.track_param_tests(rf, 2026), "skill": V.skill_test(dr, 2026)}
        v2 = {"track_params": V.track_param_tests(rf, 2022), "skill": V.skill_test(dr, 2022)}
        breaks = combined_breaks(v1, v2)
    else:
        breaks = {p: tuple(b for b in v if b <= target) for p, v in fixed_breaks["breaks"].items()}
        v1 = {"skill": {"decision": fixed_breaks["skill"]}, "track_params": {}}
        v2 = {"skill": {"decision": "carry_over"}, "track_params": {}}
    log(f"validation done; breaks {breaks}")

    skill_break = 2026 if v1["skill"]["decision"] == "break" and target >= 2026 else None
    sk = S.fit(dr, break_year=skill_break)
    proj = S.project(sk["skill"], sk["omega2"], TARGET)
    log("skill fitted")

    tp = T.run(rf, breaks_by_param=breaks)
    rf["TrackKey"] = T.track_keys(rf)
    tk = dict(zip(rf.RaceKey, rf.TrackKey))
    for k, r in races.iterrows():                 # wet / unfitted races keep circuitId
        tk.setdefault(r.RaceKey, r.CircuitId)
    log("track pace pooled")

    stops = E.pit_stops(laps, clean)
    pit = E.pit_params(stops, tk)
    dep = E.deployments(laps, races)
    sc = E.sc_params(dep, races, tk)
    neutral = E.neutralised_pace(laps, clean)
    dnf = E.dnf_params(res, races, tk)
    start = E.start_params(laps, res, races, tk)
    log("race events fitted")

    ov = O.run(laps, races, rf, dr, tk, target_year=TARGET)
    pairs = O.build_pairs(laps, races, rf, dr)
    log("overtaking fitted")
    st = SI.stints_table(laps, res, races, tk)
    max_st, strat = SI.max_stint(st), SI.strategies(st)
    gaps = {**SI.gaps(laps, races), **SI.held_gaps(pairs)}
    pmode = SI.pace_mode(laps, clean, rf)
    log("sim inputs measured")
    wet = W.run(laps, races, rf, dr, tk, sk["skill"])
    wet["switch_timing"] = WS.run(laps, races)          # W10
    log("wet fitted")

    # ------------------------------------------------------------ export
    season = json.loads((C.ROOT / "data" / "raw" / str(TARGET) / "_jolpica_season.json").read_text())
    calendar = [{"round": int(k), "circuit_id": r["Circuit"]["circuitId"], "race_name": r["raceName"],
                 "date": r["date"], "circuit_name": r["Circuit"]["circuitName"],
                 "locality": r["Circuit"]["Location"]["locality"], "country": r["Circuit"]["Location"]["country"]}
                for k, r in sorted(season["races"].items(), key=lambda kv: int(kv[0]))]
    names = races.sort_values("Year").groupby("CircuitId").tail(1).set_index("CircuitId")

    # Car pace: per 2026 race, plus the team-season mean as the fallback.
    car = sk["car"].copy()
    car["Year"] = car["RaceKey"].str[:4].astype(int)
    car["TrackKey"] = car["RaceKey"].map(tk)
    car26 = car[car.Year == TARGET]
    teams_out = {}
    last_res = res[res.Year == TARGET].sort_values("Round")
    team_names = last_res.groupby("TeamId")["TeamName"].last().to_dict()
    form = CF.fit(sk["car"])               # within-season recency (I1)
    grid_fx = CF.grid_effect(sk, dr, res, form)   # weekend pace from the grid (I2)
    quali_all = C.load_quali(res if grid_res is None else pd.concat([res, grid_res]))
    quali_fx = CF.quali_effect(sk, dr, quali_all[quali_all["RaceKey"].isin(set(res["RaceKey"]))], form)   # I4
    log(f"car form: {form}; grid effect: {grid_fx}")
    for team, g in car26.groupby("TeamId"):
        w = 1 / g["car_sd"] ** 2
        avg = float(np.sum(w * g["car_pct"]) / np.sum(w))
        spread = float(np.sqrt(np.average((g["car_pct"] - avg) ** 2, weights=w)))
        mean, sd_next = CF.current(g, form["omega_pct2_per_race"], form["sigma_track_pct"])
        by_track = {r.TrackKey: {"car_pct": r.car_pct, "sd": r.car_sd, "race": r.RaceKey,
                                 "source": "2026 race"} for r in g.itertuples()}
        teams_out[team] = {"name": team_names.get(team, team), "season_mean_pct": mean,
                           "season_sd_pct": sd_next, "season_avg_equal_weights_pct": avg,
                           "race_to_race_sd_pct": spread, "n_races": int(len(g)), "by_track": by_track,
                           "dnf": dnf["teams_target_season"].get(team)}

    if grid_res is None:
        latest = last_res[last_res.Round == last_res.Round.max()].sort_values("Position")
    else:
        # Backtest: the test race's actual starting grid (pit-lane starts at
        # the back; non-starters left out).
        latest = grid_res[~grid_res["Status"].isin(E.NOT_RACED)].copy()
        latest["g"] = latest["GridPosition"].where(latest["GridPosition"] > 0, 99)
        latest = latest.sort_values(["g", "Position"])
    grid = [{"driver_id": r.DriverId, "code": r.Abbreviation, "name": r.FullName, "team_id": r.TeamId,
             "number": str(r.DriverNumber)} for r in latest.itertuples()]
    if grid_res is not None and not quali_all.empty:
        # Backtest: the test race's own qualifying (run before the race).
        qk = quali_all[quali_all["RaceKey"] == grid_res["RaceKey"].iloc[0]].set_index("DriverId")
        for g_ in grid:
            if g_["driver_id"] in qk.index:
                g_["quali_gap_pct"] = float(qk.loc[g_["driver_id"], "GapPct"])
                g_["quali_wet"] = bool(qk.loc[g_["driver_id"], "Wet"])
    info = res.sort_values(["Year", "Round"]).groupby("DriverId").tail(1).set_index("DriverId")
    wet_eff = wet.get("driver_wet_effects", {})
    drivers_out = {}
    for r in proj.itertuples():
        i = info.loc[r.DriverId]
        drivers_out[r.DriverId] = {
            "name": i.FullName, "code": i.Abbreviation, "last_team": i.TeamId, "last_season": int(r.Year),
            "skill_pct": r.skill_pct, "sd_pct": r.proj_sd, "years_since_last": int(r.years_since),
            "career_dry_races_fitted": int(r.career_races), "first_season": int(r.first_season),
            "car_corr_2026": {tk.get(rk, rk): c for (d_, rk), c in sk["corr_car_skill"].items()
                              if d_ == r.DriverId and rk.startswith(str(TARGET))},
            "wet_extra_pct": wet_eff.get(r.DriverId, {}).get("wet_extra_pct", 0.0),
            "wet_extra_sd": wet_eff.get(r.DriverId, {}).get("sd", wet["driver_wet_skill"]["between_driver_sd_pct"]),
            "wet_races": wet_eff.get(r.DriverId, {}).get("wet_races", 0),
            "history": {int(y): {"skill_pct": s, "sd": d, "races": int(n)} for y, s, d, n in
                        sk["skill"][sk["skill"].DriverId == r.DriverId][["Year", "skill_pct", "skill_sd", "n_races"]].values}}

    # Grid drivers with no dry race in the data (e.g. a one-off wet start)
    # get the prior: an average driver with the fitted initial spread.
    for g_ in grid:
        if g_["driver_id"] not in drivers_out:
            drivers_out[g_["driver_id"]] = {
                "name": g_["name"], "code": g_["code"], "last_team": g_["team_id"], "last_season": TARGET,
                "skill_pct": 0.0, "sd_pct": float(np.sqrt(sk["sigma02"] + sk["omega2"])), "years_since_last": 0,
                "career_dry_races_fitted": 0, "first_season": TARGET, "no_dry_data": True, "car_corr_2026": {},
                "wet_extra_pct": 0.0, "wet_extra_sd": wet["driver_wet_skill"]["between_driver_sd_pct"], "wet_races": 0,
                "history": {}}

    all_track_keys = sorted(set(tp["tracks"]) | {c["circuit_id"] for c in calendar})
    tracks_out = {}
    for t in all_track_keys:
        e = tp["tracks"].get(t)
        cid = t.replace("_short", "")
        nm = names.loc[cid] if cid in names.index else None
        cal = next((c for c in calendar if c["circuit_id"] == t), None)
        tracks_out[t] = {
            "name": (cal["race_name"] if cal else (nm.Event if nm is not None else t)) + (" (outer loop)" if t.endswith("_short") else ""),
            "circuit_name": cal["circuit_name"] if cal else (nm.CircuitName if nm is not None else t),
            "country": cal["country"] if cal else (nm.Country if nm is not None else ""),
            "on_2026_calendar": cal is not None, "round_2026": cal["round"] if cal else None,
            "has_dry_data": e is not None,
            "total_laps": e["total_laps"] if e else (int(nm.TotalLaps) if nm is not None else None),
            "base_lap": e["base_lap_s"] if e else None,
            "mean_track_temp": e["mean_track_temp"] if e else None,
            "dry_races": e["dry_races"] if e else 0,
            "pace": e["params"] if e else None,
            "pit": pit["tracks"].get(t),
            "sc_rate": sc["types"]["SC"]["tracks"].get(t),
            "vsc_rate": sc["types"]["VSC"]["tracks"].get(t),
            "red_rate": sc["types"]["RED"]["tracks"].get(t),
            "overtake": ov["tracks"].get(t),
            "start": start["tracks"].get(t),
            "dnf": dnf["tracks"].get(t),
            "max_stint": max_st.get(t),
            "strategies": strat.get(t),
        }

    global_out = {
        "pooled": {"pace": {p: {"mean_pct": m["pooled_mean"], "sd_pct": m["pooled_sd"], "omega_pct_per_year": float(np.sqrt(m["omega2"])),
                                "n_tracks": m["n_tracks"], "breaks": m.get("breaks", [])} for p, m in tp["pooling"].items()},
                   "pit_green_loss_s": pit["pooled_green_loss_s"], "pit_sd_s": pit["pooled_sd"]},
        "era_pace_ratio": {str(k): {"ratio": v[0], "n_tracks": v[1]} for k, v in tp["era_pace_ratio"].items()},
        "temperature_effects_pct_per_degC": tp["temperature"],
        "pit": {k: pit[k] for k in ("stop_residual_quantiles_s", "neutralised_ratio", "n_green_stops", "counts_by_kind", "omega2")},
        "safety_car": {typ: {k: v for k, v in d.items() if k != "tracks"} for typ, d in sc["types"].items()},
        "neutralised_pace": neutral,
        "dnf": {k: v for k, v in dnf.items() if k not in ("tracks", "teams_target_season")},
        "start": {k: v for k, v in start.items() if k != "tracks"},
        "overtaking": {k: v for k, v in ov.items() if k != "tracks"},
        "wet": {k: v for k, v in wet.items() if k != "driver_wet_effects"},
        "gaps": gaps, "pace_mode": pmode,
        "max_stint_pooled": {c: int(st.loc[st.compound == c, "age_end"].quantile(0.95)) for c in C.DRY},
        "car_form": form, "grid_effect": grid_fx, "quali_effect": quali_fx,
        "skill_model": {"tau_pct": float(np.sqrt(sk["tau2"])), "omega_pct_per_year": float(np.sqrt(sk["omega2"])),
                        "sigma0_pct": float(np.sqrt(sk["sigma02"])), "n_obs": sk["n_obs"],
                        "n_downweighted": sk["n_downweighted"], "break_year": skill_break},
        "validation": {"V1_2026": v1, "V2_2022": v2, "car_order_correlation": V.car_transfer(sk["car"]) if fixed_breaks is None else None,
                       "breaks_used": {p: list(b) for p, b in breaks.items()}},
    }
    meta = {"generated_utc": datetime.now(timezone.utc).isoformat(), "target_season": TARGET,
            "races_in_data": int(len(races)), "dry_races_fitted": int(len(rf)),
            "first_race": races.sort_values(["Year", "Round"]).iloc[0][["Year", "Event"]].tolist(),
            "last_race": races.sort_values(["Year", "Round"]).iloc[-1][["Year", "Event"]].tolist(),
            # Races the model has learned from; the website flags predictions of
            # these as "already seen" (not a genuine forecast).
            "data_through": {"year": int(races.sort_values(["Year", "Round"]).iloc[-1]["Year"]),
                             "round": int(races.sort_values(["Year", "Round"]).iloc[-1]["Round"])},
            "lap_rows": int(len(laps)), "clean_laps": int(clean.sum()), "filter_removed": removed,
            "outlier_laps_removed": int(rf["n_outliers"].sum()),
            "compound_laps_dropped_thin": int(rf["dropped_compound_laps"].sum()),
            "sources": {"laps": "TracingInsights GitHub (FastF1 output)", "results": "Jolpica-F1"},
            "units": {"pct": "percent of the track's base lap time; negative = faster",
                      "s": "seconds"}}

    C.write_json("meta.json", meta)
    C.write_json("tracks.json", tracks_out)
    C.write_json("teams.json", teams_out)
    C.write_json("drivers.json", drivers_out)
    # Example for the website's "after qualifying" mode: the latest race of the
    # season with a dry qualifying session, in real grid order.
    example = None
    # Only races with results in this fit: in a backtest quali_all also holds
    # the test race itself, which has no results here.
    q_season = quali_all[quali_all["RaceKey"].str.startswith(str(TARGET)) & quali_all["RaceKey"].isin(set(res["RaceKey"]))]
    dry_q = q_season.groupby("RaceKey")["Wet"].first()
    dry_q = dry_q[~dry_q.astype(bool)]
    if len(dry_q):
        ek = sorted(dry_q.index)[-1]
        er = res[(res.RaceKey == ek) & ~res["Status"].isin(E.NOT_RACED)].copy()
        er["g"] = er["GridPosition"].where(er["GridPosition"] > 0, 99)
        bl = q_season[q_season.RaceKey == ek].set_index("DriverId")["BestLapS"]
        example = {"race": f"{TARGET} {er['Event'].iloc[0]}", "wet": False,
                   "rows": [{"code": r.Abbreviation, "grid": int(r.GridPosition),
                             "best_lap_s": float(bl[r.DriverId]) if r.DriverId in bl.index else None}
                            for r in er.sort_values(["g", "Position"]).itertuples()]}
    C.write_json("grid_2026.json", {"grid": grid, "example_quali": example, "calendar": calendar,
                                    "from_race": latest.iloc[0].Event})
    C.write_json("global.json", global_out)
    if write_fits:
        stops.to_csv(C.PROC / "fits" / "pit_stops.csv", index=False)
        dep.to_csv(C.PROC / "fits" / "deployments.csv", index=False)
    (C.PARAMS / "_validation_preview.json").unlink(missing_ok=True)
    sizes = {p.name: f"{p.stat().st_size / 1024:.0f} KB" for p in sorted(C.PARAMS.glob("*.json"))}
    log(f"exported {sizes}")


if __name__ == "__main__":
    main()
