<script lang="ts">
  let { value }: { value: number } = $props();
  const cls = $derived(value >= 0.75 ? 'hi' : value >= 0.5 ? 'mid' : 'low');
</script>

<span class="badge {cls} num" title="Classifier confidence {value.toFixed(2)}">{Math.round(value * 100)}%</span>
