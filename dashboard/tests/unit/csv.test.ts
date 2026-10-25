import { describe, expect, it } from 'vitest';
import { gzipSync } from 'node:zlib';
import { ParseError, alignLabels, parseLabels, parseRaw, readText, sniffCsv, splitCsvLine, toCsv } from '../../src/lib/csv';
import { parseLabel } from '../../src/lib/taxonomy';
import { rawCsv } from './helpers';

describe('parseRaw', () => {
  it('parses columns, time base and |a|-1g', () => {
    const { raw, warnings } = parseRaw(rawCsv(100));
    expect(raw.n).toBe(100);
    expect(raw.t[0]).toBe(0);
    expect(raw.t[1]).toBeCloseTo(1 / 416, 5);
    expect(raw.amag[0]).toBeCloseTo(0, 6);
    expect(raw.hostT0).toBeCloseTo(1792864800, 3);
    expect(warnings).toEqual([]);
  });
  it('counts saturated samples', () => {
    const { raw } = parseRaw(rawCsv(100, { satEvery: 10 }));
    expect(raw.satCount).toBe(10);
    expect(raw.amag[0]).toBeCloseTo(15, 5);
  });
  it('unwraps a uint32 microsecond counter rollover', () => {
    const { raw } = parseRaw(rawCsv(50, { dev0: 2 ** 32 - 20 * 2404 }));
    for (let i = 1; i < raw.n; i++) expect(raw.t[i]).toBeGreaterThan(raw.t[i - 1]);
    expect(raw.t[49]).toBeCloseTo(49 / 416, 3);
  });
  it('rejects empty input and missing columns with friendly errors', () => {
    expect(() => parseRaw('')).toThrow(ParseError);
    expect(() => parseRaw('host_time_s,device_time_us,ax_g\n1,2,3\n')).toThrow(/missing column/);
    expect(() => parseRaw('host_time_s,device_time_us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,sat\n')).toThrow(/no data rows/);
  });
  it('skips malformed rows with a warning', () => {
    const csv = rawCsv(10) + 'garbage,row\n' + '1,2,x,0,0,0,0,0,0\n';
    const { raw, warnings } = parseRaw(csv);
    expect(raw.n).toBe(10);
    expect(warnings[0]).toMatch(/Skipped 2 malformed/);
  });
  it('fails when every row is malformed', () => {
    expect(() => parseRaw('host_time_s,device_time_us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,sat\na,b,c,d,e,f,g,h,i\n')).toThrow(/No valid rows/);
  });
  it('handles CRLF line endings and missing sat column', () => {
    const csv = 'host_time_s,device_time_us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps\r\n1,0,0,0,1,0,0,0\r\n1.1,2404,0,0,1,0,0,0\r\n';
    const { raw, warnings } = parseRaw(csv);
    expect(raw.n).toBe(2);
    expect(warnings.some((w) => /sat/.test(w))).toBe(true);
  });
});

describe('labels', () => {
  it('parses labels, quoted notes and unknown labels', () => {
    const { rows, warnings } = parseLabels('host_time_s,label,note\n10.5,jab_L,"combo, 1-2"\n11,lead_hook,\n12,banana,\n');
    expect(rows).toHaveLength(3);
    expect(rows[0].note).toBe('combo, 1-2');
    expect(warnings.join()).toMatch(/banana/);
  });
  it('rejects empty and headerless files', () => {
    expect(() => parseLabels('')).toThrow(/empty/);
    expect(() => parseLabels('time,what\n1,jab\n')).toThrow(/host_time_s/);
  });
  it('maps legacy and hand-suffixed labels via stance', () => {
    expect(parseLabel('jab_L')).toEqual({ type: 'jab', hand: 'L' });
    expect(parseLabel('hook_L', 'orthodox')).toEqual({ type: 'lead_hook', hand: 'L' });
    expect(parseLabel('hook_L', 'southpaw')).toEqual({ type: 'rear_hook', hand: 'L' });
    expect(parseLabel('uppercut_R')).toEqual({ type: 'rear_uppercut', hand: 'R' });
    expect(parseLabel('kick').type).toBe('kick_or_body_movement');
    expect(parseLabel('Clinch').type).toBe('clinch');
    expect(parseLabel('nonsense').type).toBeNull();
    expect(parseLabel('truth:rear_hook')).toEqual({ type: 'rear_hook', hand: null });
    expect(parseLabel('clinch_start').type).toBe('clinch');
    expect(parseLabel('sync')).toEqual({ type: null, hand: null, marker: true });
    expect(parseLabel('cal_end').marker).toBe(true);
  });
  it('aligns to the raw host clock, else to start_time_iso', () => {
    const rows = [{ host: 1792864810, rawLabel: 'jab_L', note: '' }];
    expect(alignLabels(rows, { hostT0: 1792864800 })[0].t).toBeCloseTo(10);
    expect(alignLabels(rows, { startIso: new Date(1792864800 * 1000).toISOString() })[0].t).toBeCloseTo(10);
    expect(alignLabels([{ host: 5, rawLabel: 'jab', note: '' }], {})[0].t).toBe(5);
  });
});

describe('misc csv', () => {
  it('sniffs file kinds', () => {
    expect(sniffCsv(rawCsv(1))).toBe('raw');
    expect(sniffCsv('\uFEFFhost_time_s,label,note\n')).toBe('labels');
    expect(sniffCsv('punch_id,t_peak_s\n')).toBe('punches_csv');
    expect(sniffCsv('a,b\n')).toBe('unknown');
  });
  it('splits and escapes CSV', () => {
    expect(splitCsvLine('a,"b,c","d""e"')).toEqual(['a', 'b,c', 'd"e']);
    expect(toCsv(['x', 'y'], [['a,b', null], [1, true]])).toBe('x,y\n"a,b",\n1,true\n');
  });
  it('reads gzip by magic bytes and plain text otherwise', async () => {
    const text = rawCsv(5);
    expect(await readText(new Blob([gzipSync(text)]), 'x.csv.gz')).toBe(text);
    expect(await readText(new Blob([text]), 'already-decoded.csv.gz')).toBe(text);
  });
});
