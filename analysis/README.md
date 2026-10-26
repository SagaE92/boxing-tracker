# Offline analysis

```bash
python analysis/detector.py rec_raw.csv --labels rec_labels.csv --hand rear --stance orthodox \
    --punches-out rec_punches.csv --session-out rec_session.json
python analysis/synth.py --demo analysis/samples/demo     # regenerate the demo session
python analysis/evaluate.py [--hard]                      # synthetic per-class recall
python -m pytest analysis/tests tools/tests -s            # tests (prints recall tables)
```

## Outputs

* **`session.json`** — conforms to `docs/session.schema.json` (schema 1.0.0, owned by
  the dashboard): session metadata incl. calibration, `detector_params`, `rounds`
  (round/rest split by ≥ 20 s activity gaps), `punches` (all events: strikes plus the
  non-strike `kick_or_body_movement` and `clinch`), `summary`. Validated in pytest
  with `jsonschema`.
* **punches CSV** — `punch_id,t_peak_s,t_start_s,t_end_s,type,peak_g,speed_mps_est,duration_ms,gyro_int_x,gyro_int_y,gyro_int_z,saturated`.
  All times are seconds from the first raw sample (device clock).

## Pipeline

1. `dyn = |a| − 1 g`. Threshold **3.5 g** (`--threshold`, 3–4 typical), **150 ms**
   refractory, peak = max of the above-threshold run, feature window **±150 ms**.
2. **Calibration** (`docs/axes.md`): guard window → gravity/up; first straight punch
   (≥ 40 ms long, so the sync clap is skipped) → forward axis. Uses
   `cal_start`/`cal_end` labels, otherwise searches the first 30 s. Events before the
   end of calibration and within 0.3 s of a `sync` label are ignored.
3. **Features** per window, in the calibrated frame: peak g (saturation flag → lower
   bound), roll/pitch/yaw integrals (±150 ms, and [−400, +150] ms for spins), peak rates
   per axis, rotation-axis direction, rotational/linear ratio (0.3 m lever × rotation ÷
   linear impulse), linear direction at the peak (minus pre-strike gravity), its
   elevation (target head/body), duration, pre-strike orientation, speed estimate
   (∫ positive dyn accel up to the peak).
4. **Rules** (`classify()`), gyro first — hooks and uppercuts are decided by rotation:
   * spinning_backfist: long-window yaw ≤ −150° *opposite* to that wrist's hook direction
   * uppercut: pitch ≤ −40° (fist up) dominating yaw, linear accel up
   * overhand: pitch ≥ +40° (fist down) dominating yaw, linear accel down
   * hook: yaw ≥ 45° in the wrist's hook direction, sideways linear accel
   * straight: forward linear accel, |yaw|, |pitch| < 45° → jab (lead) / cross (rear)
   * otherwise `unknown`; confidence 0–1 from rule margins, ×0.5 if uncalibrated, ×0.9 if clipped
   * lead/rear naming from `--hand`; L/R wrist from `--hand` + `--stance`
5. **Non-strikes** (low confidence 0.3, excluded from `punch_count` and every strike stat):
   * `kick_or_body_movement`: smoothed |ω| ≥ 220 dps for ≥ 150 ms with no strike peak nearby
     (a wrist sensor cannot see kicks; this is body rotation / arm swing that looks like one)
   * `clinch`: ≥ 4 s of 1 s windows with moderate dyn-accel std (0.12–1.2 g), gyro RMS
     40–300 dps, ≥ 6 sign changes/s/axis and no strike peak — duration event (`t_start_s..t_end_s`)

**This is a starting heuristic, tuned only on synthetic data.** The thresholds will
move once real, video-labelled recordings exist. Assumptions: sensor on the back of the
wrist inside the wrap, correct `--hand`/`--stance`, a calibration at session start.

## Two sensors (one inside each wrap)

