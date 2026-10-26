<script lang="ts">
  import { app } from '../../state.svelte';
  import { athleteRounds, finishCompare, finishNotes, handLine, hasBothHands, mixOf, sessionOverview, takeaway, topCombos, FRIENDLY_COLOR, type AthleteRound } from '../../athlete';
  import { ATIPS } from '../../athlete-tips';
  import { dataQuality, fmtTime } from '../../stats';
  import Tip from '../Tip.svelte';
  import LineChart from '../LineChart.svelte';
  import SplitBar from './SplitBar.svelte';
  import RoundTimeline from './RoundTimeline.svelte';

  const s = $derived(app.active);
  const j = $derived(s?.json);
  const rs = $derived(j ? athleteRounds(j) : []);
  const fin = $derived(finishCompare(rs));
  const both = $derived(j ? hasBothHands(j) : false);
  const total = $derived(rs.reduce((a, r) => a + r.strikes, 0));
  const kicks = $derived(rs.reduce((a, r) => a + r.kicks, 0));
  const lead = $derived(rs.reduce((a, r) => a + r.lead, 0));
  const rear = $derived(rs.reduce((a, r) => a + r.rear, 0));
  const act = $derived(rs.reduce((a, r) => a + r.durS, 0));
  const pace = $derived(act > 0 ? total / (act / 60) : 0);
  const best = $derived(rs.find((r) => r.best) ?? null);
  const take = $derived(takeaway(rs, fin));
  const notes = $derived(finishNotes(fin, both));
  const hline = $derived(both ? handLine(rs, fin) : null);
  const allEv = $derived(rs.flatMap((r) => r.events));
  const mix = $derived(mixOf(allEv).sort((a, b) => b.count - a.count));
  const tops = $derived(topCombos(allEv, 5));
  const maxStrikes = $derived(Math.max(1, ...rs.map((r) => r.strikes)));
  const dq = $derived(j ? dataQuality(j, s?.raw, j.punches) : null);
  const dqGood = $derived(!!dq && !dq.issues.some((i) => i.level === 'bad'));
  const roundLen = $derived(rs.length ? rs.reduce((a, r) => a + r.durS, 0) / rs.length : 0);
  const history = $derived(app.sessions.map(sessionOverview).filter((x) => x !== null).sort((a, b) => b!.date.getTime() - a!.date.getTime()) as NonNullable<ReturnType<typeof sessionOverview>>[]);
  const histAsc = $derived([...history].reverse());
  const dateFmt = (d: Date, long = false) => d.toLocaleDateString(undefined, long ? { weekday: 'long', day: 'numeric', month: 'long' } : { day: 'numeric', month: 'short' });
  const f1 = (v: number | null | undefined) => (v === null || v === undefined || !Number.isFinite(v) ? '—' : v.toFixed(1));
  const rel = (v: number | null, base: number | null) => (v === null || base === null || !base ? null : (v / base) * 100);
  const trend = $derived(fin ? [
    { name: 'Output', color: '#ff7a59', values: rs.map((r) => rel(r.strikes, fin.first.strikesPerRound)) },
    { name: 'Speed', color: '#38bdf8', values: rs.map((r) => rel(r.speed, fin.first.speed)) },
    { name: 'Impact', color: '#c084fc', values: rs.map((r) => rel(r.impact, fin.first.impact)) },
  ] : []);
  function toggle(r: AthleteRound) {
    app.openRound = app.openRound === r.number ? null : r.number;
  }
  function chg(v: number | null, digits = 0, unit = '%') {
    if (v === null || !Number.isFinite(v)) return { t: '—', cls: '' };
    const r = +v.toFixed(digits);
    return { t: `${r > 0 ? '+' : r < 0 ? '−' : '±'}${Math.abs(r).toFixed(digits)}${unit}`, cls: r <= -5 ? 'down' : r >= 5 ? 'up' : '' };
  }
  /** "3 min" when the detected round length is within ~6 s of a whole minute, else m:ss. */
  const roundLenTxt = (sec: number) => (Math.abs(sec / 60 - Math.round(sec / 60)) < 0.1 && sec >= 50 ? `${Math.round(sec / 60)} min` : fmtTime(sec));
  const pctTxt = (v: number) => `${Math.round(v * 100)}%`;
</script>

