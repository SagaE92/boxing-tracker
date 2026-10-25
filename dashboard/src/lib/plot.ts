import type uPlot from 'uplot';

export const AXIS = {
  stroke: '#8592a8',
  grid: { stroke: 'rgba(148,163,184,0.08)', width: 1 },
  ticks: { stroke: 'rgba(148,163,184,0.18)', width: 1, size: 4 },
  font: '11px Inter, system-ui, sans-serif',
};
export const AXIS_COLORS = { x: '#f87171', y: '#4ade80', z: '#60a5fa', mag: '#ffb020' };

export const xTime = (secs: boolean) => (_u: uPlot, vals: number[]) =>
  vals.map((v) => {
    if (v === null || v === undefined) return '';
    if (secs) return `${v.toFixed(Math.abs(v) < 10 ? 2 : 1)}`;
    const m = Math.floor(v / 60), s = v - m * 60;
    return `${m}:${(s < 10 ? '0' : '') + s.toFixed(s % 1 ? 1 : 0)}`;
  });

/** Pixel x for value, in canvas (device) pixels relative to the canvas. */
export function cx(u: uPlot, v: number) { return Math.round(u.valToPos(v, 'x', true)); }
export function cy(u: uPlot, v: number, scale = 'y') { return Math.round(u.valToPos(v, scale, true)); }

export function fillSpan(u: uPlot, t0: number, t1: number, style: string) {
  const { left, top, width, height } = u.bbox;
  const x0 = Math.max(left, cx(u, t0)), x1 = Math.min(left + width, cx(u, t1));
  if (x1 <= x0) return;
  u.ctx.fillStyle = style;
  u.ctx.fillRect(x0, top, x1 - x0, height);
}
export function hatchSpan(u: uPlot, t0: number, t1: number, color: string) {
  const { left, top, width, height } = u.bbox;
  const x0 = Math.max(left, cx(u, t0)), x1 = Math.min(left + width, cx(u, t1));
  if (x1 <= x0) return;
  const ctx = u.ctx;
  ctx.save();
  ctx.beginPath(); ctx.rect(x0, top, x1 - x0, height); ctx.clip();
  ctx.strokeStyle = color; ctx.lineWidth = 1 * devicePixelRatio;
  const step = 8 * devicePixelRatio;
  for (let x = x0 - height; x < x1; x += step) { ctx.beginPath(); ctx.moveTo(x, top + height); ctx.lineTo(x + height, top); ctx.stroke(); }
  ctx.restore();
}
export function hline(u: uPlot, v: number, color: string, dash: number[] = [6, 6], scale = 'y', label?: string) {
  const { left, width, top, height } = u.bbox;
  const y = cy(u, v, scale);
  if (y < top || y > top + height) return;
  const ctx = u.ctx;
  ctx.save(); ctx.strokeStyle = color; ctx.lineWidth = 1.2 * devicePixelRatio; ctx.setLineDash(dash.map((d) => d * devicePixelRatio));
  ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(left + width, y); ctx.stroke();
  if (label) { ctx.setLineDash([]); ctx.fillStyle = color; ctx.font = `${11 * devicePixelRatio}px Inter, system-ui, sans-serif`; ctx.textAlign = 'right'; ctx.fillText(label, left + width - 4 * devicePixelRatio, y - 4 * devicePixelRatio); }
  ctx.restore();
}

/** Wheel zoom around the cursor + shift/horizontal wheel pans. Calls onRange with the new range. */
export function attachWheel(u: uPlot, getBounds: () => [number, number], onRange: (r: [number, number]) => void) {
  u.over.addEventListener('wheel', (e: WheelEvent) => {
    e.preventDefault();
    const [b0, b1] = getBounds();
    const min = u.scales.x.min!, max = u.scales.x.max!;
    const span = max - min;
    let n0: number, n1: number;
    if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
      const d = ((e.shiftKey ? e.deltaY : e.deltaX) / 500) * span;
      n0 = min + d; n1 = max + d;
    } else {
      const rect = u.over.getBoundingClientRect();
      const frac = (e.clientX - rect.left) / rect.width;
      const at = min + frac * span;
      const f = e.deltaY < 0 ? 0.8 : 1.25;
      const ns = Math.max(0.05, Math.min(b1 - b0, span * f));
      n0 = at - frac * ns; n1 = n0 + ns;
    }
    const w = n1 - n0;
    if (n0 < b0) { n0 = b0; n1 = b0 + w; }
    if (n1 > b1) { n1 = b1; n0 = b1 - w; }
    onRange([Math.max(b0, n0), Math.min(b1, n1)]);
  }, { passive: false });
}
