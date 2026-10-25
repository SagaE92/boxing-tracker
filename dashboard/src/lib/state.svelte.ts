import { defaultFilters, type Filters } from './stats';
import type { LoadedSession } from './types';
import { loadDemo, loadFiles, type InFile } from './load';

export type Tab = 'overview' | 'signals' | 'strikes' | 'trends' | 'accuracy' | 'live' | 'about';
export const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'signals', label: 'Signals' },
  { id: 'strikes', label: 'Strikes' },
  { id: 'trends', label: 'Trends' },
  { id: 'accuracy', label: 'Accuracy' },
  { id: 'live', label: 'Live' },
  { id: 'about', label: 'Why this is different' },
];

class AppState {
  sessions = $state.raw<LoadedSession[]>([]);
  activeKey = $state<string | null>(null);
  tab = $state<Tab>('overview');
  filters = $state<Filters>(defaultFilters());
  selectedId = $state<number | null>(null);
  range = $state<[number, number] | null>(null);
  comboGapMs = $state(600);
  tolMs = $state(200);
  errors = $state<string[]>([]);
  loading = $state<string | null>(null);

  active = $derived(this.sessions.find((s) => s.key === this.activeKey) ?? this.sessions[this.sessions.length - 1] ?? null);

  async addFiles(files: InFile[]) {
    this.loading = `Loading ${files.length} file(s)…`;
    try {
      const { sessions, errors } = await loadFiles(files, this.sessions);
      const before = new Set(this.sessions.map((s) => s.key));
      this.sessions = sessions;
      this.errors = errors;
      const added = sessions.filter((s) => !before.has(s.key));
      const touched = added[added.length - 1] ?? sessions.find((s) => files.some((f) => s.files.includes(f.name)));
      if (touched) this.select(touched.key);
    } catch (e) {
      this.errors = [`Could not load files: ${(e as Error).message}`];
    } finally {
      this.loading = null;
    }
  }
  async demo() {
    this.loading = 'Loading demo session…';
    try {
      const { sessions, errors } = await loadDemo();
      this.sessions = sessions;
      this.errors = errors;
      this.select(sessions[sessions.length - 1]?.key ?? null);
    } catch (e) {
      this.errors = [`Could not load demo: ${(e as Error).message}`];
    } finally {
      this.loading = null;
    }
  }
  select(key: string | null) {
    this.activeKey = key;
    this.selectedId = null;
    this.range = null;
    this.filters = defaultFilters();
  }
  remove(key: string) {
    this.sessions = this.sessions.filter((s) => s.key !== key);
    if (this.activeKey === key) this.select(this.sessions[this.sessions.length - 1]?.key ?? null);
  }
  selectStrike(id: number | null, zoom = true) {
    this.selectedId = id;
    const e = this.active?.json?.punches.find((p) => p.id === id);
    if (e && zoom) {
      const pad = Math.max(1.5, (e.t_end_s - e.t_start_s) / 2 + 0.5);
      this.range = [e.t_peak_s - pad, e.t_peak_s + pad];
    }
  }
}
export const app = new AppState();
