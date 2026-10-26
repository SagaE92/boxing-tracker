// Athlete-view analytics: plain-language round-by-round summary built on the detector's
// session.json. Pure functions (unit tested in tests/unit/athlete.test.ts).
//
// Definitions used throughout the athlete view:
// * "Strikes" = punches (every strike type, incl. unknown) + kicks (kick_or_body_movement).
//   Clinch is time, not a strike. (Lab's "Strikes" counts punches only.)
// * Speed / impact averages use punches only (kicks have no speed estimate).
// * "Impact" is a 0-100+ score relative to the athlete's own baseline (IMPACT below):
//   100 x mean peak_g / baseline peak_g. Raw g stays in Lab. Clipped peaks count as their
//   recorded value; the lower-bound marker is a Lab-only detail.
// * Combo = 2+ punches whose peaks are less than COMBO_GAP_MS apart (stats.combos, the same
//   rule as Lab's combo panel). A kick or clinch ends a combo.
// * Lead/rear: from each strike's wrist (L/R) and the session stance (orthodox: L = lead).
import { combos } from './stats';
import { isStrike, type EventType } from './taxonomy';
import type { LoadedSession, SessionJson, StrikeEvent } from './types';

export const COMBO_GAP_MS = 600;
export const FINISH_ROUNDS = 3;

export const FRIENDLY = ['Jab', 'Cross', 'Hook', 'Uppercut', 'Overhand', 'Spinning backfist', 'Kick', 'Other'] as const;
export type Friendly = (typeof FRIENDLY)[number];
const MAP: Record<EventType, Friendly | null> = {
  jab: 'Jab', cross: 'Cross', lead_hook: 'Hook', rear_hook: 'Hook', lead_uppercut: 'Uppercut', rear_uppercut: 'Uppercut',
  overhand: 'Overhand', spinning_backfist: 'Spinning backfist', kick_or_body_movement: 'Kick', unknown: 'Other', clinch: null,
};
export const FRIENDLY_COLOR: Record<Friendly, string> = {
  Jab: '#38bdf8', Cross: '#f472b6', Hook: '#fb923c', Uppercut: '#a3e635', Overhand: '#c084fc',
  'Spinning backfist': '#f87171', Kick: '#2dd4bf', Other: '#64748b',
};
export const friendly = (t: string): Friendly | null => (t in MAP ? (MAP as Record<string, Friendly | null>)[t] : 'Other');

const avg = (a: number[]) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);
export const isKick = (e: StrikeEvent) => e.type === 'kick_or_body_movement';
export const isPunch = (e: StrikeEvent) => isStrike(e.type);
export const counts = (e: StrikeEvent) => isPunch(e) || isKick(e);

export type Side = 'lead' | 'rear';
export function sideOf(e: StrikeEvent, stance: string | null | undefined): Side | null {
  if (!e.hand) return null;
  const leadWrist = stance === 'southpaw' ? 'R' : 'L';
  return e.hand === leadWrist ? 'lead' : 'rear';
}
/** Two sensors (schema 1.1 devices) or punches seen from both wrists. */
export function hasBothHands(j: SessionJson): boolean {
  const d = j.session.devices ?? [];
  if (new Set(d.map((x) => x.hand).filter(Boolean)).size >= 2) return true;
  const w = new Set(j.punches.filter(isPunch).map((e) => e.hand).filter(Boolean));
  return w.size >= 2 && j.punches.filter(isPunch).filter((e) => e.hand).length > 0
    && Math.min(...['L', 'R'].map((h) => j.punches.filter((e) => isPunch(e) && e.hand === h).length)) >= 0.05 * j.punches.filter(isPunch).length;
}

export interface MixItem { label: Friendly; count: number; share: number }
export function mixOf(events: StrikeEvent[]): MixItem[] {
  const c = new Map<Friendly, number>();
  for (const e of events) { if (!counts(e)) continue; const f = friendly(e.type); if (f) c.set(f, (c.get(f) ?? 0) + 1); }
  const total = [...c.values()].reduce((a, b) => a + b, 0);
  return FRIENDLY.filter((f) => c.get(f)).map((f) => ({ label: f, count: c.get(f)!, share: total ? c.get(f)! / total : 0 }));
}

