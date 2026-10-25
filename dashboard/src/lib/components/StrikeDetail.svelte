<script lang="ts">
  import uPlot from 'uplot';
  import { onDestroy, untrack } from 'svelte';
  import { AXIS, AXIS_COLORS, hline } from '../plot';
  import { lowerBound } from '../decimate';
  import { DURATION_TYPES, NON_STRIKE, typeColor, typeLabel, type EventType } from '../taxonomy';
  import { fmt, fmtTime } from '../stats';
  import type { LoadedSession, StrikeEvent } from '../types';
  import ConfBadge from './ConfBadge.svelte';
  import { TIPS } from '../tips';
  import Tip from './Tip.svelte';

  let { session, event, onclose, onprev, onnext }: { session: LoadedSession; event: StrikeEvent; onclose: () => void; onprev: () => void; onnext: () => void } = $props();
  let elA = $state<HTMLDivElement>(), elG = $state<HTMLDivElement>();
  let plots: uPlot[] = [];
  const win = $derived((session.json?.detector_params.window_ms ?? 150) / 1000);
  const range = $derived(session.json?.session.accel_range_g ?? 16);

  function build() {
    plots.forEach((p) => p.destroy()); plots = [];
    const raw = session.raw;
    if (!raw || !elA || !elG) return;
    const isDur = DURATION_TYPES.has(event.type);
    const a = isDur ? event.t_start_s - 0.5 : event.t_peak_s - win, b = isDur ? event.t_end_s + 0.5 : event.t_peak_s + win;
    const i0 = lowerBound(raw.t, a), i1 = lowerBound(raw.t, b);
    const step = Math.max(1, Math.floor((i1 - i0) / 1500));
    const x: number[] = [], m: number[] = [], ax: number[] = [], ay: number[] = [], az: number[] = [], gx: number[] = [], gy: number[] = [], gz: number[] = [], st: (number | null)[] = [];
    for (let i = i0; i < i1; i += step) {
      x.push(isDur ? raw.t[i] - event.t_start_s : (raw.t[i] - event.t_peak_s) * 1000);
      m.push(raw.amag[i]); ax.push(raw.ax[i]); ay.push(raw.ay[i]); az.push(raw.az[i]); gx.push(raw.gx[i]); gy.push(raw.gy[i]); gz.push(raw.gz[i]);
      st.push(raw.sat[i] ? raw.amag[i] : null);
    }
    const w = elA.clientWidth;
    const xAxis = { ...AXIS, values: (_u: uPlot, v: number[]) => v.map((q) => `${q.toFixed(0)}${isDur ? ' s' : ''}`), label: isDur ? 's from clinch start' : 'ms from peak', labelSize: 18, labelFont: AXIS.font };
    const common = (h: number): Partial<uPlot.Options> => ({ width: w, height: h, padding: [8, 8, 0, 0], legend: { live: true }, cursor: { sync: { key: `detail-${session.key}` }, drag: { x: false, y: false } } });
    plots.push(new uPlot({
      ...common(200), scales: { x: { time: false } },
      axes: [xAxis, { ...AXIS, size: 44, label: 'g', labelSize: 14, labelFont: AXIS.font }],
      series: [{ value: (_u, v) => (v == null ? '' : `${v.toFixed(isDur ? 2 : 1)}${isDur ? ' s' : ' ms'}`) },
        { label: '|a|−1', stroke: AXIS_COLORS.mag, width: 2, points: { show: false } },
        { label: 'ax', stroke: AXIS_COLORS.x, width: 1, points: { show: false } },
        { label: 'ay', stroke: AXIS_COLORS.y, width: 1, points: { show: false } },
        { label: 'az', stroke: AXIS_COLORS.z, width: 1, points: { show: false } },
        { label: 'clipped', stroke: '#fbbf24', width: 0, points: { show: true, size: 7, fill: '#fbbf24', stroke: '#fbbf24' } }],
      hooks: { draw: [(u) => { hline(u, range, 'rgba(251,191,36,.6)', [2, 4], 'y', `${range} g`); hline(u, -range, 'rgba(251,191,36,.6)', [2, 4]); }] },
    } as uPlot.Options, [x, m, ax, ay, az, st] as uPlot.AlignedData, elA));
    plots.push(new uPlot({
      ...common(170), scales: { x: { time: false } },
      axes: [xAxis, { ...AXIS, size: 44, label: '°/s', labelSize: 14, labelFont: AXIS.font }],
      series: [{}, { label: 'ωx', stroke: AXIS_COLORS.x, width: 1.4, points: { show: false } }, { label: 'ωy', stroke: AXIS_COLORS.y, width: 1.4, points: { show: false } }, { label: 'ωz', stroke: AXIS_COLORS.z, width: 1.4, points: { show: false } }],
    } as uPlot.Options, [x, gx, gy, gz] as uPlot.AlignedData, elG));
  }
  $effect(() => { void event; void session; void elA; void elG; untrack(build); });
  onDestroy(() => plots.forEach((p) => p.destroy()));
  const nonStrike = $derived(NON_STRIKE.has(event.type as EventType));
