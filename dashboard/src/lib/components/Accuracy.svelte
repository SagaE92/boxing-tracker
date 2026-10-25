<script lang="ts">
  import { app } from '../state.svelte';
  import { fmt, matchLabels, pct } from '../stats';
  import { HOOKS, NON_STRIKE, typeColor, typeLabel, TYPE_SHORT, type EventType } from '../taxonomy';
  import { TIPS } from '../tips';
  import { download } from '../exporters';
  import { toCsv } from '../csv';
  import Stat from './Stat.svelte';
  import Tip from './Tip.svelte';

  const s = $derived(app.active!);
  const m = $derived(s.json && s.labels ? matchLabels(s.json.punches, s.labels, app.tolMs) : null);
  const rowTotal = (cls: string) => (m ? m.classes.reduce((a, c) => a + m!.confusion[cls][c], 0) + m.missed[cls] : 0);
  function shade(v: number, tot: number, diag: boolean) {
    if (!v || !tot) return 'transparent';
    const f = v / tot;
    return diag ? `rgba(52,211,153,${0.12 + 0.6 * f})` : `rgba(248,113,113,${0.1 + 0.6 * f})`;
  }
  function exportMatrix() {
    if (!m) return;
    const header = ['labelled \\ predicted', ...m.classes, 'missed'];
    const rows: (string | number)[][] = m.classes.map((c) => [c, ...m!.classes.map((p) => m!.confusion[c][p]), m!.missed[c]]);
    rows.push(['no_label (false positive)', ...m.classes.map((p) => m!.falsePos[p]), '']);
    download(`${s.json!.session.id}_confusion_tol${app.tolMs}ms.csv`, toCsv(header, rows));
  }
</script>

