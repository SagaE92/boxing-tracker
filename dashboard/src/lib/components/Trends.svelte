<script lang="ts">
  import { app } from '../state.svelte';
  import { fmt, personalBests, sessionTrend, type SessionTrend } from '../stats';
  import { TYPES, isStrike, typeColor, typeLabel } from '../taxonomy';
  import { TIPS } from '../tips';
  import LineChart from './LineChart.svelte';
  import Bars from './Bars.svelte';
  import Stat from './Stat.svelte';
  import Tip from './Tip.svelte';

  const ts = $derived(app.sessions.map(sessionTrend).filter((t): t is SessionTrend => !!t).sort((a, b) => +a.date - +b.date));
  const labels = $derived(ts.map((t) => t.date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })));
  const pb = $derived(personalBests(ts));
  const PAL = ['#64748b', '#38bdf8', '#ff5a36', '#a3e635', '#c084fc', '#facc15'];
  const maxRounds = $derived(Math.max(0, ...ts.map((t) => t.rounds.length)));
  let aKey = $state<string | null>(null);
  let bKey = $state<string | null>(null);
  $effect(() => {
    if (ts.length >= 2) {
      if (!aKey || !ts.find((t) => t.key === aKey)) aKey = ts[ts.length - 2].key;
      if (!bKey || !ts.find((t) => t.key === bKey)) bKey = ts[ts.length - 1].key;
    }
  });
  const A = $derived(ts.find((t) => t.key === aKey));
  const B = $derived(ts.find((t) => t.key === bKey));
  type Row = { label: string; get: (t: SessionTrend) => number | null; d: number; unit: string; better: 1 | -1 | 0 };
  const rows: Row[] = [
    { label: 'Strikes', get: (t) => t.strikes, d: 0, unit: '', better: 1 },
    { label: 'Work rate', get: (t) => t.perMin, d: 1, unit: '/min', better: 1 },
    { label: 'Mean peak g', get: (t) => t.meanPeak, d: 2, unit: ' g', better: 1 },
    { label: 'Max peak g', get: (t) => t.maxPeak, d: 1, unit: ' g', better: 1 },
    { label: 'Speed est. (mean)', get: (t) => t.meanSpeed, d: 2, unit: ' m/s', better: 1 },
    { label: 'Peak g drop, R1→last', get: (t) => t.fat.peakDropPct, d: 1, unit: '%', better: -1 },
    { label: 'Speed drop, R1→last', get: (t) => t.fat.speedDropPct, d: 1, unit: '%', better: -1 },
    { label: 'Kick/clinch events', get: (t) => t.nonStrike, d: 0, unit: '', better: 0 },
    { label: 'Saturated samples', get: (t) => t.satFraction * 100, d: 3, unit: '%', better: -1 },
  ];
  const day = (t: SessionTrend | null) => (t ? t.date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '');
</script>

