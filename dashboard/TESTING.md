# Dashboard testing

Last full run: 2026-10-26 (branch `feat/athlete-view`), headless Chromium (Playwright 1.64 bundled build), Node 22.

| Suite | Command | Result |
|---|---|---|
| Type / Svelte check | `npm run check` | 0 errors, 0 warnings |
| Unit (Vitest) | `npm test` | **71 / 71 passed** |
| Production build | `npm run build` | OK → `dist/` (relative base `./`) |
| E2E + screenshots (Playwright) | `npm run test:e2e` | **28 / 28 passed** (~40 s; 12 athlete + 16 Lab) |
| Python (analysis + tools + firmware host tests) | `python -m pytest -q analysis/tests tools/tests` | **45 / 45 passed** |

`npm run test:e2e` builds nothing itself; run `npm run build` first (it serves `dist/` with `vite preview` on :4173).
`tests/e2e/global-setup.ts` generates the fixtures (1 h session, heavy saturation, idle, single hand, broken/empty/future-version files) into `tests/e2e/.fixtures/` (git-ignored).

## Unit tests (`tests/unit/`)

- **csv.test.ts** – raw CSV parsing (header sniffing, CRLF, gzip by magic bytes, malformed rows skipped with a warning, empty file / wrong header → friendly error, uint32 µs device-clock wrap), labels parsing (`truth:` prefix, `_L/_R` suffix, legacy `hook`/`uppercut` mapped via stance, marker rows ignored), label time alignment, CSV export quoting.
- **athlete.test.ts** – athlete analytics (`src/lib/athlete.ts`): per-round strikes (punches + kicks, clinch excluded), pace, speed, impact, combos (2+ punches < 0.6 s apart); best / lowest round; friendly labels (hooks and uppercuts merged, kick, other); mix shares; top combo sequences; **first 3 vs last 3** (volume, speed, impact, combos, kick share, lead share) with the < 6-round fallback (halves; "First round vs last round"; null for 1 round); plain-language finish notes; hand line ("Rear hand did N% in rounds 8–10…"); **takeaway** for every rule (strong start + drop, speed-only drop, finished strong, steady, one round, empty) with the exact percentages; no banned words; session overview for history.
- **schema.test.ts** – all bundled demos validate (incl. the 1.1.0 two-sensor `demo-10x3`); 1.0.0 sessions (no `devices`) load without a warning; a newer minor (1.2.0) warns; bad `devices[].hand` / `device_id` give path messages; `schema_version` 2.x rejected; missing required field and unknown `type` give readable path messages; invalid JSON.
- **stats.test.ts** – strike totals exclude `kick_or_body_movement` and `clinch`; filters (confidence, type, hand, target, round, saturated); per-round stats and within-round fatigue slope; combos (<600 ms) and sequence counts; data quality (saturation %, gaps / dropped-sample estimate, measured rate, jitter); label matching (one-to-one, tolerance, clinch span matching, precision/recall/F1, per-class recall, hook recall); trends and personal bests.
- **gatt-load.test.ts** – Web Bluetooth packet decoding (raw 18 B header + 12 B samples, scaling 0.488 mg / 70 mdps, punch-event type codes 0–10), file grouping by stem (`_raw/_session/_labels`), labels without a session → error, legacy punches CSV → explanatory error.

## E2E cases (`tests/e2e/`)

### Athlete view (`athlete.spec.ts`, phone 390 × 844 first)

| Case | Covered by |
|---|---|
| Landing: one **Open session** button, Bluetooth sync disabled ("soon"), Athlete selected by default | `landing…` |
| Header: "10 rounds × 3 min", takeaway matches the rule template, strikes / per min / best round, data-quality badge, **hand balance** split bar and "Rear hand did N% in rounds 8–10" | `header + rounds…` |
| 10 round cards, exactly one Best and one Lowest, per-round hand split, impact + combos | `header + rounds…` |
| Tap a round → its timeline (≥ 30 strike marks, per-minute counts); tap again closes | `tapping a round…` |
| How you finished: first 3 vs last 3 table incl. rear-hand share, negative output change, notes (kicks dropped off, lead hand faded more), trend chart | `How you finished…` |
| Strike mix uses friendly labels only; top combos | `strike mix…` |
| History: 5 sessions, volume + late drop-off charts; switching to a 3-round session falls back to "First round vs last round" | `session history…` |
| Lab toggle remembered across reloads (`localStorage`), back to Athlete; data-quality badge opens Lab's panel | `Lab toggle…` |
| Open session with raw + session + labels works in Athlete; a bad file shows a short message pointing to Lab | `Open session accepts…` |
| **No Lab words** on athlete screens (incl. hidden tooltips): saturation, clipping, confidence, sample rate / Hz, ±g, g-range, CSV, "lower bound", power, force; Lab tabs hidden | every athlete test (`assertNoLabWords`) |
| 375 / 414 / 820 / 1440 px: no horizontal overflow with a round open; tablet + desktop screenshots | `athlete view …px` ×4 |
| Zero console errors / warnings | `watchConsole` in the athlete tests |

