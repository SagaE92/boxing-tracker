"""v1.1 two-sensor firmware protocol on the host side: role characteristic and advertising,
time anchors, event-log transfer + decoding, and building a session.json from two
sensors' flash logs (tools/evlog.py). Wire formats are checked against bt_proto.h."""
import asyncio
import json
import re
import struct
from pathlib import Path

import pytest

import evlog
import logger
import proto

ROOT = Path(__file__).resolve().parents[2]
H = (ROOT / "firmware" / "src" / "bt_proto.h").read_text()
SCHEMA = ROOT / "docs" / "session.schema.json"


# ---------------------------------------------------------------- helpers
def rec(kind, seq, boot, payload=b""):
    typ = {v: k for k, v in proto.LOG_TYPES.items()}[kind]
    body = struct.pack("<BBHI22s", typ, 0, boot, seq, payload.ljust(22, b"\0"))
    return body + struct.pack("<H", proto.crc16(body))


class Log:
    """Builds a device log the way the firmware writes it."""

    def __init__(self, boot=1):
        self.seq, self.boot, self.data = 1, boot, b""

    def add(self, kind, payload=b""):
        self.data += rec(kind, self.seq, self.boot, payload)
        self.seq += 1

    def start(self, sid, dev_t0, role, wrist):
        self.add("session_start", proto.LOG_SESSION_START.pack(sid, dev_t0 & 0xFFFFFFFF, role, wrist, 0, 0,
                                                               350, 150, 0, 2, 0, 0))

    def anchor(self, host_s, dev_us, rtt_ms=8.0):
        self.add("anchor", proto.TIME_ANCHOR.pack(round(host_s * 1e6), dev_us & 0xFFFFFFFF, round(rtt_ms * 10)) + b"\0" * 8)

    def event(self, dev_us, peak_g, typ=0, flags=0):
        self.add("event", proto.LOG_EVENT.pack(dev_us & 0xFFFFFFFF, typ, flags, round(peak_g * 100), 650, 900,
                                               0, 20, 30, 100, -50, 3000))

    def stop(self, sid, dev_us, n):
        self.add("session_stop", proto.LOG_SESSION_STOP.pack(sid, 0, dev_us & 0xFFFFFFFF, n))

    def round_mark(self, dev_us, n):
        self.add("round_mark", proto.LOG_ROUND.pack(dev_us & 0xFFFFFFFF, n))


# ---------------------------------------------------------------- header consistency
def test_v11_uuids_ops_and_sizes_match_header():
    assert proto.TIME_SYNC_UUID.startswith("6e7b0008") and proto.ROLE_UUID.startswith("6e7b0009")
    assert proto.EVENT_LOG_UUID.startswith("6e7b000a")
    assert re.search(r"BTRK_UUID_ROLE\s+0x0009", H) and re.search(r"BTRK_UUID_EVENT_LOG\s+0x000A", H)
    assert re.search(r"BTRK_OP_FORGET\s+= 0x08", H) and proto.OP_FORGET == 8
    for name, size in (("btrk_role_chr", 4), ("btrk_adv_mfg", 8), ("btrk_time_sync", 8),
                       ("btrk_time_anchor", 14), ("btrk_log_info", 16)):
        assert f"sizeof(struct {name}) == {size}" in H
    assert "BTRK_LOG_REC_SIZE  32" in H and proto.LOG_REC.size == 32
    for k, v in proto.LOG_TYPES.items():
        if v not in ("end", "empty"):
            assert re.search(rf"BTRK_LOG_{v.upper()}\s+= 0x{k:02X}", H), v
    assert f"0x{proto.LOG_ERASE_MAGIC:08x}u" in H.lower()
    assert re.search(r"BTRK_ADV_COMPANY_ID\s+0xFFFF", H) and re.search(r"BTRK_ADV_PROTO\s+0x11", H)


def test_crc16_ccitt_false_check_value():
    assert proto.crc16(b"123456789") == 0x29B1