export interface AthleteRound {
  number: number; tStart: number; tEnd: number; durS: number;
  strikes: number; punches: number; kicks: number; perMin: number;
  /** impactG = mean peak_g of the punches (raw g, never shown in the athlete view);
   *  impact = impact score (100 x impactG / impactBase), null without a baseline. */
  speed: number | null; impactG: number | null; impact: number | null; impactBase: number | null; combos: number;
  lead: number; rear: number; leadShare: number | null;
  top: MixItem[]; mix: MixItem[]; events: StrikeEvent[];
  best: boolean; weakest: boolean;
}

export const impactScore = (g: number | null | undefined, base: number | null | undefined) =>
  g === null || g === undefined || !base ? null : (100 * g) / base;

export function athleteRounds(j: SessionJson, opts: { impactBase?: number | null; gapMs?: number } = {}): AthleteRound[] {
  const gapMs = opts.gapMs ?? COMBO_GAP_MS, base = opts.impactBase ?? null;
  const rounds = j.rounds.filter((r) => r.kind === 'round');
  const out = rounds.map((r, i) => {
    const ev = j.punches.filter((e) => e.t_peak_s >= r.t_start_s && e.t_peak_s < r.t_end_s);
    const p = ev.filter(isPunch), k = ev.filter(isKick);
    const durS = r.t_end_s - r.t_start_s;
    const strikes = p.length + k.length;
    const lead = p.filter((e) => sideOf(e, j.session.stance) === 'lead').length;
    const rear = p.filter((e) => sideOf(e, j.session.stance) === 'rear').length;
    const mix = mixOf(ev);
    return {
      number: i + 1, tStart: r.t_start_s, tEnd: r.t_end_s, durS, strikes, punches: p.length, kicks: k.length,
      perMin: durS > 0 ? strikes / (durS / 60) : 0,
      speed: avg(p.map((e) => e.speed_mps_est).filter((v): v is number => v != null)),
      impactG: avg(p.map((e) => e.peak_g)), impact: impactScore(avg(p.map((e) => e.peak_g)), base), impactBase: base,
      combos: combos(ev, gapMs).filter((c) => c.events.length >= 2).length,
      lead, rear, leadShare: lead + rear ? lead / (lead + rear) : null,
      top: [...mix].sort((a, b) => b.count - a.count).slice(0, 3), mix, events: ev, best: false, weakest: false,
    };
  });
  if (out.length >= 2) {
    // best = most strikes (ties: faster); weakest = fewest strikes (ties: slower)
    const key = (r: AthleteRound) => r.strikes + (r.speed ?? 0) / 1000;
    const best = out.reduce((a, b) => (key(b) > key(a) ? b : a));
    const weak = out.reduce((a, b) => (key(b) < key(a) ? b : a));
    if (best !== weak) { best.best = true; weak.weakest = true; }
  }
  return out;
}

export interface Agg {
  rounds: number[]; strikesPerRound: number; perMin: number; speed: number | null; impactG: number | null; impact: number | null;
  combosPerRound: number; kicksPerRound: number; hookShare: number; leadShare: number | null; mix: MixItem[];
}
function agg(rs: AthleteRound[]): Agg {
  const n = rs.length;
  const strikes = rs.reduce((a, r) => a + r.strikes, 0);
  const punches = rs.flatMap((r) => r.events.filter(isPunch));
  const ev = rs.flatMap((r) => r.events);
  const kicks = rs.reduce((a, r) => a + r.kicks, 0);
  const lead = rs.reduce((a, r) => a + r.lead, 0), rear = rs.reduce((a, r) => a + r.rear, 0);
  return {
    rounds: rs.map((r) => r.number), strikesPerRound: strikes / n,
    perMin: rs.reduce((a, r) => a + r.perMin, 0) / n,
    speed: avg(punches.map((e) => e.speed_mps_est).filter((v): v is number => v != null)),
    impactG: avg(punches.map((e) => e.peak_g)), impact: impactScore(avg(punches.map((e) => e.peak_g)), rs[0]?.impactBase),
    combosPerRound: rs.reduce((a, r) => a + r.combos, 0) / n, kicksPerRound: kicks / n,
    hookShare: strikes ? ev.filter((e) => friendly(e.type) === 'Hook').length / strikes : 0,
    leadShare: lead + rear ? lead / (lead + rear) : null, mix: mixOf(ev),
  };
}
export const pctChange = (a: number | null, b: number | null) => (a === null || b === null || a === 0 ? null : ((b - a) / a) * 100);

