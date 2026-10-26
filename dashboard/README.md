# StrikeLab dashboard

Static, offline single-page app for reviewing sessions from the DIY boxing/kickboxing
tracker (XIAO nRF52840 Sense, LSM6DS3TR-C, ±16 g / ±2000 dps, 416 Hz). Vite +
TypeScript + Svelte 5, uPlot for the 416 Hz charts. No backend, no account: files are
parsed in the browser and never uploaded.

Live site (after the first push to `main` with Pages enabled):
https://sagae92.github.io/boxing-tracker/

## Run

```bash
cd dashboard
npm ci
npm run dev          # http://localhost:5173  (add ?demo to auto-load the demo)
npm run build        # → dashboard/dist (relative base: works on Pages, any static server, or file preview)
npx vite preview     # serve dist/ on http://localhost:4173
# or: cd dist && python3 -m http.server
```

`dist/` is self-contained (JS, CSS, fonts are system fonts, demo data in `dist/demo/`).

## Inputs

Drop files anywhere on the page or use **Load files** (several at once; `.gz` is fine).
Files are grouped into sessions by name stem (`X_raw.csv`, `X_session.json`,
`X_labels.csv`); if a drop contains exactly one session.json, other CSVs attach to it.

| File | Format | Source |
|---|---|---|
| Raw CSV | `host_time_s,device_time_us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,sat` | `tools/` bleak logger |
| `session.json` | `docs/session.schema.json` (schema_version 1.x; current 1.1.0 adds `session.devices[]` and per-event `device_id`; 1.0.0 loads silently), validated with Ajv; friendly errors | `analysis/detector.py` |
| Labels CSV | `host_time_s,label,note`; label = type, optional hand (`lead_hook_L`), `truth:` prefix OK, markers (`sync`, `cal_start`, `round`…) ignored | video labelling |

The detector is **not** ported to JS: `analysis/detector.py` is the single source of
truth. A raw CSV without a session.json shows waveforms only.

Time base: session times are seconds from the first raw sample on the device clock
(`device_time_us`, uint32 rollover unwrapped; two-sensor sessions: the aligned session clock,
see `analysis/README.md`); labels are aligned by subtracting the
raw CSV's first `host_time_s` (or `start_time_iso` if no raw is loaded).

## Two layers: Athlete (default) and Lab

The header has an **Athlete | Lab** switch; the choice is stored in `localStorage`
(`strikelab.view`) and can be forced with `?view=athlete` / `?view=lab` (`?tab=…` implies Lab).

### Athlete view (mobile-first, designed at 390 px)

For the kickboxer after ~10 rounds: no files, sensor limits or detector numbers.

1. **Session header**: date, rounds × length, total strikes (punches + kicks), average pace
   (strikes per minute of round time), best round, duration, and a one-sentence
   **takeaway** (rules below). A small **Data quality: good / check** badge links to Lab's
   data-quality panel ("check" when any issue is severe, the same rule Lab uses for red).
   With two sensors: **hand balance** (lead/rear split bar) and a line such as
   "Rear hand did 72% in rounds 8–10, up from 55% early."
2. **Round by round** (the centrepiece): one card per round with strikes, a bar to scan down
   the rounds, strikes/min, average speed, average **impact** (mean peak wrist
   acceleration; tooltip explains it), combos, the top 3 strike types and a lead/rear split
   bar. Best and lowest rounds are highlighted. Tapping a round opens its strike timeline
   (impact sticks coloured by type, kicks as diamonds, combo marks, strikes per minute).
