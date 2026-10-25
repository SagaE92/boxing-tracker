import type { RawData } from './types';

export function lowerBound(t: ArrayLike<number>, x: number): number {
  let lo = 0, hi = t.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (t[mid] < x) lo = mid + 1; else hi = mid; }
  return lo;
}

/**
 * Min/max decimation for line charts: for each of `buckets` bins inside [x0, x1]
 * emit 2 points (min then max, in time order). If the range already has fewer
 * samples than 2*buckets, the raw samples are returned unchanged.
 * Series values are taken from `cols`; gaps (dt > gapS) produce a null break.
 */
export function decimate(t: Float64Array, cols: ArrayLike<number>[], x0: number, x1: number, buckets: number, gapS = Infinity): { x: number[]; ys: (number | null)[][] } {
  const i0 = Math.max(0, lowerBound(t, x0) - 1), i1 = Math.min(t.length, lowerBound(t, x1) + 1);
  const n = i1 - i0;
  const x: number[] = [];
  const ys: (number | null)[][] = cols.map(() => []);
  if (n <= 0) return { x, ys };
  if (n <= buckets * 2) {
    for (let i = i0; i < i1; i++) {
      if (i > i0 && t[i] - t[i - 1] > gapS) { x.push((t[i] + t[i - 1]) / 2); ys.forEach((y) => y.push(null)); }
      x.push(t[i]); cols.forEach((c, k) => ys[k].push(c[i]));
    }
    return { x, ys };
  }
  const span = (t[i1 - 1] - t[i0]) || 1;
  let i = i0;
  for (let b = 0; b < buckets && i < i1; b++) {
    const bEnd = t[i0] + (span * (b + 1)) / buckets;
    const start = i;
    const mins = cols.map(() => Infinity), maxs = cols.map(() => -Infinity);
    let gap = false;
    while (i < i1 && (t[i] <= bEnd || i === start)) {
      if (i > start && t[i] - t[i - 1] > gapS) gap = true;
      for (let k = 0; k < cols.length; k++) { const v = cols[k][i]; if (v < mins[k]) mins[k] = v; if (v > maxs[k]) maxs[k] = v; }
      i++;
    }
    const tA = t[start], tB = t[i - 1];
    if (gap || (x.length && tA - x[x.length - 1] > gapS)) { x.push(tA - 1e-6); ys.forEach((y) => y.push(null)); }
    x.push(tA); x.push(tB === tA ? tA + 1e-6 : tB);
    for (let k = 0; k < cols.length; k++) { ys[k].push(mins[k]); ys[k].push(maxs[k]); }
  }
  return { x, ys };
}

/** Max-only envelope (for overview of |a|-1g). */
export function envelope(raw: RawData, buckets: number): { x: number[]; y: number[] } {
  const x: number[] = [], y: number[] = [];
  if (!raw.n) return { x, y };
  const t0 = raw.t[0], span = raw.t[raw.n - 1] - t0 || 1;
  let i = 0;
  for (let b = 0; b < buckets && i < raw.n; b++) {
    const end = t0 + (span * (b + 1)) / buckets;
    let m = -Infinity; const s = i;
    while (i < raw.n && (raw.t[i] <= end || i === s)) { if (raw.amag[i] > m) m = raw.amag[i]; i++; }
    x.push((raw.t[s] + raw.t[i - 1]) / 2); y.push(m);
  }
  return { x, y };
}

/** Contiguous runs of sat=1 as [t0, t1] pairs. */
export function satRuns(raw: RawData): [number, number][] {
  const out: [number, number][] = [];
  let s = -1;
  for (let i = 0; i < raw.n; i++) {
    if (raw.sat[i] && s < 0) s = i;
    else if (!raw.sat[i] && s >= 0) { out.push([raw.t[s], raw.t[i - 1]]); s = -1; }
  }
  if (s >= 0) out.push([raw.t[s], raw.t[raw.n - 1]]);
  return out;
}
