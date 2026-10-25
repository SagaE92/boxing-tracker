# Boxing tracker – component recommendation

Last updated: 2026-10-25. Figures come from manufacturer datasheets and product pages (links at the end). Anything marked **estimate** is my own calculation from those figures and needs to be checked by measuring a real board (Nordic PPK2).

## Targets

- Wrist-worn on the back of the wrist, under hand wraps. Measures punch count, speed, power (G-force), work rate and punch type (jab/cross/hook/uppercut). Connects to a phone app over BLE.
- Custom PCB **≤ 25 × 20 mm** (500 mm²), with the thinnest stack-up we can get.
- Cell **40–60 mAh** LiPo. Must last **1 week per charge** with up to 10 × 1 h sessions plus standby.
- USB-C side charging, sealed enclosure.
- Prototype on dev modules first, then move to the custom PCB.

## Top picks (custom board)

| Area | Part | Part number | Why |
|---|---|---|---|
| MCU + radio | Insight SiP ISP1807 (nRF52840) | ISP1807-LR-RS | 8.0 × 8.0 × 1.0 mm with integrated antenna and both crystals. Pre-certified (CE/FCC/IC/TELEC/KC). It is the only nRF52840 module that is both small and thin enough for 25 × 20 mm. Antenna keep-out is a 4.0 mm × 18.0 mm min strip at the board edge. |
| IMU (primary) | ST LSM6DSV320X | LSM6DSV320XTR | One LGA-14 2.5 × 3.0 × 0.86 mm package with low-g ±16 g, high-g ±32…±320 g and a ±4000 dps gyro. High-g ODR runs 480 Hz–7.68 kHz. Has MLC/FSM for on-sensor classification, SFLP, 4.5 KB FIFO. Typical current: 0.67 mA (gyro + low-g HP) plus 0.225 mA for the high-g channel. |
| IMU (alt) | ST LSM6DSV80X | LSM6DSV80XTR | Same package and features, but the high-g channel tops out at ±80 g. ST markets it for boxing and sport wearables. |
| PMIC | Nordic nPM1304 | nPM1304 (WLCSP 3.1 × 2.4 mm) | Charge current 4–100 mA in 0.5 mA steps, which is right for 40–60 mAh cells. Also has a fuel gauge (SoC/SoH), 2 × 200 mA bucks, 2 LDO/load switches, USB-C current-limit detection, 22 V OVP, ship mode 370 nA and 3 LED drivers. |
| Charger (alt) | TI BQ25100 | BQ25100 (DSBGA 1.6 × 0.9 mm) | 10–250 mA ISET with 1 mA termination. Use it with a TPS7A02 LDO (25 nA Iq) and a MAX17048 fuel gauge (3 µA hibernate). |
| Cell | 3.0 mm thick 60 mAh pouch | e.g. FLP-301025 (3.0 × 10 × 25 mm) | The thinnest option in range. It fits under a 25 × 20 mm board. |
| USB-C | GCT IP67 6-pin power-only | USB4715-GF-A (mid-mount) | Sealed with a gasket. Charge-only (VBUS, GND, CC1/CC2). Add 2 × 5.1 kΩ CC pull-downs. |
| ESD | TI | TPD1E10B06 (VBUS), TPD2E2U06 (D+/D− if used) | Per TI's USB ESD guide. |

## MCU: nRF52840 options checked against a 25 × 20 mm board

