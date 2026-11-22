"""Stage B: separate driver skill from car pace (Gaussian mixed model).

For each driver-race pace offset y (percent of lap time, from stage A):

    y = car[team, race] + skill[driver, season] + e,   e ~ N(0, se^2 + tau^2)

* car[team, race]: one free parameter per team per race (vague prior). This
  makes skill identifiable only through teammate comparisons, and drivers who
  changed teams chain those comparisons together.
* skill[driver, season]: random walk across seasons,
  skill[y] = skill[y-1] + eta, eta ~ N(0, omega^2 * years elapsed),
  first season ~ N(0, sigma0^2). omega^2 is the data-driven era weighting:
  the larger it is, the less old seasons count for current skill.
* tau^2, omega^2, sigma0^2 maximise the marginal likelihood. Then two passes
  of outlier down-weighting: |standardised residual| > 3 gets its variance
  inflated so the weight matches a Huber loss.

Negative skill = faster. Units: percent of lap time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize

import common as C

CAR_PRIOR_VAR = 100.0     # vague: car offsets are within a few percent
HUBER_K = 3.0             # assumption S3


def build(dr: pd.DataFrame, break_year: int | None = None):
    dr = dr.copy()
    dr["car_key"] = dr["TeamId"] + "|" + dr["RaceKey"]
    dr["skill_key"] = dr["DriverId"] + "|" + dr["Year"].astype(str)
    cars = sorted(dr["car_key"].unique())
    skills = (dr[["DriverId", "Year", "skill_key"]].drop_duplicates()
              .sort_values(["DriverId", "Year"]).reset_index(drop=True))
    ci = {k: i for i, k in enumerate(cars)}
    si = {k: i + len(cars) for i, k in enumerate(skills["skill_key"])}
    n, p = len(dr), len(cars) + len(skills)
    X = np.zeros((n, p))
    X[np.arange(n), dr["car_key"].map(ci).values] = 1
    X[np.arange(n), dr["skill_key"].map(si).values] = 1
    # Random-walk structure: list of (index, prev index or None, years gap).
    chain = []
    for drv, g in skills.groupby("DriverId"):
        prev = None
        for _, r in g.iterrows():
            idx = si[r.skill_key]
            if prev and break_year is not None and prev[1] < break_year <= r.Year:
                prev = None          # regulation break: no carry-over of skill
            chain.append((idx, prev[0] if prev else None, (r.Year - prev[1]) if prev else 0))
            prev = (idx, r.Year)
    return dr, X, cars, skills, chain


def prior_precision(p, n_cars, chain, omega2, sigma02):
    P = np.zeros((p, p))
    P[np.arange(n_cars), np.arange(n_cars)] = 1 / CAR_PRIOR_VAR
    for idx, prev, gap in chain:
        if prev is None:
            P[idx, idx] += 1 / sigma02
        else:
            w = 1 / (omega2 * gap)
            P[idx, idx] += w; P[prev, prev] += w
            P[idx, prev] -= w; P[prev, idx] -= w
    return P


def marginal(theta, X, y, se2, n_cars, chain, infl):
    tau2, omega2, sigma02 = np.exp(theta)
    r = (se2 + tau2) * infl
    P = prior_precision(X.shape[1], n_cars, chain, omega2, sigma02)
    Xw = X / r[:, None]
    Q = P + X.T @ Xw
    b = Xw.T @ y
    try:
        cQ = cho_factor(Q, lower=True)
        cP = cho_factor(P, lower=True)
    except np.linalg.LinAlgError:
        return 1e12, None
    mean = cho_solve(cQ, b)
    logdetQ = 2 * np.sum(np.log(np.diag(cQ[0])))
    logdetP = 2 * np.sum(np.log(np.diag(cP[0])))
    ll = -0.5 * (np.sum(np.log(2 * np.pi * r)) + logdetQ - logdetP + np.sum(y ** 2 / r) - b @ mean)
    return -ll, (mean, cQ, r)


def fit(dr: pd.DataFrame, break_year: int | None = None) -> dict:
    dr, X, cars, skills, chain = build(dr, break_year)
    y, se2 = dr["delta_pct"].values, dr["se_pct"].values ** 2
    infl = np.ones(len(y))
    theta = np.log([0.05, 0.01, 0.1])
    for it in range(3):
        opt = minimize(lambda t: marginal(t, X, y, se2, len(cars), chain, infl)[0], theta,
                       method="Nelder-Mead", options={"xatol": 1e-3, "fatol": 1e-3, "maxiter": 400})
        theta = opt.x
        _, (mean, cQ, r) = marginal(theta, X, y, se2, len(cars), chain, infl)
        z = (y - X @ mean) / np.sqrt(r)
        new = np.where(np.abs(z) > HUBER_K, (np.abs(z) / HUBER_K), 1.0) * infl
        if it < 2:
            infl = np.maximum(infl, new)
    cov_full = cho_solve(cQ, np.eye(X.shape[1]))
    cov_diag = np.diag(cov_full)
    tau2, omega2, sigma02 = np.exp(theta)

    car = pd.DataFrame({"car_key": cars, "car_pct": mean[:len(cars)],
                        "car_sd": np.sqrt(cov_diag[:len(cars)])})
    car[["TeamId", "RaceKey"]] = car["car_key"].str.split("|", expand=True)
    sk = skills.copy()
    sk["skill_pct"] = mean[len(cars):]
    sk["skill_sd"] = np.sqrt(cov_diag[len(cars):])
    counts = dr.groupby("skill_key").agg(n_races=("RaceKey", "nunique"),
                                         teammates=("TeamId", "nunique"))
    sk = sk.join(counts, on="skill_key")
    dr["resid_z"] = z
    # Posterior correlation between each driver's skill and the car values of
    # the team-races they drove (identified only through teammates, so these
    # are strongly negative; the engine must draw them jointly, E1).
    ci = {k: i for i, k in enumerate(cars)}
    si = {k: i + len(cars) for i, k in enumerate(skills["skill_key"])}
    corr = {}
    for _, r in dr.iterrows():
        a, b = ci[r.car_key], si[r.skill_key]
        corr[(r.DriverId, r.RaceKey)] = float(cov_full[a, b] / np.sqrt(cov_full[a, a] * cov_full[b, b]))
    return {"corr_car_skill": corr, "car": car, "skill": sk, "tau2": tau2, "omega2": omega2, "sigma02": sigma02,
            "n_obs": len(y), "n_downweighted": int((infl > 1).sum()), "data": dr,
            "loglik": -opt.fun}


def project(sk: pd.DataFrame, omega2: float, year: int) -> pd.DataFrame:
    """Latest skill per driver, projected to `year` (variance grows by
    omega^2 per year since the driver's last season)."""
    last = sk.sort_values("Year").groupby("DriverId").tail(1).copy()
    gap = (year - last["Year"]).clip(lower=0)
    last["proj_sd"] = np.sqrt(last["skill_sd"] ** 2 + omega2 * gap)
    last["years_since"] = gap
    tot = sk.groupby("DriverId").agg(career_races=("n_races", "sum"),
                                     first_season=("Year", "min"))
    return last.join(tot, on="DriverId")


if __name__ == "__main__":
    import time
    t = time.time()
    dr = pd.read_csv(C.PROC / "fits" / "driver_race_pace.csv")
    f = fit(dr)
    print(f"tau={np.sqrt(f['tau2']):.3f}%  omega={np.sqrt(f['omega2']):.3f}%/yr  "
          f"sigma0={np.sqrt(f['sigma02']):.3f}%  obs={f['n_obs']}  "
          f"downweighted={f['n_downweighted']}  {time.time() - t:.0f}s")
    pj = project(f["skill"], f["omega2"], 2026)
    print(pj[pj.Year >= 2025].sort_values("skill_pct")[
        ["DriverId", "Year", "skill_pct", "proj_sd", "career_races"]].round(3).to_string(index=False))
