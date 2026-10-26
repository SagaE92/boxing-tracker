<script lang="ts">
  // Lead / rear share as a two-colour bar (lead = sky, rear = pink).
  let { lead, rear, size = 'sm', labels = false }: { lead: number; rear: number; size?: 'sm' | 'lg'; labels?: boolean } = $props();
  const total = $derived(lead + rear);
  const lp = $derived(total ? Math.round((lead / total) * 100) : 50);
</script>

{#if total}
  <div class="split {size}" role="img" aria-label={`Lead hand ${lp}%, rear hand ${100 - lp}%`}>
    <span class="l" style="width:{lp}%"></span><span class="r" style="width:{100 - lp}%"></span>
  </div>
  {#if labels}
    <div class="lab"><span><i class="dl"></i>Lead <b class="num">{lp}%</b> <span class="dim num">({lead})</span></span><span><i class="dr"></i>Rear <b class="num">{100 - lp}%</b> <span class="dim num">({rear})</span></span></div>
  {/if}
{/if}

<style>
  .split { display: flex; height: 6px; border-radius: 99px; overflow: hidden; background: #1c2538; gap: 2px; }
  .split.lg { height: 10px; }
  .l { background: #38bdf8; border-radius: 99px 0 0 99px; }
  .r { background: #f472b6; border-radius: 0 99px 99px 0; }
  .lab { display: flex; justify-content: space-between; font-size: 0.8rem; color: var(--muted); margin-top: 0.35rem; }
  .lab b { color: var(--text); }
  i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 0.35rem; }
  .dl { background: #38bdf8; } .dr { background: #f472b6; }
</style>