| Option | Body (mm) | Height | Antenna / keep-out | Share of 500 mm² | Verdict |
|---|---|---|---|---|---|
| Insight SiP ISP1807-LR | 8.0 × 8.0 | 1.0 | Integrated. Metal-free zone 4.0 mm × 18.0 mm min at the board edge | ≈ 64 mm² body + ≈ 72 mm² keep-out ≈ 27 % (estimate) | **Best fit.** Thinnest and pre-certified. |
| Raytac MDBT50Q-1MV2 | 10.5 × 15.5 | 2.05 | Chip antenna on the module. No ground under the antenna on any layer. Must sit on the board edge | ≈ 163 mm² ≈ 33 % | Fits, but adds ~1 mm of height. Good second source. |
| u-blox NINA-B306 | 10.0 × 15.0 | 2.2 | Integrated PCB antenna | 150 mm² ≈ 30 % | Fits. Thickest of the fitting options. |
| u-blox NINA-B301 | 10.0 × 11.6 | 2.2 | Antenna pin. Needs an external antenna and matching | 116 mm² + antenna | Not worth it here: you need your own RF design and it is still 2.2 mm tall. |
| Fanstel BT840F | 15 × 20.8 | 1.9 | PCB trace antenna | 312 mm² ≈ 62 % | Too big. |
| Minew MS88SF2 | 23.2 × 17.4 | 2.0 | PCB antenna / IPEX | ≈ 81 % | Does not fit. |
| Bare nRF52840 | aQFN73 7 × 7 / WLCSP 3.544 × 3.607 | — | Needs a chip antenna, matching network, 32 MHz crystal and DC/DC inductor, plus your own RF tuning and CE RED radio testing | Similar to ISP1807 once you add the antenna (estimate) | Only for v3+. WLCSP needs HDI. |

Alternatives to the preferred chip: nRF54L15 uses less power (4.8 mA system TX at 0 dBm, WLCSP 2.4 × 2.2 mm). nRF52833 has a smaller WLCSP (3.175 mm). nRF52832 has no USB. Staying on nRF52840 is fine, because BLE TX is a small part of the power budget.

## IMU and high-g

Punches drive wrist and hand acceleration well past ±16 g. In-glove impact peaks measured 35–172 g, and post-impact deceleration reached 454 g (MDPI Proceedings 2020). A ±16 g IMU such as the LSM6DS3TR-C on the XIAO Sense or the BMI270 will clip on bag contact. They are still fine for swing-phase speed and for classifying punch type.

| Part | Accel FS | Gyro | Max ODR | Current (typ) | FIFO | Package (mm) |
|---|---|---|---|---|---|---|
| LSM6DS3TR-C (XIAO Sense) | ±2…16 g | ±2000 dps | 6.66 kHz | 0.90 mA combo HP | 4 KB | 2.5 × 3 × 0.83 |
| BMI270 | ±2…16 g | ±2000 dps | accel 1.6 kHz / gyro 6.4 kHz | 685 µA (both at max ODR) | 2 KB | 2.5 × 3 × 0.8 |
| LSM6DSO32 | ±4…32 g | ±2000 dps | 6.66 kHz | 0.55 mA combo HP | 3 KB (9 KB compressed) | 2.5 × 3 × 0.83 |
| LSM6DSO32X | ±4…32 g + MLC | ±2000 dps | 6.66 kHz | 0.55 mA | 3 KB | 2.5 × 3 × 0.83 |
| LSM6DSV16X | ±2…16 g + MLC/SFLP | ±4000 dps | 7.68 kHz | 0.65 mA | 4.5 KB | 2.5 × 3 × 0.83 |
| **LSM6DSV80X** | ±16 g + high-g ±80 g | ±4000 dps | high-g 480 Hz–7.68 kHz | 0.67 mA + 0.225 mA high-g | 4.5 KB | 2.5 × 3 × 0.86 |
| **LSM6DSV320X** | ±16 g + high-g ±320 g | ±4000 dps | high-g 480 Hz–7.68 kHz | 0.67 mA (6-axis HP) + 0.225 mA high-g (high-g figure verified on the DSV80X datasheet) | 4.5 KB | 2.5 × 3 × 0.86 |
| ADXL372 (add-on) | ±200 g | — | 3200 Hz | 22 µA @ 3200 Hz | 512 samples | 3 × 3.25 × 1.06 |
| ADXL375 (add-on) | ±200 g | — | 3200 Hz | 145 µA | 32 | 3 × 5 × 1 |
| H3LIS331DL (add-on) | ±100/200/400 g | — | 1 kHz | 370 µA @ 1 kHz | — | 3 × 3 × 1 |

### Does a single LSM6DSV320X save area over LSM6DSO32 + ADXL372? Yes.

