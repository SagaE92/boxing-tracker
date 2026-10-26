# Host tools

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

## `logger.py` — record the raw stream over BLE

```bash
python tools/logger.py --out recordings/2026-10-26_bag --hand rear --stance orthodox
```

Connects (scans for `BoxTrk` or the service UUID; move the tracker to wake it), writes the
config, enables raw streaming and starts a session, and writes:

| File | Header |
|---|---|
| `<out>_raw.csv` | `host_time_s,device_time_us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,sat` |
| `<out>_labels.csv` | `host_time_s,label,note` |
| `<out>_punches_device.csv` | on-device events, for comparison |

* `device_time_us` is unwrapped (the firmware clock is 32-bit µs). `host_time_s` is
  derived from the device clock anchored at the first packet (no BLE jitter).
* `sat` = 1 if any accel axis ≥ 15.66 g or gyro axis ≥ 1960 dps (clipped data; peaks are lower bounds).
* Lost packets (sequence gaps) and FIFO/ring overruns are counted and reported at the end.

Labels: while recording, type a label + Enter: `sync`, `cal_start`, `cal_end`,
`round`, `rest`, `jab`, … or `label: note`. Empty line = `mark`, `q` = stop.

### Two sensors (one inside each wrap)

```bash
python tools/logger.py --out recordings/sess --stance orthodox \
    --device lead=C4:12:34:56:78:9A --device rear=D7:65:43:21:0F:1E
```

Connects to both at once, writes the hand role to each device's Config, and records
`sess_lead_raw.csv`, `sess_rear_raw.csv` (one file per device, same columns), a shared
`sess_labels.csv`, and `sess_sync.csv` (`device_id,role,host_time_s,device_time_us,rtt_ms,source`):
time-sync bursts (0x0008, at connect, every `--sync-every` s and at stop) or, for firmware
without 0x0008, packet-arrival samples. Then run `analysis/detector.py --stream … --sync …`
(see `analysis/README.md`). Do the sync clap with both hands, then one straight with each.

## Video sync convention

1. Start the phone video, then start `logger.py`.
2. **Sync clap:** with the tracker on the wrist, clap once sharply (or slap the
   sensor hand on a pad) in view of the camera. It appears as an isolated > 6 g spike
   in the IMU and as an audio transient / contact frame in the video. Type `sync`.
3. **Calibration:** type `cal_start`, hold your guard still for ~2 s, throw **one
   straight punch with the sensor hand** (jab if it's on the lead hand, cross if rear),
   type `cal_end`.
4. Box. Mark rounds if you like.
5. Afterwards, find the clap's time in the video (e.g. 3.47 s) and align:
   ```bash
   python tools/sync_video.py rec_raw.csv --video-clap 3.47
   # optional: convert labels made in a video annotator (video_time_s,label,note)
   python tools/sync_video.py rec_raw.csv --video-clap 3.47 --video-labels vid.csv --out rec_labels.csv
   ```

## `proto.py`

Python mirror of `firmware/src/bt_proto.h` (UUIDs, struct layouts, parsers). Tests in
`tools/tests/` check it against the C header and against packets produced by the
firmware packer compiled on the host.
