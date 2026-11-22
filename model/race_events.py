"""Race events: pit loss, safety car / VSC / red flag, retirements, lap-1 start.

All rates use empirical Bayes: a prior is fitted across every race or track,
then each track or team is shrunk toward it in proportion to its sample size.
Nothing is set by hand.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import betaln, gammaln

import common as C

FINISHED = r"^(Finished|Lapped|\+\d+ Laps?)$"
TARGET_YEAR = 2026          # season parameters are projected to (set by fit_all)
NOT_RACED = {"Did not start", "Withdrew", "Did not qualify", "Did not prequalify"}


# ------------------------------------------------------------------ pit loss
def pit_stops(laps: pd.DataFrame, clean: pd.Series) -> pd.DataFrame:
    """Pit loss = in-lap + out-lap - 2 x the driver's reference lap.
    Reference = median of that driver's clean laps within 5 laps either side
    (assumption P1)."""
    laps = laps.sort_values(["RaceKey", "Driver", "LapNumber"])
    # Same-lap median of cars not pitting: the reference for neutralised stops,
    # where the cost that matters is relative to cars that stay out.
    stay = laps[~laps["PitIn"] & ~laps["PitOut"] & laps["LapTimeS"].notna()]
    field = stay.groupby(["RaceKey", "LapNumber"])["LapTimeS"].median()
    rows = []
    cl = laps[clean]
    ref_src = {k: g for k, g in cl.groupby(["RaceKey", "Driver"])}
    for (rk, drv), g in laps.groupby(["RaceKey", "Driver"]):
        g = g.set_index("LapNumber")
        ref_laps = ref_src.get((rk, drv))
        if ref_laps is None:
            continue
        for L in g.index[g["PitIn"]]:
            if L + 1 not in g.index or not g.loc[L + 1, "PitOut"]:
                continue
            inlap, outlap = g.loc[L, "LapTimeS"], g.loc[L + 1, "LapTimeS"]
            if not (np.isfinite(inlap) and np.isfinite(outlap)):
                continue
            w = ref_laps[(ref_laps["LapNumber"] >= L - 5) & (ref_laps["LapNumber"] <= L + 6)]
            if len(w) < 2:
                continue
            st = str(g.loc[L, "TrackStatus"]) + str(g.loc[L + 1, "TrackStatus"])
            kind = "red" if "5" in st else "sc" if "4" in st else "vsc" if ("6" in st or "7" in st) \
                else "green" if st.replace("1", "") == "" else "yellow"
            rows.append({"RaceKey": rk, "Year": int(g.loc[L, "Year"]), "CircuitId": g.loc[L, "CircuitId"],
                         "Driver": drv, "Lap": int(L), "kind": kind,
                         "loss_s": inlap + outlap - 2 * float(w["LapTimeS"].median()),
                         "loss_vs_field_s": inlap + outlap - field.get((rk, L), np.nan) - field.get((rk, L + 1), np.nan)})
    return pd.DataFrame(rows)


def pit_params(stops: pd.DataFrame, track_key: dict) -> dict:
    stops = stops.copy()
    stops["TrackKey"] = stops["RaceKey"].map(track_key).fillna(stops["CircuitId"])
    g = stops[(stops["kind"] == "green") & (stops["loss_s"] > 0)]
    # Per track-year robust centre and its SE (median SE ~ 1.253 sigma/sqrt n).
    ty = g.groupby(["TrackKey", "Year"])["loss_s"].agg(
        med="median", n="count", sig=lambda s: C.robust_sigma(s)).reset_index()
    ty = ty[ty["n"] >= 3]
    ty["se"] = 1.253 * ty["sig"].clip(lower=0.3) / np.sqrt(ty["n"])
    groups = [(d["med"].values, d["se"].values, d["Year"].values) for _, d in ty.groupby("TrackKey")]
    names = [tk for tk, _ in ty.groupby("TrackKey")]
    omega2, _ = C.fit_omega(groups)
    first = [C.local_level(y, s, yr, omega2)[:2] for y, s, yr in groups]
    mu, tau2, _, _ = C.eb_normal([m for m, _ in first], [np.sqrt(P) for _, P in first])
    tracks = {}
    for tk, (y, s, yr) in zip(names, groups):
        m, P, _ = C.local_level(y, s, yr, omega2, prior_mean=mu, prior_var=max(tau2, 1e-6))
        P += omega2 * max(TARGET_YEAR - yr.max(), 0)
        tracks[tk] = {"green_loss_s": m, "sd": float(np.sqrt(P)), "n_stops": int(g[g.TrackKey == tk].shape[0]),
                      "years": [int(v) for v in sorted(yr)]}
    # Residual spread of individual stops around their track-year median:
    # slow stops, traffic in the pit lane, etc. Empirical quantiles.
    g = g.merge(ty[["TrackKey", "Year", "med"]], on=["TrackKey", "Year"])
    resid = (g["loss_s"] - g["med"]).values
    qs = np.linspace(0.01, 0.99, 99)
    # Neutralised stops: ratio of loss to that track-year's green median.
    ratios = {}
    for kind in ("sc", "vsc"):
        k = stops[stops["kind"] == kind].merge(ty[["TrackKey", "Year", "med"]], on=["TrackKey", "Year"])
        r = (k["loss_vs_field_s"] / k["med"]).dropna().values
        ratios[kind] = {"median_ratio": float(np.median(r)) if len(r) else None,
                        "q25": float(np.quantile(r, .25)) if len(r) else None,
                        "q75": float(np.quantile(r, .75)) if len(r) else None, "n_stops": int(len(r))}
    return {"tracks": tracks, "pooled_green_loss_s": mu, "pooled_sd": float(np.sqrt(tau2)),
            "omega2": omega2, "stop_residual_quantiles_s": dict(zip([round(q, 2) for q in qs], np.quantile(resid, qs))),
            "n_green_stops": int(len(g)), "neutralised_ratio": ratios,
            "counts_by_kind": stops["kind"].value_counts().to_dict()}


# ---------------------------------------------------------------- safety car
def deployments(laps: pd.DataFrame, races: pd.DataFrame) -> pd.DataFrame:
    """Each SC (4), VSC (6) and red flag (5) start from the track-status
    timeline, mapped to the leader's lap, with duration in leader laps."""
    rows = []
    lead = laps[laps["Position"] == 1].groupby(["RaceKey", "LapNumber"])["LapEndSessionTimeS"].min()
    for _, r in races.iterrows():
        stem = C.ROOT / "data" / "raw" / str(r.Year)
        src = list(stem.glob(f"{r.Year}_{int(r.Round):02d}_*_source/session_info.json"))
        if not src or r.RaceKey not in lead.index.get_level_values(0):
            continue
        info = json.loads(src[0].read_text())
        ts = info.get("track_status") or {}
        ends = lead.loc[r.RaceKey].sort_index()
        t_end, lapno = ends.values, ends.index.values
        times, codes = ts.get("Time", []), [str(c) for c in ts.get("Status", [])]
        start = next((t for t, s in zip(info["session_status"]["Time"], info["session_status"]["Status"])
                      if s == "Started"), None)
        prev = None
        last_flag = None                     # last non-green code seen
        for i, (t, c) in enumerate(zip(times, codes)):
            # A "4" whose previous non-green code was a "5" is the restart
            # behind the SC after a red flag ("5 1 4"), not a new deployment;
            # the engine adds that restart lap itself.
            restart = c == "4" and last_flag == "5"
            if c in ("4", "5", "6") and c != prev and not restart and (start is None or t >= start):
                # end = next time status returns to green (1) after this
                t_clear = next((tt for tt, cc in zip(times[i + 1:], codes[i + 1:]) if cc == "1"), np.nan)
                lap = int(lapno[np.searchsorted(t_end, t)]) if t <= t_end[-1] else int(lapno[-1])
                dur = int(np.sum((t_end > t) & (t_end <= t_clear))) if np.isfinite(t_clear) else np.nan
                rows.append({"RaceKey": r.RaceKey, "Year": r.Year, "CircuitId": r.CircuitId,
                             "type": {"4": "SC", "5": "RED", "6": "VSC"}[c], "lap": lap,
                             "lap_frac": lap / r.TotalLaps, "duration_laps": dur,
                             "wet": bool(r.MixedOrWetRace)})
            prev = c
            if c != "1":
                last_flag = c
    return pd.DataFrame(rows)


