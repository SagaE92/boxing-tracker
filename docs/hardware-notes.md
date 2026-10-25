# Hardware notes and known risks

## Known risk: wrist punches exceed ±16 g

Hand/wrist acceleration at impact in hard punches is commonly well above 16 g
(hooks especially; tens of g at the wrist are plausible). The XIAO's onboard
**LSM6DS3TR-C tops out at ±16 g** (and ±2000 dps), so the hardest punches will clip.

What the software does about it today:

* Firmware flags every raw sample with any accel axis at |raw| ≥ 32100 LSB (≥ 15.66 g,
  98 % of full scale) or gyro axis ≥ 28000 LSB (≥ 1960 dps), per sample, in the raw
  stream (`accel_sat_mask`, `gyro_sat_mask`) → the logger's `sat` column.
* Punch events carry `ACCEL_SAT` / `GYRO_SAT` flags; `analysis/detector.py` sets
  `saturated: true` and treats `peak_g` as a **lower bound**. The demo session includes
  saturated hooks.
* The classifier relies mainly on **gyro** features (rotation integrals and rates),
  which saturate later than the accelerometer, and down-weights confidence on clipped windows.
* There is no "power" metric anywhere — only `peak_g` (acceleration) and `speed_mps_est`.

Mitigations for the custom board (pick after measuring real saturation rates with the prototype):

1. **LSM6DSO32** (±32 g, ±2000 dps, same 2.5 × 3 mm footprint, ~0.55 mA combo HP) —
   simplest swap; needs a new driver/compatible (different register map).
2. **LSM6DSV320X** (dual-range: ±16 g low-g + ±320 g high-g channel in one package) —
   recommended in `docs/components.md`.
3. Keep a 6-axis IMU and add a **high-g accelerometer**: ADXL372 (±200 g, 22 µA at 3200 Hz,
   coarse 100 mg/LSB) or H3LIS331DL (±100/200/400 g, ~370 µA at 1 kHz).
4. Software only: estimate clipped peaks from the pulse shape (fit before/after the
   clip) — cheap, but an estimate.

## Placement / enclosure

* Inside the hand wrap on the back of the wrist (`docs/axes.md`), flat, wrapped over so it
  cannot rotate. Calibration at every session start absorbs mounting variation.
* Sealed enclosure, **no button**: wake on motion, sleep on timeout or app command.
* Charging via **pogo pins** (preferred for sealing) or USB-C on the side (prototype).
* Keep the antenna area (chip antenna/PCB antenna end) away from the hand/metal; the
  wrap and body detune it — test range with the wrap on.

## XIAO nRF52840 Sense specifics used by the firmware

* IMU: LSM6DS3TR-C on I2C0 @ 0x6A, INT1 → P0.11, power enable P1.08 (`lsm6ds3tr-c-en`).
* Battery sense: VBAT divider on P0.31 (AIN7) enabled by P0.14 (not implemented yet).
* Bootloader: Adafruit nRF52 UF2 at 0xF4000 + SoftDevice/MBR at 0x0–0x27000 — kept;
  MCUboot is chain-loaded at 0x27000 (see `firmware/README.md`).
* 2 MB QSPI NOR (P25Q16H) available for session storage; kept in deep power-down.
* PDM microphone, UART, USB stack disabled in the overlay/prj.conf to save power.