# ---------------------------------------------------------------- role + advertising
def test_role_pack_parse_and_names():
    assert proto.pack_role("rear", "R") == b"\x02\x02" and proto.pack_role(None) == b"\x00\x00"
    r = proto.parse_role(bytes([1, 1, proto.ROLE_F_WINDOW_OPEN | proto.ROLE_F_PERSISTED, 87]))
    assert r == {"role": "lead", "wrist": "L", "window_open": True, "bonded_link": False, "persisted": True,
                 "window_s": 87}
    assert proto.default_wrist("lead") == "L" and proto.default_wrist("lead", "southpaw") == "R"
    assert proto.role_from_name("BoxTrk-L") == "lead" and proto.role_from_name("BoxTrk-R") == "rear"
    assert proto.role_from_name("BoxTrk") is None and proto.role_from_name("Other-L") is None
    assert logger.is_tracker("BoxTrk-R") and logger.is_tracker("", [proto.SERVICE_UUID]) and not logger.is_tracker("X")


def test_adv_info_prefers_manufacturer_data_and_pick_by_role():
    class Adv:
        def __init__(self, mfg):
            self.manufacturer_data = mfg
    mfg = {0xFFFF: bytes([0x11, 2, 2, proto.ADV_F_LOG_PENDING, 0xAD, 0xDE])}
    i = logger.adv_info("BoxTrk", Adv(mfg))
    assert i["role"] == "rear" and i["log_pending"] and i["dev_suffix"] == "dead"
    assert logger.adv_info("BoxTrk-L", Adv({}))["role"] == "lead"      # name suffix fallback
    assert proto.parse_adv_mfg({0x004C: b"\x02\x15"}) is None           # someone else's data
    found = [("A", "BoxTrk-L", {"role": "lead"}), ("B", "BoxTrk-R", {"role": "rear"})]
    assert logger.pick_by_role(found, "rear") == "B"
    with pytest.raises(SystemExit):
        logger.pick_by_role(found + [("C", "BoxTrk-R", {"role": "rear"})], "rear")
    with pytest.raises(SystemExit):
        logger.pick_by_role(found[:1], "rear")


class FakeServices:
    def __init__(self, uuids):
        self.uuids = set(uuids)

    def get_characteristic(self, u):
        return u if u in self.uuids else None


class FakeRoleClient:
    def __init__(self, role=0, wrist=0, uuids=(proto.ROLE_UUID,)):
        self.services = FakeServices(uuids)
        self.role, self.wrist, self.writes = role, wrist, []

    async def read_gatt_char(self, u):
        assert u == proto.ROLE_UUID
        return bytes([self.role, self.wrist, proto.ROLE_F_PERSISTED if self.role else 0, 0])

    async def write_gatt_char(self, u, data, response=True):
        self.writes.append((u, bytes(data)))
        self.role, self.wrist = data[0], data[1]


def test_ensure_role_assigns_unset_and_refuses_mismatch():
    c = FakeRoleClient()
    r = asyncio.run(logger.ensure_role(c, "rear", "southpaw"))
    assert c.writes == [(proto.ROLE_UUID, b"\x02\x01")] and r["role"] == "rear" and r["wrist"] == "L"
    c = FakeRoleClient(1, 1)
    assert asyncio.run(logger.ensure_role(c, "lead", "orthodox"))["role"] == "lead" and not c.writes
    with pytest.raises(SystemExit, match="assigned 'lead'"):
        asyncio.run(logger.ensure_role(c, "rear", "orthodox"))
    assert asyncio.run(logger.ensure_role(FakeRoleClient(uuids=()), "rear", "orthodox")) is None  # v1.0 fw


def test_round_marks_from_labels():
    m = logger.RoundMarks(["lead", "rear"])
    lw = logger.LabelWriter(__import__("io").StringIO(), on_label=m)
    for lab in ("sync", "round", "rest", "round"):
        lw.mark(lab, 1.0)
    want = [bytes([proto.OP_ROUND_MARK, 1]), bytes([proto.OP_ROUND_MARK, 0]), bytes([proto.OP_ROUND_MARK, 2])]
    assert m.take("lead") == want and m.take("rear") == want and m.take("lead") == []


