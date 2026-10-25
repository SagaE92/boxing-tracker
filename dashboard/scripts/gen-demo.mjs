#!/usr/bin/env node
// Synthetic session generator for the dashboard demo and tests.
//
// This is NOT the punch detector. analysis/detector.py is the single source of
// truth for detection/classification. This script *simulates* a recording: it
// synthesises raw 6-axis IMU data around a known ground-truth strike schedule,
// then writes a session.json that mimics plausible detector output (peak g is
// measured from the synthetic signal; type errors, misses and false positives
// are injected on purpose so the label-review view has something to show).
//
// Usage:
//   node scripts/gen-demo.mjs [--out public/demo] [--prefix demo-2026-10-24]
//     [--date 2026-10-24T18:00:00Z] [--rounds 3] [--round-s 180] [--rest-s 60]
//     [--seed 1] [--fatigue 1] [--intensity 1] [--json-only] [--no-labels]
//     [--profile normal|idle|heavy-sat|single-hand] [--gaps 2] [--no-calibration]
//     [--no-gzip] [--hand lead|rear]
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, arr) => {
    if (a.startsWith('--')) {
      const nxt = arr[i + 1];
      acc.push([a.slice(2), nxt === undefined || nxt.startsWith('--') ? true : nxt]);
    }
    return acc;
  }, []),
);
const OUT = args.out ?? 'public/demo';
const PREFIX = args.prefix ?? 'demo-2026-10-24';
const DATE = args.date ?? '2026-10-24T18:00:00Z';
const ROUNDS = +(args.rounds ?? 3);
const ROUND_S = +(args['round-s'] ?? 180);
const REST_S = +(args['rest-s'] ?? 60);
const SEED = +(args.seed ?? 1);
const FATIGUE = +(args.fatigue ?? 1);
const INTENSITY = +(args.intensity ?? 1);
const PROFILE = args.profile ?? 'normal';
const GAPS = +(args.gaps ?? 2);
const SENSOR = args.hand === 'rear' ? 'rear' : 'lead'; // which hand wears the sensor (orthodox stance)
const SENSOR_HAND = SENSOR === 'lead' ? 'L' : 'R';
const FS = 416;
const RANGE_G = 16;
const RANGE_DPS = 2000;
const THRESH = 3.5;
const WIN_MS = 150;
const REFRACT_MS = 150;