export interface Finish {
  n: number; label: string; first: Agg; last: Agg;
  /** percent changes, last vs first; leadSharePts in percentage points */
  change: { volume: number | null; speed: number | null; impact: number | null; combos: number | null; kicks: number | null; leadSharePts: number | null };
}
/** First N vs last N rounds: N = 3 with 6+ rounds, else half the rounds (rounded down); null with < 2 rounds. */
export function finishCompare(rs: AthleteRound[]): Finish | null {
  if (rs.length < 2) return null;
  const n = rs.length >= 2 * FINISH_ROUNDS ? FINISH_ROUNDS : Math.floor(rs.length / 2);
  const first = agg(rs.slice(0, n)), last = agg(rs.slice(-n));
  return {
    n, label: n === 1 ? 'First round vs last round' : `First ${n} vs last ${n} rounds`, first, last,
    change: {
      volume: pctChange(first.strikesPerRound, last.strikesPerRound), speed: pctChange(first.speed, last.speed),
      impact: pctChange(first.impactG, last.impactG), combos: pctChange(first.combosPerRound, last.combosPerRound),
      kicks: pctChange(first.kicksPerRound, last.kicksPerRound),
      leadSharePts: first.leadShare !== null && last.leadShare !== null ? (last.leadShare - first.leadShare) * 100 : null,
    },
  };
}

const r0 = (v: number) => Math.round(Math.abs(v));
const lastPhrase = (n: number) => (n === 1 ? 'in the last round' : `in the last ${n} rounds`);
const rangeText = (rs: number[]) => (rs.length === 1 ? `round ${rs[0]}` : `rounds ${rs[0]}–${rs[rs.length - 1]}`);

/** Thresholds for the takeaway rules (percent change, last N vs first N rounds). */
export const TAKEAWAY = { volume: 8, speed: 5 } as const;

/**
 * One-sentence takeaway, rule based:
 *  1. no strikes -> "No strikes …";  one round -> totals for that round
 *  2. output (strikes/round) down >= 8 % and/or speed down >= 5 % -> "…your output dropped X% and speed Y% in the last N rounds."
 *     prefixed "Strong start; " when the best round is in the first half
 *  3. output up >= 8 % -> "You finished strong: output up X% in the last N rounds."
 *  4. otherwise -> "Steady pace: output and speed held within X% from first to last rounds."
 */
export function takeaway(rs: AthleteRound[], f: Finish | null): string {
  const total = rs.reduce((a, r) => a + r.strikes, 0);
  if (!rs.length || total === 0) return 'No strikes recorded in this session.';
  if (!f) return `One round: ${total} strikes at ${Math.round(rs[0].perMin)} per minute.`;
  const v = f.change.volume ?? 0, s = f.change.speed ?? 0;
  const bestIdx = rs.findIndex((r) => r.best);
  const strongStart = bestIdx >= 0 && bestIdx < rs.length / 2;
  const volDown = v <= -TAKEAWAY.volume, spdDown = s <= -TAKEAWAY.speed;
  if (volDown || spdDown) {
    const parts = volDown && spdDown ? `your output dropped ${r0(v)}% and speed ${r0(s)}%`
      : volDown ? `your output dropped ${r0(v)}%` : `your speed dropped ${r0(s)}%`;
    const sentence = `${parts} ${lastPhrase(f.n)}.`;
    return strongStart ? `Strong start; ${sentence}` : sentence.charAt(0).toUpperCase() + sentence.slice(1);
  }
  if (v >= TAKEAWAY.volume) return `You finished strong: output up ${r0(v)}% ${lastPhrase(f.n)}${s >= TAKEAWAY.speed ? ` and speed up ${r0(s)}%` : ''}.`;
  const within = Math.max(r0(v), r0(s), 1);
  return `Steady pace: your output and speed held within ${within}% from the first to the last rounds.`;
}

