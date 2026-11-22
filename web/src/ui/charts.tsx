// SVG charts. Conventions (dataviz skill): thin 2px lines, recessive solid
// hairline grid, one y-axis, legend for >= 2 series plus direct labels on the
// highlighted ones, crosshair + tooltip on hover, text in text tokens.
// Motion: lines draw in (pathLength 1 + dash offset), bars sweep from their
// baseline, all by CSS so reduced motion turns it off; a focused driver
// (hovered anywhere on the page) is brought forward and the rest recede.
import { useMemo, useRef, useState } from "preact/hooks";
import type { Compound } from "../engine/types.ts";

const W = 900;

function ticks(min: number, max: number, n = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return [min];
  const raw = (max - min) / n, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

export interface Series { key: string; label: string; color: string; values: number[]; emphasis: boolean }

export function LineChart(props: { series: Series[]; height?: number; yLabel: string; invert?: boolean; yMaxClip?: number; fmt?: (v: number) => string; bands?: { from: number; to: number; color: string }[]; focusKey?: string | null }) {
  const { series, height = 300, yLabel, invert = false, fmt = (v) => v.toFixed(1) } = props;
  const M = { l: 48, r: 56, t: 10, b: 28 };
  const N = series[0]?.values.length ?? 0;
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const { y0, y1 } = useMemo(() => {
    let lo = Infinity, hi = -Infinity;
    for (const s of series) for (const v of s.values) if (Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    if (props.yMaxClip !== undefined) hi = Math.min(hi, props.yMaxClip);
    if (!Number.isFinite(lo)) { lo = 0; hi = 1; }
    if (lo > 0) lo = 0;
    return { y0: lo, y1: hi === lo ? lo + 1 : hi };
  }, [series, props.yMaxClip]);
  const x = (i: number) => M.l + (i / Math.max(1, N - 1)) * (W - M.l - M.r);
  const y = (v: number) => { const f = (Math.min(v, y1) - y0) / (y1 - y0); return invert ? M.t + f * (height - M.t - M.b) : height - M.b - f * (height - M.t - M.b); };
  const path = (vals: number[]) => {
    let d = "", pen = false;
    vals.forEach((v, i) => { if (!Number.isFinite(v)) { pen = false; return; } d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true; });
    return d;
  };
  const onMove = (e: MouseEvent) => {
    const r = ref.current!.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(((px - M.l) / (W - M.l - M.r)) * (N - 1));
    setHover(i >= 0 && i < N ? i : null);
  };
  const xt = ticks(1, N, 8).filter((v) => v >= 1);
  const focus = props.focusKey ?? null;
  const rank = (s: Series) => (s.key === focus ? 2 : s.emphasis ? 1 : 0);
  const ordered = [...series].sort((a, b) => rank(a) - rank(b));
  const shown = series.filter((s) => s.emphasis || s.key === focus);
  const width = (s: Series) => (s.key === focus ? 2.75 : s.emphasis ? 2 : 1);
  const opacity = (s: Series) => (!focus ? (s.emphasis ? 1 : 0.55) : s.key === focus ? 1 : s.emphasis ? 0.3 : 0.18);
  return (
    <div class="chart">
      <svg ref={ref} viewBox={`0 0 ${W} ${height}`} onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img" aria-label={yLabel}>
        {props.bands?.map((b) => <rect x={x(b.from - 1) - 1} width={Math.max(2, x(b.to - 1) - x(b.from - 1) + 2)} y={M.t} height={height - M.t - M.b} fill={b.color} />)}
        {ticks(y0, y1).map((v) => (
          <g><line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} stroke="var(--grid)" stroke-width="1" />
            <text x={M.l - 6} y={y(v) + 4} text-anchor="end">{fmt(v)}</text></g>
        ))}
        {xt.map((v) => <text x={x(v - 1)} y={height - 8} text-anchor="middle">{v}</text>)}
        <text x={W - M.r + 18} y={height - 8}>lap</text>
        <text x={4} y={M.t + 4} transform={`rotate(-90 4 ${M.t + 4})`} text-anchor="end">{yLabel}</text>
        {ordered.map((s, k) => <path class={`draw series ${s.emphasis ? "em" : ""}`} style={{ "--i": s.emphasis ? 8 + k : k }} pathLength={1} d={path(s.values)} fill="none"
          stroke={s.key === focus && !s.emphasis ? "var(--accent-text)" : s.color} stroke-width={width(s)} stroke-opacity={opacity(s)} stroke-linejoin="round" stroke-linecap="round" />)}
        {shown.map((s) => {
          let i = s.values.length - 1;
          while (i > 0 && !Number.isFinite(s.values[i])) i--;
          return <text class="fadein" x={x(i) + 6} y={y(s.values[i]) + 4} style={{ fill: s.key === focus ? "var(--text-primary)" : "var(--text-secondary)", "font-weight": s.key === focus ? 650 : 400 }}>{s.label}</text>;
        })}
        {hover !== null && <g>
          <line x1={x(hover)} x2={x(hover)} y1={M.t} y2={height - M.b} stroke="var(--axis)" />
          {shown.map((s) => Number.isFinite(s.values[hover]) && <circle cx={x(hover)} cy={y(s.values[hover])} r={4} fill={s.color} stroke="var(--surface-1)" stroke-width="2" />)}
        </g>}
        <rect x={M.l} y={M.t} width={W - M.l - M.r} height={height - M.t - M.b} fill="transparent" />
      </svg>
      {hover !== null && (
        <div class="tooltip" style={{ left: `${(x(hover) / W) * 100}%`, top: "8px", transform: x(hover) > W * 0.7 ? "translateX(-105%)" : "translateX(8px)" }}>
          <div class="tt-h">Lap {hover + 1}</div>
          {shown.map((s) => <div><i class="key" style={{ background: s.key === focus && !s.emphasis ? "var(--accent-text)" : s.color }} /><b>{Number.isFinite(s.values[hover]) ? fmt(s.values[hover]) : "out"}</b> <span style={{ color: "var(--text-muted)" }}>{s.label}</span></div>)}
        </div>
      )}
    </div>
  );
}

export function BandChart(props: { p25: number[]; p50: number[]; p75: number[]; height?: number; yLabel: string; w?: number }) {
  const { p25, p50, p75, height = 220, yLabel } = props;
  const W = props.w ?? 900;
  const M = { l: 48, r: 20, t: 10, b: 28 };
  const N = p50.length;
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const all = [...p25, ...p75, 0].filter(Number.isFinite);
  const lo = Math.min(...all), hi = Math.max(...all);
  const pad = (hi - lo) * 0.08 || 1;
  const y0 = lo - pad, y1 = hi + pad;
  const x = (i: number) => M.l + (i / Math.max(1, N - 1)) * (W - M.l - M.r);
  const y = (v: number) => height - M.b - ((v - y0) / (y1 - y0)) * (height - M.t - M.b);
  const band = p75.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join("") + p25.map((_, j) => { const i = N - 1 - j; return `L${x(i)},${y(p25[i])}`; }).join("") + "Z";
  const line = p50.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join("");
  const onMove = (e: MouseEvent) => {
    const r = ref.current!.getBoundingClientRect();
    const i = Math.round((((e.clientX - r.left) / r.width) * W - M.l) / (W - M.l - M.r) * (N - 1));
    setHover(i >= 0 && i < N ? i : null);
  };
  return (
    <div class="chart">
      <svg ref={ref} viewBox={`0 0 ${W} ${height}`} onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img" aria-label={yLabel}>
        {ticks(y0, y1).map((v) => <g><line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} stroke={v === 0 ? "var(--axis)" : "var(--grid)"} />
          <text x={M.l - 6} y={y(v) + 4} text-anchor="end">{v > 0 ? `+${v}` : v}</text></g>)}
        {ticks(1, N, 8).map((v) => <text x={x(v - 1)} y={height - 8} text-anchor="middle">{v}</text>)}
        <path class="fadein" d={band} fill="var(--series-1)" fill-opacity="0.14" />
        <path class="draw em" pathLength={1} d={line} fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
        {hover !== null && <g><line x1={x(hover)} x2={x(hover)} y1={M.t} y2={height - M.b} stroke="var(--axis)" />
          <circle cx={x(hover)} cy={y(p50[hover])} r="4" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2" /></g>}
      </svg>
      {hover !== null && <div class="tooltip" style={{ left: `${(x(hover) / W) * 100}%`, top: "8px", transform: x(hover) > W * 0.7 ? "translateX(-105%)" : "translateX(8px)" }}>
        <div class="tt-h">After lap {hover + 1}</div>
        <div>Median: <b>{p50[hover] > 0 ? "+" : ""}{p50[hover].toFixed(2)} s</b></div>
        <div>Middle 50%: {p25[hover].toFixed(2)} to {p75[hover].toFixed(2)} s</div>
      </div>}
    </div>
  );
}

export const COMPOUND_COLOR: Record<Compound, string> = {
  SOFT: "var(--c-soft)", MEDIUM: "var(--c-medium)", HARD: "var(--c-hard)", INTERMEDIATE: "var(--c-inter)", WET: "var(--c-wet)",
};
export const COMPOUND_LETTER: Record<Compound, string> = { SOFT: "S", MEDIUM: "M", HARD: "H", INTERMEDIATE: "I", WET: "W" };

export function StintMap(props: { rows: { code: string; pos: number; dnf: boolean; stints: { compound: Compound; from: number; to: number }[]; user: boolean }[]; laps: number; status: number[]; wetness: number[] | null; focus?: string | null; onFocus?: (code: string | null) => void }) {
  const { rows, laps, status } = props;
  const rowH = 14, gap = 6, M = { l: 70, r: 12, t: 6, b: 24 };
  const focus = props.focus ?? null;
  const H = M.t + rows.length * (rowH + gap) + M.b;
  const x = (lap: number) => M.l + ((lap - 1) / laps) * (W - M.l - M.r);
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const bands: { from: number; to: number; s: number }[] = [];
  status.forEach((s, i) => { if (s) { const last = bands[bands.length - 1]; if (last && last.s === s && last.to === i) last.to = i + 1; else bands.push({ from: i + 1, to: i + 1, s }); } });
  const bandColor = (s: number) => (s === 1 ? "var(--sc)" : s === 2 ? "var(--vsc)" : "var(--red)");
  return (
    <div class="chart">
      <svg viewBox={`0 0 ${W} ${H}`} onMouseLeave={() => { setTip(null); props.onFocus?.(null); }} role="img" aria-label="Tyre stint map">
        {bands.map((b) => <rect x={x(b.from)} width={x(b.to + 1) - x(b.from)} y={M.t - 2} height={H - M.t - M.b + 2} fill={bandColor(b.s)} />)}
        {ticks(1, laps, 10).map((v) => <text x={x(v) + (x(2) - x(1)) / 2} y={H - 8} text-anchor="middle">{v}</text>)}
        {rows.map((r, k) => {
          const yy = M.t + k * (rowH + gap);
          return <g class={`row ${focus && focus !== r.code ? "row-dim" : ""}`} onMouseEnter={() => props.onFocus?.(r.code)}>
            <rect x={0} y={yy - gap / 2} width={W} height={rowH + gap} fill="transparent" />
            <text x={M.l - 8} y={yy + rowH - 3} text-anchor="end" style={{ fill: r.user || focus === r.code ? "var(--text-primary)" : "var(--text-secondary)", "font-weight": r.user || focus === r.code ? 650 : 400 }}>{r.dnf ? "DNF" : `P${r.pos}`} {r.code}</text>
            {r.stints.filter((s) => s.to >= s.from).map((s) => {
              const x0 = x(s.from) + 1, x1 = x(s.to + 1) - 1, w = Math.max(1, x1 - x0);
              return <g onMouseMove={(e) => setTip({ x: (e as MouseEvent).offsetX, y: yy, text: `${r.code}: ${s.compound} laps ${s.from}–${s.to} (${s.to - s.from + 1})` })}>
                <rect class="sweep" style={{ "--i": k }} x={x0} y={yy} width={w} height={rowH} rx="4" fill={COMPOUND_COLOR[s.compound]} fill-opacity={r.user ? 1 : 0.82} />
                {w > 16 && <text class="fadein" x={x0 + 5} y={yy + rowH - 3} style={{ fill: "#0c0d12", "font-weight": 700, "font-size": "9.5px" }}>{COMPOUND_LETTER[s.compound]}</text>}
              </g>;
            })}
          </g>;
        })}
      </svg>
      {tip && <div class="tooltip" style={{ left: `${tip.x + 12}px`, top: `${tip.y}px` }}>{tip.text}</div>}
    </div>
  );
}

export function PairedBars(props: { items: { label: string; a: number; b: number }[]; aLabel: string; bLabel: string; unit: string; w?: number }) {
  const { items, aLabel, bLabel, unit } = props;
  const W = props.w ?? 900;
  const rowH = 30, M = { l: 130, r: 70, t: 4, b: 6 }, H = M.t + items.length * rowH + M.b;
  const hi = Math.max(1, ...items.flatMap((i) => [Math.abs(i.a), Math.abs(i.b)]));
  const lo = Math.min(0, ...items.flatMap((i) => [i.a, i.b]));
  const x = (v: number) => M.l + ((v - lo) / (hi - lo)) * (W - M.l - M.r);
  return (
    <div class="chart">
      <div class="legend"><span><i class="sq" style={{ background: "var(--series-1)" }} />{aLabel}</span><span><i class="sq" style={{ background: "var(--series-2)" }} />{bLabel}</span></div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Time breakdown">
        <line x1={x(0)} x2={x(0)} y1={M.t} y2={H - M.b} stroke="var(--axis)" />
        {items.map((it, k) => {
          const yy = M.t + k * rowH;
          const bar = (v: number, dy: number, c: string) => <rect class="sweep" style={{ "--i": k * 2 + (dy > 5 ? 1 : 0), "transform-origin": v < 0 ? "right center" : "left center" }} x={Math.min(x(0), x(v))} y={yy + dy} width={Math.max(1, Math.abs(x(v) - x(0)))} height={10} rx="3" fill={c} />;
          return <g>
            <text x={M.l - 8} y={yy + 15} text-anchor="end" style={{ fill: "var(--text-secondary)" }}>{it.label}</text>
            {bar(it.a, 3, "var(--series-1)")}{bar(it.b, 15, "var(--series-2)")}
            <text x={Math.max(x(it.a), x(0)) + 4} y={yy + 12}>{it.a.toFixed(1)}{unit}</text>
            <text x={Math.max(x(it.b), x(0)) + 4} y={yy + 24}>{it.b.toFixed(1)}{unit}</text>
          </g>;
        })}
      </svg>
    </div>
  );
}

/** Position distribution strip: one cell per finishing position, sequential blue. */
export function Heat(props: { hist: number[] }) {
  const max = Math.max(...props.hist);
  return <div class="heat" title={props.hist.map((p, i) => `${i < props.hist.length - 1 ? "P" + (i + 1) : "DNF"} ${(100 * p).toFixed(1)}%`).join("\n")}>
    {props.hist.map((p) => <i style={{ background: p === 0 ? "var(--surface-3)" : `rgba(57,135,229,${0.15 + 0.85 * (p / max)})` }} />)}
  </div>;
}