- Package area: 7.5 mm² for one LGA-14, against 7.5 + 9.75 = 17.25 mm² for the pair.
- Placed with decoupling caps and routing (estimate): about 12 mm² against about 25–28 mm². That saves roughly 13–16 mm², or about 3 % of a 25 × 20 board.
- It also gets you one bus device instead of two, so the ADXL372 doesn't need its own SPI chip select and INT pins.
- High-g and gyro samples are synchronised in one FIFO. The MLC/FSM can use the high-g data directly, and the part is 0.2 mm lower (0.86 mm vs 1.06 mm).
- The pair uses less power: 0.55 + 0.022 ≈ 0.57 mA, against ≈ 0.90 mA for the DSV320X. Over 10 h/week that is ≈ 3.2 mAh less.
- The ADXL372 is coarse: 100 mg/LSB, with ~300–350 mg RMS noise.
- **Recommendation:** use the LSM6DSV320X (or the DSV80X). Fall back to LSM6DSO32 + ADXL372 only if the DSV parts can't be bought: in Oct 2026 DigiKey showed 24 weeks for the DSV320XTR, while the ST eStore listed stock.

## Charging and protection (40–60 mAh)

- Many small pouch cells specify **0.5C max charge** (DNK501015, YDL 501015). That means 20–30 mA charge for 40–60 mAh.
- nPM1304: set 20–30 mA.
- BQ25100: 10 mA minimum, set by the ISET resistor.
- MCP73831: 15 mA minimum.
- nPM1300: **32 mA minimum**, which is above 0.5C for a 50 mAh cell. Avoid it.
- nPM1100: 20 mA minimum. Borderline.
- XIAO nRF52840 (BQ25101) charges at a fixed 50 mA, or 100 mA if P0.13 is driven low. With a 50 mAh cell that is 1C. For the prototype, use a cell rated for 1C charge or a larger cell.
- Protection: buy cells with a PCM. Alternatively, on bare cells use a TI BQ2970 (WSON 1.5 × 1.5 mm, 4 µA typ) plus a dual N-FET. Its 4 µA counts against the sleep budget.

## Cells, 40–60 mAh (thickness first)

| Model | mAh | T × W × L (mm) | Source |
|---|---|---|---|
| FLP-251015 | 42 | 2.5 × 10 × 15 | FLYPOWER catalogue |
| FLP-301025 | 60 | 3.0 × 10 × 25 | FLYPOWER catalogue |
| FLP-311116 | 55 | 3.1 × 11 × 16 | FLYPOWER catalogue |
| FLP-381018 | 50 | 3.8 × 10 × 18 | FLYPOWER catalogue |
| FLP-401020 / THOR-401020 | 50 / 55 | 4.0 × 10 × 20 | FLYPOWER / THOR |
| Ampul 401012 | 40 | 4.0 × 10 × 12 | ampul.eu (EU) |
| DNK / YDL 501015 | 50 (YDL lists min 40 / typ 60) | 5.0 × 10 × 15 (17 with PCM) | datasheets |
| VARTA CP1240 A4X (coin) | 50 | Ø12.1 × 4.0 | VARTA / Texim Europe |
| VARTA CP1254 A4 (coin) | 74 | Ø12.1 × 5.4 | VARTA / Conrad |
| LIR2032 (coin) | 40 | Ø20 × 3.2 | RS Pro |

## Power budget (estimate, typical datasheet values)

Assumptions:

- 10 sessions × 1 h per week, which leaves 158 h of standby.
- IMU: LSM6DSV320X in HP mode at 0.67 mA, plus 0.225 mA for the high-g channel.
- nRF52840 CPU: 3.3 mA (DC/DC, 64 MHz) at a 10 % duty cycle.
- BLE: a connection with punch notifications, estimated at 0.15 mA average. Raw streaming is estimated at 1.5 mA.
- LED and haptic: 0.05 mA average.
- Sleep: System ON with RTC at 3.16 µA, plus IMU wake-on-motion in LPM1 at 1.875 Hz (4.5 µA), plus PMIC and regulators at 1.0 µA (an assumption). Total 8.66 µA.
- Self-discharge: 3 %/month (an assumption).
- Usable capacity: 85 % of nominal.

| Configuration | Active mA | Week (mAh) | 40 mAh lasts | 50 mAh lasts | 60 mAh lasts |
|---|---|---|---|---|---|
| Recommended (on-device processing) | 1.43 | 16.0 | 14.9 days | 18.6 days | 22.3 days |
| LSM6DSO32 + ADXL372 | 1.10 | 12.7 | 18.7 days | 23.4 days | 28.1 days |
| Raw IMU streaming to phone | 3.10 | 32.7 | 7.3 days | 9.1 days | 10.9 days |
| XIAO Sense prototype (10 µA sleep) | 1.43 | 16.2 | 14.7 days | 18.4 days | 22.0 days |

