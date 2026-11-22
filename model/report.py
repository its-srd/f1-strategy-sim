"""Render the fitted-results section of docs/assumptions.md from data/params.

Everything between the AUTO markers is regenerated, and the hand-written
structural assumptions above it are left alone.
    .venv/bin/python model/report.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "data" / "params"
DOC = ROOT / "docs" / "assumptions.md"
START, END = "<!-- AUTO:START -->", "<!-- AUTO:END -->"


def f(x, n=3):
    return "–" if x is None else f"{x:.{n}f}"


def main():
    meta = json.loads((P / "meta.json").read_text())
    g = json.loads((P / "global.json").read_text())
    tracks = json.loads((P / "tracks.json").read_text())
    drivers = json.loads((P / "drivers.json").read_text())
    teams = json.loads((P / "teams.json").read_text())
    grid = json.loads((P / "grid_2026.json").read_text())
    L = [START, "", f"_Generated {meta['generated_utc'][:16]} UTC by `model/report.py` from `data/params/`. Do not edit by hand._", ""]

    L += ["## Fitted results", "", "### Data used", "",
          f"{meta['races_in_data']} races ({meta['first_race'][0]} {meta['first_race'][1]} to {meta['last_race'][0]} {meta['last_race'][1]}), "
          f"{meta['lap_rows']:,} driver-laps. Dry-pace fits use {meta['clean_laps']:,} clean laps from {meta['dry_races_fitted']} dry races. "
          f"{meta['outlier_laps_removed']:,} outlier laps and {meta['compound_laps_dropped_thin']:,} laps on thinly-run compounds were removed (F8, F10).", "",
          "| Clean-lap rule (applied in order) | Laps removed |", "|---|---|"]
    L += [f"| {k} | {v:,} |" for k, v in meta["filter_removed"].items()]

    sm = g["skill_model"]
    L += ["", "### Driver skill vs car pace", "",
          f"Mixed model on {sm['n_obs']:,} driver-race pace values. Fitted: extra race-to-race noise tau = {sm['tau_pct']:.3f}%, "
          f"year-to-year skill drift omega = {sm['omega_pct_per_year']:.3f}% per season (the recency weighting), "
          f"spread of skill at a driver's first season sigma0 = {sm['sigma0_pct']:.3f}%. {sm['n_downweighted']} outlier driver-races were down-weighted.", "",
          "Current grid, skill projected to 2026 (negative = faster than the average driver; ±1 SD):", "",
          "| Driver | Skill % | SD % | Dry races fitted | Wet adj. % (pooled) |", "|---|---|---|---|---|"]
    for d in sorted({x["driver_id"] for x in grid["grid"]}, key=lambda k: drivers.get(k, {}).get("skill_pct", 9)):
        v = drivers.get(d)
        if v:
            L.append(f"| {v['name']} | {v['skill_pct']:+.3f} | {v['sd_pct']:.3f} | {v['career_dry_races_fitted']} | {v['wet_extra_pct']:+.2f} ± {v['wet_extra_sd']:.2f} ({v['wet_races']} wet races) |")
    L += ["", "2026 car pace (team-season mean, percent of lap time; negative = faster):", "",
          "| Team | Car % | SD % | 2026 races | Retirement rate 2026 (EB) |", "|---|---|---|---|---|"]
    for k, v in sorted(teams.items(), key=lambda kv: kv[1]["season_mean_pct"]):
        dn = v.get("dnf") or {}
        L.append(f"| {v['name']} | {v['season_mean_pct']:+.3f} | {v['season_sd_pct']:.3f} | {v['n_races']} | {f(dn.get('rate'))} ({dn.get('dnf', '–')}/{dn.get('starts', '–')}) |")

    val = g["validation"]
    L += ["", "### Validation V1 (2026 rules) and V2 (2022 18-inch tyres)", "",
          "Score = one-step-ahead predictive log-likelihood (per-track parameters) or marginal likelihood (skill). "
          "A break is used only when it beats carry-over by more than 2 units.", "",
          "| Quantity | V2: break - carry (2022) | Decision | V1: break - carry (2026) | Decision | n obs after 2026 |", "|---|---|---|---|---|---|"]
    for p in val["V1_2026"]["track_params"]:
        a, b = val["V2_2022"]["track_params"][p], val["V1_2026"]["track_params"][p]
        L.append(f"| {p} | {a['break_minus_carry']:+.1f} | {a['decision']} | {b['break_minus_carry']:+.1f} | {b['decision']} | {b['n_obs_after_break']} |")
    a, b = val["V2_2022"]["skill"], val["V1_2026"]["skill"]
    L.append(f"| driver skill | {a['break_minus_carry']:+.1f} | {a['decision']} | {b['break_minus_carry']:+.1f} | {b['decision']} | – |")
    cc = val["car_order_correlation"]
    L += ["", "Team order correlation with the previous season (team-season mean car pace): " +
          ", ".join(f"{y}: {v['corr']:.2f}" for y, v in cc.items()) +
          ". Car pace is never carried across seasons. It is fitted per team per race.", ""]

    L += ["### Pooled lap-time parameters", "",
          "| Parameter | Pooled mean (% of lap) | Between-track SD | Drift per season | Tracks | Breaks used |", "|---|---|---|---|---|---|"]
    for p, v in g["pooled"]["pace"].items():
        L.append(f"| {p} | {f(v['mean_pct'], 4)} | {f(v['sd_pct'], 4)} | {f(v['omega_pct_per_year'], 4)} | {v['n_tracks']} | {', '.join(map(str, v['breaks'])) or '–'} |")
    te = g["temperature_effects_pct_per_degC"]
    L += ["", "Track temperature (within-track, across years): " + "; ".join(
        f"{k}: {v['per_degC']:+.5f} ± {v['se']:.5f} %/°C (n={v['n_races']})" for k, v in te.items() if v) +
        ". **No effect is distinguishable from zero**, so the simulator applies none (T1).", ""]

    L += ["### 2026 calendar tracks", "",
          "Wear in seconds per lap of tyre age (net of fuel). Source `track` = fitted at that track and shrunk toward the pool; `pooled` = no data at that track.", "",
          "| Track | Dry races | Base lap s | Wear S / M / H (s/lap) | Pit loss s | SC / VSC per race | Overtake difficulty | Notes |", "|---|---|---|---|---|---|---|---|"]
    for k, v in sorted(tracks.items(), key=lambda kv: kv[1]["round_2026"] or 99):
        if not v["on_2026_calendar"]:
            continue
        if not v["has_dry_data"]:
            L.append(f"| {v['name']} | 0 | – | – | – | – | – | No dry race at this circuit (2026 race was wet). Not simulated. |")
            continue
        pc = v["pace"]
        wear = " / ".join(f"{pc[f'slope_{c}']['mean_s']:+.3f}{'*' if pc[f'slope_{c}']['source'] == 'pooled' else ''}" for c in ("SOFT", "MEDIUM", "HARD"))
        neg = [c for c in ("SOFT", "MEDIUM", "HARD") if pc[f"slope_{c}"]["mean_s"] < 0]
        ov = v["overtake"]
        L.append(f"| {v['name']} | {v['dry_races']} | {v['base_lap']['base_s']:.2f} | {wear} | "
                 f"{f(v['pit']['green_loss_s'], 1) if v['pit'] else '–'} | {f(v['sc_rate']['rate_per_race'], 2) if v['sc_rate'] else '–'} / {f(v['vsc_rate']['rate_per_race'], 2) if v['vsc_rate'] else '–'} | "
                 f"{f(ov['intercept'], 2) if ov else '–'} | {'negative net wear: ' + ', '.join(neg) if neg else ''}{' base scaled from ' + str(v['base_lap']['from_year']) if v['base_lap']['source'] == 'track_scaled' else ''} |")
    L += ["", "\\* pooled value. Overtake difficulty = track intercept in the pass model (lower = harder; 0 = pooled average).", ""]

    sc = g["safety_car"]
    L += ["### Safety car, VSC, red flag", "",
          "| Type | Deployments | Rate per dry race | Variance/mean | Between-track difference detected | Wet ratio (95% CI) | 2026 vs earlier (95% CI) | 2026 ratio applied |", "|---|---|---|---|---|---|---|---|"]
    for t, v in sc.items():
        e = v["era_2026"]
        L.append(f"| {t} | {v['n_deployments']} | {v['pooled_rate_dry']:.3f} | {f(v['variance_to_mean'], 2)} | {'yes' if v['between_track_variation_detected'] else '**no**: every track gets the pooled rate'} | "
                 f"{f(v['wet_rate_ratio'], 2)} ({f(v['wet_ratio_ci95'][0], 2)}–{f(v['wet_ratio_ci95'][1], 2)}) | {f(e['ratio'], 2)} ({f(e['ratio_ci95'][0], 2)}–{f(e['ratio_ci95'][1], 2)}) | {'yes' if e['apply_2026_ratio'] else 'no'} |")
    np_ = g["neutralised_pace"]
    pr = g["pit"]["neutralised_ratio"]
    L += ["", f"Lap time under SC = {np_['SC']['median_ratio']:.3f} x clean lap (n={np_['SC']['n_laps']:,}), under VSC = {np_['VSC']['median_ratio']:.3f} x (n={np_['VSC']['n_laps']:,}). "
          f"Pit stop cost vs cars staying out: under SC {pr['sc']['median_ratio']:.2f} x green loss (n={pr['sc']['n_stops']}), under VSC {pr['vsc']['median_ratio']:.2f} x (n={pr['vsc']['n_stops']}). "
          f"Green-flag stops measured: {g['pit']['n_green_stops']:,}.", ""]

    dn = g["dnf"]
    L += ["### Retirements and starts", "",
          "Retirement rate by season: " + ", ".join(f"{y}: {v['rate']:.3f} ({v['dnf']}/{v['starts']})" for y, v in dn["season_rates"].items()) +
          f". {dn['lap1_share']:.0%} of retirements happen on lap 1. Wet races {dn['wet_rate']:.3f} vs dry {dn['dry_rate']:.3f}. "
          "Cause (mechanical vs incident) is not modelled: Jolpica reports 241 retirements as plain 'Retired' (R4).", "",
          f"Lap-1 position change: empirical distribution per grid slot from {g['start']['n_starts']:,} dry starts; per-track spread scaled by an EB-shrunk ratio "
          f"(between-track SD of log spread = {g['start']['between_track_tau_log']:.2f}).", ""]

    ov = g["overtaking"]
    L += ["### Overtaking", "",
          f"{ov['n_pairs']:,} close-following pairs (within {ov['window_s']} s), {ov['n_passes']:,} passes. "
          f"Pace advantage coefficient {ov['coef']['pace_adv']['beta']:.2f} ± {ov['coef']['pace_adv']['se']:.2f} per s/lap; gap {ov['coef']['gap']['beta']:.2f} ± {ov['coef']['gap']['se']:.2f} per s; "
          f"interaction {ov['coef']['pace_adv_x_gap']['beta']:.2f} ± {ov['coef']['pace_adv_x_gap']['se']:.2f}. Track penalty chosen by 5-fold CV: {ov['penalty']}. "
          "Era offsets: " + ", ".join(f"{k} {v['offset']:+.2f} ± {v['se']:.2f}" for k, v in ov["eras"].items()) + ".", "",
          "Calibration (mean predicted vs observed pass rate by decile of prediction): " +
          ", ".join(f"{p:.3f}/{o:.3f}" for p, o in zip(ov["calibration"]["pred"], ov["calibration"]["obs"])) + ".", ""]

    w = g["wet"]
    L += ["### Wet weather (pooled across all tracks; labelled pooled on the site)", "",
          f"{w['n_wet_races']} races used wet tyres; {w['n_with_dry_reference']} have a dry race at the same track to normalise against.", "",
          f"* Slick/inter crossover from when teams switch tyres: inter lap ratio {w['switch_crossover']['inter_ratio']:.3f} "
          f"(95% CI {w['switch_crossover']['ci95'][0]:.3f}–{w['switch_crossover']['ci95'][1]:.3f}; {w['switch_crossover']['n_races']} races). "
          f"Fitted from laps with both tyre types running: {w['slick_minus_inter']['crossover_inter_ratio']:.3f} (CI {f(w['slick_minus_inter']['crossover_ci95'][0])}–{f(w['slick_minus_inter']['crossover_ci95'][1])}; {w['slick_minus_inter']['n_laps']} laps). The slope is not identified (W3).",
          f"* Inter/full-wet crossover: inter ratio {w['wet_minus_inter']['crossover_inter_ratio']:.3f} (CI {f(w['wet_minus_inter']['crossover_ci95'][0])}–{f(w['wet_minus_inter']['crossover_ci95'][1])}; {w['wet_minus_inter']['n_laps']} laps, {w['wet_minus_inter']['n_races']} races).",
          f"* Drying: inter ratio relaxes with rho = {w['dynamics']['rho']:.3f} per lap (CI {w['dynamics']['rho_ci95'][0]:.3f}–{w['dynamics']['rho_ci95'][1]:.3f}) toward {f(w['dynamics']['stationary_dry_level'])} (inters on a dried track). "
          f"Rainfall flag effect: {w['dynamics_best_tyre']['kappa_rain']:+.4f} (CI {w['dynamics_best_tyre']['kappa_ci95'][0]:+.4f}–{w['dynamics_best_tyre']['kappa_ci95'][1]:+.4f}): **not distinguishable from zero**, so rain onset is replayed from the {len(w['trajectories'])} observed wet-race trajectories (W4).",
          f"* Driver wet skill: {w['driver_wet_skill']['pairs']} teammate pairs in {w['driver_wet_skill']['races']} races; between-driver SD beyond dry skill = {w['driver_wet_skill']['between_driver_sd_pct']:.2f}%. Per-driver values are heavily shrunk (see table above).", "", END]

    text = DOC.read_text()
    block = "\n".join(L)
    if START in text:
        text = text[:text.index(START)] + block + text[text.index(END) + len(END):]
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    DOC.write_text(text)
    print(f"wrote {len(L)} lines to {DOC}")


if __name__ == "__main__":
    main()
