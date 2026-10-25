<script lang="ts">
  import { TYPES, typeColor, typeLabel, NON_STRIKE } from '../taxonomy';
  import { defaultFilters, filtersActive, type Filters } from '../stats';
  import Tip from './Tip.svelte';
  import { TIPS } from '../tips';
  let { filters = $bindable(), present, roundIdx, duration }: { filters: Filters; present: Record<string, number>; roundIdx: number[]; duration: number } = $props();
  function toggle(t: string) {
    filters.types = filters.types.includes(t) ? filters.types.filter((x) => x !== t) : [...filters.types, t];
  }
</script>

<div class="fb card" aria-label="Filters">
  <div class="row chips" role="group" aria-label="Filter by type">
    {#each TYPES.filter((t) => present[t]) as t (t)}
      <button class="chip" aria-pressed={filters.types.includes(t)} onclick={() => toggle(t)}>
        <span class="dot" style="background:{typeColor(t)}"></span>{typeLabel(t)} <span class="num dim">{present[t]}</span>{#if NON_STRIKE.has(t)}<span class="badge low">low conf.</span>{/if}
      </button>
    {/each}
  </div>
  <div class="row ctrls">
    <label class="field">Min confidence <span class="num">{Math.round(filters.minConfidence * 100)}%</span>
      <input type="range" min="0" max="1" step="0.05" bind:value={filters.minConfidence} aria-label="Minimum confidence" /></label>
    <label class="field">Min peak g <span class="num">{filters.minPeakG.toFixed(1)} g</span>
      <input type="range" min="0" max="16" step="0.5" bind:value={filters.minPeakG} aria-label="Minimum peak g" /></label>
    <label class="field">Hand
      <select bind:value={filters.hand}><option value="all">Both</option><option value="L">Left</option><option value="R">Right</option></select></label>
    <label class="field">Target
      <select bind:value={filters.target}><option value="all">All</option><option value="head">Head</option><option value="body">Body</option></select></label>
    <label class="field">Round
      <select bind:value={filters.round}>
        <option value="all">All</option>
        {#each roundIdx as ri, i (ri)}<option value={ri}>Round {i + 1}</option>{/each}
      </select></label>
    <label class="field">From (s)<input type="number" min="0" max={duration} step="1" style="width:5.5rem" value={filters.tMin ?? ''} oninput={(e) => (filters.tMin = (e.currentTarget as HTMLInputElement).value === '' ? null : +(e.currentTarget as HTMLInputElement).value)} /></label>
    <label class="field">To (s)<input type="number" min="0" max={duration} step="1" style="width:5.5rem" value={filters.tMax ?? ''} oninput={(e) => (filters.tMax = (e.currentTarget as HTMLInputElement).value === '' ? null : +(e.currentTarget as HTMLInputElement).value)} /></label>
    <label class="check"><input type="checkbox" bind:checked={filters.saturatedOnly} /> Clipped only</label>
    <label class="check"><input type="checkbox" bind:checked={filters.includeNonStrike} /> Include kick/clinch in totals <Tip text={TIPS.nonStrike} /></label>
    {#if filtersActive(filters) || filters.includeNonStrike}<button class="btn sm ghost" onclick={() => (filters = defaultFilters())}>Clear filters</button>{/if}
  </div>
</div>

<style>
  .fb { display: flex; flex-direction: column; gap: 0.7rem; padding: 0.8rem 1rem; }
  .row { display: flex; flex-wrap: wrap; gap: 0.45rem 0.9rem; align-items: flex-end; }
  .chips { gap: 0.4rem; }
  .check { display: flex; gap: 0.35rem; align-items: center; font-size: 0.82rem; color: var(--muted); padding-bottom: 0.35rem; }
  .field input[type='range'] { width: 130px; }
</style>
