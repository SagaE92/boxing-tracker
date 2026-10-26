"""Two sensors (one inside each hand wrap): clock alignment, per-device detection and merge,
and backwards compatibility with single-sensor input and schema 1.0.0 files."""
import csv
import json
from pathlib import Path

import numpy as np
import pytest

import detector as D
import synth

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "docs" / "session.schema.json"
HOST_T0 = 1_792_864_800.0
SKEW_TOL_MS = 2.0   # docs/gatt-spec.md: target <= 2 ms after alignment


def _validate(doc):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text()),
                                    format_checker=jsonschema.FormatChecker()).validate(doc)


# ---------------------------------------------------------------- alignment
@pytest.mark.parametrize("skew_ppm,start_s", [(23.0, 0.37), (-17.5, 0.0), (40.0, 2.0)])
def test_rtt_sync_aligns_within_tolerance_over_40_min(skew_ppm, start_s):
    rng = np.random.default_rng(1)
    clk = synth.DeviceClock(dev_t0_us=3_000_000_000, skew_ppm=skew_ppm, start_s=start_s)
    rows = synth.sync_rows("d", "lead", clk, HOST_T0, 2400.0, rng)
    fit = D.clock_from_sync([(float(r[2]), int(r[3]), float(r[4]), r[5]) for r in rows])
    t = np.linspace(start_s, 2400.0, 500)
    err_ms = (fit.host(clk.dev_us(t) / 1e6) - (HOST_T0 + t)) * 1e3
    assert np.abs(err_ms).max() <= SKEW_TOL_MS, np.abs(err_ms).max()
    assert abs(fit.skew_ppm + skew_ppm) < 2.0          # host = a + b*dev, b ~ 1/(1+skew)
    # without drift correction the same clock is off by tens of ms after 40 min
    assert abs(skew_ppm) * 1e-6 * 2400 * 1e3 > 10 * SKEW_TOL_MS


def test_packet_arrival_lower_envelope_recovers_drift():
    rng = np.random.default_rng(2)
    clk = synth.DeviceClock(dev_t0_us=10, skew_ppm=30.0)
    t = np.arange(0, 1200, 18 / 416)                  # one notification per 18 samples
    host = HOST_T0 + t + (12 + rng.exponential(4.0, t.size)) / 1e3
    fit = D.fit_clock(clk.dev_us(t), host, source="packet")
    assert abs(fit.skew_ppm + 30.0) < 2.0
    # constant BLE latency remains (same for both sensors); the residual spread is small
    err = (fit.host(clk.dev_us(t) / 1e6) - (HOST_T0 + t)) * 1e3
    assert np.ptp(err) <= SKEW_TOL_MS


# ---------------------------------------------------------------- merge
def _e(t, dev, typ="jab", g=8.0, t0=None, t1=None):
    return {"t_peak_s": t, "t_start_s": t - 0.05 if t0 is None else t0, "t_end_s": t + 0.05 if t1 is None else t1,
            "type": typ, "confidence": 0.8, "target": None, "hand": "L", "peak_g": g, "speed_mps_est": 5.0,
            "duration_ms": 100.0, "gyro_int_dps_s": [0, 0, 0], "saturated": False, "device_id": dev}


def test_merge_drops_crosstalk_but_keeps_near_simultaneous_strikes():
    lead = [_e(1.00, "L", g=12.0), _e(5.00, "L", g=9.0)]
    rear = [_e(1.02, "R", "cross", g=4.0),              # crosstalk from the lead hook
            _e(5.03, "R", "cross", g=8.5),              # real near-simultaneous double strike
            _e(7.0, "R", "cross", g=10.0)]
    out, dropped = D.merge_events([lead, rear])
    assert dropped == 1
    assert [(e["t_peak_s"], e["device_id"]) for e in out] == [(1.0, "L"), (5.0, "L"), (5.03, "R"), (7.0, "R")]
    assert out[1].get("near_simultaneous") and out[2].get("near_simultaneous")


def test_merge_dedupes_whole_body_events_across_devices():
    lead = [_e(10.0, "L", "kick_or_body_movement", g=2.0), _e(30.0, "L", "clinch", g=1.0, t0=28.0, t1=33.0)]
    rear = [_e(10.1, "R", "kick_or_body_movement", g=2.5), _e(31.0, "R", "clinch", g=1.5, t0=29.0, t1=35.0),
            _e(50.0, "R", "kick_or_body_movement", g=2.0)]
    out, _ = D.merge_events([lead, rear])
    kicks = [e for e in out if e["type"] == "kick_or_body_movement"]
    clinch = [e for e in out if e["type"] == "clinch"]
    assert len(kicks) == 2 and kicks[0]["device_id"] == "R"          # larger peak kept
    assert len(clinch) == 1 and (clinch[0]["t_start_s"], clinch[0]["t_end_s"]) == (28.0, 35.0)


