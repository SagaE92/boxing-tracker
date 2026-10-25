import type { LabelRow, LoadedSession, RawData, Round, SessionJson, StrikeEvent } from './types';
import { DURATION_TYPES, HOOKS, NON_STRIKE, TYPES, isStrike, type EventType } from './taxonomy';

export const mean = (a: number[]) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);
export const maxOf = (a: number[]) => (a.length ? Math.max(...a) : null);
export const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);

/** Least-squares fit y = a + b x. */
export function linfit(xs: number[], ys: number[]): { a: number; b: number } | null {
  const n = xs.length;
  if (n < 2) return null;
  const mx = sum(xs) / n, my = sum(ys) / n;
  let sxx = 0, sxy = 0;
  for (let i = 0; i < n; i++) { sxx += (xs[i] - mx) ** 2; sxy += (xs[i] - mx) * (ys[i] - my); }
  if (sxx === 0) return null;
  const b = sxy / sxx;
  return { a: my - b * mx, b };
}

export interface Filters {
  types: string[]; // empty = all
  minConfidence: number;
  minPeakG: number;
  tMin: number | null;
  tMax: number | null;
  hand: 'all' | 'L' | 'R';
  target: 'all' | 'head' | 'body';
  round: number | 'all';
  saturatedOnly: boolean;
  includeNonStrike: boolean; // include kick_or_body_movement / clinch in totals
}
export const defaultFilters = (): Filters => ({
  types: [], minConfidence: 0, minPeakG: 0, tMin: null, tMax: null,
  hand: 'all', target: 'all', round: 'all', saturatedOnly: false, includeNonStrike: false,
});
export function filtersActive(f: Filters) {
  return f.types.length > 0 || f.minConfidence > 0 || f.minPeakG > 0 || f.tMin !== null || f.tMax !== null || f.hand !== 'all' || f.target !== 'all' || f.round !== 'all' || f.saturatedOnly;
}

/** Events passing the filters. Non-strike events pass only if includeNonStrike or explicitly selected by type. */
export function applyFilters(events: StrikeEvent[], f: Filters): StrikeEvent[] {
  return events.filter((e) => {
    if (f.types.length) { if (!f.types.includes(e.type)) return false; } else if (!f.includeNonStrike && !isStrike(e.type)) return false;
    if (e.confidence < f.minConfidence) return false;
    if (e.peak_g < f.minPeakG) return false;
    if (f.tMin !== null && e.t_peak_s < f.tMin) return false;
    if (f.tMax !== null && e.t_peak_s > f.tMax) return false;
    if (f.hand !== 'all' && e.hand !== f.hand) return false;
    if (f.target !== 'all' && e.target !== f.target) return false;
    if (f.round !== 'all' && e.round_index !== f.round) return false;
    if (f.saturatedOnly && !e.saturated) return false;
    return true;
  });
}

export interface SummaryStats {
  strikes: number; nonStrike: number; kicks: number; clinches: number; clinchTimeS: number;
  activeTimeS: number; perMin: number;
  /** Mean over all strikes; clipped strikes contribute their lower bound, so if any are clipped this is itself a lower bound. */
  meanPeak: number | null; maxPeak: number | null; maxPeakSaturated: boolean;
  /** Mean over strikes that did not clip (exact values only). */
  meanPeakUnclipped: number | null; maxPeakUnclipped: number | null; unclippedStrikes: number;
  meanSpeed: number | null; maxSpeed: number | null;
  byType: Record<string, number>; byHand: { L: number; R: number; unknown: number };
  byTarget: { head: number; body: number; unknown: number };
  saturatedStrikes: number; meanConfidence: number | null; lowConfidence: number;
}

export function activeTime(json: SessionJson | undefined, duration: number): number {
  const r = json?.rounds.filter((x) => x.kind === 'round') ?? [];
  return r.length ? sum(r.map((x) => x.t_end_s - x.t_start_s)) : duration;
}