def negbin_fit(counts):
    """Gamma(a, b) prior on per-track Poisson rates via the negative binomial
    marginal over all races (each race is one exposure unit)."""
    counts = np.asarray(counts, float)

    def nll(t):
        a, b = np.exp(t)
        return -np.sum(gammaln(counts + a) - gammaln(a) - gammaln(counts + 1)
                       + a * np.log(b / (b + 1)) - counts * np.log(b + 1))
    o = minimize(nll, np.log([1.0, 1.0]), method="Nelder-Mead")
    return np.exp(o.x)


def sc_params(dep: pd.DataFrame, races: pd.DataFrame, track_key: dict) -> dict:
    rc = races[~races[["Year", "Round"]].apply(tuple, axis=1).isin(C.EXCLUDE_RACES)].copy()
    rc["TrackKey"] = rc["RaceKey"].map(track_key).fillna(rc["CircuitId"])
    out = {"types": {}}
    for typ in ("SC", "VSC", "RED"):
        n = dep[dep["type"] == typ].groupby("RaceKey").size()
        rc[typ] = rc["RaceKey"].map(n).fillna(0)
        # Era test: does 2026 differ from earlier seasons? (rate ratio, Poisson CI)
        a26, n26 = rc.loc[rc.Year == 2026, typ].sum(), (rc.Year == 2026).sum()
        a0, n0 = rc.loc[rc.Year < 2026, typ].sum(), (rc.Year < 2026).sum()
        rr = (a26 / n26) / (a0 / n0) if a0 and n26 else np.nan
        se_log = np.sqrt(1 / max(a26, 0.5) + 1 / max(a0, 0.5))
        era = {"rate_2026": a26 / n26 if n26 else None, "rate_pre2026": a0 / n0,
               "ratio": rr, "ratio_ci95": [rr * np.exp(-1.96 * se_log), rr * np.exp(1.96 * se_log)],
               "n_races_2026": int(n26), "n_races_pre": int(n0)}
        era["apply_2026_ratio"] = bool(np.isfinite(rr) and not (era["ratio_ci95"][0] <= 1 <= era["ratio_ci95"][1]))
        # Wet vs dry rate ratio.
        w, d = rc[rc.MixedOrWetRace], rc[~rc.MixedOrWetRace]
        wet_rr = (w[typ].mean() / d[typ].mean()) if d[typ].mean() > 0 else np.nan
        se_w = np.sqrt(1 / max(w[typ].sum(), 0.5) + 1 / max(d[typ].sum(), 0.5))
        # Per-track EB on dry races (wet effect handled by the ratio).
        a, b = negbin_fit(d[typ].values)
        x = d[typ].values
        dispersion = float(x.var() / x.mean()) if x.mean() > 0 else None
        tracks = {}
        for tk, g in d.groupby("TrackKey"):
            tracks[tk] = {"rate_per_race": (a + g[typ].sum()) / (b + len(g)),
                          "sd": float(np.sqrt((a + g[typ].sum()) / (b + len(g)) ** 2)),
                          "n_races": int(len(g)), "observed": int(g[typ].sum())}
        dd = dep[dep["type"] == typ]
        frac_bins = np.linspace(0, 1, 11)
        out["types"][typ] = {
            "prior_gamma_a": min(a, 1e4), "prior_gamma_b": min(b, 1e4) if a < 1e4 else 1e4 / float(d[typ].mean()),
            "variance_to_mean": dispersion,
            "between_track_variation_detected": bool(a < 50), "pooled_rate_dry": float(d[typ].mean()),
            "wet_rate_ratio": wet_rr, "wet_ratio_ci95": [wet_rr * np.exp(-1.96 * se_w), wet_rr * np.exp(1.96 * se_w)],
            "n_wet_races": int(len(w)), "era_2026": era, "tracks": tracks,
            "lap1_share": float((dd["lap"] == 1).mean()) if len(dd) else None,
            "lap_frac_hist": np.histogram(dd.loc[dd["lap"] > 1, "lap_frac"].clip(0, 1), frac_bins)[0].tolist(),
            "lap_frac_bins": frac_bins.tolist(),
            "duration_laps_pmf": dd["duration_laps"].dropna().astype(int).value_counts(normalize=True).sort_index().to_dict(),
            "n_deployments": int(len(dd))}
    return out


