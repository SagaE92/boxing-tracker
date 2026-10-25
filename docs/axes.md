# Sensor placement and axis convention

**Placement:** inside the hand wrap, on the **back of the wrist** (dorsal side,
just behind the knuckles' line of the wrist joint), flat against the skin, wrapped
over so it cannot rotate. Either hand; the session settings say which:

* `hand`: `lead` or `rear` — which hand wears the sensor
* `stance`: `orthodox` (left hand leads) or `southpaw`
  → physical wrist `hand_worn` = L/R (orthodox lead = L, rear = R; southpaw mirrored)

## Calibrated frame (what the classifier uses)

The chip's own axes depend on how the board sits in the wrap, so we never rely on
them. At session start the user holds a guard and throws one straight punch:

```
              z  (UP: opposite to gravity in the guard pose)
              ^
              |      x (FORWARD: direction of the calibration straight punch,
              |     /     made perpendicular to z)
              |    /
              |   /        Right-handed:  y = z × x
              |  /
              | /
   y  <-------o            y = LEFT (from the boxer's point of view)
 (LEFT)     wrist

 Rotation signs: right-hand rule about each axis (viewed from the arrow tip,
 counter-clockwise = positive).
   roll  ωx : forearm corkscrew (pronation/supination) – straights
   pitch ωy : + = fist goes DOWN (forward axis tips down) – overhand
              − = fist goes UP                              – uppercut
   yaw   ωz : + = fist sweeps to the LEFT (counter-clockwise seen from above)
              RIGHT wrist hook  → ωz > 0, linear accel +y
              LEFT  wrist hook  → ωz < 0, linear accel −y   (mirror image)
              spinning backfist → large yaw OPPOSITE to that wrist's hook direction
```

Calibration math (`analysis/detector.py::calibrate`, firmware `src/session.c`):

* `up` = normalised mean accelerometer vector over a ≥1.5 s quiet guard window
  (|a| within 1 ± 0.08 g, |ω| < 30 dps). (The accelerometer reads +1 g *upwards* at rest.)
* `fwd` = accel at the straight punch's peak minus the guard gravity, with its `up`
  component removed, normalised.
* `left = up × fwd`; rotation `R = [fwd; left; up]` maps sensor vectors to the
  calibrated frame: `v_cal = R · v_sensor`.

These axes are **fixed to the sensor** (body frame); during a hook the forearm
rotates, so "up" stops pointing up — rotation features are integrated in this
body frame, which is what the rules expect.

If no calibration is found (no `cal_start`/`cal_end` labels and no quiet window
followed by a ≥40 ms strike within the first 30 s), the detector falls back to
raw chip axes and halves every confidence.

`session.json` `gyro_int_dps_s` = [roll, pitch, yaw] integrals in the calibrated
frame (degrees) when calibrated, chip x/y/z otherwise.
