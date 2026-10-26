# DIY boxing tracker

Wrist-worn IMU strike tracker (inside the hand wrap) in the spirit of Corner-style
trackers: strike counting, `peak_g` and a hand-speed estimate, work rate, strike-type
classification, BLE to a phone/web app. Prototype hardware: **Seeed XIAO nRF52840 Sense**
(onboard LSM6DS3TR-C); a custom board follows.

| Path | What |
|---|---|
| `firmware/` | Zephyr app (`xiao_ble/nrf52840/sense`), IMU FIFO driver, on-device strike detector + flash event log, hand role, time sync, BLE service, battery, power state machine, MCUboot + SMP OTA DFU — [README](firmware/README.md) |
| `docs/bringup.md` | **bring-up checklist for two XIAOs + two LiPos**: soldering, flashing, roles, placement, first two-sensor recording, detector, StrikeLab, troubleshooting |
| `tools/` | `logger.py` (bleak → raw CSV + labels, roles, log fetch), `evlog.py` (on-device logs → session.json), `sync_video.py`, `proto.py` — [README](tools/README.md) |
| `analysis/` | `detector.py` (strike detector/classifier → punches CSV + `session.json`), `synth.py`, `evaluate.py`, tests, demo session — [README](analysis/README.md) |
| `docs/gatt-spec.md` | BLE GATT spec (byte layouts for raw stream, punch events, control, summary, config; v1.1 role, time sync, event log) |
| `docs/axes.md` | placement, axis convention, calibration |
| `docs/power.md` | power state machine and weekly budget |
| `docs/hardware-notes.md` | ±16 g saturation risk + mitigations, enclosure/charging notes |
| `docs/session.schema.json`, `docs/components.md`, `dashboard/` | owned by other workstreams |

Quick start (no hardware):

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python -m pytest analysis/tests tools/tests
python analysis/detector.py analysis/samples/demo_raw.csv --labels analysis/samples/demo_labels.csv \
    --hand rear --stance orthodox --session-out /tmp/demo_session.json
```
