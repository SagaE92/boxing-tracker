<script lang="ts">
  // Small multi-series line chart in SVG with optional linear trendlines.
  import { linfit } from '../stats';
  type S = { name: string; color: string; values: (number | null)[]; trend?: boolean; dashed?: boolean };
  let { labels, series, height = 180, unit = '', decimals = 1, yMin = null, ariaLabel = 'line chart' }: { labels: string[]; series: S[]; height?: number; unit?: string; decimals?: number; yMin?: number | null; ariaLabel?: string } = $props();
  let w = $state(320);
  const pad = { t: 14, b: 26, l: 40, r: 26 };
  const all = $derived(series.flatMap((s) => s.values.filter((v): v is number => v !== null)));
  const lo = $derived(yMin ?? (all.length ? Math.min(...all) * 0.9 : 0));
  const hi = $derived(all.length ? Math.max(...all) * 1.06 : 1);
  const X = (i: number) => pad.l + (labels.length <= 1 ? (w - pad.l - pad.r) / 2 : (i * (w - pad.l - pad.r)) / (labels.length - 1));
  const Y = (v: number) => height - pad.b - ((v - lo) / (hi - lo || 1)) * (height - pad.t - pad.b);
  const ticks = $derived([0, 0.5, 1].map((f) => lo + f * (hi - lo)));
  function path(vals: (number | null)[]) {
    let d = '', pen = false;
    vals.forEach((v, i) => { if (v === null) { pen = false; return; } d += `${pen ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`; pen = true; });
    return d;
  }
  function trend(vals: (number | null)[]) {
    const xs: number[] = [], ys: number[] = [];
    vals.forEach((v, i) => { if (v !== null) { xs.push(i); ys.push(v); } });
    const f = linfit(xs, ys);
    if (!f) return '';
    const n = labels.length - 1;
    return `M${X(0)},${Y(f.a)}L${X(n)},${Y(f.a + f.b * n)}`;
  }
</script>

<div class="lc" bind:clientWidth={w}>
  <svg width={w} {height} role="img" aria-label={ariaLabel}>
    {#each ticks as t (t)}
      <line x1={pad.l} x2={w - pad.r} y1={Y(t)} y2={Y(t)} stroke="#223049" stroke-dasharray="3 4" />
      <text x={pad.l - 6} y={Y(t) + 4} text-anchor="end" font-size="10.5" fill="#6f7d96" class="num">{t.toFixed(decimals)}</text>
    {/each}
    {#each labels as l, i (i)}
      <text x={X(i)} y={height - 7} text-anchor="middle" font-size="10.5" fill="#9aa8bf">{l}</text>
    {/each}
    {#each series as s (s.name)}
      {#if s.trend}<path d={trend(s.values)} stroke={s.color} stroke-width="1.5" stroke-dasharray="5 5" fill="none" opacity="0.7" />{/if}
      <path d={path(s.values)} stroke={s.color} stroke-width="2.4" fill="none" stroke-dasharray={s.dashed ? '2 4' : undefined} stroke-linejoin="round" />
      {#each s.values as v, i (i)}
        {#if v !== null}<circle cx={X(i)} cy={Y(v)} r="4" fill="#0b0f17" stroke={s.color} stroke-width="2"><title>{s.name} · {labels[i]}: {v.toFixed(decimals)}{unit}</title></circle>{/if}
      {/each}
    {/each}
  </svg>
  <div class="legend">
    {#each series as s (s.name)}<span><i style="background:{s.color}"></i>{s.name}</span>{/each}
    {#if series.some((s) => s.trend)}<span class="dim">- - - trend</span>{/if}
  </div>
</div>

<style>
  .lc { width: 100%; min-width: 0; overflow: hidden; }
  svg { display: block; }
  .legend { display: flex; gap: 0.9rem; flex-wrap: wrap; font-size: 0.78rem; color: var(--muted); margin-top: 0.2rem; }
  .legend i { display: inline-block; width: 10px; height: 3px; border-radius: 2px; margin-right: 0.35rem; vertical-align: middle; }
</style>
