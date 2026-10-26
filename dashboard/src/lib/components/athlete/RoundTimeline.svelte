<script lang="ts">
  // One round's strikes over time: stick height = impact, colour = strike type, diamonds = kicks,
  // shaded bands = combos. Plus strikes per minute.
  import { COMBO_GAP_MS, FRIENDLY_COLOR, friendly, isKick, isPunch, sideOf, type AthleteRound } from '../../athlete';
  import { combos, fmtTime } from '../../stats';
  let { round, stance, bothHands }: { round: AthleteRound; stance: string | null; bothHands: boolean } = $props();
  let w = $state(340);
  const H = 136, pad = { l: 8, r: 8, t: 10, b: 30 };
  const ev = $derived(round.events.filter((e) => isPunch(e) || isKick(e)));
  const maxImp = $derived(Math.max(8, ...ev.filter(isPunch).map((e) => e.peak_g)));
  const X = (t: number) => pad.l + ((t - round.tStart) / round.durS) * (w - pad.l - pad.r);
  const Y = (g: number) => H - pad.b - (g / maxImp) * (H - pad.t - pad.b);
  const bands = $derived(combos(round.events, COMBO_GAP_MS).filter((c) => c.events.length >= 2));
  // whole minutes; a few seconds over (detected round edges) go into the last minute
  const nMin = $derived(Math.max(1, Math.floor(round.durS / 60 + 0.15)));
  const minutes = $derived(Array.from({ length: nMin }, (_, m) => m));
  const perMinute = $derived(minutes.map((m) => ev.filter((e) => { const t = e.t_peak_s - round.tStart; return t >= m * 60 && (m === nMin - 1 || t < (m + 1) * 60); }).length));
  const present = $derived([...new Set(ev.map((e) => friendly(e.type)!))]);
</script>

<div class="rt" bind:clientWidth={w}>
  <svg width={w} height={H} role="img" aria-label={`Round ${round.number} strike timeline`}>
    {#each minutes as m (m)}
      <line x1={X(round.tStart + m * 60)} x2={X(round.tStart + m * 60)} y1={pad.t} y2={H - pad.b} stroke="#223049" stroke-dasharray="3 4" />
      <text x={X(round.tStart + m * 60)} y={H - 6} font-size="10.5" fill="#6f7d96" text-anchor={m === 0 ? 'start' : 'middle'}>{m}:00</text>
    {/each}
    {#if round.durS - nMin * 60 > 20 || nMin * 60 - round.durS > 20}<text x={w - pad.r} y={H - 6} font-size="10.5" fill="#6f7d96" text-anchor="end">{fmtTime(round.durS)}</text>{/if}
    {#each bands as c, i (i)}
      <rect x={X(c.events[0].t_peak_s) - 2} y={H - pad.b + 3} width={Math.max(4, X(c.events[c.events.length - 1].t_peak_s) - X(c.events[0].t_peak_s) + 4)} height="4" fill="#ffb020" opacity="0.85" rx="2" />
    {/each}
    <line x1={pad.l} x2={w - pad.r} y1={H - pad.b} y2={H - pad.b} stroke="#2c3b59" />
    {#each ev as e (e.id)}
      {@const c = FRIENDLY_COLOR[friendly(e.type)!]}
      {#if isKick(e)}
        <rect x={X(e.t_peak_s) - 4.5} y={pad.t + 2} width="9" height="9" transform={`rotate(45 ${X(e.t_peak_s)} ${pad.t + 6.5})`} fill={c}><title>Kick · {fmtTime(e.t_peak_s - round.tStart)}</title></rect>
      {:else}
        <line x1={X(e.t_peak_s)} x2={X(e.t_peak_s)} y1={H - pad.b} y2={Y(e.peak_g)} stroke={c} stroke-width="2.2" stroke-linecap="round" opacity={bothHands && sideOf(e, stance) === 'lead' ? 0.75 : 1}><title>{friendly(e.type)}{bothHands ? ` · ${sideOf(e, stance)} hand` : ''} · {fmtTime(e.t_peak_s - round.tStart)} · impact {e.peak_g.toFixed(1)}</title></line>
      {/if}
    {/each}
  </svg>
  <div class="leg">
    {#each present as p (p)}<span><i style="background:{FRIENDLY_COLOR[p]}"></i>{p}</span>{/each}
    <span><i class="band"></i>Combo</span>
  </div>
  <div class="mins" aria-label="Strikes per minute">
    {#each perMinute as n, m (m)}<div><span class="dim">Min {m + 1}</span><b class="num">{n}</b></div>{/each}
  </div>
  <p class="small dim cap">Each line is a strike: taller = more impact. Diamonds are kicks, the amber marks under the axis are combos.</p>
</div>

<style>
  .rt { width: 100%; min-width: 0; }
  svg { display: block; }
  .leg { display: flex; flex-wrap: wrap; gap: 0.3rem 0.8rem; font-size: 0.76rem; color: var(--muted); margin-top: 0.35rem; }
  .leg i { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 0.3rem; vertical-align: 0; }
  .leg i.band { background: #ffb020; height: 4px; width: 12px; vertical-align: 2px; }
  .mins { display: grid; grid-template-columns: repeat(auto-fit, minmax(64px, 1fr)); gap: 0.4rem; margin-top: 0.6rem; }
  .mins div { background: #0f1625; border: 1px solid var(--line); border-radius: 10px; padding: 0.35rem 0.5rem; display: flex; flex-direction: column; font-size: 0.74rem; }
  .mins b { font-size: 1.05rem; }
  .cap { margin: 0.5rem 0 0; }
</style>