{#if !s}
  <section class="hero card">
    <div class="glow" aria-hidden="true"></div>
    <h1>Your rounds, at a glance.</h1>
    <p class="muted">After training, open your session to see every round: how many strikes, how fast, your best round, and how you held up at the end.</p>
    <div class="cta">
      <button class="btn primary big" onclick={() => app.pickFiles()}>Open session</button>
      <button class="btn big" disabled aria-disabled="true" title="Coming soon">⦿ Sync from tracker <span class="soon">soon</span></button>
    </div>
    <button class="btn ghost" onclick={() => app.demo()}>See a demo session →</button>
    <p class="small dim">Sync over Bluetooth straight from your wrist trackers is coming. Until then, open the session files you copied from the tracker app. Nothing leaves your device.</p>
  </section>
{:else if !j}
  <section class="card"><h2>This session isn't ready yet</h2><p class="muted">It still needs to be processed into rounds and strikes. Switch to <button class="linkbtn" onclick={() => app.setMode('lab')}>Lab</button> for details.</p></section>
{:else}
  <section class="head card" aria-label="Session summary">
    <div class="h1row">
      <div>
        <div class="date">{dateFmt(new Date(j.session.start_time_iso), true)} · {new Date(j.session.start_time_iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}</div>
        <h1>{rs.length} {rs.length === 1 ? 'round' : 'rounds'}{roundLen ? ` × ${roundLenTxt(roundLen)}` : ''}</h1>
      </div>
      <button class="dq {dqGood ? 'good' : 'check'}" onclick={() => app.showDataQuality()} title="Open the data details in Lab">Data quality: {dqGood ? 'good' : 'check'}</button>
    </div>
    <p class="take">{take}</p>
    <div class="kpis">
      <div class="kpi main"><span class="v num">{total}</span><span class="l">strikes <Tip text={ATIPS.strikes} /></span>{#if kicks}<span class="s">incl. {kicks} {kicks === 1 ? 'kick' : 'kicks'}</span>{/if}</div>
      <div class="kpi"><span class="v num">{pace.toFixed(0)}</span><span class="l">per min <Tip text={ATIPS.pace} /></span><span class="s">average pace</span></div>
      <div class="kpi"><span class="v num">{best ? `R${best.number}` : '—'}</span><span class="l">best round <Tip text={ATIPS.best} /></span>{#if best}<span class="s">{best.strikes} strikes</span>{/if}</div>
      <div class="kpi"><span class="v num">{fmtTime(j.session.duration_s)}</span><span class="l">duration</span><span class="s">incl. rests</span></div>
    </div>
    {#if both}
      <div class="hands">
        <div class="hl">Hand balance <Tip text={ATIPS.hands} /></div>
        <SplitBar {lead} {rear} size="lg" labels />
        {#if hline}<p class="small muted hline">{hline}</p>{/if}
      </div>
    {/if}
  </section>

  <section class="card rounds" aria-label="Round by round">
    <div class="card-h"><h2>Round by round</h2><span class="sub">tap a round for its timeline</span></div>
    <ol class="rlist">
      {#each rs as r (r.number)}
        <li class:best={r.best} class:weak={r.weakest} class:open={app.openRound === r.number}>
          <button class="rrow" aria-expanded={app.openRound === r.number} aria-controls={`round-${r.number}`} onclick={() => toggle(r)}>
            <span class="rn">R{r.number}</span>
            <span class="rmain">
              <span class="rtop">
                <b class="num big">{r.strikes}</b><span class="dim">strikes</span>
                {#if r.best}<span class="tag best">Best</span>{/if}{#if r.weakest}<span class="tag weak">Lowest</span>{/if}
                <span class="chev" aria-hidden="true">{app.openRound === r.number ? '▴' : '▾'}</span>
              </span>
              <span class="bar"><span style="width:{(r.strikes / maxStrikes) * 100}%"></span></span>
              <span class="metrics">
                <span><b class="num">{r.perMin.toFixed(0)}</b><i>/min</i></span>
                <span><b class="num">{f1(r.speed)}</b><i>m/s</i></span>
                <span><b class="num">{f1(r.impact)}</b><i>impact</i></span>
                <span><b class="num">{r.combos}</b><i>combos</i></span>
              </span>
              <span class="rfoot">
                <span class="types">{#each r.top as t (t.label)}<span class="ty"><i style="background:{FRIENDLY_COLOR[t.label]}"></i>{t.label} <span class="num dim">{t.count}</span></span>{/each}</span>
                {#if both}<span class="mini"><SplitBar lead={r.lead} rear={r.rear} /></span>{/if}
              </span>
            </span>
          </button>
          {#if app.openRound === r.number}
            <div class="rdetail" id={`round-${r.number}`}>
              <RoundTimeline round={r} stance={j.session.stance} bothHands={both} />
              {#if both}<p class="small muted">Lead {r.lead} · Rear {r.rear} punches{r.kicks ? ` · ${r.kicks} ${r.kicks === 1 ? 'kick' : 'kicks'}` : ''}</p>{/if}
            </div>
          {/if}
        </li>
      {/each}
    </ol>
    <p class="small dim legend-note">Speed in m/s (estimate). Impact <Tip text={ATIPS.impact} /> · Combos <Tip text={ATIPS.combos} /></p>
  </section>

  <div class="two">
    <section class="card finish" aria-label="How you finished">
      <div class="card-h"><h2>How you finished <Tip text={ATIPS.finish} /></h2>{#if fin}<span class="sub">{fin.label}</span>{/if}</div>
      {#if fin}
        <table class="cmp">
          <thead><tr><th></th><th class="r">Early</th><th class="r">Late</th><th class="r">Change</th></tr></thead>
          <tbody>
            <tr><td>Strikes / round</td><td class="r num">{fin.first.strikesPerRound.toFixed(0)}</td><td class="r num">{fin.last.strikesPerRound.toFixed(0)}</td><td class="r num {chg(fin.change.volume).cls}">{chg(fin.change.volume).t}</td></tr>
            <tr><td>Speed (m/s)</td><td class="r num">{f1(fin.first.speed)}</td><td class="r num">{f1(fin.last.speed)}</td><td class="r num {chg(fin.change.speed).cls}">{chg(fin.change.speed).t}</td></tr>
            <tr><td>Impact</td><td class="r num">{f1(fin.first.impact)}</td><td class="r num">{f1(fin.last.impact)}</td><td class="r num {chg(fin.change.impact).cls}">{chg(fin.change.impact).t}</td></tr>
            <tr><td>Combos / round</td><td class="r num">{fin.first.combosPerRound.toFixed(0)}</td><td class="r num">{fin.last.combosPerRound.toFixed(0)}</td><td class="r num {chg(fin.change.combos).cls}">{chg(fin.change.combos).t}</td></tr>
            <tr><td>Kick share</td><td class="r num">{pctTxt(fin.first.kickShare)}</td><td class="r num">{pctTxt(fin.last.kickShare)}</td><td class="r num {fin.change.kickSharePts <= -1 ? 'down' : fin.change.kickSharePts >= 1 ? 'up' : ''}">{chg(fin.change.kickSharePts, 0, ' pts').t}</td></tr>
            {#if both && fin.first.leadShare !== null && fin.last.leadShare !== null}
              <tr><td>Rear hand share</td><td class="r num">{pctTxt(1 - fin.first.leadShare)}</td><td class="r num">{pctTxt(1 - fin.last.leadShare)}</td><td class="r num">{chg(-(fin.change.leadSharePts ?? 0), 0, ' pts').t}</td></tr>
            {/if}
          </tbody>
        </table>
        {#if both && fin.first.leadShare !== null && fin.last.leadShare !== null}
          <div class="hcmp">
            <div><span class="small dim">Early</span><SplitBar lead={fin.first.leadShare} rear={1 - fin.first.leadShare} /></div>
            <div><span class="small dim">Late</span><SplitBar lead={fin.last.leadShare} rear={1 - fin.last.leadShare} /></div>
          </div>
        {/if}
        {#if notes.length}<ul class="notes">{#each notes.slice(0, 4) as n (n)}<li>{n}</li>{/each}</ul>{/if}
        <h3 class="th">Every round vs your opening rounds</h3>
        <LineChart labels={rs.map((r) => `R${r.number}`)} series={trend} unit="%" decimals={0} height={170} ariaLabel="Output, speed and impact per round, as % of the opening rounds" />
        <p class="small dim">100% = your average over {fin.n === 1 ? 'the first round' : `the first ${fin.n} rounds`}.</p>
      {:else}
        <p class="muted">Finish comparison needs at least 2 rounds.</p>
      {/if}
    </section>

    <section class="card mixc" aria-label="Strike mix">
      <div class="card-h"><h2>Strike mix</h2><span class="sub">{total} strikes</span></div>
      <ul class="mix">
        {#each mix as m (m.label)}
          <li><span class="ml">{m.label}{#if m.label === 'Kick'} <Tip text={ATIPS.kicks} />{/if}</span><span class="mb"><span style="width:{m.share * 100}%;background:{FRIENDLY_COLOR[m.label]}"></span></span><span class="num mv">{m.count}</span><span class="num dim mp">{Math.round(m.share * 100)}%</span></li>
        {/each}
      </ul>
      <h3 class="th">Top combos <Tip text={ATIPS.combos} /></h3>
      {#if tops.length}
        <ol class="combos">{#each tops as c (c.seq)}<li><span>{c.seq}</span><b class="num">×{c.count}</b></li>{/each}</ol>
      {:else}<p class="muted small">No combos in this session.</p>{/if}
    </section>
  </div>

  <section class="card hist" aria-label="Session history">
    <div class="card-h"><h2>Session history</h2><span class="sub">{history.length} {history.length === 1 ? 'session' : 'sessions'}</span></div>
    <ul class="hlist">
      {#each history as h (h.key)}
        <li><button class:cur={h.key === s.key} onclick={() => { app.select(h.key); window.scrollTo({ top: 0, behavior: 'smooth' }); }}>
          <span class="hd"><b>{dateFmt(h.date)}</b><span class="dim small">{h.rounds} × {h.roundLenS ? roundLenTxt(h.roundLenS) : '—'}</span></span>
          <span class="hs"><b class="num">{h.strikes}</b><span class="dim small">strikes</span></span>
          <span class="hs"><b class="num">{h.perMin.toFixed(0)}</b><span class="dim small">/min</span></span>
          <span class="hs"><b class="num {h.lateDropPct !== null && h.lateDropPct <= -8 ? 'down' : ''}">{h.lateDropPct === null ? '—' : `${h.lateDropPct > 0 ? '+' : h.lateDropPct < 0 ? '−' : ''}${Math.abs(Math.round(h.lateDropPct))}%`}</b><span class="dim small">late</span></span>
        </button></li>
      {/each}
    </ul>
    {#if histAsc.length >= 2}
      <div class="htrend">
        <div><h3 class="th">Volume</h3><LineChart labels={histAsc.map((h) => dateFmt(h.date))} series={[{ name: 'Strikes per minute', color: '#ff7a59', values: histAsc.map((h) => h.perMin), trend: histAsc.length >= 3 }]} decimals={0} height={150} ariaLabel="Strikes per minute per session" /></div>
        <div><h3 class="th">Late-round drop-off</h3><LineChart labels={histAsc.map((h) => dateFmt(h.date))} series={[{ name: 'Output change, last vs first rounds (%)', color: '#fbbf24', values: histAsc.map((h) => h.lateDropPct) }]} decimals={0} unit="%" height={150} ariaLabel="Late-round output change per session" /></div>
      </div>
      <p class="small dim">"Late" = output in your last rounds compared with your first rounds. Closer to 0 means you held your pace.</p>
    {/if}
  </section>
{/if}

<style>
  h1 { font-size: clamp(1.45rem, 5.5vw, 2rem); font-weight: 800; letter-spacing: -0.03em; }
  .hero { position: relative; overflow: hidden; display: grid; gap: 1rem; justify-items: center; text-align: center; padding: clamp(1.6rem, 6vw, 3.4rem) 1.2rem; }
  .hero p { max-width: 46ch; margin: 0; }
  .glow { position: absolute; inset: -40% -20% auto; height: 220px; background: radial-gradient(closest-side, rgba(255, 90, 54, 0.25), transparent); pointer-events: none; }
  .cta { display: flex; gap: 0.6rem; flex-wrap: wrap; justify-content: center; }
  .btn.big { padding: 0.8rem 1.2rem; font-size: 1rem; border-radius: 12px; }
  .soon { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.06em; background: #24324d; padding: 0.1rem 0.4rem; border-radius: 99px; color: var(--muted); }
  .linkbtn { background: none; border: 0; padding: 0; color: #7cc4ff; cursor: pointer; text-decoration: underline; }

  .head { display: grid; gap: 0.8rem; padding: 1.1rem 1.1rem 1.2rem; background: linear-gradient(160deg, rgba(255, 90, 54, 0.14), rgba(19, 26, 40, 0.9) 45%), var(--card); }
  .h1row { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.6rem; }
  .date { color: var(--muted); font-size: 0.85rem; font-weight: 550; margin-bottom: 0.15rem; }
  .dq { border-radius: 99px; padding: 0.28rem 0.6rem; font-size: 0.72rem; font-weight: 650; cursor: pointer; white-space: nowrap; border: 1px solid; background: transparent; }
  .dq.good { color: #6ee7b7; border-color: rgba(52, 211, 153, 0.4); }
  .dq.check { color: #fde68a; border-color: rgba(251, 191, 36, 0.5); }
  .take { margin: 0; font-size: 1.08rem; font-weight: 600; line-height: 1.4; color: #ffe1d8; }
  .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.5rem; }
  .kpi { display: flex; flex-direction: column; background: rgba(11, 15, 23, 0.45); border: 1px solid var(--line); border-radius: 12px; padding: 0.6rem 0.7rem; min-width: 0; }
  .kpi .v { font-size: 1.6rem; font-weight: 800; letter-spacing: -0.02em; line-height: 1.1; }
  .kpi.main .v { color: #ffd2c6; }
  .kpi .l { display: flex; align-items: center; gap: 0.3rem; font-size: 0.72rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 650; }
  .kpi .s { font-size: 0.74rem; color: var(--dim); }
  .hands { display: grid; gap: 0.2rem; }
  .hl { display: flex; align-items: center; gap: 0.35rem; font-size: 0.72rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 650; margin-bottom: 0.2rem; }
  .hline { margin: 0.3rem 0 0; color: #d6def0; }

  .rlist { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.45rem; }
  .rlist li { border: 1px solid var(--line); border-radius: 12px; background: #111827; overflow: hidden; }
  .rlist li.best { border-color: rgba(52, 211, 153, 0.45); }
  .rlist li.weak { border-color: rgba(251, 191, 36, 0.4); }
  .rlist li.open { background: #131c2e; }
  .rrow { display: flex; gap: 0.7rem; width: 100%; text-align: left; background: none; border: 0; padding: 0.65rem 0.75rem; cursor: pointer; color: inherit; }
  .rrow:hover { background: rgba(255, 255, 255, 0.025); }
  .rrow:focus-visible { outline: 2px solid var(--accent2); outline-offset: -2px; }
  .rn { flex: none; width: 2.3rem; height: 2.3rem; border-radius: 10px; display: grid; place-items: center; background: #1b2539; font-weight: 800; font-size: 0.9rem; color: #c9d4e8; }
  .best .rn { background: rgba(52, 211, 153, 0.16); color: #6ee7b7; }
  .weak .rn { background: rgba(251, 191, 36, 0.13); color: #fde68a; }
  .rmain { flex: 1; min-width: 0; display: grid; gap: 0.35rem; }
  .rtop { display: flex; align-items: baseline; gap: 0.4rem; }
  .rtop .big { font-size: 1.3rem; font-weight: 800; line-height: 1; }
  .tag { font-size: 0.66rem; font-weight: 750; text-transform: uppercase; letter-spacing: 0.06em; padding: 0.12rem 0.42rem; border-radius: 99px; align-self: center; }
  .tag.best { background: rgba(52, 211, 153, 0.15); color: #6ee7b7; }
  .tag.weak { background: rgba(251, 191, 36, 0.14); color: #fde68a; }
  .chev { margin-left: auto; color: var(--dim); font-size: 0.85rem; }
  .bar { height: 6px; border-radius: 99px; background: #1c2538; overflow: hidden; }
  .bar span { display: block; height: 100%; border-radius: 99px; background: linear-gradient(90deg, #ff5a36, #ffb020); }
  .weak .bar span { background: linear-gradient(90deg, #a16207, #fbbf24); }
  .best .bar span { background: linear-gradient(90deg, #059669, #34d399); }
  .metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.3rem; }
  .metrics span { display: flex; align-items: baseline; gap: 0.22rem; min-width: 0; }
  .metrics b { font-size: 0.95rem; font-weight: 700; }
  .metrics i { font-style: normal; font-size: 0.72rem; color: var(--dim); white-space: nowrap; }
  .rfoot { display: flex; align-items: center; gap: 0.6rem; }
  .types { display: flex; gap: 0.3rem 0.65rem; flex-wrap: wrap; font-size: 0.76rem; color: var(--muted); flex: 1; min-width: 0; }
  .ty i { display: inline-block; width: 7px; height: 7px; border-radius: 2px; margin-right: 0.25rem; }
  .mini { width: 70px; flex: none; }
  .rdetail { padding: 0.2rem 0.8rem 0.8rem; border-top: 1px solid var(--line); }
  .rdetail p { margin: 0.4rem 0 0; }
  .legend-note { margin: 0.7rem 0 0; display: flex; gap: 0.35rem; align-items: center; flex-wrap: wrap; }

  .two { display: grid; gap: 0.9rem; grid-template-columns: 1fr; }
  .cmp { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
  .cmp th { font-size: 0.72rem; color: var(--dim); font-weight: 650; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.2rem 0.3rem; }
  .cmp td { padding: 0.42rem 0.3rem; border-top: 1px solid var(--line); }
  .r { text-align: right; }
  .down { color: #fca5a5; }
  .up { color: #6ee7b7; }
  .hcmp { display: grid; grid-template-columns: 1fr 1fr; gap: 0.8rem; margin-top: 0.8rem; }
  .hcmp div { display: grid; gap: 0.25rem; }
  .notes { margin: 0.8rem 0 0.2rem; padding-left: 1.1rem; display: grid; gap: 0.35rem; color: #d6def0; font-size: 0.9rem; }
  .th { font-size: 0.8rem; color: var(--muted); font-weight: 650; text-transform: uppercase; letter-spacing: 0.05em; margin: 1rem 0 0.4rem; display: flex; align-items: center; gap: 0.35rem; }
  .finish p, .hist p { margin: 0.3rem 0 0; }
  .mix { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.5rem; }
  .mix li { display: grid; grid-template-columns: 8.2rem 1fr 2.6rem 2.4rem; align-items: center; gap: 0.5rem; font-size: 0.9rem; }
  .ml { display: flex; align-items: center; gap: 0.3rem; white-space: nowrap; }
  .mb { height: 8px; background: #1c2538; border-radius: 99px; overflow: hidden; }
  .mb span { display: block; height: 100%; border-radius: 99px; }
  .mv, .mp { text-align: right; }
  .combos { margin: 0; padding: 0; list-style: none; display: grid; gap: 0.35rem; counter-reset: c; }
  .combos li { display: flex; justify-content: space-between; gap: 0.6rem; padding: 0.45rem 0.65rem; border: 1px solid var(--line); border-radius: 10px; background: #111827; font-size: 0.9rem; }
  .combos b { color: var(--accent2); }
  .hlist { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.4rem; }
  .hlist button { width: 100%; display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr; gap: 0.4rem; align-items: center; text-align: left; border: 1px solid var(--line); border-radius: 12px; background: #111827; padding: 0.55rem 0.7rem; cursor: pointer; color: inherit; }
  .hlist button.cur { border-color: rgba(255, 90, 54, 0.55); background: rgba(255, 90, 54, 0.07); }
  .hlist button:hover { background: #151f33; }
  .hd, .hs { display: flex; flex-direction: column; min-width: 0; }
  .hs b { font-size: 1rem; }
  .htrend { display: grid; gap: 0.6rem; grid-template-columns: 1fr; }
  @media (min-width: 900px) {
    .rlist { grid-template-columns: 1fr 1fr; }
    .rlist li.open { grid-column: 1 / -1; }
  }
  @media (min-width: 760px) {
    .two { grid-template-columns: 1.15fr 1fr; align-items: start; }
    .htrend { grid-template-columns: 1fr 1fr; }
  }
  @media (max-width: 420px) {
    .kpis { grid-template-columns: repeat(2, 1fr); }
    .mix li { grid-template-columns: 7.4rem 1fr 2.2rem 2.2rem; font-size: 0.86rem; }
    .h1row { flex-wrap: wrap; }
  }
</style>
