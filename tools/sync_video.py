#!/usr/bin/env python3
"""Align phone-video timestamps with an IMU recording using the sync clap.

Convention: at the start of every recording, with the tracker on the wrist,
clap hands (or slap the sensor hand on a pad) sharply ONCE, in view of the
camera. It shows up as an isolated spike > ~6 g in the IMU and as an audio
transient / visible contact frame in the video.

  python tools/sync_video.py rec1_raw.csv --video-clap 3.47
      -> prints offset; host_time = video_time + offset
  python tools/sync_video.py rec1_raw.csv --video-clap 3.47 --video-labels vid.csv --out rec1_labels.csv
      vid.csv: video_time_s,label,note   (e.g. exported from a video annotator)
"""
from __future__ import annotations

import argparse
import csv
import math
import sys


def find_clap(raw_csv: str, min_g: float = 6.0, search_s: float = 30.0) -> float:
    """host_time_s of the first sharp spike (|a|-1g >= min_g) in the first search_s seconds."""
    with open(raw_csv, newline="") as fh:
        r = csv.DictReader(fh)
        t0 = None
        for row in r:
            t = float(row["host_time_s"])
            t0 = t if t0 is None else t0
            if t - t0 > search_s:
                break
            a = math.sqrt(sum(float(row[k]) ** 2 for k in ("ax_g", "ay_g", "az_g"))) - 1.0
            if a >= min_g:
                return t
    raise SystemExit(f"no spike >= {min_g} g in the first {search_s} s")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw_csv")
    ap.add_argument("--video-clap", type=float, required=True, help="clap time in the video (s)")
    ap.add_argument("--min-g", type=float, default=6.0)
    ap.add_argument("--video-labels")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    t_clap = find_clap(a.raw_csv, a.min_g)
    offset = t_clap - a.video_clap
    print(f"IMU clap at host_time_s={t_clap:.3f}; offset={offset:.3f} s (host = video + offset)")
    if a.video_labels:
        out = open(a.out, "w", newline="") if a.out else sys.stdout
        w = csv.writer(out)
        w.writerow(["host_time_s", "label", "note"])
        w.writerow([f"{t_clap:.6f}", "sync", "imu clap"])
        with open(a.video_labels, newline="") as fh:
            for row in csv.DictReader(fh):
                w.writerow([f"{float(row['video_time_s']) + offset:.6f}", row["label"], row.get("note", "")])
    return offset


if __name__ == "__main__":
    main()
