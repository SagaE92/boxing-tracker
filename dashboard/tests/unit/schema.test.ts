import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import { parseSessionText, validateSession } from '../../src/lib/schema';

const demo = JSON.parse(fs.readFileSync(new URL('../../public/demo/demo_session.json', import.meta.url), 'utf8'));
const clone = () => JSON.parse(JSON.stringify(demo));

describe('session schema validation', () => {
  it('accepts the bundled demo sessions (incl. analysis/detector.py output)', () => {
    for (const f of ['demo-2026-10-10', 'demo-2026-10-17', 'demo']) {
      const j = JSON.parse(fs.readFileSync(new URL(`../../public/demo/${f}_session.json`, import.meta.url), 'utf8'));
      const r = validateSession(j, f);
      expect(r.errors).toEqual([]);
      expect(r.ok).toBe(true);
    }
  });
  it('rejects an unsupported major schema_version with a clear message', () => {
    const j = clone(); j.schema_version = '2.0.0';
    const r = validateSession(j);
    expect(r.ok).toBe(false);
    expect(r.errors[0]).toMatch(/not supported.*1\.x/);
  });
  it('warns but loads a newer minor version', () => {
    const j = clone(); j.schema_version = '1.1.0';
    const r = validateSession(j);
    expect(r.ok).toBe(true);
    expect(r.warnings[0]).toMatch(/1\.1\.0/);
  });
  it('reports a missing schema_version', () => {
    const j = clone(); delete j.schema_version;
    expect(validateSession(j).errors[0]).toMatch(/missing "schema_version"/);
  });
  it('reports missing required fields and bad enums by path', () => {
    const j = clone(); delete j.session.stance; j.punches[0].type = 'haymaker'; j.punches[1].confidence = 1.5;
    const r = validateSession(j, 's.json');
    expect(r.ok).toBe(false);
    const all = r.errors.join('\n');
    expect(all).toMatch(/session is missing required field "stance"/);
    expect(all).toMatch(/punches\.0\.type must be one of/);
    expect(all).toMatch(/punches\.1\.confidence/);
  });
  it('rejects non-objects and invalid JSON', () => {
    expect(validateSession([]).ok).toBe(false);
    expect(parseSessionText('{nope', 'bad.json').errors[0]).toMatch(/not valid JSON/);
  });
  it('accepts clinch and kick_or_body_movement as event types', () => {
    const types = new Set(demo.punches.map((p: { type: string }) => p.type));
    expect(types.has('clinch')).toBe(true);
    expect(types.has('kick_or_body_movement')).toBe(true);
  });
});
