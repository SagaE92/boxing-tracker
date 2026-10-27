# Firmware (Zephyr RTOS)

Target: **Seeed XIAO nRF52840 Sense**, board `xiao_ble/nrf52840/sense`.
Everything board-specific is in devicetree overlays:

| File | Purpose |
|---|---|
| `boards/xiao_ble_nrf52840_sense.overlay` | IMU node (`boxtrk,lsm6ds3trc-fifo`, I2C0 0x6A, INT1 P0.11), `chosen boxtrk,imu`, LED alias, disables unused peripherals, flash map, QSPI NOR `eventlog_partition` (2 MB, runtime PM), battery ADC (`zephyr,user` AIN7 + P0.14) |
| `boards/nrf52840_uf2_mcuboot_partitions.dtsi` | flash map that keeps the UF2 bootloader and chain-loads MCUboot |
| `boards/boxtrk_custom.overlay` | **placeholder** for the future custom board (not built) |
| `dts/bindings/boxtrk,lsm6ds3trc-fifo.yaml` | binding for our FIFO IMU driver |
| `sysbuild.conf`, `sysbuild/mcuboot.{conf,overlay}` | MCUboot built alongside the app |

## Modules (`src/`)

Portable C (no Zephyr headers; compiled and unit-tested on the host, `tests/host/`):

| File | What |
|---|---|
| `punch_detect.c` | streaming strike detector, a port of `analysis/detector.py find_peaks` + `event_bounds` + the speed/gyro features: \|a\|−1 g threshold, candidate while ≥ thr/2 up to 2 × window, first maximum, refractory, ±150 ms window. Same results as the Python detector on the same samples (`analysis/tests/test_firmware_detector.py`). No classification (type = unknown except the calibration straight) |
| `evlog.c` | append-only ring log of 32-byte CRC-protected records on NOR flash (through a small flash-ops struct): mount, append, overwrite-oldest, torn-write tolerant, erase with continuing sequence, iterator from a seq |
| `btrk_util.c` | CRC-16, advertising payload, role write policy, pairing-window rule, default wrist, LiPo mV → % |
| `ringbuf.c` | lock-free SPSC sample ring (IMU thread → raw-stream TX thread) |
| `raw_pack.c` | packs up to 18 samples per notification (MTU-sized) + per-sample saturation masks |
| `bt_proto.h` | wire format, shared with `tools/proto.py` |

Zephyr glue:

| File | What |
|---|---|
| `imu_lsm6ds3trc.c` | LSM6DS3TR-C raw-register driver: ±16 g / ±2000 dps, 416 Hz, continuous FIFO, watermark (12 samples) on INT1 as a level/SENSE interrupt, burst FIFO reads, pattern re-alignment, timestamp model (slow PLL against the RTC), wake-on-motion arm for System OFF |
| `session.c` | session start/stop, guard-pose + straight-punch calibration, summary counters; feeds the detector and logs start/stop/events/round marks |
| `event_log.c` | evlog on the QSPI NOR (`flash_area`), one writer thread with an append queue, READ transfers as notifications on 0x000A, ERASE / ACK |
| `role.c` | hand role + wrist, boot counter and log ACK in Zephyr settings (NVS, internal flash), pairing window from the reset cause, bonded-link check, FORGET |
| `ble_svc.c` | custom GATT service (`docs/gatt-spec.md`) incl. v1.1 time sync / role / event log, advertising with role manufacturer data and `BoxTrk-L/-R` name, pairing policy, connection parameters, raw TX thread |
| `power.c` | power state machine (`docs/power.md`): adv fast → slow → System OFF; session/idle timeouts; flushes the log before System OFF |
| `battery.c` | VBAT divider on AIN7 (P0.14 held low), SAADC, Battery Service level every 5 min and after connect |

Kconfig (`Kconfig`): `CONFIG_BTRK_ROLE_WINDOW_S` (120), `CONFIG_BTRK_RAW_STREAM` (**n** — events
only by default; set `y` for the raw-streaming debug / data-collection build, the detector and
log run regardless), `CONFIG_BTRK_BATTERY_PERIOD_S`
(300), plus the existing detector / timeout options.

MCUmgr SMP over BLE (image + OS groups) is enabled in `prj.conf`; MCUboot does
test-then-confirm swaps (swap-using-move), signed with MCUboot's **development key**
(`root-ec-p256.pem`) — replace it before giving a device to anyone.