```bash
python analysis/detector.py \
    --stream lead=rec_lead_raw.csv@boxtrk-lead --stream rear=rec_rear_raw.csv@boxtrk-rear \
    --sync rec_sync.csv --labels rec_labels.csv --stance orthodox --session-out rec_session.json
```

* **Clock alignment** (`fit_clock`, `clock_from_sync`): per device, fit
  `host_time = a + b·device_time` from the logger's sync CSV (time-sync round trips: lowest-RTT
  third per 5 s window; packet-arrival samples: lower envelope). Without `--sync`, the raw CSV's
  host-time anchor gives an offset only. Every device is mapped onto one session timeline.
  Target ≤ 2 ms between the sensors (docs/gatt-spec.md explains the number).
* **Per-device detection**: `analyze()` runs on each stream with that device's `hand` role and
  its own calibration.
* **Merge** (`merge_events`): strikes from the two devices within 60 ms → the weaker one is
  crosstalk if < 50 % of the stronger peak (dropped), otherwise both are kept and flagged
  near-simultaneous; kick/body movement and clinch seen by both sensors become one event;
  rounds are the union (`union_rounds`).
* **Output**: schema 1.1.0 — `session.devices[]` (device_id, hand, wrist, firmware version,
  clock offset/drift/residual) and `device_id` on every event. `session.hand`/`hand_worn` are
  null for two-sensor sessions. A single raw CSV still works exactly as before (one device
  entry, `--device-id`), and 1.0.0 files still validate.
* Synthetic two-hand data: `synth.make_two_hand_fatigue_session` (strikes rendered into the
  hand that threw them, sub-threshold crosstalk on the other wrist, ~4 % above threshold),
  `DeviceClock` (offset, drift, start delay), `write_raw_csv_clock`, `sync_rows`.
* Tests: `tests/test_two_sensors.py` (alignment ≤ 2 ms over 40 min, crosstalk/simultaneous
  merge, whole-body dedupe, rounds union, end-to-end vs ground truth per hand, single-sensor
  and 1.0.0 compatibility), `tests/test_fatigue.py` (late-round fade, rear share rises).

## Synthetic data and results

`synth.py` builds strikes from class templates in the calibrated frame (linear pulse +
rotation pulse + retraction, gravity rotated by the integrated rate), random mounting
rotation, ±12° technique jitter, rotation ×0.75–1.15, LSB quantisation and ±16 g /
±2000 dps clipping. Hard hooks (18–26 g) saturate.

Per-class recall, `evaluate.py` (both hands × both stances, 2 seeds, 40 events per class/condition):

| class | default | `--hard` (±25° jitter, rotation ×0.5–1.2) |
|---|---|---|
| jab | 100 % | 92.6 % |
| cross | 100 % | 90.4 % |
| lead_hook | 100 % | 93.8 % |
| rear_hook | 100 % | 91.9 % |
| lead_uppercut | 100 % | 97.5 % |
| rear_uppercut | 100 % | 95.0 % |
| overhand | 99.4 % | 85.6 % |
| spinning_backfist | 100 % | 86.6 % |
| kick_or_body_movement | 100 % | 100 % |
| clinch | 100 % (24/24) | 100 % |

These numbers show the rules are self-consistent with the templates, **not** real-world
accuracy (the templates were designed to be separable). In the demo session, where strikes come
in combos 0.3–0.5 s apart and the previous punch's retraction leaks into the next window,
recall drops (cross 78 %, rear_uppercut 89 %, overhand 86 %, rear_hook 98 %) — a more
realistic preview of the failure mode to fix with real data (e.g. subtract the pre-strike
rotation baseline).

## Samples (`samples/`)

`demo_raw.csv` (17 MB, 680 s at 416 Hz: sync clap, calibration, 3 × 3 min rounds with 1 min
rests, rear hand / orthodox, saturated hooks, clinches, body movements), `demo_labels.csv`
(sync / calibration / round markers plus `truth:<type>` ground-truth rows),
`demo_punches.csv`, `demo_session.json`.
