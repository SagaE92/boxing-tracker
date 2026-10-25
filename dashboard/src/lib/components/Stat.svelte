<script lang="ts">
  import Tip from './Tip.svelte';
  import type { Snippet } from 'svelte';
  let { label, value, unit = '', sub = '', tip = '', tone = '', children }: { label: string; value: string; unit?: string; sub?: string; tip?: string; tone?: '' | 'warn' | 'bad' | 'accent'; children?: Snippet } = $props();
</script>

<div class="stat card {tone}">
  <div class="lab">{label}{#if tip}<Tip text={tip} />{/if}</div>
  <div class="val num">{value}{#if unit}<span class="unit">{unit}</span>{/if}</div>
  {#if sub}<div class="sub">{sub}</div>{/if}
  {#if children}{@render children()}{/if}
</div>

<style>
  .stat { padding: 0.85rem 1rem; display: flex; flex-direction: column; gap: 0.2rem; position: relative; }
  .lab { display: flex; gap: 0.4rem; align-items: center; color: var(--muted); font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
  .val { font-size: 1.85rem; font-weight: 700; letter-spacing: -0.02em; line-height: 1.1; }
  .unit { font-size: 0.9rem; color: var(--muted); font-weight: 500; margin-left: 0.2rem; }
  .sub { color: var(--muted); font-size: 0.8rem; }
  .accent .val { color: #ffd2c6; }
  .accent { border-color: rgba(255, 90, 54, 0.35); }
  .warn { border-color: rgba(251, 191, 36, 0.45); }
  .warn .val { color: #fde68a; }
  .bad { border-color: rgba(248, 113, 113, 0.5); }
  .bad .val { color: #fecaca; }
</style>
