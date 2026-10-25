<script lang="ts">
  import { OURS, ROWS, STUDY_2021, STUDY_2023 } from '../compare';
  const points = [
    { t: 'Open algorithm, tunable', d: 'The detector (analysis/detector.py) is open source. Threshold, refractory period and window are in every session.json and shown on the charts. You can see why each strike counted.' },
    { t: 'Your raw data, no lock-in', d: 'Full 416 Hz 6-axis data as CSV, with every sample flagged if it clipped. Sessions use a public, versioned JSON schema. No subscription, no account, no cloud.' },
    { t: 'Accuracy you can check', d: 'Label a session from phone video and the Accuracy tab shows precision, recall and a per-class confusion matrix. Hooks get the headline number, because they are what consumer trackers miss most.' },
    { t: 'Honest units', d: 'We report peak acceleration (g) and an estimated speed, never "power" or "force". No consumer tracker has a validated force measurement.' },
    { t: 'Saturation and data quality up front', d: 'Clipped strikes are marked "≥" because the true peak was higher. BLE gaps, sample-rate jitter, missing calibration and low confidence are flagged, not hidden.' },
    { t: 'Built for kickboxing', d: 'Lead/rear hooks and uppercuts, overhand and spinning backfist. Kick-like body motion and clinch are separate low-confidence categories that never inflate strike counts.' },
    { t: 'Size and battery first', d: 'Designed to sit inside hand wraps, with a ~1 week per charge target and a high-g IMU (LSM6DSV320X, up to ±320 g) planned for the custom board so hard shots stop clipping.' },
    { t: 'Public, offline dashboard', d: 'This page is static and works offline. Live view over Web Bluetooth works in Chrome/Edge on desktop and Android (not iOS Safari).' },
  ];
</script>

<section class="hero card">
  <h1>Built to be checked, not trusted</h1>
  <p>A small open tracker for kickboxers, plus this dashboard. Here is what we do differently and what independent research says about the trackers on sale today.</p>
</section>

<section class="grid pts">
  {#each points as p (p.t)}<div class="card pt"><h3>{p.t}</h3><p class="muted">{p.d}</p></div>{/each}
</section>

<section class="card">
  <div class="card-h"><h2>What independent studies found</h2></div>
  <ul class="ev">
    <li><b>Hooks are the hard case.</b> In a 2021 shadowboxing study against video (21 subjects), Corner and Hykso recognised about 83–96% of straight punches but only about 50–65% of hooks. <a href={STUDY_2021} target="_blank" rel="noopener">Omcirk et al. 2021 ↗</a></li>
    <li><b>No validated force.</b> Against a force plate and 500 fps motion capture (20 subjects), no tracker metric was strongly correlated with real velocity or force; the authors advise against using any of them for force. Best velocity error: Hykso, MAPE 21%. <a href={STUDY_2023} target="_blank" rel="noopener">Omcirk et al. 2023 ↗</a></li>
    <li><b>Kicks and clinch.</b> Of the established brands, only FightCamp tracks kicks, and only with four trackers plus its Console. We found no consumer tracker that tracks clinch work. <a href="https://fightcamp.zendesk.com/hc/en-us/articles/30452375440027-FightCamp-Kicktracking" target="_blank" rel="noopener">FightCamp help ↗</a></li>
  </ul>
  <p class="small dim">Study figures come from different protocols and athletes than ours; treat them as context, not a head-to-head result.</p>
</section>

<section class="card">
  <div class="card-h"><h2>Comparison</h2><span class="sub">"vendor claim" = from the maker's own site or app; not independently verified</span></div>
  <div class="scroll-x">
    <table class="cmp">
      <thead><tr><th>Product</th><th>Placement / size</th><th>Battery</th><th>Kicks</th><th>Data access</th><th>Subscription</th><th>Independent evidence</th><th>Sources</th></tr></thead>
      <tbody>
        {#each [...ROWS, OURS] as r (r.product)}
          <tr class:ours={r === OURS}>
            <th scope="row">{r.product}</th><td>{r.placement}</td><td>{r.battery}</td><td>{r.kicks}</td><td>{r.data}</td><td>{r.subscription}</td><td>{r.evidence}</td>
            <td class="src">{#each r.sources as s (s.href)}<a href={s.href} target="_blank" rel="noopener">{s.label}</a>{/each}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  <p class="small dim">Compiled October 2026. Products and prices change; follow the links for current details. No affiliation with any brand listed.</p>
</section>

<style>
  .hero { padding: 1.6rem 1.4rem; background: radial-gradient(600px 200px at 0% 0%, rgba(255, 90, 54, 0.18), transparent 70%), linear-gradient(180deg, var(--card), #111827); }
  .hero h1 { font-size: clamp(1.5rem, 3.5vw, 2.2rem); font-weight: 800; letter-spacing: -0.03em; }
  .hero p { color: var(--muted); max-width: 60ch; margin: 0.5rem 0 0; }
  .pts { grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr)); }
  .pt h3 { color: #ffd2c6; margin-bottom: 0.3rem; }
  .pt p { margin: 0; font-size: 0.88rem; }
  .ev { margin: 0; padding-left: 1.1rem; display: grid; gap: 0.6rem; }
  .cmp td, .cmp th { white-space: normal; vertical-align: top; min-width: 120px; font-size: 0.82rem; }
  .cmp tbody th { color: var(--text); text-transform: none; letter-spacing: 0; font-size: 0.86rem; position: static; }
  .cmp tr.ours { background: rgba(255, 90, 54, 0.07); }
  .src { display: flex; flex-direction: column; gap: 0.2rem; min-width: 110px; }
</style>
