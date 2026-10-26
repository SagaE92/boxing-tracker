import { describe, expect, it } from 'vitest';
import { athleteRounds, athleteSession, finishCompare, finishNotes, friendly, handLine, hasBothHands, impactBaseline, impactScore, mixOf, openingImpactG, sessionOverview, takeaway, topCombos } from '../../src/lib/athlete';
import { niceScale } from '../../src/lib/nice';
import type { Round, SessionJson, StrikeEvent } from '../../src/lib/types';
import { ev } from './helpers';

/** n rounds of 180 s with 60 s rests; spec(k) gives the events of round k (times relative to its start). */
function session(n: number, spec: (k: number) => StrikeEvent[], devices = false, start = '2026-10-26T06:30:00Z'): SessionJson {
  const rounds: Round[] = [];
  const punches: StrikeEvent[] = [];
  for (let k = 0; k < n; k++) {
    const t0 = 10 + k * 240;
    rounds.push({ index: rounds.length, t_start_s: t0, t_end_s: t0 + 180, kind: 'round' });
    if (k < n - 1) rounds.push({ index: rounds.length, t_start_s: t0 + 180, t_end_s: t0 + 240, kind: 'rest' });
    for (const e of spec(k)) punches.push({ ...e, t_peak_s: e.t_peak_s + t0, t_start_s: e.t_start_s + t0, t_end_s: e.t_end_s + t0, round_index: k });
  }
  return {
    schema_version: '1.1.0', generator: { name: 'test', version: '0' },
    session: { id: 's', start_time_iso: start, duration_s: n * 240, sample_rate_hz: 416, accel_range_g: 16, gyro_range_dps: 2000,
      hand_worn: null, hand: null, stance: 'orthodox',
      devices: devices ? [{ device_id: 'a', hand: 'lead', wrist: 'L' }, { device_id: 'b', hand: 'rear', wrist: 'R' }] : undefined },
    detector_params: { threshold_g: 3.5, refractory_ms: 150, window_ms: 150 }, rounds, punches,
    summary: { punch_count: 0, punches_per_min: 0, punches_per_round: [], mean_peak_g: null, max_peak_g: null, mean_speed_mps_est: null, max_speed_mps_est: null, by_type: {}, by_hand: {}, saturated_sample_fraction: 0 },
  };
}
/** `count` strikes 2 s apart (no combos) of alternating jab (L) / cross (R), plus `kicks` kicks. */
function steady(count: number, opts: { speed?: number; peak?: number; kicks?: number; leadEvery?: number; combos?: number } = {}): StrikeEvent[] {
  const out: StrikeEvent[] = [];
  for (let i = 0; i < count; i++) {
    const lead = i % (opts.leadEvery ?? 2) === 0;
    out.push(ev(2 + i * 1.5, lead ? 'jab' : 'cross', { hand: lead ? 'L' : 'R', speed_mps_est: opts.speed ?? 5, peak_g: opts.peak ?? 8 }));
  }
  for (let c = 0; c < (opts.combos ?? 0); c++) { // 2-punch combos 0.4 s apart, late in the round
    out.push(ev(150 + c * 2, 'lead_hook', { hand: 'L', speed_mps_est: opts.speed ?? 5, peak_g: opts.peak ?? 8 }));
    out.push(ev(150.4 + c * 2, 'rear_hook', { hand: 'R', speed_mps_est: opts.speed ?? 5, peak_g: opts.peak ?? 8 }));
  }
  for (let i = 0; i < (opts.kicks ?? 0); i++) out.push(ev(100 + i * 5, 'kick_or_body_movement', { hand: null, speed_mps_est: null, peak_g: 2 }));
  return out;
}

