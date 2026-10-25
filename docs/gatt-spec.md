# Boxing Tracker BLE GATT specification (protocol v1)

Source of truth for the wire format. Firmware: `firmware/src/bt_proto.h` (packed C
structs + `static_assert` sizes). Host: `tools/proto.py`. A host test
(`tools/tests/test_logger.py`) compiles the firmware packer with gcc and decodes
its output with `proto.py`, so the three must agree.

* All multi-byte fields are **little-endian**, structs are packed (no padding).
* Device name `BoxTrk`; advertises the custom service UUID (flags + 128-bit UUID in
  ADV, name in scan response).
* Recommended ATT MTU: **247** (the firmware enables DLE 251 and asks for 2M PHY).
  Web Bluetooth / BlueZ / iOS negotiate large MTUs automatically. Minimum for raw
  streaming is 33.

## UUIDs

Base: `6e7bXXXX-4b1d-4c8a-9a3e-2f5b0c1d7a00` (XXXX = 16-bit alias below).

| Alias | UUID | Name | Properties |
|---|---|---|---|
| 0x0001 | `6e7b0001-4b1d-4c8a-9a3e-2f5b0c1d7a00` | Boxing Tracker service | primary |
| 0x0002 | `6e7b0002-…` | Punch event | notify |
| 0x0003 | `6e7b0003-…` | Session control point | write (with response), indicate |
| 0x0004 | `6e7b0004-…` | Session summary | read, notify |
| 0x0005 | `6e7b0005-…` | Raw IMU stream | notify |
| 0x0006 | `6e7b0006-…` | Config | read, write |
| 0x0007 | `6e7b0007-…` | Status | read, notify |

Standard services also exposed:

| Service | UUID | Notes |
|---|---|---|
| Battery Service | `0x180F` (Battery Level `0x2A19`, read/notify, %) | Zephyr `CONFIG_BT_BAS`. Value is a placeholder (100 %) until the ADC reader is written (`src/battery.c`). |
| Device Information | `0x180A` | Model `BoxTrk-XIAO`, manufacturer `DIY` |
| SMP (MCUmgr) DFU | service `8d53dc1d-1db7-4cd3-868b-8a527460aa84`, characteristic `da2e7828-fbce-4e01-ae9e-261174997c48` | Zephyr `CONFIG_MCUMGR_TRANSPORT_BT`: image upload/test/confirm, reset. Use nRF Connect Device Manager (iOS/Android) or `mcumgr`/`smpmgr`. **Unauthenticated in this prototype** — add pairing/bonding + `BT_GATT_PERM_*_AUTHEN` before shipping. |

## 0x0005 Raw IMU stream (notify) — dev / data-collection mode only

Started with control op `RAW_START`. One notification = 18-byte header + `n` × 12-byte samples.
`n = min(18, (ATT_MTU − 3 − 18) / 12)` → 18 samples (234 bytes) at MTU ≥ 237;
≈ 23 notifications/s at 416 Hz (~5.4 kB/s).

Header (18 bytes):

| Offset | Type | Field | Meaning |
|---|---|---|---|
| 0 | u16 | `seq` | packet counter, wraps; gaps = lost packets |
| 2 | u8 | `n` | samples in this packet, 1..18 |
| 3 | u8 | `flags` | bit0 `FIFO_OVERRUN` (IMU FIFO overflowed before this packet), bit1 `RING_OVERRUN` (firmware ring/BLE dropped samples), bit2 `TS_RESYNC` (time base re-anchored, expect a timestamp jump) |
| 4 | u32 | `t0_us` | device time of sample 0, µs, **wraps every 71.6 min** (host unwraps) |
| 8 | u16 | `period_us` | sample spacing; sample *i* is at `t0_us + i·period_us` (~2404 µs at 416 Hz) |
| 10 | u32 | `accel_sat_mask` | bit *i* = sample *i* has any accel axis with \|raw\| ≥ 32100 (≥ 15.66 g, 98 % of ±16 g) |
| 14 | u32 | `gyro_sat_mask` | bit *i* = sample *i* has any gyro axis with \|raw\| ≥ 28000 (≥ 1960 dps, 98 % of ±2000 dps) |

Sample (12 bytes), LSM6DS3TR-C chip axes, raw signed:

| Offset | Type | Field | Scale |
|---|---|---|---|
| 0,2,4 | i16 ×3 | `ax, ay, az` | × 0.488 mg/LSB (FS ±16 g; datasheet sensitivity) |
| 6,8,10 | i16 ×3 | `gx, gy, gz` | × 70 mdps/LSB (FS ±2000 dps) |

Note the accel output clips at ±32767 LSB = ±15.99 g; anything flagged in the mask
is a **lower bound** (see `docs/hardware-notes.md`).

The logger writes `sat = 1` in the CSV when either mask bit is set.

## 0x0002 Punch event (notify), 16 bytes

Sent once per detected event (strike or non-strike event) during a session.

