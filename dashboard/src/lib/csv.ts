import type { LabelRow, RawData } from './types';
import { parseLabel } from './taxonomy';

export const RAW_COLUMNS = ['host_time_s', 'device_time_us', 'ax_g', 'ay_g', 'az_g', 'gx_dps', 'gy_dps', 'gz_dps', 'sat'] as const;
export const LABEL_COLUMNS = ['host_time_s', 'label', 'note'] as const;

export class ParseError extends Error {}

/** Read a File/Blob as text, transparently gunzipping `.gz` or gzip-magic content. */
export async function readText(blob: Blob, name = ''): Promise<string> {
  const head = new Uint8Array(await blob.slice(0, 2).arrayBuffer());
  void name; // decide by magic bytes: servers may already have decoded a .gz
  const gz = head[0] === 0x1f && head[1] === 0x8b;
  if (!gz) return blob.text();
  if (typeof DecompressionStream === 'undefined') throw new ParseError('This browser cannot decompress .gz files; unzip it first.');
  const stream = blob.stream().pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).text();
}

export type CsvKind = 'raw' | 'labels' | 'punches_csv' | 'unknown';
export function sniffCsv(text: string): CsvKind {
  const first = firstLine(text).toLowerCase().replace(/\s/g, '');
  if (first.startsWith('host_time_s,device_time_us')) return 'raw';
  if (first.startsWith('host_time_s,label')) return 'labels';
  if (first.startsWith('punch_id,')) return 'punches_csv';
  return 'unknown';
}
function firstLine(text: string) {
  const i = text.indexOf('\n');
  return (i < 0 ? text : text.slice(0, i)).replace(/^\uFEFF/, '').trim();
}

/** Parse the bleak logger CSV into columnar arrays. Throws ParseError with a friendly message. */
export function parseRaw(text: string): { raw: RawData; warnings: string[] } {
  const warnings: string[] = [];
  if (!text.trim()) throw new ParseError('The raw CSV is empty.');
  const header = firstLine(text).split(',').map((s) => s.trim());
  const idx = RAW_COLUMNS.map((c) => header.indexOf(c));
  const missing = RAW_COLUMNS.filter((_, i) => idx[i] < 0 && RAW_COLUMNS[i] !== 'sat');
  if (missing.length) throw new ParseError(`Raw CSV header is missing column(s): ${missing.join(', ')}. Expected: ${RAW_COLUMNS.join(',')}`);
  // Count lines for allocation.
  let cap = 0;
  for (let p = text.indexOf('\n'); p >= 0; p = text.indexOf('\n', p + 1)) cap++;
  cap += 1;
  const t = new Float64Array(cap), ax = new Float32Array(cap), ay = new Float32Array(cap), az = new Float32Array(cap);
  const gx = new Float32Array(cap), gy = new Float32Array(cap), gz = new Float32Array(cap), amag = new Float32Array(cap);
  const sat = new Uint8Array(cap);
  let n = 0, bad = 0, firstBad = '', hostT0 = NaN, dev0 = NaN, wrap = 0, prevDev = NaN, satCount = 0, nonMono = 0;
  let pos = text.indexOf('\n') + 1;
  if (pos === 0) throw new ParseError('The raw CSV has a header but no data rows.');
  const [iH, iD, iAx, iAy, iAz, iGx, iGy, iGz, iS] = idx;
  while (pos < text.length) {
    let end = text.indexOf('\n', pos);
    if (end < 0) end = text.length;
    const line = text.slice(pos, end);
    pos = end + 1;
    if (!line.trim()) continue;
    const f = line.split(',');
    const host = +f[iH], dev = +f[iD];
    const vals = [+f[iAx], +f[iAy], +f[iAz], +f[iGx], +f[iGy], +f[iGz]];
    if (!Number.isFinite(host) || !Number.isFinite(dev) || vals.some((v) => !Number.isFinite(v))) {
      bad++; if (!firstBad) firstBad = line.slice(0, 80); continue;
    }
    if (Number.isNaN(dev0)) { dev0 = dev; hostT0 = host; prevDev = dev; }
    if (dev < prevDev) { if (prevDev - dev > 2 ** 31) wrap += 2 ** 32; else nonMono++; }
    prevDev = dev;
    t[n] = (dev + wrap - dev0) / 1e6;
    ax[n] = vals[0]; ay[n] = vals[1]; az[n] = vals[2]; gx[n] = vals[3]; gy[n] = vals[4]; gz[n] = vals[5];
    amag[n] = Math.hypot(vals[0], vals[1], vals[2]) - 1;
    const s = iS >= 0 ? (f[iS]?.trim() === '1' ? 1 : 0) : 0;
    sat[n] = s; satCount += s;
    n++;
  }
  if (n === 0) throw new ParseError(bad ? `No valid rows in raw CSV (${bad} malformed, e.g. "${firstBad}").` : 'The raw CSV has a header but no data rows.');
  if (bad) warnings.push(`Skipped ${bad} malformed raw row(s), e.g. "${firstBad}".`);
  if (nonMono) warnings.push(`${nonMono} device timestamp(s) went backwards (out-of-order BLE packets?).`);
  if (iS < 0) warnings.push('Raw CSV has no "sat" column; saturation will not be shown.');
  return {
    raw: {
      n, t: t.subarray(0, n), ax: ax.subarray(0, n), ay: ay.subarray(0, n), az: az.subarray(0, n),
      gx: gx.subarray(0, n), gy: gy.subarray(0, n), gz: gz.subarray(0, n), amag: amag.subarray(0, n), sat: sat.subarray(0, n),
      hostT0, satCount,
    },
    warnings,
  };
}

