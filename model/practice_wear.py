"""Tyre wear measured on the race weekend's long runs (review 2.2).

The race's own wear level is what decides one stop or two, and the track's
history predicts it poorly. The only information before the race about this
weekend's wear is the teams' long runs: Practice 2 on a normal weekend, the
Sprint (a short race) and Practice 1 on a sprint weekend
(scripts/export_practice.py).

A long run is a stint with at least MIN_RUN_LAPS clean laps on one set of a
dry compound: green, not deleted, not an in- or out-lap, no rain, and within
RUN_BAND of the stint's median (cool-down and push laps dropped). Per
weekend, lap time = stint level + wear slope per compound x tyre age, by
least squares with one intercept per stint, so car, driver and fuel load of
each run cancel. The slope measured that way is wear plus the lap-to-lap
gain from fuel burn and track rubbering, which the race model measures as
its "fuel" term; it is added back so the result is comparable with the race
model's wear slope. All in percent of the stint's median lap.

    .venv/bin/python model/practice_wear.py      # writes data/processed/fits/practice_wear.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

MIN_RUN_LAPS = 5
RUN_BAND = 0.015          # laps more than 1.5% off the stint median are not long-run laps
SESSIONS = ("fp2", "sprint", "fp1")


def long_run_laps(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    ok = d["LapTimeS"].notna() & d["Compound"].isin(C.DRY) & ~d["PitIn"].astype(bool) & ~d["PitOut"].astype(bool) \
        & (d["TrackStatus"].astype(str).str.replace(".0", "", regex=False) == "1") \
        & ~d["Deleted"].astype(str).str.lower().eq("true") & ~d["Rainfall"].astype(str).str.lower().eq("true") \
        & d["TyreLife"].notna()
    d = d[ok]
    d["med"] = d.groupby(["Driver", "Stint"])["LapTimeS"].transform("median")
    d = d[(d["LapTimeS"] / d["med"] - 1).abs() <= RUN_BAND]
    n = d.groupby(["Driver", "Stint"])["LapTimeS"].transform("size")
    d = d[n >= MIN_RUN_LAPS].copy()
    d["pct"] = 100 * (d["LapTimeS"] / d["med"] - 1)
    return d


def fit_weekend(d: pd.DataFrame) -> dict:
    """Wear slope per compound (% of lap per lap of tyre age, fuel and track
    gain still included), stint intercepts absorbed by demeaning."""
    out = {}
    d = d.copy()
    d["run"] = d["Driver"] + "|" + d["Stint"].astype(str)
    for c in C.DRY:
        g = d[d["Compound"] == c]
        if g["run"].nunique() < 2 or len(g) < 15:
            continue
        x = g["TyreLife"] - g.groupby("run")["TyreLife"].transform("mean")
        y = g["pct"] - g.groupby("run")["pct"].transform("mean")
        if (x ** 2).sum() <= 0:
            continue
        b = float((x * y).sum() / (x ** 2).sum())
        e = y - b * x
        # run-clustered SE
        s = pd.DataFrame({"r": g["run"], "xe": x * e}).groupby("r")["xe"].sum()
        se = float(np.sqrt((s ** 2).sum()) / (x ** 2).sum())
        out[c] = {"slope": b, "se": se, "laps": int(len(g)), "runs": int(g["run"].nunique())}
    return out


def main():
    rows = []
    for meta in sorted((C.ROOT / "data" / "raw").glob("20*/*_meta.json")):
        stem = str(meta)[: -len("_meta.json")]
        year, rnd = int(Path(stem).name[:4]), int(Path(stem).name[5:7])
        if year < 2022:
            continue
        parts = [pd.read_csv(f"{stem}_{s}.csv") for s in SESSIONS if Path(f"{stem}_{s}.csv").exists()]
        if not parts:
            continue
        laps = pd.concat([long_run_laps(p.assign(Stint=p["Stint"].astype(str) + f"_{i}")) for i, p in enumerate(parts)])
        fit = fit_weekend(laps)
        for c, v in fit.items():
            rows.append({"RaceKey": f"{year}_{rnd:02d}", "Year": year, "Round": rnd, "compound": c, **v})
    df = pd.DataFrame(rows)
    out = C.PROC / "fits" / "practice_wear.csv"
    df.to_csv(out, index=False)
    print(f"{df.RaceKey.nunique()} weekends, {len(df)} compound slopes -> {out}")
    return df


if __name__ == "__main__":
    main()


# ------------------------------------------------------------------ evaluation
def pairs() -> pd.DataFrame:
    """Practice estimate (fuel and track gain added back with the race fit's
    own term) next to the race's measured wear, per compound."""
    pw = pd.read_csv(C.PROC / "fits" / "practice_wear.csv")
    rf = pd.read_csv(C.PROC / "fits" / "race_fits.csv").set_index("RaceKey")
    rows = []
    for r in pw.itertuples():
        if r.RaceKey not in rf.index:
            continue
        q = rf.loc[r.RaceKey]
        real = 100 * q[f"slope_{r.compound}"] / q["base_s"]
        if np.isfinite(real):
            rows.append({"RaceKey": r.RaceKey, "Year": r.Year, "compound": r.compound, "practice": r.slope,
                         "practice_se": r.se, "fuel": 100 * q["fuel"] / q["base_s"], "real": real,
                         "real_se": 100 * q[f"slope_{r.compound}_se"] / q["base_s"]})
    return pd.DataFrame(rows)


