<script lang="ts">
  let { items, size = 150, thickness = 22, center = '', centerSub = '' }: { items: { label: string; value: number; color: string }[]; size?: number; thickness?: number; center?: string; centerSub?: string } = $props();
  const total = $derived(items.reduce((a, b) => a + b.value, 0));
  const arcs = $derived.by(() => {
    const r = (size - thickness) / 2, c = 2 * Math.PI * r;
    let off = 0;
    return items.filter((i) => i.value > 0).map((i) => {
      const len = total ? (i.value / total) * c : 0;
      const a = { ...i, r, dash: `${Math.max(0, len - 1.5)} ${c - Math.max(0, len - 1.5)}`, off: -off };
      off += len;
      return a;
    });
  });
</script>

<svg width={size} height={size} viewBox="0 0 {size} {size}" role="img" aria-label={items.filter((i) => i.value).map((i) => `${i.label} ${i.value}`).join(', ')}>
  <circle cx={size / 2} cy={size / 2} r={(size - thickness) / 2} fill="none" stroke="#1b2436" stroke-width={thickness} />
  <g transform="rotate(-90 {size / 2} {size / 2})">
    {#each arcs as a (a.label)}
      <circle cx={size / 2} cy={size / 2} r={a.r} fill="none" stroke={a.color} stroke-width={thickness} stroke-dasharray={a.dash} stroke-dashoffset={a.off}><title>{a.label}: {a.value}</title></circle>
    {/each}
  </g>
  {#if center}<text x="50%" y="48%" text-anchor="middle" fill="#e8edf6" font-size="22" font-weight="700" dominant-baseline="middle">{center}</text>{/if}
  {#if centerSub}<text x="50%" y="64%" text-anchor="middle" fill="#9aa8bf" font-size="11">{centerSub}</text>{/if}
</svg>
