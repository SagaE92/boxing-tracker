# Power design and budget

**Goal:** one week per charge with up to **10 sessions × 1 h** (~10 h active) plus a
week of standby, in the smallest package. Target cell 40–60 mAh (`docs/components.md`).
For comparison, Corner-style trackers (reported ~25 × 35 × 8 mm, 10 g) are said to last
4–12 h per charge (figures from the competitor comparison, not verified here) — we get
to a week by **never streaming in normal use**:

* on-device detection, BLE sends **punch events only** (16 B each); raw streaming is an
  opt-in dev/data-collection build (`CONFIG_BTRK_RAW_STREAM`, default **n**), so the
  default firmware cannot be put into the raw mode by accident
* a **long connection interval** (100–200 ms, slave latency 4) during sessions
* **System OFF** whenever idle, woken by the **IMU wake-on-motion** interrupt
* **no button** (motion is the only wake source; `POWER_OFF` opcode or timeouts put it to sleep)
* **on-device event log** on the XIAO's 2 MB QSPI NOR (v1.1): every strike is stored, so
  the phone need not stay connected; fetch after the session (GATT 0x000A, `docs/gatt-spec.md`)
* charging through **pogo pins** (magnetic 2–4 pin) is preferred over a USB-C receptacle
  for a sealed, sweat-proof enclosure; USB-C side charging stays an option for the prototype

All currents below are **estimates** built from datasheet typicals (25 °C) — measure the
real board with a PPK2 or similar before trusting them.

## Datasheet figures used

| Part | Figure | Value | Source |
|---|---|---|---|
| nRF52840 | System OFF, no RAM retention (`I_OFF_RAMOFF_RESET`) | 0.40 µA | nRF52840 PS v1.x, Sleep table |
| nRF52840 | System ON, full RAM, RTC wake (`I_ON_RAMON_RTC`) | 3.16 µA | PS, Sleep table |
| nRF52840 | System ON, full RAM, wake on GPIOTE IN event | 17.37 µA | PS — why the IMU IRQ uses a *level*/SENSE interrupt (2.36 µA PORT event) |
| nRF52840 | CPU from flash, CoreMark | 52 µA/MHz (≈3.3 mA at 64 MHz) | PS key features |
| nRF52840 | Radio TX 0 dBm / RX 1 Mbps, DC/DC | 6.40 mA / 6.26 mA | PS, Radio table |
| LSM6DS3TR-C | Gyro + accel, high-performance (`IddHP`, ODR 1.6 kHz) | 0.90 mA | DS DocID030071 Rev 3, Table 4 (Vdd 1.8 V) |
| LSM6DS3TR-C | Gyro + accel, normal mode (`IddNM`, ODR 208 Hz) | 0.45 mA | Table 4 |
| LSM6DS3TR-C | Accel only, low-power (`LA_IddLM`, ODR 12.5 Hz) | 9 µA | Table 4 |
| LSM6DS3TR-C | Power-down (`IddPD`) | 3 µA | Table 4 |
| Protection IC | TI BQ2970 (if using a bare cell) | 4 µA typ | see `docs/components.md` |

416 Hz is a high-performance-mode ODR on this IMU, so we assume the 0.90 mA HP figure
(the table quotes it at 1.6 kHz; HP current is roughly ODR-independent — *estimate*).

## Firmware power state machine (`firmware/src/power.c`)