## Two sensors (one per wrap)

Implemented in this firmware (details in `docs/gatt-spec.md` "Two sensors"):

* **Hand role** (lead/rear + wrist) on characteristic 0x0009, stored with Zephyr settings.
  Writable during a 120 s pairing window after a RESET tap / power-on, over a bonded link,
  or while unset; reset with role 0 or control op `FORGET` (also deletes bonds).
* **Advertising** carries the role in manufacturer data (company 0xFFFF, prototype) and the
  name becomes `BoxTrk-L` / `BoxTrk-R`. **0xFFFF is the Bluetooth SIG test/prototype company
  ID: it is for development only and must be replaced with an assigned company ID (or the
  data moved to a service-data UUID) before any device is distributed.**
* **Time sync** 0x0008: read the 32-bit µs device clock (+ boot id); write a time anchor that
  goes into the event log.
* **On-device detection + event log**: every strike, session start/stop, round mark, boot and
  anchor goes to a ring log on the 2 MB QSPI NOR; fetch it over 0x000A
  (`tools/logger.py --fetch-log`, `tools/evlog.py session`).
* **Battery** from the VBAT divider.
* **Raw streaming** is an opt-in debug / data-collection build (`CONFIG_BTRK_RAW_STREAM`,
  default **n**). The default firmware sends events only; build with
  `-DCONFIG_BTRK_RAW_STREAM=y` for `tools/logger.py` raw recordings.

Bring-up with two XIAOs: `docs/bringup.md`.

## Security (prototype only)

**Do not ship this configuration.** Two things must change before any public firmware
release or before a device leaves the developer's hands:

1. **MCUboot signs with the development key.** Images are signed with MCUboot's public
   sample key (`root-ec-p256.pem`), whose private half is published upstream, so anyone
   can build an image this bootloader will accept. Generate a production key
   (`imgtool keygen -t ecdsa-p256`), keep the private key out of the repo (CI secret /
   HSM), and point sysbuild at it (e.g. `SB_CONFIG_BOOT_SIGNATURE_KEY_FILE`).
2. **SMP/DFU over BLE is unauthenticated.** The MCUmgr SMP characteristic needs no
   pairing or bonding, so any nearby phone can upload an image or reset the device
   (combined with 1., flash arbitrary firmware). Require an authenticated, bonded link
   (e.g. `CONFIG_BT_SMP=y`, `CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN=y`, LE Secure
   Connections with passkey/numeric comparison), or only enable SMP in a
   button-triggered DFU mode.

3. **Advertising uses the test company ID 0xFFFF.** The manufacturer data (role, wrist,
   flags) is tagged with 0xFFFF, which the Bluetooth SIG reserves for testing. It is
   test-only: replace it with an assigned company ID (or switch to service data under our
   own UUID) before any distribution (`BTRK_ADV_COMPANY_ID` in `src/bt_proto.h`,
   `ADV_COMPANY_ID` in `tools/proto.py`).

Tracked as issues **#2** (production signing key) and **#3** (authenticated SMP DFU).
v1.1 turns on BLE pairing/bonding (`CONFIG_BT_SMP`, Just Works) for the hand role, but
that does **not** fix #3: the SMP characteristic still accepts unencrypted writes, and Just
Works pairing has no MITM protection. Bonds are only accepted inside the 120 s window after a
RESET tap / power-on (or while the device has none), which limits who can bond, nothing more.

## Build status (honest)

Built successfully on 2026-10-26 in a Linux box with **upstream Zephyr v4.1.0**
(Zephyr SDK 0.17.0, `arm-zephyr-eabi`), **with sysbuild + MCUboot**, also with
`CONFIG_COMPILER_WARNINGS_AS_ERRORS=y` for the app, both as the default events-only build
and with `CONFIG_BTRK_RAW_STREAM=y` (CI builds both):

```
app     FLASH 240188 B / 360 KB (65 %)   RAM 97804 B / 256 KB (37 %)
mcuboot FLASH  33506 B /  48 KB (68 %)
outputs: firmware/zephyr/zephyr.signed.{bin,hex}, mcuboot/zephyr/zephyr.uf2 @0x27000
```

