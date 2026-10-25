<script lang="ts">
  import uPlot from 'uplot';
  import 'uplot/dist/uPlot.min.css';
  import { onDestroy, onMount, untrack } from 'svelte';
  import { AXIS, cx, cy, fillSpan, hatchSpan, hline, xTime } from '../plot';
  import { envelope } from '../decimate';
  import { DURATION_TYPES, isStrike, typeColor, typeLabel } from '../taxonomy';
  import { combos, fmt, fmtTime } from '../stats';
  import type { LabelRow, LoadedSession, StrikeEvent } from '../types';

  let { session, events, labels = [], comboGapMs = 600, selectedId = null, range = null, onselect, onrange, height = 230 }: {
    session: LoadedSession; events: StrikeEvent[]; labels?: LabelRow[]; comboGapMs?: number; selectedId?: number | null;
    range?: [number, number] | null; onselect: (id: number) => void; onrange: (r: [number, number] | null) => void; height?: number;
  } = $props();

  let el = $state<HTMLDivElement>() as HTMLDivElement;
  let u: uPlot | null = null;
  let hover = $state<{ x: number; y: number; e: StrikeEvent } | null>(null);
  // Plain mirrors read by canvas hooks.
  let cur = { events: [] as StrikeEvent[], labels: [] as LabelRow[], combos: [] as StrikeEvent[][], sel: null as number | null, range: null as [number, number] | null };

  const duration = $derived(session.json?.session.duration_s ?? (session.raw ? session.raw.t[session.raw.n - 1] : 1));
  const ymax = $derived(Math.max(8, ...events.map((e) => e.peak_g)) * 1.12);

  function build() {
    if (u) { u.destroy(); u = null; }
    const raw = session.raw;
    const env = raw ? envelope(raw, Math.min(2400, Math.max(400, el.clientWidth * 2))) : { x: [0, duration], y: [null, null] as unknown as number[] };
    const thr = session.json?.detector_params.threshold_g ?? 3.5;
    const opts: uPlot.Options = {
      width: el.clientWidth, height,
      padding: [12, 10, 0, 2],
      scales: { x: { time: false, range: [0, duration] }, y: { range: () => [0, ymax] } },
      legend: { show: false },
      cursor: { drag: { x: true, y: false, setScale: false }, points: { show: false }, y: false },
      axes: [
        { ...AXIS, values: xTime(false), space: 70 },
        { ...AXIS, label: 'peak g', labelSize: 16, labelFont: AXIS.font, size: 46, values: (_u, v) => v.map((x) => x.toFixed(0)) },
      ],
      series: [{}, { stroke: 'rgba(148,163,184,0.38)', width: 1, fill: 'rgba(148,163,184,0.06)', points: { show: false } }],
      hooks: {
        drawClear: [(u) => {
          for (const r of session.json?.rounds ?? []) {
            if (r.kind === 'round') fillSpan(u, r.t_start_s, r.t_end_s, 'rgba(255,90,54,0.045)');
            else hatchSpan(u, r.t_start_s, r.t_end_s, 'rgba(148,163,184,0.10)');
          }
          for (const e of cur.events) if (DURATION_TYPES.has(e.type)) { fillSpan(u, e.t_start_s, e.t_end_s, 'rgba(124,141,181,0.22)'); }
          if (cur.range) fillSpan(u, cur.range[0], cur.range[1], 'rgba(255,176,32,0.10)');
        }],
        draw: [(u) => {
          const ctx = u.ctx, dpr = devicePixelRatio;
          hline(u, thr, 'rgba(255,176,32,0.65)', [5, 5], 'y', `threshold ${thr} g`);
          const { top, height: h, left, width } = u.bbox;
          // round labels
          ctx.save(); ctx.font = `${600} ${10.5 * dpr}px Inter, system-ui, sans-serif`; ctx.fillStyle = 'rgba(232,237,246,0.55)'; ctx.textAlign = 'left';
          let rn = 0;
          for (const r of session.json?.rounds ?? []) {
            const x = cx(u, r.t_start_s) + 5 * dpr;
            if (r.kind === 'round') { rn++; if (x < left + width - 20) ctx.fillText(`R${rn}`, x, top + 12 * dpr); }
            else if (cx(u, r.t_end_s) - cx(u, r.t_start_s) > 40 * dpr) { ctx.fillStyle = 'rgba(148,163,184,0.6)'; ctx.fillText('rest', x, top + 12 * dpr); ctx.fillStyle = 'rgba(232,237,246,0.55)'; }
          }
          ctx.restore();
          // combo connectors
          ctx.save(); ctx.lineWidth = 1.5 * dpr; ctx.strokeStyle = 'rgba(232,237,246,0.28)';
          for (const c of cur.combos) {
            ctx.beginPath();
            c.forEach((e, i) => { const x = cx(u, e.t_peak_s), y = cy(u, e.peak_g); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
            ctx.stroke();
          }
          ctx.restore();
          // markers
          for (const e of cur.events) {
            if (DURATION_TYPES.has(e.type)) continue;
            const x = cx(u, e.t_peak_s), y = cy(u, Math.min(e.peak_g, ymax));
            if (x < left - 4 || x > left + width + 4) continue;
            const r = (e.id === cur.sel ? 6.5 : isStrike(e.type) ? 4 : 3.4) * dpr;
            ctx.beginPath();
            if (!isStrike(e.type)) { ctx.rect(x - r, y - r, 2 * r, 2 * r); } else ctx.arc(x, y, r, 0, Math.PI * 2);
            ctx.fillStyle = typeColor(e.type); ctx.globalAlpha = isStrike(e.type) ? 0.35 + 0.65 * Math.max(0.3, e.confidence) : 0.55; ctx.fill(); ctx.globalAlpha = 1;
            if (e.saturated) { ctx.lineWidth = 2 * dpr; ctx.strokeStyle = '#f87171'; ctx.stroke(); }
            if (e.id === cur.sel) { ctx.lineWidth = 2.5 * dpr; ctx.strokeStyle = '#fff'; ctx.stroke(); }
          }
          // label ticks along the bottom
          ctx.save(); ctx.fillStyle = 'rgba(232,237,246,0.55)';
          for (const l of cur.labels) {
            const x = cx(u, l.t);
            if (x < left || x > left + width) continue;
            ctx.fillRect(x, top + h - 7 * dpr, 1 * dpr, 7 * dpr);
          }
          ctx.restore();
          // density strip: strikes per 10 s along the very bottom
          const bin = 10, nb = Math.ceil(duration / bin), counts = new Array(nb).fill(0);
          for (const e of cur.events) if (isStrike(e.type)) counts[Math.min(nb - 1, Math.floor(e.t_peak_s / bin))]++;
          const cmax = Math.max(1, ...counts);
          for (let i = 0; i < nb; i++) {
            if (!counts[i]) continue;
            const x0 = cx(u, i * bin), x1 = cx(u, (i + 1) * bin);
            ctx.fillStyle = `rgba(255,90,54,${0.15 + 0.75 * (counts[i] / cmax)})`;
            ctx.fillRect(x0, top + h + 1 * dpr, Math.max(1, x1 - x0 - 1), 5 * dpr);
          }
        }],
        setSelect: [(u) => {
          if (u.select.width > 4) {
            const a = u.posToVal(u.select.left, 'x'), b = u.posToVal(u.select.left + u.select.width, 'x');
            onrange([Math.max(0, a), Math.min(duration, b)]);
          }
          u.setSelect({ left: 0, width: 0, top: 0, height: 0 }, false);
        }],
        setCursor: [(u) => {
          const { left, top } = u.cursor;
          if (left === undefined || left < 0) { hover = null; return; }
          const dpr = devicePixelRatio;
          let best: StrikeEvent | null = null, bd = 12;
          for (const e of cur.events) {
            const dx = Math.abs(u.valToPos(e.t_peak_s, 'x') - left);
            const dy = DURATION_TYPES.has(e.type) ? 0 : Math.abs(u.valToPos(Math.min(e.peak_g, ymax), 'y') - (top ?? 0));
            const d = Math.hypot(dx, dy * 0.6);
            if (d < bd) { bd = d; best = e; }
          }
          void dpr;
          hover = best ? { x: left, y: top ?? 0, e: best } : null;
        }],
      },
    };
    u = new uPlot(opts, [env.x, env.y], el);
    let down: [number, number] | null = null;
    u.over.addEventListener('mousedown', (e) => (down = [e.clientX, e.clientY]));
    u.over.addEventListener('click', (e) => {
      if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
      if (hover) onselect(hover.e.id);
    });
    u.over.addEventListener('dblclick', () => onrange(null));
    u.over.style.cursor = 'crosshair';
  }

  $effect(() => {
    cur = {
      events, labels, sel: selectedId, range,
      combos: combos(events, comboGapMs).filter((c) => c.events.length > 1).map((c) => c.events),
    };
    untrack(() => u?.redraw(false));
  });
  $effect(() => {
    void session; void ymax; void height;
    if (el) untrack(build);
  });
  let ro: ResizeObserver;
  onMount(() => {
    ro = new ResizeObserver(() => { if (u && el.clientWidth && Math.abs(u.width - el.clientWidth) > 2) u.setSize({ width: el.clientWidth, height }); });
    ro.observe(el);
  });
  onDestroy(() => { ro?.disconnect(); u?.destroy(); });
</script>

<div class="tl">
  <div bind:this={el} class="plot" role="img" aria-label="Strike timeline: peak g of each strike over the session, coloured by type, with rounds shaded"></div>
  {#if hover}
    <div class="hov" style="left:{Math.min(hover.x + 14, (el?.clientWidth ?? 300) - 200)}px; top:{Math.max(0, hover.y - 10)}px">
      <div class="h1"><span class="dot" style="background:{typeColor(hover.e.type)}"></span>{typeLabel(hover.e.type)}</div>
      <div class="num">{fmtTime(hover.e.t_peak_s, true)} · {DURATION_TYPES.has(hover.e.type) ? `${((hover.e.t_end_s - hover.e.t_start_s)).toFixed(1)} s` : `${hover.e.saturated ? '≥' : ''}${fmt(hover.e.peak_g, 1)} g`}{hover.e.speed_mps_est !== null ? ` · ~${fmt(hover.e.speed_mps_est, 1)} m/s` : ''}</div>
      <div class="dim">confidence {Math.round(hover.e.confidence * 100)}%{hover.e.saturated ? ' · clipped' : ''} · click to inspect</div>
    </div>
  {/if}
</div>

<style>
  .tl { position: relative; width: 100%; }
  .plot { width: 100%; min-height: 120px; }
  .hov { position: absolute; pointer-events: none; z-index: 5; background: #0a0f19ee; border: 1px solid var(--line2); border-radius: 10px; padding: 0.45rem 0.6rem; font-size: 0.78rem; min-width: 170px; box-shadow: 0 8px 24px rgba(0,0,0,.5); }
  .h1 { display: flex; gap: 0.4rem; align-items: center; font-weight: 600; }
</style>
