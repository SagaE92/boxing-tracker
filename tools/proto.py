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
OP_RESPONSE = 0x80

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
