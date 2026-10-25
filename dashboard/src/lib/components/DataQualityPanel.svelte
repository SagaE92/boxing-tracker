<script lang="ts">
  import type { DataQuality } from '../stats';
  import { fmt, fmtTime, pct } from '../stats';
  import type { LoadedSession } from '../types';
  import { TIPS } from '../tips';
  import Tip from './Tip.svelte';
  import Bars from './Bars.svelte';
  let { dq, session }: { dq: DataQuality; session: LoadedSession } = $props();
  const cal = $derived(session.json?.session.calibration);
</script>

<section class="card" aria-label="Data quality">
  <div class="card-h"><h2>Data quality</h2><span class="sub">how much to trust this session</span></div>
  <div class="dq">
    <div class="item"><span class="k">Saturation <Tip text={TIPS.saturation} /></span><b class="num {dq.saturationLevel}">{pct(dq.satFraction, 3)}</b><span class="small muted">{dq.satSamples.toLocaleString()} samples · <span class={dq.clipLevel === 'ok' ? '' : dq.clipLevel}>{dq.saturatedStrikes} of {dq.strikes} strikes clipped</span></span></div>
    <div class="item"><span class="k">BLE gaps <Tip text={TIPS.dropped} /></span>
      {#if session.raw}<b class="num {dq.gaps.length ? 'warn' : 'ok'}">{dq.gaps.length} gap(s)</b><span class="small muted">~{dq.droppedEst.toLocaleString()} samples lost ({fmt(dq.droppedPct, 3)}%){dq.gaps.length ? ` · longest ${(dq.maxGapS * 1000).toFixed(0)} ms` : ''}</span>
      {:else}<b class="dim">n/a</b><span class="small muted">needs raw CSV</span>{/if}</div>
    <div class="item"><span class="k">Sample rate / jitter <Tip text={TIPS.jitter} /></span>
      {#if dq.measuredHz}<b class="num">{dq.measuredHz.toFixed(1)} Hz</b><span class="small muted">jitter {fmt(dq.jitterUs, 1)} µs · nominal {session.json?.session.sample_rate_hz ?? 416} Hz</span>
      {:else}<b class="dim">n/a</b>{/if}</div>
    <div class="item"><span class="k">Calibration <Tip text={TIPS.calibration} /></span>
      {#if cal}<b class="ok">Calibrated</b><span class="small muted">guard g = [{cal.guard_gravity_g.map((v) => v.toFixed(2)).join(', ')}] · {fmtTime(cal.t_start_s)}–{fmtTime(cal.t_end_s)}</span>
      {:else if session.json}<b class="warn">Missing</b><span class="small muted">type and target use default axes</span>{:else}<b class="dim">n/a</b>{/if}</div>
  </div>
  {#if dq.gaps.length}
    <details class="small"><summary class="muted">Gap list ({dq.gaps.length})</summary>
      <ul class="gaps num">{#each dq.gaps.slice(0, 50) as g (g.t)}<li>{fmtTime(g.t, true)} · {(g.dur * 1000).toFixed(0)} ms</li>{/each}</ul>
    </details>
  {/if}
  <div class="card-h" style="margin-top:.8rem"><h3>Confidence distribution (strikes) <Tip text={TIPS.confidence} /></h3><span class="sub">{dq.lowConfShare === null ? '' : `${Math.round(dq.lowConfShare * 100)}% below 0.5`}</span></div>
  <Bars data={dq.confHist.map((v, i) => ({ label: `${i * 10}`, value: v, color: i < 5 ? '#64748b' : i < 7 ? '#fbbf24' : '#34d399' }))} height={120} ariaLabel="Confidence histogram, 10% bins" />
</section>

<style>
  .dq { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 0.8rem; }
  .item { display: flex; flex-direction: column; gap: 0.15rem; padding: 0.6rem 0.7rem; border-radius: 10px; background: rgba(255,255,255,0.02); border: 1px solid var(--line); }
  .k { color: var(--muted); font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.05em; display: flex; gap: 0.3rem; align-items: center; }
  b { font-size: 1.15rem; }
  .ok { color: #86efac; } .warn { color: #fde68a; } .bad { color: #fca5a5; }
  .gaps { columns: 3 160px; margin: 0.4rem 0 0; }
</style>