/** Minimal RFC-4180-ish split for one line (labels may have quoted notes). */
export function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = '', q = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (q) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (c === '"') q = false; else cur += c;
    } else if (c === '"') q = true;
    else if (c === ',') { out.push(cur); cur = ''; } else cur += c;
  }
  out.push(cur);
  return out;
}

export function parseLabels(text: string, stance: string | null = 'orthodox'): { rows: { host: number; rawLabel: string; note: string }[]; warnings: string[] } {
  const warnings: string[] = [];
  if (!text.trim()) throw new ParseError('The labels CSV is empty.');
  const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/);
  const header = splitCsvLine(lines[0]).map((s) => s.trim().toLowerCase());
  const iT = header.indexOf('host_time_s'), iL = header.indexOf('label'), iN = header.indexOf('note');
  if (iT < 0 || iL < 0) throw new ParseError(`Labels CSV needs columns host_time_s,label[,note]; got "${lines[0].slice(0, 60)}".`);
  const rows: { host: number; rawLabel: string; note: string }[] = [];
  const unknown = new Set<string>();
  let bad = 0;
  for (const line of lines.slice(1)) {
    if (!line.trim()) continue;
    const f = splitCsvLine(line);
    const host = +f[iT];
    const lab = (f[iL] ?? '').trim();
    if (!Number.isFinite(host) || !lab) { bad++; continue; }
    const pl = parseLabel(lab, stance);
    if (!pl.type && !pl.marker) unknown.add(lab);
    rows.push({ host, rawLabel: lab, note: iN >= 0 ? (f[iN] ?? '').trim() : '' });
  }
  if (bad) warnings.push(`Skipped ${bad} malformed label row(s).`);
  if (unknown.size) warnings.push(`Unrecognised label(s) ignored in accuracy: ${[...unknown].slice(0, 6).join(', ')}.`);
  if (!rows.length) throw new ParseError('The labels CSV has no valid rows.');
  rows.sort((a, b) => a.host - b.host);
  return { rows, warnings };
}

/** Align label host times to the session time base. */
export function alignLabels(rows: { host: number; rawLabel: string; note: string }[], opts: { hostT0?: number; startIso?: string; stance?: string | null }): LabelRow[] {
  let off = 0;
  if (opts.hostT0 !== undefined && Number.isFinite(opts.hostT0)) off = opts.hostT0;
  else if (rows.length && rows[0].host > 1e6 && opts.startIso) off = Date.parse(opts.startIso) / 1000;
  return rows.map((r) => {
    const p = parseLabel(r.rawLabel, opts.stance ?? 'orthodox');
    return { t: r.host - off, rawLabel: r.rawLabel, type: p.type, hand: p.hand, note: r.note };
  });
}

export function toCsv(header: string[], rows: (string | number | boolean | null | undefined)[][]): string {
  const esc = (v: unknown) => {
    if (v === null || v === undefined) return '';
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [header.join(','), ...rows.map((r) => r.map(esc).join(','))].join('\n') + '\n';
}
