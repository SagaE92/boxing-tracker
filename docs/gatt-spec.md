# Boxing Tracker BLE GATT specification (protocol v1.1)

Source of truth for the wire format. Firmware: `firmware/src/bt_proto.h` (packed C
structs + `static_assert` sizes). Host: `tools/proto.py`. A host test
(`tools/tests/test_logger.py`) compiles the firmware packer with gcc and decodes
its output with `proto.py`, so the three must agree. v1.1 (two sensors: role, time sync,
event log) only adds characteristics and opcodes; v1.0 centrals keep working.

* All multi-byte fields are **little-endian**, structs are packed (no padding).
* Device name `BoxTrk-L` (role lead), `BoxTrk-R` (rear) or `BoxTrk` (no role yet); match
  on the `BoxTrk` prefix or the service UUID. ADV = flags + 128-bit service UUID +
  manufacturer data (role, below) = 31 bytes; the name is in the scan response.
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
| 0x0008 | `6e7b0008-…` | Time sync (v1.1) | read, write |
| 0x0009 | `6e7b0009-…` | Hand role (v1.1) | read, write |
| 0x000A | `6e7b000a-…` | Event log (v1.1) | read, write, notify |

Standard services also exposed:

| Service | UUID | Notes |
|---|---|---|
| Battery Service | `0x180F` (Battery Level `0x2A19`, read/notify, %) | Zephyr `CONFIG_BT_BAS`. From the XIAO VBAT divider (AIN7, `src/battery.c`), every 5 min and after connect; generic LiPo curve, ±10 %. **Not yet checked against a multimeter.** Falls back to a fixed 100 % if the ADC is unavailable. |
| Device Information | `0x180A` | Model `BoxTrk-XIAO`, manufacturer `DIY` |
| SMP (MCUmgr) DFU | service `8d53dc1d-1db7-4cd3-868b-8a527460aa84`, characteristic `da2e7828-fbce-4e01-ae9e-261174997c48` | Zephyr `CONFIG_MCUMGR_TRANSPORT_BT`: image upload/test/confirm, reset. Use nRF Connect Device Manager (iOS/Android) or `mcumgr`/`smpmgr`. **Unauthenticated in this prototype** (issue #3): v1.1 enables SMP pairing/bonding for the role, but the DFU characteristic still needs no pairing — add `CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN` + an authenticated pairing method before shipping. Images are signed with MCUboot's development key (issue #2). |

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
| 0x08 `FORGET` (v1.1) | – | clear role + wrist and delete **all** bonds; same permission rule as a role write (below); refused during a session |

`ROUND_MARK` (v1.1): also appended to the event log with the device time; offline,
`tools/evlog.py` treats n > 0 as "round n starts" and 0 as "rest starts"
(`tools/logger.py` sends them for the `round` / `rest` labels).

Response indication (3 bytes): `0x80, request_opcode, status` with status 0 OK,
1 unsupported opcode, 2 invalid parameter, 3 bad state (e.g. start while active),
4 not permitted (v1.1: role locked — pairing window closed and link not bonded).

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
| 1 | u8 | `hand` | sensor hand: 0 lead, 1 rear. v1.1: follows the stored role (0x0009); a write that conflicts with a set role fails with 0x13; with no role yet, writing Config assigns the role (v1.0 centrals) |
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

## Two sensors, one inside each wrap (protocol v1.1)

A kickboxer wears one tracker inside each hand wrap. Per-device size and battery targets
are unchanged (see `docs/power.md`); the phone/laptop (central) connects to both at once.
**Status:** host side (`tools/logger.py`, `tools/evlog.py`, `analysis/detector.py --stream`,
schema 1.1.0) and firmware (this section) are implemented. The firmware builds and its
portable parts are unit-tested on the host, but **none of it has run on hardware yet**
(`docs/bringup.md`).

### Hand role (0x0009, read/write), 4 bytes, stored on the device

| Offset | Type | Field |
|---|---|---|
| 0 | u8 | `role`: 0 unset, 1 lead, 2 rear |
| 1 | u8 | `wrist`: 0 unknown, 1 left, 2 right (follows from role + stance; stored so the device can advertise it) |
| 2 | u8 | flags (read-only): bit0 pairing window open, bit1 this link is encrypted with a bonded peer, bit2 role persisted in settings |
| 3 | u8 | seconds left in the pairing window (read-only) |

Write 2 bytes (`role, wrist`) or 4 (flags/seconds ignored). Persisted with Zephyr settings on
the internal `storage_partition` (NVS, keys `btrk/role`, `btrk/wrist`), so it survives
power-off and is advertised before any connection.

**Who may change it** (`btrk_role_write_allowed`, host-tested):

* during the **pairing window**: the first `CONFIG_BTRK_ROLE_WINDOW_S` (120 s) after a
  **tap on RESET or a power-on** (battery connected). A wake from System OFF (motion in a
  gym bag) does **not** open it;
* or over a link **encrypted with a bonded peer** (pair once inside the window; Just Works);
* or while **no role is set** (a fresh device).

Otherwise the write fails with ATT 0x05 (insufficient authentication: the central should
pair) or 0x03 (write not permitted, already encrypted but not bonded). Role writes are also
refused during a session. New bonds are accepted only inside the window or while the device
has no bonds (`CONFIG_BT_SMP_APP_PAIRING_ACCEPT`, `CONFIG_BT_MAX_PAIRED=4`).

**Reset path:** write role 0 (`00 00`), or control op 0x08 `FORGET` (also deletes all bonds),
both under the rules above. Physically: tap RESET once, then do either within 2 minutes
(`tools/logger.py --forget`). A double-tap enters the UF2 bootloader instead.

Pairing UX: "tap RESET on the tracker in your LEAD wrap" → the app connects to the device
advertising the window-open flag → writes role 1. Same for the rear wrap.
`tools/logger.py --assign-role lead|rear [--wrist L|R] [--address …]`.

### Advertising (v1.1)

ADV: flags (3 B) + 128-bit service UUID (18 B) + **manufacturer-specific data** (10 B) = 31 B:

| Offset | Type | Field |
|---|---|---|
| 0 | u16 | company ID `0xFFFF` (reserved for testing / prototypes; a product needs its own ID) |
| 2 | u8 | `0x11` = protocol major 1, minor 1 |
| 3 | u8 | role (0 unset, 1 lead, 2 rear) |
| 4 | u8 | wrist (0 unknown, 1 L, 2 R) |
| 5 | u8 | flags: bit0 session active, bit1 event log has records not ACKed yet, bit2 pairing window open |
| 6 | u16 | low 16 bits of the FICR device ID (tells two `BoxTrk-L`s apart) |

Scan response: complete name `BoxTrk-L` / `BoxTrk-R` / `BoxTrk` (also the GAP Device Name).
Updated live (`bt_le_adv_update_data`) when the role, session or log state changes.
Parsers: `proto.parse_adv_mfg` (bleak's `manufacturer_data`), name fallback
`proto.role_from_name`. (The earlier draft put the role in **service data**; that does not fit
next to a 128-bit UUID in 31 bytes, so v1.1 uses manufacturer data.
`proto.parse_role_service_data` remains only for old captures.)
`tools/logger.py --device lead=auto --device rear=auto` picks the sensors by role.

### 0x0008 Time sync (read 8 bytes, write 14 bytes)

Read:

| Offset | Type | Field |
|---|---|---|
| 0 | u32 | `device_time_us` — the same 32-bit microsecond counter as the raw stream's `t0_us`, the IMU sample timestamps and the log's device times (`k_uptime` in µs, truncated), sampled when the read is handled |
| 4 | u16 | `boot_id` — increments every boot (the counter restarts at 0 at every boot, including each wake from System OFF) |
| 6 | u8 | flags: bit0 session active |
| 7 | u8 | reserved |

(Readers must accept ≥ 4 bytes; `proto.parse_time_sync` reads the first u32.)

Write — **time anchor**, stored as an `ANCHOR` record in the event log:

| Offset | Type | Field |
|---|---|---|
| 0 | u64 | `host_unix_us` — host clock at the exchange midpoint |
| 8 | u32 | `device_time_us` read in that exchange |
| 12 | u16 | its round-trip time, 0.1 ms units |

The central aligns clocks with NTP-style exchanges (`tools/logger.py DeviceRecorder.sync_burst`):

1. **At connect** and then **every 30 s** (`--sync-every`) and **at stop**, do a burst of 8 reads
   per device. For each: `t_req`, read, `t_resp` on the host clock; record
   (`host = (t_req + t_resp)/2`, `device_time_us`, `rtt = t_resp − t_req`) in `<out>_sync.csv`
   (source `rtt`). Then **write the lowest-RTT exchange back as an anchor** (v1.1 firmware,
   i.e. when the read returned 8 bytes), so the device's own log carries host time.
2. Offline (`analysis/detector.py fit_clock`), per device: keep the lowest-RTT third of each
   5 s window (least asymmetric), unwrap the u32 counter, fit
   `host_time = a + b·device_time` (offset `a`, drift `b − 1`), and map every sample onto one
   session timeline (t = 0 at the earliest aligned first sample).
3. Firmware without 0x0008: the logger also records (device time of each notification's last
   sample, host arrival time) every ~2 s; BLE latency only adds delay, so the lower envelope
   of those points is fitted instead (drift is recovered; a common latency bias remains).

**Skew tolerance: target ≤ 2 ms between the two sensors after alignment.** Why that number:

* It is under one sample period (2.4 ms at 416 Hz), so a strike's peak lands on the same or
  the adjacent sample on both timelines.
* It is ~75× smaller than the 150 ms refractory window and ~150× smaller than the 300 ms
  minimum gap between punches in a combo, so the merge (cross-sensor crosstalk window 60 ms,
  combo gap 600 ms) never mis-orders strikes from the two hands.
* It is achievable: with a 7.5 ms connection interval the best round trip is one interval;
  the absolute error of one exchange is at most half of that (≤ 3.75 ms) and is mostly a
  *systematic* bias that both sensors share (same firmware, same interval), so it cancels
  between them. Drift is the real risk: nRF52840 32 MHz crystals are ±20–40 ppm, i.e. up
  to ~140 ms per hour uncorrected; fitting `b` removes it (tests: ≤ 1 ppm residual).
* Tests: `tools/tests/test_logger.py::test_time_sync_bursts_align_two_sensors_within_2ms`
  (fake BLE link, 32-bit wrap, ±35/−20 ppm, checks the anchors written) and
  `analysis/tests/test_two_sensors.py::test_rtt_sync_aligns_within_tolerance_over_40_min`.

**Caveat for flash-log sessions.** Anchors only place records **of the same boot**: the
device clock restarts after every System OFF wake. A session recorded while connected (the
logger writes an anchor every 30 s) gets the full offset + drift fit. A session started, then
left disconnected, then fetched **before the device sleeps** gets anchors from the start and
from the fetch — also a full fit. If the device slept in between, that session's boot has only
its start-time anchors: offset exact, drift (±20–40 ppm, ≤ ~0.15 s per hour) uncorrected,
and `tools/evlog.py` reports a single-anchor fit (`sync_points` 1). A boot without any anchor
cannot be placed and is refused with a message.

### 0x000A Event log (read 16 bytes / write ops / notify records)

On-device strike detection (`firmware/src/punch_detect.c`, a streaming port of
`analysis/detector.py find_peaks`: threshold 3.5 g on |a|−1 g, candidate extends while
≥ threshold/2 up to 2×150 ms, first maximum, refractory 150 ms; same peak index, peak g,
speed estimate, bounds and gyro integral as the Python detector on the same samples —
`analysis/tests/test_firmware_detector.py`) runs in every session. Each event is notified
on 0x0002 **and** appended to a ring log on the XIAO's 2 MB QSPI NOR (P25Q16H), connected or
not, together with session start/stop, round marks, boot records and time anchors.

Read — log info:

| Offset | Type | Field |
|---|---|---|
| 0 | u32 | `first_seq` (oldest record still stored) |
| 4 | u32 | `next_seq` (seq of the next record to be written) |
| 8 | u32 | `capacity` (records; 65,408 on the XIAO) |
| 12 | u16 | `boot_id` |
| 14 | u8 | record size (32) |
| 15 | u8 | flags: bit0 a READ is in progress, bit7 no flash (log disabled) |

Write — operations:

| Op | Payload | Action |
|---|---|---|
| 0x01 `READ` | u32 `from_seq`, u32 `max_records` (0 = all) | notify all stored records with seq ≥ from_seq, oldest first, `floor((MTU−3)/32)` per notification (7 at MTU 247), then one `END` record. Enable notifications on 0x000A first |
| 0x02 `ABORT` | – | stop a READ (also on disconnect) |
| 0x03 `ERASE` | u32 `0x45524153` ("ERAS") | erase the whole log (seconds); the sequence continues with an `ERASED` record |
| 0x04 `ACK` | u32 `seq` | host has everything below `seq`; persisted; clears the advertised "log pending" flag. Records are **not** deleted (the ring overwrites the oldest sector when full) |

Errors: ATT 0x13 bad parameter, 0x06 unknown op, 0xFE READ/ERASE while busy or no flash.

Record (32 bytes): `u8 type, u8 flags (0), u16 boot_id, u32 seq, u8 payload[22], u16 crc`,
CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over bytes 0..29. Payloads (little-endian,
device times are the 32-bit µs counter of that boot):

| Type | Name | Payload |
|---|---|---|
| 0x01 | `SESSION_START` | u32 session_id, u32 dev_t0_us, u8 role, u8 wrist, u8 stance, u8 odr_code, u16 threshold_cg, u16 refractory_ms, u8 fw major/minor/patch, 3 × pad |
| 0x02 | `EVENT` | u32 dev_t_peak_us, u8 type, u8 flags (as 0x0002), u16 peak_cg, u16 speed_cms, u16 peak_gyro_dps, u8 confidence, u8 pre (peak − start, 2 ms units), u8 post (end − peak, 2 ms units), i16 × 3 gyro integral over ±150 ms (0.1°, **sensor frame**), pad |
| 0x03 | `ANCHOR` | the 14-byte 0x0008 write, pad |
| 0x04 | `SESSION_STOP` | u32 session_id, u32 duration_ms, u32 dev_t_us, u16 punch_count, pad |
| 0x05 | `ROUND_MARK` | u32 dev_t_us, u8 round, pad |
| 0x06 | `BOOT` | u32 reset cause (Zephyr hwinfo bits), u8 role, u8 wrist, pad |
| 0x07 | `ERASED` | – (first record after an ERASE) |
| 0xFE | `END` | transfer only: u32 records_sent, u32 device next_seq |

Storage (`firmware/src/evlog.c`, portable C, host-tested on a RAM model of NOR flash):
4 KB sectors × 128 records; records are programmed once (NOR 1→0), a torn record (power
loss mid-write) fails its CRC and is skipped; mount reads the first record of every sector
to find the newest one, then scans it for the first free slot. The QSPI flash sits in deep
power-down between accesses (runtime PM). Event types on the device are the calibration
straight (jab for the lead sensor, cross for the rear) and `unknown` — **strike
classification is not ported to the firmware**; run `analysis/detector.py` on raw data
for types.

Host side: `tools/logger.py --fetch-log --device lead=auto --device rear=auto --out s1`
(writes an anchor first, then `s1_lead_log.bin`, `s1_rear_log.bin`; `--ack` marks them
synced), then `tools/evlog.py session --log lead=s1_lead_log.bin --log rear=s1_rear_log.bin
--session-out s1_session.json` builds a schema-1.1.0 session (clock source `anchor`,
merge with `detector.merge_events`, rounds from round marks). Tests:
`tools/tests/test_two_sensor_fw.py`.

### Merging the two streams

Detection runs per device (each with its own calibration and `hand` role); events are then
merged by time (`detector.merge_events`): a peak on the other wrist within 60 ms that is
< 50 % of the stronger one is crosstalk (body motion from the punching hand) and is dropped;
two comparable peaks are both kept (near-simultaneous strikes). Kick/body movement and clinch,
which both sensors feel, are merged into one event. Rounds are the union of both devices'
round spans. Each event carries `device_id` (schema 1.1.0, `session.devices[]` holds role,
wrist, firmware version and the applied clock offset/drift).

## Planned

* On-device strike classification (port of `analysis/detector.py classify`; needs the
  calibration rotation and the feature window on the device).
* Authenticated SMP DFU (issue #3) and a production MCUboot key (issue #2).
* Auto-starting a session on wake-on-motion (today a session is started by the central and
  then survives disconnects).