**Verdict:**

- A 40 mAh cell covers a week of 10 × 1 h sessions with about 2× margin, as long as punches are processed on the device.
- If you plan to stream raw IMU data, pick **50–60 mAh**.
- Aim for **50 mAh** at about 3.0–4.0 mm thick.

## Thickness (estimate)

| Stack | Bottom wall | Cell | PCB | Tallest part | Top wall | Total |
|---|---|---|---|---|---|---|
| ISP1807 board | 0.8 mm | 3.0 mm (FLP-301025) | 0.8 mm | 1.0 mm (ISP1807) | 0.8 mm | ≈ 6.4–7 mm |
| MDBT50Q board | 0.8 mm | 3.0 mm | 0.8 mm | 2.05 mm (MDBT50Q) | 0.8 mm | ≈ 7.5–8 mm |

The ISP1807 total includes about 0.3 mm of foam/gap. A USB-C receptacle is usually the tallest part at the board edge; GCT lists 4.00 mm profile for the USB4715. Pogo-pin or magnetic dock contacts give the thinnest, best-sealed device (Hykso, StrikeTec and PIQ all use docks), but they drop the USB-C side port.

## Prototype BOM vs custom BOM

| Function | Prototype (dev modules) | Custom PCB v1 |
|---|---|---|
| MCU / BLE | Seeed XIAO nRF52840 Sense (21 × 17.8 mm, LSM6DS3TR-C, BQ25101) | ISP1807-LR-RS |
| IMU | Onboard LSM6DS3TR-C, plus STEVAL-MKI251A (LSM6DSV320X) or STEVAL-MKI247A (LSM6DSV80X) adapter on SPI. Adafruit 4692 (LSM6DSO32) is a cheap ±32 g option | LSM6DSV320XTR (alt LSM6DSV80XTR) |
| Power | XIAO onboard BQ25101 + LDO. Optional nPM1304 EK for charger/fuel-gauge work | nPM1304 (alt BQ25100 + TPS7A02 + MAX17048) |
| Cell | 50–100 mAh JST pouch (≥ 0.5C charge at 50 mA) | 50–60 mAh, 3–4 mm pouch with PCM |
| USB | XIAO USB-C | USB4715-GF-A + 2 × 5.1 kΩ CC + TPD1E10B06 |
| Feedback | XIAO RGB LED | nPM1304 LED driver + 0402 LED. Optional DRV2605L (1.5 × 1.5 mm WCSP) + LRA |
| Storage | XIAO onboard 2 MB QSPI flash | MX25R6435F (64 Mb, USON 4 × 3 / WLCSP) |
| Charging contacts | XIAO USB-C | USB4715-GF-A **or** flush pogo pads + Mill-Max 0921-0 spring pins in the dock |
| Wake | IMU INT1 → GPIO (no button) | Same, LSM6DSV320X wake-up/tap → nRF52840 GPIO |
| Debug | XIAO SWD pads | Tag-Connect / SWD test pads |

## System hardware notes (decided direction)

- **No button.** The IMU's wake-up / tap interrupt goes to an nRF52840 GPIO. Use System ON + RTC (3.16 µA) for timekeeping, or System OFF (0.40 µA) for storage.
- Plugging the device into the charger, or a double-tap, wakes it into pairing.
- For shipping, use nPM1304 ship mode (370 nA). Check which sources can wake it from ship mode (VBUS, SHPHLD) in the nPM1304 datasheet.
- **Wake-on-motion.** The LSM6DSV320X/80X low-g channel runs in LPM1 at 1.875 Hz (4.5 µA). Gyro and high-g stay off until motion is detected.
- When motion is detected, the FSM/MLC decides whether it is a session start. That way ordinary arm movement doesn't spin up BLE.
- **Flash logging with sync later.** Log punch events (and optional raw windows) to QSPI NOR, then bulk-sync over BLE when the phone connects. This removes the FightCamp "phone too far" failure mode.
- **Charging.** Use USB-C (USB4715-GF-A, IP67) if the side port is required. The sealed alternative is pogo/magnetic contacts with flat gold pads on the device. Put the spring pins in the dock so the device gains no height.