# ---------------------------------------------------------------- time sync
def test_time_sync_parse_8_and_4_bytes_and_anchor_pack():
    assert proto.parse_time_sync(proto.TIME_SYNC.pack(123, 9, 1, 0)) == 123
    assert proto.parse_time_sync(struct.pack("<I", 77)) == 77
    assert proto.parse_time_sync_full(proto.TIME_SYNC.pack(5, 9, 1, 0)) == {"device_time_us": 5, "boot_id": 9,
                                                                             "session": True}
    a = proto.pack_time_anchor(1_792_864_800.123456, 0x1_0000_0005, 7.46)
    assert len(a) == 14 and proto.TIME_ANCHOR.unpack(a) == (1_792_864_800_123_456, 5, 75)


# ---------------------------------------------------------------- log transfer
class FakeLogClient:
    """Answers READ with the given records, packed 7 per notification, then END."""

    def __init__(self, records: bytes, next_seq):
        self.records, self.next_seq, self.cb, self.ops = records, next_seq, None, []

    async def start_notify(self, u, cb):
        assert u == proto.EVENT_LOG_UUID
        self.cb = cb

    async def stop_notify(self, u):
        self.cb = None

    async def write_gatt_char(self, u, data, response=True):
        self.ops.append(bytes(data))
        op, frm, mx = struct.unpack("<BII", data)
        assert op == proto.LOG_OP_READ
        recs = [self.records[i:i + 32] for i in range(0, len(self.records), 32)]
        recs = [r for r in recs if struct.unpack_from("<I", r, 4)[0] >= frm]
        end = rec("end", 0, 1, struct.pack("<II", len(recs), self.next_seq))
        allr = recs + [end]
        for i in range(0, len(allr), 7):
            self.cb(None, bytearray(b"".join(allr[i:i + 7])))


def test_log_fetcher_collects_until_end():
    lg = Log()
    for k in range(20):
        lg.event(1000 + k * 500_000, 4.0 + k / 10)
    c = FakeLogClient(lg.data, lg.seq)
    data = asyncio.run(logger.LogFetcher().fetch(c, from_seq=5))
    recs, bad = evlog.read_records(data)
    assert bad == 0 and [r["seq"] for r in recs] == list(range(5, 21))
    assert c.ops == [proto.log_read_cmd(5, 0)]


def test_read_records_skips_bad_crc_and_dedups():
    lg = Log()
    lg.event(10, 5.0)
    lg.event(20, 6.0)
    broken = bytearray(lg.data)
    broken[40] ^= 0xFF                       # corrupt record 2's payload
    recs, bad = evlog.read_records(bytes(broken) + lg.data[:32])
    assert bad == 1 and [r["seq"] for r in recs] == [1]


# ---------------------------------------------------------------- session from two logs
HOST0 = 1_792_864_800.0


def two_logs(skew_lead=30e-6, skew_rear=-20e-6, anchors_every=30.0):
    """Two devices, each with its own boot clock (lead wraps the 32-bit counter), a shared
    session id, a few strikes at known host times and one crosstalk peak."""
    sid = int(HOST0)
    out = {}
    truth = {"lead": [10.0, 40.0, 70.25], "rear": [11.0, 40.02, 90.5]}
    for role, dev0, skew, wrist in (("lead", 0xFFFFFFFF - 20_000_000, skew_lead, 1), ("rear", 50_000_000, skew_rear, 2)):
        dev = lambda t: int(dev0 + t * (1 + skew) * 1e6)  # noqa: E731
        lg = Log(boot=3 if role == "lead" else 8)
        lg.add("boot", proto.LOG_BOOT.pack(0, 1 if role == "lead" else 2, wrist))
        lg.anchor(HOST0 - 1.0, dev(-1.0))
        lg.start(sid, dev(0.0), 1 if role == "lead" else 2, wrist)
        t = 0.0
        evs = sorted([(x, 6.0) for x in truth[role]] + ([(40.01, 1.5)] if role == "lead" else []))  # crosstalk
        lg.round_mark(dev(5.0), 1)
        for te, g in evs:
            while t + anchors_every <= te:
                t += anchors_every
                lg.anchor(HOST0 + t, dev(t))
            lg.event(dev(te), g, typ=1 if (role == "lead" and te == 10.0) else 0)
        lg.round_mark(dev(80.0), 0)
        lg.stop(sid, dev(100.0), len(evs))
        lg.anchor(HOST0 + 100.0, dev(100.0))
        out[role] = lg.data
    return out, truth


