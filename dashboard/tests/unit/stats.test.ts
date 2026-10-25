import { describe, expect, it } from 'vitest';
import { clippedStrikeLevel, satSampleLevel, worst, applyFilters, combos, comboStats, dataQuality, defaultFilters, fatigue, linfit, matchLabels, peakText, roundStats, summarize } from '../../src/lib/stats';
import { eventsCsv, summaryCsv } from '../../src/lib/exporters';
import { decimate, envelope, satRuns } from '../../src/lib/decimate';
import { parseRaw } from '../../src/lib/csv';
import type { LabelRow, SessionJson } from '../../src/lib/types';
import { ev, rawCsv } from './helpers';

const lab = (t: number, type: LabelRow['type'], hand: LabelRow['hand'] = 'L'): LabelRow => ({ t, rawLabel: String(type), type, hand, note: '' });

describe('summarize', () => {
  const events = [ev(1, 'jab', { peak_g: 4 }), ev(2, 'lead_hook', { peak_g: 16.2, saturated: true, speed_mps_est: 9 }), ev(3, 'kick_or_body_movement', { peak_g: 30, hand: null }),
    ev(10, 'clinch', { t_start_s: 8, t_end_s: 14, peak_g: 2, speed_mps_est: null, hand: null })];
  it('excludes kick/clinch from strike totals and means', () => {
    const s = summarize(events, 60);
    expect(s.strikes).toBe(2);
    expect(s.perMin).toBeCloseTo(2);
    expect(s.meanPeak).toBeCloseTo(10.1);
    expect(s.maxPeak).toBeCloseTo(16.2);
    expect(s.maxPeakSaturated).toBe(true);
    expect(s.maxSpeed).toBe(9);
    expect(s.kicks).toBe(1);
    expect(s.clinches).toBe(1);
    expect(s.clinchTimeS).toBe(6);
    expect(s.saturatedStrikes).toBe(1);
  });
  it('reports unclipped mean separately from the mean incl. clipped lower bounds', () => {
    const s = summarize(events, 60);
    expect(s.meanPeakUnclipped).toBe(4);
    expect(s.unclippedStrikes).toBe(1);
    expect(s.maxPeakUnclipped).toBe(4);
    expect(peakText(s.maxPeak, s.maxPeakSaturated)).toBe('≥16.2');
    expect(peakText(s.maxPeakUnclipped, false)).toBe('4.0');
    expect(peakText(null, true)).toBe('—');
  });
  it('exports clipped columns in CSV', () => {
    const csv = eventsCsv(events.slice(0, 2)).split('\n');
    expect(csv[0]).toContain('peak_g,clipped,peak_g_text');
    expect(csv[2]).toContain('16.2,true,>=16.2');
    expect(csv[1]).toContain('4,false,4');
    const sc = summaryCsv('x', summarize(events, 60));
    expect(sc).toContain('mean_peak_g_unclipped,4');
    expect(sc).toContain('mean_peak_g_incl_clipped_is_lower_bound,true');
    expect(sc).toContain('max_peak_g_clipped,true');
    expect(sc).toContain('clipped_strikes,1');
  });
  it('can include kick events when asked (clinch never counts as a strike)', () => {
    const s = summarize(events, 60, true);
    expect(s.strikes).toBe(3);
    expect(s.maxPeak).toBe(30);
  });
  it('handles zero events', () => {
    const s = summarize([], 0);
    expect(s.strikes).toBe(0);
    expect(s.perMin).toBe(0);
    expect(s.meanPeak).toBeNull();
  });
});

describe('filters', () => {
  const events = [ev(1, 'jab', { confidence: 0.3 }), ev(2, 'cross', { hand: 'R', peak_g: 9 }), ev(3, 'kick_or_body_movement'), ev(4, 'jab', { saturated: true, round_index: 2 })];
  it('defaults exclude non-strike events', () => expect(applyFilters(events, defaultFilters())).toHaveLength(3));
  it('filters by confidence, hand, peak, saturation, round and time', () => {
    expect(applyFilters(events, { ...defaultFilters(), minConfidence: 0.5 })).toHaveLength(2);
    expect(applyFilters(events, { ...defaultFilters(), hand: 'R' })).toHaveLength(1);
    expect(applyFilters(events, { ...defaultFilters(), minPeakG: 8 })).toHaveLength(1);
    expect(applyFilters(events, { ...defaultFilters(), saturatedOnly: true })).toHaveLength(1);
    expect(applyFilters(events, { ...defaultFilters(), round: 2 })).toHaveLength(1);
    expect(applyFilters(events, { ...defaultFilters(), tMin: 1.5, tMax: 3.5 })).toHaveLength(1);
  });
  it('explicit type selection can show non-strike events', () => {
    expect(applyFilters(events, { ...defaultFilters(), types: ['kick_or_body_movement'] })).toHaveLength(1);
  });
});