/** Summary over a set of events. Strike metrics use strikes only, unless includeNonStrike. */
export function summarize(events: StrikeEvent[], activeTimeS: number, includeNonStrike = false): SummaryStats {
  const counted = events.filter((e) => includeNonStrike || isStrike(e.type));
  const strikes = counted.filter((e) => !DURATION_TYPES.has(e.type));
  const peaks = strikes.map((e) => e.peak_g);
  const speeds = strikes.map((e) => e.speed_mps_est).filter((v): v is number => v !== null && v !== undefined);
  const byType: Record<string, number> = {};
  for (const t of TYPES) byType[t] = 0;
  for (const e of events) byType[e.type] = (byType[e.type] ?? 0) + 1;
  const byHand = { L: 0, R: 0, unknown: 0 }, byTarget = { head: 0, body: 0, unknown: 0 };
  for (const e of strikes) { byHand[e.hand ?? 'unknown']++; byTarget[e.target ?? 'unknown']++; }
  const maxPeak = maxOf(peaks);
  const clin = events.filter((e) => e.type === 'clinch');
  return {
    strikes: counted.filter((e) => e.type !== 'clinch').length,
    nonStrike: events.filter((e) => NON_STRIKE.has(e.type)).length,
    kicks: events.filter((e) => e.type === 'kick_or_body_movement').length,
    clinches: clin.length, clinchTimeS: sum(clin.map((e) => e.t_end_s - e.t_start_s)),
    activeTimeS, perMin: activeTimeS > 0 ? strikes.length / (activeTimeS / 60) : 0,
    meanPeak: mean(peaks), maxPeak, maxPeakSaturated: strikes.some((e) => e.saturated && e.peak_g === maxPeak),
    meanPeakUnclipped: mean(strikes.filter((e) => !e.saturated).map((e) => e.peak_g)),
    maxPeakUnclipped: maxOf(strikes.filter((e) => !e.saturated).map((e) => e.peak_g)),
    unclippedStrikes: strikes.filter((e) => !e.saturated).length,
    meanSpeed: mean(speeds), maxSpeed: maxOf(speeds), byType, byHand, byTarget,
    saturatedStrikes: strikes.filter((e) => e.saturated).length,
    meanConfidence: mean(strikes.map((e) => e.confidence)),
    lowConfidence: strikes.filter((e) => e.confidence < 0.5).length,
  };
}

export interface RoundStats {
  round: Round; number: number; strikes: number; perMin: number; restAfterS: number | null;
  meanPeak: number | null; maxPeak: number | null; meanSpeed: number | null;
  /** clipped strikes in the round; maxPeakSat = the round's max is a clipped lower bound */
  clipped: number; maxPeakSat: boolean;
  withinPeakChangePct: number | null; withinSpeedChangePct: number | null; nonStrike: number;
}
/** Round-by-round breakdown with within-round decline (linear fit start→end). */
export function roundStats(json: SessionJson, events: StrikeEvent[]): RoundStats[] {
  const rounds = json.rounds.filter((r) => r.kind === 'round');
  return rounds.map((r, i) => {
    const ev = events.filter((e) => e.t_peak_s >= r.t_start_s && e.t_peak_s < r.t_end_s);
    const st = ev.filter((e) => isStrike(e.type));
    const dur = r.t_end_s - r.t_start_s;
    const rest = json.rounds.find((x) => x.kind === 'rest' && Math.abs(x.t_start_s - r.t_end_s) < 1);
    const within = (vals: (number | null)[]) => {
      const xs: number[] = [], ys: number[] = [];
      st.forEach((e, k) => { const v = vals[k]; if (v !== null && v !== undefined) { xs.push(e.t_peak_s - r.t_start_s); ys.push(v); } });
      const f = xs.length >= 6 ? linfit(xs, ys) : null;
      if (!f || f.a <= 0) return null;
      return ((f.b * dur) / f.a) * 100;
    };
    const speeds = st.map((e) => e.speed_mps_est).filter((v): v is number => v != null);
    return {
      round: r, number: i + 1, strikes: st.length, perMin: dur > 0 ? st.length / (dur / 60) : 0,
      restAfterS: rest ? rest.t_end_s - rest.t_start_s : null,
      meanPeak: mean(st.map((e) => e.peak_g)), maxPeak: maxOf(st.map((e) => e.peak_g)), meanSpeed: mean(speeds),
      clipped: st.filter((e) => e.saturated).length,
      maxPeakSat: st.some((e) => e.saturated && e.peak_g === maxOf(st.map((x) => x.peak_g))),
      withinPeakChangePct: within(st.map((e) => e.peak_g)), withinSpeedChangePct: within(st.map((e) => e.speed_mps_est)),
      nonStrike: ev.length - st.length,
    };
  });
}

