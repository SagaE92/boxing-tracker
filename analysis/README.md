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
