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
 8. two sensors (one per wrap, --stream lead=... --stream rear=... [--sync sync.csv]):
    fit each device clock to host time (offset + drift), resample nothing but map
    every device timestamp onto one session timeline, detect per device, merge by
    time (crosstalk suppression + cross-device dedupe of kick/clinch), union rounds.

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
SCHEMA_VERSION = "1.1.0"


# --------------------------------------------------------------------------- data
@dataclass
class Recording:
    t: np.ndarray        # s from first sample (device clock)
    acc: np.ndarray      # g, sensor frame
    gyr: np.ndarray      # dps, sensor frame
    sat: np.ndarray      # bool per sample (logger flag)
    host_t0: float       # host_time_s of first sample
    fs: float
    dev_t0_us: int = 0   # unwrapped device_time_us of the first sample (clock alignment)

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
    return Recording(t, acc, gyr, sat, float(data["host_time_s"][0]), float(fs), int(dev[0]))


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



# --------------------------------------------------------------------------- two sensors
@dataclass
class ClockFit:
    """host_time_s = a + b * device_time_s  (b = 1 + skew)."""
    a: float
    b: float
    source: str
    residual_ms: Optional[float]
    n: int

    @property
    def skew_ppm(self):
        return (self.b - 1.0) * 1e6

    def host(self, dev_s):
        return self.a + self.b * np.asarray(dev_s, float)


def fit_clock(dev_us, host_s, rtt_ms=None, window_s=5.0, source="rtt") -> ClockFit:
    """Fit device clock -> host clock from sync samples.

    source "rtt": NTP-style exchanges (host_s = midpoint of request/response). If rtt_ms
    is given, only the lowest-RTT third per `window_s` is used (least asymmetric).
    source "packet": (device time of a notification's last sample, host rx time) pairs;
    BLE latency only ever ADDS delay, so the lower envelope (min host-dev per window)
    is fitted. Falls back to offset-only when the span is too short for drift."""
    dev = np.asarray(dev_us, float) / 1e6
    host = np.asarray(host_s, float)
    if dev.size == 0:
        raise ValueError("no sync samples")
    keep = np.ones(dev.size, bool)
    if source == "packet" or rtt_ms is not None:
        keep[:] = False
        bins = np.floor((dev - dev[0]) / window_s).astype(int)
        for b in np.unique(bins):
            idx = np.flatnonzero(bins == b)
            if source == "packet":
                keep[idx[np.argmin(host[idx] - dev[idx])]] = True
            else:
                r = np.asarray(rtt_ms, float)[idx]
                keep[idx[r <= np.quantile(r, 0.34)]] = True
    d, h = dev[keep], host[keep]
    if d.size >= 2 and d.max() - d.min() >= 10.0:
        b, a = np.polyfit(d - d[0], h, 1)
        a = a - b * d[0]
    else:
        b, a = 1.0, float(np.median(h - d))
    res = h - (a + b * d)
    return ClockFit(float(a), float(b), source, round(float(np.std(res) * 1e3), 3) if d.size > 2 else None, int(d.size))


def load_sync(path) -> dict:
    """sync CSV (tools/logger.py): device_id,role,host_time_s,device_time_us,rtt_ms,source -> {key: rows}.
    Rows are keyed by both device_id and role."""
    out = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            r = (float(row["host_time_s"]), int(row["device_time_us"]),
                 float(row["rtt_ms"]) if row.get("rtt_ms") not in (None, "") else None, row.get("source") or "rtt")
            for k in {row.get("device_id"), row.get("role")} - {None, ""}:
                out.setdefault(k, []).append(r)
    return out


def clock_from_sync(rows) -> ClockFit:
    rows = sorted(rows, key=lambda r: r[1])
    src = "packet" if all(r[3] == "packet" for r in rows) else "rtt"
    if src == "rtt":
        rows = [r for r in rows if r[3] != "packet"]
    rtt = [r[2] for r in rows] if all(r[2] is not None for r in rows) and src == "rtt" else None
    return fit_clock([r[1] for r in rows], [r[0] for r in rows], rtt, source=src)


@dataclass
class Stream:
    role: str                  # lead / rear (hand wearing this sensor)
    rec: Recording
    device_id: str
    clock: Optional[ClockFit] = None
    firmware_version: Optional[str] = None


def align_streams(streams: List[Stream]):
    """Map every stream onto one session timeline (seconds from the earliest aligned first
    sample). Streams without a sync fit use their raw CSV host_time_s anchor (offset only).
    Returns (aligned Recordings, session host_t0, start offsets)."""
    hosts0 = []
    for st in streams:
        if st.clock is None:
            st.clock = ClockFit(st.rec.host_t0 - st.rec.dev_t0_us / 1e6, 1.0, "raw_host_time", None, 1)
        hosts0.append(float(st.clock.host((st.rec.dev_t0_us / 1e6) + st.rec.t[0])))
    T0 = min(hosts0)
    out = []
    for st in streams:
        th = st.clock.host(st.rec.dev_t0_us / 1e6 + st.rec.t) - T0
        fs = (len(th) - 1) / (th[-1] - th[0]) if th[-1] > th[0] else st.rec.fs
        out.append(Recording(th, st.rec.acc, st.rec.gyr, st.rec.sat, T0, float(fs), st.rec.dev_t0_us))
    return out, T0, [h - T0 for h in hosts0]


