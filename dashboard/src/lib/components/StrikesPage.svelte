<script lang="ts">
  import { app } from '../state.svelte';
  import { applyFilters, filtersActive } from '../stats';
  import { download, eventsCsv } from '../exporters';
  import FilterBar from './FilterBar.svelte';
  import StrikeTable from './StrikeTable.svelte';
  import StrikeDetail from './StrikeDetail.svelte';
  import Timeline from './Timeline.svelte';

  const s = $derived(app.active!);
  const j = $derived(s.json!);
  const all = $derived(j.punches);
  const filtered = $derived(applyFilters(all, app.filters));
  const present = $derived(Object.fromEntries(all.reduce((m, e) => m.set(e.type, (m.get(e.type) ?? 0) + 1), new Map<string, number>())));
  const roundIdx = $derived(j.rounds.filter((r) => r.kind === 'round').map((r) => r.index));
  const selected = $derived(all.find((e) => e.id === app.selectedId) ?? null);
  const roundNumber = (idx: number | null) => { const k = roundIdx.indexOf(idx ?? -1); return k >= 0 ? `R${k + 1}` : '—'; };
  function step(d: number) {
    const i = filtered.findIndex((e) => e.id === app.selectedId);
    const n = filtered[Math.max(0, Math.min(filtered.length - 1, i + d))];
    if (n) app.selectStrike(n.id);
  }
</script>

<FilterBar bind:filters={app.filters} {present} {roundIdx} duration={j.session.duration_s} />
<section class="card">
  <div class="card-h"><h2>Timeline <span class="sub">({filtered.length} shown)</span></h2></div>
  <Timeline session={s} events={filtered} labels={s.labels ?? []} comboGapMs={app.comboGapMs} selectedId={app.selectedId} range={app.range} height={170}
    onselect={(id) => app.selectStrike(id)} onrange={(r) => { app.range = r; if (r) { app.filters.tMin = Math.floor(r[0]); app.filters.tMax = Math.ceil(r[1]); } }} />
</section>
<div class="layout" class:withdetail={!!selected}>
  <section class="card">
    <div class="card-h">
      <h2>Events <span class="sub">{filtered.length}{filtersActive(app.filters) ? ` of ${all.length}` : ''}</span></h2>
      <button class="btn sm" onclick={() => download(`${j.session.id}_events${filtersActive(app.filters) ? '_filtered' : ''}.csv`, eventsCsv(filtered))}>⤓ Export CSV</button>
    </div>
    <StrikeTable events={filtered} selectedId={app.selectedId} onselect={(id) => app.selectStrike(id)} {roundNumber} />
  </section>
  {#if selected}
    <div class="side"><StrikeDetail session={s} event={selected} onclose={() => (app.selectedId = null)} onprev={() => step(-1)} onnext={() => step(1)} /></div>
  {/if}
</div>

<style>
  .layout { display: grid; gap: 0.9rem; grid-template-columns: 1fr; }
  @media (min-width: 1200px) { .layout.withdetail { grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); } .side { position: sticky; top: 76px; align-self: start; } }
</style>