def calibrate(d: pd.DataFrame) -> dict:
    """Race wear = a + b x (practice slope - fuel term), with the residual
    variance beyond both measurements' own noise: how far a weekend's long
    runs can be from the race."""
    x = d["practice"] - d["fuel"]
    b, a = np.polyfit(x, d["real"], 1)
    e = d["real"] - (a + b * x)
    s2 = float(max(np.mean(e ** 2) - np.mean(d["real_se"] ** 2), 1e-6))
    return {"a": float(a), "b": float(b), "resid_var": s2, "n": int(len(d)), "races": int(d.RaceKey.nunique())}


def forecast(m: float, P: float, practice: float, practice_se: float, fuel: float, cal: dict) -> tuple[float, float]:
    """Combine the track's as-of forecast N(m, P) with the weekend's long runs:
    precision-weighted, the practice signal carrying its calibration error."""
    p_hat = cal["a"] + cal["b"] * (practice - fuel)
    v = cal["resid_var"] + (cal["b"] * practice_se) ** 2
    w = (1 / v) / (1 / P + 1 / v)
    return float(w * p_hat + (1 - w) * m), float(1 / (1 / P + 1 / v))


def evaluate():
    import json
    d = pairs()
    bt = C.ROOT / "data" / "backtest"
    for test in (2025, 2026):
        cal = calibrate(d[d.Year < test])
        rows = []
        for r in d[d.Year == test].itertuples():
            pf = bt / r.RaceKey / "params"
            if not (pf / "tracks.json").exists():
                continue
            track = json.loads((bt / r.RaceKey / "race.json").read_text())["track"]
            est = json.loads((pf / "tracks.json").read_text())[track]["pace"][f"slope_{r.compound}"]
            m, P = est["mean"], est["sd"] ** 2
            comb, _ = forecast(m, P, r.practice, r.practice_se, r.fuel, cal)
            rows.append({"race": r.RaceKey, "real": r.real, "history": m,
                         "practice": cal["a"] + cal["b"] * (r.practice - r.fuel), "combined": comb})
        e = pd.DataFrame(rows)
        rm = lambda c: float(np.sqrt(np.mean((e.real - e[c]) ** 2)))
        mean = e.groupby("race")[["real", "history", "practice", "combined"]].mean()
        rmm = lambda c: float(np.sqrt(np.mean((mean.real - mean[c]) ** 2)))
        print(f"{test} (calibrated on {cal['races']} earlier races: race = {cal['a']:.3f} + {cal['b']:.2f} x practice): "
              f"{len(e)} compound slopes in {e.race.nunique()} races")
        for c in ("history", "practice", "combined"):
            print(f"   {c:9s} slope RMSE {rm(c):.4f}   race-mean wear RMSE {rmm(c):.4f}")


# ------------------------------------------------------------------ use
def weekend_estimate(race_key: str) -> dict:
    """This weekend's long-run wear per compound, if measured."""
    pw = pd.read_csv(C.PROC / "fits" / "practice_wear.csv")
    g = pw[pw.RaceKey == race_key]
    return {r.compound: {"slope": r.slope, "se": r.se, "laps": int(r.laps), "runs": int(r.runs)} for r in g.itertuples()}


def apply_weekend(track: dict, race_key: str, before: callable, est: dict | None = None, sessions=()) -> dict:
    """Update one track's wear slopes (tracks.json entry) with the weekend's
    long runs, calibrated on races for which `before(year, round)` is true
    (strictly earlier races, so a backtest stays honest). Keeps the history
    forecast under "history" so it can be re-applied. Returns what changed."""
    est = weekend_estimate(race_key) if est is None else est
    d = pairs()
    d = d[[before(int(k[:4]), int(k[5:])) for k in d.RaceKey]]
    if not est or d.RaceKey.nunique() < 20:
        return {}
    cal = calibrate(d)
    pace, base = track["pace"], track["base_lap"]["base_s"]
    fuel = pace["fuel"]["mean"]                 # % of lap per lap, the race model's fuel + track term
    changed = {}
    for c, v in est.items():
        p = pace.get(f"slope_{c}")
        if p is None:
            continue
        hist = p.get("history", {"mean": p["mean"], "sd": p["sd"], "source": p.get("source")})
        m, P = forecast(hist["mean"], hist["sd"] ** 2, v["slope"], v["se"], fuel, cal)
        p.update({"history": hist, "mean": m, "sd": float(np.sqrt(P)), "mean_s": m / 100 * base,
                  "sd_s": float(np.sqrt(P)) / 100 * base, "source": "track + weekend long runs",
                  "weekend": {"race_key": race_key, "sessions": list(sessions), "practice_slope_pct": v["slope"],
                              "laps": v["laps"], "runs": v["runs"],
                              "calibration": {k: round(x, 4) for k, x in cal.items() if isinstance(x, float)}}})
        changed[c] = (hist["mean"], m)
    return changed