CI (`.github/workflows/ci.yml`) builds the same, and runs the host unit tests.

**Nothing has run on hardware yet.** Unverified on a real XIAO: the IMU register sequence,
FIFO burst rollover, wake-on-motion from System OFF, MCUboot chain-loading after the UF2
bootloader, the QSPI NOR log (driver, runtime-PM deep power-down, erase timing), settings/NVS,
bonding and the pairing window (in particular the reset cause the UF2 bootloader leaves for
us), advertising payload on real scanners, the battery ADC reading, and all current figures.
`docs/bringup.md` is the checklist for that. **Not built with nRF Connect SDK** — see below.
The portable modules (`punch_detect`, `evlog`, `btrk_util`, `ringbuf`, `raw_pack`) compile
with host gcc and are unit tested (`tests/host/`, with ASan/UBSan in CI; the detector is also
compared sample-for-sample with `analysis/detector.py` by pytest).

## Build

Upstream Zephyr (what was tested):

```bash
pip install west
west init -m https://github.com/zephyrproject-rtos/zephyr --mr v4.1.0 zephyrproject
cd zephyrproject && west update && west zephyr-export
pip install -r zephyr/scripts/requirements.txt
# Zephyr SDK 0.17.0 with the arm-zephyr-eabi toolchain
west build -p always -b xiao_ble/nrf52840/sense --sysbuild /path/to/boxing-tracker/firmware -d build-xiao
# raw-streaming debug / data-collection build (tools/logger.py raw CSVs):
west build -p always -b xiao_ble/nrf52840/sense --sysbuild /path/to/boxing-tracker/firmware -d build-xiao-raw \
    -- -DCONFIG_BTRK_RAW_STREAM=y
```

nRF Connect SDK (v2.9 / v3.x, untested): same command inside the NCS toolchain
(`nrfutil toolchain-manager launch --shell`). NCS uses the Partition Manager instead of
devicetree partitions when MCUboot is enabled; either add `-DSB_CONFIG_PARTITION_MANAGER=n`
to keep the DTS flash map here, or write a `pm_static.yml` with the same layout
(MCUboot 0x27000/48 KB, slot0 0x33000/368 KB, slot1 0x8F000/368 KB).

## Flash (no debug probe needed)

The XIAO ships with the Adafruit UF2 bootloader; we keep it and put MCUboot at
0x27000 (where the UF2 bootloader starts applications).

1. Double-tap RESET → `XIAO-SENSE` USB drive appears.
2. Copy `build-xiao/mcuboot/zephyr/zephyr.uf2` (MCUboot, 0x27000).
3. Double-tap RESET again and copy a **signed** app UF2:
   ```bash
   python zephyr/scripts/build/uf2conv.py -c -f 0xADA52840 -o app-signed.uf2 \
       build-xiao/firmware/zephyr/zephyr.signed.hex
   ```
   (The app's own `zephyr.uf2` is unsigned and MCUboot will refuse it.)
4. Later updates over the air: `build-xiao/firmware/zephyr/zephyr.signed.bin` with
   nRF Connect Device Manager (mobile) or `mcumgr --conntype ble --connstring peer_name=BoxTrk-L image upload …` (the name has the role suffix once a role is set), then `image test`, reset, `image confirm`.

With an SWD probe (J-Link / CMSIS-DAP) `west flash --runner jlink|pyocd` also works.

Logs go to SEGGER RTT (probe needed); USB CDC is disabled to save power.

## Host tests

```bash
make -C tests/host run      # gcc -Wall -Wextra -Werror + ASan/UBSan; prints HOST TESTS OK
```

Covers the detector (refractory merge, 2 × window cap, flush, saturation, u32 time wrap),
the flash log on a RAM NOR model (append/read from seq, wrap-around, remount, torn write,
erase), the role/window policy, advertising bytes, CRC and battery curve. `tests/host/pd_cli.c`
runs the detector on stdin samples for the Python equivalence test.

## Custom board checklist

Create a Zephyr board (`boards/<vendor>/boxtrk_v1`), copy `boards/boxtrk_custom.overlay`,
provide `chosen boxtrk,imu` + `irq-gpios`, a standard MCUboot flash map (no UF2
bootloader), and update `sysbuild/mcuboot.overlay`. For ±32 g parts see
`docs/hardware-notes.md`.
