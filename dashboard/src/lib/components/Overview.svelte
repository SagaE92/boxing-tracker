<script lang="ts">
  import { app } from '../state.svelte';
  import { activeTime, applyFilters, comboStats, combos, dataQuality, fatigue, filtersActive, fmt, fmtTime, maxOf, pct, peakText, roundStats, summarize } from '../stats';
  import { NON_STRIKE, TYPES, isStrike, typeColor, typeLabel } from '../taxonomy';
  import { TIPS } from '../tips';
  import { download, eventsCsv, exportPng, summaryCsv } from '../exporters';
  import Stat from './Stat.svelte';
  import Donut from './Donut.svelte';
  import Bars from './Bars.svelte';
  import LineChart from './LineChart.svelte';
  import Tip from './Tip.svelte';
  import Timeline from './Timeline.svelte';
  import StrikeDetail from './StrikeDetail.svelte';
  import DataQualityPanel from './DataQualityPanel.svelte';

  const s = $derived(app.active!);
  const j = $derived(s.json);
  const all = $derived(j?.punches ?? []);
  const filtered = $derived(applyFilters(all, app.filters));
  const act = $derived(activeTime(j, j?.session.duration_s ?? 0));
  const sm = $derived(summarize(filtered, act, app.filters.includeNonStrike));
  const allSm = $derived(summarize(all, act));
  const rs = $derived(j ? roundStats(j, filtered) : []);
  const fat = $derived(fatigue(rs));
  const cmb = $derived(comboStats(combos(filtered, app.comboGapMs)));
  const dq = $derived(dataQuality(j, s.raw, all));
  const range = $derived(j?.session.accel_range_g ?? 16);
  const maxClipped = $derived(maxOf(filtered.filter((e) => e.saturated && isStrike(e.type)).map((e) => e.peak_g)));
  const active = $derived(filtersActive(app.filters));
  const selected = $derived(all.find((e) => e.id === app.selectedId) ?? null);
  const leadHand = $derived(j?.session.stance === 'southpaw' ? 'R' : 'L');
  const lead = $derived(leadHand === 'L' ? sm.byHand.L : sm.byHand.R);
  const rear = $derived(leadHand === 'L' ? sm.byHand.R : sm.byHand.L);
  const typeItems = $derived(TYPES.filter((t) => isStrike(t)).map((t) => ({ label: typeLabel(t), value: sm.byType[t] ?? 0, color: typeColor(t) })));
  const byHandType = $derived(TYPES.filter((t) => isStrike(t) && (sm.byType[t] ?? 0) > 0).map((t) => ({ t, L: filtered.filter((e) => e.type === t && e.hand === 'L').length, R: filtered.filter((e) => e.type === t && e.hand === 'R').length })));
  let summaryEl = $state<HTMLElement>();

  function step(d: number) {
    const ev = filtered.length ? filtered : all;
    const i = ev.findIndex((e) => e.id === app.selectedId);
    const n = ev[Math.max(0, Math.min(ev.length - 1, i + d))];
    if (n) app.selectStrike(n.id);
  }
  const base = $derived(j?.session.id ?? s.name);
  async function png() { if (summaryEl) await exportPng(summaryEl, `${base}_summary.png`); }
  function csvSummary() {
    download(`${base}_summary.csv`, summaryCsv(base, sm, [
      ['filters_active', String(active)], ['peak_g_drop_first_to_last_round_pct', fat.peakDropPct !== null ? +fat.peakDropPct.toFixed(1) : null],
      ['speed_drop_first_to_last_round_pct', fat.speedDropPct !== null ? +fat.speedDropPct.toFixed(1) : null], ['saturated_sample_fraction', +dq.satFraction.toFixed(5)],
      ['ble_gaps', dq.gaps.length], ['dropped_samples_est', dq.droppedEst], ['calibrated', String(dq.calibrated)],
      ...rs.map((r) => [`round_${r.number}_strikes`, r.strikes] as [string, number]),
    ]));
  }
  function csvEvents() { download(`${base}_events${active ? '_filtered' : ''}.csv`, eventsCsv(filtered)); }
</script>