| Offset | Type | Field | Meaning |
|---|---|---|---|
| 0 | u16 | `index` | event number within the session, from 0 |
| 2 | u32 | `t_ms` | peak time, ms since session start (for `clinch`: start time) |
| 6 | u8 | `type` | 0 unknown, 1 jab, 2 cross, 3 lead_hook, 4 rear_hook, 5 lead_uppercut, 6 rear_uppercut, 7 overhand, 8 spinning_backfist, 9 kick_or_body_movement, 10 clinch (same enum as `docs/session.schema.json`) |
| 7 | u8 | `flags` | bit0 `ACCEL_SAT` (peak clipped → `peak_cg` is a lower bound), bit1 `GYRO_SAT`, bit2 `REAR_HAND` (sensor on rear hand, else lead), bits3–4 `target` (0 none/null, 1 head, 2 body), bit5 `UNCALIBRATED` (calibration not done yet) |
| 8 | u16 | `peak_cg` | peak \|a\| − 1 g, in 0.01 g |
| 10 | u16 | `speed_cms` | hand-speed **estimate**, cm/s (heuristic integral of accel; not ground truth) |
| 12 | u16 | `peak_gyro_dps` | peak \|ω\|, dps. For `clinch`: duration in 10 ms units |
| 14 | u8 | `confidence` | 0–100 → confidence 0.00–1.00 |
| 15 | u8 | reserved | 0 |

There is deliberately no "power" field: report `peak_g` and `speed_mps_est`.
Firmware v0.1 detects strikes on-device but sends `type = 0 (unknown)`, except the
calibration strike; the reference classifier is `analysis/detector.py` and will be
ported once validated on real recordings.

## 0x0003 Session control point (write with response; responses by indication)

| Opcode | Payload | Action |
|---|---|---|
| 0x01 `SESSION_START` | u32 `session_id` (e.g. unix time) | start a session; IMU on; calibration begins (below) |
| 0x02 `SESSION_STOP` | – | stop; summary is notified on 0x0004 |
| 0x03 `RAW_START` | – | start raw streaming on 0x0005 (also powers the IMU; requests 7.5–15 ms connection interval) |
| 0x04 `RAW_STOP` | – | stop raw streaming |
| 0x05 `ROUND_MARK` | u8 round number | informational marker (logged) |
| 0x06 `POWER_OFF` | – | stop session, enter System OFF (wake on motion) |
| 0x07 `CALIBRATE` | – | redo guard-pose + straight-punch calibration |

Response indication (3 bytes): `0x80, request_opcode, status` with status 0 OK,
1 unsupported opcode, 2 invalid parameter, 3 bad state (e.g. start while active).

### Session start / calibration flow

1. App writes `SESSION_START`. Status bit3 (`calibrating`) = 1.
2. User holds a **neutral guard** for 2 s (`CONFIG_BTRK_CAL_GUARD_MS`); the firmware
   averages the gravity vector. If the wrist moves (|a| deviates > 0.15 g) the window restarts.
3. User throws **one straight punch with the sensor hand** (a jab if the sensor is on
   the lead hand, a cross if on the rear hand). Its peak acceleration direction
   (minus gravity) is the forward axis. That event is reported with type jab/cross and confidence 100.
4. Status bit2 (`calibrated`) = 1. Later events no longer carry `UNCALIBRATED`.

Axis convention: `docs/axes.md`.

## 0x0004 Session summary (read, notify on stop), 40 bytes

| Offset | Type | Field |
|---|---|---|
| 0 | u32 | `session_id` |
| 4 | u32 | `duration_ms` |
| 8 | u16 | `punch_count` (strikes only; excludes kick_or_body_movement and clinch) |
| 10 | u16 ×11 | `by_type[0..10]`, indexed by the punch `type` enum |
| 32 | u16 | `max_peak_cg` |
| 34 | u16 | `mean_peak_cg` |
| 36 | u16 | `rate_ppm_x10` (punches per minute × 10) |
| 38 | u8 | `state` (bit0 = active) |
| 39 | u8 | `saturated_count` (strikes with clipped peak, saturates at 255) |

## 0x0006 Config (read/write), 8 bytes

| Offset | Type | Field | Values |
|---|---|---|---|
| 0 | u8 | `version` | protocol version (1), read-only |
| 1 | u8 | `hand` | sensor hand: 0 lead, 1 rear |
| 2 | u8 | `stance` | 0 orthodox (left lead), 1 southpaw |
| 3 | u8 | `odr_code` | 0 = 416 Hz (only value in v1) |
| 4 | u16 | `threshold_cg` | detector threshold on \|a\|−1 g, 100..1500 (default 350 = 3.5 g) |
| 6 | u16 | `refractory_ms` | default 150 |

Invalid writes fail with ATT error 0x13 (value not allowed) or 0x0D (length).

## 0x0007 Status (read, notify), 4 bytes

| Offset | Type | Field |
|---|---|---|
| 0 | u8 | `power_state`: 0 boot, 1 adv fast, 2 adv slow, 3 connected, 4 session, 5 off |
| 1 | u8 | flags: bit0 raw streaming, bit1 session active, bit2 calibrated, bit3 calibrating |
| 2 | u16 | raw samples dropped since boot (saturating) |

## Connection parameters (peripheral requests)

| Mode | Interval | Latency | Supervision timeout |
|---|---|---|---|
| Events only (normal session) | 100–200 ms | 4 | 6 s |
| Raw streaming / DFU | 7.5–15 ms | 0 | 4 s (MCUmgr also raises it during DFU) |

## Planned (not in v1)

* On-device event log (`CONFIG_BTRK_SESSION_STORAGE`, internal flash or the XIAO's
  2 MB QSPI NOR) with a "sync log" characteristic so the phone can stay away during
  training (see `docs/power.md`).
* Bonding + authenticated SMP.
