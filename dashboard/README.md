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
| `session.json` | `docs/session.schema.json` (schema_version 1.x), validated with Ajv; friendly errors | `analysis/detector.py` |
| Labels CSV | `host_time_s,label,note`; label = type, optional hand (`lead_hook_L`), `truth:` prefix OK, markers (`sync`, `cal_start`, `round`…) ignored | video labelling |

The detector is **not** ported to JS: `analysis/detector.py` is the single source of
truth. A raw CSV without a session.json shows waveforms only.

Time base: session times are seconds from the first raw sample on the device clock
(`device_time_us`, uint32 rollover unwrapped); labels are aligned by subtracting the
raw CSV's first `host_time_s` (or `start_time_iso` if no raw is loaded).

## Views

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

`public/demo/` (rebuild with `npm run demo:data`):
* `demo-6x2_*` (**default**): 6 × 2 min rounds with fatigue (strike amplitude and work
  rate fade across and within rounds). Built by `scripts/gen_rounds_demo.py` from the
  `analysis/synth.py` primitives and processed by the unchanged `analysis/detector.py`
  CLI, so every event is real detector output. Raw CSV gzipped (~7 MB), labels included.
  Needs Python with numpy + jsonschema (the repo `.venv` is used if present).
* `demo_*`: the Python pipeline's sample (`analysis/samples`, 3 × 3 min), session.json
  and labels only (raw dropped to keep the bundle small).
* `demo-2026-10-10`, `demo-2026-10-17`: session.json only, from
  `scripts/gen-demo.mjs` (synthetic simulator, deterministic seeds) so Trends has
  history. **All demo data is synthetic**; accuracy numbers on it only show the pipeline
  works.

`scripts/gen-demo.mjs` also builds the e2e fixtures (1 h session, heavy saturation,
zero strikes, single hand).

## Tests

```bash
npm run check      # svelte-check + tsc
npm test           # Vitest unit tests (parsing, schema validation, stats, GATT parsing, loader)
npm run build && npm run test:e2e   # Playwright (Chromium): e2e + screenshots → screenshots/
```

See `TESTING.md` for what is covered and the latest results. CI:
`.github/workflows/pages.yml` runs check, build, unit and e2e tests, then deploys `dist/`
to GitHub Pages on pushes to `main`.

## Layout

```
src/App.svelte                 shell: header, tabs, drop zone, session meta
src/lib/csv.ts, load.ts        parsing + file grouping (gzip via DecompressionStream)
src/lib/schema.ts              Ajv validation against ../docs/session.schema.json
src/lib/stats.ts               summaries, rounds, fatigue, combos, data quality, label matching
src/lib/decimate.ts, plot.ts   min/max decimation, uPlot helpers
src/lib/gatt.ts                Web Bluetooth protocol (v1)
src/lib/components/*.svelte    views and charts
tests/unit, tests/e2e          Vitest, Playwright
scripts/                       demo/fixture generator
```

## Limitations

* All bundled data is synthetic; no real recordings yet.
* Touch: drag-to-zoom on charts needs a mouse; on phones use the zoom/pan buttons and tap
  markers.
* Web Bluetooth live mode has not been run against real hardware.
* PNG export uses html-to-image (renders the DOM; canvas charts included).