def merge_events(per_device, pair_window_ms=60.0, crosstalk_ratio=0.5, dedupe_s=0.5):
    """Merge per-device event lists (each event has "device_id") into one time-ordered list.

    * Strikes from different devices within `pair_window_ms`: a hard strike shakes the
      other wrist too. If the weaker peak is < crosstalk_ratio x the stronger one it is
      crosstalk and dropped; otherwise both are kept (a genuine near-simultaneous strike,
      e.g. a parry + counter or a double strike).
    * kick_or_body_movement / clinch are whole-body events both sensors see: overlapping
      ones (or peaks within `dedupe_s`) from different devices are merged into one
      (largest peak kept; clinch spans are unioned)."""
    ev = sorted([dict(e) for evs in per_device for e in evs], key=lambda e: e["t_peak_s"])
    strikes = [e for e in ev if e["type"] not in C.NON_STRIKE_TYPES]
    other = [e for e in ev if e["type"] in C.NON_STRIKE_TYPES]
    drop = set()
    w = pair_window_ms / 1000.0
    for i, a in enumerate(strikes):
        for b in strikes[i + 1:]:
            if b["t_peak_s"] - a["t_peak_s"] > w:
                break
            if a["device_id"] == b["device_id"] or id(a) in drop or id(b) in drop:
                continue
            lo, hi = (a, b) if a["peak_g"] < b["peak_g"] else (b, a)
            if lo["peak_g"] < crosstalk_ratio * hi["peak_g"]:
                drop.add(id(lo))
            else:
                a["near_simultaneous"] = b["near_simultaneous"] = True
    strikes = [e for e in strikes if id(e) not in drop]
    merged = []
    for e in other:
        m = next((x for x in merged if x["type"] == e["type"] and x["device_id"] != e["device_id"]
                  and (min(x["t_end_s"], e["t_end_s"]) >= max(x["t_start_s"], e["t_start_s"])
                       or abs(x["t_peak_s"] - e["t_peak_s"]) < dedupe_s)), None)
        if m is None:
            merged.append(e)
            continue
        if e["type"] == "clinch":
            m["t_start_s"], m["t_end_s"] = min(m["t_start_s"], e["t_start_s"]), max(m["t_end_s"], e["t_end_s"])
            m["duration_ms"] = round((m["t_end_s"] - m["t_start_s"]) * 1000, 1)
        if e["peak_g"] > m["peak_g"]:
            for k in ("peak_g", "t_peak_s", "gyro_int_dps_s", "device_id"):
                m[k] = e[k]
        m["saturated"] = m["saturated"] or e["saturated"]
    out = sorted(strikes + merged, key=lambda e: e["t_peak_s"])
    return out, len(drop)


def union_rounds(per_device_rounds):
    spans = sorted((r["t_start_s"], r["t_end_s"]) for rs in per_device_rounds for r in rs if r["kind"] == "round")
    u = []
    for a, b in spans:
        if u and a <= u[-1][1] + 1.0:
            u[-1][1] = max(u[-1][1], b)
        else:
            u.append([a, b])
    rounds = []
    for n, (a, b) in enumerate(u):
        if n:
            rounds.append({"t_start_s": u[n - 1][1], "t_end_s": a, "kind": "rest"})
        rounds.append({"t_start_s": a, "t_end_s": b, "kind": "round"})
    return [{"index": i, **r} for i, r in enumerate(rounds)]


def analyze_multi(streams: List[Stream], labels_host=None, p: Optional[Params] = None, **merge_kw):
    """Two (or more) sensors -> one merged event list. `labels_host` are (host_time_s, label, note)."""
    p = p or Params()
    recs, T0, starts = align_streams(streams)
    labels = sorted((t - T0, l, n) for t, l, n in (labels_host or []))
    per_dev, per_rounds, cals = [], [], []
    for st, rec in zip(streams, recs):
        pp = Params(**{**asdict(p), "hand": st.role})
        events, rounds, cal = analyze(rec, labels, pp)
        for e in events:
            e["device_id"] = st.device_id
        per_dev.append(events)
        per_rounds.append(rounds)
        cals.append(cal)
    events, n_crosstalk = merge_events(per_dev, **merge_kw)
    rounds = union_rounds(per_rounds)
    for k, e in enumerate(events):
        e["id"] = k
        e["round_index"] = next((r["index"] for r in rounds if r["kind"] == "round"
                                 and r["t_start_s"] <= e["t_peak_s"] <= r["t_end_s"]), None)
    devices = []
    for st, rec, cal, start in zip(streams, recs, cals, starts):
        devices.append({
            "device_id": st.device_id, "hand": st.role, "wrist": C.hand_worn(st.role, p.stance),
            "firmware_version": st.firmware_version, "sample_rate_hz": round(rec.fs, 2), "calibrated": bool(cal.ok),
            "clock": {"source": st.clock.source, "offset_s": round(start, 4), "skew_ppm": round(st.clock.skew_ppm, 2),
                      "residual_ms": st.clock.residual_ms, "sync_points": st.clock.n}})
    return events, rounds, cals, recs, devices, n_crosstalk


