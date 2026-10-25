<script lang="ts">
  import { app } from '../state.svelte';
  import { applyFilters, fmtTime } from '../stats';
  import Signals from './Signals.svelte';
  import Timeline from './Timeline.svelte';
  import StrikeDetail from './StrikeDetail.svelte';
  const s = $derived(app.active!);
  const events = $derived(s.json ? applyFilters(s.json.punches, { ...app.filters, includeNonStrike: true }) : []);
  const selected = $derived(s.json?.punches.find((e) => e.id === app.selectedId) ?? null);
  function step(d: number) {
    const i = events.findIndex((e) => e.id === app.selectedId);
    const n = events[Math.max(0, Math.min(events.length - 1, i + d))];
    if (n) app.selectStrike(n.id);
  }
</script>

{#if !s.raw}
  <div class="card"><h2>No raw data</h2><p class="muted">Drop this session's raw CSV (<span class="mono">host_time_s,device_time_us,ax_g,…,sat</span>) to see the 416 Hz waveforms. Session JSON alone has strike metrics only.</p></div>
{:else}
  <section class="card">
    <div class="card-h"><h2>Overview</h2><span class="sub">drag here to choose the window below{app.range ? ` · showing ${fmtTime(app.range[0], true)}–${fmtTime(app.range[1], true)}` : ' · full session'}</span></div>
    <Timeline session={s} {events} labels={s.labels ?? []} comboGapMs={app.comboGapMs} selectedId={app.selectedId} range={app.range} height={130}
      onselect={(id) => app.selectStrike(id)} onrange={(r) => (app.range = r)} />
  </section>
  <section class="card">
    <div class="card-h"><h2>Raw signals</h2><span class="sub">{s.raw.n.toLocaleString()} samples · min/max decimated to screen width</span></div>
    <Signals session={s} {events} labels={s.labels ?? []} selectedId={app.selectedId} range={app.range} onrange={(r) => (app.range = r)} onselect={(id) => app.selectStrike(id)} />
  </section>
  {#if selected}<StrikeDetail session={s} event={selected} onclose={() => (app.selectedId = null)} onprev={() => step(-1)} onnext={() => step(1)} />{/if}
{/if}
