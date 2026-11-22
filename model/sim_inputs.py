"""Extra empirical inputs the simulator needs, all measured from the data:

* max_stint: longest stint observed per track and dry compound (stint cap, M2)
* strategies: compound sequences and pit-lap fractions teams actually ran at
  each track (dry races, classified finishers). Rival cars sample these (A1).
* gaps: following gaps when a faster car is held up, gaps after lap 1,
  leader's lap-1 time loss (G1, G2)
* pace_mode: is there a measurable pace-vs-wear trade-off between teammates
  in the same car, race and compound? (PM1)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import common as C

QS = [round(q, 2) for q in np.linspace(0.05, 0.95, 19)]
STRATEGY_FROM_YEAR = 2022      # 18-inch tyre era (V2 breaks for SOFT/MEDIUM wear)


def stints_table(laps, res, races, track_key):
    wet = set(races.loc[races["WetCompoundUsed"], "RaceKey"])
    fin = res[res["Status"].str.match(r"^(Finished|Lapped|\+\d+ Laps?)$")][["RaceKey", "Abbreviation"]]
    fin = set(zip(fin.RaceKey, fin.Abbreviation))
    L = laps[~laps["RaceKey"].isin(wet) & ~laps["IsGhostLap"]]
    L = L[[(k, d) in fin for k, d in zip(L.RaceKey, L.Driver)]]
    L = L.sort_values(["RaceKey", "Driver", "LapNumber"])
    st = L.groupby(["RaceKey", "Year", "Driver", "Stint"]).agg(
        compound=("Compound", lambda s: s.mode().iloc[0] if s.notna().any() else None),
        start=("LapNumber", "min"), end=("LapNumber", "max"), age_end=("TyreLife", "max"),
        end_status=("TrackStatus", lambda s: str(s.iloc[-1]))).reset_index()
    st["TrackKey"] = st["RaceKey"].map(track_key)
    tl = races.set_index("RaceKey")["TotalLaps"]
    st["total"] = st["RaceKey"].map(tl)
    grid = res.set_index(["RaceKey", "Abbreviation"])["GridPosition"]
    st["grid"] = [grid.get((a, b)) for a, b in zip(st["RaceKey"], st["Driver"])]
    return st


STINT_CAP_QUANTILE = 0.95   # the cap is a long stint teams really run, not the single longest ever
STINT_CAP_MIN = 5           # fewer stints of a compound at a track: the pooled cap is used


def stint_lengths(st):
    """Dry stints of the 18-inch era (since STRATEGY_FROM_YEAR), as laps run.
    The engine fits fresh tyres at every stop, so the stint length, not the
    tyre age (longer for a used set), is what the cap limits."""
    d = st[st["compound"].isin(C.DRY) & (st["Year"] >= STRATEGY_FROM_YEAR)].copy()
    d["laps"] = d["end"] - d["start"] + 1
    return d


def max_stint(st):
    """Per track and compound: the 95th percentile of stint lengths (review
    2.3: the maximum let one outlier stint, e.g. Monaco HARD 78 laps, set the
    limit the optimiser pushes against, where the linear wear fit is least
    reliable)."""
    d = stint_lengths(st)
    out = {}
    for tk, g in d.groupby("TrackKey"):
        caps = {c: int(np.ceil(g.loc[g.compound == c, "laps"].quantile(STINT_CAP_QUANTILE)))
                for c in C.DRY if (g.compound == c).sum() >= STINT_CAP_MIN}
        if caps:
            out[tk] = caps
    return out


def max_stint_pooled(st):
    d = stint_lengths(st)
    return {c: int(np.ceil(d.loc[d.compound == c, "laps"].quantile(STINT_CAP_QUANTILE))) for c in C.DRY}


def strategies(st):
    out = {}
    for tk, g in st.groupby("TrackKey"):
        recent = g[g["Year"] >= STRATEGY_FROM_YEAR]
        use = recent if recent["RaceKey"].nunique() >= 1 else g
        seqs, dropped = [], {"reactive_stop": 0, "short_stint": 0}
        for (rk, drv), s in use.sort_values("start").groupby(["RaceKey", "Driver"]):
            if s["compound"].isna().any() or not s["compound"].isin(C.DRY).all():
                continue
            # A1: keep planned green-flag strategies only. Stops made under
            # SC/VSC/red are reactions the simulator models itself (A2), and
            # stints of 2 laps or less are damage/puncture stops.
            if s["end_status"].iloc[:-1].str.contains("[4567]", regex=True).any():
                dropped["reactive_stop"] += 1; continue
            if ((s["end"] - s["start"] + 1) <= 2).any():
                dropped["short_stint"] += 1; continue
            total = s["total"].iloc[0]
            stops = [round(float(e / total), 4) for e in s["end"].values[:-1]]
            g = s["grid"].iloc[0]
            seqs.append({"race": rk, "compounds": s["compound"].tolist(), "stop_fracs": stops,
                         "grid": int(g) if pd.notna(g) and g > 0 else None})
        if seqs:
            n_stops = pd.Series([len(x["stop_fracs"]) for x in seqs]).value_counts(normalize=True).sort_index()
            out[tk] = {"from_year": int(use["Year"].min()), "n": len(seqs), "races": int(use["RaceKey"].nunique()),
                       "dropped": dropped,
                       "stop_count_share": {int(k): float(v) for k, v in n_stops.items()}, "sequences": seqs}
    return out


def gaps(laps, races, pairs_fn=None):
    """Gap distributions measured at the line."""
    wet = set(races.loc[races["WetCompoundUsed"], "RaceKey"])
    L = laps[~laps["RaceKey"].isin(wet) & laps["Position"].notna() & ~laps["IsGhostLap"]].copy()
    L = L.sort_values(["RaceKey", "LapNumber", "Position"])
    L["gap_ahead"] = L.groupby(["RaceKey", "LapNumber"])["LapEndSessionTimeS"].diff()
    lap1 = L[L["LapNumber"] == 1]["gap_ahead"].dropna()
    lap1 = lap1[(lap1 > 0) & (lap1 < 30)]
    # Leader lap-1 loss vs his lap-2 time (standing start + opening-lap traffic).
    lead = L[L["Position"] == 1].pivot_table(index="RaceKey", columns="LapNumber", values="LapTimeS")
    loss = (lead.get(1) - lead.get(2)).dropna() if 1 in lead and 2 in lead else pd.Series(dtype=float)
    # Restart gaps: first green lap after an SC lap, consecutive cars.
    st = L.groupby(["RaceKey", "Driver"])["TrackStatus"].shift(1).fillna("")
    rs = L[st.str.contains("4") & (L["TrackStatus"].fillna("") == "1")]["gap_ahead"].dropna()
    rs = rs[(rs > 0) & (rs < 10)]
    return {"lap1_gap_quantiles_s": dict(zip(QS, np.quantile(lap1, QS))), "lap1_n": int(len(lap1)),
            "leader_lap1_loss_s": float(loss.median()) if len(loss) else None, "leader_lap1_n": int(len(loss)),
            "restart_gap_quantiles_s": dict(zip(QS, np.quantile(rs, QS))), "restart_n": int(len(rs))}


def held_gaps(pairs: pd.DataFrame):
    """Gap kept by a faster car that did not get past (follower faster by
    expected pace, within 1.5 s, no pass)."""
    h = pairs[(pairs["passed"] == 0) & (pairs["pace_adv"] > 0) & (pairs["gap"] < 1.5)]["gap"]
    return {"held_gap_quantiles_s": dict(zip(QS, np.quantile(h, QS))), "n": int(len(h))}


def pace_mode(laps, clean, rf):
    """Teammates on the same compound in the same race: does the one who runs
    a faster stint-start pace wear the tyre faster? Within-team differences
    remove the car, so the slope estimates the management trade-off."""
    d = laps[clean].copy()
    r = rf.set_index("RaceKey")
    d = d[d["RaceKey"].isin(r.index)]
    d["adj"] = d["LapTimeS"] - d["RaceKey"].map(r["fuel"]) * d["LapNumber"] - d["RaceKey"].map(r["fuel2"]) * d["LapNumber"] ** 2
    rows = []
    for (rk, drv, stint), g in d.groupby(["RaceKey", "DriverId", "Stint"]):
        if len(g) < 10 or g["TyreLife"].nunique() < 8:
            continue
        # Independent halves: pace from the first half, wear from the second,
        # so estimation noise in one cannot create a correlation with the other
        # (intercept and slope from the same laps are negatively correlated).
        g = g.sort_values("TyreLife")
        h = len(g) // 2
        first, second = g.iloc[:h], g.iloc[h:]
        if first["TyreLife"].nunique() < 3 or second["TyreLife"].nunique() < 4:
            continue
        a = float(first["adj"].mean() - 0.0)        # mean first-half pace
        b = np.polyfit(second["TyreLife"].values.astype(float), second["adj"].values, 1)[0]
        rows.append({"RaceKey": rk, "DriverId": drv, "TeamId": g["TeamId"].iloc[0],
                     "Compound": g["Compound"].iloc[0], "pace0": a, "wear": b, "n": len(g)})
    s = pd.DataFrame(rows)
    pairs = []
    for (rk, team, comp), g in s.groupby(["RaceKey", "TeamId", "Compound"]):
        if g["DriverId"].nunique() == 2:
            a = g[g.DriverId == g.DriverId.iloc[0]].mean(numeric_only=True)
            b = g[g.DriverId != g.DriverId.iloc[0]].mean(numeric_only=True)
            base = r.loc[rk, "base_s"]
            if abs(a.n - b.n) > 6:
                continue      # comparable stint lengths, so first-half ages match
            ids = sorted(g.DriverId.unique())
            sign = 1 if g.DriverId.iloc[0] == ids[0] else -1
            pairs.append({"RaceKey": rk, "pair": "|".join(ids), "sign": sign,
                          "dpace_pct": 100 * (a.pace0 - b.pace0) / base,
                          "dwear_pct": 100 * (a.wear - b.wear) / base})
    p = pd.DataFrame(pairs)
    x, y = p["dpace_pct"].values, p["dwear_pct"].values
    # Robust slope (Theil-Sen style median of pairwise slopes would be O(n^2);
    # use OLS with race-cluster bootstrap CI and Huber-trimmed sample).
    keep = (np.abs(x - np.median(x)) < 5 * C.robust_sigma(x)) & (np.abs(y - np.median(y)) < 5 * C.robust_sigma(y))
    x, y, races_ = x[keep], y[keep], p["RaceKey"].values[keep]
    slope = float(np.sum((x - x.mean()) * (y - y.mean())) / np.sum((x - x.mean()) ** 2))
    rng = np.random.default_rng(3)
    ur = np.unique(races_)
    bs = []
    for _ in range(500):
        pick = rng.choice(ur, len(ur))
        idx = np.concatenate([np.where(races_ == u)[0] for u in pick])
        xx, yy = x[idx], y[idx]
        bs.append(np.sum((xx - xx.mean()) * (yy - yy.mean())) / np.sum((xx - xx.mean()) ** 2))
    ci = np.percentile(bs, [2.5, 97.5]).tolist()
    # Managed-pace variation: teammate pace difference with each pairing's
    # average (their skill gap) removed, per driver (/sqrt 2).
    pk = p[keep].copy()
    pk["dp"] = pk["dpace_pct"] * pk["sign"]
    resid = pk["dp"] - pk.groupby("pair")["dp"].transform("mean")
    multi = pk.groupby("pair")["dp"].transform("count") >= 3
    mode_sd = float(resid[multi].std() / np.sqrt(2))
    return {"wear_change_per_pace_pct": slope, "ci95": ci, "n_pairs": int(len(x)),
            "mode_pace_sd_pct": mode_sd, "n_pairs_for_sd": int(multi.sum()),
            "supported": bool(ci[1] < 0 or ci[0] > 0),
            "note": "negative slope = a faster stint start comes with more wear (dpace<0 -> dwear>0)"}


if __name__ == "__main__":
    import json
    import track_pace as T
    import overtaking as O
    laps, res, races = C.load()
    laps = C.add_gaps(laps)
    clean, _ = C.clean_mask(laps, races)
    rf = pd.read_csv(C.PROC / "fits" / "race_fits.csv")
    tk = dict(zip(rf.RaceKey, T.track_keys(rf)))
    for _, r in races.iterrows():
        tk.setdefault(r.RaceKey, r.CircuitId)
    st = stints_table(laps, res, races, tk)
    ms = max_stint(st)
    sg = strategies(st)
    print("max stint monza", ms.get("monza"), "strategies monza", {k: v for k, v in sg["monza"].items() if k != "sequences"})
    print("gaps", json.dumps(C._clean(gaps(laps, races)))[:600])
    print("pace mode", pace_mode(laps, clean, rf))
