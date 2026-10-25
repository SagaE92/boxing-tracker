<script lang="ts">
  let { text }: { text: string } = $props();
  const id = `tip-${Math.random().toString(36).slice(2, 9)}`;
</script>

<span class="tip" tabindex="0" role="button" aria-describedby={id} aria-label="How is this computed?">
  <span aria-hidden="true">i</span>
  <span class="body" role="tooltip" {id}>{text}</span>
</span>

<style>
  .tip {
    position: relative; display: inline-grid; place-items: center; width: 16px; height: 16px; border-radius: 50%;
    border: 1px solid var(--line2); color: var(--muted); font-size: 10px; font-weight: 700; cursor: help; flex: none;
    font-style: italic; font-family: Georgia, serif; vertical-align: middle;
  }
  .body {
    display: none; position: absolute; z-index: 50; top: calc(100% + 8px); left: 50%; transform: translateX(-50%);
    width: min(290px, 80vw); padding: 0.6rem 0.7rem; border-radius: 10px; background: #0a0f19; border: 1px solid var(--line2);
    color: var(--text); font: 400 0.8rem/1.45 var(--font); font-style: normal; text-transform: none; letter-spacing: 0; text-align: left;
    box-shadow: 0 12px 30px rgba(0, 0, 0, 0.55); pointer-events: none; white-space: normal;
  }
  .tip:hover .body, .tip:focus .body { display: block; }
  .tip:hover, .tip:focus { color: var(--text); border-color: var(--accent2); }
</style>
