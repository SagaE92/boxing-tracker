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
                    str(src / "ringbuf.c"), str(src / "punch_detect.c"), "-lm"], check=True)
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