/** Plain-language notes on what changed (biggest first), for "How you finished". */
export function finishNotes(f: Finish | null, bothHands: boolean): string[] {
  if (!f) return [];
  const notes: { w: number; t: string }[] = [];
  const last = rangeText(f.last.rounds);
  const v = f.change.volume;
  if (v !== null && Math.abs(v) >= 5) notes.push({ w: Math.abs(v), t: `${v < 0 ? 'Lower' : 'Higher'} output: ${f.first.strikesPerRound.toFixed(0)} strikes per round early, ${f.last.strikesPerRound.toFixed(0)} in ${last}.` });
  const s = f.change.speed;
  if (s !== null && Math.abs(s) >= 3) notes.push({ w: Math.abs(s) * 1.5, t: `Hands ${s < 0 ? 'slowed' : 'got faster'}: average speed ${s < 0 ? 'down' : 'up'} ${r0(s)}% (${f.first.speed!.toFixed(1)} → ${f.last.speed!.toFixed(1)} m/s).` });
  const im = f.change.impact;
  if (im !== null && Math.abs(im) >= 5) notes.push({ w: Math.abs(im), t: f.first.impact !== null && f.last.impact !== null
    ? `Impact ${im < 0 ? 'faded' : 'rose'}: ${Math.round(f.first.impact)} → ${Math.round(f.last.impact)} (${r0(im)}% ${im < 0 ? 'lower' : 'higher'} in ${last}).`
    : `Impact ${im < 0 ? 'faded' : 'rose'}: ${r0(im)}% ${im < 0 ? 'lower' : 'higher'} in ${last}.` });
  const hk = (f.last.hookShare - f.first.hookShare) * 100;
  if (Math.abs(hk) >= 3) notes.push({ w: Math.abs(hk) * 2, t: `${hk < 0 ? 'Fewer' : 'More'} hooks late: ${Math.round(f.first.hookShare * 100)}% of your strikes early, ${Math.round(f.last.hookShare * 100)}% in ${last}.` });
  // kicks per round (not share of strikes): "4.0 → 1.3 per round"
  const kd = f.change.kicks;
  if (f.first.kicksPerRound === 0 && f.last.kicksPerRound >= 1) notes.push({ w: 20, t: `Kicks came in late: ${f.last.kicksPerRound.toFixed(1)} per round in ${last}, none early.` });
  else if (kd !== null && kd <= -25) notes.push({ w: Math.abs(kd) / 4, t: `Kicks dropped off: ${f.first.kicksPerRound.toFixed(1)} → ${f.last.kicksPerRound.toFixed(1)} per round (${r0(kd)}% fewer in ${last}).` });
  else if (kd !== null && kd >= 25) notes.push({ w: kd / 4, t: `More kicks late: ${f.first.kicksPerRound.toFixed(1)} → ${f.last.kicksPerRound.toFixed(1)} per round in ${last}.` });
  const c = f.change.combos;
  if (c !== null && Math.abs(c) >= 10) notes.push({ w: Math.abs(c) / 1.5, t: `${c < 0 ? 'Fewer' : 'More'} combinations: ${f.first.combosPerRound.toFixed(0)} per round early, ${f.last.combosPerRound.toFixed(0)} in ${last}.` });
  if (bothHands && f.change.leadSharePts !== null && Math.abs(f.change.leadSharePts) >= 3) {
    const rearLate = Math.round((1 - f.last.leadShare!) * 100), rearEarly = Math.round((1 - f.first.leadShare!) * 100);
    notes.push({ w: Math.abs(f.change.leadSharePts) * 2, t: f.change.leadSharePts < 0
      ? `Lead hand faded more: your rear hand threw ${rearLate}% of punches in ${last} (${rearEarly}% early).`
      : `Rear hand faded more: your lead hand threw ${100 - rearLate}% of punches in ${last} (${100 - rearEarly}% early).` });
  }
  return notes.sort((a, b) => b.w - a.w).map((n) => n.t);
}

/** e.g. "Rear hand did 64% in rounds 8–10." (two hands only) */
export function handLine(rs: AthleteRound[], f: Finish | null): string | null {
  const lead = rs.reduce((a, r) => a + r.lead, 0), rear = rs.reduce((a, r) => a + r.rear, 0);
  if (!lead || !rear) return null;
  if (f && f.last.leadShare !== null && f.first.leadShare !== null && Math.abs(f.change.leadSharePts ?? 0) >= 3) {
    const rearLate = 1 - f.last.leadShare;
    const side = rearLate >= 0.5 ? 'Rear' : 'Lead';
    return `${side} hand did ${Math.round((side === 'Rear' ? rearLate : f.last.leadShare) * 100)}% in ${rangeText(f.last.rounds)}, up from ${Math.round((side === 'Rear' ? 1 - f.first.leadShare : f.first.leadShare) * 100)}% early.`;
  }
  const share = rear / (lead + rear);
  return `Balanced hands: lead ${Math.round((1 - share) * 100)}%, rear ${Math.round(share * 100)}% of punches.`;
}

export interface ComboItem { seq: string; count: number }
export function topCombos(events: StrikeEvent[], n = 5, gapMs = COMBO_GAP_MS): ComboItem[] {
  const m = new Map<string, number>();
  for (const c of combos(events, gapMs)) {
    if (c.events.length < 2) continue;
    const seq = c.events.map((e) => friendly(e.type) ?? 'Other').join(' → ');
    m.set(seq, (m.get(seq) ?? 0) + 1);
  }
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, n).map(([seq, count]) => ({ seq, count }));
}