{#if !j}
  <div class="card"><h2>Raw data only</h2><p class="muted">This session has a raw CSV but no <span class="mono">session.json</span>. Run <span class="mono">python analysis/detector.py</span> on it and drop the output here to see strikes, rounds and stats. The Signals tab shows the raw waveforms now.</p></div>
{:else}
  {#if dq.issues.some((i) => i.level !== 'info')}
    <section class="dq-banner" aria-label="Data quality warnings">
      {#each dq.issues.filter((i) => i.level !== 'info') as i (i.text)}
        <div class="alert {i.level}"><span class="ico">{i.level === 'bad' ? '!!' : '!'}</span><span>{i.text}</span></div>
      {/each}
    </section>
  {/if}

  <div class="exports" data-noexport>
    {#if active}<span class="badge info">Filtered view: {filtered.length} of {all.length} events</span>{/if}
    <span class="spacer"></span>
    <button class="btn sm" onclick={png}>⤓ Summary PNG</button>
    <button class="btn sm" onclick={csvSummary}>⤓ Summary CSV</button>
    <button class="btn sm" onclick={csvEvents}>⤓ {active ? 'Filtered' : 'All'} events CSV</button>
  </div>

  <section bind:this={summaryEl} class="summary" aria-label="Session summary">
    <div class="stats">
      <Stat label="Strikes" value={String(sm.strikes)} tip={TIPS.strikes} tone="accent" sub={`${allSm.nonStrike} non-strike event(s) excluded`} />
      <Stat label="Work rate" value={fmt(sm.perMin, 1)} unit="/min" tip={TIPS.perMin} sub={`over ${fmtTime(act)} of rounds`} />
      {#if sm.saturatedStrikes}
        <Stat label="Mean peak · unclipped" value={fmt(sm.meanPeakUnclipped, 1)} unit="g" tip={TIPS.meanPeak} sub={`${sm.unclippedStrikes} exact · incl. ${sm.saturatedStrikes} clipped: ${peakText(sm.meanPeak, true)} g`} />
      {:else}
        <Stat label="Mean peak" value={fmt(sm.meanPeak, 1)} unit="g" tip={TIPS.meanPeak} sub="acceleration, not force" />
      {/if}
      <Stat label="Max peak" value={peakText(sm.maxPeak, sm.maxPeakSaturated)} unit="g" tip={TIPS.maxPeak} tone={sm.maxPeakSaturated ? 'warn' : ''}
        sub={sm.maxPeakSaturated ? `clipped at ±${range} g/axis · lower bound` : `not clipped · 3-axis magnitude${sm.saturatedStrikes ? ` · max clipped ${peakText(maxClipped, true)}` : ''}`} />
      <Stat label="Speed (est.)" value={fmt(sm.meanSpeed, 1)} unit="m/s" tip={TIPS.speed} sub={`max ~${fmt(sm.maxSpeed, 1)} m/s · estimate`} />
      <Stat label="Clipped strikes" value={String(sm.saturatedStrikes)} tip={TIPS.saturation} tone={sm.saturatedStrikes ? 'warn' : ''} sub={`${pct(dq.satFraction, 3)} of samples saturated`} />
      <Stat label="Confidence" value={sm.meanConfidence === null ? '—' : `${Math.round(sm.meanConfidence * 100)}%`} tip={TIPS.confidence} sub={`${sm.lowConfidence} strike(s) below 50%`} />
      <Stat label="Kick / clinch" value={`${allSm.kicks} · ${allSm.clinches}`} tip={TIPS.nonStrike} sub={`kick/body events · clinch ${fmt(allSm.clinchTimeS, 0)} s`}>
        <span class="badge low" style="align-self:flex-start;margin-top:.2rem">low confidence · not in totals</span>
      </Stat>
    </div>

    <div class="row3">
      <div class="card">
        <div class="card-h"><h2>Type mix <Tip text={TIPS.types} /></h2><span class="sub">strikes only</span></div>
        <div class="mix">
          <Donut items={typeItems} center={String(sm.strikes)} centerSub="strikes" />
          <ul class="legend">
            {#each typeItems.filter((t) => t.value) as t (t.label)}
              <li><span class="dot" style="background:{t.color}"></span>{t.label}<span class="num">{t.value}</span><span class="num dim">{pct(t.value / Math.max(1, sm.strikes))}</span></li>
            {/each}
          </ul>
        </div>
      </div>
      <div class="card">
        <div class="card-h"><h2>Hands & targets <Tip text={TIPS.hand} /></h2><span class="sub">sensor on {j.session.hand ?? '?'} hand · {j.session.stance ?? '?'}</span></div>
        <div class="split" aria-label="Lead versus rear balance">
          <div class="splitbar"><span style="flex:{lead || 0.001};background:#38bdf8"></span><span style="flex:{rear || 0.001};background:#f472b6"></span><span style="flex:{sm.byHand.unknown || 0.001};background:#475569"></span></div>
          <div class="splitlab small"><span>Lead ({leadHand}) <b class="num">{lead}</b></span><span>Rear ({leadHand === 'L' ? 'R' : 'L'}) <b class="num">{rear}</b></span>{#if sm.byHand.unknown}<span class="dim">Unknown <b class="num">{sm.byHand.unknown}</b></span>{/if}</div>
        </div>
        <div class="split" aria-label="Head versus body">
          <div class="splitbar"><span style="flex:{sm.byTarget.head || 0.001};background:#ffb020"></span><span style="flex:{sm.byTarget.body || 0.001};background:#a3e635"></span><span style="flex:{sm.byTarget.unknown || 0.001};background:#475569"></span></div>
          <div class="splitlab small"><span>Head <b class="num">{sm.byTarget.head}</b></span><span>Body <b class="num">{sm.byTarget.body}</b></span>{#if sm.byTarget.unknown}<span class="dim">Unknown <b class="num">{sm.byTarget.unknown}</b></span>{/if}<Tip text={TIPS.target} /></div>
        </div>
        <table class="mini">
          <thead><tr><th>Type</th><th class="r">L</th><th class="r">R</th></tr></thead>
          <tbody>{#each byHandType as r (r.t)}<tr><td><span class="dot" style="background:{typeColor(r.t)}"></span> {typeLabel(r.t)}</td><td class="r num">{r.L}</td><td class="r num">{r.R}</td></tr>{/each}</tbody>
        </table>
      </div>
      <div class="card">
        <div class="card-h"><h2>Strikes per round <Tip text={TIPS.perRound} /></h2><span class="sub">{fmt(sm.perMin, 1)}/min overall</span></div>
        <Bars data={rs.map((r) => ({ label: `R${r.number}`, value: r.strikes, note: `${fmt(r.perMin, 1)}/min` }))} height={150} ariaLabel="Strikes per round" />
        <div class="card-h" style="margin:.6rem 0 .2rem"><h3>Work rate per round <Tip text={TIPS.workRate} /></h3></div>
        <Bars data={rs.map((r) => ({ label: `R${r.number}`, value: r.perMin, color: '#ffb020' }))} height={110} decimals={1} unit="/min" ariaLabel="Work rate per round" />
      </div>
    </div>
  </section>

  <section class="card">
    <div class="card-h">
      <h2>Session timeline</h2>
      <span class="sub">peak g per strike · rounds shaded, rests hatched · lines link combos (&lt;{app.comboGapMs} ms) · red ring = clipped · ■ = kick/body · grey band = clinch · bottom strip = density · drag to zoom the signal view</span>
    </div>
    <Timeline session={s} events={filtered} labels={s.labels ?? []} comboGapMs={app.comboGapMs} selectedId={app.selectedId} range={app.range}
      onselect={(id) => app.selectStrike(id)} onrange={(r) => (app.range = r)} />
    <div class="keys small">
      {#each TYPES.filter((t) => allSm.byType[t]) as t (t)}<span><span class="dot" style="background:{typeColor(t)}"></span>{typeLabel(t)}{NON_STRIKE.has(t) ? ' (low conf.)' : ''}</span>{/each}
      {#if s.labels}<span class="dim">| ticks at bottom = video labels</span>{/if}
      {#if app.range}<button class="btn sm ghost" onclick={() => (app.tab = 'signals')}>Open selection in Signals →</button>{/if}
    </div>
  </section>

  {#if selected}
    <StrikeDetail session={s} event={selected} onclose={() => (app.selectedId = null)} onprev={() => step(-1)} onnext={() => step(1)} />
  {/if}

  <div class="row2">
    <section class="card">
      <div class="card-h"><h2>Fatigue <Tip text={TIPS.fatigue} /></h2><span class="sub">mean per round, dashed = linear trend{sm.saturatedStrikes ? ' · peak means include clipped lower bounds' : ''}</span></div>
      <div class="fat">
        <div><span class="k">Peak g, first → last round</span><b class="num {fat.peakDropPct !== null && fat.peakDropPct > 5 ? 'down' : ''}">{fmt(fat.firstPeak, 1)} → {fmt(fat.lastPeak, 1)} g</b><span class="num">{fat.peakDropPct === null ? '' : `${fat.peakDropPct > 0 ? '−' : '+'}${Math.abs(fat.peakDropPct).toFixed(1)}%`}</span></div>
        <div><span class="k">Speed (est.), first → last</span><b class="num {fat.speedDropPct !== null && fat.speedDropPct > 5 ? 'down' : ''}">{fmt(fat.firstSpeed, 1)} → {fmt(fat.lastSpeed, 1)} m/s</b><span class="num">{fat.speedDropPct === null ? '' : `${fat.speedDropPct > 0 ? '−' : '+'}${Math.abs(fat.speedDropPct).toFixed(1)}%`}</span></div>
        <div><span class="k">Work rate, first → last</span><b class="num {fat.rateDropPct !== null && fat.rateDropPct > 5 ? 'down' : ''}">{fmt(fat.firstRate, 0)} → {fmt(fat.lastRate, 0)} /min</b><span class="num">{fat.rateDropPct === null ? '' : `${fat.rateDropPct > 0 ? '−' : '+'}${Math.abs(fat.rateDropPct).toFixed(1)}%`}</span></div>
      </div>
      <LineChart labels={rs.map((r) => `R${r.number}`)} series={[
        { name: 'Mean peak g', color: '#ff5a36', values: rs.map((r) => r.meanPeak), trend: true },
        { name: 'Speed est. (m/s)', color: '#38bdf8', values: rs.map((r) => r.meanSpeed), trend: true },
      ]} ariaLabel="Mean peak g and estimated speed per round" />
    </section>
    <section class="card">
      <div class="card-h"><h2>Combos <Tip text={TIPS.combos} /></h2>
        <label class="small muted">gap <input type="range" min="300" max="1200" step="50" bind:value={app.comboGapMs} aria-label="Combo gap in ms" /> <span class="num">{app.comboGapMs} ms</span></label>
      </div>
      <div class="fat">
        <div><span class="k">Combos (2+)</span><b class="num">{cmb.comboCount}</b></div>
        <div><span class="k">Mean length</span><b class="num">{fmt(cmb.meanLength, 1)}</b></div>
        <div><span class="k">Strikes in combos</span><b class="num">{pct(cmb.strikesInCombos / Math.max(1, sm.strikes))}</b></div>
      </div>
      <Bars data={Object.entries(cmb.lengths).map(([k, v]) => ({ label: k === '1' ? 'single' : `${k} strikes`, value: v, color: '#c084fc' }))} height={120} ariaLabel="Combo length distribution" />
      <h3 style="margin:.6rem 0 .3rem">Most common sequences</h3>
      <ol class="seqs">
        {#each cmb.top as [seq, n] (seq)}
          <li><span class="seq">{#each seq.split('>') as t, i (i)}{#if i}<span class="arrow">→</span>{/if}<span class="pill" style="border-color:{typeColor(t)};color:{typeColor(t)}">{typeLabel(t)}</span>{/each}</span><span class="num">{n}×</span></li>
        {:else}<li class="muted">No combos with the current gap.</li>{/each}
      </ol>
    </section>
  </div>

  <section class="card">
    <div class="card-h"><h2>Round by round</h2><span class="sub">within-round change = fitted start→end change in that round</span></div>
    <div class="scroll-x">
      <table>
        <thead><tr><th>Round</th><th class="r">Strikes</th><th class="r">Rate /min</th><th class="r">Mean peak g</th><th class="r">Max peak g</th><th class="r">Clipped</th><th class="r">Speed est.</th><th class="r">Peak g within round</th><th class="r">Speed within round</th><th class="r">Kick/clinch</th><th class="r">Rest after</th></tr></thead>
        <tbody>
          {#each rs as r (r.number)}
            <tr>
              <td><b>R{r.number}</b> <span class="dim num small">{fmtTime(r.round.t_start_s)}–{fmtTime(r.round.t_end_s)}</span></td>
              <td class="r num">{r.strikes}</td><td class="r num">{fmt(r.perMin, 1)}</td><td class="r num" title={r.clipped ? `includes ${r.clipped} clipped strike(s) whose peak is a lower bound, so the true mean is at least this` : undefined}>{peakText(r.meanPeak, r.clipped > 0, 2)}</td><td class="r num">{peakText(r.maxPeak, r.maxPeakSat)}</td><td class="r num {r.clipped ? 'warn-t' : 'dim'}">{r.clipped}</td><td class="r num">{fmt(r.meanSpeed, 2)}</td>
              <td class="r num {r.withinPeakChangePct !== null && r.withinPeakChangePct < -5 ? 'down' : ''}">{r.withinPeakChangePct === null ? '—' : `${r.withinPeakChangePct > 0 ? '+' : ''}${r.withinPeakChangePct.toFixed(1)}%`}</td>
              <td class="r num {r.withinSpeedChangePct !== null && r.withinSpeedChangePct < -5 ? 'down' : ''}">{r.withinSpeedChangePct === null ? '—' : `${r.withinSpeedChangePct > 0 ? '+' : ''}${r.withinSpeedChangePct.toFixed(1)}%`}</td>
              <td class="r num">{r.nonStrike}</td>
              <td class="r num">{r.restAfterS === null ? '—' : `${r.restAfterS.toFixed(0)} s`}</td>
            </tr>
          {:else}<tr><td colspan="11" class="muted">No rounds in this session.json.</td></tr>{/each}
        </tbody>
      </table>
    </div>
  </section>

  <DataQualityPanel {dq} session={s} />
{/if}

<style>
  .dq-banner { display: grid; gap: 0.5rem; }
  .exports { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
  .spacer { flex: 1; }
  .warn-t { color: var(--warn, #fbbf24); }
  .summary { display: grid; gap: 0.9rem; padding: 2px; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.75rem; }
  .row3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr)); gap: 0.9rem; }
  .row2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(340px, 100%), 1fr)); gap: 0.9rem; }
  .mix { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; }
  .legend { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.25rem; font-size: 0.85rem; flex: 1; min-width: 150px; }
  .legend li { display: grid; grid-template-columns: 14px 1fr auto 3rem; gap: 0.4rem; align-items: center; }
  .legend .num { text-align: right; }
  .split { margin-bottom: 0.7rem; }
  .splitbar { display: flex; height: 12px; border-radius: 6px; overflow: hidden; gap: 2px; }
  .splitlab { display: flex; gap: 1rem; margin-top: 0.3rem; color: var(--muted); flex-wrap: wrap; align-items: center; }
  .splitlab b { color: var(--text); }
  .mini td, .mini th { padding: 0.25rem 0.4rem; }
  .keys { display: flex; gap: 0.9rem; flex-wrap: wrap; color: var(--muted); margin-top: 0.4rem; align-items: center; }
  .keys > span { display: inline-flex; gap: 0.35rem; align-items: center; }
  .fat { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.6rem; margin-bottom: 0.6rem; }
  .fat > div { display: flex; flex-direction: column; gap: 0.1rem; }
  .fat .k { color: var(--muted); font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.05em; }
  .fat b { font-size: 1.05rem; }
  .down { color: #fca5a5; }
  .seqs { margin: 0; padding-left: 1.2rem; display: grid; gap: 0.35rem; font-size: 0.84rem; }
  .seqs li { display: flex; justify-content: space-between; gap: 0.5rem; }
  .seq { display: inline-flex; flex-wrap: wrap; gap: 0.25rem; align-items: center; }
  .pill { border: 1px solid; border-radius: 999px; padding: 0 0.45rem; font-size: 0.76rem; }
  .arrow { color: var(--dim); }
</style>
