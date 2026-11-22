"""Which qualifying gap predicts race pace best? (review 2.4)

Three definitions, each used in the I4 blend fitted on as-of priors
(model/calibrate_pace.py), forward-chained: fitted on 2024, scored on how
well it predicts 2025 race pace; the 2026 column is shown for information
only (fitted on 2024 + 2025).

  best      each driver's best lap of the whole session (the current gap)
  segment   each driver's time in the last segment they ran, scaled to the
            Q3 track: a Q2 time times the median Q3/Q2 ratio of drivers who
            ran both, a Q1 time also times the median Q2/Q1 ratio
  q1        everyone's Q1 time (one track state, but top teams do not push)

Score: root mean square error of the predicted race pace (field-centred,
% of lap time), out of sample. Lower is better.

    .venv/bin/python model/quali_gap_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calibrate_pace as CP  # noqa: E402
import common as C  # noqa: E402


def segment_gaps(seg: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (y, r), g in seg.groupby(["Year", "Round"]):
        g = g.copy()
        both32 = g[g.Q3.notna() & g.Q2.notna()]
        both21 = g[g.Q2.notna() & g.Q1.notna()]
        r32 = float((both32.Q3 / both32.Q2).median()) if len(both32) >= 3 else np.nan
        r21 = float((both21.Q2 / both21.Q1).median()) if len(both21) >= 3 else np.nan
        t = g.Q3.copy()
        t = t.fillna(g.Q2 * r32)
        t = t.fillna(g.Q1 * r21 * r32)
        g["segment"] = 100 * (t / t.min() - 1)
        g["q1"] = 100 * (g.Q1 / g.Q1.min() - 1)
        out.append(g[["Year", "Round", "DriverId", "segment", "q1"]])
    return pd.concat(out, ignore_index=True)


def predict_error(train: pd.DataFrame, test: pd.DataFrame, col: str, tau2: float) -> tuple[float, int]:
    fit = CP.fit(train.assign(gap=train[col]), tau2)["quali"]
    q = test[~test.wet & test[col].notna() & (test[col] <= fit["quali_gap_clip_pct"])].copy()
    for c in ("prior", col):
        q[c + "_c"] = q[c] - q.groupby("RaceKey")[c].transform("mean")
    pred = fit["weight_prior"] * q["prior_c"] + fit["weight_quali"] * q[col + "_c"]
    e = q["delta_pct"] - pred
    return float(np.sqrt(np.mean(e ** 2))), int(len(q))


def main():
    dirs = [d for d in sorted(CP.BT.glob("20*_*")) if (d / "params" / "meta.json").exists() and (d / "race.json").exists()]
    pr = pd.concat([CP.priors(d) for d in dirs], ignore_index=True)
    pace = pd.read_csv(C.PROC / "fits" / "driver_race_pace.csv")[["RaceKey", "DriverId", "delta_pct", "se_pct"]]
    pr = pr.merge(pace, on=["RaceKey", "DriverId"], how="inner")
    pr["Round"] = pr["RaceKey"].str[5:].astype(int)
    seg = pd.concat([pd.read_csv(p) for p in sorted((C.ROOT / "data" / "raw").glob("*/quali_segments.csv"))])
    pr = pr.merge(segment_gaps(seg), on=["Year", "Round", "DriverId"], how="left")
    pr["best"] = pr["gap"]
    ok = pr[["best", "segment", "q1"]].notna().all(axis=1)
    pr = pr[ok].copy()
    import json
    tau2 = json.loads((C.ROOT / "data" / "params" / "global.json").read_text())["skill_model"]["tau_pct"] ** 2
    print(f"{len(pr)} driver-races with all three gaps")
    for col in ("best", "segment", "q1"):
        e25, n25 = predict_error(pr[pr.Year == 2024], pr[pr.Year == 2025], col, tau2)
        e26, n26 = predict_error(pr[pr.Year < 2026], pr[pr.Year == 2026], col, tau2)
        w = CP.fit(pr[pr.Year < 2026].assign(gap=pr[col]), tau2)["quali"]
        print(f"  {col:8s} 2025 error {e25:.4f} (n {n25})  | 2026 error {e26:.4f} (n {n26})  | weights {w['weight_prior']:.2f} / {w['weight_quali']:.2f}")


if __name__ == "__main__":
    main()
