import csv
import io
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

import logger
import proto

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "firmware"


def make_packet(seq, t0, period, samples, flags=0):
    amask = gmask = 0
    body = b""
    for i, (a, g) in enumerate(samples):
        if any(abs(v) >= proto.ACCEL_SAT_RAW for v in a):
            amask |= 1 << i
        if any(abs(v) >= proto.GYRO_SAT_RAW for v in g):
            gmask |= 1 << i
        body += proto.RAW_SAMPLE.pack(*a, *g)
    return proto.RAW_HDR.pack(seq, len(samples), flags, t0, period, amask, gmask) + body


def test_raw_csv_writer_header_scaling_sat_and_wrap():
    fh = io.StringIO()
    w = logger.RawCsvWriter(fh)
    s = [((2049, 0, 0), (0, 0, 0)), ((32767, 0, 0), (0, 0, 0)), ((0, 0, 0), (0, 28571, 0))]
    w.on_packet(make_packet(1, 0xFFFFF000, 2404, s), 1000.0)
    w.on_packet(make_packet(3, (0xFFFFF000 + 3 * 2404) & 0xFFFFFFFF, 2404, s), 1000.01)
    rows = list(csv.reader(io.StringIO(fh.getvalue())))
    assert rows[0] == logger.RAW_HEADER
    assert rows[0] == ["host_time_s", "device_time_us", "ax_g", "ay_g", "az_g",
                       "gx_dps", "gy_dps", "gz_dps", "sat"]
    assert abs(float(rows[1][2]) - 1.0) < 0.001        # 2049 LSB = 1 g
    assert [r[8] for r in rows[1:4]] == ["0", "1", "1"]
    dev = [int(r[1]) for r in rows[1:]]
    assert dev == sorted(dev) and dev[-1] > 0xFFFFFFFF  # unwrapped across the 32-bit wrap
    assert w.lost_packets == 1                           # seq 2 missing


def test_label_writer():
    fh = io.StringIO()
    lw = logger.LabelWriter(fh)
    lw.mark("sync", 5.0)
    lw.mark("cal_start: hold guard", 6.0)
    lw.mark("", 7.0)
    rows = list(csv.reader(io.StringIO(fh.getvalue())))
    assert rows[0] == ["host_time_s", "label", "note"]
    assert rows[1][1:] == ["sync", ""] and rows[2][1:] == ["cal_start", "hold guard"]
    assert rows[3][1] == "mark"


def test_struct_sizes_match_firmware_header():
    h = (FW / "src" / "bt_proto.h").read_text()
    assert "BTRK_RAW_HDR_SIZE        18" in h and "BTRK_RAW_SAMPLE_SIZE     12" in h
    assert "sizeof(struct btrk_punch_evt) == 16" in h
    assert "sizeof(struct btrk_session_summary) == 40" in h
    assert f"BTRK_ACCEL_SAT_RAW       {proto.ACCEL_SAT_RAW}" in h
    assert f"BTRK_GYRO_SAT_RAW        {proto.GYRO_SAT_RAW}" in h
    for i, name in enumerate(proto.PUNCH_TYPES):
        assert f"= {i}," in h  # enum values exist in order
    assert "6e7bXXXX-4b1d-4c8a-9a3e-2f5b0c1d7a00" in h
    assert proto.SERVICE_UUID == "6e7b0001-4b1d-4c8a-9a3e-2f5b0c1d7a00"


