#!/usr/bin/env python3
"""Evaluate detector output against synthetic ground truth (per-class recall,
precision, confusion matrix). Used by tests and for tuning.

  python analysis/evaluate.py            # full synthetic benchmark, both hands/stances
"""
from __future__ import annotations

import argparse
import zlib
from collections import Counter, defaultdict

try:
    from . import common as C, synth, detector
except ImportError:
    import common as C
    import synth
    import detector


def match(events, truths, tol_s=0.12):
    """Greedy time matching. Returns list of (truth_type, detected_type or None) and #false positives."""
    used = set()
    pairs = []
    for tr in truths:
        if tr.base == "clap":
            continue
        best, bd = None, None
        for k, e in enumerate(events):
            if k in used:
                continue
            if tr.base == "clinch":
                ok = e["type"] == "clinch" and e["t_start_s"] < tr.t_end_s and e["t_end_s"] > tr.t_s
                d = 0 if ok else None
            else:
                d = abs(e["t_peak_s"] - tr.t_s)
                ok = d <= (0.35 if tr.base == "kick" else tol_s)
            if ok and (bd is None or d < bd):
                best, bd = k, d
        if best is not None:
            used.add(best)
            pairs.append((tr.type, events[best]["type"]))
        else:
            pairs.append((tr.type, None))
    fp = [e for k, e in enumerate(events) if k not in used]
    return pairs, fp


def recall_table(pairs):
    tot, hit = Counter(), Counter()
    conf = defaultdict(Counter)
    for t, d in pairs:
        tot[t] += 1
        hit[t] += int(t == d)
        conf[t][d or "missed"] += 1
    return {t: (hit[t] / tot[t], tot[t], dict(conf[t])) for t in tot}


def run_benchmark(count=40, seeds=(1, 2), verbose=True, jitter_deg=12.0, rot_scale=(0.75, 1.15)):
    pairs_all, fps = [], 0
    for hand in ("lead", "rear"):
        for stance in ("orthodox", "southpaw"):
            for base in synth.BASE_CLASSES + ["kick", "clinch"]:
                for seed in seeds:
                    n = 3 if base == "clinch" else count
                    gap = {"clinch": 8.0, "kick": 2.5}.get(base, 1.2)
                    s, cal = synth.make_class_session(base, n, hand, stance,
                                                      seed=seed * 101 + zlib.crc32(f"{hand}{stance}{base}".encode()) % 997,
                                                      gap=gap, hard_frac=0.3 if base == "hook" else 0.0,
                                                      jitter_deg=jitter_deg, rot_scale=rot_scale)
                    acc, gyr, sat, _ = s.render()
                    rec = detector.Recording(s.t, acc, gyr, sat, 0.0, synth.FS)
                    labels = [(cal[0], "cal_start", ""), (cal[1], "cal_end", ""), (2.5, "sync", "")]
                    p = detector.Params(hand=hand, stance=stance)
                    events, _, _ = detector.analyze(rec, labels, p)
                    pr, fp = match(events, s.truths)
                    pairs_all += pr
                    fps += len(fp)
    table = recall_table(pairs_all)
    if verbose:
        print(f"{'class':24s} recall   n   confusion")
        for t in sorted(table):
            r, n, cm = table[t]
            print(f"{t:24s} {r:6.1%} {n:4d}   {cm}")
        print(f"false positives (unmatched detections): {fps}")
    return table, fps


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--hard", action="store_true",
                    help="stress setting: 25 deg technique jitter, rotation x0.5-1.2")
    a = ap.parse_args()
    if a.hard:
        run_benchmark(a.count, jitter_deg=25.0, rot_scale=(0.5, 1.2))
    else:
        run_benchmark(a.count)
