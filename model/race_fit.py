"""Stage A: one lap-time regression per dry race.

    LapTime = base
            + delta[driver]                      (car + driver, this race)
            + offset[compound]                   (0 for the reference compound)
            + slope[compound] * TyreAge
            + curve * TyreAge^2                  (one per race, all compounds)
            + fuel * LapNumber + fuel2 * LapNumber^2   (fuel burn + track evolution)
            + traffic * 1[gap ahead < 1 s]
            + noise

Fitted by OLS on clean laps (common.clean_mask), with one pass of outlier
removal (|residual| > OUTLIER_Z robust sigma). Standard errors are
cluster-robust by driver-stint, because laps in a stint are not independent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import common as C

MIN_DRIVER_LAPS = 5     # assumption F9
MIN_COMPOUND_STINTS = 3  # assumption F10
MIN_COMPOUND_LAPS = 30   # assumption F10


def _ols(X, y, groups):
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    e = y - X @ beta
    # Cluster-robust (CR1) covariance by driver-stint.
    meat = np.zeros((X.shape[1], X.shape[1]))
    for g in np.unique(groups):
        idx = groups == g
        s = X[idx].T @ e[idx]
        meat += np.outer(s, s)
    G, n, k = len(np.unique(groups)), len(y), X.shape[1]
    factor = G / max(G - 1, 1) * (n - 1) / max(n - k, 1)
    cov = factor * XtX_inv @ meat @ XtX_inv
    return beta, e, cov


def fit_race(d: pd.DataFrame) -> dict | None:
    counts = d["DriverId"].value_counts()
    d = d[d["DriverId"].isin(counts[counts >= MIN_DRIVER_LAPS].index)]
    # A compound is estimable only if several independent stints ran it.
    stints = d.assign(_k=d["DriverId"] + d["Stint"].astype(str)).groupby("Compound")["_k"].nunique()
    nlaps = d["Compound"].value_counts()
    comps = [c for c in C.DRY if stints.get(c, 0) >= MIN_COMPOUND_STINTS
             and nlaps.get(c, 0) >= MIN_COMPOUND_LAPS]
    dropped_compound_laps = int((~d["Compound"].isin(comps)).sum())
    d = d[d["Compound"].isin(comps)]
    counts = d["DriverId"].value_counts()
    d = d[d["DriverId"].isin(counts[counts >= MIN_DRIVER_LAPS].index)]
    if d["DriverId"].nunique() < 6 or not comps:
        return None
    ref = "MEDIUM" if "MEDIUM" in comps else d["Compound"].value_counts().index[0]
    keep = None
    for _ in range(2):
        dd = d if keep is None else d[keep]
        drivers = sorted(dd["DriverId"].unique())
        cols, names = [], []
        for drv in drivers:
            cols.append((dd["DriverId"] == drv).astype(float).values); names.append(("delta", drv))
        age = dd["TyreLife"].values.astype(float)
        for c in comps:
            ind = (dd["Compound"] == c).astype(float).values
            if c != ref:
                cols.append(ind); names.append(("offset", c))
            cols.append(ind * age); names.append(("slope", c))
        cols.append(age ** 2); names.append(("curve", ""))
        cols.append(dd["LapNumber"].values.astype(float)); names.append(("fuel", ""))
        # M1b: fuel burn + track evolution is curved; the lap^2 term removes the
        # bias it otherwise puts into first-stint (often SOFT) wear estimates.
        cols.append(dd["LapNumber"].values.astype(float) ** 2); names.append(("fuel2", ""))
        cols.append((dd["GapAheadStartS"].fillna(99).values < C.TRAFFIC_GAP_S).astype(float))
        names.append(("traffic", ""))
        X = np.column_stack(cols)
        y = dd["LapTimeS"].values.astype(float)
        groups = (dd["DriverId"] + "_" + dd["Stint"].astype(str)).values
        # Drop columns with no variation (e.g. compound used by one stint only).
        ok = X.std(axis=0) > 0
        ok[[i for i, n in enumerate(names) if n[0] == "delta"]] = True
        X, names_ok = X[:, ok], [n for n, o in zip(names, ok) if o]
        beta, e, cov = _ols(X, y, groups)
        sig = C.robust_sigma(e)
        if keep is None:
            keep = pd.Series(np.abs(e) <= C.OUTLIER_Z * sig, index=dd.index).reindex(d.index).fillna(False)
            n_outliers = int((~keep).sum())
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    # SE of each driver offset relative to the race mean (the exported
    # quantity): contrast M V M' with M = I - 11'/k. The raw dummy SE also
    # carries the shared uncertainty of base and fuel, which cancels here.
    di = [i for i, n in enumerate(names_ok) if n[0] == "delta"]
    k = len(di)
    Mc = np.eye(k) - np.ones((k, k)) / k
    Vd = cov[np.ix_(di, di)]
    delta_se = dict(zip([names_ok[i][1] for i in di], np.sqrt(np.clip(np.diag(Mc @ Vd @ Mc.T), 0, None))))
    out = {"delta_se": delta_se,"dropped_compound_laps": dropped_compound_laps, "names": names_ok, "beta": beta, "se": se, "sigma": sig, "n_laps": len(y),
           "n_outliers": n_outliers, "ref_compound": ref, "drivers": drivers,
           "n_driver_laps": dd["DriverId"].value_counts().to_dict(),
           "max_age": dd.groupby("Compound")["TyreLife"].max().to_dict(),
           "laps_by_compound": dd["Compound"].value_counts().to_dict()}
    return out


def run(laps: pd.DataFrame, mask: pd.Series, races: pd.DataFrame):
    clean = laps[mask]
    race_rows, driver_rows = [], []
    info = races.set_index("RaceKey")
    for key, d in clean.groupby("RaceKey"):
        f = fit_race(d)
        if f is None:
            continue
        coef = {n: (b, s) for n, b, s in zip(f["names"], f["beta"], f["se"])}
        deltas = np.array([coef[("delta", drv)][0] for drv in f["drivers"]])
        base = float(deltas.mean())            # average driver, ref compound, age 0, lap 0
        r = info.loc[key]
        row = {"RaceKey": key, "Year": int(r.Year), "Round": int(r.Round),
               "CircuitId": r.CircuitId, "base_s": base, "sigma_s": f["sigma"],
               "n_laps": f["n_laps"], "n_outliers": f["n_outliers"],
               "dropped_compound_laps": f["dropped_compound_laps"],
               "ref_compound": f["ref_compound"], "MeanTrackTemp": r.get("MeanTrackTemp"),
               "TotalLaps": r.TotalLaps}
        for kind in ("curve", "fuel", "fuel2", "traffic"):
            b, s = coef.get((kind, ""), (np.nan, np.nan))
            row[f"{kind}"], row[f"{kind}_se"] = b, s
        for c in C.DRY:
            b, s = coef.get(("slope", c), (np.nan, np.nan))
            row[f"slope_{c}"], row[f"slope_{c}_se"] = b, s
            if c == f["ref_compound"]:
                b, s = 0.0, 0.0
            else:
                b, s = coef.get(("offset", c), (np.nan, np.nan))
            row[f"offset_{c}"], row[f"offset_{c}_se"] = b, s
            row[f"laps_{c}"] = f["laps_by_compound"].get(c, 0)
            row[f"maxage_{c}"] = f["max_age"].get(c, np.nan)
        race_rows.append(row)
        team = d.groupby("DriverId")["TeamId"].agg(lambda s: s.mode().iloc[0])
        for drv, dlt in zip(f["drivers"], deltas):
            driver_rows.append({
                "RaceKey": key, "Year": int(r.Year), "CircuitId": r.CircuitId,
                "DriverId": drv, "TeamId": team[drv],
                "delta_s": dlt - base, "se_s": f["delta_se"][drv],
                "delta_pct": 100 * (dlt - base) / base,
                "se_pct": 100 * f["delta_se"][drv] / base,
                "n_laps": f["n_driver_laps"][drv]})
    return pd.DataFrame(race_rows), pd.DataFrame(driver_rows)


if __name__ == "__main__":
    import time
    t = time.time()
    laps, res, races = C.load()
    laps = C.add_gaps(laps)
    mask, _ = C.clean_mask(laps, races)
    rf, dr = run(laps, mask, races)
    out = C.PROC / "fits"
    out.mkdir(exist_ok=True)
    rf.to_csv(out / "race_fits.csv", index=False)
    dr.to_csv(out / "driver_race_pace.csv", index=False)
    print(f"{len(rf)} races fitted, {len(dr)} driver-races, {time.time() - t:.0f}s")
