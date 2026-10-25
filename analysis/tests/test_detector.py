import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest

import common as C
import detector
import evaluate
import synth

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "docs" / "session.schema.json"
SAMPLES = ROOT / "analysis" / "samples"


def _run(s, cal, hand, stance, **kw):
    acc, gyr, sat, mount = s.render()
    rec = detector.Recording(s.t, acc, gyr, sat, 1_792_864_800.0, synth.FS)
    labels = [(cal[0], "cal_start", ""), (cal[1], "cal_end", ""), (2.5, "sync", "")]
    p = detector.Params(hand=hand, stance=stance, **kw)
    events, rounds, c = detector.analyze(rec, labels, p)
    return rec, events, rounds, c, mount, p


# ---------------------------------------------------------------- per-class recall
@pytest.fixture(scope="module")
def bench():
    return evaluate.run_benchmark(count=25, seeds=(1,), verbose=True)


@pytest.mark.parametrize("cls", C.ALL_TYPES[:-1])  # every class except "unknown"
def test_every_class_recall_default(bench, cls):
    table, fps = bench
    assert cls in table, f"{cls} not covered by the synthetic benchmark"
    recall, n, conf = table[cls]
    print(f"{cls}: recall {recall:.1%} (n={n}) {conf}")
    assert n >= 3
    assert recall >= 0.9, conf


def test_no_false_positives_on_isolated_events(bench):
    assert bench[1] <= 5


def test_hook_and_uppercut_recall_under_stress():
    """Headline target: hooks. Harder synthetic variation (25 deg jitter, weaker rotation)."""
    table, _ = evaluate.run_benchmark(count=20, seeds=(3,), verbose=True,
                                      jitter_deg=25.0, rot_scale=(0.5, 1.2))
    for cls in ("lead_hook", "rear_hook", "lead_uppercut", "rear_uppercut"):
        assert table[cls][0] >= 0.8, (cls, table[cls])
    for cls in ("jab", "cross", "overhand", "spinning_backfist"):
        assert table[cls][0] >= 0.7, (cls, table[cls])


# ---------------------------------------------------------------- detector mechanics
def _impulses(times, amp=8.0, dur=3.0):
    n = int(dur * synth.FS)
    t = np.arange(n) / synth.FS
    acc = np.zeros((n, 3))
    acc[:, 2] = 1.0
    for t0 in times:
        acc[:, 0] += amp * np.exp(-0.5 * ((t - t0) / 0.03) ** 2)
    return detector.Recording(t, acc, np.zeros((n, 3)), np.zeros(n, bool), 0.0, synth.FS)


def test_refractory_merges_close_peaks():
    p = detector.Params()
    rec = _impulses([1.0, 1.1])
    assert len(detector.find_peaks(detector.dyn_g(rec.acc), rec.t, p)) == 1
    rec = _impulses([1.0, 1.4])
    assert len(detector.find_peaks(detector.dyn_g(rec.acc), rec.t, p)) == 2


def test_threshold_configurable():
    rec = _impulses([1.0], amp=3.0)
    dyn = detector.dyn_g(rec.acc)
    assert len(detector.find_peaks(dyn, rec.t, detector.Params(threshold_g=3.5))) == 0
    assert len(detector.find_peaks(dyn, rec.t, detector.Params(threshold_g=2.0))) == 1


def test_calibration_recovers_mounting():
    s, cal = synth.make_class_session("straight", 5, "lead", "orthodox", seed=11)
    rec, events, _, c, mount, _ = _run(s, cal, "lead", "orthodox")
    assert c.ok
    # calibrated frame axes expressed in the sensor frame are mount @ e_i
    fwd_true, up_true = mount @ np.array([1.0, 0, 0]), mount @ np.array([0, 0, 1.0])
    ang = lambda a, b: math.degrees(math.acos(np.clip(np.dot(a, b), -1, 1)))  # noqa: E731
    assert ang(c.rot[2], up_true) < 5
    assert ang(c.rot[0], fwd_true) < 20  # calibration jab itself has technique jitter
    assert events[0]["type"] == "jab" and events[0]["confidence"] == 1.0


def test_saturated_hooks_flagged_peak_is_lower_bound():
    s, cal = synth.make_class_session("hook", 20, "rear", "orthodox", seed=5, hard_frac=1.0)
    rec, events, *_ = _run(s, cal, "rear", "orthodox")
    truth = {round(t.t_s, 2): t for t in s.truths if t.base == "hook"}
    hooks = [e for e in events[1:] if e["type"] == "rear_hook"]
    sat = [e for e in hooks if e["saturated"]]
    assert len(hooks) >= 18 and len(sat) >= 5, (len(hooks), len(sat))
    assert rec.sat.any()
    for e in sat:
        tr = min(truth.values(), key=lambda t: abs(t.t_s - e["t_peak_s"]))
        # clipped measurement: never above the true amplitude (+gravity/noise slack)
        assert e["peak_g"] <= tr.amp_g + 1.0
        assert e["peak_g"] <= math.sqrt(3) * 16
    # unsaturated events are never flagged
    assert not any(e["saturated"] for e in events[:1])