3. **How you finished**: first 3 vs last 3 rounds (strikes/round, speed, impact,
   combos/round, kick share, rear-hand share), a trend chart of every round as % of the
   opening rounds, and plain-language notes (e.g. "Kicks dropped off: 4.0 per round early,
   1.3 in rounds 8–10", "Lead hand faded more…"). With 2–5 rounds it compares the first and
   last half (rounded down); with one round it says so.
4. **Strike mix** with friendly labels — Jab, Cross, Hook (lead + rear), Uppercut, Overhand,
   Spinning backfist, Kick (`kick_or_body_movement`), Other (`unknown`) — and the top combos.
5. **Session history**: every loaded session (newest first, tap to open) plus volume
   (strikes/min) and late-round drop-off trends across sessions.
6. **Loading**: one **Open session** button (same file chooser and file types underneath;
   drag-and-drop still works) and a disabled **Sync from tracker · soon** for the coming
   Bluetooth path. File errors show a short message that points to Lab.

The athlete view never mentions saturation/clipping, confidence, g-range or sample rate
(clipped peaks are plain numbers; the "≥" lower-bound marker is Lab-only) and never says
"power" or "force" — enforced by `tests/e2e/athlete.spec.ts`.

**Definitions** (`src/lib/athlete.ts`):
* *Strikes* = punches (all strike types incl. unknown) + kicks; clinch is excluded. (Lab's
  "Strikes" card counts punches only and lists kicks separately.)
* *Combo* = 2+ punches, each within **0.6 s** of the previous one (`COMBO_GAP_MS`, the same
  `stats.combos` rule as Lab's combo panel); a kick or clinch ends it.
* *Best / lowest round* = most / fewest strikes (ties broken by speed).
* *Lead / rear* = the strike's wrist (L/R) mapped through the stance (orthodox: L leads).
  Shown only when the session has two sensors (or both wrists are clearly present).
* **Takeaway rules** (`takeaway()`, thresholds in `TAKEAWAY`): compare the last N rounds with
  the first N (N = 3, or half with < 6 rounds):
  1. no strikes → "No strikes recorded in this session."; one round → "One round: X strikes at Y per minute."
  2. output (strikes/round) down ≥ 8 % and/or speed down ≥ 5 % → "Your output dropped X% and
     speed Y% in the last N rounds." — prefixed "Strong start; " when the best round is in the
     first half;
  3. output up ≥ 8 % → "You finished strong: output up X% in the last N rounds.";
  4. otherwise → "Steady pace: your output and speed held within X% …".
  All numbers come from the loaded session; nothing is hard-coded.

### Lab view

Everything that existed before, unchanged: the tabs below, the strike table with
confidence, accuracy, data-quality and saturation banners, CSV/JSON/PNG exports, Live BLE
and the comparison page. For two-sensor sessions the session card lists both sensors and
their clock alignment (offset, drift, fit residual).

## Lab views

* **Overview**: data-quality warnings, summary cards (strikes, work rate, mean/max peak g
  with "≥" for clipped peaks, estimated speed, clipped strikes, confidence, kick/clinch
  kept out of totals), type mix, lead/rear and head/body split, type-by-hand, strikes and
  work rate per round, session timeline (round/rest bands, clinch bands, combo links,
  density strip, label ticks), fatigue (first→last round change + trendlines), combos
  (length distribution, most common sequences, adjustable gap), round-by-round table
  with within-round change, data-quality panel (saturation, BLE gaps, sample-rate
  jitter, calibration, confidence histogram). Export summary PNG/CSV and events CSV.
* **Signals**: overview brush + |a|−1 g, 3-axis accel and gyro with threshold,
  ±range lines, saturated-sample shading, strike markers, video labels. Min/max
  decimation per pixel keeps a 1 h session (1.5M samples) interactive. Drag = zoom,
  wheel = zoom, Shift+wheel = pan, double-click = reset, arrow/+/−/0 keys.
* **Strikes**: filters (type, confidence, peak g, hand, target, round, time, clipped),
  sortable table, ±window waveform detail for the selected strike, CSV export.
* **Trends**: personal bests, volume & work rate, peak-g trend, estimated speed,
  fatigue across sessions, mean peak g by round per session, type mix, A/B session
  comparison.
* **Accuracy** (with labels): hook recall headline vs the published 50–65% reference,
  detection precision/recall/F1, type and hand accuracy, per-class recall, confusion
  matrix with missed / false-positive row and column, matching tolerance slider,
  confusion CSV.
* **Live**: Web Bluetooth client for the v1 GATT protocol (`docs/gatt-spec.md`,
  `firmware/src/bt_proto.h`): raw |a| stream and on-device strike events. Chrome/Edge
  desktop + Android only. Untested against hardware.
* **Why this is different**: sourced comparison (`docs/why.md`).

Metric definitions are in the ⓘ tooltips (`src/lib/tips.ts`). Units are peak g and
estimated speed; nothing is called "power" or "force".

## Demo data

`public/demo/` (rebuild with `npm run demo:data`; needs Python with numpy + jsonschema, the
repo `.venv` is used if present):
* `demo-10x3_*` (**default**): 10 × 3 min kickboxing with **two sensors** (one per wrap) and a
  realistic late-round fade: both hands fade, the lead hand more (rear share rises), with
  fewer kicks, combos and hooks and lower speed/impact in rounds 8–10.
  `scripts/gen_rounds_demo.py --two-hands` renders a lead and a rear device stream with
  `analysis/synth.py make_two_hand_fatigue_session` (each with its own clock offset, drift and
  start delay, plus time-sync samples), and `analysis/detector.py --stream … --sync …` aligns,
  detects per device and merges, so `session.schema.json` stays the single source of truth.
  **Raw data:** the full 39 min × 2 sensors is ~126 MB, so only the rear sensor's first 60 s
  ship (`demo-10x3_raw.csv.gz`, ~0.5 MB; the rear sensor started first, so its clock is the
  session origin). Lab shows a loader note saying so.
* `demo-6x2_*`: the previous default (6 × 2 min, single sensor), session.json + labels only —
  its 7 MB raw CSV is no longer committed.
* `demo_*`: the Python pipeline's sample (`analysis/samples`, 3 × 3 min), session.json
  and labels only (raw dropped to keep the bundle small).
* `demo-2026-10-10`, `demo-2026-10-17`: session.json only, from
  `scripts/gen-demo.mjs` (synthetic simulator, deterministic seeds) so Trends has
  history. **All demo data is synthetic**; accuracy numbers on it only show the pipeline
  works.

Big binaries are not committed: the demo raw stays under ~1 MB. To get full raw data for a
demo locally, run `python scripts/gen_rounds_demo.py --two-hands --out /tmp/d10 …` (see
`scripts/gen-all-demo.sh`) and drop the files into Lab.

`scripts/gen-demo.mjs` also builds the e2e fixtures (1 h session, heavy saturation,
zero strikes, single hand).

## Tests

```bash
npm run check      # svelte-check + tsc
npm test           # Vitest unit tests (parsing, schema validation, stats, athlete view, GATT parsing, loader)
npm run build && npm run test:e2e   # Playwright (Chromium): e2e + screenshots → screenshots/
```

See `TESTING.md` for what is covered and the latest results. CI:
`.github/workflows/pages.yml` runs check, build, unit and e2e tests, then deploys `dist/`
to GitHub Pages on pushes to `main`.

## Layout

```
src/App.svelte                 shell: header, Athlete/Lab switch, Lab tabs, drop zone, session meta
src/lib/athlete.ts             athlete analytics: rounds, finish comparison, takeaway, mix, combos, history
src/lib/components/athlete/    athlete view (Athlete, RoundTimeline, SplitBar)
src/lib/csv.ts, load.ts        parsing + file grouping (gzip via DecompressionStream)
src/lib/schema.ts              Ajv validation against ../docs/session.schema.json
src/lib/stats.ts               summaries, rounds, fatigue, combos, data quality, label matching
src/lib/decimate.ts, plot.ts   min/max decimation, uPlot helpers
src/lib/gatt.ts                Web Bluetooth protocol (v1)
src/lib/components/*.svelte    views and charts
tests/unit, tests/e2e          Vitest, Playwright
scripts/                       demo/fixture generator
```

## Export compatibility note

Review 1 renamed some export columns. The old names are kept as **aliases** (same values)
so existing spreadsheets keep working:

| Export | New column | Old name kept as alias |
|---|---|---|
| Events CSV | `clipped`, `peak_g_text` (`>=16.1` for clipped peaks) | `peak_g_is_lower_bound` |
| Summary CSV | `clipped_strikes` | `saturated_strikes` |
| Summary CSV | `mean_peak_g_incl_clipped`, `mean_peak_g_unclipped` | `mean_peak_g` (= incl. clipped) |
| Summary CSV | `max_peak_g_clipped` | `max_peak_g_is_lower_bound` |

Events CSV also gained a trailing `device_id` column (schema 1.1, two sensors).

## Limitations

* Lab > Signals shows one raw stream per session; for a two-sensor session load one
  device's raw CSV (named `<session>_raw.csv`). Side-by-side raw for both sensors is not
  implemented yet.
* The athlete view is offline-only; "Sync from tracker" (Bluetooth) is a placeholder.

* All bundled data is synthetic; no real recordings yet.
* Touch: drag-to-zoom on charts needs a mouse; on phones use the zoom/pan buttons and tap
  markers.
* Web Bluetooth live mode has not been run against real hardware.
* PNG export uses html-to-image (renders the DOM; canvas charts included).
