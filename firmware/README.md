# Firmware (Zephyr RTOS)

Target: **Seeed XIAO nRF52840 Sense**, board `xiao_ble/nrf52840/sense`.
Everything board-specific is in devicetree overlays:

| File | Purpose |
|---|---|
| `boards/xiao_ble_nrf52840_sense.overlay` | IMU node (`boxtrk,lsm6ds3trc-fifo`, I2C0 0x6A, INT1 P0.11), `chosen boxtrk,imu`, LED alias, disables unused peripherals, flash map |
| `boards/nrf52840_uf2_mcuboot_partitions.dtsi` | flash map that keeps the UF2 bootloader and chain-loads MCUboot |
| `boards/boxtrk_custom.overlay` | **placeholder** for the future custom board (not built) |
| `dts/bindings/boxtrk,lsm6ds3trc-fifo.yaml` | binding for our FIFO IMU driver |
| `sysbuild.conf`, `sysbuild/mcuboot.{conf,overlay}` | MCUboot built alongside the app |

## Modules (`src/`)

| File | What |
|---|---|
| `imu_lsm6ds3trc.c` | LSM6DS3TR-C raw-register driver: ±16 g / ±2000 dps, 416 Hz, continuous FIFO, watermark (12 samples) on INT1 as a level/SENSE interrupt, burst FIFO reads, pattern re-alignment, timestamp model (slow PLL against the RTC), wake-on-motion arm for System OFF |
| `ringbuf.c` | lock-free SPSC sample ring (IMU thread → raw-stream TX thread), portable C |
| `raw_pack.c` | packs up to 18 samples per notification (MTU-sized) + per-sample saturation masks, portable C |
| `punch_detect.c` | streaming detector stub: \|a\|−1 g threshold, refractory, peak, gyro integrals, crude speed; portable C (type = unknown for now) |
| `session.c` | session start/stop, guard-pose + straight-punch calibration, summary counters |
| `ble_svc.c` | custom GATT service (`docs/gatt-spec.md`), advertising, connection parameters, raw TX thread |
| `power.c` | power state machine (`docs/power.md`): adv fast → slow → System OFF; session/idle timeouts |
| `battery.c` | Battery Service level — **stub** (fixed 100 %) |
| `bt_proto.h` | wire format, shared with `tools/proto.py` |

MCUmgr SMP over BLE (image + OS groups) is enabled in `prj.conf`; MCUboot does
test-then-confirm swaps (swap-using-move), signed with MCUboot's **development key**
(`root-ec-p256.pem`) — replace it before giving a device to anyone.

## Two sensors (one per wrap) — planned firmware changes

The host tools already handle two trackers (`tools/logger.py --device lead=… --device rear=…`,
`analysis/detector.py --stream … --sync …`); see `docs/gatt-spec.md` "Two sensors". Firmware
still to do (not in this build, deliberately kept out of this change so the Zephyr build stays
as verified):

* Persist the Config `hand` byte as the device's **role** with Zephyr settings
  (`CONFIG_SETTINGS=y`, `CONFIG_SETTINGS_NVS=y`, `CONFIG_NVS=y`, key `btrk/role`), written when
  the central sets it at pairing.
* Advertise the role in service data on the 0x0001 UUID (`u8 role`, `u16 device id suffix`).
* Add the **0x0008 Time sync** read characteristic returning the raw stream's 32-bit µs
  counter (`k_ticks_to_us_floor64(k_uptime_ticks())`, truncated), so the central can estimate
  offset and drift. Target: ≤ 2 ms between the two sensors after alignment.
* `CONFIG_BT_MAX_CONN` stays 1 per device (each tracker has one central); the phone holds two
  connections. Per-device size and battery targets are unchanged (`docs/power.md`).

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

Tracked as issue drafts (not yet filed).

## Build status (honest)

Built successfully on 2026-10-25 in a Linux box with **upstream Zephyr v4.1.0**
(Zephyr SDK 0.17.0, `arm-zephyr-eabi`), **with sysbuild + MCUboot**:

```
app     FLASH 177868 B / 360 KB (48 %)   RAM 79892 B / 256 KB (30 %)
mcuboot FLASH  33506 B /  48 KB (68 %)
outputs: firmware/zephyr/zephyr.signed.{bin,hex} (imgtool verify: OK), mcuboot/zephyr/zephyr.uf2 @0x27000
```

No compiler warnings from our sources. **Not done:** nothing has run on hardware yet
(IMU register sequence, FIFO burst rollover, wake-on-motion, MCUboot chain-loading
after the UF2 bootloader are all unverified). **Not built with nRF Connect SDK** — see below.
The portable modules (`ringbuf`, `raw_pack`, `punch_detect`) also compile with host gcc
and are unit tested (`tests/host/`, run by pytest).

## Build

Upstream Zephyr (what was tested):

```bash
pip install west
west init -m https://github.com/zephyrproject-rtos/zephyr --mr v4.1.0 zephyrproject
cd zephyrproject && west update && west zephyr-export
pip install -r zephyr/scripts/requirements.txt
# Zephyr SDK 0.17.0 with the arm-zephyr-eabi toolchain
west build -p always -b xiao_ble/nrf52840/sense --sysbuild /path/to/boxing-tracker/firmware -d build-xiao
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
   nRF Connect Device Manager (mobile) or `mcumgr --conntype ble --connstring peer_name=BoxTrk image upload …`, then `image test`, reset, `image confirm`.

With an SWD probe (J-Link / CMSIS-DAP) `west flash --runner jlink|pyocd` also works.

Logs go to SEGGER RTT (probe needed); USB CDC is disabled to save power.

## Host tests

```bash
gcc -std=c99 -Wall -Wextra -Werror -Isrc -o /tmp/t tests/host/test_host.c \
    src/raw_pack.c src/ringbuf.c src/punch_detect.c -lm && /tmp/t
```

## Custom board checklist

Create a Zephyr board (`boards/<vendor>/boxtrk_v1`), copy `boards/boxtrk_custom.overlay`,
provide `chosen boxtrk,imu` + `irq-gpios`, a standard MCUboot flash map (no UF2
bootloader), and update `sysbuild/mcuboot.overlay`. For ±32 g parts see
`docs/hardware-notes.md`.