### Flash (QSPI NOR)

| Part | Density | Package | Key figures | Use |
|---|---|---|---|---|
| Macronix MX25R6435F | 64 Mb (8 MB) | 8-USON 4 × 3 mm or 22-ball WLCSP | 1.65–3.6 V. Deep power-down 7 nA typ (0.35 µA max). ULP mode: 4-I/O read 2.2 mA typ, program 3.5 mA typ. 100k cycles, 4 KB sectors | **Primary.** Works with the nRF52840 QSPI peripheral |
| MX25R family | 512 Kb–64 Mb | USON / WLCSP | Same ball map across densities in WLCSP | Drop to 16–32 Mb if raw capture is cut |
| nRF52840 internal flash | 1 MB shared with firmware | — | No extra part | Events only (≈ 0.5 MB/week fits only if firmware is small) |

Sizing for a week (estimate):

- Punch event record: 16 bytes. That covers a timestamp, hand/type, low-g peak, high-g peak, gyro peak, speed estimate, duration and flags.
- Events: 10 sessions × up to 3,000 punches/h ≈ 30,000 events ≈ **0.5 MB per week**.
- Raw 6-axis at 416 Hz, 12 B/sample, comes to ≈ 5 kB/s, or ≈ 18 MB/h. Continuous raw logging for a whole week does not fit.
- Raw punch windows: 300 ms at 960 Hz with 9 axes (low-g + gyro + high-g) is ≈ 5.2 kB per punch.
- **Verdict: 64 Mb (8 MB)** holds a week of events plus about 1,400 raw punch windows or about 25 min of continuous 6-axis raw. That is enough for labelling and debugging.

### Pogo / magnetic charging (sealed alternative to USB-C)

| Side | Part | Notes |
|---|---|---|
| Device | 2 (or 3) flat hard-gold / ENIG pads flush with the enclosure, or moulded-in target pins | Zero added height. 3rd pad optional for SWD/UART or one-wire DFU |
| Dock, spring pins | Mill-Max 0921-0-57-20-76-14-11-0 | Ultra-low-profile, short stroke (0.5 mm mid / 0.99 mm max). Tape & reel |
| Dock, spring pins | Mill-Max 0906-1-15-20-75-14-11-0 | Standard 0906 pin, 100k–1M cycles |
| Dock, header | Mill-Max 821-22-002-10-001101 | 2-pin 2.54 mm pogo header, 4.50 mm above board, 6.5 A, 20 mΩ max |
| Dock, magnetic | Mill-Max Maxnetic 872-22-002-10-012101 / 873-10-002-10-012000 target | 2-position, 2.54 mm. Mated stack height 10.9 mm, so it suits the dock only |
| Cable, magnetic | CFE CMA-0021 | 2-pin magnetic pogo cable for smart watches: 2 N, 12 V / 1 A, 20k cycles |

The pogo route needs reverse-polarity and ESD protection on the pads. The nPM1304 has 22 V OVP. Add a TVS (TPD1E10B06) and a keyed or magnet-polarised dock. Keep the CC resistors only if USB-C is also fitted.

## Size vs Corner

Corner is reportedly **25 × 35 × 8 mm, 10 g** (trainwithcorner.com). Our target board is **≤ 25 × 20 mm**, and the estimated stack is about 6.4–7 mm with the ISP1807 and a 3 mm cell.

- Footprint: about 43 % smaller (500 mm² vs 875 mm²) for the board. The enclosure adds about 1.5–2 mm per side (estimate).
- Height: about 1–1.5 mm thinner without USB-C. With a USB-C side port, the edge height approaches Corner's 8 mm.

## Competitors

