<script lang="ts">
  // Simple vertical bar chart (SVG), responsive width.
  let { data, height = 150, color = '#ff5a36', unit = '', decimals = 0, ariaLabel = 'bar chart', highlight = -1 }: { data: { label: string; value: number | null; color?: string; note?: string }[]; height?: number; color?: string; unit?: string; decimals?: number; ariaLabel?: string; highlight?: number } = $props();
  let w = $state(300);
  const max = $derived(Math.max(1e-9, ...data.map((d) => d.value ?? 0)));
  const pad = { t: 18, b: 22, l: 4, r: 4 };
  const bw = $derived(data.length ? (w - pad.l - pad.r) / data.length : 0);
</script>

<div class="bars" bind:clientWidth={w}>
  <svg width={w} {height} role="img" aria-label={ariaLabel}>
    {#each data as d, i (i)}
      {@const h = d.value ? ((height - pad.t - pad.b) * d.value) / max : 0}
      {@const x = pad.l + i * bw + bw * 0.15}
      <rect {x} y={height - pad.b - h} width={Math.max(1, bw * 0.7)} height={h} rx="4" fill={d.color ?? color} opacity={highlight < 0 || highlight === i ? 1 : 0.45}><title>{d.label}: {d.value === null ? '—' : d.value.toFixed(decimals)}{unit}{d.note ? ` (${d.note})` : ''}</title></rect>
      {#if bw > 22}<text x={x + bw * 0.35} y={height - pad.b - h - 5} text-anchor="middle" font-size="11" fill="#e8edf6" class="num">{d.value === null ? '' : d.value.toFixed(decimals)}</text>{/if}
      <text x={x + bw * 0.35} y={height - 6} text-anchor="middle" font-size="10.5" fill="#9aa8bf">{d.label}</text>
    {/each}
  </svg>
</div>

<style>
  .bars { width: 100%; min-width: 0; overflow: hidden; }
  svg { display: block; overflow: visible; }
</style>
