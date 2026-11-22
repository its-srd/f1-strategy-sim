"""Shared data loading, identifiers, clean-lap filters and small statistics
helpers for every fitting module.

Every filter here is a structural assumption and is listed in
docs/assumptions.md (section "Clean-lap filter"). Counts of rows removed by
each rule are written to data/params/filters.json by fit_all.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import warnings

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
PARAMS = ROOT / "data" / "params"
DRY = ["SOFT", "MEDIUM", "HARD"]
EXCLUDE_RACES = {(2021, 12)}          # 2021 Spa: safety car laps only (assumption D5)
TRAFFIC_GAP_S = 1.0                   # assumption F7
OUTLIER_Z = 4.0                       # assumption F8
# numpy 2.0 + Apple Accelerate raises spurious FP flags in matmul (verified
# against lstsq on random data: identical to 1e-16).
warnings.filterwarnings("ignore", message=".*encountered in matmul")


def load():
    laps = pd.read_parquet(PROC / "laps.parquet")
    res = pd.read_csv(PROC / "results.csv", dtype={"ClassifiedPosition": str, "DriverNumber": str})
    races = pd.read_csv(PROC / "races.csv")
    laps["RaceKey"] = laps["Year"].astype(str) + "_" + laps["Round"].astype(str).str.zfill(2)
    res["RaceKey"] = res["Year"].astype(str) + "_" + res["Round"].astype(str).str.zfill(2)
    races["RaceKey"] = races["Year"].astype(str) + "_" + races["Round"].astype(str).str.zfill(2)
    # Stable identities from Jolpica: driverId, constructorId.
    ids = res[["RaceKey", "Abbreviation", "DriverId", "TeamId", "TeamName", "FullName"]]
    laps = laps.merge(ids, left_on=["RaceKey", "Driver"], right_on=["RaceKey", "Abbreviation"],
                      how="left").drop(columns="Abbreviation")
    for c in ("Rainfall", "IsAccurate", "Deleted", "PitIn", "PitOut", "IsGhostLap",
              "TrackStatusSC", "TrackStatusVSC", "TrackStatusRed", "TrackStatusYellow"):
        laps[c] = laps[c].astype(str).str.lower().eq("true")
    laps["TrackStatus"] = laps["TrackStatus"].astype("string")
    return laps, res, races


def load_quali(res: pd.DataFrame) -> pd.DataFrame:
    """Best qualifying lap per driver-race with DriverId attached (empty if the
    qualifying export has not been run)."""
    path = PROC / "quali.csv"
    if not path.exists():
        return pd.DataFrame(columns=["RaceKey", "DriverId", "GapPct", "Wet"])
    q = pd.read_csv(path)
    q["RaceKey"] = q["Year"].astype(str) + "_" + q["Round"].astype(str).str.zfill(2)
    ids = res[["RaceKey", "Abbreviation", "DriverId"]].rename(columns={"Abbreviation": "Driver"})
    return q.merge(ids, on=["RaceKey", "Driver"], how="inner")


def add_gaps(laps: pd.DataFrame) -> pd.DataFrame:
    """Physical gap at the line: time since any other car crossed it just
    before this car, at the start of the lap (previous lap end).
    Includes lapped / lapping cars, since dirty air does not care about laps."""
    laps = laps.sort_values(["RaceKey", "LapEndSessionTimeS"]).copy()
    t = laps["LapEndSessionTimeS"]
    prev_t = laps.groupby("RaceKey")["LapEndSessionTimeS"].shift(1)
    laps["GapAtLineS"] = t - prev_t          # gap to car ahead at end of this lap
    laps = laps.sort_values(["RaceKey", "Driver", "LapNumber"])
    # Gap at the START of lap L = gap at the end of lap L-1 for this driver.
    laps["GapAheadStartS"] = laps.groupby(["RaceKey", "Driver"])["GapAtLineS"].shift(1)
    return laps


def clean_mask(laps: pd.DataFrame, races: pd.DataFrame) -> tuple[pd.Series, dict]:
    """Green-flag, representative dry racing laps. Returns mask and the number of
    laps each rule removes (counted sequentially)."""
    wet_races = set(races.loc[races["WetCompoundUsed"], "RaceKey"])
    prev_status = laps.groupby(["RaceKey", "Driver"])["TrackStatus"].shift(1).fillna("1")
    rules = [
        ("excluded race (2021 Spa)", ~laps[["Year", "Round"]].apply(tuple, axis=1).isin(EXCLUDE_RACES)),
        ("ghost lap", ~laps["IsGhostLap"]),
        ("no lap time", laps["LapTimeS"].notna()),
        ("lap 1", laps["LapNumber"] > 1),
        ("pit in or out lap", ~laps["PitIn"] & ~laps["PitOut"]),
        ("not green for the whole lap", laps["TrackStatus"].fillna("") == "1"),
        ("first lap after SC/VSC/red", ~prev_status.str.contains("[4567]", regex=True)),
        ("FastF1 IsAccurate false", laps["IsAccurate"]),
        ("deleted by race control", ~laps["Deleted"]),
        ("race where wet tyres were used", ~laps["RaceKey"].isin(wet_races)),
        ("rainfall reported on lap", ~laps["Rainfall"]),
        ("not a dry compound / no tyre age", laps["Compound"].isin(DRY) & laps["TyreLife"].notna()),
        ("no driver identity", laps["DriverId"].notna()),
    ]
    mask = pd.Series(True, index=laps.index)
    removed = {}
    for name, rule in rules:
        before = int(mask.sum())
        mask &= rule.fillna(False).astype(bool)
        removed[name] = before - int(mask.sum())
    return mask, removed


# ------------------------------------------------------------ statistics
def robust_sigma(x) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return float(1.4826 * np.median(np.abs(x - np.median(x)))) if len(x) else float("nan")


def local_level(y, se, years, omega2: float, prior_var: float = 1e4, breaks=(), prior_mean: float = 0.0):
    """Random-walk (local level) Kalman filter over yearly estimates.

    State x_y = x_{y-1} + eta, eta ~ N(0, omega2 * dyears); obs y ~ N(x, se^2).
    A year in `breaks` resets the state variance to prior_var (no carry-over).
    Returns (filtered mean at last obs, filtered var, total log predictive
    density of each obs given the past)."""
    m, P, last = prior_mean, prior_var, None
    diffuse = prior_var >= 1e3
    logp = 0.0
    for yi, si, yr in sorted(zip(y, se, years), key=lambda z: z[2]):
        if last is not None:
            P += omega2 * max(yr - last, 0)
            if any(last < b <= yr for b in breaks):
                m, P = prior_mean, prior_var
        S = P + si ** 2
        if not (diffuse and P >= prior_var * 0.5):   # skip diffuse first obs
            logp += -0.5 * (np.log(2 * np.pi * S) + (yi - m) ** 2 / S)
        K = P / S
        m, P, last = m + K * (yi - m), (1 - K) * P, yr
    return m, P, logp


def ar1_level(y, se, years, phi: float, tau2: float, mean_of, breaks=()):
    """Mean-reverting track level (review 2.2): the deviation of a track's
    value from its era's pooled mean decays by phi per year, with stationary
    variance tau2 (how much tracks really differ), so an old value fades back
    to the pool instead of being kept for ever as a random walk would.

    s_y = phi^dt * s_{y-dt} + eta,  Var(s) = tau2;  obs y ~ N(mean_of(year) + s, se^2).
    A year in `breaks` starts a new era: the deviation restarts at 0 with
    variance tau2. Returns (deviation at the last obs, its variance, total log
    predictive density of each obs given the past, last year)."""
    s, P, last = 0.0, tau2, None
    logp = 0.0
    for yi, si, yr in sorted(zip(y, se, years), key=lambda z: z[2]):
        if last is not None:
            if any(last < b <= yr for b in breaks):
                s, P = 0.0, tau2
            else:
                f = phi ** (yr - last)
                s, P = f * s, f * f * P + tau2 * (1 - f * f)
        m = mean_of(yr)
        S = P + si ** 2
        logp += -0.5 * (np.log(2 * np.pi * S) + (yi - m - s) ** 2 / S)
        K = P / S
        s, P, last = s + K * (yi - m - s), (1 - K) * P, yr
    return s, P, logp, last


def ar1_project(s, P, last, target, phi, tau2, breaks=()):
    """Carry a deviation from its last year to the target year (resets apply)."""
    if last is None or any(last < b <= target for b in breaks):
        return 0.0, tau2
    f = phi ** max(target - last, 0)
    return f * s, f * f * P + tau2 * (1 - f * f)


def fit_omega(groups, breaks=(), grid=None, prior_mean=0.0, prior_var=1e4) -> tuple[float, dict]:
    """Pick the random-walk variance that maximises the one-step-ahead
    predictive likelihood across many series. groups: list of (y, se, years)."""
    grid = grid if grid is not None else np.concatenate([[0.0], np.logspace(-6, 1, 50)])
    scores = []
    for w in grid:
        scores.append(sum(local_level(y, s, yr, w, breaks=breaks, prior_mean=prior_mean,
                                      prior_var=prior_var)[2] for y, s, yr in groups))
    i = int(np.nanargmax(scores))
    return float(grid[i]), {"grid_best": float(grid[i]), "log_pred": float(scores[i])}


def eb_normal(est, se):
    """Normal-normal empirical Bayes: tau^2 by method of moments (DerSimonian-
    Laird), shrunken estimates. Returns mean, tau2, shrunk, shrunk_sd."""
    est, se = np.asarray(est, float), np.asarray(se, float)
    w = 1 / se ** 2
    mu = np.sum(w * est) / np.sum(w)
    q = np.sum(w * (est - mu) ** 2)
    tau2 = max(0.0, (q - (len(est) - 1)) / (np.sum(w) - np.sum(w ** 2) / np.sum(w)))
    B = se ** 2 / (se ** 2 + tau2) if tau2 > 0 else np.ones_like(se)
    shrunk = B * mu + (1 - B) * est
    sd = np.sqrt((1 - B) * se ** 2 + B ** 2 * (1 / np.sum(w)))
    return float(mu), float(tau2), shrunk, sd


def write_json(name: str, obj) -> Path:
    PARAMS.mkdir(parents=True, exist_ok=True)
    p = PARAMS / name
    p.write_text(json.dumps(_clean(obj), indent=1, default=_np_default, allow_nan=False))
    return p


def _clean(o):
    """Recursively turn NaN/inf into None and numpy scalars into Python."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return [_clean(v) for v in o.tolist()]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 6)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _np_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else round(float(o), 6)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    raise TypeError(type(o))