describe('rounds, fatigue, combos', () => {
  const json = {
    rounds: [{ index: 0, t_start_s: 0, t_end_s: 60, kind: 'round' }, { index: 1, t_start_s: 60, t_end_s: 90, kind: 'rest' }, { index: 2, t_start_s: 90, t_end_s: 150, kind: 'round' }],
  } as unknown as SessionJson;
  const events = [
    ...Array.from({ length: 10 }, (_, i) => ev(i * 5 + 1, 'jab', { peak_g: 10 - i * 0.2, speed_mps_est: 8 })),
    ...Array.from({ length: 5 }, (_, i) => ev(91 + i * 10, 'jab', { peak_g: 8, speed_mps_est: 6, round_index: 2 })),
  ];
  const rs = roundStats(json, events);
  it('computes per-round stats and rest length', () => {
    expect(rs.map((r) => r.strikes)).toEqual([10, 5]);
    expect(rs[0].perMin).toBe(10);
    expect(rs[0].restAfterS).toBe(30);
    expect(rs[1].restAfterS).toBeNull();
    expect(rs[0].withinPeakChangePct!).toBeLessThan(0); // declines within round 1
    expect(rs[1].withinPeakChangePct).toBeNull(); // <6 strikes: not fitted
  });
  it('computes first→last drop and trends', () => {
    const f = fatigue(rs);
    expect(f.speedDropPct).toBeCloseTo(25);
    expect(f.peakDropPct!).toBeGreaterThan(0);
    expect(f.peakTrend!.b).toBeLessThan(0);
  });
  it('linfit recovers a line', () => {
    const f = linfit([0, 1, 2, 3], [1, 3, 5, 7])!;
    expect(f.a).toBeCloseTo(1); expect(f.b).toBeCloseTo(2);
    expect(linfit([1], [1])).toBeNull();
  });
  it('groups combos by gap and breaks on kicks', () => {
    const cs = combos([ev(0, 'jab'), ev(0.3, 'cross'), ev(0.7, 'lead_hook'), ev(2, 'jab'), ev(2.3, 'kick_or_body_movement'), ev(2.5, 'jab')], 600);
    expect(cs.map((c) => c.events.length)).toEqual([3, 1, 1]);
    expect(cs[0].seq).toBe('jab>cross>lead_hook');
    const st = comboStats(cs);
    expect(st.lengths['3']).toBe(1);
    expect(st.comboCount).toBe(1);
    expect(st.top[0]).toEqual(['jab>cross>lead_hook', 1]);
  });
});

describe('matchLabels', () => {
  it('matches one-to-one within tolerance and builds the confusion matrix', () => {
    const events = [ev(1.0, 'jab'), ev(2.0, 'lead_hook'), ev(3.0, 'jab'), ev(9.0, 'cross', { hand: 'R' })];
    const labels = [lab(1.05, 'jab'), lab(2.1, 'lead_hook'), lab(3.02, 'lead_hook'), lab(5, 'rear_hook', 'R'), lab(1.1, 'jab')];
    const m = matchLabels(events, labels, 200);
    expect(m.tp).toBe(3);
    expect(m.fn).toBe(2);
    expect(m.fp).toBe(1);
    expect(m.precision).toBeCloseTo(0.75);
    expect(m.recall).toBeCloseTo(0.6);
    expect(m.confusion.lead_hook.jab).toBe(1);
    expect(m.confusion.jab.jab).toBe(1);
    expect(m.missed.jab).toBe(1);
    expect(m.missed.rear_hook).toBe(1);
    expect(m.falsePos.cross).toBe(1);
    expect(m.hookLabelled).toBe(3);
    expect(m.hookCorrect).toBe(1);
    expect(m.hookRecall).toBeCloseTo(1 / 3);
    const lh = m.perClass.find((p) => p.cls === 'lead_hook')!;
    expect(lh.recall).toBeCloseTo(0.5);
  });
  it('tolerance changes the result', () => {
    const m = matchLabels([ev(1, 'jab')], [lab(1.3, 'jab')], 200);
    expect(m.tp).toBe(0);
    expect(matchLabels([ev(1, 'jab')], [lab(1.3, 'jab')], 400).tp).toBe(1);
  });
  it('matches clinch labels anywhere inside the clinch span', () => {
    const m = matchLabels([ev(20, 'clinch', { t_start_s: 15, t_end_s: 25 })], [lab(16, 'clinch', null)], 200);
    expect(m.confusion.clinch.clinch).toBe(1);
  });
  it('ignores labels whose type is unrecognised', () => {
    const m = matchLabels([ev(1, 'jab')], [{ t: 1, rawLabel: 'x', type: null, hand: null, note: '' }], 200);
    expect(m.fn).toBe(0);
    expect(m.recall).toBeNull();
  });
});