</script>

<section class="card detail" aria-label="Strike detail">
  <div class="card-h">
    <h2 style="display:flex;gap:.5rem;align-items:center"><span class="dot" style="background:{typeColor(event.type)};width:12px;height:12px"></span>{typeLabel(event.type)} <span class="muted num" style="font-weight:400">#{event.id} · {fmtTime(event.t_peak_s, true)}</span></h2>
    <div style="display:flex;gap:.3rem">
      <button class="btn sm" onclick={onprev} aria-label="Previous strike">← Prev</button>
      <button class="btn sm" onclick={onnext} aria-label="Next strike">Next →</button>
      <button class="btn sm ghost" onclick={onclose} aria-label="Close detail">✕</button>
    </div>
  </div>
  <div class="facts">
    <div><span class="k">Confidence <Tip text={TIPS.confidence} /></span><ConfBadge value={event.confidence} /></div>
    <div><span class="k">Peak g <Tip text={TIPS.maxPeak} /></span><b class="num">{event.saturated ? '≥ ' : ''}{fmt(event.peak_g, 2)} g</b></div>
    <div><span class="k">Speed (est.) <Tip text={TIPS.speed} /></span><b class="num">{event.speed_mps_est === null ? '—' : `~${fmt(event.speed_mps_est, 1)} m/s`}</b></div>
    <div><span class="k">Duration</span><b class="num">{fmt(event.duration_ms, 0)} ms</b></div>
    <div><span class="k">Hand / target</span><b>{event.hand ?? '—'} · {event.target ?? '—'}</b></div>
    <div><span class="k">Rotation ∫ω (x,y,z)</span><b class="num">{event.gyro_int_dps_s.map((v) => v.toFixed(0)).join(', ')}°</b></div>
  </div>
  {#if event.saturated}<div class="alert warn" style="margin-bottom:.6rem"><span class="ico">!</span><span>This strike clipped at ±{range} g on at least one axis, so its peak g is a lower bound: the real peak was at least this.</span></div>{/if}
  {#if nonStrike}<div class="alert info" style="margin-bottom:.6rem"><span class="ico">i</span><span>{TIPS.nonStrike}</span></div>{/if}
  {#if session.raw}
    <div bind:this={elA}></div>
    <div bind:this={elG}></div>
  {:else}
    <p class="muted small">Load the raw CSV for this session to see the ±{Math.round(win * 1000)} ms waveform.</p>
  {/if}
</section>

<style>
  .facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.6rem 1rem; margin-bottom: 0.8rem; }
  .facts > div { display: flex; flex-direction: column; gap: 0.15rem; }
  .k { color: var(--muted); font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.05em; display: flex; gap: 0.3rem; align-items: center; }
</style>
