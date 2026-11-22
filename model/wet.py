"""Wet-weather model, pooled across every race where wet tyres were used.

The wet sample is too small for per-track or per-driver wet parameters
(23 races since 2018), so everything here is pooled and labelled that way.

Track state ("wetness") = the INTERMEDIATE lap-time ratio i_L: the median
inter lap time on lap L divided by the dry reference lap for that track and
lap. The dry reference is base + fuel * lap from the nearest-year dry race at
the same track (stage A).

Fitted:
  * slick - inter ratio difference as a linear function of i  -> crossover i*
  * wet   - inter ratio difference as a linear function of i  -> crossover
  * dynamics: i_{L+1} = c + rho * i_L + kappa * rain_L (pooled)
  * driver wet skill: extra between-driver variance in wet teammate gaps
    beyond dry skill (empirical Bayes). If ~0, wet pace = dry skill.
All CIs are bootstrap over races (race = cluster).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import common as C

N_BOOT = 500
MIN_CARS = 2      # assumption W2: cars per compound on a lap to compare compounds


def dry_reference(races, rf, track_key):
    rf = rf.assign(TrackKey=rf["RaceKey"].map(track_key))
    out = {}
    for _, r in races[races["WetCompoundUsed"]].iterrows():
        tk = track_key.get(r.RaceKey, r.CircuitId)
        cand = rf[rf["TrackKey"].fillna(rf["CircuitId"]) == tk]
        if cand.empty:
            continue
        c = cand.iloc[(cand["Year"] - r.Year).abs().argsort().iloc[0]]
        out[r.RaceKey] = {"base": c.base_s, "fuel": c.fuel, "fuel2": c.fuel2, "ref_year": int(c.Year)}
    return out


def lap_table(laps, races, ref):
    wl = laps[laps["RaceKey"].isin(ref.keys())].copy()
    prev = wl.groupby(["RaceKey", "Driver"])["TrackStatus"].shift(1).fillna("1")
    ok = (wl["LapNumber"] > 1) & ~wl["PitIn"] & ~wl["PitOut"] & wl["LapTimeS"].notna() \
        & (wl["TrackStatus"].fillna("") == "1") & ~prev.str.contains("[4567]", regex=True) & ~wl["IsGhostLap"]
    wl = wl[ok].copy()
    wl["dry_ref"] = [ref[k]["base"] + ref[k]["fuel"] * l + ref[k]["fuel2"] * l * l for k, l in zip(wl["RaceKey"], wl["LapNumber"])]
    wl["ratio"] = wl["LapTimeS"] / wl["dry_ref"]
    wl["grp"] = np.where(wl["Compound"].isin(C.DRY), "SLICK", wl["Compound"])
    g = wl.groupby(["RaceKey", "LapNumber", "grp"])["ratio"].agg(["median", "count"]).unstack("grp")
    rain = laps[laps["RaceKey"].isin(ref.keys())].groupby(["RaceKey", "LapNumber"])["Rainfall"].mean() > 0.5
    t = pd.DataFrame(index=g.index)
    for k in ("SLICK", "INTERMEDIATE", "WET"):
        t[k] = g["median"].get(k)
        t[f"n_{k}"] = g["count"].get(k)
    t["rain"] = rain.reindex(t.index).fillna(False)
    return t.reset_index(), wl


def linfit(x, y):
    A = np.column_stack([np.ones_like(x), x])
    return np.linalg.lstsq(A, y, rcond=None)[0]


def boot(df, fn, n=N_BOOT):
    races = df["RaceKey"].unique()
    rng = np.random.default_rng(1)
    vals = []
    for _ in range(n):
        pick = rng.choice(races, len(races), replace=True)
        d = pd.concat([df[df.RaceKey == r] for r in pick])
        try:
            vals.append(fn(d))
        except Exception:
            pass
    return np.array(vals)


def run(laps, races, rf, dr, track_key, skill_proj):
    ref = dry_reference(races, rf, track_key)
    t, wl = lap_table(laps, races, ref)
    out = {"n_wet_races": int(races["WetCompoundUsed"].sum()), "n_with_dry_reference": len(ref),
           "races_used": sorted(ref.keys())}

    def cross(d, k):
        d = d[(d[f"n_{k}"] >= MIN_CARS) & (d["n_INTERMEDIATE"] >= MIN_CARS)]
        a, b = linfit(d["INTERMEDIATE"].values, (d[k] - d["INTERMEDIATE"]).values)
        return np.array([a, b, -a / b, len(d), d.RaceKey.nunique()])

    for k in ("SLICK", "WET"):
        est = cross(t, k)
        bs = boot(t, lambda d: cross(d, k)[:3])
        out[f"{k.lower()}_minus_inter"] = {
            "intercept": est[0], "slope_per_inter_ratio": est[1], "crossover_inter_ratio": est[2],
            "crossover_ci95": np.nanpercentile(bs[:, 2], [2.5, 97.5]).tolist() if len(bs) else None,
            "slope_ci95": np.nanpercentile(bs[:, 1], [2.5, 97.5]).tolist() if len(bs) else None,
            "n_laps": int(est[3]), "n_races": int(est[4])}

    # Dynamics of the inter ratio (only laps where inters were run on both laps).
    d = t[t["n_INTERMEDIATE"] >= 3].sort_values(["RaceKey", "LapNumber"]).copy()
    d["next"] = d.groupby("RaceKey")["INTERMEDIATE"].shift(-1)
    d["gap"] = d.groupby("RaceKey")["LapNumber"].shift(-1) - d["LapNumber"]
    d = d[(d["gap"] == 1) & d["next"].notna()]

    def dyn(dd, col="INTERMEDIATE"):
        A = np.column_stack([np.ones(len(dd)), dd[col].values, dd["rain"].astype(float).values])
        return np.linalg.lstsq(A, dd["next"].values, rcond=None)[0]
    est = dyn(d)
    bs = boot(d, dyn)
    out["dynamics"] = {"c": est[0], "rho": est[1], "kappa_rain": est[2],
                       "rho_ci95": np.percentile(bs[:, 1], [2.5, 97.5]).tolist(),
                       "kappa_ci95": np.percentile(bs[:, 2], [2.5, 97.5]).tolist(),
                       "stationary_dry_level": est[0] / (1 - est[1]) if est[1] < 1 else None,
                       "n_lap_pairs": int(len(d)), "n_races": int(d.RaceKey.nunique()),
                       "resid_sd": float(np.std(d["next"] - np.column_stack(
                           [np.ones(len(d)), d["INTERMEDIATE"], d["rain"].astype(float)]) @ est))}
    # State on the best tyre (min over compounds) and the effect of rain on it.
    t2 = t.copy()
    t2["best"] = t2[["SLICK", "INTERMEDIATE", "WET"]].min(axis=1)
    t2 = t2.sort_values(["RaceKey", "LapNumber"])
    t2["next"] = t2.groupby("RaceKey")["best"].shift(-1)
    t2["gap"] = t2.groupby("RaceKey")["LapNumber"].shift(-1) - t2["LapNumber"]
    t2 = t2[(t2["gap"] == 1) & t2["next"].notna() & t2["best"].notna()]
    est2 = dyn(t2, "best")
    bs2 = boot(t2, lambda dd: dyn(dd, "best"))
    out["dynamics_best_tyre"] = {"c": est2[0], "rho": est2[1], "kappa_rain": est2[2],
                                 "kappa_ci95": np.percentile(bs2[:, 2], [2.5, 97.5]).tolist(),
                                 "n_lap_pairs": int(len(t2)), "n_races": int(t2.RaceKey.nunique())}
    # Empirical wetness trajectories (best-tyre ratio per lap) for resampling.
    out["trajectories"] = {rk: g.sort_values("LapNumber")[["LapNumber", "best", "rain"]].assign(
        best=lambda x: x["best"].round(4)).values.tolist()
        for rk, g in t.assign(best=t[["SLICK", "INTERMEDIATE", "WET"]].min(axis=1)).dropna(subset=["best"]).groupby("RaceKey")}
    out["inter_ratio_observed_range"] = [float(t["INTERMEDIATE"].quantile(q)) for q in (0.05, 0.5, 0.95)]

    # Revealed-preference crossover: inter ratio on laps where the field is
    # switching between slicks and inters (25-75% of running cars on slicks).
    sw = t[(t["n_INTERMEDIATE"] >= 1) & (t["n_SLICK"] >= 1)].copy()
    sw["share_slick"] = sw["n_SLICK"] / (sw["n_SLICK"] + sw["n_INTERMEDIATE"] + sw["n_WET"].fillna(0))
    sw = sw[(sw["share_slick"] >= 0.25) & (sw["share_slick"] <= 0.75)]
    per_race = sw.groupby("RaceKey")["INTERMEDIATE"].median()
    bs = [np.median(np.random.default_rng(i).choice(per_race.values, len(per_race))) for i in range(N_BOOT)]
    out["switch_crossover"] = {"inter_ratio": float(per_race.median()),
                               "ci95": np.percentile(bs, [2.5, 97.5]).tolist(),
                               "n_races": int(len(per_race)), "n_laps": int(len(sw))}

    # Driver wet skill: teammate gap on inter/wet laps (same lap, same compound)
    # minus the gap predicted by dry skill.
    sk = skill_proj.set_index(["DriverId", "Year"])["skill_pct"]
    w = wl[wl["Compound"].isin(["INTERMEDIATE", "WET"])].copy()
    w["lap_med"] = w.groupby(["RaceKey", "LapNumber", "Compound"])["ratio"].transform("median")
    w["rel_pct"] = 100 * (w["ratio"] / w["lap_med"] - 1)
    per = w.groupby(["RaceKey", "Year", "DriverId", "TeamId"])["rel_pct"].agg(
        ["median", "count", lambda s: C.robust_sigma(s)]).reset_index()
    per = per.rename(columns={per.columns[-1]: "rsd"})
    per = per[per["count"] >= 5]
    rows = []
    for (rk, team), g in per.groupby(["RaceKey", "TeamId"]):
        if len(g) != 2:
            continue
        a, b = g.iloc[0], g.iloc[1]
        sa, sb = sk.get((a.DriverId, a.Year)), sk.get((b.DriverId, b.Year))
        if sa is None or sb is None:
            continue
        # SE of each driver's median from that driver's own lap spread.
        se = 1.253 * np.sqrt(a["rsd"] ** 2 / a["count"] + b["rsd"] ** 2 / b["count"])
        rows.append({"RaceKey": rk, "a": a.DriverId, "b": b.DriverId,
                     "excess": (a["median"] - b["median"]) - (sa - sb), "se": se})
    ex = pd.DataFrame(rows)
    if len(ex) >= 5:
        mu, tau2, _, _ = C.eb_normal(ex["excess"], ex["se"])
        # Per-driver effects: excess = w_a - w_b, ridge prior w ~ N(0, tau2).
        drivers = sorted(set(ex["a"]) | set(ex["b"]))
        di = {d: i for i, d in enumerate(drivers)}
        X = np.zeros((len(ex), len(drivers)))
        X[np.arange(len(ex)), ex["a"].map(di)] = 1
        X[np.arange(len(ex)), ex["b"].map(di)] = -1
        W = 1 / ex["se"].values ** 2
        Q = (X * W[:, None]).T @ X + np.eye(len(drivers)) / max(tau2, 1e-6)
        m = np.linalg.solve(Q, (X * W[:, None]).T @ (ex["excess"].values - mu))
        sd = np.sqrt(np.diag(np.linalg.inv(Q)))
        nrace = pd.concat([ex["a"], ex["b"]]).value_counts()
        out["driver_wet_effects"] = {d: {"wet_extra_pct": m[i], "sd": sd[i], "wet_races": int(nrace[d])}
                                     for d, i in di.items()}
        out["driver_wet_skill"] = {"pairs": int(len(ex)), "races": int(ex.RaceKey.nunique()),
                                   "mean_excess_pct": mu, "between_driver_sd_pct": float(np.sqrt(tau2)),
                                   "raw_sd_pct": float(ex["excess"].std()),
                                   "detected": bool(tau2 > 0)}
    return out


if __name__ == "__main__":
    import json
    import track_pace as T
    import skill as S
    laps, res, races = C.load()
    rf = pd.read_csv(C.PROC / "fits" / "race_fits.csv")
    dr = pd.read_csv(C.PROC / "fits" / "driver_race_pace.csv")
    tk = dict(zip(rf.RaceKey, T.track_keys(rf)))
    sk = S.fit(dr)["skill"]
    o = run(laps, races, rf, dr, tk, sk)
    print(json.dumps(C._clean({k: v for k, v in o.items() if k not in ("races_used", "trajectories", "driver_wet_effects")}), indent=None))