def session_doc_multi(recs, events, rounds, cals, devices, p: Params, session_id: str):
    from types import SimpleNamespace
    combo = SimpleNamespace(t=np.array([max(float(r.t[-1]) for r in recs)]), sat=np.concatenate([r.sat for r in recs]),
                            host_t0=recs[0].host_t0, fs=float(np.mean([r.fs for r in recs])))
    cal = next((c for c in cals if c.ok), cals[0])
    doc = session_doc(combo, events, rounds, cal, Params(**{**asdict(p), "hand": devices[0]["hand"]}), session_id, devices)
    doc["session"]["hand"] = None
    doc["session"]["hand_worn"] = None
    return doc


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


def session_doc(rec, events, rounds, cal, p: Params, session_id: str, devices=None, device_id="sensor"):
    clean = [{k: v for k, v in e.items() if not k.startswith("_")} for e in events]
    order = ["id", "t_peak_s", "t_start_s", "t_end_s", "type", "confidence", "target", "hand",
             "peak_g", "speed_mps_est", "duration_ms", "gyro_int_dps_s", "saturated", "round_index", "device_id"]
    if devices is None:  # single sensor: one device entry, its clock is the session clock
        devices = [{"device_id": device_id, "hand": p.hand, "wrist": C.hand_worn(p.hand, p.stance),
                    "firmware_version": None, "sample_rate_hz": round(rec.fs, 2), "calibrated": bool(cal.ok),
                    "clock": {"source": "device", "offset_s": 0.0, "skew_ppm": 0.0, "residual_ms": None, "sync_points": 0}}]
    for e in clean:
        e.setdefault("device_id", devices[0]["device_id"] if len(devices) == 1 else None)
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
            "devices": devices,
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
    ap.add_argument("raw_csv", nargs="?", help="raw CSV of a single sensor (or use --stream)")
    ap.add_argument("--stream", action="append", default=[], metavar="ROLE=RAW_CSV[@DEVICE_ID]",
                    help="one sensor per hand, e.g. --stream lead=s_lead_raw.csv --stream rear=s_rear_raw.csv")
    ap.add_argument("--sync", help="sync CSV from tools/logger.py (device clock -> host clock samples)")
    ap.add_argument("--device-id", default="sensor", help="device id for single-sensor input")
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
    if a.stream:
        sync = load_sync(a.sync) if a.sync else {}
        streams = []
        for spec in a.stream:
            role, rest = spec.split("=", 1)
            path, _, dev_id = rest.partition("@")
            dev_id = dev_id or f"{role}"
            rows = sync.get(dev_id) or sync.get(role)
            streams.append(Stream(role, load_raw(path), dev_id, clock_from_sync(rows) if rows else None))
        labels_host = [(t + 0.0, l, n) for t, l, n in load_labels(a.labels, 0.0)]
        events, rounds, cals, recs, devices, n_x = analyze_multi(streams, labels_host, p)
        sid = a.id or Path(a.stream[0].split("=", 1)[1].partition("@")[0]).stem.replace("_raw", "").replace("_lead", "").replace("_rear", "")
        doc = session_doc_multi(recs, events, rounds, cals, devices, p, sid)
        cal = next((c for c in cals if c.ok), cals[0])
        print(f"{len(streams)} sensors aligned: " + ", ".join(
            f"{d['hand']} offset {d['clock']['offset_s']:+.3f} s skew {d['clock']['skew_ppm']:+.1f} ppm "
            f"({d['clock']['source']}, residual {d['clock']['residual_ms']} ms)" for d in devices) + f"; {n_x} crosstalk peak(s) dropped")
    else:
        if not a.raw_csv:
            ap.error("give a raw CSV or --stream ROLE=RAW_CSV")
        rec = load_raw(a.raw_csv)
        labels = load_labels(a.labels, rec.host_t0)
        sid = a.id or Path(a.raw_csv).stem.replace("_raw", "")
        events, rounds, cal = analyze(rec, labels, p, sid)
        doc = session_doc(rec, events, rounds, cal, p, sid, device_id=a.device_id)
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
