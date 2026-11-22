"""Overtaking model: probability that a car gets past the car directly ahead
on one lap.

Sample: every pair of consecutive cars on the same lap at the end of lap L-1,
within WINDOW_S seconds of each other. Both laps L-1 and L must be green for
both cars, neither car pits on either lap, no rain, lap L >= 2.
Outcome: the car behind is ahead at the end of lap L.

    logit P(pass) = track[k] + era[e] + b_pace * pace_adv + b_gap * gap
                  + b_pace_gap * pace_adv * gap

pace_adv = expected lap-time advantage of the car behind (s/lap), from the
stage A fit of that race (driver offset + compound offset + tyre-age terms).
track[k] is L2-penalised toward 0 (= the pooled level). The penalty is chosen
by 5-fold cross-validation over races, so tracks with little data borrow from
the pool. Era offsets (2018-21, 2022-25, 2026) are fitted, not assumed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import common as C

WINDOW_S = 3.0           # assumption O1
ERAS = [(2018, 2021, "2018-21"), (2022, 2025, "2022-25"), (2026, 2100, "2026")]


def era_of(y):
    return next(n for a, b, n in ERAS if a <= y <= b)


def expected_pace(laps, rf, dr):
    """Expected lap time (s) per driver-lap from the race's stage A fit."""
    rf = rf.set_index("RaceKey")
    dmap = dr.set_index(["RaceKey", "DriverId"])["delta_s"]
    out = pd.Series(np.nan, index=laps.index)
    keys = laps["RaceKey"].isin(rf.index)
    L = laps[keys]
    r = rf.loc[L["RaceKey"]]
    comp = L["Compound"].values
    age = L["TyreLife"].values.astype(float)
    off = np.zeros(len(L)); slope = np.full(len(L), np.nan)
    for c in C.DRY:
        m = comp == c
        off[m] = r[f"offset_{c}"].values[m]
        slope[m] = r[f"slope_{c}"].values[m]
    delta = pd.Series(list(zip(L["RaceKey"], L["DriverId"]))).map(dmap).values
    pred = r["base_s"].values + delta + off + slope * age + r["curve"].values * age ** 2 \
        + r["fuel"].values * L["LapNumber"].values + r["fuel2"].values * L["LapNumber"].values ** 2
    out[L.index] = pred
    return out


def build_pairs(laps, races, rf, dr):
    laps = laps.copy()
    laps["pred"] = expected_pace(laps, rf, dr)
    wet = set(races.loc[races["WetCompoundUsed"], "RaceKey"])
    ok = (~laps["RaceKey"].isin(wet)) & laps["Position"].notna() & ~laps["IsGhostLap"]
    laps = laps[ok]
    cols = ["RaceKey", "Driver", "LapNumber", "Position", "LapEndSessionTimeS", "TrackStatus",
            "PitIn", "PitOut", "Rainfall", "pred", "Year", "CircuitId"]
    cur = laps[cols]
    nxt = cur[["RaceKey", "Driver", "LapNumber", "Position", "TrackStatus", "PitIn", "PitOut", "Rainfall"]].copy()
    nxt["LapNumber"] -= 1                 # lap L joined onto lap L-1 rows
    m = cur.merge(nxt, on=["RaceKey", "Driver", "LapNumber"], suffixes=("", "_next"))
    m = m.sort_values(["RaceKey", "LapNumber", "Position"])
    ahead = m.groupby(["RaceKey", "LapNumber"]).shift(1)
    pair = m.join(ahead, rsuffix="_A")
    pair = pair[pair["Position"] == pair["Position_A"] + 1]
    pair["gap"] = pair["LapEndSessionTimeS"] - pair["LapEndSessionTimeS_A"]
    clean = (
        (pair["gap"] > 0) & (pair["gap"] < WINDOW_S) & (pair["LapNumber"] >= 1)
        & (pair["TrackStatus"].fillna("") == "1") & (pair["TrackStatus_A"].fillna("") == "1")
        & (pair["TrackStatus_next"].fillna("") == "1") & (pair["TrackStatus_next_A"].fillna("") == "1")
        & ~(pair["PitIn"] | pair["PitOut"] | pair["PitIn_next"] | pair["PitOut_next"]).astype(bool)
        & ~(pair["PitIn_A"] | pair["PitOut_A"] | pair["PitIn_next_A"] | pair["PitOut_next_A"]).astype(bool)
        & ~(pair["Rainfall_next"].astype(bool) | pair["Rainfall_next_A"].astype(bool))
        & pair["pred"].notna() & pair["pred_A"].notna()
    )
    p = pair[clean].copy()
    p["passed"] = (p["Position_next"] < p["Position_next_A"]).astype(float)
    p["pace_adv"] = p["pred_A"] - p["pred"]          # >0: car behind is faster
    p["era"] = p["Year"].map(era_of)
    return p


