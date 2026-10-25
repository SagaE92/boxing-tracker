#!/usr/bin/env python3
"""Offline strike detector + rule-based classifier for boxing-tracker raw CSVs.

  python analysis/detector.py rec_raw.csv --labels rec_labels.csv --hand rear \
      --stance orthodox --punches-out rec_punches.csv --session-out rec_session.json

Pipeline (see analysis/README.md):
 1. load CSV (device clock; t = (device_time_us - first) / 1e6)
 2. calibration: guard pose (mean gravity, sensor frame) + first straight punch
    (forward axis) -> rotation into the calibrated frame x=forward, y=left, z=up
    (docs/axes.md). Uses cal_start/cal_end labels if present, else automatic.
 3. strike detection on dyn = |a| - 1 g: threshold (3.5 g), refractory (150 ms),
    peak search, +-150 ms feature window
 4. features (peak g, gyro integrals and peak rates in the calibrated frame,
    rotation axis, rotational/linear ratio, linear direction at peak, duration,
    pre-strike gravity / orientation)
 5. rule-based classification -> v1 taxonomy, target (head/body), confidence
 6. non-strike events: kick_or_body_movement (big rotation without a strike
    peak), clinch (sustained low-amplitude activity with frequent rotations)
 7. rounds/rests from activity gaps; summary; session.json (docs/session.schema.json)

THE CLASSIFIER IS A STARTING HEURISTIC tuned on synthetic data (analysis/synth.py),
not validated on real punches. Assumptions: sensor on the back of the wrist
inside the hand wrap; `--hand` says which hand wears it, `--stance` maps that to
the left/right wrist. Saturated windows (|a| clipped at +-16 g) report peak_g as
a lower bound and `saturated: true`.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import numpy as np

try:
    from . import common as C
except ImportError:
    import common as C

GENERATOR_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0.0"


# --------------------------------------------------------------------------- data
@dataclass
class Recording:
    t: np.ndarray        # s from first sample (device clock)
    acc: np.ndarray      # g, sensor frame
    gyr: np.ndarray      # dps, sensor frame
    sat: np.ndarray      # bool per sample (logger flag)
    host_t0: float       # host_time_s of first sample
    fs: float

    @property
    def n(self):
        return len(self.t)


def load_raw(path) -> Recording:
    data = np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8")
    dev = data["device_time_us"].astype(np.int64)
    # unwrap 32-bit wrap (the logger already unwraps; harmless otherwise)
    d = np.diff(dev)
    wraps = np.concatenate([[0], np.cumsum(d < -(1 << 31))])
    dev = dev + wraps * (1 << 32)
    t = (dev - dev[0]) / 1e6
    acc = np.stack([data["ax_g"], data["ay_g"], data["az_g"]], 1).astype(float)
    gyr = np.stack([data["gx_dps"], data["gy_dps"], data["gz_dps"]], 1).astype(float)
    sat = data["sat"].astype(bool)
    fs = (len(t) - 1) / t[-1] if t[-1] > 0 else C.ODR_HZ
    return Recording(t, acc, gyr, sat, float(data["host_time_s"][0]), float(fs))


def load_labels(path, host_t0) -> list:
    out = []
    if not path:
        return out
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            out.append((float(row["host_time_s"]) - host_t0, row["label"].strip(), row.get("note", "")))
    return sorted(out)


# --------------------------------------------------------------------------- params
@dataclass
class Params:
    threshold_g: float = 3.5
    refractory_ms: float = 150.0
    window_ms: float = 150.0
    hand: str = "rear"
    stance: str = "orthodox"
    guard_s: float = 1.5
    auto_cal_search_s: float = 30.0
    rest_gap_s: float = 20.0
    min_round_s: float = 20.0


@dataclass
class Calibration:
    rot: np.ndarray                  # 3x3, calibrated = rot @ sensor
    gravity_g: list
    forward: list
    t_start_s: float
    t_end_s: float
    cal_peak_idx: Optional[int]
    ok: bool


# --------------------------------------------------------------------------- helpers
def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def dyn_g(acc):
    return np.linalg.norm(acc, axis=1) - 1.0


def find_peaks(dyn, t, p: Params, start_idx=0, stop_idx=None):
    """Threshold + refractory + peak search. Returns list of (i_peak, i_lo, i_hi)."""
    stop_idx = len(dyn) if stop_idx is None else stop_idx
    fs = 1.0 / np.median(np.diff(t[: min(len(t), 2000)]))
    win = int(p.window_ms / 1000 * fs)
    refr = int(p.refractory_ms / 1000 * fs)
    above = np.flatnonzero(dyn[start_idx:stop_idx] >= p.threshold_g) + start_idx
    peaks = []
    nxt = start_idx
    k = 0
    while k < len(above):
        i = above[k]
        if i < nxt:
            k += 1
            continue
        j = i
        lo_lvl = 0.5 * p.threshold_g
        while j < min(len(dyn), i + 2 * win) and dyn[j] >= lo_lvl:
            j += 1
        seg = slice(i, max(j, i + 1))
        ip = i + int(np.argmax(dyn[seg]))
        peaks.append(ip)
        nxt = max(j, ip + refr)
        k += 1
    out = []
    for ip in peaks:
        lo, hi = max(0, ip - win), min(len(dyn), ip + win + 1)
        out.append((ip, lo, hi))
    return out


def event_bounds(dyn, ip, lo, hi, level):
    a = ip
    while a > lo and dyn[a - 1] >= level:
        a -= 1
    b = ip
    while b < hi - 1 and dyn[b + 1] >= level:
        b += 1
    return a, b


# --------------------------------------------------------------------------- calibration
def _quiet_mask(rec):
    m = np.abs(np.linalg.norm(rec.acc, axis=1) - 1.0) < 0.08
    m &= np.linalg.norm(rec.gyr, axis=1) < 30.0
    return m


def calibrate(rec: Recording, labels, p: Params) -> Calibration:
    dyn = dyn_g(rec.acc)
    fs = rec.fs
    gN = int(p.guard_s * fs)
    quiet = _quiet_mask(rec)
    lab = {l: t for t, l, _ in labels if l in ("cal_start", "cal_end")}
    if "cal_start" in lab:
        t0 = lab["cal_start"]
        t1 = lab.get("cal_end", t0 + 10.0)
    else:
        t0, t1 = 0.0, p.auto_cal_search_s
    i0, i1 = np.searchsorted(rec.t, [t0, t1])
    # quiet run cumulative sums
    qc = np.concatenate([[0], np.cumsum(quiet.astype(int))])
    peaks = find_peaks(dyn, rec.t, p, i0, i1)
    for ip, lo, hi in peaks:
        a, b = event_bounds(dyn, ip, lo, hi, 0.25 * p.threshold_g)
        dur_ms = (b - a) / fs * 1000
        if dur_ms < 40:          # sync clap / tap: too impulsive to be a punch
            continue
        # need a guard window: gN quiet samples ending within 1.2 s before the strike
        g_end = None
        for e in range(a - int(0.1 * fs), max(i0 + gN, a - int(1.2 * fs)), -int(0.05 * fs)):
            if e - gN >= 0 and qc[e] - qc[e - gN] >= 0.95 * gN:
                g_end = e
                break
        if g_end is None:
            continue
        gvec = rec.acc[g_end - gN:g_end].mean(0)
        up = _unit(gvec)
        lin = rec.acc[ip] - gvec
        fwd = _unit(lin - np.dot(lin, up) * up)
        left = np.cross(up, fwd)
        rot = np.stack([fwd, left, up])
        return Calibration(rot, gvec.round(4).tolist(), fwd.round(4).tolist(),
                           float(rec.t[g_end - gN]), float(rec.t[min(hi, rec.n - 1)]), ip, True)
    # fallback: identity (sensor frame), low confidence
    return Calibration(np.eye(3), [0.0, 0.0, 1.0], [1.0, 0.0, 0.0], 0.0, 0.0, None, False)


# --------------------------------------------------------------------------- features
@dataclass
class Features:
    peak_g: float
    saturated: bool
    gyro_saturated: bool
    t_start: float
    t_end: float
    duration_ms: float
    speed_mps_est: float
    gyro_int: list           # deg, calibrated frame [roll(x), pitch(y), yaw(z)]
    gyro_int_long: list      # deg over [-400, +150] ms (for spins)
    peak_rate: list          # max |w| per calibrated axis, dps
    rot_axis: list
    rot_lin_ratio: float
    lin_dir: list            # unit, calibrated frame, accel at peak minus pre-strike gravity
    elev_deg: float
    pre_pitch_deg: float


def features(rec: Recording, cal: Calibration, dyn, ip, lo, hi, p: Params) -> Features:
    fs, dt = rec.fs, 1.0 / rec.fs
    R = cal.rot
    w = rec.gyr[lo:hi] @ R.T
    gint = w.sum(0) * dt
    # long, mostly pre-peak window to capture whole-body spins
    wl = rec.gyr[max(0, ip - int(0.4 * fs)):min(rec.n, ip + int(0.15 * fs))] @ R.T
    gint_long = wl.sum(0) * dt
    a, b = event_bounds(dyn, ip, lo, hi, 0.25 * p.threshold_g)
    pre0, pre1 = max(0, a - int(0.25 * fs)), max(1, a - int(0.08 * fs))
    gpre = rec.acc[pre0:pre1].mean(0) if pre1 > pre0 else R.T @ np.array([0, 0, 1.0])
    lin_s = rec.acc[ip] - gpre
    lin_c = _unit(R @ lin_s)
    elev = math.degrees(math.asin(max(-1.0, min(1.0, lin_c[2]))))
    gpre_c = _unit(R @ gpre)
    pre_pitch = math.degrees(math.asin(max(-1.0, min(1.0, gpre_c[0]))))
    v = float(np.clip(dyn[a:ip + 1], 0, None).sum() * dt * 9.81)
    lin_imp = float(np.clip(dyn[lo:hi], 0, None).sum() * dt * 9.81)
    rot_rad = float(np.linalg.norm(gint) * math.pi / 180)
    ratio = rot_rad * 0.3 / lin_imp if lin_imp > 1e-6 else 0.0
    sat_acc = bool(rec.sat[lo:hi].any() and (np.abs(rec.acc[lo:hi]) >= C.ACCEL_SAT_RAW * C.ACCEL_G_PER_LSB).any())
    sat_gyr = bool((np.abs(rec.gyr[lo:hi]) >= C.GYRO_SAT_RAW * C.GYRO_DPS_PER_LSB).any())
    if rec.sat[lo:hi].any() and not (sat_acc or sat_gyr):
        sat_acc = True  # trust the logger flag
    return Features(
        peak_g=float(dyn[ip]), saturated=sat_acc, gyro_saturated=sat_gyr,
        t_start=float(rec.t[a]), t_end=float(rec.t[b]), duration_ms=float((b - a) * dt * 1000),
        speed_mps_est=v, gyro_int=gint.tolist(), gyro_int_long=gint_long.tolist(),
        peak_rate=np.abs(w).max(0).tolist(), rot_axis=_unit(gint).tolist(),
        rot_lin_ratio=ratio, lin_dir=lin_c.tolist(), elev_deg=elev, pre_pitch_deg=pre_pitch)


# --------------------------------------------------------------------------- classifier
def classify(f: Features, hand_worn: str, calibrated: bool):
    """Rule-based starting heuristic. Returns (base_class, confidence, target).

    Sign convention (calibrated frame, docs/axes.md): x forward, y left, z up;
    rotation sign by the right-hand rule. For a RIGHT-wrist sensor a hook sweeps
    the fist to the left: yaw (wz) > 0 and linear y > 0. Left wrist: mirrored.
    Uppercut: forearm pitches up (wy < 0) with upward linear accel.
    Overhand: forearm pitches down (wy > 0), accel forward-down.
    Spinning backfist: large yaw opposite to the hook direction (whole-body spin).
    """
    h = 1.0 if hand_worn == "R" else -1.0
    roll, pitch, yaw = f.gyro_int
    yaw_h = yaw * h
    yaw_long_h = f.gyro_int_long[2] * h
    lx, ly, lz = f.lin_dir
    ly_h = ly * h
    sq = lambda x: max(0.0, min(1.0, x))  # noqa: E731

    if yaw_long_h <= -150 and abs(yaw_long_h) > 1.5 * abs(f.gyro_int_long[1]):
        base, conf = "spinning_backfist", 0.5 + 0.5 * sq((-yaw_long_h - 150) / 150)
    elif abs(pitch) >= 40 and abs(pitch) > abs(yaw):
        if pitch < 0 and lz > 0.3:
            base, conf = "uppercut", 0.5 + 0.5 * sq((-pitch - 40) / 50) * sq(lz / 0.8)
        elif pitch > 0 and lz < 0:
            base, conf = "overhand", 0.5 + 0.5 * sq((pitch - 40) / 50) * sq(-lz / 0.6)
        else:
            base, conf = "unknown", 0.2
    elif yaw_h >= 45 and ly_h > 0.3:
        # gyro first: rotation dominates, linear sideways component confirms
        base = "hook"
        conf = 0.5 + 0.5 * sq((yaw_h - 45) / 60) * sq((ly_h - 0.3) / 0.4) * sq(f.rot_lin_ratio / 0.3)
    elif lx > 0.6 and abs(yaw) < 45 and abs(pitch) < 45:
        base, conf = "straight", 0.5 + 0.5 * sq((lx - 0.6) / 0.3) * sq((45 - abs(yaw)) / 30)
    else:
        base, conf = "unknown", 0.2

    target = None
    if base in ("straight", "hook"):
        target = "body" if f.elev_deg < -20 else "head"
    elif base in ("overhand", "spinning_backfist"):
        target = "head"
    if not calibrated:
        conf *= 0.5
    if f.saturated:
        conf *= 0.9  # clipped peak distorts the linear direction
    return base, round(float(conf), 3), target


# --------------------------------------------------------------------------- non-strike events
def detect_clinch(rec: Recording, dyn, strike_peaks_t, min_s=4.0):
    """Sustained close-range activity: moderate dyn accel + frequent small rotations."""
    fs = rec.fs
    W = int(1.0 * fs)
    step = int(0.5 * fs)
    gm = np.linalg.norm(rec.gyr, axis=1)
    flags = []
    for s in range(0, rec.n - W, step):
        sl = slice(s, s + W)
        d_sd = float(np.std(dyn[sl]))
        g_rms = float(np.sqrt(np.mean(gm[sl] ** 2)))
        g0 = rec.gyr[sl, :] - rec.gyr[sl, :].mean(0)
        zc = int((np.diff(np.sign(g0), axis=0) != 0).sum()) / 3.0  # crossings per axis per s
        flags.append(0.12 <= d_sd <= 1.2 and 40 <= g_rms <= 300 and zc >= 6
                     and float(dyn[sl].max()) < 3.0)
    events = []
    k = 0
    while k < len(flags):
        if flags[k]:
            j = k
            while j < len(flags) and flags[j]:
                j += 1
            t0, t1 = k * step / fs, ((j - 1) * step + W) / fs
            if t1 - t0 >= min_s:
                i0, i1 = int(t0 * fs), min(rec.n, int(t1 * fs))
                ip = i0 + int(np.argmax(dyn[i0:i1]))
                events.append((t0, t1, ip))
            k = j
        else:
            k += 1
    return events


def detect_body_rotation(rec: Recording, dyn, strike_idx, clinches, p: Params):
    """Whole-body rotation / arm swing without a strike peak -> kick_or_body_movement."""
    fs = rec.fs
    k = int(0.05 * fs)
    gm = np.convolve(np.linalg.norm(rec.gyr, axis=1), np.ones(k) / k, "same")
    above = gm >= 220.0
    events = []
    i = 0
    strike_idx = np.asarray(sorted(strike_idx))
    refr = int(0.8 * fs)  # the return rotation belongs to the same movement
    last = -10 ** 9
    while i < rec.n:
        if above[i]:
            j = i
            while j < rec.n and above[j]:
                j += 1
            if (j - i) / fs >= 0.15:
                ip = i + int(np.argmax(gm[i:j]))
                t = rec.t[ip]
                near = strike_idx.size and np.min(np.abs(strike_idx - ip)) < int(0.6 * fs)
                in_cl = any(a - 0.5 <= t <= b + 0.5 for a, b, _ in clinches)
                if not near and not in_cl and dyn[i:j].max() < p.threshold_g and i - last > refr:
                    events.append((i, j, ip))
                    last = j
            i = j
        else:
            i += 1
    return events


# --------------------------------------------------------------------------- rounds
def segment_rounds(rec: Recording, dyn, t_from: float, p: Params):
    fs = rec.fs
    W = int(fs)
    nW = rec.n // W
    gm = np.linalg.norm(rec.gyr, axis=1)
    act = np.array([np.std(dyn[k * W:(k + 1) * W]) > 0.06 or
                    np.sqrt(np.mean(gm[k * W:(k + 1) * W] ** 2)) > 12 for k in range(nW)])
    k0 = int(math.ceil(t_from))
    act[:k0] = False
    idx = np.flatnonzero(act)
    if idx.size == 0:
        return []
    spans = []
    s = e = idx[0]
    for k in idx[1:]:
        if k - e - 1 >= p.rest_gap_s:
            spans.append((s, e + 1))
            s = k
        e = k
    spans.append((s, e + 1))
    spans = [(a, b) for a, b in spans if b - a >= p.min_round_s]
    rounds = []
    for n, (a, b) in enumerate(spans):
        if n > 0:
            rounds.append({"t_start_s": float(spans[n - 1][1]), "t_end_s": float(a), "kind": "rest"})
        rounds.append({"t_start_s": float(a), "t_end_s": float(min(b, rec.t[-1])), "kind": "round"})
    for i, r in enumerate(rounds):
        r["index"] = i
    return [{"index": r["index"], "t_start_s": r["t_start_s"], "t_end_s": r["t_end_s"],
             "kind": r["kind"]} for r in rounds]


# --------------------------------------------------------------------------- main analysis
def analyze(rec: Recording, labels=None, p: Optional[Params] = None, session_id="session"):
    p = p or Params()
    labels = labels or []
    hw = C.hand_worn(p.hand, p.stance)
    dyn = dyn_g(rec.acc)
    cal = calibrate(rec, labels, p)
    t_skip = cal.t_end_s if cal.ok else 0.0
    sync_t = [t for t, l, _ in labels if l == "sync"]

    events = []
    peaks = find_peaks(dyn, rec.t, p)
    strike_idx = []
    for ip, lo, hi in peaks:
        t = rec.t[ip]
        if cal.ok and ip == cal.cal_peak_idx:
            pass  # the calibration straight counts as a strike
        elif t < t_skip or any(abs(t - s) < 0.3 for s in sync_t):
            continue
        f = features(rec, cal, dyn, ip, lo, hi, p)
        if cal.ok and ip == cal.cal_peak_idx:
            base, conf, target = "straight", 1.0, ("body" if f.elev_deg < -20 else "head")
        else:
            base, conf, target = classify(f, hw, cal.ok)
        strike_idx.append(ip)
        events.append({
            "t_peak_s": float(t), "t_start_s": f.t_start, "t_end_s": f.t_end,
            "type": C.resolve_type(base, p.hand), "confidence": conf, "target": target,
            "hand": hw, "peak_g": round(f.peak_g, 3), "speed_mps_est": round(f.speed_mps_est, 3),
            "duration_ms": round(f.duration_ms, 1),
            "gyro_int_dps_s": [round(x, 2) for x in f.gyro_int],
            "saturated": f.saturated, "_features": asdict(f)})

    clinches = [c for c in detect_clinch(rec, dyn, [e["t_peak_s"] for e in events]) if c[0] >= t_skip]
    for t0, t1, ip in clinches:
        i0, i1 = np.searchsorted(rec.t, [t0, t1])
        gi = (rec.gyr[i0:i1] @ cal.rot.T).sum(0) / rec.fs
        events.append({
            "t_peak_s": float(rec.t[ip]), "t_start_s": float(t0), "t_end_s": float(t1),
            "type": "clinch", "confidence": 0.3, "target": None, "hand": None,
            "peak_g": round(float(max(0.0, dyn[ip])), 3), "speed_mps_est": None,
            "duration_ms": round((t1 - t0) * 1000, 1), "gyro_int_dps_s": [round(x, 2) for x in gi],
            "saturated": bool(rec.sat[i0:i1].any())})
    for i, j, ip in detect_body_rotation(rec, dyn, strike_idx, clinches, p):
        if rec.t[ip] < t_skip:
            continue
        gi = (rec.gyr[i:j] @ cal.rot.T).sum(0) / rec.fs
        events.append({
            "t_peak_s": float(rec.t[ip]), "t_start_s": float(rec.t[i]), "t_end_s": float(rec.t[j - 1]),
            "type": "kick_or_body_movement", "confidence": 0.3, "target": None, "hand": None,
            "peak_g": round(float(max(0.0, dyn[i:j].max())), 3), "speed_mps_est": None,
            "duration_ms": round((j - i) / rec.fs * 1000, 1),
            "gyro_int_dps_s": [round(x, 2) for x in gi], "saturated": bool(rec.sat[i:j].any())})

    events.sort(key=lambda e: e["t_peak_s"])
    rounds = segment_rounds(rec, dyn, t_skip, p)
    for k, e in enumerate(events):
        e["id"] = k
        e["round_index"] = next((r["index"] for r in rounds if r["kind"] == "round"
                                 and r["t_start_s"] <= e["t_peak_s"] <= r["t_end_s"]), None)
    return events, rounds, cal


def summarize(rec, events, rounds):
    strikes = [e for e in events if e["type"] not in C.NON_STRIKE_TYPES]
    round_list = [r for r in rounds if r["kind"] == "round"]
    active_s = sum(r["t_end_s"] - r["t_start_s"] for r in round_list) or float(rec.t[-1])
    peaks = [e["peak_g"] for e in strikes]
    speeds = [e["speed_mps_est"] for e in strikes if e["speed_mps_est"] is not None]
    by_type = {k: 0 for k in C.ALL_TYPES}
    for e in events:
        by_type[e["type"]] += 1
    by_hand = {"L": 0, "R": 0, "unknown": 0}
    by_target = {"head": 0, "body": 0, "unknown": 0}
    for e in strikes:
        by_hand[e["hand"] or "unknown"] += 1
        by_target[e["target"] or "unknown"] += 1
    r2 = lambda x: None if x is None else round(float(x), 3)  # noqa: E731
    return {
        "punch_count": len(strikes),
        "punches_per_min": round(len(strikes) / (active_s / 60.0), 2) if active_s > 0 else 0.0,
        "punches_per_round": [sum(1 for e in strikes if e["round_index"] == r["index"]) for r in round_list],
        "mean_peak_g": r2(np.mean(peaks)) if peaks else None,
        "max_peak_g": r2(max(peaks)) if peaks else None,
        "mean_speed_mps_est": r2(np.mean(speeds)) if speeds else None,
        "max_speed_mps_est": r2(max(speeds)) if speeds else None,
        "by_type": by_type,
        "by_hand": by_hand,
        "saturated_sample_fraction": round(float(rec.sat.mean()), 6),
        "non_punch_count": len(events) - len(strikes),
        "by_target": by_target,
        "saturated_punch_count": sum(1 for e in strikes if e["saturated"]),
        "clinch_time_s": round(sum(e["t_end_s"] - e["t_start_s"] for e in events if e["type"] == "clinch"), 2),
    }


def session_doc(rec, events, rounds, cal, p: Params, session_id: str):
    clean = [{k: v for k, v in e.items() if not k.startswith("_")} for e in events]
    order = ["id", "t_peak_s", "t_start_s", "t_end_s", "type", "confidence", "target", "hand",
             "peak_g", "speed_mps_est", "duration_ms", "gyro_int_dps_s", "saturated", "round_index"]
    clean = [{k: e[k] for k in order} for e in clean]
    for e in clean:
        for k in ("t_peak_s", "t_start_s", "t_end_s"):
            e[k] = round(max(0.0, e[k]), 4)
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": {"name": "analysis/detector.py", "version": GENERATOR_VERSION},
        "session": {
            "id": session_id,
            "start_time_iso": datetime.fromtimestamp(rec.host_t0, tz=timezone.utc).isoformat(),
            "duration_s": round(float(rec.t[-1]), 3),
            "sample_rate_hz": round(rec.fs, 2),
            "accel_range_g": C.ACCEL_RANGE_G,
            "gyro_range_dps": C.GYRO_RANGE_DPS,
            "hand_worn": C.hand_worn(p.hand, p.stance),
            "hand": p.hand,
            "stance": p.stance,
            "sensor_mount": "hand_wrap",
            "calibration": ({"guard_gravity_g": cal.gravity_g, "forward_axis": cal.forward,
                             "t_start_s": round(cal.t_start_s, 3), "t_end_s": round(cal.t_end_s, 3)}
                            if cal.ok else None),
        },
        "detector_params": {"threshold_g": p.threshold_g, "refractory_ms": p.refractory_ms,
                            "window_ms": p.window_ms},
        "rounds": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()} for r in rounds],
        "punches": clean,
        "summary": summarize(rec, events, rounds),
    }


def write_punches_csv(path, events):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(C.PUNCH_CSV_HEADER)
        for e in events:
            gi = e["gyro_int_dps_s"]
            w.writerow([e["id"], f"{e['t_peak_s']:.4f}", f"{e['t_start_s']:.4f}", f"{e['t_end_s']:.4f}",
                        e["type"], f"{e['peak_g']:.3f}",
                        "" if e["speed_mps_est"] is None else f"{e['speed_mps_est']:.3f}",
                        f"{e['duration_ms']:.1f}", f"{gi[0]:.2f}", f"{gi[1]:.2f}", f"{gi[2]:.2f}",
                        int(e["saturated"])])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw_csv")
    ap.add_argument("--labels", help="labels CSV (host_time_s,label,note)")
    ap.add_argument("--hand", choices=["lead", "rear"], default="rear", help="hand wearing the sensor")
    ap.add_argument("--stance", choices=["orthodox", "southpaw"], default="orthodox")
    ap.add_argument("--threshold", type=float, default=3.5, help="g on |a|-1g (3-4 typical)")
    ap.add_argument("--refractory-ms", type=float, default=150)
    ap.add_argument("--window-ms", type=float, default=150)
    ap.add_argument("--punches-out", help="punches CSV path")
    ap.add_argument("--session-out", help="session.json path (docs/session.schema.json)")
    ap.add_argument("--id", help="session id (default: file stem)")
    a = ap.parse_args(argv)
    p = Params(a.threshold, a.refractory_ms, a.window_ms, a.hand, a.stance)
    rec = load_raw(a.raw_csv)
    labels = load_labels(a.labels, rec.host_t0)
    sid = a.id or Path(a.raw_csv).stem.replace("_raw", "")
    events, rounds, cal = analyze(rec, labels, p, sid)
    doc = session_doc(rec, events, rounds, cal, p, sid)
    if a.punches_out:
        write_punches_csv(a.punches_out, events)
    if a.session_out:
        with open(a.session_out, "w") as fh:
            json.dump(doc, fh, indent=1)
    s = doc["summary"]
    print(f"{s['punch_count']} strikes, {s['non_punch_count']} non-strike events, "
          f"{len([r for r in rounds if r['kind'] == 'round'])} rounds, "
          f"{s['punches_per_min']} /min, max peak {s['max_peak_g']} g "
          f"({s['saturated_punch_count']} saturated: peak is a lower bound), calibrated={cal.ok}")
    print("by_type:", {k: v for k, v in s["by_type"].items() if v})
    return doc


if __name__ == "__main__":
    main()