describe('athlete round stats', () => {
  const j = session(3, (k) => steady([40, 30, 20][k], { kicks: [3, 2, 0][k], combos: [4, 2, 0][k], speed: [6, 5, 4][k], peak: [10, 9, 8][k] }));
  const rs = athleteRounds(j);
  it('counts punches + kicks per round, pace, speed, impact and combos', () => {
    expect(rs).toHaveLength(3);
    expect(rs[0]).toMatchObject({ number: 1, punches: 48, kicks: 3, strikes: 51, combos: 4 });
    expect(rs[0].perMin).toBeCloseTo(51 / 3);
    expect(rs[0].speed).toBeCloseTo(6);
    expect(rs[0].impactG).toBeCloseTo(10);
    expect(rs[0].impact).toBeNull(); // no baseline passed
    expect(rs[2]).toMatchObject({ strikes: 20, kicks: 0, combos: 0 });
  });
  it('marks best and weakest rounds', () => {
    expect(rs.map((r) => [r.best, r.weakest])).toEqual([[true, false], [false, false], [false, true]]);
  });
  it('top types use friendly labels (hooks merged)', () => {
    expect(rs[0].top.map((t) => t.label)).toEqual(['Jab', 'Cross', 'Hook']);
    expect(rs[0].top[2].count).toBe(8);
  });
  it('excludes clinch from strikes', () => {
    const k = session(1, () => [ev(5, 'jab'), ev(20, 'clinch', { t_start_s: 18, t_end_s: 26, speed_mps_est: null })]);
    expect(athleteRounds(k)[0].strikes).toBe(1);
  });
});

describe('friendly labels and mix', () => {
  it('maps the taxonomy to athlete labels', () => {
    expect(['jab', 'cross', 'lead_hook', 'rear_hook', 'lead_uppercut', 'rear_uppercut', 'overhand', 'spinning_backfist', 'kick_or_body_movement', 'unknown', 'clinch'].map(friendly))
      .toEqual(['Jab', 'Cross', 'Hook', 'Hook', 'Uppercut', 'Uppercut', 'Overhand', 'Spinning backfist', 'Kick', 'Other', null]);
  });
  it('mix shares sum to 1 and ignore clinch', () => {
    const m = mixOf([ev(1, 'jab'), ev(2, 'lead_hook'), ev(3, 'rear_hook'), ev(4, 'kick_or_body_movement'), ev(9, 'clinch')]);
    expect(m.map((x) => [x.label, x.count])).toEqual([['Jab', 1], ['Hook', 2], ['Kick', 1]]);
    expect(m.reduce((a, x) => a + x.share, 0)).toBeCloseTo(1);
  });
  it('top combos read as sequences of friendly labels', () => {
    const c = topCombos([ev(1, 'jab'), ev(1.4, 'cross'), ev(5, 'jab'), ev(5.4, 'cross'), ev(5.8, 'lead_hook'), ev(9, 'jab'), ev(9.3, 'cross')]);
    expect(c[0]).toEqual({ seq: 'Jab → Cross', count: 2 });
    expect(c[1]).toEqual({ seq: 'Jab → Cross → Hook', count: 1 });
  });
});