export interface Fatigue {
  firstPeak: number | null; lastPeak: number | null; peakDropPct: number | null;
  firstSpeed: number | null; lastSpeed: number | null; speedDropPct: number | null;
  firstRate: number | null; lastRate: number | null; rateDropPct: number | null;
  peakTrend: { a: number; b: number } | null; speedTrend: { a: number; b: number } | null;
}
const pctDrop = (a: number | null, b: number | null) => (a && b !== null ? ((a - b) / a) * 100 : null);
/** First vs last round, plus linear trend over rounds (x = round number). */
export function fatigue(rs: RoundStats[]): Fatigue {
  const valid = rs.filter((r) => r.strikes > 0);
  const f = valid[0], l = valid[valid.length - 1];
  const pk = valid.filter((r) => r.meanPeak !== null), sp = valid.filter((r) => r.meanSpeed !== null);
  return {
    firstPeak: f?.meanPeak ?? null, lastPeak: l?.meanPeak ?? null, peakDropPct: valid.length > 1 ? pctDrop(f.meanPeak, l.meanPeak) : null,
    firstSpeed: f?.meanSpeed ?? null, lastSpeed: l?.meanSpeed ?? null, speedDropPct: valid.length > 1 ? pctDrop(f.meanSpeed, l.meanSpeed) : null,
    firstRate: f?.perMin ?? null, lastRate: l?.perMin ?? null, rateDropPct: valid.length > 1 ? pctDrop(f.perMin, l.perMin) : null,
    peakTrend: linfit(pk.map((r) => r.number), pk.map((r) => r.meanPeak as number)),
    speedTrend: linfit(sp.map((r) => r.number), sp.map((r) => r.meanSpeed as number)),
  };
}

