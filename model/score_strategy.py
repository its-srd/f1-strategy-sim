"""Strategy check, part 3: score the teammate pairs (review section 4).

For each pair and engine mode (web/scripts/strategy-check.ts), the error of
the predicted gap with the real strategies is compared with the error when
the engine ignores the strategy difference ("blind"). Gain = blind error -
error with strategies: positive means knowing the strategies helped.

The 95% ranges resample whole races, not pairs: pairs from one race share
its safety cars and conditions (review section 4.3). Pairs with a stop made
under SC/VSC/red ("reactive") are reported apart from clean pairs.

    .venv/bin/python model/score_strategy.py
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
EFFECT_S = 5.0          # "the model predicts a real effect": over 5 s


def table(rows: list[dict]) -> pd.DataFrame:
    recs = []
    for r in rows:
        for mode, v in r["modes"].items():
            effect = v["actual"] - v["blind"]
            recs.append({"race": r["race"], "year": r["race"][:4], "mode": mode, "kind": r["kind"], "reactive": r["reactive"],
                         "err_with": abs(v["actual"] - r["actual_gap_s"]), "err_blind": abs(v["blind"] - r["actual_gap_s"]),
                         "effect": effect, "real_vs_blind": r["actual_gap_s"] - v["blind"]})
    d = pd.DataFrame(recs)
    d["gain"] = d["err_blind"] - d["err_with"]
    return d


def summary(d: pd.DataFrame, rng) -> dict:
    races = d["race"].unique()
    boot = []
    for _ in range(2000):
        pick = rng.choice(races, len(races))
        boot.append(pd.concat([d[d.race == k] for k in pick])["gain"].mean())
    big = d[d["effect"].abs() > EFFECT_S]
    return {"pairs": int(len(d)), "races": int(len(races)),
            "median_err_with_s": float(d["err_with"].median()), "median_err_blind_s": float(d["err_blind"].median()),
            "mean_gain_s": float(d["gain"].mean()), "gain_ci95": np.percentile(boot, [2.5, 97.5]).tolist(),
            "big_effect_pairs": int(len(big)),
            "big_effect_right_direction": float((np.sign(big["effect"]) == np.sign(big["real_vs_blind"])).mean()) if len(big) else None,
            "mean_abs_effect_s": float(d["effect"].abs().mean())}


def main():
    d = table(json.loads((OUT / "strategy_check.json").read_text()))
    rng = np.random.default_rng(0)
    res = {}
    for (year, mode), g in d.groupby(["year", "mode"]):
        res[f"{year} {mode}"] = {"all": summary(g, rng),
                                 "clean": summary(g[~g.reactive], rng) if (~g.reactive).any() else None,
                                 "reactive": summary(g[g.reactive], rng) if g.reactive.any() else None,
                                 "stop_timing": summary(g[g.kind == "stop_timing"], rng) if (g.kind == "stop_timing").any() else None}
    (OUT / "strategy_scores.json").write_text(json.dumps(C._clean(res), indent=1))
    for k, v in res.items():
        for part in ("all", "clean", "reactive", "stop_timing"):
            s = v[part]
            if s:
                print(f"{k:12s} {part:11s} pairs {s['pairs']:3d} races {s['races']:2d} | err {s['median_err_with_s']:5.1f} vs blind {s['median_err_blind_s']:5.1f} | "
                      f"gain {s['mean_gain_s']:+5.2f} s [{s['gain_ci95'][0]:+.1f}, {s['gain_ci95'][1]:+.1f}] | "
                      f"direction {s['big_effect_right_direction'] if s['big_effect_right_direction'] is None else round(s['big_effect_right_direction'], 2)} of {s['big_effect_pairs']}")


if __name__ == "__main__":
    main()