describe('first 3 vs last 3', () => {
  // 10 rounds: steady for 7, then a late fade with fewer kicks/combos and more rear hand
  const j = session(10, (k) => (k < 7
    ? steady(60, { speed: 6, peak: 10, kicks: 4, combos: 10 })
    : steady(42, { speed: 5.4, peak: 8.5, kicks: 1, combos: 4, leadEvery: 3 })), true);
  const rs = athleteRounds(j);
  const f = finishCompare(rs)!;
  it('compares the first 3 with the last 3 rounds', () => {
    expect(f.n).toBe(3);
    expect(f.label).toBe('First 3 vs last 3 rounds');
    expect(f.first.rounds).toEqual([1, 2, 3]);
    expect(f.last.rounds).toEqual([8, 9, 10]);
    expect(f.first.strikesPerRound).toBe(84);
    expect(f.last.strikesPerRound).toBe(51);
    expect(f.change.volume).toBeCloseTo(((51 - 84) / 84) * 100);
    expect(f.change.speed).toBeCloseTo(-10, 0);
    expect(f.change.impact).toBeCloseTo(-15, 0);
    expect(f.change.combos).toBeCloseTo(-60);
    expect(f.first.kicksPerRound).toBe(4);
    expect(f.last.kicksPerRound).toBe(1);
    expect(f.change.kicks).toBeCloseTo(-75);
    expect(f.change.leadSharePts).toBeLessThan(0);
  });
  it('falls back to halves with fewer than 6 rounds, and null with < 2', () => {
    expect(finishCompare(athleteRounds(session(5, () => steady(10))))!.n).toBe(2);
    expect(finishCompare(athleteRounds(session(2, () => steady(10))))!.label).toBe('First round vs last round');
    expect(finishCompare(athleteRounds(session(1, () => steady(10))))).toBeNull();
  });
  it('explains the change in plain language', () => {
    const notes = finishNotes(f, true).join(' ');
    expect(notes).toMatch(/Lower output: 84 strikes per round early, 51 in rounds 8–10/);
    expect(notes).toMatch(/Kicks dropped off: 4\.0 → 1\.0 per round \(75% fewer in rounds 8–10\)/);
    expect(notes).toMatch(/Fewer combinations/);
    expect(notes).toMatch(/Lead hand faded more: your rear hand threw \d+% of punches in rounds 8–10/);
    expect(notes).not.toMatch(/power|force|confidence|clip|saturat/i);
  });
  it('hand line names the hand that carried the late rounds', () => {
    expect(handLine(rs, f)).toMatch(/^Rear hand did \d+% in rounds 8–10, up from 50% early\.$/);
    expect(hasBothHands(j)).toBe(true);
  });
});

describe('takeaway', () => {
  const fade = (vol: number[], spd: number[]) => athleteRounds(session(vol.length, (k) => steady(vol[k], { speed: spd[k] })));
  it('strong start + output and speed drop', () => {
    const rs = fade([50, 48, 46, 45, 44, 40, 39, 30, 28, 26], [6, 6, 6, 6, 5.9, 5.8, 5.7, 5.5, 5.5, 5.4]);
    const t = takeaway(rs, finishCompare(rs));
    expect(t).toMatch(/^Strong start; your output dropped (\d+)% and speed (\d+)% in the last 3 rounds\.$/);
    const [, v, s] = t.match(/dropped (\d+)% and speed (\d+)%/)!;
    expect(+v).toBe(Math.round(((48 - 28) / 48) * 100));
    expect(+s).toBe(Math.round(((6 - 5.4667) / 6) * 100));
  });
  it('speed-only drop without a strong start', () => {
    const rs = fade([40, 40, 40, 41, 42, 43], [6, 6, 6, 5.2, 5.2, 5.2]);
    expect(takeaway(rs, finishCompare(rs))).toBe('Your speed dropped 13% in the last 3 rounds.');
  });
  it('finishing strong and steady pace', () => {
    const up = fade([30, 30, 30, 40, 40, 40], [5, 5, 5, 5, 5, 5]);
    expect(takeaway(up, finishCompare(up))).toBe('You finished strong: output up 33% in the last 3 rounds.');
    const flat = fade([40, 41, 40, 40, 39, 40], [5, 5, 5, 5, 5, 5]);
    expect(takeaway(flat, finishCompare(flat))).toMatch(/^Steady pace: your output and speed held within \d+% /);
  });
  it('one round and empty sessions', () => {
    const one = fade([30], [5]);
    expect(takeaway(one, finishCompare(one))).toBe('One round: 30 strikes at 10 per minute.');
    expect(takeaway([], null)).toBe('No strikes recorded in this session.');
  });
  it('never uses Lab-only or banned words', () => {
    const rs = fade([50, 48, 46, 30, 28, 26], [6, 6, 6, 5.4, 5.4, 5.4]);
    expect(takeaway(rs, finishCompare(rs))).not.toMatch(/power|force|confidence|clip|saturat|csv/i);
  });
});

