"""Pace blend (I4) and grid effect (I2) fitted on the priors the engine
really has before a race (review 1.6).

model/car_form.py fits both inside the model, with each driver's skill for
the whole season, so the prior already knows the race it is explaining and
the blend leans on it too much. Here every backtest race (data/backtest/
<race>/params, fitted on earlier races only) gives the prior exactly as the
engine builds it: car pace for the track (or the season mean) plus the
driver's skill. The race's measured pace (stage A, data/processed/fits/
driver_race_pace.csv) is regressed on that prior and on the dry qualifying
gap, both centred on the field.

Forward-chained: the blend used to score a season is fitted only on earlier
seasons; the blend for the website and the exam uses every season before
the exam. Results go to data/params/calibration.json.

    .venv/bin/python model/calibrate_pace.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

BT = C.ROOT / "data" / "backtest"
CAL = C.ROOT / "data" / "params" / "calibration.json"


def priors(d: Path) -> pd.DataFrame:
    P = lambda f: json.loads((d / "params" / f).read_text())
    race = json.loads((d / "race.json").read_text())
    teams, drivers, grid = P("teams.json"), P("drivers.json"), P("grid_2026.json")["grid"]
    rows = []
    for slot, g in enumerate(grid, 1):
        team = teams.get(g["team_id"])
        if team is None:
            continue
        bt = team["by_track"].get(race["track"])
        car = bt["car_pct"] if bt else team["season_mean_pct"]
        rows.append({"RaceKey": race["key"], "Year": race["year"], "DriverId": g["driver_id"], "slot": slot,
                     "prior": car + drivers.get(g["driver_id"], {}).get("skill_pct", 0.0),
                     "gap": g.get("quali_gap_pct"), "wet": bool(g.get("quali_wet", False)),
                     "qpos": g.get("quali_pos"), "pit": bool(g.get("pit_lane", False))})
    return pd.DataFrame(rows)


def fit(d: pd.DataFrame, tau2: float) -> dict:
    """Weighted least squares on field-centred values; weights 1 / (lap-time
    noise of the measured pace + race-to-race form)."""
    d = d.copy()
    d["prior_c"] = d["prior"] - d.groupby("RaceKey")["prior"].transform("mean")
    w = 1 / (d["se_pct"] ** 2 + tau2)
    noise = np.average(d["se_pct"] ** 2, weights=w)

    def resid_sd(e):
        return float(np.sqrt(max(np.average(e ** 2, weights=w[e.index]) - noise, 1e-6)))

    out = {"n_driver_races": int(len(d)), "n_races": int(d.RaceKey.nunique()),
           "seasons": sorted(int(y) for y in d.Year.unique())}
    # I4: race pace = a * prior + b * qualifying gap (dry, gap inside the clip).
    q = d[~d["wet"] & d["gap"].notna()].copy()
    clip = float(q["gap"].median() + 4 * C.robust_sigma(q["gap"]))
    q = q[q["gap"] <= clip]
    q["gap_c"] = q["gap"] - q.groupby("RaceKey")["gap"].transform("mean")
    q["prior_c"] = q["prior"] - q.groupby("RaceKey")["prior"].transform("mean")
    wq = w[q.index].values
    X = q[["prior_c", "gap_c"]].values
    XtW = X.T * wq
    beta = np.linalg.solve(XtW @ X, XtW @ q["delta_pct"].values)
    e = q["delta_pct"] - X @ beta
    meat = (X * (wq * e.values)[:, None]).T @ (X * (wq * e.values)[:, None])
    bread = np.linalg.inv(XtW @ X)
    out["quali"] = {"weight_prior": float(beta[0]), "weight_quali": float(beta[1]),
                    "se": np.sqrt(np.diag(bread @ meat @ bread)).tolist(),
                    "form_sd_after_quali_pct": resid_sd(e),
                    "form_sd_prior_only_pct": resid_sd(q["delta_pct"] - q["prior_c"]),
                    "quali_gap_clip_pct": clip, "n_driver_races": int(len(q))}
    # I2: pace per place between where the car qualified and where its prior
    # ranks it (pit-lane starts left out).
    g = d[~d["pit"]].copy()
    g["place"] = g["qpos"].fillna(g["slot"])
    g["expected"] = g.groupby("RaceKey")["prior"].rank(method="first")
    g["place"] = g.groupby("RaceKey")["place"].rank(method="first")
    x = (g["place"] - g["expected"]).values
    y = (g["delta_pct"] - g["prior_c"]).values
    wg = w[g.index].values
    b = float(np.sum(wg * x * y) / np.sum(wg * x * x))
    r = y - b * x
    se = float(np.sqrt(np.sum((wg * x * r) ** 2)) / np.sum(wg * x * x))
    sd = lambda v: float(np.sqrt(max(np.average(v ** 2, weights=wg) - noise, 1e-6)))
    out["grid"] = {"pct_per_grid_place": b, "se": se, "form_sd_before_grid_pct": sd(y),
                   "form_sd_after_grid_pct": sd(r), "n_driver_races": int(len(g))}
    return out


SEASON_N0 = 60        # driver-races (about 3 races) at which the season's own spread gets half the weight


def season_spread(pr: pd.DataFrame, blend: dict) -> pd.DataFrame:
    """Race pace left unexplained by form + qualifying, per driver-race:
    squared residual minus the pace measurement's own noise (review: 2026
    swings about twice as much as 2024-25, 0.64% vs 0.30%)."""
    q = pr[~pr["wet"] & pr["gap"].notna() & (pr["gap"] <= blend["quali"]["quali_gap_clip_pct"])].copy()
    for c in ("prior", "gap"):
        q[c + "_c"] = q[c] - q.groupby("RaceKey")[c].transform("mean")
    e = q["delta_pct"] - blend["quali"]["weight_prior"] * q["prior_c"] - blend["quali"]["weight_quali"] * q["gap_c"]
    q["excess_var"] = e ** 2 - q["se_pct"] ** 2
    return q[["RaceKey", "Year", "excess_var"]]


def season_form(q: pd.DataFrame, year: int, before_key: str | None, base_sd: float) -> dict:
    """Form spread for a race of `year`: the season's own measured spread on
    its earlier races, blended with the long-run value by how many driver-
    races the season has so far (I5). Variances are blended."""
    s = q[(q.Year == year) & ((q.RaceKey < before_key) if before_key else True)]
    n = len(s)
    own = float(np.sqrt(max(s["excess_var"].mean(), 1e-6))) if n else base_sd
    w = n / (n + SEASON_N0)
    sd = float(np.sqrt(w * own ** 2 + (1 - w) * base_sd ** 2))
    return {"sd": sd, "ratio": sd / base_sd, "season_sd": own, "n": int(n), "weight": w}


def main():
    dirs = [d for d in sorted(BT.glob("20*_*")) if (d / "params" / "meta.json").exists() and (d / "race.json").exists()]
    pr = pd.concat([priors(d) for d in dirs], ignore_index=True)
    pace = pd.read_csv(C.PROC / "fits" / "driver_race_pace.csv")[["RaceKey", "DriverId", "delta_pct", "se_pct"]]
    pr = pr.merge(pace, on=["RaceKey", "DriverId"], how="inner")
    tau2 = json.loads((C.ROOT / "data" / "params" / "global.json").read_text())["skill_model"]["tau_pct"] ** 2
    target = int(json.loads((C.ROOT / "data" / "params" / "meta.json").read_text())["target_season"])
    cal = json.loads(CAL.read_text())
    forward = {}
    for year in sorted(pr.Year.unique()):
        before = pr[pr.Year < year]
        if before.RaceKey.nunique() >= 10:
            forward[str(int(year))] = fit(before, tau2)
    final = fit(pr[pr.Year < target], tau2) if pr[pr.Year < target].RaceKey.nunique() >= 10 else fit(pr, tau2)
    # I5: each season's form spread, as of each race (backtests) and now
    # (the website and live forecasts).
    per_race, current = {}, None
    for year in sorted(pr.Year.unique()):
        blend = forward.get(str(int(year)))
        if blend is None:
            continue
        q = season_spread(pr, blend)
        base = blend["quali"]["form_sd_after_quali_pct"]
        for key in sorted(pr.loc[pr.Year == year, "RaceKey"].unique()):
            per_race[key] = season_form(q, int(year), key, base)
    q = season_spread(pr, final)
    current = season_form(q, target, None, final["quali"]["form_sd_after_quali_pct"])
    cal["pace_blend"] = {**final, "note": "I2/I4 refitted on as-of priors (docs/assumptions.md); used by the website and the exam"}
    cal["pace_blend_forward"] = forward
    cal["season_form"] = {"note": "I5: the target season's own form spread (form + qualifying leave this much race pace "
                          "unexplained), blended with the long-run value by driver-races so far; per_race = as of each backtest race",
                          "current": {**current, "season": target}, "per_race": per_race}
    CAL.write_text(json.dumps(C._clean(cal), indent=1, ensure_ascii=False) + "\n")
    for k, v in [("final", final), *forward.items()]:
        print(k, v["seasons"], "I4", {x: round(v["quali"][x], 3) for x in ("weight_prior", "weight_quali", "form_sd_after_quali_pct")},
              "I2", {x: round(v["grid"][x], 4) for x in ("pct_per_grid_place", "form_sd_before_grid_pct", "form_sd_after_grid_pct")},
              "n", v["n_driver_races"])
    print("season form now:", {k: round(v, 3) if isinstance(v, float) else v for k, v in current.items()})
    for key in ("2025_10", "2025_24", "2026_06", "2026_13", "2026_21"):
        if key in per_race:
            print("  as of", key, {k: round(v, 3) if isinstance(v, float) else v for k, v in per_race[key].items()})


if __name__ == "__main__":
    main()
