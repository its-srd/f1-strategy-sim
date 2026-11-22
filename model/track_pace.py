"""Pool per-race lap-time parameters (stage A) into per-track values.

Everything is pooled in percent of the race's base lap time, so tracks of
different length share one scale. Values are converted back to seconds with
each track's current base lap time.

For each (track, parameter) the yearly estimates go through a mean-reverting
filter (common.ar1_level): the track's deviation from its era's pooled mean
carries over from year to year by a factor phi and fades back to the pool.
phi and the between-track spread are chosen per parameter by one-step-ahead
predictive likelihood across all tracks. Until the 2026-11-22 review this was
a random walk, which kept an old noisy value as the track's mean for ever. When a track has no estimate for a parameter, the
pooled cross-track value is used and labelled "pooled".

Track key: Jolpica circuitId. A race whose base lap time is under 85% of the
circuit's median is a different layout (2020 Sakhir outer loop) and gets the
key "<circuitId>_short" (assumption D6).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import common as C

TARGET_YEAR = 2026
PARAMS = ["fuel", "fuel2", "traffic", "curve"] + [f"slope_{c}" for c in C.DRY] + \
         [f"offset_{c}" for c in ("SOFT", "HARD")]


def track_keys(rf: pd.DataFrame) -> pd.Series:
    med = rf.groupby("CircuitId")["base_s"].transform("median")
    return np.where(rf["base_s"] < 0.85 * med, rf["CircuitId"] + "_short", rf["CircuitId"])


def to_pct(rf: pd.DataFrame) -> pd.DataFrame:
    out = rf[["RaceKey", "Year", "TrackKey", "base_s", "MeanTrackTemp", "ref_compound"]].copy()
    for p in PARAMS:
        v, s = rf[p].copy(), rf[p + "_se"].copy()
        if p.startswith("offset_"):
            # Offsets relative to MEDIUM exist only where MEDIUM was the reference.
            bad = rf["ref_compound"] != "MEDIUM"
            v[bad], s[bad] = np.nan, np.nan
        out[p] = 100 * v / rf["base_s"]
        out[p + "_se"] = 100 * s / rf["base_s"]
    out["sigma"] = 100 * rf["sigma_s"] / rf["base_s"]
    out["sigma_se"] = out["sigma"] / np.sqrt(2 * rf["n_laps"].clip(lower=2))
    return out


def series(df, p):
    g = []
    for tk, d in df.dropna(subset=[p, p + "_se"]).groupby("TrackKey"):
        d = d[d[p + "_se"] > 0]
        if len(d):
            g.append((tk, d[p].values, d[p + "_se"].values, d["Year"].values))
    return g


PHI_GRID = np.round(np.arange(0.0, 1.0, 0.05), 2).tolist() + [0.97, 0.99]
TAU_SCALE = np.exp(np.linspace(np.log(0.1), np.log(4.0), 25))


def era_means(df, p, breaks):
    """Pooled mean of each era (between reset years), from every race in it:
    precision-weighted with the between-race spread (DerSimonian-Laird).
    Returns {era start: (mean, se of the mean, tau2)}; an era without data
    takes the previous era's mean with one extra between-track spread of
    uncertainty."""
    d = df.dropna(subset=[p, p + "_se"])
    d = d[d[p + "_se"] > 0]
    starts = [None] + sorted(breaks)
    out, prev = {}, None
    for i, a in enumerate(starts):
        b = starts[i + 1] if i + 1 < len(starts) else None
        e = d[(d.Year >= (a if a is not None else -1)) & (d.Year < (b if b is not None else 10 ** 4))]
        if len(e) >= 2:
            mu, tau2, _, _ = C.eb_normal(e[p], e[p + "_se"])
            w = 1 / (e[p + "_se"] ** 2 + tau2)
            out[a] = (mu, float(np.sqrt(1 / w.sum())), tau2)
        elif prev is not None:
            out[a] = (prev[0], float(np.sqrt(prev[1] ** 2 + prev[2])), prev[2])
        else:
            out[a] = (np.nan, np.nan, np.nan)
        prev = out[a]
    return out


def pool_param(df, p, breaks=()):
    """Mean-reverting pooling (review 2.2). Each track's value is its era's
    pooled mean plus a deviation that persists from year to year by phi and
    has stationary spread tau2 between tracks. phi and tau2 are chosen by the
    one-step-ahead predictive likelihood of every race given the earlier
    ones, across all tracks (the same yardstick the random walk used). phi
    near 0 means a track's history says little about its next race: values
    go to the pool. A reset year starts a new era, also when projecting a
    track not yet raced since the reset (review 1.2)."""
    groups = [(y, s, yr) for _, y, s, yr in series(df, p)]
    names = [tk for tk, *_ in series(df, p)]
    if not groups:
        return {}, {"omega2": np.nan, "pooled_mean": np.nan, "pooled_sd": np.nan, "n_tracks": 0}
    eras = era_means(df, p, breaks)
    starts = sorted(k for k in eras if k is not None)

    def era_of(yr):
        return max([b for b in starts if b <= yr], default=None)

    mean_of = lambda yr: eras[era_of(yr)][0]
    tau_ref = np.nanmax([v[2] for v in eras.values()] + [1e-8])
    best = (-np.inf, None, None)
    for phi in PHI_GRID:
        for sc in TAU_SCALE:
            tau2 = max(tau_ref * sc, 1e-10)
            lp = sum(C.ar1_level(y, s, yr, phi, tau2, mean_of, breaks)[2] for y, s, yr in groups)
            if lp > best[0]:
                best = (lp, phi, tau2)
    log_pred, phi, tau2 = best
    m_t, se_t, _ = eras[era_of(TARGET_YEAR)]
    rows = {}
    for tk, (y, s, yr) in zip(names, groups):
        dev, P, _, last = C.ar1_level(y, s, yr, phi, tau2, mean_of, breaks)
        dev, P = C.ar1_project(dev, P, int(last), TARGET_YEAR, phi, tau2, breaks)
        rows[tk] = {"mean": float(m_t + dev), "sd": float(np.sqrt(P + se_t ** 2)), "n_races": int(len(y)),
                    "last_year": int(yr.max()), "source": "track"}
    return rows, {"omega2": float(tau2 * (1 - phi ** 2)), "phi": float(phi), "tau2": float(tau2),
                  "pooled_mean": float(m_t), "pooled_mean_se": float(se_t),
                  "pooled_sd": float(np.sqrt(tau2 + se_t ** 2)), "n_tracks": len(rows), "log_pred": float(log_pred),
                  "grid_best": float(phi)}


def temperature_effect(df, p):
    """Within-track: does the parameter move with track temperature across
    years? Weighted regression of deviations from each track's mean."""
    d = df.dropna(subset=[p, p + "_se", "MeanTrackTemp"])
    d = d[d.groupby("TrackKey")["Year"].transform("count") >= 2]
    if len(d) < 10:
        return None
    w = 1 / d[p + "_se"] ** 2
    xm = d.groupby("TrackKey")["MeanTrackTemp"].transform("mean")
    ym = d.groupby("TrackKey")[p].transform(lambda s: np.average(s, weights=w.loc[s.index]))
    x, y = d["MeanTrackTemp"] - xm, d[p] - ym
    b = np.sum(w * x * y) / np.sum(w * x * x)
    resid = y - b * x
    # Robust (sandwich) SE.
    se = np.sqrt(np.sum((w * x * resid) ** 2)) / np.sum(w * x * x)
    return {"per_degC": b, "se": se, "n_races": int(len(d)), "n_tracks": int(d["TrackKey"].nunique())}


