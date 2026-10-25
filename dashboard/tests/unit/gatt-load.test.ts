import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import { UUID, parsePunchEvent, parseRawPacket } from '../../src/lib/gatt';
import { fileKey, loadFiles } from '../../src/lib/load';
import { rawCsv } from './helpers';

describe('GATT wire format (bt_proto.h v1)', () => {
  it('builds 128-bit UUIDs from the base', () => {
    expect(UUID.service).toBe('6e7b0001-4b1d-4c8a-9a3e-2f5b0c1d7a00');
    expect(UUID.rawStream).toBe('6e7b0005-4b1d-4c8a-9a3e-2f5b0c1d7a00');
  });
  it('parses a raw packet with saturation masks', () => {
    const buf = new ArrayBuffer(18 + 2 * 12), dv = new DataView(buf);
    dv.setUint16(0, 7, true); dv.setUint8(2, 2); dv.setUint8(3, 0); dv.setUint32(4, 1000, true); dv.setUint16(8, 2404, true);
    dv.setUint32(10, 0b10, true); dv.setUint32(14, 0, true);
    dv.setInt16(18, 2049, true); dv.setInt16(18 + 4, -32768, true); dv.setInt16(18 + 6, 1000, true);
    dv.setInt16(30 + 4, 32100, true);
    const p = parseRawPacket(dv);
    expect(p.seq).toBe(7); expect(p.n).toBe(2);
    expect(p.samples[0].ax).toBeCloseTo(1.0, 2);
    expect(p.samples[0].az).toBeCloseTo(-15.99, 1);
    expect(p.samples[0].gx).toBeCloseTo(70, 5);
    expect(p.samples[1].t_us).toBe(3404);
    expect(p.samples[0].sat).toBe(false);
    expect(p.samples[1].sat).toBe(true);
  });
  it('rejects truncated packets', () => {
    const dv = new DataView(new ArrayBuffer(20)); dv.setUint8(2, 3);
    expect(() => parseRawPacket(dv)).toThrow(/declares 3 samples/);
  });
  it('parses a 16-byte punch event', () => {
    const dv = new DataView(new ArrayBuffer(16));
    dv.setUint16(0, 12, true); dv.setUint32(2, 61500, true); dv.setUint8(6, 3); dv.setUint8(7, 0x01 | (2 << 3));
    dv.setUint16(8, 1650, true); dv.setUint16(10, 812, true); dv.setUint8(14, 87);
    const e = parsePunchEvent(dv);
    expect(e).toMatchObject({ index: 12, t_s: 61.5, type: 'lead_hook', saturated: true, target: 'body', peak_g: 16.5, speed_mps: 8.12, confidence: 0.87 });
  });
});

describe('loadFiles', () => {
  const json = fs.readFileSync(new URL('../../public/demo/demo_session.json', import.meta.url), 'utf8');
  const file = (name: string, text: string) => ({ name, blob: new Blob([text]) });
  it('derives a session key from file names', () => {
    expect(fileKey('2026-10-24_raw.csv.gz')).toBe('2026-10-24');
    expect(fileKey('dir/2026-10-24-session.json')).toBe('2026-10-24');
    expect(fileKey('x_labels.csv')).toBe('x');
  });
  it('groups raw + session + labels by stem', async () => {
    const { sessions, errors } = await loadFiles([file('a_session.json', json), file('a_raw.csv', rawCsv(100)), file('a_labels.csv', 'host_time_s,label,note\n1792864801,jab_L,\n')]);
    expect(errors).toEqual([]);
    expect(sessions).toHaveLength(1);
    expect(sessions[0].raw!.n).toBe(100);
    expect(sessions[0].labels![0].t).toBeCloseTo(1, 2);
  });
  it('attaches differently named CSVs to the only session.json in the batch', async () => {
    const { sessions } = await loadFiles([file('foo.json', json), file('recording.csv', rawCsv(10))]);
    expect(sessions).toHaveLength(1);
    expect(sessions[0].raw).toBeTruthy();
  });
  it('reports unknown, empty and malformed files', async () => {
    const { sessions, errors } = await loadFiles([file('x.csv', 'a,b\n1,2\n'), file('e.csv', ''), file('bad_raw.csv', 'host_time_s,device_time_us,ax_g\n1,2,3\n'), file('v2.json', JSON.stringify({ ...JSON.parse(json), schema_version: '2.0.0' }))]);
    expect(sessions).toHaveLength(0);
    expect(errors.join('\n')).toMatch(/unrecognised file/);
    expect(errors.join('\n')).toMatch(/empty/);
    expect(errors.join('\n')).toMatch(/missing column/);
    expect(errors.join('\n')).toMatch(/2\.0\.0.*not supported/);
  });
  it('labels alone need a session', async () => {
    const { sessions, errors } = await loadFiles([file('z_labels.csv', 'host_time_s,label\n1,jab\n')]);
    expect(sessions).toHaveLength(0);
    expect(errors[0]).toMatch(/need a matching session/);
  });
});