### Lab view (`dashboard.spec.ts`, `perf.spec.ts`; open with `?view=lab`)

| Case | Covered by |
|---|---|
| Demo load, every tab rendered, **zero console errors / warnings**; two-sensor session card (sensors + clock alignment) | `demo session › loads with zero console errors…` |
| Default demo is the 10 × 3 min two-sensor session (10 round rows, loader note for the partial raw); 6 × 2 demo selectable | `default demo is the 10 x 3 min…` |
| Strike click → ±150 ms detail + Signals zoom | `clicking a strike opens its window…` |
| Accuracy view **with labels**: hook recall headline, synthetic-data note, tolerance slider | `accuracy view surfaces hook recall…` |
| Accuracy view **without labels** (explains how to add them) | `missing labels…` |
| PNG export, summary CSV, events CSV (non-strikes excluded by default); **compatibility aliases** (`peak_g_is_lower_bound`, `saturated_strikes`, `max_peak_g_is_lower_bound`) and the `device_id` column | `exports summary PNG…` |
| Multiple sessions in Trends, A/B compare, no "power"/"force" wording in headings | `trends compare multiple sessions` |
| File picker grouping raw + session + labels | `file picker groups…` |
| Simulated drag-and-drop (heavy-saturation fixture → saturation warning, peak g shown as lower bound) | `simulated drag-and-drop…` |
| Empty CSV, malformed CSV, unknown file, schema_version 2.0.0, schema-invalid JSON → friendly errors | `friendly errors…` |
| Missing raw (session.json only) | `missing labels…` (loads JSON-only session) |
| Zero punches (idle fixture) | `zero strikes renders cleanly` |
| Single hand only | screenshot `single-hand-overview.png` (drag-drop test set) |
| Viewports 375 / 390 / 414 / 820 px + 1440 desktop: no horizontal overflow on any tab | `responsive …px` ×4 |
| 1 h, 416 Hz session (~1.49 M samples): load, render, zoom, wheel, heap | `perf.spec.ts` |

## Export compatibility note

Review 1 renamed export columns; the old names are kept as aliases with the same values
(details in `README.md` › Export compatibility note): events CSV `peak_g_is_lower_bound`
next to `clipped` / `peak_g_text`; summary CSV `saturated_strikes` next to `clipped_strikes`,
`mean_peak_g` (= `mean_peak_g_incl_clipped`) and `max_peak_g_is_lower_bound` (= `max_peak_g_clipped`).
Asserted in `exports summary PNG…`.

## Python: two sensors and the fade demo

- `analysis/tests/test_two_sensors.py` – clock alignment from time-sync round trips ≤ 2 ms over 40 min at +23 / −17.5 / +40 ppm (uncorrected drift would be > 20 ms); packet-arrival lower envelope recovers drift; merge drops crosstalk and keeps near-simultaneous strikes; kick/clinch seen by both sensors merged; rounds union; end-to-end two-sensor run vs ground truth per hand (≥ 90 % matched within 60 ms, kicks counted once, device ids and wrists right); single raw CSV input still works; 1.0.0 documents still validate.
- `analysis/tests/test_fatigue.py` – `FatigueProfile` monotonic; late-round fade on ground truth and after the detector; the shipped `demo-10x3` has the fade, both hands fade, the lead more, and the rear share rises.
- `tools/tests/test_logger.py` – two `DeviceRecorder`s write per-device raw CSVs and one sync CSV; time-sync bursts against fake BLE clients (32-bit wrap, ±ppm drift, asymmetric round trips) align the two sensors within 2 ms; `--device` parsing.

## Saturation severity scheme

Clipped strikes and saturated samples share one scale (`clippedStrikeLevel` / `satSampleLevel` in `src/lib/stats.ts`, `SAT_THRESHOLDS`), used by the Overview card, the data-quality panel, the warning banner and the strike detail:

| Level | Clipped strikes (share of strikes) | Saturated raw samples | Meaning |
|---|---|---|---|
| green / ok | 0 | 0 | no clipping |
| **amber / warn** | > 0 and < 10 % | > 0 and < 1 % | some peaks are lower bounds (shown as `≥`) |
| **red / bad** | ≥ 10 % | ≥ 1 % | peak-g means, maxima and trends substantially understated; high-g IMU path needed |

The banner shows one combined line at the worse of the two levels. Clipping marks in charts (timeline ring, signal shading, ±16 g lines, strike-table badge) are amber. Unit-tested in `stats.test.ts`; the heavy-saturation e2e test checks that card, panel and banner agree.

## Performance (1 h @ 416 Hz, `screenshots/perf.json`)