def test_c_packer_matches_python_parser(tmp_path):
    """Compile the firmware's portable modules on the host and decode their output."""
    cc = shutil.which("gcc") or shutil.which("cc")
    if not cc:
        pytest.skip("no C compiler")
    exe = tmp_path / "test_host"
    src = FW / "src"
    subprocess.run([cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-O1", f"-I{src}", "-o", str(exe),
                    str(FW / "tests" / "host" / "test_host.c"), str(src / "raw_pack.c"),
                    str(src / "ringbuf.c"), str(src / "punch_detect.c"), str(src / "evlog.c"),
                    str(src / "btrk_util.c"), "-lm"], check=True)
    out = subprocess.run([str(exe)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout
    assert "HOST TESTS OK" in out.stdout
    hexpkt = next(l for l in out.stdout.splitlines() if l.startswith("PKT ")).split()[1]
    pkt = proto.parse_raw(bytes.fromhex(hexpkt))
    assert pkt.seq == 0xBEEF and len(pkt.samples) == 18 and pkt.period_us == 2404
    assert pkt.flags & proto.RAW_F_TS_RESYNC
    assert [s.accel_sat for s in pkt.samples].count(True) == 2
    assert pkt.samples[3].accel_sat and pkt.samples[5].accel_sat and pkt.samples[7].gyro_sat
    assert pkt.samples[2].accel_raw == (200, -2, 2049)
    assert pkt.samples[17].t_us == (0xFFFFF000 + 17 * 2404) & 0xFFFFFFFF
    # event-log record written by the C side (evlog_rec_seal) decodes with the right CRC
    rec = proto.parse_log_record(bytes.fromhex(next(l for l in out.stdout.splitlines() if l.startswith("REC ")).split()[1]))
    assert rec["kind"] == "event" and rec["seq"] == 0xA0B0C0D0 and rec["boot_id"] == 0x1234
    assert rec["type"] == "cross" and rec["saturated"] and rec["hand"] == "rear" and rec["peak_g"] == 16.12
    assert rec["dev_t_peak_us"] == 0xFFFFFF00 and rec["pre_ms"] == 60 and rec["post_ms"] == 82
    assert rec["gyro_int_deg_sensor"] == [-123.4, 5.6, 3276.7] and rec["confidence"] == 1.0
    adv = bytes.fromhex(next(l for l in out.stdout.splitlines() if l.startswith("ADV ")).split()[1])
    assert int.from_bytes(adv[:2], "little") == proto.ADV_COMPANY_ID
    assert proto.parse_adv_mfg(adv[2:]) == {"proto": 0x11, "role": "rear", "wrist": "R", "session": True,
                                            "log_pending": False, "window_open": False, "dev_suffix": "c0de"}


def test_punch_event_roundtrip():
    data = proto.PUNCH_EVT.pack(4, 12345, 4, proto.PUNCH_F_ACCEL_SAT | proto.PUNCH_F_REAR_HAND | (2 << 3),
                                1650, 820, 1200, 75, 0)
    p = proto.parse_punch(data)
    assert p["type"] == "rear_hook" and p["saturated"] and p["hand"] == "rear"
    assert p["target"] == "body" and p["peak_g"] == 16.5 and p["confidence"] == 0.75


def test_sync_video_finds_clap(tmp_path):
    import sync_video
    import sys
    sys.path.insert(0, str(ROOT / "analysis"))
    import synth
    s, cal = synth.make_class_session("straight", 2, "lead", "orthodox", seed=1)
    acc, gyr, sat, _ = s.render()
    raw = tmp_path / "r_raw.csv"
    synth.write_raw_csv(raw, acc, gyr, sat, 1000.0)
    t = sync_video.find_clap(str(raw))
    assert abs(t - 1002.5) < 0.02  # synth clap at 2.5 s


# ---------------------------------------------------------------- two sensors
def test_parse_device_args():
    assert logger.parse_device_args(["lead=AA:BB", "rear=CC:DD"]) == [("lead", "AA:BB"), ("rear", "CC:DD")]
    for bad in (["left=AA"], ["lead"], ["lead=AA", "lead=BB"]):
        with pytest.raises(SystemExit):
            logger.parse_device_args(bad)


def test_two_device_recorders_write_per_device_raw_and_shared_sync():
    sync_fh = io.StringIO()
    sync = logger.SyncWriter(sync_fh)
    raws = {r: io.StringIO() for r in ("lead", "rear")}
    recs = {r: logger.DeviceRecorder(r, f"dev-{r}", raws[r], sync, packet_sync_every=1) for r in raws}
    s = [((2049, 0, 0), (0, 0, 0))] * 18
    for k in range(3):
        recs["lead"].on_raw(make_packet(k, 1_000_000 + k * 18 * 2404, 2404, s), 100.0 + k * 0.043)
        recs["rear"].on_raw(make_packet(k, 5_000_000 + k * 18 * 2404, 2404, s), 100.01 + k * 0.043)
    rows = list(csv.reader(io.StringIO(sync_fh.getvalue())))
    assert rows[0] == logger.SYNC_HEADER
    assert {r[0] for r in rows[1:]} == {"dev-lead", "dev-rear"}
    assert all(r[5] == "packet" and r[4] == "" for r in rows[1:])
    lead_rows = [r for r in rows[1:] if r[1] == "lead"]
    assert int(lead_rows[0][3]) == 1_000_000 + 17 * 2404       # device time of the packet's last sample
    for r in raws:
        lines = raws[r].getvalue().strip().splitlines()
        assert lines[0].split(",") == logger.RAW_HEADER and len(lines) == 1 + 3 * 18


def test_time_sync_bursts_align_two_sensors_within_2ms():
    """Two fake BLE clients with drifting 32-bit device clocks (one wraps mid-session) and a
    BLE-like link: the read is answered 1-2 connection intervals after the request and the
    device stamps it somewhere inside that window. The absolute error is bounded by half the
    best round trip; the error BETWEEN the two sensors (what matters for merging hands) is
    <= 2 ms because both links share the same timing behaviour."""
    import asyncio
    import random
    import detector

    rnd = random.Random(3)
    st = {"t": 1000.0}
    now = lambda: st["t"]  # noqa: E731
    conn = 0.0075

    class FakeClient:
        def __init__(self, dev0, skew):
            self.dev0, self.skew = dev0, skew
            self.anchors = []

        async def write_gatt_char(self, uuid, data, response=True):
            assert uuid == proto.TIME_SYNC_UUID
            self.anchors.append(proto.TIME_ANCHOR.unpack(data))

        def dev_at(self, t):
            return int(self.dev0 + (t - 1000.0) * (1 + self.skew) * 1e6)

        async def read_gatt_char(self, uuid):
            assert uuid == proto.TIME_SYNC_UUID
            rtt = conn * rnd.choice((1, 1, 2))
            stamp = st["t"] + rtt * rnd.uniform(0.3, 0.7)
            st["t"] += rtt
            return proto.TIME_SYNC.pack(self.dev_at(stamp) & 0xFFFFFFFF, 7, 0, 0)

    clients = {"lead": FakeClient(0xFFFFFFFF - 5_000_000, 35e-6), "rear": FakeClient(123_456, -20e-6)}
    sync_fh = io.StringIO()
    sync = logger.SyncWriter(sync_fh)
    recs = {r: logger.DeviceRecorder(r, f"dev-{r}", io.StringIO(), sync, now=now) for r in clients}
    for _ in range(40):                               # a burst per device every 30 s = 20 min
        for r, c in clients.items():
            assert 7 < asyncio.run(recs[r].sync_burst(c)) < 16
        st["t"] += 30.0
    rows = list(csv.DictReader(io.StringIO(sync_fh.getvalue())))
    fits = {}
    for r in clients:
        rr = [(float(x["host_time_s"]), int(x["device_time_us"]), float(x["rtt_ms"]), x["source"]) for x in rows if x["role"] == r]
        if r == "lead":
            assert rr[-1][1] > 1 << 32                # 32-bit wrap unwrapped
        fits[r] = detector.clock_from_sync(rr)
        assert abs(fits[r].skew_ppm + clients[r].skew * 1e6) < 1.0
        # one anchor per burst = the burst's lowest-RTT exchange, as 32-bit device time
        an = clients[r].anchors
        assert len(an) == 40 and recs[r].anchors == 40
        best = min((x for x in rr[:8]), key=lambda x: x[2])
        assert abs(an[0][0] - best[0] * 1e6) <= 1 and an[0][1:] == (best[1] & 0xFFFFFFFF, round(best[2] * 10))
    lead, rear = clients["lead"], clients["rear"]
    for t in (1000.0, 1300.0, 1800.0, 2200.0):
        h_lead = fits["lead"].host(lead.dev_at(t) / 1e6)   # dev_at is already unwrapped
        h_rear = fits["rear"].host(rear.dev_at(t) / 1e6)
        assert abs(h_lead - t) * 1e3 <= conn / 2 * 1e3 + 0.5   # absolute: <= half the best RTT
        assert abs(h_lead - h_rear) * 1e3 <= 2.0                # between sensors: <= 2 ms
