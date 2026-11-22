// Seeded PRNG (sfc32) and the few distributions the engine needs.
// Seeded so a run is reproducible and paired strategy comparisons can use
// common random numbers.

export class Rng {
  private a: number; private b: number; private c: number; private d: number;
  private spare: number | null = null;

  constructor(seed: number) {
    // splitmix32 to expand the seed
    let s = seed >>> 0;
    const next = () => {
      s = (s + 0x9e3779b9) >>> 0;
      let z = s;
      z = Math.imul(z ^ (z >>> 16), 0x85ebca6b) >>> 0;
      z = Math.imul(z ^ (z >>> 13), 0xc2b2ae35) >>> 0;
      return (z ^ (z >>> 16)) >>> 0;
    };
    this.a = next(); this.b = next(); this.c = next(); this.d = next();
    for (let i = 0; i < 12; i++) this.u();
  }

  /** Uniform [0, 1). */
  u(): number {
    const t = (((this.a + this.b) >>> 0) + this.d) >>> 0;
    this.d = (this.d + 1) >>> 0;
    this.a = this.b ^ (this.b >>> 9);
    this.b = (this.c + (this.c << 3)) >>> 0;
    this.c = ((this.c << 21) | (this.c >>> 11)) >>> 0;
    this.c = (this.c + t) >>> 0;
    return t / 4294967296;
  }

  normal(mean = 0, sd = 1): number {
    if (this.spare !== null) { const v = this.spare; this.spare = null; return mean + sd * v; }
    let u = 0, v = 0;
    while (u <= 1e-12) u = this.u();
    v = this.u();
    const r = Math.sqrt(-2 * Math.log(u));
    this.spare = r * Math.sin(2 * Math.PI * v);
    return mean + sd * r * Math.cos(2 * Math.PI * v);
  }

  poisson(lambda: number): number {
    if (lambda <= 0) return 0;
    const L = Math.exp(-lambda);
    let k = 0, p = 1;
    do { k++; p *= this.u(); } while (p > L);
    return k - 1;
  }

  int(n: number): number { return Math.floor(this.u() * n); }
}

// ---- compiled samplers (built once per run)

export interface QTable { p0: number; p1: number; vals: Float64Array }
export function compileQuantiles(q: Record<string, number>): QTable {
  const ps = Object.keys(q).map(Number).sort((a, b) => a - b);
  const byNum = new Map(Object.entries(q).map(([k, v]) => [Number(k), v]));
  return { p0: ps[0], p1: ps[ps.length - 1], vals: Float64Array.from(ps.map((x) => byNum.get(x)!)) };
}
/** Draw from a quantile table whose levels run evenly from p0 to p1; the
 *  tails below p0 and above p1 are extended linearly with the end slopes. */
export function sampleQ(t: QTable, rng: Rng, min = -Infinity): number {
  const n = t.vals.length, v = t.vals;
  const x = ((rng.u() - t.p0) / (t.p1 - t.p0)) * (n - 1);
  let out: number;
  if (x <= 0) out = v[0] + x * (v[1] - v[0]);
  else if (x >= n - 1) out = v[n - 1] + (x - (n - 1)) * (v[n - 1] - v[n - 2]);
  else { const i = Math.floor(x), f = x - i; out = v[i] * (1 - f) + v[i + 1] * f; }
  return Math.max(min, out);
}

export interface Pmf { keys: Float64Array; cdf: Float64Array }
export function compilePmf(pmf: Record<string, number>): Pmf {
  const ks = Object.keys(pmf);
  const total = ks.reduce((a, k) => a + pmf[k], 0) || 1;
  let acc = 0;
  return { keys: Float64Array.from(ks.map(Number)), cdf: Float64Array.from(ks.map((k) => (acc += pmf[k] / total))) };
}
export function samplePmf(p: Pmf, rng: Rng): number {
  const u = rng.u();
  for (let i = 0; i < p.cdf.length; i++) if (u <= p.cdf[i]) return p.keys[i];
  return p.keys[p.keys.length - 1];
}
export function compileHist(counts: number[], bins: number[]): { pmf: Pmf; bins: number[] } {
  const pm: Record<string, number> = {};
  counts.forEach((c, i) => { pm[String(i)] = c; });
  return { pmf: compilePmf(pm), bins };
}
export function sampleHistC(h: { pmf: Pmf; bins: number[] }, rng: Rng): number {
  const i = samplePmf(h.pmf, rng);
  return h.bins[i] + rng.u() * (h.bins[i + 1] - h.bins[i]);
}