def base_pace(rf: pd.DataFrame) -> dict:
    """Current base lap time per track. Tracks not yet raced in TARGET_YEAR
    are scaled by the era pace ratio: the median ratio of TARGET_YEAR base
    to that track's previous-year base, over tracks raced in both."""
    last = rf.sort_values("Year").groupby("TrackKey").tail(1).set_index("TrackKey")
    ratios = {}
    for yr in sorted(rf["Year"].unique()):
        if yr == rf["Year"].min():
            continue
        a = rf[rf.Year == yr].groupby("TrackKey")["base_s"].mean()
        b = rf[rf.Year == yr - 1].groupby("TrackKey")["base_s"].mean()
        j = pd.concat([a, b], axis=1, keys=["now", "prev"]).dropna()
        if len(j):
            ratios[int(yr)] = (float(np.median(j["now"] / j["prev"])), int(len(j)))
    out = {}
    for tk, r in last.iterrows():
        factor, chain = 1.0, []
        for yr in range(int(r.Year) + 1, TARGET_YEAR + 1):
            if yr in ratios:
                factor *= ratios[yr][0]; chain.append(yr)
        out[tk] = {"base_s": float(r.base_s * factor), "from_year": int(r.Year),
                   "scaled_by_years": chain, "source": "track" if not chain else "track_scaled"}
    return out, ratios