export interface SessionOverview {
  key: string; name: string; date: Date; durationS: number; rounds: number; roundLenS: number | null;
  strikes: number; perMin: number; best: AthleteRound | null; lateDropPct: number | null; takeaway: string;
  /** mean peak_g of the opening rounds (raw g, for the impact baseline) */
  openingImpactG: number | null;
}
export function sessionOverview(s: LoadedSession): SessionOverview | null {
  const j = s.json;
  if (!j) return null;
  const rs = athleteRounds(j);
  const f = finishCompare(rs);
  const strikes = rs.length ? rs.reduce((a, r) => a + r.strikes, 0) : j.punches.filter(counts).length;
  const act = rs.reduce((a, r) => a + r.durS, 0) || j.session.duration_s;
  const lens = rs.map((r) => r.durS);
  return {
    key: s.key, name: s.name, date: new Date(j.session.start_time_iso), durationS: j.session.duration_s, rounds: rs.length,
    roundLenS: lens.length ? lens.reduce((a, b) => a + b, 0) / lens.length : null,
    strikes, perMin: act > 0 ? strikes / (act / 60) : 0, best: rs.find((r) => r.best) ?? null,
    lateDropPct: f?.change.volume ?? null, takeaway: takeaway(rs, f), openingImpactG: openingImpactG(rs),
  };
}

// ---- Impact score -------------------------------------------------------------------------
/**
 * Impact score: 100 x (mean peak wrist acceleration of the punches) / baseline.
 * Baseline ("your usual"), in this order:
 *  1. history: the median, over your IMPACT.maxSessions most recent EARLIER sessions that are loaded
 *     (at least IMPACT.minSessions of them, each with >= IMPACT.minPunches punches), of each
 *     session's opening-rounds mean peak (the same first-N rounds as "How you finished");
 *  2. otherwise this session's own opening rounds (so they score 100).
 * Only earlier sessions count, so a session's score does not change when you add newer ones.
 */
export const IMPACT = { minSessions: 2, maxSessions: 5, minPunches: 20 } as const;
export interface ImpactBaseline { g: number; source: 'history' | 'session'; sessions: number; text: string }

/** Mean peak_g of the punches in the opening rounds (first N as in finishCompare; 1 round: that round). */
export function openingImpactG(rs: AthleteRound[]): number | null {
  if (!rs.length) return null;
  const n = rs.length >= 2 * FINISH_ROUNDS ? FINISH_ROUNDS : Math.max(1, Math.floor(rs.length / 2));
  return avg(rs.slice(0, n).flatMap((r) => r.events.filter(isPunch).map((e) => e.peak_g)));
}
const median = (a: number[]) => { const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

export function impactBaseline(j: SessionJson, history: SessionJson[] = []): ImpactBaseline | null {
  const t = Date.parse(j.session.start_time_iso);
  const earlier = history
    .filter((h) => h !== j && Date.parse(h.session.start_time_iso) < t && h.punches.filter(isPunch).length >= IMPACT.minPunches)
    .sort((a, b) => Date.parse(b.session.start_time_iso) - Date.parse(a.session.start_time_iso))
    .slice(0, IMPACT.maxSessions)
    .map((h) => openingImpactG(athleteRounds(h)))
    .filter((v): v is number => v !== null && v > 0);
  if (earlier.length >= IMPACT.minSessions)
    return { g: median(earlier), source: 'history', sessions: earlier.length, text: `100 = your usual: the median of your opening rounds over your last ${earlier.length} sessions.` };
  const rs = athleteRounds(j);
  const own = openingImpactG(rs);
  if (own === null || own <= 0) return null;
  const n = rs.length >= 2 * FINISH_ROUNDS ? FINISH_ROUNDS : Math.max(1, Math.floor(rs.length / 2));
  return { g: own, source: 'session', sessions: 0, text: `100 = your ${n === 1 ? 'first round' : `first ${n} rounds`} today (open earlier sessions to compare with your usual).` };
}

/** Rounds with impact scores against the baseline (history of loaded sessions, else this session). */
export function athleteSession(j: SessionJson, history: SessionJson[] = []) {
  const base = impactBaseline(j, history);
  const rounds = athleteRounds(j, { impactBase: base?.g ?? null });
  return { rounds, finish: finishCompare(rounds), base };
}
