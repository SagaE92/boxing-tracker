<script lang="ts">
  import uPlot from 'uplot';
  import { onDestroy } from 'svelte';
  import { LiveClient, UUID, webBluetoothAvailable, type LivePunch, type RawPacket } from '../gatt';
  import { AXIS, AXIS_COLORS } from '../plot';
  import { typeColor, typeLabel } from '../taxonomy';
  import TypeTag from './TypeTag.svelte';

  const supported = webBluetoothAvailable();
  let status = $state('Not connected');
  let err = $state<string | null>(null);
  let connected = $state(false);
  let punches = $state<LivePunch[]>([]);
  let packets = $state(0), lost = $state(0), satCount = $state(0);
  let el = $state<HTMLDivElement>();
  let u: uPlot | null = null;
  const N = 416 * 10;
  const xs: number[] = [], ys: number[] = [];
  let lastSeq = -1, client: LiveClient | null = null, raf = 0;

  function onRaw(p: RawPacket) {
    packets++;
    if (lastSeq >= 0 && ((lastSeq + 1) & 0xffff) !== p.seq) lost += (p.seq - lastSeq - 1 + 0x10000) & 0xffff;
    lastSeq = p.seq;
    for (const s of p.samples) { xs.push(s.t_us / 1e6); ys.push(Math.hypot(s.ax, s.ay, s.az) - 1); if (s.sat) satCount++; }
    if (xs.length > N) { xs.splice(0, xs.length - N); ys.splice(0, ys.length - N); }
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; u?.setData([xs, ys]); });
  }
  async function connect() {
    err = null;
    client = new LiveClient({ raw: onRaw, punch: (p) => (punches = [p, ...punches].slice(0, 50)), status: (s) => { status = s; connected = s.startsWith('Connected'); }, error: (e) => (err = e) });
    try {
      await client.connect();
      if (el && !u) u = new uPlot({ width: el.clientWidth, height: 220, scales: { x: { time: false } }, legend: { show: false }, axes: [{ ...AXIS }, { ...AXIS, size: 44, label: '|a|−1 g', labelSize: 14, labelFont: AXIS.font }], series: [{}, { stroke: AXIS_COLORS.mag, width: 1.2, points: { show: false } }] }, [[], []], el);
    } catch (e) { err = (e as Error).message; status = 'Not connected'; }
  }
  async function disconnect() { await client?.disconnect(); connected = false; status = 'Disconnected'; }
  onDestroy(() => { client?.disconnect(); u?.destroy(); cancelAnimationFrame(raf); });
</script>

<section class="card">
  <div class="card-h"><h2>Live (Web Bluetooth) <span class="badge info">beta</span></h2><span class="sub">{status}</span></div>
  {#if !supported}
    <div class="alert info"><span class="ico">i</span><span>This browser has no Web Bluetooth. Use Chrome or Edge on desktop or Android (iOS Safari does not support it). Everything else in the dashboard works offline without it.</span></div>
  {:else}
    <p class="muted small">Connects to the tracker's custom GATT service, starts the raw stream and shows |a|−1 g for the last 10 s plus on-device strike events. Requires firmware with the v1 protocol built with the raw-stream debug option (<span class="mono">CONFIG_BTRK_RAW_STREAM=y</span>); the default firmware sends strike events only.</p>
    <div style="display:flex;gap:.5rem;flex-wrap:wrap">
      {#if !connected}<button class="btn primary" onclick={connect}>Connect tracker</button>{:else}<button class="btn" onclick={disconnect}>Disconnect</button>{/if}
    </div>
  {/if}
  {#if err}<div class="alert bad" style="margin-top:.6rem"><span class="ico">!</span><span>{err}</span></div>{/if}
  <div bind:this={el} style="margin-top:.8rem"></div>
  {#if connected}<p class="small muted num">{packets} packets · {lost} lost · {satCount} saturated samples</p>{/if}
</section>
{#if punches.length}
  <section class="card"><div class="card-h"><h2>Live events</h2></div>
    <table><thead><tr><th>#</th><th>t</th><th>Type</th><th class="r">Peak g</th><th class="r">Speed est.</th><th class="r">Conf.</th></tr></thead>
      <tbody>{#each punches as p (p.index)}<tr><td class="num">{p.index}</td><td class="num">{p.t_s.toFixed(2)} s</td><td><TypeTag type={p.type} confidence={p.confidence} /></td><td class="r num">{p.saturated ? '≥' : ''}{p.peak_g.toFixed(1)}</td><td class="r num">~{p.speed_mps.toFixed(1)}</td><td class="r num">{Math.round(p.confidence * 100)}%</td></tr>{/each}</tbody></table>
  </section>
{/if}
<section class="card small">
  <div class="card-h"><h3>Protocol</h3></div>
  <p class="muted">Wire format from <span class="mono">firmware/src/bt_proto.h</span> (BTRK_PROTO_VERSION 1); the prose spec lives in <span class="mono">docs/gatt-spec.md</span>. Service <span class="mono">{UUID.service}</span>; raw stream <span class="mono">…0005</span> (18-byte header + up to 18 × 12-byte samples, accel 0.488 mg/LSB, gyro 70 mdps/LSB, per-sample saturation bitmasks); strike event <span class="mono">…0002</span> (16 bytes); control point <span class="mono">…0003</span>.</p>
  <p class="dim">Not yet tested against real hardware. {typeLabel('jab')} etc. map from the firmware type codes 0–10. <span style="color:{typeColor('clinch')}">Clinch</span> events carry their duration instead of peak gyro.</p>
</section>
