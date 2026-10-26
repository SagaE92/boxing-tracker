# Boxing Tracker (Kickboxer Edition)

DIY miniature wrist-worn IMU tracker for kickboxing. Focus: small size (inside wraps), ~1 week battery across sessions, open algorithm, high-rate data, honest metrics.

## Current status
- Prototype path: Seeed XIAO nRF52840 Sense
- Custom board direction: ultra-small nRF52840 module + high-g IMU (LSM6DSV320X class)
- Battery target: 40–60 mAh, size first
- Placement: inside hand wraps

## Dashboard
Public demo: https://sagae92.github.io/boxing-tracker/ (enable GitHub Pages from main / root)

## Why this approach
See `docs/why.md` for comparison vs Corner, Hykso, StrikeTec, etc.

Open source, transparent detection, raw data access, size/power priority, confidence scores, saturation honesty.