def test_union_rounds():
    a = [{"index": 0, "t_start_s": 10.0, "t_end_s": 70.0, "kind": "round"}]
    b = [{"index": 0, "t_start_s": 10.4, "t_end_s": 70.2, "kind": "round"},
         {"index": 1, "t_start_s": 70.2, "t_end_s": 100.0, "kind": "rest"},
         {"index": 2, "t_start_s": 100.0, "t_end_s": 160.0, "kind": "round"}]
    r = D.union_rounds([a, b])
    assert [(x["kind"], x["t_start_s"], x["t_end_s"]) for x in r] == [
        ("round", 10.0, 70.2), ("rest", 70.2, 100.0), ("round", 100.0, 160.0)]


# ---------------------------------------------------------------- end to end
@pytest.fixture(scope="module")
def two_sensor_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("two")
    S, labels = synth.make_two_hand_fatigue_session(seed=4, rounds=3, round_s=60.0, rest_s=30.0)
    clocks = {"lead": synth.DeviceClock(3_812_004_117, 23.0, 0.37), "rear": synth.DeviceClock(1_204_556_001, -17.5, 0.0)}
    rng = np.random.default_rng(0)
    args, sync = [], []
    for role, s in S.items():
        acc, gyr, sat, _ = s.render()
        synth.write_raw_csv_clock(d / f"x_{role}_raw.csv", acc, gyr, sat, HOST_T0, clocks[role], rng)
        sync += synth.sync_rows(f"dev-{role}", role, clocks[role], HOST_T0, len(acc) / synth.FS, rng)
        args += ["--stream", f"{role}={d / f'x_{role}_raw.csv'}@dev-{role}"]
    with open(d / "x_sync.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(synth.SYNC_HEADER)
        w.writerows(sync)
    synth.write_labels(d / "x_labels.csv", HOST_T0, labels)
    doc = D.main([*args, "--sync", str(d / "x_sync.csv"), "--labels", str(d / "x_labels.csv"),
                  "--session-out", str(d / "x_session.json")])
    return S, labels, doc


def test_two_sensor_session_matches_truth_per_hand(two_sensor_run):
    S, labels, doc = two_sensor_run
    _validate(doc)
    assert doc["schema_version"] == "1.1.0"
    devs = {x["hand"]: x for x in doc["session"]["devices"]}
    assert set(devs) == {"lead", "rear"} and devs["lead"]["wrist"] == "L" and devs["rear"]["wrist"] == "R"
    assert abs(devs["lead"]["clock"]["offset_s"] - 0.37) < 0.002
    assert devs["lead"]["clock"]["source"] == "rtt"
    truth = [(t, lab.split(":", 1)[1]) for t, lab, _ in labels if lab.startswith("truth:")
             and lab.split(":", 1)[1] not in ("kick_or_body_movement",)]
    strikes = [e for e in doc["punches"] if e["type"] not in ("kick_or_body_movement", "clinch")]
    # event times are on the aligned session clock; labels are true time from the same origin
    # (the rear sensor starts at true t = 0 and has the earliest first sample)
    matched = sum(any(abs(e["t_peak_s"] - t) < 0.06 for e in strikes) for t, _ in truth)
    assert matched >= 0.9 * len(truth), (matched, len(truth))
    assert len(strikes) <= 1.08 * len(truth)
    by_dev = {h: sum(e["device_id"] == devs[h]["device_id"] for e in strikes) for h in devs}
    tr_lead = sum(1 for t, typ in truth if typ in ("jab", "lead_hook", "lead_uppercut")) + \
        sum(1 for t, lab, n in labels if "hand=lead" in n and lab == "truth:spinning_backfist")
    assert abs(by_dev["lead"] - tr_lead) <= 0.15 * tr_lead + 2
    assert all(e["hand"] == devs["lead"]["wrist"] for e in strikes if e["device_id"] == devs["lead"]["device_id"])
    kicks_truth = sum(1 for t, lab, _ in labels if lab == "truth:kick_or_body_movement")
    kicks = sum(1 for e in doc["punches"] if e["type"] == "kick_or_body_movement")
    assert kicks <= kicks_truth + 2   # seen by both sensors but counted once
    assert sum(1 for r in doc["rounds"] if r["kind"] == "round") == 3


def test_single_sensor_input_still_works(tmp_path):
    s, cal = synth.make_class_session("straight", 8, "lead", "southpaw", seed=3)
    acc, gyr, sat, _ = s.render()
    raw = tmp_path / "solo_raw.csv"
    synth.write_raw_csv(raw, acc, gyr, sat, HOST_T0)
    doc = D.main([str(raw), "--hand", "lead", "--stance", "southpaw", "--device-id", "boxtrk-1"])
    _validate(doc)
    assert doc["session"]["hand"] == "lead" and doc["session"]["hand_worn"] == "R"
    assert doc["session"]["devices"][0]["device_id"] == "boxtrk-1"
    assert {e["device_id"] for e in doc["punches"]} == {"boxtrk-1"}


def test_schema_1_0_0_documents_still_validate():
    doc = json.loads((ROOT / "analysis" / "samples" / "demo_session.json").read_text())
    assert doc["schema_version"] == "1.0.0" and "devices" not in doc["session"]
    _validate(doc)