describe('data quality and decimation', () => {
  it('finds BLE gaps, estimates dropped samples and sample rate', () => {
    const { raw } = parseRaw(rawCsv(2000, { gapAt: 1000, gapLen: 100, satEvery: 500 }));
    const dq = dataQuality(undefined, raw, []);
    expect(dq.gaps).toHaveLength(1);
    expect(dq.droppedEst).toBe(100);
    expect(dq.measuredHz!).toBeCloseTo(416, 0);
    expect(dq.satSamples).toBe(3); // sample 1000 fell inside the gap
    expect(dq.issues.some((i) => /gap/.test(i.text))).toBe(true);
  });
  it('uses one amber/red scheme for clipped strikes and saturated samples', () => {
    expect(clippedStrikeLevel(0, 100)).toBe('ok');
    expect(clippedStrikeLevel(9, 100)).toBe('warn');
    expect(clippedStrikeLevel(10, 100)).toBe('bad');
    expect(satSampleLevel(0)).toBe('ok');
    expect(satSampleLevel(0.0015)).toBe('warn');
    expect(satSampleLevel(0.01)).toBe('bad');
    expect(worst('warn', 'ok')).toBe('warn');
    expect(worst('warn', 'bad')).toBe('bad');
    const json = { session: { sample_rate_hz: 416, accel_range_g: 16, calibration: {}, duration_s: 100 }, summary: { saturated_sample_fraction: 0.002 } } as unknown as SessionJson;
    const evs = [ev(1, 'jab', { saturated: true }), ...Array.from({ length: 19 }, (_, i) => ev(2 + i, 'jab'))];
    const dq = dataQuality(json, undefined, evs);
    expect(dq.saturationLevel).toBe('warn');
    expect(dq.issues.filter((i) => /clipped|saturated/.test(i.text))).toHaveLength(1);
    const dq2 = dataQuality(json, undefined, evs.slice(0, 5));
    expect(dq2.saturationLevel).toBe('bad');
  });
  it('flags missing calibration and clipped strikes', () => {
    const json = { session: { sample_rate_hz: 416, accel_range_g: 16, calibration: null, duration_s: 10 }, summary: { saturated_sample_fraction: 0 } } as unknown as SessionJson;
    const dq = dataQuality(json, undefined, [ev(1, 'jab', { saturated: true })]);
    expect(dq.calibrated).toBe(false);
    expect(dq.issues.map((i) => i.text).join()).toMatch(/calibration/);
    expect(dq.issues.map((i) => i.text).join()).toMatch(/clipped/);
  });
  it('min/max decimation preserves extremes and bounds point count', () => {
    const n = 100000, t = new Float64Array(n), y = new Float32Array(n);
    for (let i = 0; i < n; i++) { t[i] = i / 416; y[i] = Math.sin(i / 50); }
    y[54321] = 42; y[12345] = -42;
    const d = decimate(t, [y], 0, t[n - 1], 500);
    expect(d.x.length).toBeLessThanOrEqual(1002);
    expect(Math.max(...(d.ys[0] as number[]))).toBe(42);
    expect(Math.min(...(d.ys[0] as number[]))).toBe(-42);
    for (let i = 1; i < d.x.length; i++) expect(d.x[i]).toBeGreaterThanOrEqual(d.x[i - 1]);
  });
  it('returns raw samples when zoomed in and breaks lines at gaps', () => {
    const { raw } = parseRaw(rawCsv(500, { gapAt: 200, gapLen: 50 }));
    const d = decimate(raw.t, [raw.amag], 0, 2, 2000, 3 / 416);
    expect(d.ys[0].filter((v) => v === null)).toHaveLength(1);
  });
  it('envelope and saturation runs', () => {
    const { raw } = parseRaw(rawCsv(1000, { satEvery: 400 }));
    expect(envelope(raw, 10).x).toHaveLength(10);
    expect(satRuns(raw)).toHaveLength(3);
  });
});
