<script lang="ts">
  import uPlot from 'uplot';
  import 'uplot/dist/uPlot.min.css';
  import { onDestroy, onMount, untrack } from 'svelte';
  import { AXIS, AXIS_COLORS, attachWheel, cx, fillSpan, hline, xTime } from '../plot';
  import { decimate, satRuns } from '../decimate';
  import { DURATION_TYPES, typeColor } from '../taxonomy';
  import type { LabelRow, LoadedSession, StrikeEvent } from '../types';
  import { fmtTime } from '../stats';

  let { session, events, labels = [], selectedId = null, range = null, onrange, onselect }: {
    session: LoadedSession; events: StrikeEvent[]; labels?: LabelRow[]; selectedId?: number | null;
    range?: [number, number] | null; onrange: (r: [number, number] | null) => void; onselect: (id: number) => void;
  } = $props();

  const raw = $derived(session.raw!);
  const t0 = $derived(raw.t[0]);
  const t1 = $derived(raw.t[raw.n - 1]);
  const fs = $derived(session.json?.session.sample_rate_hz ?? 416);
  const accelRange = $derived(session.json?.session.accel_range_g ?? 16);
  const gyroRange = $derived(session.json?.session.gyro_range_dps ?? 2000);
  const thr = $derived(session.json?.detector_params.threshold_g ?? null);

  let elMag: HTMLDivElement, elAcc: HTMLDivElement, elGyr: HTMLDivElement, wrap: HTMLDivElement;
  let plots: uPlot[] = [];
  let sats: [number, number][] = [];
  let cur = { events: [] as StrikeEvent[], labels: [] as LabelRow[], sel: null as number | null };
  let lastMs = $state<number | null>(null);
  let visiblePts = $state(0);

  function bounds(): [number, number] { return [t0, t1]; }

  function overlays(kind: 'mag' | 'acc' | 'gyr') {
    return (u: uPlot) => {
      for (const [a, b] of sats) fillSpan(u, a - 0.5 / fs, b + 0.5 / fs, 'rgba(251,191,36,0.22)');
      for (const e of cur.events) {
        if (DURATION_TYPES.has(e.type)) { fillSpan(u, e.t_start_s, e.t_end_s, 'rgba(124,141,181,0.14)'); continue; }
        if (e.t_peak_s < u.scales.x.min! || e.t_peak_s > u.scales.x.max!) continue;
        const ctx = u.ctx, dpr = devicePixelRatio, x = cx(u, e.t_peak_s), { top, height } = u.bbox;
        const sel = e.id === cur.sel;
        if (sel) fillSpan(u, e.t_start_s, e.t_end_s, 'rgba(255,255,255,0.06)');
        ctx.save(); ctx.strokeStyle = typeColor(e.type); ctx.globalAlpha = sel ? 0.95 : 0.45; ctx.lineWidth = (sel ? 2 : 1) * dpr;
        ctx.setLineDash(sel ? [] : [3 * dpr, 3 * dpr]);
        ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + height); ctx.stroke(); ctx.restore();
        if (kind === 'mag') { ctx.fillStyle = typeColor(e.type); ctx.beginPath(); ctx.arc(x, top + 6 * dpr, (sel ? 5 : 3.5) * dpr, 0, 7); ctx.fill(); }
      }
      if (kind === 'mag') {
        if (thr !== null) hline(u, thr, 'rgba(255,176,32,0.8)', [6, 5], 'y', `threshold ${thr} g`);
        const ctx = u.ctx, dpr = devicePixelRatio, { top, height } = u.bbox;
        ctx.fillStyle = 'rgba(232,237,246,0.7)';
        for (const l of cur.labels) {
          if (l.t < u.scales.x.min! || l.t > u.scales.x.max!) continue;
          const x = cx(u, l.t);
          ctx.beginPath(); ctx.moveTo(x, top + height); ctx.lineTo(x - 4 * dpr, top + height - 8 * dpr); ctx.lineTo(x + 4 * dpr, top + height - 8 * dpr); ctx.fill();
          if (u.scales.x.max! - u.scales.x.min! < 20) { ctx.font = `${10 * dpr}px Inter, system-ui`; ctx.textAlign = 'center'; ctx.fillText(l.rawLabel, x, top + height - 11 * dpr); }
        }
      }
      if (kind === 'acc') { hline(u, accelRange, 'rgba(251,191,36,0.6)', [2, 4], 'y', `+${accelRange} g clip`); hline(u, -accelRange, 'rgba(251,191,36,0.6)', [2, 4], 'y'); }
      if (kind === 'gyr') { hline(u, gyroRange, 'rgba(251,191,36,0.6)', [2, 4]); hline(u, -gyroRange, 'rgba(251,191,36,0.6)', [2, 4]); }
    };
  }

  function mk(el: HTMLDivElement, kind: 'mag' | 'acc' | 'gyr', h: number): uPlot {
    const series: uPlot.Series[] = [{ label: 't', value: (_u, v) => (v == null ? '' : fmtTime(v, true)) }];
    if (kind === 'mag') series.push({ label: '|a| − 1 g', stroke: AXIS_COLORS.mag, width: 1.25, points: { show: false }, value: (_u, v) => (v == null ? '' : `${v.toFixed(2)} g`) });
    else {
      const unit = kind === 'acc' ? 'g' : '°/s';
      for (const a of ['x', 'y', 'z'] as const) series.push({ label: `${kind === 'acc' ? 'a' : 'ω'}${a}`, stroke: AXIS_COLORS[a], width: 1, points: { show: false }, value: (_u, v) => (v == null ? '' : `${v.toFixed(kind === 'acc' ? 2 : 0)} ${unit}`) });
    }
    const opts: uPlot.Options = {
      width: el.clientWidth, height: h, padding: [8, 10, 0, 0],
      scales: { x: { time: false }, y: kind === 'mag' ? { range: (_u, _min, max) => [-0.5, Math.max((thr ?? 3) + 1, max * 1.08)] } : {} },
      cursor: { sync: { key: 'raw-' + session.key, setSeries: false }, drag: { x: true, y: false, setScale: false }, points: { size: 5 } },
      legend: { live: true },
      axes: [
        { ...AXIS, values: xTime(false), space: 80, show: kind === 'gyr' },
        { ...AXIS, size: 52, label: kind === 'mag' ? '|a|−1 g' : kind === 'acc' ? 'accel g' : 'gyro °/s', labelSize: 16, labelFont: AXIS.font },
      ],
      series,
      hooks: {
        draw: [overlays(kind)],
        setSelect: [(u) => {
          if (u.select.width > 4) onrange([u.posToVal(u.select.left, 'x'), u.posToVal(u.select.left + u.select.width, 'x')]);
          u.setSelect({ left: 0, width: 0, top: 0, height: 0 }, false);
        }],
      },
    };
    const u = new uPlot(opts, [[t0, t1], ...series.slice(1).map(() => [null, null])] as uPlot.AlignedData, el);
    attachWheel(u, bounds, (r) => onrange(r));
    u.over.addEventListener('dblclick', () => onrange(null));
    let down: [number, number] | null = null;
    u.over.addEventListener('mousedown', (e) => (down = [e.clientX, e.clientY]));
    u.over.addEventListener('click', (e) => {
      if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
      const x = u.posToVal(u.cursor.left ?? -1, 'x');
      const span = u.scales.x.max! - u.scales.x.min!;
      let best: StrikeEvent | null = null, bd = (span / u.bbox.width) * devicePixelRatio * 10;
      for (const ev of cur.events) { const d = Math.abs(ev.t_peak_s - x); if (d < bd) { bd = d; best = ev; } }
      if (best) onselect(best.id);
    });
    return u;
  }

  function setRange(r: [number, number] | null) {
    if (!plots.length) return;
    const start = performance.now();
    const [a, b] = r ?? [t0, t1];
    const px = Math.max(200, plots[0].bbox.width / devicePixelRatio);
    const gap = 3 / fs;
    const mag = decimate(raw.t, [raw.amag], a, b, px, gap);
    const acc = decimate(raw.t, [raw.ax, raw.ay, raw.az], a, b, px, gap);
    const gyr = decimate(raw.t, [raw.gx, raw.gy, raw.gz], a, b, px, gap);
    visiblePts = mag.x.length;
    const sets = [mag, acc, gyr];
    plots.forEach((u, i) => u.batch(() => { u.setData([sets[i].x, ...sets[i].ys] as uPlot.AlignedData, false); u.setScale('x', { min: a, max: b }); }));
    lastMs = performance.now() - start;
    // exposed for the perf e2e test
    const w = window as unknown as { __lastRangeMs?: number; __rangeCalls?: number };
    w.__lastRangeMs = lastMs;
    w.__rangeCalls = (w.__rangeCalls ?? 0) + 1;
  }

  function build() {
    plots.forEach((p) => p.destroy());
    sats = satRuns(raw);
    plots = [mk(elMag, 'mag', 210), mk(elAcc, 'acc', 170), mk(elGyr, 'gyr', 190)];
    untrack(() => setRange(range));
  }

  $effect(() => { void session; if (elMag) untrack(build); });
  // Only `range`/`raw` may re-trigger this: uPlot draw hooks read deriveds, so run untracked.
  $effect(() => { const r = range; void raw; untrack(() => setRange(r)); });
  $effect(() => { cur = { events, labels, sel: selectedId }; untrack(() => plots.forEach((p) => p.redraw(false))); });

  function zoom(f: number) {
    const [a, b] = range ?? [t0, t1];
    const c = (a + b) / 2, h = Math.min((t1 - t0) / 2, ((b - a) / 2) * f);
    let n0 = c - h, n1 = c + h;
    if (n0 < t0) { n1 += t0 - n0; n0 = t0; } if (n1 > t1) { n0 -= n1 - t1; n1 = t1; }
    onrange(f >= 1 && n1 - n0 >= t1 - t0 - 1e-6 ? null : [Math.max(t0, n0), Math.min(t1, n1)]);
  }
  function pan(dir: number) {
    const [a, b] = range ?? [t0, t1];
    const w = b - a, d = dir * w * 0.5;
    let n0 = a + d, n1 = b + d;
    if (n0 < t0) { n0 = t0; n1 = t0 + w; } if (n1 > t1) { n1 = t1; n0 = t1 - w; }
    onrange([n0, n1]);
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === 'ArrowLeft') { pan(-1); e.preventDefault(); } else if (e.key === 'ArrowRight') { pan(1); e.preventDefault(); }
    else if (e.key === '+' || e.key === '=') zoom(0.5); else if (e.key === '-') zoom(2); else if (e.key === '0' || e.key === 'Escape') onrange(null);
  }
  let ro: ResizeObserver;
  onMount(() => {
    ro = new ResizeObserver(() => {
      const w = wrap?.clientWidth;
      if (!w || !plots.length || Math.abs(plots[0].width - w) < 3) return;
      plots.forEach((p) => p.setSize({ width: w, height: p.height }));
      setRange(range);
    });
    ro.observe(wrap);
  });
  onDestroy(() => { ro?.disconnect(); plots.forEach((p) => p.destroy()); });
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div class="sig" bind:this={wrap} tabindex="0" role="application" aria-label="Raw signal charts. Arrow keys pan, plus and minus zoom, 0 resets." onkeydown={onKey}>
  <div class="bar">
    <div class="btns">
      <button class="btn sm" onclick={() => pan(-1)} aria-label="Pan left">◀</button>
      <button class="btn sm" onclick={() => zoom(0.5)} aria-label="Zoom in">＋</button>
      <button class="btn sm" onclick={() => zoom(2)} aria-label="Zoom out">－</button>
      <button class="btn sm" onclick={() => pan(1)} aria-label="Pan right">▶</button>
      <button class="btn sm ghost" onclick={() => onrange(null)}>Reset</button>
    </div>
    <div class="hint small dim">Drag to zoom · wheel zooms, Shift+wheel pans · double-click resets · click a marker to inspect
      {#if lastMs !== null}<span class="num"> · {visiblePts.toLocaleString()} pts drawn ({raw.n.toLocaleString()} samples) in {lastMs.toFixed(0)} ms</span>{/if}
    </div>
  </div>
  <div class="legend-key small">
    <span><i class="sw sat"></i>saturated (clipped) samples</span>
    <span><i class="sw thr"></i>detection threshold</span>
    <span><i class="sw lab"></i>label (video)</span>
    <span><i class="sw cl"></i>clinch</span>
  </div>
  <div bind:this={elMag}></div>
  <div bind:this={elAcc}></div>
  <div bind:this={elGyr}></div>
</div>

<style>
  .sig { width: 100%; outline: none; }
  .sig:focus-visible { outline: 2px solid var(--accent2); outline-offset: 4px; border-radius: 8px; }
  .bar { display: flex; gap: 0.8rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.4rem; }
  .btns { display: flex; gap: 0.3rem; }
  .legend-key { display: flex; gap: 1rem; flex-wrap: wrap; color: var(--muted); margin: 0.2rem 0 0.4rem; }
  .sw { display: inline-block; width: 14px; height: 10px; margin-right: 0.35rem; vertical-align: middle; border-radius: 2px; }
  .sw.sat { background: rgba(251, 191, 36, 0.45); }
  .sw.thr { height: 0; border-top: 2px dashed rgba(255, 176, 32, 0.9); }
  .sw.lab { width: 0; height: 0; border-left: 5px solid transparent; border-right: 5px solid transparent; border-bottom: 8px solid rgba(232, 237, 246, 0.7); border-radius: 0; }
  .sw.cl { background: rgba(124, 141, 181, 0.4); }
</style>