// ---------- RNG ----------
let s = SEED >>> 0 || 1;
const rnd = () => {
  s = (s + 0x6d2b79f5) >>> 0;
  let t = s;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
const randn = () => Math.sqrt(-2 * Math.log(rnd() + 1e-12)) * Math.cos(2 * Math.PI * rnd());
const uni = (a, b) => a + (b - a) * rnd();
const pick = (arr) => arr[Math.floor(rnd() * arr.length)];
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

// ---------- schedule ----------
const LEAD_IN = 8, TAIL = 8;
const segments = [];
let t = LEAD_IN;
for (let r = 0; r < ROUNDS; r++) {
  segments.push({ kind: 'round', t0: t, t1: t + ROUND_S });
  t += ROUND_S;
  if (r < ROUNDS - 1) { segments.push({ kind: 'rest', t0: t, t1: t + REST_S }); t += REST_S; }
}
const DURATION = t + TAIL;
const N = Math.round(DURATION * FS);

// Orthodox stance; sensor inside the wrap on the lead (left) or rear (right) hand.
const LEAD = ['jab', 'lead_hook', 'lead_uppercut'];
const COMBOS = [
  ['jab'], ['jab'], ['jab', 'jab'], ['jab', 'cross'], ['jab', 'cross'], ['jab', 'cross', 'lead_hook'],
  ['jab', 'cross', 'lead_hook', 'cross'], ['lead_hook', 'cross'], ['jab', 'rear_uppercut', 'lead_hook'],
  ['lead_uppercut', 'lead_hook'], ['jab', 'overhand'], ['jab', 'cross', 'kick'], ['kick'],
  ['jab', 'jab', 'cross'], ['lead_hook', 'rear_hook'], ['spinning_backfist'], ['jab', 'rear_hook', 'kick'],
];
const SINGLE = [['jab'], ['jab', 'jab'], ['jab', 'lead_hook'], ['lead_hook'], ['lead_uppercut', 'lead_hook'], ['jab', 'jab', 'lead_hook']];
const handOf = (ty) => (ty === 'kick' ? null : LEAD.includes(ty) ? 'L' : 'R');

const strikes = []; // ground truth
const roundsOnly = segments.filter((x) => x.kind === 'round');
const clinches = [];
if (PROFILE === 'normal') roundsOnly.forEach((seg, ri) => {
  if (ri === 0 && roundsOnly.length > 1) return;
  const len = uni(6, 14), c0 = uni(seg.t0 + 30, seg.t1 - 30 - len);
  clinches.push({ t0: c0, t1: c0 + len, round: ri });
});
const inClinch = (tt) => clinches.some((c) => tt > c.t0 - 0.5 && tt < c.t1 + 0.5);
if (PROFILE !== 'idle') {
  roundsOnly.forEach((seg, ri) => {
    let tt = seg.t0 + uni(1.5, 3);
    while (tt < seg.t1 - 2) {
      if (inClinch(tt)) { tt += 0.5; continue; }
      const prog = (tt - seg.t0) / (seg.t1 - seg.t0);
      const fat = 1 - FATIGUE * (0.07 * ri + 0.06 * prog);
      const combo = pick(PROFILE === 'single-hand' ? SINGLE : COMBOS);
      for (const ty of combo) {
        if (tt > seg.t1 - 1) break;
        strikes.push({ t: tt, type: ty, hand: handOf(ty), fat, round: ri, combo: true });
        tt += ty === 'kick' ? uni(0.55, 0.8) : uni(0.26, 0.42);
      }
      tt += uni(1.0, 3.6) / INTENSITY / Math.max(0.6, fat);
    }
  });
}

// ---------- signal ----------
const ax = new Float32Array(N), ay = new Float32Array(N), az = new Float32Array(N);
const gx = new Float32Array(N), gy = new Float32Array(N), gz = new Float32Array(N);
const inRound = (tt) => segments.find((x) => x.kind === 'round' && tt >= x.t0 && tt < x.t1);
const G0 = [0.28, -0.22, 0.93];
const gn = Math.hypot(...G0); G0.forEach((v, i) => (G0[i] = v / gn));
let wob1 = rnd() * 6, wob2 = rnd() * 6;
for (let i = 0; i < N; i++) {
  const tt = i / FS;
  const active = !!inRound(tt);
  const bounce = active ? 0.22 * Math.sin(2 * Math.PI * 2.1 * tt + wob1) + 0.06 * Math.sin(2 * Math.PI * 0.37 * tt) : 0.01 * Math.sin(2 * Math.PI * 0.2 * tt);
  const tilt = (active ? 0.12 : 0.04) * Math.sin(2 * Math.PI * 0.11 * tt + wob2);
  ax[i] = G0[0] + tilt + 0.3 * bounce * G0[0] + 0.015 * randn();
  ay[i] = G0[1] - tilt * 0.5 + 0.3 * bounce * G0[1] + 0.015 * randn();
  az[i] = G0[2] + bounce + 0.015 * randn();
  const w = active ? 22 : 2;
  gx[i] = w * Math.sin(2 * Math.PI * 1.3 * tt + wob1) + 0.6 * randn();
  gy[i] = w * 0.7 * Math.sin(2 * Math.PI * 0.9 * tt + wob2) + 0.6 * randn();
  gz[i] = w * 0.5 * Math.sin(2 * Math.PI * 1.7 * tt) + 0.6 * randn();
}
const gauss = (x, mu, sd) => Math.exp(-0.5 * ((x - mu) / sd) ** 2);
function addPulse(arr, tc, sdS, amp) {
  const i0 = Math.max(0, Math.floor((tc - 5 * sdS) * FS)), i1 = Math.min(N - 1, Math.ceil((tc + 5 * sdS) * FS));
  for (let i = i0; i <= i1; i++) arr[i] += amp * gauss(i / FS, tc, sdS);
}
const PEAK = { jab: [5, 9.5], cross: [7, 12], lead_hook: [8, 21], rear_hook: [8, 18], lead_uppercut: [6.5, 13], rear_uppercut: [6.5, 12], overhand: [8, 15], spinning_backfist: [9, 19], kick: [3.4, 6.5] };
const SPEED = { jab: [5, 7.2], cross: [6.5, 8.8], lead_hook: [6.5, 9.8], rear_hook: [6.5, 9.4], lead_uppercut: [5, 7.6], rear_uppercut: [5, 7.4], overhand: [6.5, 9], spinning_backfist: [7, 10], kick: [1, 2.5] };
const heavy = PROFILE === 'heavy-sat';
for (const st of strikes) {
  let [lo, hi] = PEAK[st.type];
  if (heavy && st.type !== 'kick') { lo = Math.max(lo, 13); hi = hi + 8; }
  let A = uni(lo, hi) * st.fat;
  if (st.type === 'jab' && rnd() < 0.08) A = uni(2.4, 3.6); // flicked / feint jab: some fall under threshold
  // Sensor on the lead hand: rear-hand strikes reach it only via torso rotation.
  const viaBody = st.hand !== null && st.hand !== SENSOR_HAND;
  if (viaBody) A *= uni(0.45, 0.7);
  st.A = A;
  st.speed = uni(...SPEED[st.type]) * st.fat;
  const dImp = heavy ? 2.5 : 1; // heavy-sat: longer, harder impacts (bag work with heavy shots)
  const d = st.type === 'kick' ? uni(0.28, 0.4) : st.type === 'spinning_backfist' ? uni(0.3, 0.42) : uni(0.13, 0.22);
  st.d = d;
  const tAcc = st.t - 0.45 * d, tImp = st.t;
  const ty = st.type;
  if (ty === 'kick') {
    addPulse(az, tAcc, d * 0.25, A * 0.6); addPulse(ax, tImp, d * 0.12, -A * 0.9); addPulse(ay, tImp, d * 0.15, A * 0.35);
    addPulse(gz, tAcc, d * 0.3, uni(150, 300)); continue;
  }
  if (viaBody) {
    addPulse(ay, tAcc, d * 0.2, A * 0.5); addPulse(ax, tImp, d * 0.08, -A * 0.85); addPulse(gz, tAcc, d * 0.3, uni(180, 380)); continue;
  }
  if (ty === 'jab' || ty === 'cross') {
    addPulse(ax, tAcc, d * 0.18, A * 0.55); addPulse(ax, tImp, d * 0.06 * dImp, -A); addPulse(ay, tImp, d * 0.08, A * 0.15);
    addPulse(gx, tAcc, d * 0.25, uni(250, 520));
  } else if (ty.endsWith('hook') || ty === 'overhand' || ty === 'spinning_backfist') {
    const spin = ty === 'spinning_backfist';
    addPulse(ay, tAcc, d * 0.2, -A * 0.6); addPulse(ax, tAcc, d * 0.2, A * 0.35);
    addPulse(ay, tImp, d * 0.06 * dImp, A * 0.95); addPulse(ax, tImp, d * 0.06, -A * 0.4);
    addPulse(gz, tAcc, d * 0.25, (spin ? -1 : 1) * uni(spin ? 1300 : 800, spin ? 1950 : 1500));
    if (ty === 'overhand') addPulse(gy, tAcc, d * 0.25, uni(400, 700));
  } else {
    addPulse(az, tAcc, d * 0.2, A * 0.6); addPulse(az, tImp, d * 0.06 * dImp, -A * 0.8); addPulse(ax, tImp, d * 0.07, -A * 0.4);
    addPulse(gy, tAcc, d * 0.25, -uni(600, 1100));
  }
}
// false positives: guard adjustments / glove taps
const taps = [];
if (PROFILE === 'normal') for (const seg of roundsOnly) for (let k = 0; k < 2; k++) {
  const tt = uni(seg.t0 + 5, seg.t1 - 5);
  if (strikes.some((x) => Math.abs(x.t - tt) < 0.6)) continue;
  const A = uni(3.9, 5.2); addPulse(ax, tt, 0.012, -A); addPulse(ay, tt, 0.015, A * 0.3); taps.push(tt);
}
// clinch: pushing/pulling, knees (body jolts), wrist heavily rotated
for (const c of clinches) {
  for (let i = Math.floor(c.t0 * FS); i < Math.floor(c.t1 * FS); i++) {
    const tt = i / FS;
    ax[i] += 0.6 * Math.sin(2 * Math.PI * 0.7 * tt) + 0.05 * randn(); ay[i] += 0.5 * Math.sin(2 * Math.PI * 0.45 * tt + 1);
    gx[i] += 60 * Math.sin(2 * Math.PI * 0.6 * tt); gy[i] += 45 * Math.sin(2 * Math.PI * 0.9 * tt);
  }
  for (let k = 0; k < Math.floor((c.t1 - c.t0) / 2.5); k++) { const tk = uni(c.t0 + 0.5, c.t1 - 0.5); addPulse(az, tk, 0.03, uni(1.8, 3.2)); addPulse(ax, tk, 0.02, -uni(0.8, 1.6)); }
}
// clip + sat
const sat = new Uint8Array(N);
const CLIP = RANGE_G - 0.001;
for (let i = 0; i < N; i++) {
  for (const a of [ax, ay, az]) if (a[i] > CLIP || a[i] < -RANGE_G) { a[i] = clamp(a[i], -RANGE_G, CLIP); sat[i] = 1; }
  for (const g of [gx, gy, gz]) g[i] = clamp(g[i], -RANGE_DPS, RANGE_DPS);
}
const amag = (i) => Math.hypot(ax[i], ay[i], az[i]) - 1;

// BLE gaps: drop samples (rows missing from CSV)
const drop = new Uint8Array(N);
const gapsInfo = [];
for (let k = 0; k < GAPS; k++) {
  const seg = pick(roundsOnly.length ? roundsOnly : segments);
  const t0 = uni(seg.t0 + 10, seg.t1 - 10), len = uni(0.15, 0.6);
  for (let i = Math.floor(t0 * FS); i < Math.floor((t0 + len) * FS); i++) drop[i] = 1;
  gapsInfo.push([+t0.toFixed(3), +len.toFixed(3)]);
}

// ---------- simulated detector output ----------
const W = Math.round((WIN_MS / 1000) * FS);
const CONFUSE = {
  jab: ['cross', 'lead_uppercut'], cross: ['jab', 'rear_hook'], lead_hook: ['rear_hook', 'overhand', 'lead_uppercut'],
  rear_hook: ['lead_hook', 'overhand'], lead_uppercut: ['lead_hook', 'jab'], rear_uppercut: ['lead_uppercut', 'rear_hook'],
  overhand: ['rear_hook', 'cross'], spinning_backfist: ['lead_hook', 'unknown'], kick: ['unknown'],
};
const cand0 = [...strikes.map((x) => ({ t: x.t, gt: x })), ...taps.map((tt) => ({ t: tt, gt: null }))].sort((a, b) => a.t - b.t);
const cand = cand0;
const events = [];
let lastPeak = -1e9;
for (const c of cand) {
  const ic = Math.round(c.t * FS);
  let ip = ic, mx = -1;
  for (let i = Math.max(0, ic - 40); i <= Math.min(N - 1, ic + 40); i++) { if (drop[i]) continue; const m = amag(i); if (m > mx) { mx = m; ip = i; } }
  if (mx < THRESH || (ip - lastPeak) * 1000 / FS < REFRACT_MS) continue;
  lastPeak = ip;
  const a0 = Math.max(0, ip - W), a1 = Math.min(N - 1, ip + W);
  let is = ip, ie = ip;
  while (is > a0 && amag(is - 1) > 1.0) is--;
  while (ie < a1 && amag(ie + 1) > 1.0) ie++;
  is = Math.max(a0, is - Math.round(0.03 * FS)); ie = Math.min(a1, ie + Math.round(0.02 * FS));
  let satw = false; const gi = [0, 0, 0];
  for (let i = a0; i <= a1; i++) { if (sat[i]) satw = true; gi[0] += gx[i] / FS; gi[1] += gy[i] / FS; gi[2] += gz[i] / FS; }
  const gt = c.gt;
  let type, conf;
  if (!gt) { type = rnd() < 0.5 ? 'unknown' : 'jab'; conf = uni(0.25, 0.5); }
  else {
    const gtt = gt.type === 'kick' ? 'kick_or_body_movement' : gt.type;
    const viaBody = gt.hand !== null && gt.hand !== SENSOR_HAND;
    const pCorrect = gt.type === 'kick' ? 0.75 : viaBody ? 0.6 : 0.88;
    if (rnd() < pCorrect) { type = gtt; conf = gt.type === 'kick' ? uni(0.2, 0.45) : viaBody ? uni(0.4, 0.75) : uni(0.65, 0.97); }
    else { const alt = pick(CONFUSE[gt.type]); type = alt === 'kick' ? 'kick_or_body_movement' : alt; conf = uni(0.3, 0.6); }
  }
  const isKick = type === 'kick_or_body_movement';
  const hand = isKick || type === 'unknown' ? null : LEAD.includes(type) ? 'L' : 'R';
  const target = isKick ? null : type.includes('uppercut') || rnd() < 0.22 ? (rnd() < 0.75 ? 'body' : 'head') : rnd() < 0.08 ? null : 'head';
  const speed = gt ? (isKick ? null : +(gt.speed * uni(0.9, 1.1)).toFixed(2)) : +uni(2, 4).toFixed(2);
  events.push({
    t_peak_s: +(ip / FS).toFixed(4), t_start_s: +(is / FS).toFixed(4), t_end_s: +(ie / FS).toFixed(4),
    type, confidence: +conf.toFixed(2), target, hand,
    peak_g: +mx.toFixed(3), speed_mps_est: speed, duration_ms: +(((ie - is) / FS) * 1000).toFixed(1),
    gyro_int_dps_s: gi.map((v) => +v.toFixed(2)), saturated: satw,
  });
}
for (const c of clinches) {
  let mx = 0, ip = Math.floor(c.t0 * FS); const gi = [0, 0, 0]; let satw = false;
  for (let i = Math.floor(c.t0 * FS); i < Math.floor(c.t1 * FS); i++) { if (drop[i]) continue; const m = amag(i); if (m > mx) { mx = m; ip = i; } if (sat[i]) satw = true; gi[0] += gx[i] / FS; gi[1] += gy[i] / FS; gi[2] += gz[i] / FS; }
  events.push({ t_peak_s: +(ip / FS).toFixed(4), t_start_s: +c.t0.toFixed(3), t_end_s: +c.t1.toFixed(3), type: 'clinch', confidence: +uni(0.3, 0.55).toFixed(2), target: null, hand: null,
    peak_g: +mx.toFixed(3), speed_mps_est: null, duration_ms: +((c.t1 - c.t0) * 1000).toFixed(1), gyro_int_dps_s: gi.map((v) => +v.toFixed(2)), saturated: satw });
}
events.sort((a, b) => a.t_peak_s - b.t_peak_s);
const rounds = segments.map((x, i) => ({ index: i, t_start_s: +x.t0.toFixed(3), t_end_s: +x.t1.toFixed(3), kind: x.kind }));
events.forEach((e, i) => {
  e.id = i;
  const r = rounds.find((r) => e.t_peak_s >= r.t_start_s && e.t_peak_s < r.t_end_s);
  e.round_index = r ? r.index : null;
});
const ordered = events.map(({ id, ...rest }) => ({ id, ...rest }));
const TYPES = ['jab', 'cross', 'lead_hook', 'rear_hook', 'lead_uppercut', 'rear_uppercut', 'overhand', 'spinning_backfist', 'kick_or_body_movement', 'clinch', 'unknown'];
const punches = ordered.filter((e) => e.type !== 'kick_or_body_movement' && e.type !== 'clinch');
const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);
const max = (a) => (a.length ? Math.max(...a) : null);
const r3 = (v) => (v == null ? null : +v.toFixed(3));
const by_type = {}; TYPES.forEach((k) => (by_type[k] = 0)); ordered.forEach((e) => by_type[e.type]++);
const by_hand = { L: 0, R: 0, unknown: 0 }; punches.forEach((e) => by_hand[e.hand ?? 'unknown']++);
const by_target = { head: 0, body: 0, unknown: 0 }; punches.forEach((e) => by_target[e.target ?? 'unknown']++);
const roundTime = rounds.filter((r) => r.kind === 'round').reduce((a, r) => a + r.t_end_s - r.t_start_s, 0) || DURATION;
const speeds = punches.map((e) => e.speed_mps_est).filter((v) => v != null);
let nSat = 0; for (let i = 0; i < N; i++) if (sat[i] && !drop[i]) nSat++;
let nKept = 0; for (let i = 0; i < N; i++) if (!drop[i]) nKept++;
const startMs = Date.parse(DATE);
const session = {
  schema_version: '1.0.0',
  generator: { name: 'dashboard/scripts/gen-demo.mjs (synthetic demo, not detector output)', version: '0.1.0' },
  session: {
    id: PREFIX, start_time_iso: new Date(startMs).toISOString(), duration_s: +DURATION.toFixed(3), sample_rate_hz: FS,
    accel_range_g: RANGE_G, gyro_range_dps: RANGE_DPS, hand_worn: SENSOR_HAND, hand: SENSOR, stance: 'orthodox', sensor_mount: 'hand_wrap',
    calibration: args['no-calibration'] ? null : { guard_gravity_g: G0.map((v) => +v.toFixed(3)), forward_axis: [1, 0, 0], t_start_s: 1, t_end_s: 6 },
  },
  detector_params: { threshold_g: THRESH, refractory_ms: REFRACT_MS, window_ms: WIN_MS },
  rounds,
  punches: ordered,
  summary: {
    punch_count: punches.length,
    punches_per_min: +(punches.length / (roundTime / 60)).toFixed(2),
    punches_per_round: rounds.filter((r) => r.kind === 'round').map((r) => punches.filter((e) => e.round_index === r.index).length),
    mean_peak_g: r3(mean(punches.map((e) => e.peak_g))), max_peak_g: r3(max(punches.map((e) => e.peak_g))),
    mean_speed_mps_est: r3(mean(speeds)), max_speed_mps_est: r3(max(speeds)),
    by_type, by_hand, by_target, non_punch_count: ordered.length - punches.length,
    clinch_time_s: +clinches.reduce((a, c) => a + c.t1 - c.t0, 0).toFixed(2),
    saturated_sample_fraction: +(nSat / nKept).toFixed(5),
  },
};
fs.mkdirSync(OUT, { recursive: true });
fs.writeFileSync(path.join(OUT, `${PREFIX}_session.json`), JSON.stringify(session, null, 1));
const files = [`${PREFIX}_session.json`];
if (!args['json-only']) {
  const host0 = startMs / 1000;
  const parts = ['host_time_s,device_time_us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,sat\n'];
  let buf = '';
  for (let i = 0; i < N; i++) {
    if (drop[i]) continue;
    // host time arrives in BLE batches of ~8 samples (connection interval) with jitter
    const batchT = Math.ceil((i + 1) / 8) * 8 / FS + 0.004 + 0.003 * Math.abs(Math.sin(i * 0.37));
    buf += `${(host0 + batchT).toFixed(4)},${Math.round((i * 1e6) / FS)},${ax[i].toFixed(3)},${ay[i].toFixed(3)},${az[i].toFixed(3)},${gx[i].toFixed(1)},${gy[i].toFixed(1)},${gz[i].toFixed(1)},${sat[i]}\n`;
    if (buf.length > 1 << 20) { parts.push(buf); buf = ''; }
  }
  parts.push(buf);
  const csv = parts.join('');
  if (args['no-gzip']) { fs.writeFileSync(path.join(OUT, `${PREFIX}_raw.csv`), csv); files.push(`${PREFIX}_raw.csv`); }
  else { fs.writeFileSync(path.join(OUT, `${PREFIX}_raw.csv.gz`), zlib.gzipSync(csv, { level: 9 })); files.push(`${PREFIX}_raw.csv.gz`); }
  if (!args['no-labels']) {
    const notes = { kick: 'kick (body movement at wrist)', spinning_backfist: 'spinning backfist' };
    const lines = ['host_time_s,label,note'];
    const lab0 = [...strikes.map((st) => ({ t: st.t, st })), ...clinches.map((c) => ({ t: c.t0 + 0.3, c }))].sort((a, b) => a.t - b.t);
    for (const { st, c } of lab0) {
      if (c) { lines.push(`${(host0 + c.t0 + 0.3).toFixed(3)},clinch,clinch ${(c.t1 - c.t0).toFixed(1)} s`); continue; }
      const tl = host0 + st.t + 0.04 * randn() + 0.008; // video sync jitter
      const lab = st.type === 'kick' ? 'kick_or_body_movement' : `${st.type}_${st.hand}`;
      lines.push(`${tl.toFixed(3)},${lab},${notes[st.type] ?? ''}`);
    }
    fs.writeFileSync(path.join(OUT, `${PREFIX}_labels.csv`), lines.join('\n') + '\n');
    files.push(`${PREFIX}_labels.csv`);
  }
}
console.log(JSON.stringify({ clinches: clinches.length, out: OUT, files, samples: N, strikes: strikes.length, events: ordered.length, punches: punches.length, gaps: gapsInfo, sat_frac: session.summary.saturated_sample_fraction }));