def neutralised_pace(laps: pd.DataFrame, clean: pd.Series) -> dict:
    """Lap time under SC / VSC as a ratio of the race's median clean lap."""
    med = laps[clean].groupby("RaceKey")["LapTimeS"].median()
    out = {}
    for typ, code in (("SC", "4"), ("VSC", "6")):
        m = laps["TrackStatus"].fillna("").str.fullmatch(code) & ~laps["PitIn"] & ~laps["PitOut"] & laps["LapTimeS"].notna()
        r = laps.loc[m, "LapTimeS"] / laps.loc[m, "RaceKey"].map(med)
        r = r.dropna()
        out[typ] = {"median_ratio": float(r.median()), "q10": float(r.quantile(.1)),
                    "q90": float(r.quantile(.9)), "n_laps": int(len(r))}
    return out


# --------------------------------------------------------------- retirements
def betabin_fit(k, n):
    k, n = np.asarray(k, float), np.asarray(n, float)

    def nll(t):
        a, b = np.exp(t)
        return -np.sum(betaln(k + a, n - k + b) - betaln(a, b))
    o = minimize(nll, np.log([1.0, 10.0]), method="Nelder-Mead")
    return np.exp(o.x)


def dnf_params(res: pd.DataFrame, races: pd.DataFrame, track_key: dict) -> dict:
    r = res[~res["Status"].isin(NOT_RACED)].copy()
    r = r[~r[["Year", "Round"]].apply(tuple, axis=1).isin(C.EXCLUDE_RACES)]
    r["dnf"] = ~r["Status"].str.match(FINISHED) & (r["Status"] != "Disqualified")
    r = r.merge(races[["RaceKey", "TotalLaps", "MixedOrWetRace"]], on="RaceKey")
    r["TrackKey"] = r["RaceKey"].map(track_key).fillna(r["CircuitId"])
    by_season = r.groupby("Year")["dnf"].agg(["mean", "sum", "count"])
    # Team-season reliability for the target season (EB beta-binomial).
    cur = r[r.Year == r.Year.max()]
    ts = cur.groupby("TeamId")["dnf"].agg(["sum", "count"])
    a, b = betabin_fit(ts["sum"], ts["count"])
    season_rate = cur["dnf"].mean()
    teams = {t: {"rate": (a + v["sum"]) / (a + b + v["count"]),
                 "ratio_to_season": ((a + v["sum"]) / (a + b + v["count"])) / season_rate,
                 "dnf": int(v["sum"]), "starts": int(v["count"])} for t, v in ts.iterrows()}
    # Track factor (EB) over all seasons, as a ratio to each season's rate.
    tr = r.groupby("TrackKey")["dnf"].agg(["sum", "count"])
    a2, b2 = betabin_fit(tr["sum"], tr["count"])
    overall = r["dnf"].mean()
    tracks = {t: {"rate": (a2 + v["sum"]) / (a2 + b2 + v["count"]),
                  "ratio": ((a2 + v["sum"]) / (a2 + b2 + v["count"])) / overall,
                  "starts": int(v["count"])} for t, v in tr.iterrows()}
    # When in the race: completed-lap fraction at retirement.
    d = r[r["dnf"]]
    frac = (d["Laps"] / d["TotalLaps"]).clip(0, 1)
    bins = np.linspace(0, 1, 11)
    return {"season_rates": {int(y): {"rate": v["mean"], "dnf": int(v["sum"]), "starts": int(v["count"])}
                             for y, v in by_season.iterrows()},
            "target_season": int(r.Year.max()), "target_season_rate": season_rate,
            "teams_target_season": teams, "team_prior_beta": [a, b],
            "tracks": tracks, "track_prior_beta": [a2, b2],
            "wet_rate": float(r.loc[r.MixedOrWetRace, "dnf"].mean()),
            "dry_rate": float(r.loc[~r.MixedOrWetRace, "dnf"].mean()),
            "lap1_share": float((d["Laps"] == 0).mean()),
            "lap_frac_hist": np.histogram(frac[d["Laps"] > 0], bins)[0].tolist(), "lap_frac_bins": bins.tolist(),
            "n_dnf": int(len(d)), "n_starts": int(len(r))}