{#if ts.length < 2}
  <div class="card empty">
    <h2>Trends need 2+ sessions</h2>
    <p class="muted">Drop several <span class="mono">session.json</span> files at once (or one by one) to compare volume, peak g, type mix and fatigue across sessions. The demo loads three.</p>
    <button class="btn primary" onclick={() => app.demo()}>Load demo sessions</button>
  </div>
{:else}
  <section class="pbs" aria-label="Personal bests">
    <Stat label="Best max peak" value={`${pb.maxPeak?.maxPeakSat ? '≥' : ''}${fmt(pb.maxPeak?.maxPeak, 1)}`} unit="g" sub={day(pb.maxPeak)} tip={TIPS.maxPeak} tone="accent" />
    <Stat label="Best speed (est.)" value={fmt(pb.maxSpeed?.maxSpeed, 1)} unit="m/s" sub={day(pb.maxSpeed)} tip={TIPS.speed} />
    <Stat label="Most strikes" value={String(pb.strikes?.strikes ?? '—')} sub={day(pb.strikes)} tip={TIPS.strikes} />
    <Stat label="Best work rate" value={fmt(pb.perMin?.perMin, 1)} unit="/min" sub={day(pb.perMin)} tip={TIPS.perMin} />
  </section>
  <div class="row2">
    <section class="card"><div class="card-h"><h2>Volume & work rate</h2><span class="sub">strikes per session · strikes per minute of rounds</span></div>
      <div class="two">
        <Bars data={ts.map((t, i) => ({ label: labels[i], value: t.strikes }))} height={170} ariaLabel="Strikes per session" highlight={ts.length - 1} />
        <Bars data={ts.map((t, i) => ({ label: labels[i], value: t.perMin, color: '#a3e635' }))} height={170} decimals={1} unit="/min" ariaLabel="Work rate per session" highlight={ts.length - 1} />
      </div>
    </section>
    <section class="card"><div class="card-h"><h2>Peak-g trend <Tip text={TIPS.meanPeak} /></h2><span class="sub">acceleration, not force</span></div>
      <LineChart {labels} series={[{ name: 'Mean peak g', color: '#ff5a36', values: ts.map((t) => t.meanPeak), trend: true }, { name: 'Max peak g', color: '#ffb020', values: ts.map((t) => t.maxPeak), dashed: true }]} ariaLabel="Peak g per session" />
    </section>
    <section class="card"><div class="card-h"><h2>Speed (est.) <Tip text={TIPS.speed} /></h2><span class="sub">m/s, heuristic estimate</span></div>
      <LineChart {labels} series={[{ name: 'Mean speed est.', color: '#38bdf8', values: ts.map((t) => t.meanSpeed), trend: true }, { name: 'Max speed est.', color: '#c084fc', values: ts.map((t) => t.maxSpeed), dashed: true }]} unit=" m/s" ariaLabel="Estimated speed per session" />
    </section>
    <section class="card"><div class="card-h"><h2>Fatigue across sessions <Tip text={TIPS.fatigue} /></h2><span class="sub">first → last round drop (lower is better)</span></div>
      <LineChart {labels} series={[{ name: 'Peak g drop %', color: '#f87171', values: ts.map((t) => t.fat.peakDropPct) }, { name: 'Speed drop %', color: '#c084fc', values: ts.map((t) => t.fat.speedDropPct) }]} unit="%" ariaLabel="Fatigue drop per session" />
    </section>
  </div>
  <section class="card"><div class="card-h"><h2>Mean peak g by round, per session</h2><span class="sub">steeper slope = more fade</span></div>
    <LineChart labels={Array.from({ length: maxRounds }, (_, i) => `R${i + 1}`)} series={ts.map((t, i) => ({ name: labels[i], color: PAL[(i + PAL.length - ts.length) % PAL.length] ?? '#94a3b8', values: Array.from({ length: maxRounds }, (_, k) => t.rounds[k]?.meanPeak ?? null), trend: i === ts.length - 1 }))} ariaLabel="Mean peak g by round for each session" />
  </section>
  <section class="card"><div class="card-h"><h2>Type mix</h2><span class="sub">share of strikes</span></div>
    <div class="mix">
      {#each ts as t, i (t.key)}
        {@const tot = TYPES.filter(isStrike).reduce((a, k) => a + (t.byType[k] ?? 0), 0) || 1}
        <div class="mixrow"><span class="num small">{labels[i]}</span>
          <div class="stack" role="img" aria-label="Type mix {labels[i]}">{#each TYPES.filter(isStrike) as k (k)}{#if t.byType[k]}<span style="flex:{t.byType[k]};background:{typeColor(k)}" title="{typeLabel(k)}: {t.byType[k]} ({Math.round((100 * t.byType[k]) / tot)}%)"></span>{/if}{/each}</div>
        </div>
      {/each}
      <div class="keys small">{#each TYPES.filter(isStrike) as k (k)}<span><span class="dot" style="background:{typeColor(k)}"></span>{typeLabel(k)}</span>{/each}</div>
    </div>
  </section>
  <section class="card"><div class="card-h"><h2>Compare sessions</h2>
      <div class="cmpsel">
        <select bind:value={aKey} aria-label="Session A">{#each ts as t, i (t.key)}<option value={t.key}>{labels[i]} · {t.name}</option>{/each}</select>
        <span class="muted">vs</span>
        <select bind:value={bKey} aria-label="Session B">{#each ts as t, i (t.key)}<option value={t.key}>{labels[i]} · {t.name}</option>{/each}</select>
      </div></div>
    {#if A && B}
      <div class="scroll-x"><table>
        <thead><tr><th>Metric</th><th class="r">A · {day(A)}</th><th class="r">B · {day(B)}</th><th class="r">Δ (B − A)</th></tr></thead>
        <tbody>
          {#each rows as r (r.label)}
            {@const a = r.get(A)}{@const b = r.get(B)}
            {@const d = a !== null && b !== null ? b - a : null}
            <tr><td>{r.label}</td><td class="r num">{fmt(a, r.d)}{r.unit}</td><td class="r num">{fmt(b, r.d)}{r.unit}</td>
              <td class="r num {d === null || r.better === 0 || Math.abs(d) < 1e-9 ? '' : d * r.better > 0 ? 'up' : 'down'}">{d === null ? '—' : `${d > 0 ? '+' : ''}${d.toFixed(r.d)}${r.unit}`}</td></tr>
          {/each}
        </tbody>
      </table></div>
    {/if}
  </section>
{/if}

<style>
  .empty { text-align: center; padding: 2rem; display: grid; gap: 0.7rem; justify-items: center; }
  .pbs { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 0.75rem; }
  .row2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(420px, 100%), 1fr)); gap: 0.9rem; }
  .mix { display: grid; gap: 0.5rem; }
  .mixrow { display: grid; grid-template-columns: 4.5rem 1fr; gap: 0.6rem; align-items: center; }
  .stack { display: flex; height: 18px; border-radius: 6px; overflow: hidden; gap: 1px; }
  .keys { display: flex; flex-wrap: wrap; gap: 0.8rem; color: var(--muted); margin-top: 0.3rem; }
  .keys span { display: inline-flex; gap: 0.3rem; align-items: center; }
  .cmpsel { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
  .two { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(180px, 100%), 1fr)); gap: 0.8rem; }
  .two > :global(*) { min-width: 0; }
  .up { color: #86efac; } .down { color: #fca5a5; }
  @media (max-width: 420px) { .row2 { grid-template-columns: 1fr; } }
</style>
