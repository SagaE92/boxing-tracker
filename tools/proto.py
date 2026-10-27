"""Boxing Tracker BLE wire format (Python side).

MUST stay in sync with firmware/src/bt_proto.h and docs/gatt-spec.md.
All fields little-endian.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List

PROTO_VERSION = 1


def uuid(short: int) -> str:
    return f"6e7b{short:04x}-4b1d-4c8a-9a3e-2f5b0c1d7a00"


SERVICE_UUID = uuid(0x0001)
PUNCH_EVENT_UUID = uuid(0x0002)
SESSION_CTRL_UUID = uuid(0x0003)
SESSION_SUMMARY_UUID = uuid(0x0004)
RAW_STREAM_UUID = uuid(0x0005)
CONFIG_UUID = uuid(0x0006)
STATUS_UUID = uuid(0x0007)
TIME_SYNC_UUID = uuid(0x0008)  # v1.1: read -> TIME_SYNC (8 B); write <- TIME_ANCHOR (14 B)
ROLE_UUID = uuid(0x0009)       # v1.1: hand role, read/write ROLE_CHR
EVENT_LOG_UUID = uuid(0x000A)  # v1.1: read LOG_INFO, write log ops, notify 32-byte records
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
SMP_SERVICE_UUID = "8d53dc1d-1db7-4cd3-868b-8a527460aa84"

# scale factors (LSM6DS3TR-C at +-16 g / +-2000 dps)
ACCEL_G_PER_LSB = 0.000488
GYRO_DPS_PER_LSB = 0.070
ACCEL_SAT_RAW = 32100
GYRO_SAT_RAW = 28000

RAW_HDR = struct.Struct("<HBBIHII")  # 18 bytes
RAW_SAMPLE = struct.Struct("<6h")    # 12 bytes
RAW_MAX_SAMPLES = 18
RAW_F_FIFO_OVERRUN = 0x01
RAW_F_RING_OVERRUN = 0x02
RAW_F_TS_RESYNC = 0x04

PUNCH_EVT = struct.Struct("<HIBBHHHBB")  # 16 bytes
SUMMARY = struct.Struct("<IIH11HHHHBB")  # 40 bytes
CONFIG = struct.Struct("<BBBBHH")        # 8 bytes
STATUS = struct.Struct("<BBH")           # 4 bytes

PUNCH_TYPES = [
    "unknown", "jab", "cross", "lead_hook", "rear_hook", "lead_uppercut",
    "rear_uppercut", "overhand", "spinning_backfist", "kick_or_body_movement", "clinch",
]
PUNCH_F_ACCEL_SAT = 0x01
PUNCH_F_GYRO_SAT = 0x02
PUNCH_F_REAR_HAND = 0x04
PUNCH_F_TARGET_MASK = 0x18
PUNCH_F_UNCALIBRATED = 0x20
TARGETS = [None, "head", "body", None]

OP_SESSION_START = 0x01
OP_SESSION_STOP = 0x02
OP_RAW_START = 0x03
OP_RAW_STOP = 0x04
OP_ROUND_MARK = 0x05
OP_POWER_OFF = 0x06
OP_CALIBRATE = 0x07
OP_FORGET = 0x08          # v1.1: clear role + wrist + all bonds (role write rules apply)
OP_RESPONSE = 0x80
ST_OK, ST_UNSUPPORTED, ST_INVALID_PARAM, ST_BAD_STATE, ST_NOT_PERMITTED = range(5)

assert RAW_HDR.size == 18 and RAW_SAMPLE.size == 12
assert PUNCH_EVT.size == 16 and SUMMARY.size == 40 and CONFIG.size == 8 and STATUS.size == 4


@dataclass
class RawSample:
    t_us: int                  # device time (uint32, wraps)
    accel_raw: tuple
    gyro_raw: tuple
    accel_sat: bool
    gyro_sat: bool

    @property
    def accel_g(self):
        return tuple(v * ACCEL_G_PER_LSB for v in self.accel_raw)

    @property
    def gyro_dps(self):
        return tuple(v * GYRO_DPS_PER_LSB for v in self.gyro_raw)


@dataclass
class RawPacket:
    seq: int
    flags: int
    t0_us: int
    period_us: int
    samples: List[RawSample] = field(default_factory=list)


def parse_raw(data: bytes) -> RawPacket:
    if len(data) < RAW_HDR.size:
        raise ValueError(f"raw packet too short: {len(data)}")
    seq, n, flags, t0, period, amask, gmask = RAW_HDR.unpack_from(data, 0)
    if n == 0 or n > RAW_MAX_SAMPLES or len(data) != RAW_HDR.size + n * RAW_SAMPLE.size:
        raise ValueError(f"bad raw packet: n={n} len={len(data)}")
    pkt = RawPacket(seq, flags, t0, period)
    for i in range(n):
        v = RAW_SAMPLE.unpack_from(data, RAW_HDR.size + i * RAW_SAMPLE.size)
        pkt.samples.append(RawSample(
            t_us=(t0 + i * period) & 0xFFFFFFFF,
            accel_raw=v[0:3], gyro_raw=v[3:6],
            accel_sat=bool(amask >> i & 1), gyro_sat=bool(gmask >> i & 1)))
    return pkt


def parse_punch(data: bytes) -> dict:
    idx, t_ms, typ, flags, peak_cg, speed_cms, gyro_dps, conf, _ = PUNCH_EVT.unpack(data)
    return {
        "index": idx, "t_ms": t_ms,
        "type": PUNCH_TYPES[typ] if typ < len(PUNCH_TYPES) else "unknown",
        "peak_g": peak_cg / 100.0, "speed_mps_est": speed_cms / 100.0,
        "peak_gyro_dps": gyro_dps, "confidence": conf / 100.0,
        "saturated": bool(flags & PUNCH_F_ACCEL_SAT),
        "gyro_saturated": bool(flags & PUNCH_F_GYRO_SAT),
        "hand": "rear" if flags & PUNCH_F_REAR_HAND else "lead",
        "target": TARGETS[(flags & PUNCH_F_TARGET_MASK) >> 3],
        "uncalibrated": bool(flags & PUNCH_F_UNCALIBRATED),
    }


def parse_summary(data: bytes) -> dict:
    v = SUMMARY.unpack(data)
    return {
        "session_id": v[0], "duration_ms": v[1], "punch_count": v[2],
        "by_type": dict(zip(PUNCH_TYPES, v[3:14])),
        "max_peak_g": v[14] / 100.0, "mean_peak_g": v[15] / 100.0,
        "punches_per_min": v[16] / 10.0, "active": bool(v[17] & 1), "saturated_count": v[18],
    }


def pack_config(hand: str = "lead", stance: str = "orthodox", threshold_g: float = 3.5,
                refractory_ms: int = 150) -> bytes:
    return CONFIG.pack(PROTO_VERSION, 1 if hand == "rear" else 0,
                       1 if stance == "southpaw" else 0, 0, int(round(threshold_g * 100)),
                       refractory_ms)


def session_start_cmd(session_id: int) -> bytes:
    return struct.pack("<BI", OP_SESSION_START, session_id & 0xFFFFFFFF)


# ---------------------------------------------------------------- v1.1: two sensors
TIME_SYNC = struct.Struct("<IHBB")   # device_time_us, boot_id, flags, reserved (8 B)
TIME_SYNC_V10 = struct.Struct("<I")  # early v1.1 drafts: device_time_us only
TIME_ANCHOR = struct.Struct("<QIH")  # host_unix_us, device_time_us, rtt_100us (14 B)
TS_F_SESSION = 0x01
ROLE_UNSET, ROLE_LEAD, ROLE_REAR = 0, 1, 2
ROLES = {ROLE_LEAD: "lead", ROLE_REAR: "rear"}
ROLE_CODES = {"lead": ROLE_LEAD, "rear": ROLE_REAR, None: ROLE_UNSET}
WRIST_UNKNOWN, WRIST_LEFT, WRIST_RIGHT = 0, 1, 2
WRISTS = {WRIST_LEFT: "L", WRIST_RIGHT: "R"}
WRIST_CODES = {"L": WRIST_LEFT, "R": WRIST_RIGHT, None: WRIST_UNKNOWN}
ROLE_CHR = struct.Struct("<BBBB")    # role, wrist, flags, window_s
ROLE_F_WINDOW_OPEN, ROLE_F_BONDED_LINK, ROLE_F_PERSISTED = 0x01, 0x02, 0x04
NAME_PREFIX = "BoxTrk"               # advertised: BoxTrk, BoxTrk-L (lead), BoxTrk-R (rear)
ADV_COMPANY_ID = 0xFFFF
ADV_PROTO = 0x11
ADV_MFG = struct.Struct("<BBBBH")    # after the company id: proto, role, wrist, flags, dev_suffix
ADV_F_SESSION, ADV_F_LOG_PENDING, ADV_F_WINDOW_OPEN = 0x01, 0x02, 0x04

LOG_REC = struct.Struct("<BBHI22sH")  # type, flags, boot_id, seq, payload, crc (32 B)
LOG_INFO = struct.Struct("<IIIHBB")   # first_seq, next_seq, capacity, boot_id, rec_size, flags
LOG_SESSION_START = struct.Struct("<IIBBBBHHBBBB2x")
LOG_EVENT = struct.Struct("<IBBHHHBBB3hx")  # dev_t_peak_us, type, flags, peak_cg, speed_cms, gyro_dps, conf, pre, post, gyro_int[3]
LOG_ANCHOR = struct.Struct("<QIH8x")
LOG_SESSION_STOP = struct.Struct("<IIIH8x")
LOG_ROUND = struct.Struct("<IB17x")
LOG_BOOT = struct.Struct("<IBB16x")
LOG_TYPES = {0x01: "session_start", 0x02: "event", 0x03: "anchor", 0x04: "session_stop",
             0x05: "round_mark", 0x06: "boot", 0x07: "erased", 0xFE: "end", 0xFF: "empty"}
LOG_END = 0xFE
LOG_OP_READ, LOG_OP_ABORT, LOG_OP_ERASE, LOG_OP_ACK = 1, 2, 3, 4
LOG_ERASE_MAGIC = 0x45524153

assert TIME_SYNC.size == 8 and TIME_ANCHOR.size == 14 and ROLE_CHR.size == 4 and ADV_MFG.size == 6
assert LOG_REC.size == 32 and LOG_INFO.size == 16
assert all(s.size == 22 for s in (LOG_SESSION_START, LOG_EVENT, LOG_ANCHOR, LOG_SESSION_STOP, LOG_ROUND, LOG_BOOT))


def parse_time_sync(data: bytes) -> int:
    """device_time_us from a 0x0008 read (8 B; 4 B from early drafts also accepted)."""
    if len(data) < TIME_SYNC_V10.size:
        raise ValueError(f"time sync: {len(data)} bytes")
    return TIME_SYNC_V10.unpack_from(data)[0]


def parse_time_sync_full(data: bytes) -> dict:
    if len(data) >= TIME_SYNC.size:
        t, boot, flags, _ = TIME_SYNC.unpack_from(data)
        return {"device_time_us": t, "boot_id": boot, "session": bool(flags & TS_F_SESSION)}
    return {"device_time_us": parse_time_sync(data), "boot_id": None, "session": None}


def pack_time_anchor(host_unix_s: float, device_time_us: int, rtt_ms: float) -> bytes:
    """Write to 0x0008 after a sync burst: the best (lowest-RTT) exchange; stored in the
    device's event log so offline log fetches can be put on the host clock."""
    return TIME_ANCHOR.pack(int(round(host_unix_s * 1e6)), device_time_us & 0xFFFFFFFF,
                            min(0xFFFF, int(round(rtt_ms * 10))))


