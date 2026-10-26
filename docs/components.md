# Component recommendation (size-first, kickboxer)

## Prototype
- **Seeed XIAO nRF52840 Sense** (21 × 17.8 mm)  
  Onboard LSM6DS3TR-C (6-axis). Good for algorithm development. Note: ±16 g limit — real punches can clip.

## Custom board target (~25×20 mm or smaller)
- **MCU/module**: ISP1807 or similar ultra-small nRF52840 module with antenna (8×8 mm class).
- **IMU**: LSM6DSV320X (or LSM6DSV80X) — single chip with high-g accel (±320 g or ±80 g) + gyro. Saves board area vs separate high-g + 6-axis.
- **Power**: nPM1304 or similar low-Iq PMIC + fuel gauge. Charge current suitable for 40–60 mAh cells.
- **Battery**: 40–60 mAh LiPo (thinnest available, e.g. 3×10×25 mm class).
- **Charging**: Prefer pogo pins (thinner, easier seal) over side USB-C.
- **Storage**: Small QSPI NOR for session logging.
- **Other**: One button or none, minimal LED, SWD pads.

## Power budget (datasheet estimate)
On-device detection + event logging + deep sleep: roughly 10–20 mAh per week for ~10 × 1 h sessions + standby.  
Raw streaming every session roughly doubles consumption.

Size and sealability under wraps take priority over absolute runtime.