```
             any motion (IMU wake-up INT1 → GPIO SENSE)
  ┌───────────────┐ ───────────────────────────────▶ ┌──────────────┐
  │  SYSTEM OFF   │                                  │  ADV FAST    │ 100–150 ms, 30 s
  │ nRF 0.4 µA +  │ ◀──── no connection, 5 min ───── │  IMU off     │
  │ IMU WoM 9 µA  │            (ADV_TIMEOUT)         └──────┬───────┘
  └───────────────┘ ◀──────────┐                          │ 30 s
          ▲                    │                   ┌──────▼───────┐
          │ POWER_OFF opcode   └────────────────── │  ADV SLOW    │ ~1 s interval
          │                                        └──────┬───────┘
          │                                   connect     │      ▲ disconnect
          │                                        ┌──────▼───────┐
          │                 conn idle 10 min ────▶ │  CONNECTED   │ IMU off,
          │                 (disconnect)           │              │ 100–200 ms interval
          │                                        └──────┬───────┘
          │                         SESSION_START         │      ▲ SESSION_STOP /
          │                                        ┌──────▼───────┐ no strike 10 min
          └──────────────────────────────────────  │   SESSION    │ IMU 416 Hz FIFO,
                                                   │ (+raw: dev)  │ detector on-device
                                                   └──────────────┘
```

* Session survives a disconnect (advertises slowly to reconnect) and keeps logging events
  to the QSPI flash; it auto-stops after `CONFIG_BTRK_SESSION_IDLE_TIMEOUT_S` (600 s) without
  a strike. After the stop the device advertises for the rest of `CONFIG_BTRK_ADV_TIMEOUT_S`
  and then goes to System OFF; fetching the log before that keeps it in the same boot as
  the session (better clock alignment, `docs/gatt-spec.md` "Caveat for flash-log sessions").
* Before System OFF the event-log queue is flushed to flash; the QSPI NOR is in deep
  power-down (P25Q16H DPD: µA-class or below — check its datasheet; *not measured*) whenever it is not
  being read or written (Zephyr runtime PM on the `nordic,qspi-nor` driver), including in
  System OFF.
* The pairing window (role changes, new bonds) is open for 120 s after a RESET tap or
  power-on only; a wake-on-motion boot does not open it.
* Before System OFF: IMU → accel-only 12.5 Hz low-power, ±2 g, wake-up threshold
  125 mg (`CONFIG_BTRK_WOM_THRESHOLD_MG`, 31.25 mg steps), latched on INT1; INT1 is set
  as a level-high SENSE pin, then `sys_poweroff()`. The IMU regulator GPIO (P1.08 on the
  XIAO) keeps its state in System OFF, so the IMU stays powered.
* Timeouts are Kconfig options (`firmware/Kconfig`).

## Per-state current (estimates)

| State | Contributors | Estimate |
|---|---|---|
| **Session (events only)** | IMU HP 416 Hz 0.90 mA; FIFO burst reads 5 kB/s over 400 kHz I2C ≈ 12 % duty × ~0.5 mA (TWIM + HFINT, estimate) ≈ 60 µA; detector ≈ 20 µs/sample × 416/s at 3.3 mA ≈ 28 µA; BLE at 200 ms + latency 4 + ~0.5 events/s ≈ 20 µA (estimate, check with Nordic Online Power Profiler); System ON base 3 µA; board leakage ~6 µA | **≈ 1.0 mA** |
| Session, IMU at 208 Hz normal mode (option) | IMU 0.45 mA, rest as above | ≈ 0.55 mA |
| Raw streaming (dev only) | above + 7.5–15 ms interval, ~23 × 244 B notifications/s on 2M PHY | ≈ 2–3 mA |
| Connected idle | IMU power-down 3 µA; BLE 100–200 ms ≈ 25–40 µA | ≈ 40 µA |
| Advertising fast (30 s after wake) | 100–150 ms, 3 channels, ~31 B | ≈ 100–150 µA |
| Advertising slow | ~1 s interval | ≈ 15–20 µA |
| **System OFF + WoM** | nRF 0.4 µA; IMU accel LP 9 µA; protection IC 4 µA; LDO/charger leakage ~0.5 µA | **≈ 14 µA** |

The XIAO dev board will be worse in OFF (its own LDO, charger, and the battery-sense
divider) — measure it; the numbers above are for the custom board.

## Weekly budget (10 × 1 h sessions + standby)