The sourced comparison lives on its own Page: **Kickboxing tracker: competitors vs our DIY prototype** (https://cursor.com/canvas/store-b1e91ea7-bd38-4267-a1d3-059598a48ba5/870451cb-5488-4909-84a2-9fd18723ec92). It is not duplicated here. Reconciled facts:

| Item | Competitor Page | This research | Resolution |
|---|---|---|---|
| Hykso price | $199 (list $299) | $299.99 on Amazon | Both are true. The Hykso shop sells at $199; $299 is list price |
| StrikeTec battery | 10–12 h training, 72 h standby | Same, but the user guide says up to 5 h while streaming | Battery life depends on streaming |
| StrikeTec weight | 10 g | 0.35 oz | Same (0.35 oz ≈ 9.9 g) |
| ROOQ size | not published | 42 × 32 × 9 mm, 12 g (ROOQ FAQ) | Add to comparison |
| Move It Swift | sensor built into gloves | Removable module 43 × 34 × 12 mm. Sources disagree on the cell: 300 mAh (FCC manual) vs 30 mAh (reseller) | The FCC manual is primary, but unconfirmed |
| Battery target | 10 × 1.5 h assumed | 10 × 1 h (current requirement) | Use 10 × 1 h |
| Corner sensor | reseller says 3-axis accel (unverified) | Same | Unverified |

## Open questions

1. USB-C side port or sealed pogo dock? This is the biggest single factor in thickness. The current plan is pogo as the sealed option.
2. Do we need raw streaming, or is on-device classification enough? This decides 40 vs 60 mAh.
3. Should high-g go to ±320 g (DSV320X) or ±80 g (DSV80X)? Measure wrist peaks with the STEVAL adapter first.
4. Check stock of LSM6DSV320XTR, LSM6DSV80XTR and ISP1807-LR-RS at Mouser / DigiKey / Farnell EU.
5. Settle on a cell vendor that ships to the EU with UN38.3 paperwork.

## Sources

- nRF52840 PS (sleep, radio, CPU): https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/keyfeatures_html5.html
- ISP1807: https://www.insightsip.com/fichiers_insightsip/pdf/ble/ISP1807/isp_ble_DS1807.pdf
- MDBT50Q: https://www.raytac.com/product/ins.php?index_id=24
- NINA-B30: https://www.u-blox.com/en/product/nina-b30-series-open-cpu-0
- Fanstel BT840: https://www.fanstel.com/bt840
- Minew MS88SF2: https://en.minewsemi.com/file/MS88SF2-nRF52840_Datasheet_K_EN.pdf
- XIAO nRF52840: https://wiki.seeedstudio.com/XIAO_BLE/
- LSM6DSV320X: https://www.st.com/en/mems-and-sensors/lsm6dsv320x.html
- LSM6DSV80X: https://www.st.com/en/mems-and-sensors/lsm6dsv80x.html
- LSM6DSO32X: https://www.st.com/en/mems-and-sensors/lsm6dso32x.html
- LSM6DS3TR-C: https://www.st.com/resource/en/datasheet/lsm6ds3tr-c.pdf
- BMI270: https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmi270-ds000.pdf
- ADXL372: https://www.analog.com/en/products/adxl372.html
- nPM1304: https://www.nordicsemi.com/Products/nPM1304
- nPM1300: https://www.nordicsemi.com/Products/nPM1300
- BQ25100: https://www.ti.com/product/BQ25100
- MAX17048: https://www.analog.com/en/products/max17048.html
- GCT USB4715: https://gct.co/connector/usb4715
- FLYPOWER cells: https://www.fly-power.com/en/li-polymer-batteries-2/li-po-standard-industrial-series
- Punch tracker validity: https://pmc.ncbi.nlm.nih.gov/articles/PMC10599804/
- MX25R6435F: https://www.macronix.com/Lists/Datasheet/Attachments/8868/MX25R6435F,%20Wide%20Range,%2064Mb,%20v1.6.pdf
- Mill-Max spring pins: https://www.mill-max.com/sites/default/files/external/catalog/2021-02/023M-028M.pdf
- Mill-Max 821-22-002-10-001101: https://www.mill-max.com/products/datasheet/821-22-002-10-001101
- Mill-Max Maxnetic: https://www.mill-max.com/products/new/introducing-100-pitch-maxnetic-connectors
- CFE CMA-0021: https://cfeconn.com/connector/2-pin-magnetic-pogo-pin-connector-with-usb-cable/
- Competitor Page: https://cursor.com/canvas/store-b1e91ea7-bd38-4267-a1d3-059598a48ba5/870451cb-5488-4909-84a2-9fd18723ec92