{#if !s.json}
  <div class="card"><h2>Needs session.json</h2><p class="muted">Accuracy compares the detector's events with video labels.</p></div>
{:else if !s.labels}
  <div class="card empty">
    <h2>No labels loaded</h2>
    <p class="muted">Label a session from phone video (<span class="mono">host_time_s,label,note</span>; label is a type, optionally with a hand, e.g. <span class="mono">lead_hook_L</span>) and drop the CSV together with its session.json. This view then reports detection precision/recall and a per-class confusion matrix, so every accuracy claim is checkable.</p>
    <p class="small dim">Recognised labels: jab, cross, lead_hook, rear_hook, lead_uppercut, rear_uppercut, overhand, spinning_backfist, kick_or_body_movement, clinch, unknown; legacy hook_L / uppercut_R map via stance.</p>
  </div>
{:else if m}
  {#if s.demo || s.json.generator.name.includes('synthetic')}
    <div class="alert warn" role="note"><span class="ico">!</span><span><b>Synthetic data.</b> These labels are the simulator's ground truth, so the numbers below only check that the pipeline works end to end. They say nothing about real-world accuracy until we label real sessions from video.</span></div>
  {/if}
  <section class="card tolbar">
    <label class="field">Matching tolerance <Tip text={TIPS.tolerance} />
      <span class="tol"><input type="range" min="50" max="500" step="10" bind:value={app.tolMs} aria-label="Matching tolerance in ms" /><b class="num">±{app.tolMs} ms</b></span></label>
    <span class="small muted">{s.labels.length} labels · {s.json.punches.length} detected events · mean |Δt| of matches {fmt(m.meanAbsDtMs, 0)} ms</span>
    <button class="btn sm" onclick={exportMatrix}>⤓ Confusion CSV</button>
  </section>

  <section class="hook card" aria-label="Hook recall">
    <div>
      <div class="lab">Hook recall · headline target <Tip text={TIPS.classRecall} /></div>
      <div class="big num">{pct(m.hookRecall)}</div>
      <div class="small muted">{m.hookCorrect} of {m.hookLabelled} labelled hooks detected <b>and</b> typed as the right hook.</div>
    </div>
    <div class="ref small">
      <div class="muted">Published reference (shadowboxing vs video, 21 subjects):</div>
      <div>Corner / Hykso hooks recognised: <b>~50–65%</b>; straights ~83–96%.</div>
      <a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC8123076/" target="_blank" rel="noopener">Omcirk et al. 2021 ↗</a>
      <div class="dim">Different protocol and athletes: indicative, not head-to-head.</div>
    </div>
  </section>

  <section class="stats">
    <Stat label="Detection recall" value={pct(m.recall)} tip={TIPS.recall} sub={`${m.tp} of ${m.tp + m.fn} labels found (any type)`} tone="accent" />
    <Stat label="Detection precision" value={pct(m.precision)} tip={TIPS.precision} sub={`${m.fp} unmatched detection(s)`} />
    <Stat label="F1" value={m.f1 === null ? '—' : m.f1.toFixed(2)} sub="harmonic mean of the two" />
    <Stat label="Type accuracy" value={pct(m.typeAccuracy)} sub="of matched events" />
    <Stat label="Hand accuracy" value={pct(m.handAccuracy)} sub="labels with a hand suffix" />
  </section>

  <section class="card">
    <div class="card-h"><h2>Recall per class <Tip text={TIPS.classRecall} /></h2><span class="sub">labelled strikes detected with the correct type · hooks highlighted</span></div>
    <div class="recall">
      {#each m.perClass.filter((p) => p.labelled > 0).sort((a, b) => (HOOKS.includes(b.cls) ? 1 : 0) - (HOOKS.includes(a.cls) ? 1 : 0)) as p (p.cls)}
        <div class="rrow" class:hookrow={HOOKS.includes(p.cls)}>
          <span class="name"><span class="dot" style="background:{typeColor(p.cls)}"></span>{typeLabel(p.cls)}{#if NON_STRIKE.has(p.cls as EventType)} <span class="badge low">low conf.</span>{/if}</span>
          <div class="track" role="meter" aria-valuenow={Math.round((p.recall ?? 0) * 100)} aria-valuemin="0" aria-valuemax="100" aria-label="{typeLabel(p.cls)} recall">
            <span style="width:{(p.recall ?? 0) * 100}%;background:{typeColor(p.cls)}"></span>
            {#if HOOKS.includes(p.cls)}<i class="refband" title="Published consumer-tracker range 50–65%"></i>{/if}
          </div>
          <span class="num val">{pct(p.recall)}</span>
          <span class="num dim small">{p.correct}/{p.labelled} · prec. {pct(p.precision)}</span>
        </div>
      {/each}
    </div>
    <p class="small dim">Hatched band on hook rows: 50–65% published range for consumer trackers (see reference above).</p>
  </section>

  <section class="card">
    <div class="card-h"><h2>Confusion matrix</h2><span class="sub">rows = video label, columns = detector · green = correct, red = confused · last column/row = missed / false positives</span></div>
    <div class="scroll-x">
      <table class="cm">
        <thead>
          <tr><th>Label ↓ / Pred →</th>{#each m.classes as c (c)}<th class="r" title={typeLabel(c)}><span class="dot" style="background:{typeColor(c)}"></span> {TYPE_SHORT[c]}</th>{/each}<th class="r">Missed</th><th class="r">Recall</th></tr>
        </thead>
        <tbody>
          {#each m.classes as c (c)}
            {@const tot = rowTotal(c)}
            {#if tot > 0}
              <tr class:hookrow={HOOKS.includes(c)}>
                <th scope="row" class="rowh"><span class="dot" style="background:{typeColor(c)}"></span> {typeLabel(c)} <span class="dim num">({tot})</span></th>
                {#each m.classes as p (p)}<td class="r num" style="background:{shade(m.confusion[c][p], tot, c === p)}">{m.confusion[c][p] || ''}</td>{/each}
                <td class="r num" style="background:{shade(m.missed[c], tot, false)}">{m.missed[c] || ''}</td>
                <td class="r num"><b>{pct(m.confusion[c][c] / tot)}</b></td>
              </tr>
            {/if}
          {/each}
          <tr class="fprow"><th scope="row" class="rowh">No label (false +)</th>{#each m.classes as p (p)}<td class="r num">{m.falsePos[p] || ''}</td>{/each}<td></td><td></td></tr>
        </tbody>
      </table>
    </div>
    <p class="small muted">Matching is one-to-one, greedy by smallest time difference within ±{app.tolMs} ms. Clinch labels match a detected clinch if they fall inside its span. With a single sensor, strikes from the other hand are only seen through body motion, so expect lower recall for them.</p>
  </section>
{/if}

<style>
  .empty { display: grid; gap: 0.5rem; }
  .tolbar { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; }
  .tol { display: flex; gap: 0.6rem; align-items: center; }
  .tol input { width: 200px; }
  .hook { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(260px, 100%), 1fr)); gap: 1rem; align-items: center; border-color: rgba(251, 146, 60, 0.5); background: linear-gradient(135deg, rgba(251, 146, 60, 0.12), rgba(19, 26, 40, 0.9) 60%); }
  .hook .lab { color: #fed7aa; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; display: flex; gap: 0.4rem; align-items: center; }
  .big { font-size: 3rem; font-weight: 800; letter-spacing: -0.03em; color: #ffedd5; line-height: 1.1; }
  .ref { display: grid; gap: 0.2rem; padding: 0.7rem 0.8rem; border-left: 3px solid rgba(251, 146, 60, 0.6); background: rgba(0, 0, 0, 0.2); border-radius: 0 10px 10px 0; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.75rem; }
  .recall { display: grid; gap: 0.45rem; }
  .rrow { display: grid; grid-template-columns: minmax(9rem, 13rem) 1fr 3.2rem minmax(7rem, auto); gap: 0.6rem; align-items: center; font-size: 0.86rem; padding: 0.2rem 0.3rem; border-radius: 8px; }
  .rrow.hookrow { background: rgba(251, 146, 60, 0.08); outline: 1px solid rgba(251, 146, 60, 0.3); }
  .name { display: flex; gap: 0.4rem; align-items: center; }
  .track { position: relative; height: 12px; background: #1b2436; border-radius: 6px; overflow: hidden; }
  .track > span { position: absolute; inset: 0 auto 0 0; border-radius: 6px; }
  .refband { position: absolute; top: 0; bottom: 0; left: 50%; width: 15%; background: repeating-linear-gradient(45deg, rgba(255,255,255,0.35) 0 2px, transparent 2px 5px); }
  .val { text-align: right; font-weight: 700; }
  .cm td, .cm th { padding: 0.35rem 0.5rem; }
  .cm .rowh { text-transform: none; letter-spacing: 0; font-size: 0.82rem; color: var(--text); position: sticky; left: 0; background: #121a29; }
  .cm tr.hookrow .rowh { color: #fed7aa; }
  .fprow td, .fprow th { border-top: 2px solid var(--line2); color: #fca5a5; }
  @media (max-width: 560px) { .rrow { grid-template-columns: 1fr 3rem; } .rrow .track { grid-column: 1 / -1; grid-row: 2; } .rrow .small { display: none; } }
</style>
