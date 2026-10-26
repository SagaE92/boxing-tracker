<script lang="ts">
  import { onMount } from 'svelte';
  import { app, TABS } from './lib/state.svelte';
  import { fmtTime } from './lib/stats';
  import Overview from './lib/components/Overview.svelte';
  import StrikesPage from './lib/components/StrikesPage.svelte';
  import SignalsPage from './lib/components/SignalsPage.svelte';
  import Trends from './lib/components/Trends.svelte';
  import Accuracy from './lib/components/Accuracy.svelte';
  import Live from './lib/components/Live.svelte';
  import About from './lib/components/About.svelte';
  import Athlete from './lib/components/athlete/Athlete.svelte';

  let dragging = $state(false);
  let picker: HTMLInputElement;
  let dragDepth = 0;
  const s = $derived(app.active);
  const j = $derived(s?.json);
  const synthetic = $derived(!!s?.demo || !!j?.generator.name.includes('synthetic'));
  const needsSession = $derived(!['trends', 'about', 'live'].includes(app.tab));
  const lab = $derived(app.mode === 'lab');

  function onFiles(list: FileList | null) {
    if (!list || !list.length) return;
    app.addFiles([...list].map((f) => ({ name: f.name, blob: f })));
  }
  onMount(() => {
    app.pickFiles = () => picker.click();
    const p = new URLSearchParams(location.search);
    const t = p.get('tab');
    if (t && TABS.some((x) => x.id === t)) app.tab = t as typeof app.tab;
    if (p.has('demo')) app.demo();
  });
  $effect(() => {
    const url = new URL(location.href);
    url.searchParams.delete('lab');
    url.searchParams.set('view', app.mode);
    if (app.mode === 'lab') url.searchParams.set('tab', app.tab); else url.searchParams.delete('tab');
    history.replaceState(null, '', url);
  });
</script>

<svelte:window
  ondragenter={(e) => { if (e.dataTransfer?.types.includes('Files')) { dragDepth++; dragging = true; } }}
  ondragleave={() => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) dragging = false; }}
  ondragover={(e) => e.preventDefault()}
  ondrop={(e) => { e.preventDefault(); dragDepth = 0; dragging = false; onFiles(e.dataTransfer?.files ?? null); }}
/>