def parse_role(data: bytes) -> dict:
    role, wrist, flags, win = ROLE_CHR.unpack_from(data)
    return {"role": ROLES.get(role), "wrist": WRISTS.get(wrist), "window_open": bool(flags & ROLE_F_WINDOW_OPEN),
            "bonded_link": bool(flags & ROLE_F_BONDED_LINK), "persisted": bool(flags & ROLE_F_PERSISTED),
            "window_s": win}


def pack_role(role, wrist=None) -> bytes:
    """role: "lead" / "rear" / None (unset); wrist: "L" / "R" / None."""
    return bytes([ROLE_CODES[role], WRIST_CODES[wrist]])


def default_wrist(role, stance="orthodox"):
    if role is None:
        return None
    return ("L" if role == "lead" else "R") if stance != "southpaw" else ("R" if role == "lead" else "L")


def parse_adv_mfg(mfg: dict | bytes):
    """Advertised manufacturer data -> dict or None. Accepts bleak's
    AdvertisementData.manufacturer_data ({company_id: bytes}) or the raw bytes
    after the company id."""
    if isinstance(mfg, dict):
        data = mfg.get(ADV_COMPANY_ID)
        if data is None:
            return None
    else:
        data = mfg
    if len(data) < ADV_MFG.size or data[0] >> 4 != ADV_PROTO >> 4:
        return None
    proto_v, role, wrist, flags, suffix = ADV_MFG.unpack_from(data)
    return {"proto": proto_v, "role": ROLES.get(role), "wrist": WRISTS.get(wrist),
            "session": bool(flags & ADV_F_SESSION), "log_pending": bool(flags & ADV_F_LOG_PENDING),
            "window_open": bool(flags & ADV_F_WINDOW_OPEN), "dev_suffix": f"{suffix:04x}"}


