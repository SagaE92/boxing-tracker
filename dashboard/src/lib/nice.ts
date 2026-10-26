/** Round axis ticks: step = 1, 2, 2.5 or 5 x 10^k so that there are at most `maxTicks` ticks;
 *  range snapped outwards to whole steps (e.g. 72..118 -> 60, 80, 100, 120). */
export function niceScale(values: number[], maxTicks = 5): { lo: number; hi: number; step: number; ticks: number[] } {
  const v = values.filter((x) => Number.isFinite(x));
  let min = v.length ? Math.min(...v) : 0, max = v.length ? Math.max(...v) : 1;
  if (max - min < 1e-9) { min -= 1; max += 1; }
  const raw = (max - min) / Math.max(1, maxTicks - 1);
  const mag = 10 ** Math.floor(Math.log10(raw));
  let step = mag * 10;
  for (const m of [1, 2, 2.5, 5, 10]) {
    const st = m * mag;
    if (Math.ceil(max / st) - Math.floor(min / st) + 1 <= maxTicks) { step = st; break; }
  }
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let t = lo; t <= hi + step * 1e-6; t += step) ticks.push(+t.toFixed(10));
  return { lo, hi, step, ticks };
}
