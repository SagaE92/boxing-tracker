# Bring-up: two XIAO nRF52840 Sense trackers

Step-by-step checklist to go from two bare boards and two LiPo cells to a two-sensor
session in StrikeLab. Tick the boxes as you go.

> **Status: written before any hardware test.** The firmware builds (Zephyr v4.1.0,
> sysbuild + MCUboot, CI) and its portable parts are unit-tested on a PC, but nothing in this
> repository has run on a real XIAO yet. Every step below that says *expect* is what the
> code is designed to do, not something that was observed. If a step does not behave as
> described, see [Troubleshooting](#10-troubleshooting) and please note what you saw.

Related: `firmware/README.md` (build details, security), `docs/gatt-spec.md` (protocol),
`docs/power.md` (power states), `docs/axes.md` (placement and axes).

## 1. Parts list

| Qty | Part | Notes |
|---|---|---|
| 2 | Seeed Studio **XIAO nRF52840 Sense** | the *Sense* variant (onboard LSM6DS3TR-C IMU and the 2 MB QSPI flash). The plain XIAO nRF52840 has no IMU |
| 2 | 1-cell **LiPo with protection circuit (PCM)**, 3.7 V nominal / 4.2 V full, ≥ 50 mAh, rated for **≥ 1C charge** | e.g. 50–150 mAh pouch cells. Bare cells without a protection board are not OK (see §2) |
| 1 | USB-C data cable | flashing and charging |
| – | Soldering iron (fine tip), flux, thin solder, tweezers | |
| – | **Multimeter** | polarity check before soldering, battery voltage check |
| – | Kapton tape or heat-shrink, thin foam | insulation, comfort in the wrap |
| 2 | Hand wraps (+ gloves) | |
| 1 | PC with Bluetooth LE (Linux/BlueZ, macOS, or Windows 10+) | for `tools/logger.py` (bleak). Some built-in adapters struggle with two connections plus raw streaming; a recent USB BLE 5 dongle helps |
| optional | SWD probe (J-Link / CMSIS-DAP) + Tag-Connect or pogo clip | only to read RTT logs; not needed to flash |
| optional | Current meter (Nordic PPK2 or similar) | to check the power figures in `docs/power.md` |

## 2. Solder the LiPo to the BAT pads

The XIAO has two battery pads on the **underside**, marked **BAT+** / **BAT−** (check the
silkscreen on your board and the Seeed wiki pin-out for your revision).

- [ ] **Check the cell's polarity with the multimeter** before you solder. JST-style
      connector colours and pin orders are *not* standardised; red is not guaranteed to be +.
      Cut the connector off and work from the measured polarity.
- [ ] **Reversed polarity will destroy the board** (assume there is no reverse-polarity
      protection on the pads) and can damage the cell. Double-check, then check again.
- [ ] Never let the two cell wires touch. Insulate one wire end (Kapton) while you solder
      the other; work with the USB cable **unplugged**.
- [ ] Tin the pads, then solder **+ to BAT+** and **− to BAT−** with short, quick joints
      (heat is bad for the cell). Strain-relieve the wires with a dab of hot glue or tape.
- [ ] Measure: the cell should read 3.0–4.2 V. Below ~3.0 V the protection circuit may have
      cut it off; charging over USB should recover it.
- [ ] Insulate the underside (Kapton) so nothing shorts against the cell.

**Charge current.** The XIAO's charger (BQ25101) charges at a fixed **50 mA**, or 100 mA if
P0.13 is driven low. The firmware never touches P0.13, so it stays at 50 mA (per the Seeed
documentation — verify on your board). 50 mA is **1C for a 50 mAh cell** and more than 1C
for anything smaller; use a cell rated for that charge rate, or a bigger cell for the
prototype. Charge only through the XIAO's USB-C, on a non-flammable surface, and do not leave
a new cell charging unattended the first time. A charge LED near the USB connector lights
while charging.

**Battery sense.** The firmware drives **P0.14 low** permanently to enable the VBAT divider
(1 MΩ / 510 kΩ to P0.31/AIN7). Do not change that pin in your own code: driving P0.14
**high** with a cell connected puts the battery voltage on P0.31, above the nRF52840's pin
limit (Seeed's warning). The divider costs ~2.8 µA.

## 3. Toolchain

Host tools (logger, detector, tests):

```bash
git clone https://github.com/SagaE92/boxing-tracker && cd boxing-tracker
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q analysis/tests tools/tests     # all green, no hardware needed
make -C firmware/tests/host run                    # HOST TESTS OK
```

Firmware (upstream Zephyr, as built in CI):

```bash
pip install west
west init -m https://github.com/zephyrproject-rtos/zephyr --mr v4.1.0 ~/zephyrproject
cd ~/zephyrproject
# optional: only the modules this app needs (faster)
west config manifest.project-filter -- '-.*,+cmsis,+cmsis_6,+hal_nordic,+mcuboot,+zcbor,+tinycrypt,+mbedtls,+segger'
west update && west zephyr-export
pip install -r zephyr/scripts/requirements.txt
# Zephyr SDK 0.17.0 with at least the arm-zephyr-eabi toolchain:
# https://docs.zephyrproject.org/4.1.0/develop/toolchains/zephyr_sdk.html
```

## 4. Build and flash (UF2 + MCUboot), both boards

```bash
cd ~/zephyrproject
west build -p always -b xiao_ble/nrf52840/sense --sysbuild \
    -d build-xiao /path/to/boxing-tracker/firmware
python zephyr/scripts/build/uf2conv.py -c -f 0xADA52840 -o app-signed.uf2 \
    build-xiao/firmware/zephyr/zephyr.signed.hex
```

The XIAO keeps its Adafruit UF2 bootloader; MCUboot is chain-loaded at 0x27000 and boots
the **signed** app.

For **each** board:

- [ ] Plug in USB, **double-tap RESET** → a `XIAO-SENSE` drive appears.
- [ ] Copy `build-xiao/mcuboot/zephyr/zephyr.uf2` (MCUboot) onto it. The drive disappears.
- [ ] Double-tap RESET again and copy `app-signed.uf2`. (The unsigned
      `build-xiao/firmware/zephyr/zephyr.uf2` will be refused by MCUboot.)
- [ ] *Expect:* the board advertises as **`BoxTrk`** within a second (no role yet):
      `python tools/logger.py --scan` lists it with `role unset` and `[window_open]`.

Security reminder: the images are signed with MCUboot's public **development key**
(issue #2) and SMP DFU over BLE is **unauthenticated** (issue #3). Fine on your desk; do not
hand these devices to anyone else (`firmware/README.md` "Security").

Later updates can go over the air (nRF Connect Device Manager or `mcumgr`, signed `.bin`).
Reflashing does **not** erase the settings partition: roles and bonds survive an update.

## 5. Assign the roles (lead / rear)

The role is stored on each device and advertised (`BoxTrk-L` = lead, `BoxTrk-R` = rear).
It can be changed only in the **pairing window** (120 s after a RESET tap or after
connecting the battery — *not* after waking from sleep by motion), over a bonded link, or
while it is still unset.

- [ ] Keep only **tracker A** powered (or move B away), tap its **RESET once**.
- [ ] `python tools/logger.py --assign-role lead --stance orthodox`
      (or `--address <addr>` from `--scan`; `--wrist L|R` to override; stance decides the
      default wrist: orthodox lead = left).
- [ ] Tap RESET once on **tracker B**: `python tools/logger.py --assign-role rear --stance orthodox`.
- [ ] `python tools/logger.py --scan` → *expect* `BoxTrk-L … role lead wrist L` and
      `BoxTrk-R … role rear wrist R`. Write the role on each board (marker/tape).
- [ ] Power-cycle one board (unplug USB, wait for it to sleep, or tap RESET) and scan again:
      the role must persist.

To undo: tap RESET, then `python tools/logger.py --forget --address <addr>` (clears the role
and all bonds).

## 6. Placement in the wraps and axes

- [ ] Put each tracker on the **back of the wrist** (dorsal side), flat, centred, just behind
      the wrist joint, under the first turns of the wrap so it cannot rotate
      (`docs/axes.md`). The **lead** tracker goes on the lead hand (orthodox: left).
- [ ] Mount both the **same way** (e.g. component side out, USB port towards the elbow) so the
      two data sets look alike; the calibration makes the exact orientation irrelevant to the
      detector, but consistency makes debugging easier.
- [ ] Cover the board with tape or heat-shrink against sweat; add thin foam for comfort.
      Keep the cell from being punched directly (put it on the forearm side of the board).
- [ ] Axes the detector uses come from calibration (guard pose → up, first straight → forward):
      hold the guard 2 s at the start, then throw **one jab with the lead hand and one cross
      with the rear hand**.

## 7. First two-device recording

```bash
python tools/logger.py --out recordings/s1 --stance orthodox --device lead=auto --device rear=auto
```

- [ ] Move both hands (wake from sleep), start the command. *Expect* both to connect, print an
      MTU (≥ 185, ideally 247) and a time-sync min RTT (≈ 7.5–15 ms) per hand.
- [ ] Type `sync` and do one sharp **clap with both hands**; then `cal_start`, guard 2 s, one jab,
      one cross, `cal_end`.
- [ ] Type `round` at the start of each round and `rest` at the end (also sent to both trackers
      as round marks). Box 1–3 short rounds.
- [ ] `q` to stop. *Expect* `recordings/s1_lead_raw.csv`, `s1_rear_raw.csv`, `s1_sync.csv`,
      `s1_labels.csv`; few or no lost packets.
- [ ] Each tracker also ran its own detector and logged every strike to flash. Fetch both logs
      (within ~5 min of the session stop, before the trackers go to sleep, for the best clock
      alignment):

      ```bash
      python tools/logger.py --out recordings/s1 --fetch-log --device lead=auto --device rear=auto
      ```

      *Expect* `s1_lead_log.bin` and `s1_rear_log.bin`.

## 8. Run the detector

From the raw streams (full classifier, the reference):

```bash
python analysis/detector.py --stream lead=recordings/s1_lead_raw.csv --stream rear=recordings/s1_rear_raw.csv \
    --sync recordings/s1_sync.csv --labels recordings/s1_labels.csv --stance orthodox \
    --session-out recordings/s1_session.json
```

*Expect* "2 sensors aligned: lead offset … skew … ppm (rtt, residual … ms)". Skews should be
within ±40 ppm; residuals of a few ms or less.

From the on-device logs (no raw stream needed; types are only the calibration jab/cross and
`unknown`, because classification is not ported to the firmware):

```bash
python tools/evlog.py session --log lead=recordings/s1_lead_log.bin --log rear=recordings/s1_rear_log.bin \
    --stance orthodox --session-out recordings/s1_device_session.json
```

- [ ] Compare the strike counts of the two session files; the on-device detector uses the same
      threshold/refractory/peak logic, so per-hand counts should match closely
      (`analysis/tests/test_firmware_detector.py` checks this on synthetic data).

## 9. Open the session in StrikeLab

- [ ] Open https://sagae92.github.io/boxing-tracker/ (or run it locally:
      `cd dashboard && npm ci && npm run dev`).
- [ ] **Open session** → pick `s1_session.json` (add the raw CSVs and labels at the same time
      for Lab-view waveforms). *Expect* both hands in the Athlete view (hand balance, lead/rear
      split per round). Files never leave the browser.

## 10. Troubleshooting

| Symptom | Things to check |
|---|---|
| No `XIAO-SENSE` drive | Double-tap faster; try another (data, not charge-only) cable/port. |
| Copied the app, nothing advertises | Was MCUboot copied first? Is the app the **signed** UF2 (`app-signed.uf2` from `zephyr.signed.hex`)? An unsigned or mis-signed app makes MCUboot refuse to boot. Re-copy both. With an SWD probe, read RTT logs (`west attach` / J-Link RTT Viewer). |
| Advertises, but `--scan` shows nothing | Scan longer (`--scan-timeout 30`); on Linux restart `bluetoothd` if stale; macOS shows UUID-style addresses (use those). The device sleeps after ~5 min without a connection: move it to wake it. |
| `IMU init failed` (RTT) / no strikes | Is it a *Sense* board? The IMU regulator is P1.08; check power. |
| Never sleeps / wakes in the bag | Wake threshold `CONFIG_BTRK_WOM_THRESHOLD_MG` (125 mg); raise it. Sleep only happens with no connection for `CONFIG_BTRK_ADV_TIMEOUT_S` (300 s). |
| Does not wake from System OFF | Needs a clear movement above the threshold on INT1 (P0.11). A RESET tap always wakes it. Unverified on hardware — report it. |
| `role write refused` | Window closed: tap RESET once and retry within 2 minutes (a double-tap enters the bootloader instead). From a central that bonded inside a window it always works. |
| Window seems to open after a motion wake (or never) | The rule relies on the reset cause the UF2 bootloader leaves for the app (`RESET_LOW_POWER_WAKE` for a wake). If the bootloader clears it, a wake looks like a power-on. The BOOT record in the event log (`tools/evlog.py dump`) shows the reset cause bits — please report what you see. |
| Two `BoxTrk-L`, no `-R` | Both got the lead role. Tap RESET on one, `--assign-role rear --address …`. |
| `this sensor is assigned 'lead', not 'rear'` | `--device` addresses swapped: use `ROLE=auto` or swap them. |
| Pairing fails / OS keeps an old bond | After `--forget` (or a chip erase) remove the device from the OS Bluetooth settings too. New bonds are refused outside the window once the device has a bond. |
| Lost packets / high RTT with two sensors | Raw streaming at 416 Hz on two links is demanding: use a BLE 5 USB dongle, keep both close, avoid Wi-Fi on 2.4 GHz nearby. The on-device log is not affected — fetch it afterwards. |
| `no time anchor in boot …` from `evlog.py` | That session's boot never had a time-sync burst (started without the logger?). Start sessions with `tools/logger.py`; fetch before the device sleeps. |
| Device-log events off by up to ~0.1 s per hour | The device slept between the session and the fetch, so only the start anchors were usable: drift is uncorrected (`docs/gatt-spec.md` "Caveat for flash-log sessions"). |
| Battery % looks wrong | Compare the cell voltage with a multimeter; the % curve is generic (±10 %) and reads high while charging. If it always says 100 %, the ADC setup failed (RTT log `no battery ADC`). |
| Log full | The ring keeps the newest ~65,000 records and overwrites the oldest. `ERASE` (0x000A op 3) wipes it. |
| Currents far above `docs/power.md` | Expected on the XIAO in part (its LDO, charger, divider). Measure with a PPK2 in each state (advertising, connected, session, System OFF) and report. |
