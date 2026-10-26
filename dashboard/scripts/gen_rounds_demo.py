#!/usr/bin/env python3
"""Multi-round demo session built with the analysis/ tooling, so the Python detector
stays the single source of truth for every event the dashboard shows.

  1. analysis/synth.py primitives (Session.strike/clinch/kick_or_body/footwork, render,
     write_raw_csv/write_labels) synthesise an N x M-minute recording with fatigue:
       * strike amplitude fades across rounds (~3.5 %/round) and within each round (~6 %),
         partly recovering in the rest
       * work rate drops: longer pauses between combos, shorter combos late on
       * fewer hard (clipping) hooks when tired
  2. analysis/detector.py (CLI, unchanged) turns raw + labels into session.json.

  --profile kickboxing-late-fade uses analysis/synth.py make_fatigue_session/FatigueProfile
  instead (10 x 3 min default demo: late-round drop in output, speed, kicks and combos).

Usage (from the repo root, numpy + jsonschema installed):
  python dashboard/scripts/gen_rounds_demo.py --out /tmp/demo6 [--rounds 6 --round-s 120 --rest-s 60 --seed 11]
writes /tmp/demo6_raw.csv, _labels.csv, _session.json, _punches.csv. Not a detector:
it only produces synthetic sensor data and ground-truth labels.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis"))

import numpy as np  # noqa: E402
import synth as S  # noqa: E402
import detector as D  # noqa: E402


FatigueSession = S.FatigueSession  # moved to analysis/synth.py


def make_rounds_demo(seed=11, hand="rear", stance="orthodox", rounds=6, round_s=120.0, rest_s=60.0,
                     fade_round=0.035, fade_within=0.06):
    lead_in = 12.0
    dur = lead_in + rounds * round_s + (rounds - 1) * rest_s + 8.0
    s = FatigueSession(int(dur * S.FS), hand, stance, seed)
    cal = S.calibration_preamble(s)
    r = s.rng
    labels = [(2.5, "sync", "clap"), (cal[0], "cal_start", "hold guard, then one straight"), (cal[1], "cal_end", "")]
    mix = ["straight"] * 40 + ["hook"] * 28 + ["uppercut"] * 14 + ["overhand"] * 8 + ["spinning_backfist"] * 3
    t = lead_in
    for k in range(rounds):
        t0, t1 = t, t + round_s
        labels += [(t0, "round", f"round {k+1} start"), (t1, "rest", f"round {k+1} end")]
        s.footwork(t0, t1)
        busy = []
        if r.random() < 0.7:
            ca = t0 + r.uniform(30, round_s - 25)
            s.clinch(ca, r.uniform(5, 9))
            busy.append((ca - 1, ca + 10))
        for _ in range(2):
            kt = t0 + r.uniform(8, round_s - 8)
            if not any(a <= kt <= b for a, b in busy):
                s.kick_or_body(kt)
                busy.append((kt - 0.6, kt + 0.6))
        start_f = 1.0 - fade_round * k
        pause_scale = 1.0 + 0.09 * k
        max_combo = 5 if k < 3 else 4
        tt = t0 + 2.0
        while tt < t1 - 2:
            prog = (tt - t0) / round_s
            s.f = start_f * (1.0 - fade_within * prog) * r.uniform(0.94, 1.04)
            for _ in range(int(r.integers(1, max_combo))):
                if not any(a <= tt <= b for a, b in busy):
                    base = mix[int(r.integers(len(mix)))]
                    tg = "body" if base in ("straight", "hook") and r.random() < 0.25 else None
                    s.strike(tt, base, target=tg, hard=(base == "hook" and r.random() < 0.35 * s.f))
                tt += r.uniform(0.3, 0.5) * (1 + 0.04 * k)
            tt += r.uniform(1.5, 4.0) * pause_scale
        t = t1 + rest_s
    for tr in s.truths:
        if tr.base == "clap":
            continue
        note = "synthetic ground truth" + (f"; target={tr.target}" if tr.target else "")
        if tr.base == "clinch":
            labels += [(tr.t_s, "clinch_start", note), (tr.t_end_s, "clinch_end", note)]
        else:
            labels.append((tr.t_s, f"truth:{tr.type}", note))
    return s, labels


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="output prefix")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--round-s", type=float, default=120.0)
    ap.add_argument("--rest-s", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--hand", default="rear", choices=["lead", "rear"])
    ap.add_argument("--stance", default="orthodox", choices=["orthodox", "southpaw"])
    ap.add_argument("--date", default="2026-10-25T18:00:00+00:00")
    ap.add_argument("--id", default=None)
    ap.add_argument("--two-hands", action="store_true",
                    help="two sensors (one per wrap): writes <out>_lead_raw.csv, <out>_rear_raw.csv and "
                         "<out>_sync.csv with per-device clock offset + drift, merged by detector.py --stream")
    ap.add_argument("--profile", default="fade6", choices=["fade6", "kickboxing-late-fade"],
                    help="fade6: the original 6-round demo; kickboxing-late-fade: synth.make_fatigue_session "
                         "(gentle fade + late-round drop in output, speed, kicks and combos)")
    a = ap.parse_args(argv)
    if a.two_hands:
        return two_hands(a)
    if a.profile == "kickboxing-late-fade":
        s, labels = S.make_fatigue_session(a.seed, a.hand, a.stance, a.rounds, a.round_s, a.rest_s)
    else:
        s, labels = make_rounds_demo(a.seed, a.hand, a.stance, a.rounds, a.round_s, a.rest_s)
    acc, gyr, sat, _ = s.render()
    host_t0 = datetime.fromisoformat(a.date).astimezone(timezone.utc).timestamp()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    S.write_raw_csv(f"{out}_raw.csv", acc, gyr, sat, host_t0)
    S.write_labels(f"{out}_labels.csv", host_t0, labels)
    print(f"synth: {len(acc)} samples, {sat.mean()*100:.3f}% saturated, {sum(1 for x in labels if x[1].startswith('truth:'))} truth strikes")
    D.main([f"{out}_raw.csv", "--labels", f"{out}_labels.csv", "--hand", a.hand, "--stance", a.stance,
            "--session-out", f"{out}_session.json", "--punches-out", f"{out}_punches.csv", "--id", a.id or out.name])


# Per-device clocks for the two-sensor demo: different counters, +23 / -17.5 ppm drift,
# the lead sensor starts logging 0.37 s after the rear one.
CLOCKS = {"lead": S.DeviceClock(dev_t0_us=3_812_004_117, skew_ppm=23.0, start_s=0.37),
          "rear": S.DeviceClock(dev_t0_us=1_204_556_001, skew_ppm=-17.5, start_s=0.0)}
DEVICE_IDS = {"lead": "boxtrk-lead-7c1e", "rear": "boxtrk-rear-a94b"}


def two_hands(a):
    import csv
    sessions, labels = S.make_two_hand_fatigue_session(a.seed, a.stance, a.rounds, a.round_s, a.rest_s)
    host_t0 = datetime.fromisoformat(a.date).astimezone(timezone.utc).timestamp()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(a.seed + 99)
    sync = []
    streams = []
    for role, s in sessions.items():
        acc, gyr, sat, _ = s.render()
        S.write_raw_csv_clock(f"{out}_{role}_raw.csv", acc, gyr, sat, host_t0, CLOCKS[role], rng)
        sync += S.sync_rows(DEVICE_IDS[role], role, CLOCKS[role], host_t0, len(acc) / S.FS, rng)
        streams += ["--stream", f"{role}={out}_{role}_raw.csv@{DEVICE_IDS[role]}"]
        print(f"synth {role}: {len(acc)} samples, {sat.mean()*100:.3f}% saturated")
    with open(f"{out}_sync.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(S.SYNC_HEADER)
        w.writerows(sorted(sync, key=lambda r: float(r[2])))
    S.write_labels(f"{out}_labels.csv", host_t0, labels)
    print(f"{sum(1 for x in labels if x[1].startswith('truth:'))} truth events")
    return D.main([*streams, "--sync", f"{out}_sync.csv", "--labels", f"{out}_labels.csv", "--stance", a.stance,
                   "--session-out", f"{out}_session.json", "--punches-out", f"{out}_punches.csv", "--id", a.id or out.name])


if __name__ == "__main__":
    main()