| Metric | Result | Budget asserted |
|---|---|---|
| Load + parse (gzip CSV + JSON) | ~1.6 s | – |
| Open Signals tab (3 charts drawn) | **~0.33 s** | < 5 s |
| Decimation passes on opening Signals | 2 | ≤ 3 |
| First range draw | ~70 ms | < 500 ms |
| 6 successive zooms | 41 → 5 ms | < 250 ms each |
| 10 wheel-zoom events | ~0.6 s | – |
| JS heap after load | ~61 MB | < 600 MB |

Charts use min/max per-pixel decimation (gaps preserved), so drawn points stay ~2 × width regardless of session length.

### Bug found and fixed by the perf test
Opening Signals on the 1 h session originally took 4.7–12.9 s. Profiling showed `decimate()` running ~228 times: the range `$effect` also tracked derived values read inside uPlot draw hooks, so each redraw re-triggered it. The effect now tracks only `range`/`raw` and runs the draw `untrack`ed (same guard applied to Timeline and StrikeDetail redraws). Result: 2 passes, ~0.3 s. The test now asserts the pass count so the loop can't come back.

Other issues found and fixed during testing: tooltips caused horizontal overflow on phones (now `display:none` until hover/focus); charts in grids overflowed at 375 px (`minmax(min(Npx,100%),1fr)`); uPlot legend inherited table header styling; Timeline/Signals rebuilt on every zoom; the round filter used the wrong index; demo data initially had no saturation to exercise the warning.

## Review 1 (before / after)

`node scripts/review-shots.mjs before|after` (with `vite preview` on :4173) writes `screenshots/review-1/`:

| Item | Before | After |
|---|---|---|
| 1. clipped peaks as lower bounds | `1-peak-cards-before.png`, `1-round-table-before.png`, `1-strike-table-clipped-before.png` | `1-peak-cards-after.png` (new default demo), `1-peak-cards-same-session-after.png`, `1-round-table-after.png`, `1-round-table-same-session-after.png`, `1-strike-table-clipped-after.png` |
| 2. one severity scheme | `2-data-quality-before.png` (red saturation vs amber clipped card) | `2-data-quality-after.png`, `2-data-quality-same-session-after.png`, `2-warning-banner-same-session-after.png` |
| 3. 6 × 2 min default demo | `3-header-demo-select-before.png`, `3-overview-default-demo-before.png`, `3-trends-before.png` | `3-header-demo-select-after.png`, `3-overview-default-demo-after.png`, `3-trends-after.png` |

Finding for item 1: the old "20.2 g" max on the 3-round demo was **not** clipped. The ±16 g limit is per axis and that strike's axes peaked at about −12.9 / −6.5 / −15.5 g (|a| = 21.2 g, so peak g = 20.2), so the magnitude is real. Clipped strikes are now marked `≥` everywhere (cards, round table, strike table, timeline tooltip, Trends, personal bests, CSV `clipped` + `peak_g_text` columns), and the mean is shown unclipped plus "incl. clipped ≥…".

New e2e checks: default demo is `demo-6x2` (6 round rows) and the 3-round demo can be selected; card, panel and banner severity agree on the heavy-saturation fixture; CSV has `clipped` / `peak_g_text` / `mean_peak_g_unclipped` / `max_peak_g_clipped`.

## Screenshots (`screenshots/`, regenerated by every e2e run)
Athlete view (`screenshots/athlete/`): `phone-390-landing.png`, `phone-390-header-rounds.png`, `phone-390-hand-balance.png`, `phone-390-round-timeline.png`, `phone-390-finish.png`, `phone-390-strike-mix.png`, `phone-390-history.png`, `phone-390-lab-toggle.png`, `tablet-820-overview.png`, `desktop-1440-overview.png`.

Lab: `desktop-{overview,signals,strikes,strike-detail,trends,accuracy,live,about}.png`, `phone-375-overview.png`, `phone-390-{overview,signals,strikes,trends,accuracy,live,why}.png`, `phone-414-overview.png`, `tablet-820-*.png`, `errors.png`, `heavy-saturation.png`, `single-hand-overview.png`, `export-summary.png`, `perf-1h-signals.png`, `perf.json`.

## Not covered / limitations
- Two sensors: the host pipeline is tested with synthetic streams and fake BLE links only; the firmware side (role in settings/advertising, 0x0008 time sync) is specified in `docs/gatt-spec.md` but not implemented, and `tools/logger.py --device` has not run against hardware. Lab › Signals shows one raw stream per session.
- All data is synthetic (Python demo output from `analysis/samples` plus `scripts/gen-demo.mjs`); accuracy numbers validate the pipeline, not the detector on real punches.
- Web Bluetooth live mode is only unit-tested at the packet-decoding level; not tested against hardware (Chromium headless has no BLE).
- Touch drag-to-zoom is not supported on charts (use the zoom buttons / strike selection).
- Only Chromium is tested (no Firefox/WebKit runs; Firefox/Safari also lack Web Bluetooth).
