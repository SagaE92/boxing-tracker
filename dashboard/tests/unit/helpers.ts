import type { StrikeEvent } from '../../src/lib/types';
import type { EventType } from '../../src/lib/taxonomy';

let nextId = 0;
export function ev(t: number, type: EventType = 'jab', extra: Partial<StrikeEvent> = {}): StrikeEvent {
  return {
    id: nextId++, t_peak_s: t, t_start_s: t - 0.05, t_end_s: t + 0.03, type, confidence: 0.9, target: 'head', hand: 'L',
    peak_g: 6, speed_mps_est: 6, duration_ms: 80, gyro_int_dps_s: [0, 0, 0], saturated: false, round_index: 0, ...extra,
  };
}
export function rawCsv(rows: number, opts: { fs?: number; gapAt?: number; gapLen?: number; satEvery?: number; dev0?: number } = {}): string {
  const fs = opts.fs ?? 416;
  const lines = ['host_time_s,device_time_us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,sat'];
  let skip = 0;
  for (let i = 0; i < rows; i++) {
    if (opts.gapAt !== undefined && i === opts.gapAt) skip = opts.gapLen ?? 10;
    if (skip > 0) { skip--; continue; }
    const dev = ((opts.dev0 ?? 0) + Math.round((i * 1e6) / fs)) % 2 ** 32;
    const sat = opts.satEvery && i % opts.satEvery === 0 ? 1 : 0;
    lines.push(`${(1792864800 + i / fs).toFixed(4)},${dev},0,0,${sat ? 16 : 1},0,0,0,${sat}`);
  }
  return lines.join('\n') + '\n';
}
