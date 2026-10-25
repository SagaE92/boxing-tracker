<script lang="ts">
  import { NON_STRIKE, typeColor, typeLabel, type EventType } from '../taxonomy';
  let { type, confidence = null, short = false }: { type: string; confidence?: number | null; short?: boolean } = $props();
  const low = $derived(NON_STRIKE.has(type as EventType) || (confidence !== null && confidence < 0.5));
</script>

<span class="tt"><span class="dot" style="background:{typeColor(type)}"></span>{short ? typeLabel(type).replace('Kick / body movement', 'Kick/body') : typeLabel(type)}{#if low}<span class="badge low" title="Low confidence">low conf.</span>{/if}</span>

<style>
  .tt { display: inline-flex; align-items: center; gap: 0.4rem; }
</style>
