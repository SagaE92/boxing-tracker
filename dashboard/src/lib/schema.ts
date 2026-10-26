import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import schema from '../../../docs/session.schema.json';
import type { SessionJson } from './types';

export const SUPPORTED_MAJOR = 1;
export const SCHEMA_VERSION = '1.1.0';

const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);
const validateFn = ajv.compile(schema as object);

export interface ValidationResult { ok: boolean; data?: SessionJson; errors: string[]; warnings: string[] }

/** Validate parsed JSON against docs/session.schema.json with human-friendly messages. */
export function validateSession(input: unknown, fileName = 'session.json'): ValidationResult {
  const warnings: string[] = [];
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    return { ok: false, errors: [`${fileName}: expected a JSON object at the top level.`], warnings };
  }
  const v = (input as { schema_version?: unknown }).schema_version;
  if (typeof v !== 'string') {
    return { ok: false, errors: [`${fileName}: missing "schema_version". This dashboard reads schema ${SCHEMA_VERSION} (any 1.x).`], warnings };
  }
  const major = +v.split('.')[0];
  if (major !== SUPPORTED_MAJOR) {
    return {
      ok: false,
      errors: [`${fileName}: schema_version "${v}" is not supported. This dashboard reads ${SUPPORTED_MAJOR}.x (current ${SCHEMA_VERSION}). ${major > SUPPORTED_MAJOR ? 'Update the dashboard.' : 'Re-run analysis/detector.py to regenerate it.'}`],
      warnings,
    };
  }
  // Older minors (e.g. 1.0.0, no devices list) are a subset of the current schema: load silently.
  // A newer minor may carry fields this dashboard ignores: load with a note.
  const minor = +(v.split('.')[1] ?? 0), ourMinor = +SCHEMA_VERSION.split('.')[1];
  if (minor > ourMinor) warnings.push(`${fileName}: schema_version ${v} is newer than ${SCHEMA_VERSION}; loading anyway (same major), new fields are ignored.`);
  const ok = validateFn(input);
  if (!ok) {
    const errs = (validateFn.errors ?? []).slice(0, 8).map((e) => {
      const where = e.instancePath ? e.instancePath.replace(/^\//, '').replace(/\//g, '.') : '(top level)';
      let msg = e.message ?? 'is invalid';
      if (e.keyword === 'enum') msg = `must be one of ${(e.params as { allowedValues: unknown[] }).allowedValues.map((x) => JSON.stringify(x)).join(', ')}`;
      if (e.keyword === 'required') msg = `is missing required field "${(e.params as { missingProperty: string }).missingProperty}"`;
      return `${fileName}: ${where} ${msg}`;
    });
    const more = (validateFn.errors?.length ?? 0) - errs.length;
    if (more > 0) errs.push(`…and ${more} more problem(s).`);
    return { ok: false, errors: errs, warnings };
  }
  return { ok: true, data: input as SessionJson, errors: [], warnings };
}

export function parseSessionText(text: string, fileName = 'session.json'): ValidationResult {
  let obj: unknown;
  try {
    obj = JSON.parse(text);
  } catch (e) {
    return { ok: false, errors: [`${fileName}: not valid JSON (${(e as Error).message}).`], warnings: [] };
  }
  return validateSession(obj, fileName);
}
