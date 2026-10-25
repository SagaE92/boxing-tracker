// Strike taxonomy v1, shared with docs/session.schema.json and firmware/src/bt_proto.h.
export const TYPES = [
  'jab', 'cross', 'lead_hook', 'rear_hook', 'lead_uppercut', 'rear_uppercut',
  'overhand', 'spinning_backfist', 'unknown', 'kick_or_body_movement', 'clinch',
] as const;
export type EventType = (typeof TYPES)[number];

/** Events that are NOT strikes: excluded from strike totals by default. */
export const NON_STRIKE: ReadonlySet<EventType> = new Set(['kick_or_body_movement', 'clinch']);
/** Duration events, drawn as bands. */
export const DURATION_TYPES: ReadonlySet<EventType> = new Set(['clinch']);
export const isStrike = (t: string) => !NON_STRIKE.has(t as EventType);

export const TYPE_LABEL: Record<EventType, string> = {
  jab: 'Jab', cross: 'Cross', lead_hook: 'Lead hook', rear_hook: 'Rear hook',
  lead_uppercut: 'Lead uppercut', rear_uppercut: 'Rear uppercut', overhand: 'Overhand',
  spinning_backfist: 'Spinning backfist', unknown: 'Unknown strike',
  kick_or_body_movement: 'Kick / body movement', clinch: 'Clinch',
};
export const TYPE_SHORT: Record<EventType, string> = {
  jab: 'JAB', cross: 'CRS', lead_hook: 'LHK', rear_hook: 'RHK', lead_uppercut: 'LUP', rear_uppercut: 'RUP',
  overhand: 'OVH', spinning_backfist: 'SBF', unknown: '?', kick_or_body_movement: 'KCK', clinch: 'CLN',
};
// Chosen for contrast on the dark background and distinguishable hues.
export const TYPE_COLOR: Record<EventType, string> = {
  jab: '#38bdf8', cross: '#f472b6', lead_hook: '#fb923c', rear_hook: '#facc15',
  lead_uppercut: '#a3e635', rear_uppercut: '#34d399', overhand: '#c084fc',
  spinning_backfist: '#f87171', unknown: '#94a3b8', kick_or_body_movement: '#64748b', clinch: '#7c8db5',
};
export const HOOKS: EventType[] = ['lead_hook', 'rear_hook'];

export function typeLabel(t: string): string {
  return (TYPE_LABEL as Record<string, string>)[t] ?? t;
}
export function typeColor(t: string): string {
  return (TYPE_COLOR as Record<string, string>)[t] ?? '#94a3b8';
}

/**
 * Normalise a label from the labels CSV. Accepts v1 types, optionally suffixed
 * with a hand (`jab_L`), and legacy names (`hook_L`, `uppercut_R`, `kick`)
 * which are mapped to lead/rear via the stance (orthodox: L = lead).
 */
/** Non-strike annotations in label files (sync clap, calibration, round markers…). */
export const LABEL_MARKERS = new Set(['sync', 'cal_start', 'cal_end', 'round', 'rest', 'round_start', 'round_end', 'rest_start', 'rest_end', 'clinch_end', 'label', 'note', 'start', 'end', 'none', 'noise']);

export function parseLabel(raw: string, stance: string | null = 'orthodox'): { type: EventType | null; hand: 'L' | 'R' | null; marker?: boolean } {
  // Accept prefixes such as "truth:cross" (analysis/synth.py) or "video:jab_L".
  let s = raw.trim().toLowerCase().replace(/^[a-z]+:/, '').replace(/[\s-]+/g, '_');
  if (LABEL_MARKERS.has(s)) return { type: null, hand: null, marker: true };
  if (s === 'clinch_start') return { type: 'clinch', hand: null };
  let hand: 'L' | 'R' | null = null;
  const m = s.match(/^(.*)_(l|r)$/);
  if (m) { s = m[1]; hand = m[2].toUpperCase() as 'L' | 'R'; }
  if ((TYPES as readonly string[]).includes(s)) return { type: s as EventType, hand };
  const leadHand = stance === 'southpaw' ? 'R' : 'L';
  const side = hand ? (hand === leadHand ? 'lead' : 'rear') : null;
  if ((s === 'hook' || s === 'uppercut') && side) return { type: `${side}_${s}` as EventType, hand };
  if (s === 'straight' && side) return { type: side === 'lead' ? 'jab' : 'cross', hand };
  if (s === 'kick' || s === 'knee' || s === 'body_movement') return { type: 'kick_or_body_movement', hand: null };
  if (s === 'spin' || s === 'backfist') return { type: 'spinning_backfist', hand };
  return { type: null, hand };
}
