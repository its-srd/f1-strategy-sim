"""Within-season car pace: recent races count more (upgrades, development).

Each team's per-race car value (stage B) is treated as a level that drifts
from race to race (random walk, variance omega per race) plus a track-to-track
scatter (sigma_track: how much a car's result varies with the circuit around
its current level) plus the estimate's own error (car_sd). omega and
sigma_track are chosen by how well each race predicts the next across every
team-season in the data (one-step-ahead predictive likelihood), so the data
decides how strongly recent races count.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import common as C

OMEGA_GRID = np.concatenate([[0.0], np.logspace(-4, 0, 25)])
SIGMA_GRID = np.linspace(0.05, 0.8, 16)


def series(car: pd.DataFrame):
    car = car.copy()
    car["Year"] = car["RaceKey"].str[:4].astype(int)
    car["Round"] = car["RaceKey"].str[5:].astype(int)
    for (team, year), g in car.sort_values("Round").groupby(["TeamId", "Year"]):
        yield team, year, g


def fit(car: pd.DataFrame) -> dict:
    groups = [(g["car_pct"].values, g["car_sd"].values, g["Round"].values) for _, _, g in series(car) if len(g) >= 2]
    best = (-np.inf, 0.0, 0.0)
    for sig in SIGMA_GRID:
        for om in OMEGA_GRID:
            ll = sum(C.local_level(y, np.sqrt(s ** 2 + sig ** 2), r, om)[2] for y, s, r in groups)
            if ll > best[0]:
                best = (ll, om, sig)
    _, omega, sigma = best
    # Same score for the old rule (equal weights within a season = omega 0).
    ll_equal = max(sum(C.local_level(y, np.sqrt(s ** 2 + sig ** 2), r, 0.0)[2] for y, s, r in groups) for sig in SIGMA_GRID)
    return {"omega_pct2_per_race": float(omega), "sigma_track_pct": float(sigma), "loglik": float(best[0]),
            "loglik_equal_weights": float(ll_equal), "team_seasons": len(groups)}


def current(car_team_season: pd.DataFrame, omega: float, sigma: float) -> tuple[float, float]:
    """Forecast for the team's next race at a track it has not raced this
    season: filtered level, and the SD of a new race value around it."""
    g = car_team_season.sort_values("Round") if "Round" in car_team_season else car_team_season
    rounds = g["RaceKey"].str[5:].astype(int).values
    m, P, _ = C.local_level(g["car_pct"].values, np.sqrt(g["car_sd"].values ** 2 + sigma ** 2), rounds, omega)
    return float(m), float(np.sqrt(P + omega + sigma ** 2))


def one_step(car: pd.DataFrame, omega: float, sigma: float) -> pd.Series:
    """For every team-race: the car pace forecast made before that race from
    the team's earlier races that season (NaN for a team's first race)."""
    out = {}
    for _, _, g in series(car):
        m, P, last = 0.0, 1e4, None
        for r in g.itertuples():
            if last is not None:
                P += omega * (r.Round - last)
                out[r.car_key] = m
            S = P + r.car_sd ** 2 + sigma ** 2
            K = P / S
            m, P, last = m + K * (r.car_pct - m), (1 - K) * P, r.Round
    return pd.Series(out)


def grid_effect(sk: dict, dr: pd.DataFrame, res: pd.DataFrame, form: dict) -> dict:
    """How much does a starting position say about a car's pace that weekend?

    For each driver-race: prior = car forecast before the race + driver's
    skill that season. Expected slot = rank of the prior among the starters.
    The regression of (actual race pace - prior) on (actual grid slot -
    expected slot) gives pace per grid place, in percent of lap time. Pit-lane
    starts and drivers without a prior are left out.
    """
    car = sk["car"].copy()
    car["Year"] = car["RaceKey"].str[:4].astype(int)
    car["Round"] = car["RaceKey"].str[5:].astype(int)
    pred = one_step(car, form["omega_pct2_per_race"], form["sigma_track_pct"])
    skill = sk["skill"].set_index(["DriverId", "Year"])["skill_pct"]
    d = dr.copy()
    d["car_key"] = d["TeamId"] + "|" + d["RaceKey"]
    d["prior"] = d["car_key"].map(pred) + [skill.get((a, b), np.nan) for a, b in zip(d["DriverId"], d["Year"])]
    g = res[["RaceKey", "DriverId", "GridPosition"]]
    d = d.merge(g, on=["RaceKey", "DriverId"], how="left")
    d = d[(d["GridPosition"] > 0) & d["prior"].notna()]
    d["expected"] = d.groupby("RaceKey")["prior"].rank(method="first")
    d["slot"] = d.groupby("RaceKey")["GridPosition"].rank(method="first")
    d["dev"] = d["slot"] - d["expected"]
    d["resid"] = d["delta_pct"] - d["prior"]
    w = 1 / (d["se_pct"] ** 2 + sk["tau2"])
    x, y = d["dev"].values, d["resid"].values - np.average(d["resid"], weights=w)
    beta = float(np.sum(w * x * y) / np.sum(w * x * x))
    resid = y - beta * x
    se = float(np.sqrt(np.sum((w * x * resid) ** 2)) / np.sum(w * x * x))
    # residual pace spread once the grid is known (for the engine's form draw)
    tau_after = float(np.sqrt(max(np.average(resid ** 2, weights=w) - np.average(d["se_pct"] ** 2, weights=w), 1e-6)))
    tau_before = float(np.sqrt(max(np.average(y ** 2, weights=w) - np.average(d["se_pct"] ** 2, weights=w), 1e-6)))
    return {"pct_per_grid_place": beta, "se": se, "n_driver_races": int(len(d)),
            "form_sd_before_grid_pct": tau_before, "form_sd_after_grid_pct": tau_after}


def quali_effect(sk: dict, dr: pd.DataFrame, quali: pd.DataFrame, form: dict) -> dict | None:
    """Blend of season form and this weekend's qualifying gap (I4).

    For each driver-race with a dry qualifying lap: prior = car forecast
    before the race + driver's skill that season; q = qualifying gap to the
    fastest (percent). Both are centred on the race's field mean, like the
    race pace they predict (stage A driver offset, also centred). Weighted
    least squares: race_pace = a * prior + b * q. Qualifying gaps beyond
    4 robust SD (crashes, no time set) are excluded.
    """
    if quali.empty:
        return None
    car = sk["car"].copy()
    car["Year"] = car["RaceKey"].str[:4].astype(int)
    car["Round"] = car["RaceKey"].str[5:].astype(int)
    pred = one_step(car, form["omega_pct2_per_race"], form["sigma_track_pct"])
    skill = sk["skill"].set_index(["DriverId", "Year"])["skill_pct"]
    d = dr.copy()
    d["prior"] = (d["TeamId"] + "|" + d["RaceKey"]).map(pred) + [skill.get((a, b), np.nan) for a, b in zip(d["DriverId"], d["Year"])]
    d = d.merge(quali[~quali["Wet"].astype(bool)][["RaceKey", "DriverId", "GapPct"]], on=["RaceKey", "DriverId"], how="inner")
    d = d[d["prior"].notna() & d["GapPct"].notna()]
    med, rs = d["GapPct"].median(), C.robust_sigma(d["GapPct"])
    clip = float(med + 4 * rs)
    d = d[d["GapPct"] <= clip]
    for c in ("prior", "GapPct"):
        d[c + "_c"] = d[c] - d.groupby("RaceKey")[c].transform("mean")
    w = (1 / (d["se_pct"] ** 2 + sk["tau2"])).values
    X = d[["prior_c", "GapPct_c"]].values
    y = d["delta_pct"].values
    XtW = X.T * w
    beta = np.linalg.solve(XtW @ X, XtW @ y)
    e = y - X @ beta
    meat = (X * (w * e)[:, None]).T @ (X * (w * e)[:, None])
    bread = np.linalg.inv(XtW @ X)
    se = np.sqrt(np.diag(bread @ meat @ bread))
    resid_sd = float(np.sqrt(max(np.average(e ** 2, weights=w) - np.average(d["se_pct"] ** 2, weights=w), 1e-6)))
    prior_only = y - d["prior_c"].values
    prior_sd = float(np.sqrt(max(np.average(prior_only ** 2, weights=w) - np.average(d["se_pct"] ** 2, weights=w), 1e-6)))
    return {"weight_prior": float(beta[0]), "weight_quali": float(beta[1]), "se": se.tolist(),
            "form_sd_after_quali_pct": resid_sd, "form_sd_prior_only_pct": prior_sd,
            "quali_gap_clip_pct": clip, "n_driver_races": int(len(d)), "n_races": int(d["RaceKey"].nunique())}