export interface Combo { events: StrikeEvent[]; seq: string }
/** Group strikes whose peaks are less than gapMs apart. Non-strike events break combos. */
export function combos(events: StrikeEvent[], gapMs = 600): Combo[] {
  const out: Combo[] = [];
  let cur: StrikeEvent[] = [];
  const flush = () => { if (cur.length) out.push({ events: cur, seq: cur.map((e) => e.type).join('>') }); cur = []; };
  for (const e of [...events].sort((a, b) => a.t_peak_s - b.t_peak_s)) {
    if (!isStrike(e.type)) { flush(); continue; }
    if (cur.length && (e.t_peak_s - cur[cur.length - 1].t_peak_s) * 1000 > gapMs) flush();
    cur.push(e);
  }
  flush();
  return out;
}
export function comboStats(cs: Combo[]) {
  const lengths: Record<string, number> = { '1': 0, '2': 0, '3': 0, '4+': 0 };
  const seqs = new Map<string, number>();
  for (const c of cs) {
    const n = c.events.length;
    lengths[n >= 4 ? '4+' : String(n)]++;
    if (n >= 2) seqs.set(c.seq, (seqs.get(c.seq) ?? 0) + 1);
  }
  const top = [...seqs.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  const multi = cs.filter((c) => c.events.length >= 2);
  return { lengths, top, comboCount: multi.length, meanLength: mean(multi.map((c) => c.events.length)), strikesInCombos: sum(multi.map((c) => c.events.length)) };
}

// ---------------- saturation severity (one scheme for clipped strikes and saturated samples) ----------------
export type Level = 'ok' | 'warn' | 'bad';
/** Any clipping = amber "warn". Red "bad" once peak-g stats are substantially biased:
 *  >= 10 % of strikes clipped, or >= 1 % of raw samples saturated. Documented in TIPS.saturation and TESTING.md. */
export const SAT_THRESHOLDS = { clippedStrikeShareBad: 0.1, satSampleFractionBad: 0.01 } as const;
export function clippedStrikeLevel(clipped: number, strikes: number): Level {
  if (!clipped) return 'ok';
  return strikes > 0 && clipped / strikes >= SAT_THRESHOLDS.clippedStrikeShareBad ? 'bad' : 'warn';
}
export function satSampleLevel(fraction: number): Level {
  if (!(fraction > 0)) return 'ok';
  return fraction >= SAT_THRESHOLDS.satSampleFractionBad ? 'bad' : 'warn';
}
export const worst = (...l: Level[]): Level => (l.includes('bad') ? 'bad' : l.includes('warn') ? 'warn' : 'ok');

export interface DataQuality {
  samples: number; expected: number; droppedEst: number; droppedPct: number;
  gaps: { t: number; dur: number }[]; maxGapS: number;
  measuredHz: number | null; jitterUs: number | null;
  satSamples: number; satFraction: number; saturatedStrikes: number; strikes: number;
  satLevel: Level; clipLevel: Level; saturationLevel: Level;
  calibrated: boolean | null; confHist: number[]; lowConfShare: number | null;
  issues: { level: 'warn' | 'bad' | 'info'; text: string }[];
}
/** Data-quality analysis from raw (if loaded) and session.json. */
export function dataQuality(json: SessionJson | undefined, raw: RawData | undefined, events: StrikeEvent[]): DataQuality {
  const fs = json?.session.sample_rate_hz ?? 416;
  const gaps: { t: number; dur: number }[] = [];
  let measuredHz: number | null = null, jitterUs: number | null = null, expected = 0, droppedEst = 0;
  if (raw && raw.n > 1) {
    const nominal = 1 / fs;
    let s1 = 0, s2 = 0, k = 0;
    for (let i = 1; i < raw.n; i++) {
      const dt = raw.t[i] - raw.t[i - 1];
      if (dt > 1.5 * nominal) { gaps.push({ t: raw.t[i - 1], dur: dt }); droppedEst += Math.round(dt / nominal) - 1; }
      else { s1 += dt; s2 += dt * dt; k++; }
    }
    const span = raw.t[raw.n - 1] - raw.t[0];
    measuredHz = k ? 1 / (s1 / k) : null;
    jitterUs = k ? Math.sqrt(Math.max(0, s2 / k - (s1 / k) ** 2)) * 1e6 : null;
    expected = Math.round(span * fs) + 1;
  }
  const satSamples = raw ? raw.satCount : Math.round((json?.summary.saturated_sample_fraction ?? 0) * (json ? json.session.duration_s * fs : 0));
  const satFraction = raw ? raw.satCount / raw.n : json?.summary.saturated_sample_fraction ?? 0;
  const strikes = events.filter((e) => isStrike(e.type));
  const confHist = new Array(10).fill(0);
  for (const e of strikes) confHist[Math.min(9, Math.floor(e.confidence * 10))]++;
  const lowConfShare = strikes.length ? strikes.filter((e) => e.confidence < 0.5).length / strikes.length : null;
  const saturatedStrikes = strikes.filter((e) => e.saturated).length;
  const calibrated = json ? !!json.session.calibration : null;
  const issues: DataQuality['issues'] = [];
  const range = json?.session.accel_range_g ?? 16;
  const satLevel = satSampleLevel(satFraction), clipLevel = clippedStrikeLevel(saturatedStrikes, strikes.length);
  const saturationLevel = worst(satLevel, clipLevel);
  if (saturationLevel !== 'ok') {
    const samp = `${(satFraction * 100).toFixed(3)}% of samples are saturated`;
    const text = saturatedStrikes
      ? `${saturatedStrikes} of ${strikes.length} strike(s) (${((saturatedStrikes / Math.max(1, strikes.length)) * 100).toFixed(1)}%) clipped at ±${range} g; ${samp}. Their peak g is a lower bound (≥).`
      : `${samp} (outside detected strikes).`;
    issues.push({ level: saturationLevel, text: saturationLevel === 'bad' ? `${text} Peak-g stats are substantially biased; consider the high-g IMU path.` : text });
  }
  if (gaps.length) issues.push({ level: gaps.some((g) => g.dur > 1) ? 'bad' : 'warn', text: `${gaps.length} BLE gap(s) in the raw stream, ~${droppedEst} sample(s) lost (longest ${(Math.max(...gaps.map((g) => g.dur)) * 1000).toFixed(0)} ms). Strikes inside gaps may be missed.` });
  if (measuredHz && Math.abs(measuredHz - fs) / fs > 0.02) issues.push({ level: 'warn', text: `Measured sample rate ${measuredHz.toFixed(1)} Hz differs from nominal ${fs} Hz.` });
  if (calibrated === false) issues.push({ level: 'warn', text: 'No guard-pose calibration: axis-dependent features (type, target) are less reliable.' });
  if (lowConfShare !== null && lowConfShare > 0.25) issues.push({ level: 'warn', text: `${Math.round(lowConfShare * 100)}% of strikes have confidence < 0.5.` });
  if (!raw && json) issues.push({ level: 'info', text: 'Raw CSV not loaded: gap, jitter and waveform checks unavailable.' });
  return {
    samples: raw?.n ?? 0, expected, droppedEst, droppedPct: expected ? (droppedEst / expected) * 100 : 0,
    gaps, maxGapS: gaps.length ? Math.max(...gaps.map((g) => g.dur)) : 0, measuredHz, jitterUs,
    satSamples, satFraction, saturatedStrikes, strikes: strikes.length, satLevel, clipLevel, saturationLevel, calibrated, confHist, lowConfShare, issues,
  };
}

// ---------------- Label review ----------------
export interface MatchResult {
  classes: EventType[];
  /** confusion[labelClass][predClass] for matched pairs */
  confusion: Record<string, Record<string, number>>;
  missed: Record<string, number>; // labels with no detection, by label class
  falsePos: Record<string, number>; // detections with no label, by predicted class
  tp: number; fp: number; fn: number; precision: number | null; recall: number | null; f1: number | null;
  perClass: { cls: EventType; labelled: number; predicted: number; correct: number; recall: number | null; precision: number | null }[];
  hookRecall: number | null; hookLabelled: number; hookCorrect: number;
  typeAccuracy: number | null; handAccuracy: number | null; meanAbsDtMs: number | null;
  pairs: { label: LabelRow; event: StrikeEvent; dt: number }[];
}
/**
 * Match labels to detected events one-to-one, greedily by smallest |dt| within tolMs.
 * Duration events (clinch) match a label anywhere inside [t_start - tol, t_end + tol].
 */
export function matchLabels(events: StrikeEvent[], labels: LabelRow[], tolMs = 200): MatchResult {
  const tol = tolMs / 1000;
  const L = labels.filter((l) => l.type !== null);
  const cand: { li: number; ei: number; d: number }[] = [];
  // events sorted by time for windowed search
  const ev = [...events].sort((a, b) => a.t_start_s - b.t_start_s);
  for (let li = 0; li < L.length; li++) {
    const t = L[li].t;
    for (let ei = 0; ei < ev.length; ei++) {
      const e = ev[ei];
      if (e.t_start_s - tol > t) break;
      let d: number;
      if (DURATION_TYPES.has(e.type) || L[li].type === 'clinch') {
        d = t >= e.t_start_s - tol && t <= e.t_end_s + tol ? Math.abs(t - e.t_peak_s) * 0.001 : Infinity;
        if (DURATION_TYPES.has(e.type) !== (L[li].type === 'clinch')) d = Math.abs(t - e.t_peak_s) <= tol ? Math.abs(t - e.t_peak_s) : Infinity;
      } else d = Math.abs(t - e.t_peak_s);
      if (d <= tol) cand.push({ li, ei, d });
    }
  }
  cand.sort((a, b) => a.d - b.d);
  const usedL = new Set<number>(), usedE = new Set<number>();
  const pairs: MatchResult['pairs'] = [];
  for (const c of cand) {
    if (usedL.has(c.li) || usedE.has(c.ei)) continue;
    usedL.add(c.li); usedE.add(c.ei);
    pairs.push({ label: L[c.li], event: ev[c.ei], dt: ev[c.ei].t_peak_s - L[c.li].t });
  }
  const present = new Set<string>();
  L.forEach((l) => present.add(l.type as string));
  ev.forEach((e) => present.add(e.type));
  const classes = TYPES.filter((t) => present.has(t));
  const confusion: Record<string, Record<string, number>> = {};
  const missed: Record<string, number> = {}, falsePos: Record<string, number> = {};
  for (const a of classes) { confusion[a] = {}; for (const b of classes) confusion[a][b] = 0; missed[a] = 0; falsePos[a] = 0; }
  for (const p of pairs) confusion[p.label.type as string][p.event.type]++;
  L.forEach((l, i) => { if (!usedL.has(i)) missed[l.type as string]++; });
  ev.forEach((e, i) => { if (!usedE.has(i)) falsePos[e.type]++; });
  const tp = pairs.length, fp = ev.length - tp, fn = L.length - tp;
  const precision = ev.length ? tp / ev.length : null, recall = L.length ? tp / L.length : null;
  const f1 = precision !== null && recall !== null && precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : null;
  const perClass = classes.map((cls) => {
    const labelled = L.filter((l) => l.type === cls).length;
    const predicted = ev.filter((e) => e.type === cls).length;
    const correct = confusion[cls][cls];
    return { cls, labelled, predicted, correct, recall: labelled ? correct / labelled : null, precision: predicted ? correct / predicted : null };
  });
  const hookLabelled = L.filter((l) => HOOKS.includes(l.type as EventType)).length;
  const hookCorrect = HOOKS.reduce((a, h) => a + (confusion[h]?.[h] ?? 0), 0);
  const handPairs = pairs.filter((p) => p.label.hand && p.event.hand);
  return {
    classes, confusion, missed, falsePos, tp, fp, fn, precision, recall, f1, perClass,
    hookRecall: hookLabelled ? hookCorrect / hookLabelled : null, hookLabelled, hookCorrect,
    typeAccuracy: tp ? pairs.filter((p) => p.label.type === p.event.type).length / tp : null,
    handAccuracy: handPairs.length ? handPairs.filter((p) => p.label.hand === p.event.hand).length / handPairs.length : null,
    meanAbsDtMs: tp ? (sum(pairs.map((p) => Math.abs(p.dt))) / tp) * 1000 : null,
    pairs,
  };
}

// ---------------- Trends ----------------
export interface SessionTrend {
  key: string; name: string; date: Date; strikes: number; perMin: number;
  meanPeak: number | null; maxPeak: number | null; maxPeakSat: boolean; clipped: number; meanSpeed: number | null; maxSpeed: number | null;
  byType: Record<string, number>; fat: Fatigue; rounds: RoundStats[]; nonStrike: number; satFraction: number;
}
export function sessionTrend(s: LoadedSession): SessionTrend | null {
  const j = s.json;
  if (!j) return null;
  const act = activeTime(j, j.session.duration_s);
  const sm = summarize(j.punches, act);
  const rs = roundStats(j, j.punches);
  return {
    key: s.key, name: s.name, date: new Date(j.session.start_time_iso), strikes: sm.strikes, perMin: sm.perMin,
    meanPeak: sm.meanPeak, maxPeak: sm.maxPeak, maxPeakSat: sm.maxPeakSaturated, clipped: sm.saturatedStrikes, meanSpeed: sm.meanSpeed, maxSpeed: sm.maxSpeed,
    byType: sm.byType, fat: fatigue(rs), rounds: rs, nonStrike: sm.nonStrike,
    satFraction: s.raw ? s.raw.satCount / s.raw.n : j.summary.saturated_sample_fraction,
  };
}
export function personalBests(ts: SessionTrend[]) {
  const best = <K extends keyof SessionTrend>(k: K) => {
    let b: SessionTrend | null = null;
    for (const t of ts) { const v = t[k] as unknown as number | null; if (v !== null && (!b || v > (b[k] as unknown as number))) b = t; }
    return b;
  };
  return { maxPeak: best('maxPeak'), maxSpeed: best('maxSpeed'), strikes: best('strikes'), perMin: best('perMin') };
}

// ---------------- formatting ----------------
/** Peak g text. `lowerBound` = the value is (or includes) a clipped peak, so the true value is at least this: "≥18.5". */
export const peakText = (v: number | null | undefined, lowerBound: boolean, d = 1) => (v === null || v === undefined || !Number.isFinite(v) ? '—' : `${lowerBound ? '≥' : ''}${v.toFixed(d)}`);
export const fmt = (v: number | null | undefined, d = 1, unit = '') => (v === null || v === undefined || !Number.isFinite(v) ? '—' : `${v.toFixed(d)}${unit}`);
export const pct = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(d)}%`);
export function fmtTime(s: number, withMs = false): string {
  const neg = s < 0; s = Math.abs(s);
  const m = Math.floor(s / 60), sec = s - m * 60;
  const ss = withMs ? sec.toFixed(2).padStart(5, '0') : Math.floor(sec).toString().padStart(2, '0');
  return `${neg ? '-' : ''}${m}:${ss}`;
}
