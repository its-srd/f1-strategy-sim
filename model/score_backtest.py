"""Score backtest predictions against what actually happened.

Compares the model with a grid-only baseline: the historical frequency of
win / podium / points / retirement from each grid slot, using only races
before the test race. If the model cannot beat "where did they start", it is
not adding anything.

Metrics (lower is better unless stated):
* Brier score: mean of (predicted probability - outcome)^2 per driver
* winner log-loss: -ln(probability given to the actual winner)
* Brier skill score vs grid baseline: 1 - Brier_model / Brier_grid
  (higher is better; > 0 means the model beats the baseline)
* rank correlation (Spearman) between expected and actual finishing order
* calibration: predicted vs observed frequency in probability bins
* 80% interval coverage: share of drivers finishing inside the model's
  10th-90th percentile range of positions (should be about 80%)
Uncertainty: 95% bootstrap intervals over races.

    .venv/bin/python model/score_backtest.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

OUT = C.ROOT / "data" / "backtest"
FINISHED = r"^(Finished|Lapped|\+\d+ Laps?)$"
NOT_RACED = {"Did not start", "Withdrew", "Did not qualify", "Did not prequalify"}
OUTCOMES = ["win", "podium", "points", "dnf"]
BINS = [0, 0.05, 0.15, 0.3, 0.5, 0.7, 0.9, 1.0001]


def actual(res_race: pd.DataFrame) -> pd.DataFrame:
    r = res_race[~res_race["Status"].isin(NOT_RACED)].copy()
    classified = r["ClassifiedPosition"].astype(str).str.isdigit()
    r["win"] = (r["Position"] == 1) & classified
    r["podium"] = (r["Position"] <= 3) & classified
    r["points"] = (r["Position"] <= 10) & classified
    r["dnf"] = ~r["Status"].astype(str).str.match(FINISHED) & (r["Status"] != "Disqualified")
    r["grid"] = r["GridPosition"].where(r["GridPosition"] > 0, len(r))
    return r.set_index("DriverId")


def grid_baseline(res: pd.DataFrame, before_keys: set, n_cars: int) -> pd.DataFrame:
    """P(outcome | grid slot) from earlier races, add-one smoothed toward the
    overall rate so empty slots are not 0 or 1."""
    rows = []
    for k in before_keys:
        a = actual(res[res.RaceKey == k])
        rows.append(a[["grid"] + OUTCOMES])
    h = pd.concat(rows)
    out = {}
    for o in OUTCOMES:
        overall = h[o].mean()
        g = h.groupby("grid")[o].agg(["sum", "count"])
        out[o] = {s: (g["sum"].get(s, 0) + overall * 2) / (g["count"].get(s, 0) + 2) for s in range(1, n_cars + 1)}
    return pd.DataFrame(out)


def score(years=("2025", "2026"), tag="all", root=OUT, pred_file="predictions.json"):
    laps, res, races = C.load()
    del laps
    rows, calib = [], []
    race_rows = []
    for d in sorted(root.glob("20*_*")):
        if not d.name.startswith(years):
            continue
        pf = d / pred_file
        if not pf.exists():
            continue
        pred = pd.DataFrame(json.loads(pf.read_text())["drivers"]).set_index("driver")
        info = json.loads((d / "race.json").read_text())
        key = info["key"]
        r = races[races.RaceKey == key].iloc[0]
        before = races[(races.Year < r.Year) | ((races.Year == r.Year) & (races.Round < r.Round))]
        act = actual(res[res.RaceKey == key])
        drivers = [x for x in pred.index if x in act.index]
        n = len(pred)
        base = grid_baseline(res, set(before.RaceKey), n)
        # Win probabilities normalised to sum to 1 in each race (both models).
        bw = base.loc[act.loc[drivers, "grid"].clip(upper=n).values, "win"].values
        bw = bw / bw.sum()
        for j, drv in enumerate(drivers):
            a = act.loc[drv]
            p = pred.loc[drv]
            hist = np.array(p["pos_hist"])
            cdf = np.cumsum(hist)
            lo, hi = int(np.searchsorted(cdf, 0.10)) + 1, int(np.searchsorted(cdf, 0.90)) + 1
            actual_pos = int(a["Position"]) if not a["dnf"] else n + 1
            exp_pos = float(np.dot(np.arange(1, n + 2), hist))
            g = int(min(a["grid"], n))
            rows.append({"race": key, "driver": drv, "grid": g, "actual_pos": actual_pos, "exp_pos": exp_pos,
                         "in80": lo <= actual_pos <= hi,
                         **{f"p_{o}": float(p[o]) for o in OUTCOMES},
                         **{f"b_{o}": float(base.loc[g, o]) for o in OUTCOMES},
                         "b_win": float(bw[j]),
                         **{f"y_{o}": bool(a[o]) for o in OUTCOMES}})
        race_rows.append({"race": key, "event": info["event"], "winner": act.index[act["win"]].tolist()[0] if act["win"].any() else None,
                          "model_fav": pred["win"].idxmax(), "model_fav_p": float(pred["win"].max()),
                          "p_winner": float(pred.loc[act.index[act["win"]][0], "win"]) if act["win"].any() else None,
                          "pole": act["grid"].idxmin()})
    df, rr = pd.DataFrame(rows), pd.DataFrame(race_rows)
    if df.empty:
        print("no predictions yet")
        return

    def metrics(d):
        out = {}
        for o in OUTCOMES:
            bm = ((d[f"p_{o}"] - d[f"y_{o}"]) ** 2).mean()
            bb = ((d[f"b_{o}"] - d[f"y_{o}"]) ** 2).mean()
            out[o] = {"brier_model": bm, "brier_grid": bb, "skill_vs_grid": 1 - bm / bb}
        w = d[d["y_win"]]
        out["winner_logloss"] = {"model": float(-np.log(w["p_win"].clip(1e-4)).mean()),
                                 "grid": float(-np.log(w["b_win"].clip(1e-4)).mean())}
        sp_m, sp_g = [], []
        for _, g in d.groupby("race"):
            sp_m.append(g["exp_pos"].corr(g["actual_pos"], method="spearman"))
            sp_g.append(g["grid"].corr(g["actual_pos"], method="spearman"))
        out["rank_corr"] = {"model": float(np.mean(sp_m)), "grid": float(np.mean(sp_g))}
        out["interval80_coverage"] = float(d["in80"].mean())
        return out

    full = metrics(df)
    rng = np.random.default_rng(0)
    races_ = df["race"].unique()
    boot = {o: [] for o in OUTCOMES}
    boot["rank"] = []
    for _ in range(1000):
        pick = rng.choice(races_, len(races_))
        d = pd.concat([df[df.race == k] for k in pick])
        m = metrics(d)
        for o in OUTCOMES:
            boot[o].append(m[o]["skill_vs_grid"])
        boot["rank"].append(m["rank_corr"]["model"] - m["rank_corr"]["grid"])
    for o in OUTCOMES:
        full[o]["skill_ci95"] = np.percentile(boot[o], [2.5, 97.5]).tolist()
    full["rank_corr"]["model_minus_grid_ci95"] = np.percentile(boot["rank"], [2.5, 97.5]).tolist()

    for o in ["win", "podium", "points", "dnf"]:
        c = pd.cut(df[f"p_{o}"], BINS, right=False)
        t = df.groupby(c, observed=True).agg(n=(f"y_{o}", "size"), predicted=(f"p_{o}", "mean"), observed=(f"y_{o}", "mean"))
        for b, v in t.iterrows():
            calib.append({"outcome": o, "bin": f"{b.left:.0%}–{min(b.right, 1):.0%}", "n": int(v.n),
                          "predicted": float(v.predicted), "observed": float(v.observed)})

    summary = {"split": tag, "years": list(years), "n_races": int(df.race.nunique()), "n_driver_races": int(len(df)), "metrics": full,
               "favourite_won": float((rr["model_fav"] == rr["winner"]).mean()),
               "pole_won": float((rr["pole"] == rr["winner"]).mean()),
               "races": rr.to_dict("records"), "calibration": calib}
    (root / f"scores_{tag}.json").write_text(json.dumps(C._clean(summary), indent=1))
    df.to_csv(root / f"driver_scores_{tag}.csv", index=False)
    print(json.dumps(C._clean({k: v for k, v in summary.items() if k not in ("races", "calibration")}), indent=1))
    print(pd.DataFrame(calib).to_string(index=False))
    return summary


if __name__ == "__main__":
    # Development (2025) vs hold-out (2026): improvements are chosen on the
    # 2025 races only; 2026 is scored once at the end to check they hold.
    split = sys.argv[1] if len(sys.argv) > 1 else "dev"
    if split == "wet":
        # Wet-race backtest (model/backtest.py wet, web/scripts/backtest-wet.ts):
        # one score per weather mode, saved in data/backtest/wet. An optional
        # variant name scores predictions_<mode>_<variant>.json instead.
        variant = sys.argv[2] if len(sys.argv) > 2 else ""
        modes = ("dry", "window", "trace") if not variant else ("window", "trace")
        for m in modes:
            mode = f"{m}_{variant}" if variant else m
            print(f"\n=== wet races, mode {mode} ===")
            score(years=("2022", "2023", "2024", "2025", "2026"), tag=mode, root=OUT / "wet", pred_file=f"predictions_{mode}.json")
        sys.exit(0)
    SPLIT_YEARS = {"dev": ("2025",), "holdout": ("2026",), "all": ("2025", "2026")}[split]
    score(years=SPLIT_YEARS, tag=split)