def run(rf: pd.DataFrame, breaks=(), breaks_by_param: dict | None = None) -> dict:
    rf = rf.copy()
    rf["TrackKey"] = track_keys(rf)
    df = to_pct(rf)
    params, meta = {}, {}
    for p in PARAMS + ["sigma"]:
        b = (breaks_by_param or {}).get(p, breaks)
        params[p], meta[p] = pool_param(df, p, breaks=b)
        meta[p]["breaks"] = list(b)
    temps = {p: temperature_effect(df, p) for p in [f"slope_{c}" for c in C.DRY] + ["fuel"]}
    base, ratios = base_pace(rf)
    tracks = {}
    for tk in sorted(set(rf["TrackKey"])):
        b = base.get(tk)
        entry = {"base_lap_s": b, "params": {}}
        for p in PARAMS + ["sigma"]:
            r = params[p].get(tk)
            if r is None:
                r = {"mean": meta[p]["pooled_mean"], "sd": meta[p]["pooled_sd"],
                     "n_races": 0, "source": "pooled"}
            r = dict(r)
            r["mean_s"] = r["mean"] / 100 * b["base_s"] if r["mean"] is not None else None
            r["sd_s"] = r["sd"] / 100 * b["base_s"] if r["sd"] is not None else None
            entry["params"][p] = r
        last = rf[rf.TrackKey == tk].sort_values("Year").iloc[-1]
        entry["circuit_id"] = last["CircuitId"]
        entry["mean_track_temp"] = float(rf.loc[rf.TrackKey == tk, "MeanTrackTemp"].mean())
        entry["total_laps"] = int(last["TotalLaps"])
        entry["dry_races"] = int((rf.TrackKey == tk).sum())
        tracks[tk] = entry
    return {"tracks": tracks, "pooling": meta, "temperature": temps,
            "era_pace_ratio": ratios, "data": df}


if __name__ == "__main__":
    rf = pd.read_csv(C.PROC / "fits" / "race_fits.csv")
    out = run(rf)
    print("omega (pct/yr) and pooled values:")
    for p, m in out["pooling"].items():
        print(f"  {p:<14} omega={np.sqrt(m['omega2']):.4f}  pooled={m['pooled_mean']:.4f}  "
              f"sd={m['pooled_sd']:.4f}  tracks={m['n_tracks']}")
    print("temperature effects (pct per degC):", {k: v and {kk: round(vv, 5) for kk, vv in v.items()} for k, v in out["temperature"].items()})
    print("era ratios:", out["era_pace_ratio"])
    for tk in ["bahrain", "monaco", "silverstone", "bahrain_short", "madring"]:
        e = out["tracks"].get(tk)
        if e:
            print(tk, round(e["base_lap_s"]["base_s"], 2), e["base_lap_s"]["source"],
                  {p: (round(v["mean_s"], 3) if v["mean_s"] is not None else None, v["source"], v["n_races"]) for p, v in e["params"].items()})