def role_from_name(name: str | None):
    if not name or not name.startswith(NAME_PREFIX):
        return None
    return {"-L": "lead", "-R": "rear"}.get(name[len(NAME_PREFIX):])


def parse_role_service_data(data: bytes):
    """Deprecated draft (service data: u8 role + u16 suffix); kept for old captures.
    v1.1 firmware advertises manufacturer data instead, see parse_adv_mfg."""
    if len(data) < 3:
        return None, None
    return ROLES.get(data[0]), int.from_bytes(data[1:3], "little")


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (firmware btrk_crc16)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def parse_log_info(data: bytes) -> dict:
    first, nxt, cap, boot, rs, flags = LOG_INFO.unpack_from(data)
    return {"first_seq": first, "next_seq": nxt, "capacity": cap, "boot_id": boot, "rec_size": rs,
            "reading": bool(flags & 1), "no_flash": bool(flags & 0x80)}


def log_read_cmd(from_seq: int = 0, max_records: int = 0) -> bytes:
    return struct.pack("<BII", LOG_OP_READ, from_seq, max_records)


def log_ack_cmd(seq: int) -> bytes:
    return struct.pack("<BI", LOG_OP_ACK, seq)


def log_erase_cmd() -> bytes:
    return struct.pack("<BI", LOG_OP_ERASE, LOG_ERASE_MAGIC)


