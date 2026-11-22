// Optional explanation panel. Claude only interprets the model's outputs
// (principle 5); it never makes the prediction. Shown only when the site is
// built with VITE_EXPLAIN_URL pointing at the small proxy in /server, so no
// API key ever reaches the browser.
import { useState } from "preact/hooks";
import type { MCResult } from "../engine/montecarlo.ts";

const URL_ = (import.meta as unknown as { env: Record<string, string | undefined> }).env.VITE_EXPLAIN_URL;

export function summarise(r: MCResult) {
  const me = r.drivers.find((d) => d.isUser)!;
  return {
    track: r.trackName, laps: r.laps, sims: r.sims, weather: r.scenario.weather, grid: r.scenario.grid,
    driver: { name: me.name, car: me.teamName, skill_pct: me.skillPct, skill_sd: me.skillSd, car_pct: me.carPct, car_sd: me.carSd, car_source: me.carSource },
    user_result: { win: me.win, podium: me.podium, points: me.points, dnf: me.dnf, mean_pos: me.meanPos, exp_points: me.expPoints },
    top_drivers: r.drivers.slice(0, 8).map((d) => ({ name: d.name, car: d.teamName, win: d.win, podium: d.podium, exp_points: d.expPoints })),
    chosen: { label: r.chosen.label, exp_points: r.chosen.expPoints, mean_pos: r.chosen.meanPos, parts_s: r.chosen.parts },
    alternative: r.alternative && { label: r.alternative.label, exp_points: r.alternative.expPoints, mean_pos: r.alternative.meanPos, parts_s: r.alternative.parts },
    neutralisations_share: r.neutralShare, warnings: r.warnings,
  };
}

export function ExplainPanel({ result }: { result: MCResult }) {
  const [text, setText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!URL_) return null;
  const ask = async () => {
    setBusy(true); setErr(null); setText(null);
    try {
      const res = await fetch(URL_, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ summary: summarise(result) }) });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? res.statusText);
      setText(j.text);
    } catch (e) { setErr(String((e as Error).message ?? e)); }
    setBusy(false);
  };
  return (
    <div class="panel">
      <h2>Explain these results (Claude)</h2>
      <div class="sub">Claude reads only the numbers above and explains them. It does not change or add to the prediction.</div>
      <button class="btn" onClick={ask} disabled={busy}>{busy ? "Asking…" : "Explain"}</button>
      {err && <div class="err" style={{ marginTop: "8px" }}>{err}</div>}
      {text && <div class="explain" style={{ marginTop: "10px" }}>{text}</div>}
    </div>
  );
}
