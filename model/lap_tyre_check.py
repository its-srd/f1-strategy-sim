"""Lap-level test of the tyre model (review 4.4).

Whenever two teammates both set a clean green lap on the same lap but on a
different compound or tyre age, the as-of tyre model (the backtest race's
parameters, fitted on earlier races only) predicts their lap-time gap from
the tyres alone: offset + wear slope x age + curvature x age^2, per car.
The real gap is the lap-time difference. Teammate pace and the race's fuel
and track evolution cancel within a pair on one lap; the remaining driver
form is removed by centring both gaps within each pair and race (so the
test is about how the gap changes as the tyres differ, which is what a
strategy comparison needs).

Reported per season: the slope of the real gap on the predicted gap (1 is
right, below 1 means the model overstates tyre differences, near 0 means it
has no idea), the RMSE, and the same for the pooled parameters (every track
at the pooled mean). Thousands of laps per season instead of a few dozen
teammate pairs, and no simulation.

    .venv/bin/python model/lap_tyre_check.py [tag]
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


def tyre_time(pace: dict, comp: pd.Series, age: pd.Series, base_s: float, pooled: dict | None = None) -> np.ndarray:
    """Seconds added by the tyre: offset vs MEDIUM + slope * age + curve * age^2."""
    def val(p):
        if pooled is not None:
            return pooled[p]["mean_pct"] / 100 * base_s
        return pace[p]["mean_s"]
    off = {"SOFT": val("offset_SOFT"), "MEDIUM": 0.0, "HARD": val("offset_HARD")}
    slope = {c: val(f"slope_{c}") for c in C.DRY}
    curve = val("curve")
    return np.array([off[c] + slope[c] * a + curve * a * a for c, a in zip(comp, age)])


def pairs_for_race(d: Path, laps: pd.DataFrame) -> pd.DataFrame:
    race = json.loads((d / "race.json").read_text())
    tr = json.loads((d / "params" / "tracks.json").read_text()).get(race["track"])
    pooled = json.loads((d / "params" / "global.json").read_text())["pooled"]["pace"]
    if not tr or not tr.get("pace"):
        return pd.DataFrame()
    L = laps[(laps.RaceKey == race["key"]) & laps.Compound.isin(C.DRY)].copy()
    if L.empty:
        return pd.DataFrame()
    base = tr["base_lap"]["base_s"]
    L["model"] = tyre_time(tr["pace"], L.Compound, L.TyreLife, base)
    L["pool"] = tyre_time(None, L.Compound, L.TyreLife, base, pooled)
    a = L[["LapNumber", "TeamId", "DriverId", "LapTimeS", "Compound", "TyreLife", "model", "pool"]]
    m = a.merge(a, on=["LapNumber", "TeamId"], suffixes=("_a", "_b"))
    m = m[m.DriverId_a < m.DriverId_b]
    m = m[(m.Compound_a != m.Compound_b) | ((m.TyreLife_a - m.TyreLife_b).abs() >= 3)]
    out = pd.DataFrame({"race": race["key"], "year": race["year"], "pair": m.TeamId + "|" + race["key"],
                        "real": m.LapTimeS_b - m.LapTimeS_a, "pred": m.model_b - m.model_a, "pred_pool": m.pool_b - m.pool_a})
    return out


def score(df: pd.DataFrame) -> dict:
    d = df.copy()
    for c in ("real", "pred", "pred_pool"):
        d[c + "_c"] = d[c] - d.groupby("pair")[c].transform("mean")
    d = d[d.groupby("pair")["real"].transform("size") >= 5]
    # Robust to the odd lap with a lock-up or a blue flag: drop 4-sigma real gaps.
    s = C.robust_sigma(d["real_c"])
    d = d[d["real_c"].abs() <= 4 * s]
    out = {"laps": int(len(d)), "pairs": int(d.pair.nunique()), "races": int(d.race.nunique()),
           "sd_real_s": float(d["real_c"].std())}
    for name, col in (("track", "pred_c"), ("pool", "pred_pool_c")):
        x, y = d[col].values, d["real_c"].values
        b = float(np.sum(x * y) / np.sum(x * x)) if np.sum(x * x) > 0 else np.nan
        # race-clustered SE of the slope
        e = y - b * x
        g = pd.DataFrame({"r": d.race.values, "xe": x * e}).groupby("r")["xe"].sum()
        se = float(np.sqrt(np.sum(g ** 2)) / np.sum(x * x))
        out[name] = {"slope": b, "slope_se": se, "rmse_s": float(np.sqrt(np.mean((y - x) ** 2))),
                     "rmse_zero_s": float(np.sqrt(np.mean(y ** 2))), "sd_pred_s": float(np.std(x))}
    return out


def main(tag: str):
    laps, res, races = C.load()
    laps = C.add_gaps(laps)
    clean, _ = C.clean_mask(laps, races)
    laps = laps[clean & (laps["GapAheadStartS"].fillna(99) >= C.TRAFFIC_GAP_S)]
    rows = [pairs_for_race(d, laps) for d in sorted(BT.glob("20*_*"))
            if (d / "race.json").exists() and (d / "params" / "tracks.json").exists() and d.name[:4] in ("2025", "2026")]
    df = pd.concat([r for r in rows if len(r)], ignore_index=True)
    res_ = {str(y): score(g) for y, g in df.groupby("year")}
    (BT / f"lap_tyre_check_{tag}.json").write_text(json.dumps(C._clean(res_), indent=1))
    for y, r in res_.items():
        print(y, f"{r['laps']} laps, {r['pairs']} pairs, {r['races']} races; real gap SD {r['sd_real_s']:.2f} s")
        for k in ("track", "pool"):
            v = r[k]
            print(f"   {k:5s} slope {v['slope']:.2f} ± {v['slope_se']:.2f}  RMSE {v['rmse_s']:.3f} s (predicting no tyre effect: {v['rmse_zero_s']:.3f})  spread of predictions {v['sd_pred_s']:.3f} s")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "current")