def parse_log_record(rec: bytes) -> dict:
    """One 32-byte event-log record -> dict with "kind" (session_start, event, anchor, ...) plus
    its fields; events also carry the punch fields of parse_punch. ValueError on a bad CRC."""
    if len(rec) != LOG_REC.size:
        raise ValueError(f"log record: {len(rec)} bytes")
    typ, flags, boot, seq, pl, crc = LOG_REC.unpack(rec)
    if crc16(rec[:30]) != crc:
        raise ValueError(f"log record seq {seq}: bad CRC")
    out = {"kind": LOG_TYPES.get(typ, f"0x{typ:02x}"), "boot_id": boot, "seq": seq}
    if typ == 0x01:
        v = LOG_SESSION_START.unpack(pl)
        out.update(session_id=v[0], dev_t0_us=v[1], role=ROLES.get(v[2]), wrist=WRISTS.get(v[3]),
                   stance="southpaw" if v[4] else "orthodox", threshold_g=v[6] / 100.0, refractory_ms=v[7],
                   firmware_version=f"{v[8]}.{v[9]}.{v[10]}")
    elif typ == 0x02:
        t_peak, typ_p, fl, peak_cg, speed_cms, gyro_dps, conf, pre, post, gx, gy, gz = LOG_EVENT.unpack(pl)
        out.update(parse_punch(PUNCH_EVT.pack(0, 0, typ_p, fl, peak_cg, speed_cms, gyro_dps, conf, 0)),
                   dev_t_peak_us=t_peak, pre_ms=pre * 2, post_ms=post * 2,
                   gyro_int_deg_sensor=[gx / 10.0, gy / 10.0, gz / 10.0])
        del out["index"], out["t_ms"]
    elif typ == 0x03:
        host_us, dev, rtt = LOG_ANCHOR.unpack(pl)
        out.update(host_time_s=host_us / 1e6, device_time_us=dev, rtt_ms=rtt / 10.0)
    elif typ == 0x04:
        sid, dur, dev, n = LOG_SESSION_STOP.unpack(pl)
        out.update(session_id=sid, duration_ms=dur, dev_t_us=dev, punch_count=n)
    elif typ == 0x05:
        dev, rnd = LOG_ROUND.unpack(pl)
        out.update(dev_t_us=dev, round=rnd)
    elif typ == 0x06:
        cause, role, wrist = LOG_BOOT.unpack(pl)
        out.update(reset_cause=cause, role=ROLES.get(role), wrist=WRISTS.get(wrist))
    elif typ == LOG_END:
        sent, nxt = struct.unpack_from("<II", pl)
        out.update(records_sent=sent, device_next_seq=nxt)
    return out


class TimeUnwrapper:
    """Unwrap the 32-bit microsecond device clock into a monotonically increasing int."""

    def __init__(self):
        self.last = None
        self.offset = 0

    def __call__(self, t32: int) -> int:
        if self.last is not None and t32 < self.last and self.last - t32 > 0x80000000:
            self.offset += 1 << 32
        self.last = t32
        return t32 + self.offset