<header class="top">
  <div class="brand">
    <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ff7a59" /><stop offset="1" stop-color="#e8461f" /></linearGradient></defs><rect width="32" height="32" rx="8" fill="url(#g)" /><path d="M5 19h5l3-9 4 14 3-8 2 3h5" stroke="#fff" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round" /></svg>
    <div><div class="name">Strike<span>Lab</span></div><div class="tag">open boxing &amp; kickboxing tracker</div></div>
  </div>
  <div class="mode" role="group" aria-label="View">
    <button aria-pressed={!lab} onclick={() => app.setMode('athlete')}>Athlete</button>
    <button aria-pressed={lab} onclick={() => app.setMode('lab')} title="Signals, strike table, accuracy, exports and data details">Lab</button>
  </div>
  <div class="actions" class:lab-actions={lab}>
    {#if lab}
      {#if app.sessions.length}
        <select class="sess" aria-label="Active session" value={s?.key} onchange={(e) => app.select((e.currentTarget as HTMLSelectElement).value)}>
          {#each app.sessions as x (x.key)}<option value={x.key}>{x.name}{x.json ? ` · ${x.json.rounds.filter((r) => r.kind === 'round').length} rounds${x.raw ? '' : ' (no raw)'}` : ' (raw only)'}</option>{/each}
        </select>
      {/if}
      <button class="btn" onclick={() => picker.click()}>⤒ Load files</button>
      <button class="btn primary" onclick={() => app.demo()}>Demo session</button>
    {:else}
      {#if app.sessions.length}<button class="btn primary sm open" aria-label="Open session" onclick={() => picker.click()}>Open<span class="wide">&nbsp;session</span></button>{/if}
    {/if}
    <input bind:this={picker} type="file" multiple accept=".csv,.json,.gz" class="sr-only" aria-label="Choose session files" onchange={(e) => { onFiles((e.currentTarget as HTMLInputElement).files); (e.currentTarget as HTMLInputElement).value = ''; }} />
  </div>
</header>

{#if lab}
<nav class="tabs" aria-label="Views">
  {#each TABS as t (t.id)}
    <button class="tab" aria-current={app.tab === t.id ? 'page' : undefined} onclick={() => (app.tab = t.id)}>{t.label}</button>
  {/each}
</nav>
{/if}

<main class:athlete={!lab}>
  {#if app.loading}<div class="alert info" role="status"><span class="ico">…</span><span>{lab ? app.loading : 'Opening session…'}</span></div>{/if}
  {#if !lab && app.errors.length}
    <div class="alert warn" role="alert">
      <span class="ico">!</span>
      <span>Some files couldn't be opened. <button class="linkbtn" onclick={() => app.setMode('lab')}>See details in Lab</button></span>
      <button class="btn sm ghost" style="margin-left:auto" onclick={() => (app.errors = [])} aria-label="Dismiss">✕</button>
    </div>
  {/if}
  {#if !lab}
    <Athlete />
  {:else}
  {#if app.errors.length}
    <div class="alert bad" role="alert">
      <span class="ico">!</span>
      <div><b>Some files could not be loaded</b><ul class="errs">{#each app.errors as e (e)}<li>{e}</li>{/each}</ul></div>
      <button class="btn sm ghost" style="margin-left:auto" onclick={() => (app.errors = [])} aria-label="Dismiss errors">✕</button>
    </div>
  {/if}

  {#if s && needsSession}
    <section class="meta card">
      <div class="m1">
        <h1>{s.name}</h1>
        {#if synthetic}<span class="badge mid" title="Bundled demo: synthetic recording{j ? `, processed by ${j.generator.name}` : ''}">demo · synthetic recording</span>{/if}
        {#if !j}<span class="badge info">raw only</span>{/if}
        {#if s.labels}<span class="badge hi">{s.labels.length} video labels</span>{/if}
      </div>
      <div class="m2 small">
        {#if j}
          <span>{new Date(j.session.start_time_iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</span>
          <span>{fmtTime(j.session.duration_s)} total</span>
          {#if j.session.devices && j.session.devices.length > 1}
            <span><b>Sensors:</b> {j.session.devices.map((d) => `${d.hand ?? '?'} (${d.wrist ?? '?'}) ${d.device_id}`).join(' + ')}{j.session.sensor_mount ? `, ${j.session.sensor_mount.replace('_', ' ')}` : ''}</span>
            <span class="dim" title="Device clocks mapped to host time: offset of each sensor's first sample and fitted drift">clock: {j.session.devices.map((d) => d.clock ? `${d.hand} ${d.clock.offset_s >= 0 ? '+' : ''}${d.clock.offset_s.toFixed(3)} s, ${d.clock.skew_ppm.toFixed(1)} ppm${d.clock.residual_ms != null ? `, ±${d.clock.residual_ms} ms` : ''} (${d.clock.source})` : `${d.hand} n/a`).join(' · ')}</span>
          {:else}
            <span><b>Sensor:</b> {j.session.hand ?? '?'} hand ({j.session.hand_worn ?? '?'}){j.session.sensor_mount ? `, ${j.session.sensor_mount.replace('_', ' ')}` : ''}</span>
          {/if}
          <span><b>Stance:</b> {j.session.stance ?? 'unknown'}</span>
          <span>{j.session.sample_rate_hz} Hz · ±{j.session.accel_range_g} g · ±{j.session.gyro_range_dps} °/s</span>
          <span class="dim">detector: {j.detector_params.threshold_g} g / {j.detector_params.refractory_ms} ms / ±{j.detector_params.window_ms} ms · {j.generator.name.split(' ')[0]} {j.generator.version} · schema {j.schema_version}</span>
        {:else if s.raw}
          <span>{s.raw.n.toLocaleString()} samples · {fmtTime(s.raw.t[s.raw.n - 1])}</span>
        {/if}
      </div>
      {#if s.warnings.length}
        <details class="small warns"><summary>{s.warnings.length} loader note(s)</summary><ul>{#each s.warnings as w (w)}<li>{w}</li>{/each}</ul></details>
      {/if}
    </section>
  {/if}

  {#if !s && needsSession}
    <section class="landing card">
      <h1>Review every strike. Trust nothing you can't check.</h1>
      <p class="muted">Drop the files from a session: the raw IMU CSV from the BLE logger, the detector's <span class="mono">session.json</span>, and optionally a video-labels CSV. Add several sessions for trends. Everything stays in your browser.</p>
      <div class="drop" role="button" tabindex="0" onclick={() => picker.click()} onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') picker.click(); }}>
        <div class="big">Drop files here</div>
        <div class="small muted">or click to choose · <span class="mono">*_raw.csv[.gz]</span>, <span class="mono">*_session.json</span>, <span class="mono">*_labels.csv</span></div>
      </div>
      <button class="btn primary" onclick={() => app.demo()}>Try the demo session</button>
    </section>
  {:else if app.tab === 'overview' && s}
    <Overview />
  {:else if app.tab === 'signals' && s}
    <SignalsPage />
  {:else if app.tab === 'strikes' && s}
    {#if s.json}<StrikesPage />{:else}<div class="card"><p class="muted">Strikes need the session.json from analysis/detector.py.</p></div>{/if}
  {:else if app.tab === 'accuracy' && s}
    <Accuracy />
  {:else if app.tab === 'trends'}
    <Trends />
  {:else if app.tab === 'live'}
    <Live />
  {:else if app.tab === 'about'}
    <About />
  {/if}
  {/if}
</main>

<footer class="small dim">
  {#if lab}Peak g is wrist acceleration, not force. Speeds are estimates. Clipped peaks (≥) are lower bounds.{:else}Speeds are estimates. Impact is a score against your own usual (100), from wrist acceleration.{/if} · Open source · <a href="https://github.com/SagaE92/boxing-tracker">github.com/SagaE92/boxing-tracker</a>
</footer>

{#if dragging}
  <div class="overlay" aria-hidden="true"><div>Drop session files to load</div></div>
{/if}

<style>
  .top { position: sticky; top: 0; z-index: 20; display: flex; align-items: center; justify-content: space-between; gap: 0.8rem; padding: 0.7rem clamp(0.8rem, 3vw, 1.6rem); background: rgba(11, 15, 23, 0.85); backdrop-filter: blur(10px); border-bottom: 1px solid var(--line); flex-wrap: wrap; }
  .brand { display: flex; align-items: center; gap: 0.6rem; }
  .name { font-weight: 800; font-size: 1.15rem; letter-spacing: -0.02em; }
  .name span { color: var(--accent); }
  .tag { font-size: 0.72rem; color: var(--dim); }
  .actions { display: flex; gap: 0.45rem; align-items: center; flex-wrap: wrap; }
  .mode { display: inline-flex; padding: 3px; border-radius: 11px; background: #0f1625; border: 1px solid var(--line2); margin-right: auto; margin-left: 0.4rem; }
  .mode button { border: 0; background: none; color: var(--muted); font-weight: 650; font-size: 0.84rem; padding: 0.38rem 0.85rem; border-radius: 8px; cursor: pointer; }
  .mode button[aria-pressed='true'] { background: #24324d; color: var(--text); box-shadow: 0 1px 0 rgba(255, 255, 255, 0.05) inset; }
  .mode button:focus-visible { outline: 2px solid var(--accent2); outline-offset: 1px; }
  main.athlete { max-width: 1100px; }
  .linkbtn { background: none; border: 0; padding: 0; color: #7cc4ff; cursor: pointer; text-decoration: underline; font: inherit; }
  .sess { max-width: 220px; }
  .tabs { display: flex; gap: 0.2rem; padding: 0.5rem clamp(0.8rem, 3vw, 1.6rem) 0; overflow-x: auto; border-bottom: 1px solid var(--line); scrollbar-width: none; }
  .tab { background: none; border: 0; padding: 0.6rem 0.85rem; color: var(--muted); font-weight: 600; font-size: 0.88rem; cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; border-radius: 8px 8px 0 0; }
  .tab:hover { color: var(--text); background: rgba(255, 255, 255, 0.03); }
  .tab[aria-current='page'] { color: var(--text); border-bottom-color: var(--accent); }
  main { padding: 1rem clamp(0.6rem, 3vw, 1.6rem) 2rem; display: grid; gap: 0.9rem; max-width: 1560px; margin: 0 auto; }
  .meta { display: grid; gap: 0.35rem; padding: 0.8rem 1rem; }
  .m1 { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; }
  .m1 h1 { font-size: 1.2rem; font-weight: 750; }
  .m2 { display: flex; gap: 0.35rem 1.1rem; flex-wrap: wrap; color: var(--muted); }
  .m2 b { color: var(--text); font-weight: 600; }
  .warns summary { cursor: pointer; color: var(--warn); }
  .errs { margin: 0.3rem 0 0; padding-left: 1.1rem; }
  .landing { text-align: center; padding: clamp(1.5rem, 5vw, 3.5rem) 1.2rem; display: grid; gap: 1rem; justify-items: center; }
  .landing h1 { font-size: clamp(1.4rem, 4vw, 2.3rem); font-weight: 800; letter-spacing: -0.03em; max-width: 22ch; }
  .landing p { max-width: 62ch; margin: 0; }
  .drop { border: 2px dashed var(--line2); border-radius: 16px; padding: 2rem; width: min(560px, 100%); cursor: pointer; transition: border-color 0.15s, background 0.15s; }
  .drop:hover, .drop:focus-visible { border-color: var(--accent); background: rgba(255, 90, 54, 0.05); outline: none; }
  .drop .big { font-size: 1.15rem; font-weight: 700; margin-bottom: 0.3rem; }
  footer { text-align: center; padding: 1rem 1rem 2rem; }
  .overlay { position: fixed; inset: 0; z-index: 100; background: rgba(11, 15, 23, 0.8); display: grid; place-items: center; pointer-events: none; }
  .overlay div { border: 3px dashed var(--accent); border-radius: 20px; padding: 3rem 4rem; font-size: 1.4rem; font-weight: 700; background: rgba(255, 90, 54, 0.08); }
  @media (max-width: 560px) {
    .tag { display: none; }
    .mode { margin-left: 0; }
    .lab-actions { width: 100%; }
    .wide { display: none; }
    .mode button { padding: 0.36rem 0.7rem; }
    .actions .btn { flex: 1; justify-content: center; }
    .sess { max-width: none; width: 100%; }
  }
</style>
