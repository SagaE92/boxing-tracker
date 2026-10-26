import { ParseError, alignLabels, parseLabels, parseRaw, readText, sniffCsv } from './csv';
import { parseSessionText } from './schema';
import type { LoadedSession } from './types';

export interface InFile { name: string; blob: Blob }

export function fileKey(name: string): string {
  const base = name.split(/[\\/]/).pop() ?? name;
  return base
    .replace(/\.gz$/i, '')
    .replace(/\.(csv|json)$/i, '')
    .replace(/[_.-]?(raw|session|labels?|punches|detector|imu)$/i, '')
    || base;
}

type Parsed =
  | { kind: 'json'; name: string; key: string; res: ReturnType<typeof parseSessionText> }
  | { kind: 'raw'; name: string; key: string; raw?: ReturnType<typeof parseRaw>; error?: string }
  | { kind: 'labels'; name: string; key: string; text: string }
  | { kind: 'error'; name: string; key: string; error: string };

async function parseOne(f: InFile): Promise<Parsed> {
  const key = fileKey(f.name);
  let text: string;
  try { text = await readText(f.blob, f.name); } catch (e) { return { kind: 'error', name: f.name, key, error: `${f.name}: ${(e as Error).message}` }; }
  const lower = f.name.toLowerCase().replace(/\.gz$/, '');
  if (lower.endsWith('.json') || text.trimStart().startsWith('{')) return { kind: 'json', name: f.name, key, res: parseSessionText(text, f.name) };
  if (!text.trim()) return { kind: 'error', name: f.name, key, error: `${f.name}: file is empty.` };
  const kind = sniffCsv(text);
  if (kind === 'raw') {
    try { return { kind: 'raw', name: f.name, key, raw: parseRaw(text) }; } catch (e) { return { kind: 'raw', name: f.name, key, error: `${f.name}: ${(e as Error).message}` }; }
  }
  if (kind === 'labels') return { kind: 'labels', name: f.name, key, text };
  if (kind === 'punches_csv') return { kind: 'error', name: f.name, key, error: `${f.name}: legacy punches CSV is not supported; load the detector's session.json instead.` };
  return { kind: 'error', name: f.name, key, error: `${f.name}: unrecognised file. Expected a raw CSV (host_time_s,device_time_us,…), a labels CSV (host_time_s,label,note) or a session.json.` };
}

/**
 * Parse a batch of dropped files and group them into sessions by file-name stem
 * (e.g. 2026-10-24_raw.csv + 2026-10-24_session.json + 2026-10-24_labels.csv).
 * If a batch contains exactly one session.json, unmatched CSVs attach to it.
 */
export async function loadFiles(files: InFile[], existing: LoadedSession[] = []): Promise<{ sessions: LoadedSession[]; errors: string[] }> {
  const parsed = await Promise.all(files.map(parseOne));
  const errors: string[] = [];
  const jsonKeys = parsed.filter((p) => p.kind === 'json').map((p) => p.key);
  const map = new Map<string, LoadedSession>();
  for (const s of existing) map.set(s.key, s);
  const get = (key: string, name: string) => {
    let s = map.get(key);
    if (!s) { s = { key, name, files: [], errors: [], warnings: [] }; map.set(key, s); }
    return s;
  };
  const resolveKey = (k: string) => {
    if (jsonKeys.includes(k) || map.has(k)) return k;
    if (jsonKeys.length === 1) return jsonKeys[0];
    return k;
  };
  // json first so names/stance are known
  for (const p of parsed.filter((x) => x.kind === 'json')) {
    if (p.kind !== 'json') continue;
    if (!p.res.ok) { errors.push(...p.res.errors); continue; }
    const s = get(p.key, p.res.data!.session.id);
    s.json = p.res.data; s.name = p.res.data!.session.id; s.files.push(p.name); s.warnings.push(...p.res.warnings);
  }
  for (const p of parsed) {
    if (p.kind === 'error') { errors.push(p.error); continue; }
    if (p.kind === 'raw') {
      if (p.error) { errors.push(p.error); continue; }
      const s = get(resolveKey(p.key), p.key);
      s.raw = p.raw!.raw; s.files.push(p.name); s.warnings.push(...p.raw!.warnings.map((w) => `${p.name}: ${w}`));
    }
  }
  for (const p of parsed) {
    if (p.kind !== 'labels') continue;
    const s = get(resolveKey(p.key), p.key);
    try {
      const stance = s.json?.session.stance ?? 'orthodox';
      const { rows, warnings } = parseLabels(p.text, stance);
      s.labels = alignLabels(rows, { hostT0: s.raw?.hostT0, startIso: s.json?.session.start_time_iso, stance });
      s.files.push(p.name); s.warnings.push(...warnings.map((w) => `${p.name}: ${w}`));
    } catch (e) {
      errors.push(`${p.name}: ${e instanceof ParseError ? e.message : (e as Error).message}`);
    }
  }
  // Drop sessions that ended up with nothing usable.
  const sessions = [...map.values()].filter((s) => s.json || s.raw);
  for (const s of map.values()) if (!s.json && !s.raw && s.labels) errors.push(`Labels for "${s.key}" need a matching session.json or raw CSV in the same drop.`);
  sessions.sort((a, b) => (a.json?.session.start_time_iso ?? '').localeCompare(b.json?.session.start_time_iso ?? ''));
  return { sessions, errors };
}

export async function loadDemo(base = import.meta.env.BASE_URL): Promise<{ sessions: LoadedSession[]; errors: string[] }> {
  const man = await (await fetch(`${base}demo/manifest.json`)).json() as { sessions: { id: string; files: string[]; notes?: string[] }[] };
  const files: InFile[] = [];
  for (const s of man.sessions) {
    for (const f of s.files) {
      const r = await fetch(`${base}demo/${f}`);
      if (!r.ok) throw new Error(`demo file ${f}: HTTP ${r.status}`);
      files.push({ name: f, blob: await r.blob() });
    }
  }
  const res = await loadFiles(files);
  res.sessions.forEach((s) => {
    s.demo = true;
    const m = man.sessions.find((x) => x.id === s.key);
    if (m?.notes) s.warnings.push(...m.notes);
  });
  return res;
}
