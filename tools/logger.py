#!/usr/bin/env python3
"""Record the Boxing Tracker raw IMU stream over BLE to CSV (+ a labels CSV).

  python tools/logger.py --out recordings/2026-10-25_bag      # scan for "BoxTrk"
  python tools/logger.py --address C4:12:34:56:78:9A --out rec1 --hand lead --stance orthodox
  # two sensors, one inside each wrap, recorded at the same time:
  python tools/logger.py --out rec2 --stance orthodox \
      --device lead=C4:12:34:56:78:9A --device rear=D7:65:43:21:0F:1E

Writes (single sensor):
  <out>_raw.csv     host_time_s,device_time_us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,sat
  <out>_labels.csv  host_time_s,label,note
  <out>_punches.csv on-device punch events (if any) for comparison
Two sensors (--device ROLE=ADDRESS, twice): one raw file per device
  <out>_lead_raw.csv, <out>_rear_raw.csv   (same columns; host_time_s per device)
  <out>_sync.csv    device_id,role,host_time_s,device_time_us,rtt_ms,source
                    source "rtt": time-sync reads (0x0008) at connect and every
                    --sync-every s, host_time_s = request/response midpoint;
                    source "packet": raw notification arrival (device time of the
                    packet's last sample, host rx time) - fallback for firmware
                    without 0x0008.
  then: python analysis/detector.py --stream lead=<out>_lead_raw.csv --stream rear=<out>_rear_raw.csv \
            --sync <out>_sync.csv --labels <out>_labels.csv --stance orthodox --session-out <out>_session.json

While recording, type a label and press Enter to write a marker (host clock):
  sync          -> you just did the sync clap/tap (see tools/README.md)
  cal_start / cal_end  -> guard-pose + calibration-jab segment
  round / rest  -> round boundaries;   anything else -> free-text label
  "label: note" -> label with a note;   empty line -> "mark";   q -> stop
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import proto  # noqa: E402

RAW_HEADER = ["host_time_s", "device_time_us", "ax_g", "ay_g", "az_g",
              "gx_dps", "gy_dps", "gz_dps", "sat"]
LABEL_HEADER = ["host_time_s", "label", "note"]
SYNC_HEADER = ["device_id", "role", "host_time_s", "device_time_us", "rtt_ms", "source"]


class SyncWriter:
    """Clock-sync samples for multi-device recordings (thread-safe; one file for all devices)."""

    def __init__(self, fh):
        self.fh = fh
        self.w = csv.writer(fh)
        self.w.writerow(SYNC_HEADER)
        self.lock = threading.Lock()
        self.rows = 0

    def add(self, device_id, role, host_s, device_us, rtt_ms=None, source="rtt"):
        with self.lock:
            self.w.writerow([device_id, role, f"{host_s:.6f}", int(device_us),
                             "" if rtt_ms is None else f"{rtt_ms:.3f}", source])
            self.rows += 1


class RawCsvWriter:
    """Turns raw-stream notifications into CSV rows. BLE-independent (unit tested)."""

    def __init__(self, fh, on_sync=None, unwrap=None):
        self.w = csv.writer(fh)
        self.w.writerow(RAW_HEADER)
        self.unwrap = unwrap or proto.TimeUnwrapper()
        self.on_sync = on_sync  # (device_us_of_last_sample, host_rx_s) per packet
        self.last_seq = None
        self.lost_packets = 0
        self.rows = 0
        self.sat_rows = 0
        self.flag_counts = {"fifo_overrun": 0, "ring_overrun": 0, "ts_resync": 0}
        self._anchor = None  # (device_us, host_s) for host-time interpolation

    def on_packet(self, data: bytes, host_rx_s: float) -> int:
        pkt = proto.parse_raw(data)
        if self.last_seq is not None:
            gap = (pkt.seq - self.last_seq - 1) & 0xFFFF
            self.lost_packets += gap
        self.last_seq = pkt.seq
        if pkt.flags & proto.RAW_F_FIFO_OVERRUN:
            self.flag_counts["fifo_overrun"] += 1
        if pkt.flags & proto.RAW_F_RING_OVERRUN:
            self.flag_counts["ring_overrun"] += 1
        if pkt.flags & proto.RAW_F_TS_RESYNC:
            self.flag_counts["ts_resync"] += 1
        dev = [self.unwrap(s.t_us) for s in pkt.samples]
        # host time per sample: map device time to host time with a fixed anchor
        # (first packet) - stable, no BLE jitter; drift is ~ppm over a session.
        if self._anchor is None:
            self._anchor = (dev[-1], host_rx_s)
        if self.on_sync is not None:
            self.on_sync(dev[-1], host_rx_s)
        a_dev, a_host = self._anchor
        for s, d in zip(pkt.samples, dev):
            ax, ay, az = s.accel_g
            gx, gy, gz = s.gyro_dps
            sat = 1 if (s.accel_sat or s.gyro_sat) else 0
            self.sat_rows += sat
            self.w.writerow([f"{a_host + (d - a_dev) / 1e6:.6f}", d,
                             f"{ax:.4f}", f"{ay:.4f}", f"{az:.4f}",
                             f"{gx:.2f}", f"{gy:.2f}", f"{gz:.2f}", sat])
        self.rows += len(pkt.samples)
        return len(pkt.samples)


class LabelWriter:
    def __init__(self, fh):
        self.fh = fh
        self.w = csv.writer(fh)
        self.w.writerow(LABEL_HEADER)
        self.lock = threading.Lock()

    def mark(self, line: str, t: float | None = None):
        t = time.time() if t is None else t
        line = line.strip()
        label, note = (line.split(":", 1) + [""])[:2] if ":" in line else (line or "mark", "")
        with self.lock:
            self.w.writerow([f"{t:.6f}", label.strip(), note.strip()])
            self.fh.flush()
        return label.strip()


def stdin_labels(labels: LabelWriter, stop: threading.Event):
    print("Type a label + Enter (sync, cal_start, cal_end, round, rest, ...). q = quit.")
    for line in sys.stdin:
        if line.strip().lower() in ("q", "quit", "exit"):
            stop.set()
            return
        print(f"  [{labels.mark(line)}] marked")
    stop.set()


async def find_device(name: str, address: str | None, timeout: float):
    from bleak import BleakScanner
    if address:
        return address
    print(f"Scanning for '{name}' ({timeout:.0f}s)... move the tracker to wake it")
    dev = await BleakScanner.find_device_by_filter(
        lambda d, ad: (d.name or ad.local_name or "") == name
        or proto.SERVICE_UUID in (ad.service_uuids or []), timeout=timeout)
    if dev is None:
        raise SystemExit("device not found")
    return dev


class DeviceRecorder:
    """One sensor of a multi-device recording: raw CSV + its clock-sync samples.
    BLE-independent apart from `sync_burst`, which takes any object with an async
    read_gatt_char(uuid) (unit tested with a fake client)."""

    def __init__(self, role, device_id, raw_fh, sync: SyncWriter, now=time.time, packet_sync_every=50):
        self.role, self.device_id, self.sync, self.now = role, device_id, sync, now
        self.unwrap = proto.TimeUnwrapper()   # shared by raw packets and time-sync reads
        self._n = 0
        self.packet_sync_every = packet_sync_every

        def on_packet_sync(dev_us, host_s):
            self._n += 1
            if (self._n - 1) % self.packet_sync_every == 0:   # default ~every 2 s at 416 Hz / 18 per packet
                self.sync.add(self.device_id, self.role, host_s, dev_us, None, "packet")
        self.raw = RawCsvWriter(raw_fh, on_sync=on_packet_sync, unwrap=self.unwrap)

    def on_raw(self, data: bytes, host_rx_s: float):
        return self.raw.on_packet(data, host_rx_s)

    async def sync_burst(self, client, n=8):
        """n time-sync reads; logs (midpoint, device time, rtt). Returns the min RTT (ms)."""
        best = None
        for _ in range(n):
            t0 = self.now()
            data = await client.read_gatt_char(proto.TIME_SYNC_UUID)
            t1 = self.now()
            dev = self.unwrap(proto.parse_time_sync(bytes(data)))
            rtt = (t1 - t0) * 1e3
            self.sync.add(self.device_id, self.role, (t0 + t1) / 2, dev, rtt, "rtt")
            best = rtt if best is None else min(best, rtt)
        return best


def parse_device_args(specs):
    """["lead=AA:BB..", "rear=CC:.."] -> [(role, address)]; roles must be lead/rear, unique."""
    out = []
    for sp in specs:
        role, sep, addr = sp.partition("=")
        if not sep or role not in ("lead", "rear") or not addr:
            raise SystemExit(f"--device expects lead=ADDRESS or rear=ADDRESS, got {sp!r}")
        out.append((role, addr))
    if len({r for r, _ in out}) != len(out):
        raise SystemExit("--device: each role (lead, rear) at most once")
    return out


async def record_one(args, role, address, rec: DeviceRecorder, stop: threading.Event):
    """Connect one sensor, set its role/stance, stream raw data and time-sync it."""
    from bleak import BleakClient
    async with BleakClient(address) as client:
        print(f"[{role}] connected {address}, MTU {client.mtu_size}")
        has_sync = client.services.get_characteristic(proto.TIME_SYNC_UUID) is not None
        await client.write_gatt_char(proto.CONFIG_UUID, proto.pack_config(role, args.stance, args.threshold),
                                     response=True)
        await client.start_notify(proto.RAW_STREAM_UUID, lambda _, d: rec.on_raw(bytes(d), time.time()))
        if has_sync:
            print(f"[{role}] time sync: min RTT {await rec.sync_burst(client):.1f} ms")
        else:
            print(f"[{role}] no time-sync characteristic: aligning on packet arrival times")
        await client.write_gatt_char(proto.SESSION_CTRL_UUID, bytes([proto.OP_RAW_START]), response=True)
        t_sync = time.time()
        while not stop.is_set() and client.is_connected:
            await asyncio.sleep(0.5)
            if has_sync and time.time() - t_sync >= args.sync_every:
                await rec.sync_burst(client)
                t_sync = time.time()
        if client.is_connected:
            if has_sync:
                await rec.sync_burst(client)
            await client.write_gatt_char(proto.SESSION_CTRL_UUID, bytes([proto.OP_RAW_STOP]), response=True)


async def run_multi(args):
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    devices = parse_device_args(args.device)
    stop = threading.Event()
    lab_fh = open(f"{out}_labels.csv", "w", newline="")
    sync_fh = open(f"{out}_sync.csv", "w", newline="")
    labels, sync = LabelWriter(lab_fh), SyncWriter(sync_fh)
    raw_fhs, recs = [], []
    for role, addr in devices:
        fh = open(f"{out}_{role}_raw.csv", "w", newline="")
        raw_fhs.append(fh)
        recs.append(DeviceRecorder(role, addr.replace(":", "").lower()[-8:] or role, fh, sync))
    threading.Thread(target=stdin_labels, args=(labels, stop), daemon=True).start()
    print("Recording both sensors. Do the SYNC CLAP now (both hands), hold guard ~2 s, then one straight with each hand.")
    try:
        await asyncio.gather(*(record_one(args, role, addr, rec, stop) for (role, addr), rec in zip(devices, recs)))
    finally:
        for fh in (lab_fh, sync_fh, *raw_fhs):
            fh.close()
    for rec in recs:
        print(f"[{rec.role}] {rec.raw.rows} samples, {rec.raw.lost_packets} packets lost -> {out}_{rec.role}_raw.csv")
    print(f"{sync.rows} sync samples -> {out}_sync.csv")


async def run(args):
    from bleak import BleakClient
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw_fh = open(f"{out}_raw.csv", "w", newline="")
    lab_fh = open(f"{out}_labels.csv", "w", newline="")
    pun_fh = open(f"{out}_punches_device.csv", "w", newline="")
    raw = RawCsvWriter(raw_fh)
    labels = LabelWriter(lab_fh)
    pun = csv.writer(pun_fh)
    pun.writerow(["host_time_s", "index", "t_ms", "type", "peak_g", "speed_mps_est",
                  "peak_gyro_dps", "confidence", "saturated", "uncalibrated"])
    stop = threading.Event()

    dev = await find_device(args.name, args.address, args.scan_timeout)
    async with BleakClient(dev) as client:
        print(f"Connected, MTU {client.mtu_size}")
        if client.mtu_size < 3 + 18 + 12:
            print("WARNING: MTU too small for raw stream (need >= 33, ideally 247)")

        def on_raw(_, data: bytearray):
            try:
                raw.on_packet(bytes(data), time.time())
            except ValueError as e:
                print(f"bad packet: {e}")

        def on_punch(_, data: bytearray):
            p = proto.parse_punch(bytes(data))
            pun.writerow([f"{time.time():.6f}", p["index"], p["t_ms"], p["type"], p["peak_g"],
                          p["speed_mps_est"], p["peak_gyro_dps"], p["confidence"],
                          int(p["saturated"]), int(p["uncalibrated"])])

        await client.write_gatt_char(proto.CONFIG_UUID,
                                     proto.pack_config(args.hand, args.stance, args.threshold),
                                     response=True)
        await client.start_notify(proto.RAW_STREAM_UUID, on_raw)
        await client.start_notify(proto.PUNCH_EVENT_UUID, on_punch)
        await client.write_gatt_char(proto.SESSION_CTRL_UUID, bytes([proto.OP_RAW_START]),
                                     response=True)
        if not args.no_session:
            await client.write_gatt_char(proto.SESSION_CTRL_UUID,
                                         proto.session_start_cmd(int(time.time())),
                                         response=True)
        threading.Thread(target=stdin_labels, args=(labels, stop), daemon=True).start()
        print("Recording. Do the SYNC CLAP now, then hold guard ~2 s and throw one jab.")
        t_last = time.time()
        while not stop.is_set() and client.is_connected:
            await asyncio.sleep(0.5)
            if args.duration and time.time() - t_last >= args.duration:
                break
            if int(time.time()) % 5 == 0:
                print(f"\r  {raw.rows} samples, {raw.sat_rows} saturated, "
                      f"{raw.lost_packets} lost pkts", end="", flush=True)
        if client.is_connected:
            for op in ([] if args.no_session else [proto.OP_SESSION_STOP]) + [proto.OP_RAW_STOP]:
                await client.write_gatt_char(proto.SESSION_CTRL_UUID, bytes([op]), response=True)
    for fh in (raw_fh, lab_fh, pun_fh):
        fh.close()
    print(f"\nWrote {raw.rows} samples ({raw.sat_rows} saturated, {raw.lost_packets} packets "
          f"lost, flags {raw.flag_counts}) to {out}_raw.csv")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="output prefix, e.g. recordings/session1")
    ap.add_argument("--name", default="BoxTrk")
    ap.add_argument("--address", help="BLE address (skip scanning)")
    ap.add_argument("--scan-timeout", type=float, default=20.0)
    ap.add_argument("--duration", type=float, default=0, help="stop after N s (0 = until q)")
    ap.add_argument("--hand", choices=["lead", "rear"], default="lead")
    ap.add_argument("--stance", choices=["orthodox", "southpaw"], default="orthodox")
    ap.add_argument("--threshold", type=float, default=3.5, help="on-device threshold (g)")
    ap.add_argument("--no-session", action="store_true", help="raw stream only")
    ap.add_argument("--device", action="append", default=[], metavar="ROLE=ADDRESS",
                    help="two sensors: --device lead=ADDR --device rear=ADDR (one raw CSV per device + sync CSV)")
    ap.add_argument("--sync-every", type=float, default=30.0, help="seconds between time-sync bursts (multi-device)")
    a = ap.parse_args(argv)
    asyncio.run(run_multi(a) if a.device else run(a))


if __name__ == "__main__":
    main()