# ----------------------------------------------------------------- lap 1
def start_params(laps: pd.DataFrame, res: pd.DataFrame, races: pd.DataFrame, track_key: dict) -> dict:
    l1 = laps[(laps["LapNumber"] == 1) & laps["Position"].notna()][["RaceKey", "Driver", "Position"]]
    g = res[["RaceKey", "Abbreviation", "GridPosition"]].rename(columns={"Abbreviation": "Driver"})
    j = l1.merge(g, on=["RaceKey", "Driver"])
    n_cars = j.groupby("RaceKey")["Driver"].transform("count")
    j["grid"] = np.where(j["GridPosition"] <= 0, n_cars, j["GridPosition"])  # pit lane = back
    j = j[~j["RaceKey"].isin({f"{y}_{r:02d}" for y, r in C.EXCLUDE_RACES})]
    j["change"] = j["Position"] - j["grid"]
    j["TrackKey"] = j["RaceKey"].map(track_key)
    j["wet"] = j["RaceKey"].map(races.set_index("RaceKey")["MixedOrWetRace"])
    pmf = {}
    for gp, d in j[~j.wet].groupby("grid"):
        pmf[int(gp)] = {"pmf": d["change"].astype(int).value_counts(normalize=True).sort_index().to_dict(),
                        "n": int(len(d))}
    # Track scale: spread of lap-1 change vs the pooled spread, EB-shrunk in log space.
    pooled_sd = j.loc[~j.wet, "change"].std()
    tracks = {}
    for tk, d in j[~j.wet].groupby("TrackKey"):
        s = d["change"].std()
        n_races = d["RaceKey"].nunique()
        w = n_races / (n_races + 3.0)   # placeholder replaced below by fitted k
        tracks[tk] = {"raw_ratio": float(s / pooled_sd), "n_races": int(n_races), "n": int(len(d))}
    # Fit the shrinkage constant k by between-track variance of log ratios.
    lr = np.log([v["raw_ratio"] for v in tracks.values()])
    nr = np.array([v["n_races"] for v in tracks.values()])
    # sampling var of log sd ~ 1/(2(n-1)) with n ~ 20 cars per race
    samp = 1 / (2 * (np.array([v["n"] for v in tracks.values()]) - 1))
    tau2 = max(np.var(lr) - np.mean(samp), 1e-6)
    for (tk, v), l, s in zip(tracks.items(), lr, samp):
        B = s / (s + tau2)
        v["ratio"] = float(np.exp((1 - B) * l))
    return {"pmf_by_grid": pmf, "pooled_sd": float(pooled_sd), "tracks": tracks,
            "between_track_tau_log": float(np.sqrt(tau2)), "n_starts": int((~j.wet).sum())}