describe('session overview (history)', () => {
  it('summarises a loaded session', () => {
    const j = session(6, (k) => steady(k < 3 ? 40 : 30));
    const o = sessionOverview({ key: 'k', name: 's', files: [], json: j, errors: [], warnings: [] })!;
    expect(o).toMatchObject({ rounds: 6, strikes: 210, roundLenS: 180 });
    expect(o.lateDropPct).toBeCloseTo(-25);
    expect(o.perMin).toBeCloseTo(210 / 18);
  });
});

describe('kicks per round in the finish notes', () => {
  it('reports kicks that only came late', () => {
    const j = session(6, (k) => steady(30, { kicks: k < 3 ? 0 : 2 }));
    expect(finishNotes(finishCompare(athleteRounds(j)), false).join(' ')).toMatch(/Kicks came in late: 2\.0 per round in rounds 4–6, none early/);
  });
});

describe('impact score', () => {
  const day = (d: number) => `2026-10-${String(d).padStart(2, '0')}T18:00:00Z`;
  const at = (d: number, peak: number, n = 6) => session(n, () => steady(30, { peak }), false, day(d));
  it('is 100 x mean peak / baseline', () => {
    expect(impactScore(8.8, 8)).toBeCloseTo(110);
    expect(impactScore(null, 8)).toBeNull();
    expect(impactScore(8, null)).toBeNull();
  });
  it('without history, 100 = this session\'s opening rounds', () => {
    const j = session(6, (k) => steady(30, { peak: k < 3 ? 10 : 8 }));
    const { rounds, finish, base } = athleteSession(j, [j]);
    expect(base).toMatchObject({ source: 'session', g: 10 });
    expect(base!.text).toMatch(/first 3 rounds today/);
    expect(rounds.map((r) => Math.round(r.impact!))).toEqual([100, 100, 100, 80, 80, 80]);
    expect(finish!.first.impact).toBeCloseTo(100);
    expect(finish!.last.impact).toBeCloseTo(80);
    expect(finish!.change.impact).toBeCloseTo(-20);
  });
  it('with 2+ earlier sessions, 100 = the median of their opening rounds', () => {
    const cur = at(26, 9);
    const hist = [at(10, 7), at(17, 8), at(24, 12), at(27, 20) /* later: ignored */, cur];
    const b = impactBaseline(cur, hist)!;
    expect(b).toMatchObject({ source: 'history', sessions: 3, g: 8 });
    expect(b.text).toMatch(/last 3 sessions/);
    expect(athleteSession(cur, hist).rounds[0].impact).toBeCloseTo(112.5);
  });
  it('uses at most the 5 most recent earlier sessions and needs 2', () => {
    const hist = [at(1, 100), at(2, 6), at(3, 6), at(4, 8), at(5, 8), at(6, 8)];
    expect(impactBaseline(at(9, 8), hist)).toMatchObject({ source: 'history', sessions: 5, g: 8 });
    expect(impactBaseline(at(9, 8), [at(1, 6)])!.source).toBe('session');
  });
  it('opening rounds follow the finish comparison (3, half, or the only round)', () => {
    expect(openingImpactG(athleteRounds(session(4, (k) => steady(10, { peak: [6, 8, 10, 10][k] }))))).toBeCloseTo(7);
    expect(openingImpactG(athleteRounds(session(1, () => steady(10, { peak: 9 }))))).toBeCloseTo(9);
    expect(openingImpactG([])).toBeNull();
  });
});

describe('nice axis ticks', () => {
  it('rounds percentage ticks to whole steps', () => {
    expect(niceScale([72, 118]).ticks).toEqual([60, 80, 100, 120]);
    expect(niceScale([61, 100, 112]).ticks).toEqual([60, 80, 100, 120]);
    expect(niceScale([90, 101, 100]).ticks).toEqual([90, 95, 100, 105]);
    expect(niceScale([-38, -5, 0]).ticks).toEqual([-40, -30, -20, -10, 0]);
    expect(niceScale([55, 104]).ticks.length).toBeLessThanOrEqual(5);
  });
});
