import { toPng } from 'html-to-image';
import { toCsv } from './csv';
import type { StrikeEvent } from './types';
import type { SummaryStats } from './stats';

export function download(name: string, data: Blob | string, mime = 'text/csv') {
  const blob = typeof data === 'string' ? new Blob([data], { type: mime }) : data;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name; a.rel = 'noopener';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export const EVENT_CSV_HEADER = ['id', 't_peak_s', 't_start_s', 't_end_s', 'type', 'confidence', 'target', 'hand', 'peak_g', 'peak_g_is_lower_bound', 'speed_mps_est', 'duration_ms', 'gyro_int_x_deg', 'gyro_int_y_deg', 'gyro_int_z_deg', 'saturated', 'round_index'];
export function eventsCsv(ev: StrikeEvent[]): string {
  return toCsv(EVENT_CSV_HEADER, ev.map((e) => [e.id, e.t_peak_s, e.t_start_s, e.t_end_s, e.type, e.confidence, e.target, e.hand, e.peak_g, e.saturated, e.speed_mps_est, e.duration_ms, ...e.gyro_int_dps_s, e.saturated, e.round_index]));
}
export function summaryCsv(sessionId: string, s: SummaryStats, extra: [string, string | number | null][] = []): string {
  const rows: [string, string | number | null][] = [
    ['session_id', sessionId], ['strikes', s.strikes], ['strikes_per_min', +s.perMin.toFixed(2)], ['active_time_s', +s.activeTimeS.toFixed(1)],
    ['mean_peak_g', s.meanPeak !== null ? +s.meanPeak.toFixed(3) : null], ['max_peak_g', s.maxPeak !== null ? +s.maxPeak.toFixed(3) : null],
    ['max_peak_g_is_lower_bound', String(s.maxPeakSaturated)],
    ['mean_speed_mps_est', s.meanSpeed !== null ? +s.meanSpeed.toFixed(2) : null], ['max_speed_mps_est', s.maxSpeed !== null ? +s.maxSpeed.toFixed(2) : null],
    ['saturated_strikes', s.saturatedStrikes], ['kick_or_body_movement_events', s.kicks], ['clinch_events', s.clinches], ['clinch_time_s', +s.clinchTimeS.toFixed(1)],
    ['head', s.byTarget.head], ['body', s.byTarget.body], ['target_unknown', s.byTarget.unknown],
    ['hand_L', s.byHand.L], ['hand_R', s.byHand.R], ['hand_unknown', s.byHand.unknown],
    ...Object.entries(s.byType).map(([k, v]) => [`type_${k}`, v] as [string, number]),
    ...extra,
  ];
  return toCsv(['metric', 'value'], rows);
}
export async function exportPng(node: HTMLElement, name: string) {
  const url = await toPng(node, { backgroundColor: '#0b0f17', pixelRatio: 2, cacheBust: true, filter: (n) => !(n instanceof HTMLElement && n.dataset.noexport !== undefined) });
  const blob = await (await fetch(url)).blob();
  download(name, blob, 'image/png');
}
