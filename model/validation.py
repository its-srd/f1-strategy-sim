"""Validation tests V1 (2026 regulation change) and V2 (2022 18-inch tyres).

For each fitted quantity, two models are compared on how well they predict
data they had not seen yet (one-step-ahead predictive log-likelihood for
per-track parameters; marginal likelihood for driver skill):

  carry-over : random walk across the break, so old seasons inform new ones
  break      : the walk is reset at the break year to the pooled prior

The model with the higher score is used in the final fit (fit_all.py).
A difference under 2 log-likelihood units is "no clear difference", and
carry-over is kept, since it uses more data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import common as C
import skill as S
import track_pace as T

THRESH = 2.0


def track_param_tests(rf: pd.DataFrame, break_year: int) -> dict:
    rf = rf.copy()
    rf["TrackKey"] = T.track_keys(rf)
    df = T.to_pct(rf)
    out = {}
    for p in T.PARAMS + ["sigma"]:
        res = {}
        for name, br in (("carry_over", ()), ("break", (break_year,))):
            _, meta = T.pool_param(df, p, breaks=br)
            res[name] = meta["log_pred"]
        diff = res["break"] - res["carry_over"]
        n_after = int(df.loc[df["Year"] >= break_year, p].notna().sum())
        out[p] = {"loglik_carry_over": res["carry_over"], "loglik_break": res["break"],
                  "break_minus_carry": diff, "n_obs_after_break": n_after,
                  "decision": "break" if diff > THRESH else "carry_over"}
    return out


def skill_test(dr: pd.DataFrame, break_year: int) -> dict:
    a = S.fit(dr)
    b = S.fit(dr, break_year=break_year)
    diff = b["loglik"] - a["loglik"]
    return {"loglik_carry_over": a["loglik"], "loglik_break": b["loglik"], "break_minus_carry": diff,
            "omega_carry": float(np.sqrt(a["omega2"])), "omega_break": float(np.sqrt(b["omega2"])),
            "decision": "break" if diff > THRESH else "carry_over"}


def car_transfer(car: pd.DataFrame) -> dict:
    """Descriptive: correlation of team-season mean car pace across consecutive
    seasons. Car pace is always fitted per race, so this only documents how
    much the 2026 order moved."""
    car = car.copy()
    car["Year"] = car["RaceKey"].str[:4].astype(int)
    tm = car.groupby(["TeamId", "Year"])["car_pct"].mean().unstack()
    out = {}
    for y in range(2019, int(car.Year.max()) + 1):
        if y in tm and y - 1 in tm:
            j = tm[[y - 1, y]].dropna()
            out[str(y)] = {"corr": float(j.corr().iloc[0, 1]), "teams": int(len(j))}
    return out


if __name__ == "__main__":
    import json
    rf = pd.read_csv(C.PROC / "fits" / "race_fits.csv")
    dr = pd.read_csv(C.PROC / "fits" / "driver_race_pace.csv")
    res = {"V1_2026": {"track_params": track_param_tests(rf, 2026), "skill": skill_test(dr, 2026)},
           "V2_2022": {"track_params": track_param_tests(rf, 2022), "skill": skill_test(dr, 2022)}}
    res["car_order_correlation"] = car_transfer(S.fit(dr)["car"])
    for k in ("V1_2026", "V2_2022"):
        print(k)
        for p, v in res[k]["track_params"].items():
            print(f"  {p:<14} break-carry={v['break_minus_carry']:+7.2f}  n_after={v['n_obs_after_break']:>3}  -> {v['decision']}")
        s = res[k]["skill"]; print(f"  skill          break-carry={s['break_minus_carry']:+7.2f}  -> {s['decision']}")
    print("car order corr:", {k: round(v["corr"], 2) for k, v in res["car_order_correlation"].items()})
    C.write_json("_validation_preview.json", res)
