// Lap chart: every car's position at the end of every lap, the way it is
// printed after a race. Rows line up with the timing tower beside it, the
// lines are revealed up to the replay's current lap, and each car's code
// rides at the front of its line. Your car is orange, the four highest
// expected scorers keep their colours from the gap chart, the rest are ink.
import { useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";

export interface LapChartRow { code: string; user: boolean; color?: string; emphasis?: boolean }

let clipSeq = 0;

export function LapChart(props: { rows: LapChartRow[]; pos: Map<string, number[]>; laps: number; lap: number; rowH: number; focus: string | null; onFocus: (code: string | null) => void }) {
  const { rows, pos, laps, lap, rowH, focus } = props;
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(560);
  const [clip] = useState(() => `lapclip${++clipSeq}`);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const M = { l: 4, r: 52, b: 20 };
  const H = rows.length * rowH;
  const x = (i: number) => M.l + (i / Math.max(1, laps - 1)) * (w - M.l - M.r);
  const y = (p: number) => (p - 0.5) * rowH;
  const paths = useMemo(() => new Map(rows.map((r) => {
    let d = "", pen = false;
    (pos.get(r.code) ?? []).forEach((p, i) => {
      if (!Number.isFinite(p)) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(p).toFixed(1)}`;
      pen = true;
    });
    return [r.code, d];
  })), [rows, pos, w, laps, rowH]);
  const rank = (r: LapChartRow) => (r.code === focus ? 3 : r.user ? 2 : r.emphasis ? 1 : 0);
  const ordered = [...rows].sort((a, b) => rank(a) - rank(b));
  const stroke = (r: LapChartRow) => (r.user ? "var(--you)" : r.emphasis && r.color ? r.color : "var(--ink)");
  const width = (r: LapChartRow) => (r.code === focus ? 3 : r.user ? 2.5 : r.emphasis ? 2 : 1.25);
  const opacity = (r: LapChartRow) => {
    if (focus) return r.code === focus ? 1 : r.user || r.emphasis ? 0.35 : 0.1;
    return r.user || r.emphasis ? 1 : 0.22;
  };
  const cx = x(lap - 1);
  const step = laps > 60 ? 10 : 5;
  const lapTicks = [1, ...Array.from({ length: Math.floor(laps / step) }, (_, k) => (k + 1) * step).filter((v) => v < laps), laps];
  return (
    <div class="lapchart" ref={box}>
      <svg width={w} height={H + M.b} viewBox={`0 0 ${w} ${H + M.b}`} role="img" aria-label={`Lap chart up to lap ${lap}`} onMouseLeave={() => props.onFocus(null)}>
        <defs><clipPath id={clip}><rect x={0} y={-6} width={cx + 0.5} height={H + 12} /></clipPath></defs>
        {rows.map((_, k) => k % 2 === 1 && <rect x={0} y={k * rowH} width={w - M.r + 8} height={rowH} fill="rgba(20,20,20,0.03)" />)}
        {lapTicks.map((v) => <g>
          <line x1={x(v - 1)} x2={x(v - 1)} y1={0} y2={H} stroke="var(--grid)" />
          <text x={x(v - 1)} y={H + 14} text-anchor={v === 1 ? "start" : v === laps ? "end" : "middle"}>{v === 1 ? "L1" : v}</text>
        </g>)}
        <g clip-path={`url(#${clip})`}>
          {ordered.map((r) => <path class="l" d={paths.get(r.code)} stroke={stroke(r)} stroke-width={width(r)} stroke-opacity={opacity(r)} />)}
        </g>
        <line class="now" x1={cx} x2={cx} y1={0} y2={H} />
        {ordered.map((r) => {
          const p = pos.get(r.code)?.[lap - 1];
          if (p === undefined || !Number.isFinite(p)) return null;
          const strong = r.user || r.emphasis || r.code === focus;
          return <g onMouseEnter={() => props.onFocus(r.code)}>
            <path class="hit" d={paths.get(r.code)} clip-path={`url(#${clip})`} />
            <circle cx={cx} cy={y(p)} r={strong ? 3.5 : 2.5} fill={strong ? stroke(r) : "var(--ink-3)"} stroke="var(--sheet)" stroke-width="1.5" />
            <text class="code" x={cx + 7} y={y(p) + 4} style={{ fill: r.code === focus || r.user ? "var(--ink)" : strong ? "var(--ink-2)" : "var(--ink-3)", "font-weight": strong ? 700 : 500 }}>{r.code}</text>
          </g>;
        })}
      </svg>
    </div>
  );
}
