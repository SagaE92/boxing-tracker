#!/usr/bin/env python3
"""Record the Boxing Tracker raw IMU stream over BLE to CSV (+ a labels CSV).

  python tools/logger.py --out recordings/2026-10-25_bag      # scan for "BoxTrk"
  python tools/logger.py --address C4:12:34:56:78:9A --out rec1 --hand lead --stance orthodox
  # two sensors, one inside each wrap, recorded at the same time:
  python tools/logger.py --out rec2 --stance orthodox \
      --device lead=C4:12:34:56:78:9A --device rear=D7:65:43:21:0F:1E
  # v1.1 firmware: assign roles once (tap RESET first: 2-minute window), then find by role
  python tools/logger.py --assign-role lead --address C4:12:34:56:78:9A --stance orthodox
  python tools/logger.py --out rec2 --device lead=auto --device rear=auto
  # sensors also log every strike to flash; fetch later (no raw stream needed)
  python tools/logger.py --out rec2 --fetch-log --device lead=auto --device rear=auto

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

  <out>_<role>_log.bin  (--fetch-log) raw 32-byte event-log records; decode / build a
                    session with tools/evlog.py (time anchors are written into the
                    device log by every sync burst, see docs/gatt-spec.md)

While recording, type a label and press Enter to write a marker (host clock):
  sync          -> you just did the sync clap/tap (see tools/README.md)
  cal_start / cal_end  -> guard-pose + calibration-jab segment
  round / rest  -> round boundaries (also sent to v1.1 sensors as ROUND_MARK n / 0);
                   anything else -> free-text label
  "label: note" -> label with a note;   empty line -> "mark";   q -> stop
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
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
    def __init__(self, fh, on_label=None):
        self.fh = fh
        self.w = csv.writer(fh)
        self.w.writerow(LABEL_HEADER)
        self.lock = threading.Lock()
        self.on_label = on_label

    def mark(self, line: str, t: float | None = None):
        t = time.time() if t is None else t
        line = line.strip()
        label, note = (line.split(":", 1) + [""])[:2] if ":" in line else (line or "mark", "")
        with self.lock:
            self.w.writerow([f"{t:.6f}", label.strip(), note.strip()])
            self.fh.flush()
        if self.on_label:
            self.on_label(label.strip())
        return label.strip()


class RoundMarks:
    """Labels "round" / "rest" -> ROUND_MARK control ops (n = round number, 0 = rest),
    queued per device (thread-safe; drained by each device's BLE loop)."""

    def __init__(self, roles):
        self.lock = threading.Lock()
        self.n = 0
        self.q = {r: [] for r in roles}

    def __call__(self, label):
        lab = label.lower()
        if lab not in ("round", "rest"):
            return
        with self.lock:
            if lab == "round":
                self.n += 1
            for q in self.q.values():
                q.append(bytes([proto.OP_ROUND_MARK, self.n if lab == "round" else 0]))

    def take(self, role):
        with self.lock:
            out, self.q[role] = self.q[role], []
        return out


def stdin_labels(labels: LabelWriter, stop: threading.Event):
    print("Type a label + Enter (sync, cal_start, cal_end, round, rest, ...). q = quit.")
    for line in sys.stdin:
        if line.strip().lower() in ("q", "quit", "exit"):
            stop.set()
            return
        print(f"  [{labels.mark(line)}] marked")
    stop.set()


def adv_info(name, adv=None):
    """Role etc. from a scan result: manufacturer data (v1.1) or the -L/-R name suffix."""
    info = proto.parse_adv_mfg(getattr(adv, "manufacturer_data", None) or {}) if adv is not None else None
    info = dict(info or {})
    if not info.get("role"):
        info["role"] = proto.role_from_name(name)
    return info


def is_tracker(name, service_uuids=()):
    return (name or "").startswith(proto.NAME_PREFIX) or proto.SERVICE_UUID in (service_uuids or [])


async def scan_trackers(timeout: float):
    """-> [(BLEDevice, name, info)] for every Boxing Tracker seen."""
    from bleak import BleakScanner
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    out = []
    for dev, adv in found.values():
        name = dev.name or adv.local_name or ""
        if is_tracker(name, adv.service_uuids):
            out.append((dev, name, adv_info(name, adv)))
    return out


def pick_by_role(found, role):
    """found: [(dev, name, info)] -> the one device advertising `role` (SystemExit otherwise)."""
    hits = [f for f in found if f[2].get("role") == role]
    if len(hits) != 1:
        names = ", ".join(f"{n} ({i.get('role') or 'unset'})" for _, n, i in found) or "none"
        raise SystemExit(f"expected exactly one sensor advertising role {role}, found {len(hits)} (seen: {names}). "
                         "Assign roles with --assign-role, or give addresses: --device lead=ADDR")
    return hits[0][0]


async def find_device(name: str, address: str | None, timeout: float):
    from bleak import BleakScanner
    if address:
        return address
    print(f"Scanning for '{name}*' ({timeout:.0f}s)... move the tracker to wake it")
    dev = await BleakScanner.find_device_by_filter(
        lambda d, ad: (d.name or ad.local_name or "").startswith(name)
        or proto.SERVICE_UUID in (ad.service_uuids or []), timeout=timeout)
    if dev is None:
        raise SystemExit("device not found")
    return dev


async def resolve_devices(specs, timeout):
    """[(role, "auto"|address)] -> [(role, address-or-BLEDevice)]."""
    if not any(a == "auto" for _, a in specs):
        return specs
    print(f"Scanning {timeout:.0f}s for sensors by role... move both trackers to wake them")
    found = await scan_trackers(timeout)
    return [(r, pick_by_role(found, r) if a == "auto" else a) for r, a in specs]


def _has(client, uuid):
    return client.services.get_characteristic(uuid) is not None


async def ensure_role(client, role, stance, tag=""):
    """v1.1: make sure the sensor's stored role matches `role` (assigns it if unset).
    Returns the role-characteristic dict, or None for v1.0 firmware."""
    if not _has(client, proto.ROLE_UUID):
        return None
    cur = proto.parse_role(bytes(await client.read_gatt_char(proto.ROLE_UUID)))
    if cur["role"] is None:
        await client.write_gatt_char(proto.ROLE_UUID, proto.pack_role(role, proto.default_wrist(role, stance)),
                                     response=True)
        cur = proto.parse_role(bytes(await client.read_gatt_char(proto.ROLE_UUID)))
        print(f"{tag}role was unset -> assigned {cur['role']} ({cur['wrist']} wrist)")
    elif cur["role"] != role:
        raise SystemExit(f"{tag}this sensor is assigned '{cur['role']}', not '{role}'. Swap the --device "
                         f"addresses, use role=auto, or re-assign: tap RESET, then --assign-role {role}")
    return cur


class DeviceRecorder:
    """One sensor of a multi-device recording: raw CSV + its clock-sync samples.
    BLE-independent apart from `sync_burst`, which takes any object with an async
    read_gatt_char(uuid) (unit tested with a fake client)."""

    def __init__(self, role, device_id, raw_fh, sync: SyncWriter, now=time.time, packet_sync_every=50):
        self.role, self.device_id, self.sync, self.now = role, device_id, sync, now
        self.unwrap = proto.TimeUnwrapper()   # shared by raw packets and time-sync reads
        self._n = 0
        self.anchors = 0
        self.packet_sync_every = packet_sync_every

        def on_packet_sync(dev_us, host_s):
            self._n += 1
            if (self._n - 1) % self.packet_sync_every == 0:   # default ~every 2 s at 416 Hz / 18 per packet
                self.sync.add(self.device_id, self.role, host_s, dev_us, None, "packet")
        self.raw = RawCsvWriter(raw_fh, on_sync=on_packet_sync, unwrap=self.unwrap)

    def on_raw(self, data: bytes, host_rx_s: float):
        return self.raw.on_packet(data, host_rx_s)

    async def sync_burst(self, client, n=8, anchor=True):
        """n time-sync reads; logs (midpoint, device time, rtt). With v1.1 firmware (8-byte
        reply) the best exchange is written back as a time anchor (stored in the device's
        event log, used by tools/evlog.py). Returns the min RTT (ms)."""
        best = None
        v11 = False
        for _ in range(n):
            t0 = self.now()
            data = bytes(await client.read_gatt_char(proto.TIME_SYNC_UUID))
            t1 = self.now()
            raw = proto.parse_time_sync(data)
            v11 = len(data) >= proto.TIME_SYNC.size
            dev = self.unwrap(raw)
            rtt = (t1 - t0) * 1e3
            self.sync.add(self.device_id, self.role, (t0 + t1) / 2, dev, rtt, "rtt")
            if best is None or rtt < best[0]:
                best = (rtt, (t0 + t1) / 2, raw)
        if anchor and v11 and best is not None:
            await client.write_gatt_char(proto.TIME_SYNC_UUID, proto.pack_time_anchor(best[1], best[2], best[0]),
                                         response=True)
            self.anchors += 1
        return best[0] if best else None


class LogFetcher:
    """Collects event-log notifications (32-byte records) until the END record."""

    def __init__(self):
        self.buf = bytearray()
        self.end = None
        self.done = asyncio.Event()

    def on_notify(self, data: bytes):
        for i in range(0, len(data) - len(data) % proto.LOG_REC.size, proto.LOG_REC.size):
            rec = bytes(data[i:i + proto.LOG_REC.size])
            if rec[0] == proto.LOG_END:
                self.end = proto.parse_log_record(rec)
                self.done.set()
            else:
                self.buf += rec

    async def fetch(self, client, from_seq=0, timeout=120.0):
        await client.start_notify(proto.EVENT_LOG_UUID, lambda _, d: self.on_notify(bytes(d)))
        try:
            await client.write_gatt_char(proto.EVENT_LOG_UUID, proto.log_read_cmd(from_seq, 0), response=True)
            await asyncio.wait_for(self.done.wait(), timeout)
        finally:
            await client.stop_notify(proto.EVENT_LOG_UUID)
        n = len(self.buf) // proto.LOG_REC.size
        if self.end and self.end["records_sent"] != n:
            raise RuntimeError(f"log fetch: device sent {self.end['records_sent']} records, got {n}")
        return bytes(self.buf)


def parse_device_args(specs):
    """["lead=AA:BB..", "rear=CC:.."] -> [(role, address)]; roles must be lead/rear, unique."""
    out = []
    for sp in specs:
        role, sep, addr = sp.partition("=")
        if not sep or role not in ("lead", "rear") or not addr:
            raise SystemExit(f"--device expects lead=ADDRESS, rear=ADDRESS or ROLE=auto, got {sp!r}")
        out.append((role, addr))
    if len({r for r, _ in out}) != len(out):
        raise SystemExit("--device: each role (lead, rear) at most once")
    return out


async def record_one(args, role, address, rec: DeviceRecorder, stop: threading.Event, marks=None, session_id=None):
    """Connect one sensor, check/set its role, stream raw data and time-sync it."""
    from bleak import BleakClient
    async with BleakClient(address) as client:
        print(f"[{role}] connected {address}, MTU {client.mtu_size}")
        has_sync = _has(client, proto.TIME_SYNC_UUID)
        await ensure_role(client, role, args.stance, f"[{role}] ")
        await client.write_gatt_char(proto.CONFIG_UUID, proto.pack_config(role, args.stance, args.threshold),
                                     response=True)
        await client.start_notify(proto.RAW_STREAM_UUID, lambda _, d: rec.on_raw(bytes(d), time.time()))
        if has_sync:
            print(f"[{role}] time sync: min RTT {await rec.sync_burst(client):.1f} ms")
        else:
            print(f"[{role}] no time-sync characteristic: aligning on packet arrival times")
        await client.write_gatt_char(proto.SESSION_CTRL_UUID, bytes([proto.OP_RAW_START]), response=True)
        if session_id is not None:  # on-device detection + flash log, same id on both sensors
            await client.write_gatt_char(proto.SESSION_CTRL_UUID, proto.session_start_cmd(session_id), response=True)
        t_sync = time.time()
        while not stop.is_set() and client.is_connected:
            await asyncio.sleep(0.5)
            for cmd in (marks.take(role) if marks else []):
                await client.write_gatt_char(proto.SESSION_CTRL_UUID, cmd, response=True)
            if has_sync and time.time() - t_sync >= args.sync_every:
                await rec.sync_burst(client)
                t_sync = time.time()
        if client.is_connected:
            if has_sync:
                await rec.sync_burst(client)
            if session_id is not None:
                await client.write_gatt_char(proto.SESSION_CTRL_UUID, bytes([proto.OP_SESSION_STOP]), response=True)
            await client.write_gatt_char(proto.SESSION_CTRL_UUID, bytes([proto.OP_RAW_STOP]), response=True)


async def run_multi(args):
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    devices = await resolve_devices(parse_device_args(args.device), args.scan_timeout)
    stop = threading.Event()
    marks = RoundMarks([r for r, _ in devices])
    lab_fh = open(f"{out}_labels.csv", "w", newline="")
    sync_fh = open(f"{out}_sync.csv", "w", newline="")
    labels, sync = LabelWriter(lab_fh, on_label=marks), SyncWriter(sync_fh)
    raw_fhs, recs = [], []
    for role, addr in devices:
        fh = open(f"{out}_{role}_raw.csv", "w", newline="")
        raw_fhs.append(fh)
        recs.append(DeviceRecorder(role, device_id_of(addr, role), fh, sync))
    sid = None if args.no_session else int(time.time())
    threading.Thread(target=stdin_labels, args=(labels, stop), daemon=True).start()
    print("Recording both sensors. Do the SYNC CLAP now (both hands), hold guard ~2 s, then one straight with each hand.")
    try:
        await asyncio.gather(*(record_one(args, role, addr, rec, stop, marks, sid)
                               for (role, addr), rec in zip(devices, recs)))
    finally:
        for fh in (lab_fh, sync_fh, *raw_fhs):
            fh.close()
    for rec in recs:
        print(f"[{rec.role}] {rec.raw.rows} samples, {rec.raw.lost_packets} packets lost, {rec.anchors} anchors "
              f"-> {out}_{rec.role}_raw.csv")
    print(f"{sync.rows} sync samples -> {out}_sync.csv")


def device_id_of(addr, role):
    a = getattr(addr, "address", addr)
    return str(a).replace(":", "").replace("-", "").lower()[-8:] or role


async def fetch_one(args, role, address, out: Path):
    """Write a fresh time anchor, then download the event log to <out>_<role>_log.bin."""
    from bleak import BleakClient
    async with BleakClient(address) as client:
        if not _has(client, proto.EVENT_LOG_UUID):
            raise SystemExit(f"[{role}] firmware has no event log (v1.1 needed)")
        await ensure_role(client, role, args.stance, f"[{role}] ")
        info = proto.parse_log_info(bytes(await client.read_gatt_char(proto.EVENT_LOG_UUID)))
        sync_fh = open(f"{out}_{role}_fetch_sync.csv", "w", newline="")
        rec = DeviceRecorder(role, device_id_of(address, role), io.StringIO(), SyncWriter(sync_fh))
        await rec.sync_burst(client)  # anchor for the current boot
        sync_fh.close()
        await asyncio.sleep(0.2)      # let the anchor reach the log
        frm = args.from_seq if args.from_seq is not None else 0
        print(f"[{role}] log seq {info['first_seq']}..{info['next_seq'] - 1}, fetching from {frm}")
        data = await LogFetcher().fetch(client, frm)
        path = f"{out}_{role}_log.bin"
        Path(path).write_bytes(data)
        n = len(data) // proto.LOG_REC.size
        print(f"[{role}] {n} records -> {path}")
        if args.ack and n:
            last = proto.LOG_REC.unpack_from(data, len(data) - proto.LOG_REC.size)[3]
            await client.write_gatt_char(proto.EVENT_LOG_UUID, proto.log_ack_cmd(last + 1), response=True)
        return path


async def run_fetch(args):
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    specs = parse_device_args(args.device) if args.device else [(args.hand, args.address or "auto")]
    devices = await resolve_devices(specs, args.scan_timeout)
    paths = [await fetch_one(args, r, a, out) for r, a in devices]  # one at a time (some adapters dislike two)
    logs = " ".join(f"--log {r}={p}" for (r, _), p in zip(devices, paths))
    print(f"then: python tools/evlog.py session {logs} --stance {args.stance} --session-out {out}_session.json")


def format_tracker(name, address, info, rssi=None):
    fl = [k for k in ("session", "log_pending", "window_open") if info.get(k)]
    return (f"{name or '?':10s} {address}  role {info.get('role') or 'unset':5s} wrist {info.get('wrist') or '-'}"
            f"  id {info.get('dev_suffix', '----')}" + (f"  rssi {rssi}" if rssi is not None else "")
            + (f"  [{', '.join(fl)}]" if fl else ""))


async def run_scan(args):
    found = await scan_trackers(args.scan_timeout)
    for dev, name, info in found:
        print(format_tracker(name, dev.address, info, getattr(dev, "rssi", None)))
    if not found:
        print("no trackers seen - move them (wake on motion) or tap RESET")


async def run_assign(args):
    """--assign-role / --forget on one sensor (needs the pairing window: tap RESET first)."""
    from bleak import BleakClient
    addr = args.address
    if not addr:
        found = await scan_trackers(args.scan_timeout)
        cands = [f for f in found if f[2].get("window_open")] or found
        if len(cands) != 1:
            raise SystemExit(f"found {len(cands)} sensors ({', '.join(n for _, n, _ in found) or 'none'}); "
                             "give --address, or power only one tracker / tap RESET on one")
        addr = cands[0][0]
    async with BleakClient(addr) as client:
        if not _has(client, proto.ROLE_UUID):
            raise SystemExit("firmware has no role characteristic (v1.1 needed)")
        cur = proto.parse_role(bytes(await client.read_gatt_char(proto.ROLE_UUID)))
        print(f"current: role {cur['role']}, wrist {cur['wrist']}, window {cur['window_s']} s, "
              f"bonded link {cur['bonded_link']}")
        if args.forget:
            await client.write_gatt_char(proto.SESSION_CTRL_UUID, bytes([proto.OP_FORGET]), response=True)
            print("FORGET sent (role cleared, bonds deleted)")
            return
        wrist = args.wrist or proto.default_wrist(args.assign_role, args.stance)
        try:
            await client.write_gatt_char(proto.ROLE_UUID, proto.pack_role(args.assign_role, wrist), response=True)
        except Exception as e:  # ATT 0x05/0x03: window closed and link not bonded
            raise SystemExit(f"role write refused ({e}). Tap RESET on the tracker (opens a 2-minute "
                             "window) and retry within it, or connect from a bonded central.")
        cur = proto.parse_role(bytes(await client.read_gatt_char(proto.ROLE_UUID)))
        print(f"assigned: role {cur['role']}, wrist {cur['wrist']} (persisted {cur['persisted']}); "
              f"it now advertises as {proto.NAME_PREFIX}-{'L' if cur['role'] == 'lead' else 'R'}")


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
        if _has(client, proto.ROLE_UUID):
            cur = proto.parse_role(bytes(await client.read_gatt_char(proto.ROLE_UUID)))
            if cur["role"] and cur["role"] != args.hand:
                print(f"sensor is assigned '{cur['role']}': using that instead of --hand {args.hand}")
                args.hand = cur["role"]
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
    ap.add_argument("--out", help="output prefix, e.g. recordings/session1 (recording / --fetch-log)")
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
    ap.add_argument("--scan", action="store_true", help="list nearby trackers (name, address, role, flags) and exit")
    ap.add_argument("--assign-role", choices=["lead", "rear"], help="store this role on the sensor and exit")
    ap.add_argument("--wrist", choices=["L", "R"], help="with --assign-role (default: from role + --stance)")
    ap.add_argument("--forget", action="store_true", help="clear the sensor's role and bonds and exit")
    ap.add_argument("--fetch-log", action="store_true", help="download the on-device event log(s) and exit")
    ap.add_argument("--from-seq", type=int, help="with --fetch-log: first record (default: everything stored)")
    ap.add_argument("--ack", action="store_true", help="with --fetch-log: mark fetched records as synced")
    a = ap.parse_args(argv)
    if not (a.scan or a.assign_role or a.forget) and not a.out:
        ap.error("--out is required")
    if (a.assign_role or a.forget) and a.device:
        ap.error("--assign-role/--forget work on one sensor (use --address)")
    if a.scan:
        asyncio.run(run_scan(a))
    elif a.assign_role or a.forget:
        asyncio.run(run_assign(a))
    elif a.fetch_log:
        asyncio.run(run_fetch(a))
    else:
        asyncio.run(run_multi(a) if a.device else run(a))


if __name__ == "__main__":
    main()
