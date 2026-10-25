<script lang="ts">
  import type { StrikeEvent } from '../types';
  import { fmt, fmtTime } from '../stats';
  import TypeTag from './TypeTag.svelte';
  import ConfBadge from './ConfBadge.svelte';
  import { DURATION_TYPES } from '../taxonomy';

  let { events, selectedId = null, onselect, roundNumber }: { events: StrikeEvent[]; selectedId?: number | null; onselect: (id: number) => void; roundNumber: (idx: number | null) => string } = $props();
  type Key = 'id' | 't_peak_s' | 'type' | 'confidence' | 'hand' | 'target' | 'peak_g' | 'speed_mps_est' | 'duration_ms' | 'round_index' | 'saturated';
  let sortKey = $state<Key>('t_peak_s');
  let asc = $state(true);
  let page = $state(0);
  const PER = 60;
  const cols: { k: Key; label: string; r?: boolean }[] = [
    { k: 'id', label: '#', r: true }, { k: 't_peak_s', label: 'Time', r: true }, { k: 'type', label: 'Type' }, { k: 'confidence', label: 'Conf.', r: true },
    { k: 'hand', label: 'Hand' }, { k: 'target', label: 'Target' }, { k: 'peak_g', label: 'Peak g', r: true }, { k: 'speed_mps_est', label: 'Speed (est.)', r: true },
    { k: 'duration_ms', label: 'Dur.', r: true }, { k: 'round_index', label: 'Round', r: true }, { k: 'saturated', label: 'Clipped' },
  ];
  const sorted = $derived.by(() => {
    const a = [...events];
    a.sort((x, y) => {
      const p = x[sortKey] as unknown, q = y[sortKey] as unknown;
      const pv = p === null || p === undefined ? -Infinity : p, qv = q === null || q === undefined ? -Infinity : q;
      const c = typeof pv === 'string' && typeof qv === 'string' ? pv.localeCompare(qv) : (pv as number) > (qv as number) ? 1 : (pv as number) < (qv as number) ? -1 : 0;
      return asc ? c : -c;
    });
    return a;
  });
  const pages = $derived(Math.max(1, Math.ceil(sorted.length / PER)));
  $effect(() => { if (page >= pages) page = pages - 1; });
  // jump to page containing selection
  $effect(() => {
    if (selectedId === null) return;
    const i = sorted.findIndex((e) => e.id === selectedId);
    if (i >= 0) page = Math.floor(i / PER);
  });
  const rows = $derived(sorted.slice(page * PER, page * PER + PER));
  function sortBy(k: Key) { if (sortKey === k) asc = !asc; else { sortKey = k; asc = k === 't_peak_s' || k === 'id' || k === 'type'; } }
</script>

<div class="scroll-x tablewrap">
  <table>
    <thead>
      <tr>
        {#each cols as c (c.k)}
          <th class:r={c.r} aria-sort={sortKey === c.k ? (asc ? 'ascending' : 'descending') : 'none'}>
            <button class="th" onclick={() => sortBy(c.k)}>{c.label}{sortKey === c.k ? (asc ? ' ▲' : ' ▼') : ''}</button>
          </th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each rows as e (e.id)}
        <tr class:sel={e.id === selectedId} onclick={() => onselect(e.id)} tabindex="0" onkeydown={(k) => { if (k.key === 'Enter' || k.key === ' ') { k.preventDefault(); onselect(e.id); } }} aria-selected={e.id === selectedId}>
          <td class="r num dim">{e.id}</td>
          <td class="r num">{fmtTime(e.t_peak_s, true)}</td>
          <td><TypeTag type={e.type} confidence={e.confidence} short /></td>
          <td class="r"><ConfBadge value={e.confidence} /></td>
          <td>{e.hand ?? '—'}</td>
          <td>{e.target ?? '—'}</td>
          <td class="r num">{DURATION_TYPES.has(e.type) ? '—' : `${e.saturated ? '≥' : ''}${fmt(e.peak_g, 1)}`}</td>
          <td class="r num">{e.speed_mps_est === null ? '—' : `~${fmt(e.speed_mps_est, 1)}`}</td>
          <td class="r num">{DURATION_TYPES.has(e.type) ? `${(e.duration_ms / 1000).toFixed(1)} s` : `${fmt(e.duration_ms, 0)} ms`}</td>
          <td class="r num">{roundNumber(e.round_index)}</td>
          <td>{#if e.saturated}<span class="badge sat">clipped</span>{/if}</td>
        </tr>
      {:else}
        <tr><td colspan="11" class="muted" style="text-align:center;padding:1.5rem">No events match the filters.</td></tr>
      {/each}
    </tbody>
  </table>
</div>
{#if pages > 1}
  <div class="pager small">
    <button class="btn sm" disabled={page === 0} onclick={() => page--}>← Prev</button>
    <span class="num muted">Page {page + 1} / {pages} · {sorted.length} events</span>
    <button class="btn sm" disabled={page >= pages - 1} onclick={() => page++}>Next →</button>
  </div>
{/if}

<style>
  .tablewrap { max-height: 560px; overflow-y: auto; border-radius: 10px; border: 1px solid var(--line); }
  .th { background: none; border: 0; padding: 0; color: inherit; font: inherit; text-transform: inherit; letter-spacing: inherit; cursor: pointer; }
  tr { cursor: pointer; }
  tr.sel { background: rgba(255, 90, 54, 0.12) !important; box-shadow: inset 3px 0 0 var(--accent); }
  tr:focus-visible { outline: 2px solid var(--accent2); outline-offset: -2px; }
  .pager { display: flex; gap: 0.8rem; align-items: center; justify-content: center; margin-top: 0.6rem; }
</style>