def test_session_from_two_logs_aligns_and_validates():
    jsonschema = pytest.importorskip("jsonschema")
    logs, truth = two_logs()
    parsed = [(r, f"dev-{r}", evlog.read_records(d)[0]) for r, d in logs.items()]
    doc, info = evlog.session_from_logs(parsed, "orthodox")
    jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text()),
                                    format_checker=jsonschema.FormatChecker()).validate(doc)
    assert doc["schema_version"] == "1.1.0" and info["crosstalk_dropped"] == 1
    p = doc["punches"]
    got = sorted((e["device_id"], round(e["t_peak_s"], 3)) for e in p)
    want = sorted([(f"dev-{r}", t) for r in truth for t in truth[r]])
    assert [g[0] for g in got] == [w[0] for w in want]
    assert all(abs(g[1] - w[1]) <= 0.002 for g, w in zip(got, want))   # <= 2 ms on the session clock
    assert {e["hand"] for e in p if e["device_id"] == "dev-lead"} == {"L"}
    assert next(e for e in p if abs(e["t_peak_s"] - 10.0) < 0.01)["type"] == "jab"   # calibration strike
    assert sum(e["type"] == "unknown" for e in p) == 5
    devs = {d["device_id"]: d for d in doc["session"]["devices"]}
    assert abs(devs["dev-lead"]["clock"]["skew_ppm"] + 30) < 1 and abs(devs["dev-rear"]["clock"]["skew_ppm"] - 20) < 1
    assert devs["dev-lead"]["clock"]["source"] == "anchor"
    kinds = [(r["kind"], round(r["t_start_s"], 1)) for r in doc["rounds"]]
    assert kinds == [("round", 5.0), ("rest", 80.0)]
    assert doc["summary"]["punches_per_round"] == [5]                 # 90.5 s strike is in the rest
    assert doc["summary"]["by_hand"] == {"L": 3, "R": 3, "unknown": 0}


def test_session_needs_an_anchor_in_the_same_boot():
    lg = Log(boot=4)
    lg.start(7, 1000, 1, 1)
    lg.event(2000, 5.0)
    with pytest.raises(SystemExit, match="no time anchor"):
        evlog.session_from_logs([("lead", "d", evlog.read_records(lg.data)[0])])


def test_evlog_cli_dump_and_session(tmp_path, capsys):
    logs, _ = two_logs()
    paths = {}
    for r, d in logs.items():
        paths[r] = tmp_path / f"s_{r}_log.bin"
        paths[r].write_bytes(d)
    assert len(evlog.main(["dump", str(paths["lead"])])) == len(logs["lead"]) // 32
    out = tmp_path / "s.json"
    doc = evlog.main(["session", "--log", f"lead={paths['lead']}", "--log", f"rear={paths['rear']}@abc",
                      "--session-out", str(out)])
    assert json.loads(out.read_text())["summary"]["punch_count"] == doc["summary"]["punch_count"] == 6
    assert "abc" in {d["device_id"] for d in doc["session"]["devices"]}


def test_format_tracker_line_and_cli_requires_out():
    line = logger.format_tracker("BoxTrk-R", "AA:BB", {"role": "rear", "wrist": "R", "dev_suffix": "c0de",
                                                      "window_open": True}, -60)
    assert "role rear" in line and "id c0de" in line and "[window_open]" in line and "rssi -60" in line
    with pytest.raises(SystemExit):
        logger.main(["--hand", "lead"])