| Item | Calculation | mAh / week |
|---|---|---|
| Sessions | 10 h × 1.0 mA | **10.0** (1.0 mAh per session) |
| Standby | (168 − 10) h × 0.014 mA | **2.2** |
| False wakes (bag, walking) | 20/day × 7 × (30 s × 0.13 mA + 270 s × 0.02 mA) ≈ 140 × 0.0026 mAh | 0.4 |
| Pre/post-session connected + summary sync | 10 × 5 min × 0.05 mA | 0.04 |
| **Total** | | **≈ 12.7 mAh** |
| Design margin | × 1.5 for estimate error, × 1/0.8 usable capacity (cut-off voltage, ageing, cold) | **≈ 24 mAh needed** |

**Smallest cell that meets it:** about **25–30 mAh**, so the **40 mAh** end of the
40–60 mAh target already gives ~1.7× on top of the margin above (≈ 3× the raw
estimate). Choose the thinnest 40–50 mAh option that fits, e.g. VARTA CP1240 A4X coin
(50 mAh, Ø12.1 × 4.0 mm) or a ~3–4 mm pouch (`docs/components.md` lists candidates).
At 208 Hz the weekly total drops to ≈ 8 mAh. If the user wants raw streaming
regularly (a firmware built with `CONFIG_BTRK_RAW_STREAM=y`), go 50–60 mAh (raw ≈ 2.5 mA → a 40 mAh cell gives ~12 h of raw streaming).

Biggest levers, in order: IMU ODR/mode (0.90 vs 0.45 mA), keeping BLE out of the hot
path (events only, long interval, or flash logging), standby leakage (protection IC,
LDO quiescent, divider), and false wakes (raise the WoM threshold or require ~2 s of
motion before advertising).

## Two sensors (one inside each wrap)

The kit is now **two identical devices**, one per hand wrap, each with the **same
per-device budget and size target** as above (40–60 mAh cell, ≤ 25 × 20 mm board,
~1 week across up to ~10 sessions). Nothing is shared between the hands, so the table
above applies to each device unchanged; the pair simply needs two cells and two charges
(a dual pogo-pin dock charges both at once).

What two sensors add per device is small:

| Item | Per device, per week |
|---|---|
| Time-sync bursts (8 reads + 1 anchor write at connect, every 30 s while connected, before a log fetch) | < 0.01 mAh (a few extra connection events) |
| Role in advertising manufacturer data (10 bytes; ADV is now the full 31 bytes) | ~+5 % per advertising event (longer packets) — negligible next to the session |
| Event log on QSPI NOR: one 32-byte page program per event (~0.5 events/s × ~1 ms at ~4 mA, *estimate*) + DPD exit/enter + a 4 KB sector erase per 128 records | ≈ 2–5 µA average during a session → < 0.05 mAh/week (*estimate, measure*) |
| QSPI NOR in deep power-down (always, also System OFF) | ≤ ~1 µA assumed → ≤ 0.17 mAh/week (*not measured*) |
| Battery divider (P0.14 held low, 1.51 MΩ at 4.2 V) | ~2.8 µA → ~0.47 mAh/week (XIAO only; the custom board should switch it) |
| Phone holding two connections | none on the device side (each device still has one link) |

In events-only mode (the default) no clock sync over BLE is needed during the session:
each device timestamps events on its own clock and logs them to flash; the time anchors
written at connect and before the log fetch give offset + drift (as long as the device did
not sleep in between), so the weekly totals above stand. Only the phone pays for the
second connection.

None of these numbers have been measured; `docs/bringup.md` lists what to check with a
current meter first.

## Charging

* The prototype XIAO charges at a fixed 50 mA (100 mA with P0.13 low) — that is 1C+
  for a 40–50 mAh cell, so use a 1C-rated cell or a larger one for the prototype.
* Custom board: a charger programmable to ~0.5C (20–25 mA) — see `docs/components.md`
  (nPM1304 or BQ25100) — with charge contacts on **pogo pins** in a sealed shell (no
  USB receptacle to seal, no button).