def design(p, tracks, eras):
    ti = {t: i for i, t in enumerate(tracks)}
    X_t = np.zeros((len(p), len(tracks)))
    X_t[np.arange(len(p)), p["TrackKey"].map(ti).values] = 1
    X_e = np.column_stack([(p["era"] == e).astype(float).values for e in eras])
    X_c = np.column_stack([p["pace_adv"].values, p["gap"].values, p["pace_adv"].values * p["gap"].values])
    return np.hstack([X_t, X_e, X_c])


def logit_fit(X, y, pen):
    beta = np.zeros(X.shape[1])
    for _ in range(50):
        eta = X @ beta
        mu = 1 / (1 + np.exp(-eta))
        W = mu * (1 - mu)
        g = X.T @ (y - mu) - pen * beta
        H = (X * W[:, None]).T @ X + np.diag(pen)
        step = np.linalg.solve(H, g)
        beta += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return beta, np.linalg.inv(H)


def run(laps, races, rf, dr, track_key, target_year: int = 2026):
    p = build_pairs(laps, races, rf, dr)
    p["TrackKey"] = p["RaceKey"].map(track_key).fillna(p["CircuitId"])
    tracks = sorted(p["TrackKey"].unique())
    eras = [n for *_, n in ERAS if (p["era"] == n).any()]      # only eras with data
    X = design(p, tracks, eras)
    y = p["passed"].values
    nt = len(tracks)

    def penvec(lam):
        v = np.zeros(X.shape[1]); v[:nt] = lam
        return v

    # 5-fold CV over races for the track-intercept penalty.
    rk = p["RaceKey"].unique()
    rng = np.random.default_rng(0)
    fold = dict(zip(rk, rng.integers(0, 5, len(rk))))
    f = p["RaceKey"].map(fold).values
    grid = [0.1, 1, 3, 10, 30, 100, 300, 1000]
    cv = []
    for lam in grid:
        ll = 0.0
        for k in range(5):
            tr, te = f != k, f == k
            b, _ = logit_fit(X[tr], y[tr], penvec(lam))
            mu = np.clip(1 / (1 + np.exp(-(X[te] @ b))), 1e-9, 1 - 1e-9)
            ll += np.sum(y[te] * np.log(mu) + (1 - y[te]) * np.log(1 - mu))
        cv.append(ll)
    lam = grid[int(np.argmax(cv))]
    beta, cov = logit_fit(X, y, penvec(lam))
    se = np.sqrt(np.diag(cov))
    counts = p.groupby("TrackKey").agg(pairs=("passed", "size"), passes=("passed", "sum"),
                                       races=("RaceKey", "nunique"))
    rate_close = p[p["gap"] < 1.0].groupby("TrackKey")["passed"].mean()
    track_out = {t: {"intercept": beta[i], "se": se[i], **counts.loc[t].to_dict(),
                     "raw_pass_rate_within_1s": rate_close.get(t)} for i, t in enumerate(tracks)}
    era_out = {e: {"offset": beta[nt + j], "se": se[nt + j],
                   "pairs": int((p["era"] == e).sum())} for j, e in enumerate(eras)}
    names = ["pace_adv", "gap", "pace_adv_x_gap"]
    coef = {n: {"beta": beta[nt + len(eras) + j], "se": se[nt + len(eras) + j]} for j, n in enumerate(names)}
    # Calibration on the fitted data: predicted vs observed by decile.
    mu = 1 / (1 + np.exp(-(X @ beta)))
    dec = pd.qcut(mu, 10, labels=False, duplicates="drop")
    calib = pd.DataFrame({"pred": mu, "obs": y, "d": dec}).groupby("d").mean().round(4).to_dict("list")
    cur = era_of(target_year)
    current = era_out.get(cur, era_out[eras[-1]])            # newest era with data if target era has none yet
    return {"current_era": cur if cur in era_out else eras[-1], "current_era_offset": current["offset"],
            "tracks": track_out, "eras": era_out, "coef": coef, "penalty": lam,
            "cv_loglik": dict(zip(map(str, grid), cv)), "n_pairs": int(len(p)),
            "n_passes": int(y.sum()), "window_s": WINDOW_S, "calibration": calib}


if __name__ == "__main__":
    import track_pace as T
    laps, res, races = C.load()
    rf = pd.read_csv(C.PROC / "fits" / "race_fits.csv")
    dr = pd.read_csv(C.PROC / "fits" / "driver_race_pace.csv")
    tk = dict(zip(rf.RaceKey, T.track_keys(rf)))
    o = run(laps, races, rf, dr, tk)
    print("pairs", o["n_pairs"], "passes", o["n_passes"], "penalty", o["penalty"])
    print("coef", {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in o["coef"].items()})
    print("eras", {k: {kk: round(vv, 3) for kk, vv in v.items()} for k, v in o["eras"].items()})
    tr = sorted(o["tracks"].items(), key=lambda kv: kv[1]["intercept"])
    print("hardest:", [(k, round(v["intercept"], 2), int(v["pairs"])) for k, v in tr[:5]])
    print("easiest:", [(k, round(v["intercept"], 2), int(v["pairs"])) for k, v in tr[-5:]])
    print("calibration", o["calibration"])