def test_non_strikes_excluded_from_totals():
    s, cal = synth.make_class_session("kick", 6, "rear", "orthodox", seed=2, gap=2.5)
    s.strike(22.0, "hook")
    rec, events, rounds, c, _, p = _run(s, cal, "rear", "orthodox")
    s2, cal2 = synth.make_class_session("clinch", 2, "rear", "orthodox", seed=3, gap=8.0)
    rec2, events2, rounds2, *_ = _run(s2, cal2, "rear", "orthodox")
    for r, ev, rd in ((rec, events, rounds), (rec2, events2, rounds2)):
        summ = detector.summarize(r, ev, rd)
        strikes = [e for e in ev if e["type"] not in C.NON_STRIKE_TYPES]
        assert summ["punch_count"] == len(strikes)
        assert summ["non_punch_count"] == len(ev) - len(strikes)
    assert sum(e["type"] == "kick_or_body_movement" for e in events) >= 5
    cl = [e for e in events2 if e["type"] == "clinch"]
    assert len(cl) == 2
    assert all(e["t_end_s"] - e["t_start_s"] >= 4 and e["confidence"] <= 0.5 for e in cl)
    assert all(e["speed_mps_est"] is None for e in cl)
    assert detector.summarize(rec2, events2, rounds2)["clinch_time_s"] >= 8


def test_lead_rear_mapping_and_southpaw():
    for hand, stance, expect, hw in [("lead", "orthodox", "lead_hook", "L"),
                                     ("rear", "orthodox", "rear_hook", "R"),
                                     ("lead", "southpaw", "lead_hook", "R"),
                                     ("rear", "southpaw", "rear_hook", "L")]:
        s, cal = synth.make_class_session("hook", 8, hand, stance, seed=4)
        _, events, *_ = _run(s, cal, hand, stance)
        hooks = [e for e in events[1:] if e["type"] == expect]
        assert len(hooks) >= 7, (hand, stance, [e["type"] for e in events])
        assert all(e["hand"] == hw for e in hooks)


def test_body_target_for_body_shots():
    s, cal = synth.make_class_session("straight", 12, "rear", "orthodox", seed=8, target="body")
    _, events, *_ = _run(s, cal, "rear", "orthodox")
    crosses = [e for e in events[1:] if e["type"] == "cross"]
    assert sum(e["target"] == "body" for e in crosses) >= 0.8 * len(crosses)


# ---------------------------------------------------------------- outputs / schema
def _validate(doc):
    jsonschema = pytest.importorskip("jsonschema")
    if not SCHEMA.exists():
        pytest.skip("docs/session.schema.json not present")
    schema = json.loads(SCHEMA.read_text())
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(doc)


def test_session_json_conforms_to_schema(tmp_path):
    s, cal = synth.make_class_session("hook", 6, "rear", "orthodox", seed=9, hard_frac=0.5)
    s.kick_or_body(19.0)
    acc, gyr, sat, _ = s.render()
    raw = tmp_path / "x_raw.csv"
    synth.write_raw_csv(raw, acc, gyr, sat, 1_792_864_800.0)
    lab = tmp_path / "x_labels.csv"
    synth.write_labels(lab, 1_792_864_800.0, [(cal[0], "cal_start", ""), (cal[1], "cal_end", "")])
    out_json, out_csv = tmp_path / "s.json", tmp_path / "p.csv"
    detector.main([str(raw), "--labels", str(lab), "--hand", "rear", "--session-out", str(out_json),
                   "--punches-out", str(out_csv)])
    doc = json.loads(out_json.read_text())
    _validate(doc)
    assert doc["schema_version"] == "1.0.0"
    with open(out_csv) as fh:
        assert next(csv.reader(fh)) == C.PUNCH_CSV_HEADER
    with open(raw) as fh:
        assert next(csv.reader(fh)) == C.RAW_HEADER


def test_committed_demo_session_is_valid_and_consistent():
    doc = json.loads((SAMPLES / "demo_session.json").read_text())
    _validate(doc)
    rounds = [r for r in doc["rounds"] if r["kind"] == "round"]
    assert len(rounds) == 3
    assert all(170 <= r["t_end_s"] - r["t_start_s"] <= 190 for r in rounds)
    assert doc["summary"]["saturated_sample_fraction"] > 0
    assert any(p["saturated"] and p["type"] == "rear_hook" for p in doc["punches"])
    with open(SAMPLES / "demo_raw.csv") as fh:
        assert next(csv.reader(fh)) == C.RAW_HEADER
    with open(SAMPLES / "demo_labels.csv") as fh:
        assert next(csv.reader(fh)) == C.LABEL_HEADER
    with open(SAMPLES / "demo_punches.csv") as fh:
        assert next(csv.reader(fh)) == C.PUNCH_CSV_HEADER
