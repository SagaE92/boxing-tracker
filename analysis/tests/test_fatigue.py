"""Late-round fade in the synthetic kickboxing session (synth.make_fatigue_session), checked
both on the ground truth and after analysis/detector.py, plus the shipped 10 x 3 min demo."""
import json
from pathlib import Path

import numpy as np
import pytest

import detector
import synth

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "dashboard" / "public" / "demo" / "demo-10x3_session.json"
STRIKES = ("jab", "cross", "lead_hook", "rear_hook", "lead_uppercut", "rear_uppercut", "overhand",
           "spinning_backfist", "unknown")


def test_profile_is_monotonic_and_late_rounds_are_harder():
    pf = synth.FatigueProfile()
    amps = [pf.amp(k) for k in range(10)]
    assert all(a > b for a, b in zip(amps, amps[1:]))
    assert [pf.late(k) for k in range(10)] == [0] * 7 + [1, 2, 3]
    assert pf.kicks(9) < pf.kicks(0) and pf.max_combo(9) < pf.max_combo(0)
    assert pf.pause(9) > pf.pause(0)


def _per_round(events, rounds):
    out = []
    for r in [x for x in rounds if x["kind"] == "round"]:
        ev = [e for e in events if r["t_start_s"] <= e["t_peak_s"] < r["t_end_s"]]
        st = [e for e in ev if e["type"] in STRIKES]
        sp = [e["speed_mps_est"] for e in st if e["speed_mps_est"] is not None]
        out.append({"n": len(st), "kicks": sum(e["type"] == "kick_or_body_movement" for e in ev),
                    "peak": float(np.mean([e["peak_g"] for e in st])), "speed": float(np.mean(sp))})
    return out


@pytest.fixture(scope="module")
def short_session():
    # 10 x 90 s keeps the test fast; the fade parameters are per round, not per second.
    s, labels = synth.make_fatigue_session(seed=5, rounds=10, round_s=90.0, rest_s=8.0)
    acc, gyr, sat, _ = s.render()
    rec = detector.Recording(s.t, acc, gyr, sat, 1_792_864_800.0, synth.FS)
    events, _, _ = detector.analyze(rec, labels, detector.Params(hand="rear", stance="orthodox"))
    # per-round windows from the synthetic bell labels (detector round segmentation is tested elsewhere)
    starts = sorted(t for t, lab, _ in labels if lab == "round")
    ends = sorted(t for t, lab, _ in labels if lab == "rest")
    rounds = [{"kind": "round", "t_start_s": a, "t_end_s": b} for a, b in zip(starts, ends)]
    return s, labels, {"punches": events, "rounds": rounds}


def test_truth_fades_late(short_session):
    s, labels, _ = short_session
    starts = sorted(t for t, lab, _ in labels if lab == "round")
    ends = sorted(t for t, lab, _ in labels if lab == "rest")
    per = []
    for a, b in zip(starts, ends):
        tr = [x for x in s.truths if a <= x.t_s < b]
        st = [x for x in tr if x.base not in ("kick", "clinch", "clap")]
        per.append((len(st), sum(x.base == "kick" for x in tr), np.mean([x.amp_g for x in st])))
    first, last = per[:3], per[-3:]
    assert sum(p[0] for p in last) < 0.9 * sum(p[0] for p in first)        # lower output
    assert sum(p[1] for p in last) < sum(p[1] for p in first)              # fewer kicks
    assert np.mean([p[2] for p in last]) < 0.92 * np.mean([p[2] for p in first])  # weaker strikes


def test_detector_sees_the_fade(short_session):
    _, _, doc = short_session
    pr = _per_round(doc["punches"], doc["rounds"])
    assert len(pr) == 10
    f, l = pr[:3], pr[-3:]
    assert np.mean([r["peak"] for r in l]) < 0.92 * np.mean([r["peak"] for r in f])
    assert np.mean([r["speed"] for r in l]) < 0.95 * np.mean([r["speed"] for r in f])
    assert sum(r["kicks"] for r in l) < sum(r["kicks"] for r in f)


@pytest.mark.skipif(not DEMO.exists(), reason="demo not generated (npm run demo:data)")
def test_shipped_demo_has_late_round_fade():
    doc = json.loads(DEMO.read_text())
    pr = _per_round(doc["punches"], doc["rounds"])
    assert len(pr) == 10
    f, l = pr[:3], pr[-3:]
    assert sum(r["n"] for r in l) < 0.85 * sum(r["n"] for r in f)
    assert np.mean([r["speed"] for r in l]) < 0.9 * np.mean([r["speed"] for r in f])
    assert np.mean([r["peak"] for r in l]) < 0.9 * np.mean([r["peak"] for r in f])
    assert sum(r["kicks"] for r in l) < sum(r["kicks"] for r in f)
