#!/usr/bin/env python3
"""Synthetic IMU data generator for the boxing tracker (testing only!).

Signals are physically *plausible* templates, not recordings: each strike is a
Gaussian linear-acceleration pulse along a class-specific direction plus a
class-specific rotation pulse (and a slower opposite "retraction" rotation),
generated in the calibrated forearm frame (x forward, y left, z up - see
docs/axes.md), with gravity rotated by the integrated angular rate, then
rotated into a random sensor mounting, quantised to LSM6DS3TR-C LSBs and
clipped at +-16 g / +-2000 dps (so hard hooks saturate, like real ones may).

  python analysis/synth.py --demo analysis/samples/demo     # 3 x 3 min rounds
"""
from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import numpy as np

try:
    from . import common as C
except ImportError:  # run as a script
    import common as C

FS = C.ODR_HZ
BASE_CLASSES = ["straight", "hook", "uppercut", "overhand", "spinning_backfist"]


def _small_rotation(rng, sigma_deg):
    """Random rotation matrix with angle ~ N(0, sigma_deg) about a random axis."""
    ax = rng.normal(size=3)
    ax /= np.linalg.norm(ax)
    th = math.radians(rng.normal(0, sigma_deg))
    K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    return np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * K @ K


@dataclass
class Truth:
    t_s: float                 # peak time (s from start), or start for clinch
    base: str                  # straight/hook/uppercut/overhand/spinning_backfist/kick/clinch/clap
    type: str                  # v1 taxonomy for the sensor hand
    target: Optional[str] = None
    t_end_s: Optional[float] = None
    saturated_intent: bool = False
    amp_g: Optional[float] = None   # true linear accel amplitude of the main pulse


@dataclass
class Session:
    n: int
    hand: str = "rear"
    stance: str = "orthodox"
    seed: int = 0
    jitter_deg: float = 12.0     # random tilt of each strike template (technique variation)
    rot_scale: tuple = (0.75, 1.15)  # random scaling of rotation magnitude
    lin: np.ndarray = field(init=False)     # linear accel, body frame, g
    omega: np.ndarray = field(init=False)   # angular rate, body frame, dps
    noise_scale: np.ndarray = field(init=False)
    truths: List[Truth] = field(default_factory=list)

    def __post_init__(self):
        self.lin = np.zeros((self.n, 3))
        self.omega = np.zeros((self.n, 3))
        self.rng = np.random.default_rng(self.seed)
        self.hw = C.hand_worn(self.hand, self.stance)
        self.m = 1.0 if self.hw == "R" else -1.0   # mirror for left wrist
        self.t = np.arange(self.n) / FS

    # ---- primitives -------------------------------------------------
    def _gauss(self, mu, sigma):
        lo = max(0, int((mu - 5 * sigma) * FS))
        hi = min(self.n, int((mu + 5 * sigma) * FS) + 1)
        sl = slice(lo, hi)
        return sl, np.exp(-0.5 * ((self.t[sl] - mu) / sigma) ** 2)

    def add_lin(self, mu, sigma, vec):
        sl, g = self._gauss(mu, sigma)
        self.lin[sl] += g[:, None] * np.asarray(vec)[None, :]

    def add_rot(self, mu, sigma, vec, retract=True):
        sl, g = self._gauss(mu, sigma)
        self.omega[sl] += g[:, None] * np.asarray(vec)[None, :]
        if retract:  # opposite, slower pulse so orientation returns to guard
            sl, g = self._gauss(mu + 0.28, sigma * 1.5)
            self.omega[sl] -= g[:, None] * np.asarray(vec)[None, :] / 1.5

    def mir(self, v):
        """Mirror a right-wrist template for the left wrist (y -> -y).
        For linear vectors flip y; for angular (pseudo) vectors flip x and z."""
        return np.array([v[0], self.m * v[1], v[2]])

    def mir_w(self, w):
        return np.array([self.m * w[0], w[1], self.m * w[2]])

    # ---- strikes ------------------------------------------------------
    def strike(self, t, base, target=None, hard=False):
        r = self.rng
        u = r.uniform
        target = target or "head"
        elev = math.radians(-35 if target == "body" else u(-5, 8))
        sa = u(0.035, 0.05)
        A = u(6, 11)
        if base == "straight":
            A = u(6, 10) if self.hand == "lead" else u(7, 13)
            d = np.array([math.cos(elev), u(-0.08, 0.08), math.sin(elev)])
            w = np.array([u(500, 800), 0.0, u(-200, 200)])  # corkscrew roll, small yaw
            sw = 0.03
        elif base == "hook":
            A = u(18, 26) if hard else u(8, 14)
            fwd = u(0.35, 0.55)
            d = np.array([fwd * math.cos(elev), math.sqrt(1 - fwd ** 2) * math.cos(elev), math.sin(elev)])
            w = np.array([u(-150, 150), u(-150, 150), u(900, 1300)])
            sw = 0.045
        elif base == "uppercut":
            d = np.array([u(0.25, 0.45), u(-0.1, 0.1), 0.0])
            d[2] = math.sqrt(max(0.0, 1 - d[0] ** 2 - d[1] ** 2))
            w = np.array([u(-200, 200), -u(800, 1100), u(-150, 150)])
            sw = 0.04
            target = None
        elif base == "overhand":
            A = u(8, 13)
            d = np.array([0.55, 0.3, -0.78])
            w = np.array([u(-150, 150), u(700, 1000), u(200, 400)])
            sw = 0.045
            target = "head"
        elif base == "spinning_backfist":
            A = u(6, 10)
            d = np.array([0.2, -0.95, u(-0.1, 0.1)])
            w = np.array([0.0, u(-100, 100), -u(1100, 1500)])
            sw = 0.09
            target = "head"
        else:
            raise ValueError(base)
        d = d / np.linalg.norm(d)
        # technique variation: tilt the whole template, scale the rotation
        J = _small_rotation(r, self.jitter_deg)
        d, w = J @ d, J @ (w * r.uniform(*self.rot_scale))
        d, w = self.mir(d), self.mir_w(w)
        self.add_lin(t, sa, A * d)
        self.add_lin(t + 0.06, 0.03, -0.5 * A * d)          # impact / deceleration
        # a spin completes (no counter-rotation); other strikes retract to guard
        self.add_rot(t - 0.02, sw, w, retract=(base != "spinning_backfist"))
        self.truths.append(Truth(t, base, C.resolve_type(base, self.hand), target,
                                 saturated_intent=hard, amp_g=float(A)))

    def kick_or_body(self, t):
        u = self.rng.uniform
        ang = u(0, 2 * math.pi)
        A = u(1.2, 2.2)
        self.add_lin(t, 0.08, A * np.array([math.cos(ang), math.sin(ang), 0.2]))
        s = 1 if self.rng.random() < 0.5 else -1
        self.add_rot(t, 0.12, np.array([u(-80, 80), u(-150, 150), s * u(380, 550)]))
        self.truths.append(Truth(t, "kick", "kick_or_body_movement"))

    def clinch(self, t0, dur):
        i0, i1 = int(t0 * FS), min(self.n, int((t0 + dur) * FS))
        n = i1 - i0
        k = np.ones(40) / 40.0  # ~100 ms smoothing -> "small, frequent" motions
        for ax in range(3):
            self.lin[i0:i1, ax] += np.convolve(self.rng.normal(0, 0.35 * 6.3, n), k, "same")
            self.omega[i0:i1, ax] += np.convolve(self.rng.normal(0, 75 * 6.3, n), k, "same")
        self.truths.append(Truth(t0, "clinch", "clinch", t_end_s=t0 + dur))

    def clap(self, t):
        self.add_lin(t, 0.004, np.array([0.0, 0.0, -10.0]))
        self.truths.append(Truth(t, "clap", "sync"))

    def footwork(self, t0, t1):
        i0, i1 = int(t0 * FS), int(t1 * FS)
        tt = self.t[i0:i1]
        self.lin[i0:i1, 2] += 0.25 * np.sin(2 * math.pi * 2.0 * tt)
        self.lin[i0:i1, 0] += 0.08 * np.sin(2 * math.pi * 1.1 * tt + 1)
        self.omega[i0:i1, 0] += 8 * np.sin(2 * math.pi * 1.3 * tt)

    # ---- render ------------------------------------------------------
    def render(self, mount: Optional[np.ndarray] = None):
        """Integrate orientation, add gravity + noise, rotate into the sensor frame,
        quantise and clip. Returns (accel_g[n,3], gyro_dps[n,3], sat[n], R_mount)."""
        r = self.rng
        if mount is None:
            q = r.normal(size=4)
            q /= np.linalg.norm(q)
            a, b, c, d = q
            mount = np.array([
                [a*a + b*b - c*c - d*d, 2*(b*c - a*d), 2*(b*d + a*c)],
                [2*(b*c + a*d), a*a - b*b + c*c - d*d, 2*(c*d - a*b)],
                [2*(b*d - a*c), 2*(c*d + a*b), a*a - b*b - c*c + d*d]])
        dt = 1.0 / FS
        grav = np.empty((self.n, 3))
        gx, gy, gz = 0.0, 0.0, 1.0
        w = np.radians(self.omega).tolist()
        for i in range(self.n):
            wx, wy, wz = w[i]
            # body-frame gravity: dg/dt = -w x g (first order), renormalised
            nx = gx - dt * (wy * gz - wz * gy)
            ny = gy - dt * (wz * gx - wx * gz)
            nz = gz - dt * (wx * gy - wy * gx)
            inv = 1.0 / math.sqrt(nx * nx + ny * ny + nz * nz)
            gx, gy, gz = nx * inv, ny * inv, nz * inv
            # slow drift back to the guard orientation
            gx -= 0.0015 * gx
            gy -= 0.0015 * gy
            gz += 0.0015 * (1.0 - gz)
            grav[i] = (gx, gy, gz)
        acc_b = self.lin + grav
        acc_b += r.normal(0, 0.012, acc_b.shape)
        gyr_b = self.omega + r.normal(0, 1.5, self.omega.shape)
        acc_s = acc_b @ mount.T
        gyr_s = gyr_b @ mount.T
        araw = np.clip(np.round(acc_s / C.ACCEL_G_PER_LSB), -32768, 32767)
        graw = np.clip(np.round(gyr_s / C.GYRO_DPS_PER_LSB), -32768, 32767)
        sat = (np.abs(araw) >= C.ACCEL_SAT_RAW).any(1) | (np.abs(graw) >= C.GYRO_SAT_RAW).any(1)
        return araw * C.ACCEL_G_PER_LSB, graw * C.GYRO_DPS_PER_LSB, sat, mount


def calibration_preamble(s: Session, t0=0.0):
    """sync clap at t0+2.5 s, guard hold t0+3..6 s, calibration straight at t0+6.5 s."""
    s.clap(t0 + 2.5)
    s.strike(t0 + 6.5, "straight")
    return t0 + 3.0, t0 + 7.2  # cal_start, cal_end


def write_raw_csv(path, accel, gyro, sat, host_t0, dev_t0_us=123_456_789):
    n = len(accel)
    dev = dev_t0_us + np.round(np.arange(n) * 1e6 / FS).astype(np.int64)
    host = host_t0 + (dev - dev_t0_us) / 1e6
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(C.RAW_HEADER)
        for i in range(n):
            w.writerow([f"{host[i]:.4f}", int(dev[i]),
                        f"{accel[i,0]:.3f}", f"{accel[i,1]:.3f}", f"{accel[i,2]:.3f}",
                        f"{gyro[i,0]:.1f}", f"{gyro[i,1]:.1f}", f"{gyro[i,2]:.1f}", int(sat[i])])


def write_labels(path, host_t0, labels):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(C.LABEL_HEADER)
        for t, lab, note in sorted(labels, key=lambda x: x[0]):
            w.writerow([f"{host_t0 + t:.4f}", lab, note])


def make_class_session(base, count=40, hand="rear", stance="orthodox", seed=1, gap=1.2,
                       target=None, hard_frac=0.0, jitter_deg=12.0, rot_scale=(0.75, 1.15)):
    """Preamble + `count` isolated events of one class (for recall tests)."""
    step = gap + 6.0 if base == "clinch" else gap
    dur = 10 + count * step + 3
    s = Session(int(dur * FS), hand, stance, seed, jitter_deg, rot_scale)
    cal = calibration_preamble(s)
    for k in range(count):
        t = 10 + k * gap + s.rng.uniform(-0.1, 0.1)
        if base == "kick":
            s.kick_or_body(t)
        elif base == "clinch":
            pass
        else:
            tg = target or ("body" if (base in ("straight", "hook") and s.rng.random() < 0.3) else None)
            s.strike(t, base, target=tg, hard=s.rng.random() < hard_frac)
    if base == "clinch":  # `count` clinches of `gap` s, 6 s apart
        for k in range(count):
            s.clinch(10.0 + k * step, gap * s.rng.uniform(0.75, 1.0))
    return s, cal


def make_demo(seed=7, hand="rear", stance="orthodox", rounds=3, round_s=180.0, rest_s=60.0):
    lead_in = 12.0
    dur = lead_in + rounds * round_s + (rounds - 1) * rest_s + 8.0
    s = Session(int(dur * FS), hand, stance, seed)
    cal = calibration_preamble(s)
    r = s.rng
    labels = [(2.5, "sync", "clap"), (cal[0], "cal_start", "hold guard, then one straight"),
              (cal[1], "cal_end", "")]
    rounds_t = []
    t = lead_in
    mix = ["straight"] * 40 + ["hook"] * 28 + ["uppercut"] * 14 + ["overhand"] * 8 + ["spinning_backfist"] * 3
    for k in range(rounds):
        t0, t1 = t, t + round_s
        rounds_t.append((t0, t1))
        labels += [(t0, "round", f"round {k+1} start"), (t1, "rest", f"round {k+1} end")]
        s.footwork(t0, t1)
        clinch_at = t0 + r.uniform(60, round_s - 30)
        s.clinch(clinch_at, r.uniform(6, 10))
        busy = [(clinch_at - 1, clinch_at + 11)]
        kicks = [t0 + r.uniform(10, round_s - 10) for _ in range(3)]
        for kt in kicks:
            if not any(a <= kt <= b for a, b in busy):
                s.kick_or_body(kt)
                busy.append((kt - 0.6, kt + 0.6))
        tt = t0 + 2.0
        while tt < t1 - 2:
            # combo of 1-4 strikes, 0.3-0.5 s apart, then 1.5-4 s pause
            for _ in range(int(r.integers(1, 5))):
                if not any(a <= tt <= b for a, b in busy):
                    base = mix[int(r.integers(len(mix)))]
                    tg = "body" if base in ("straight", "hook") and r.random() < 0.25 else None
                    s.strike(tt, base, target=tg, hard=(base == "hook" and r.random() < 0.35))
                tt += r.uniform(0.3, 0.5)
            tt += r.uniform(1.5, 4.0)
        t = t1 + rest_s
    for tr in s.truths:
        if tr.base not in ("clap",):
            note = "synthetic ground truth" + (f"; target={tr.target}" if tr.target else "")
            if tr.base == "clinch":
                labels.append((tr.t_s, "clinch_start", note))
                labels.append((tr.t_end_s, "clinch_end", note))
            else:
                labels.append((tr.t_s, f"truth:{tr.type}", note))
    return s, cal, labels, rounds_t


# ---------------------------------------------------------------- fatigue (multi-round demos)
class FatigueSession(Session):
    """Session whose strike() scales the strike's linear pulse by self.f (rotation by sqrt(f)),
    so a tired strike is both lower-g and slower (speed is integrated from acceleration)."""
    f: float = 1.0

    def strike(self, t, base, target=None, hard=False):
        lo, hi = max(0, int((t - 1.0) * FS)), min(self.n, int((t + 1.0) * FS))
        lin0, om0 = self.lin[lo:hi].copy(), self.omega[lo:hi].copy()
        n_truth = len(self.truths)
        super().strike(t, base, target=target, hard=hard)
        self.lin[lo:hi] = lin0 + self.f * (self.lin[lo:hi] - lin0)
        self.omega[lo:hi] = om0 + np.sqrt(self.f) * (self.omega[lo:hi] - om0)
        for tr in self.truths[n_truth:]:
            if tr.amp_g is not None:
                tr.amp_g *= self.f


@dataclass
class FatigueProfile:
    """Per-round fatigue for a kickboxing session (round k = 0 .. rounds-1).

    Gentle fade every round, plus a late-session fade from `late_from` (1-based round):
      * amplitude  f_k = 1 - fade_round*k - late_amp*(late rounds so far)   (lower g + speed)
      * pauses     between combos x (1 + pause_round*k + late_pause*late)  (lower output)
      * combos     at most `max_combo_early` strikes, `max_combo_late` in late rounds
      * kicks      `kicks_early` per round, `kicks_late` in late rounds
      * hooks      share of hooks in the mix is cut by `late_hook_cut` in late rounds
    Within a round, amplitude also fades by `fade_within` from bell to bell."""
    fade_round: float = 0.01
    fade_within: float = 0.05
    pause_round: float = 0.02
    late_from: int = 8
    late_amp: float = 0.03
    late_pause: float = 0.08
    max_combo_early: int = 4
    max_combo_late: int = 3
    kicks_early: int = 4
    kicks_late: int = 1
    late_hook_cut: float = 0.4

    def late(self, k: int) -> int:
        """Number of late rounds up to and including round k (0 before late_from)."""
        return max(0, k + 2 - self.late_from)

    def amp(self, k: int) -> float:
        return 1.0 - self.fade_round * k - self.late_amp * self.late(k)

    def pause(self, k: int) -> float:
        return 1.0 + self.pause_round * k + self.late_pause * self.late(k)

    def max_combo(self, k: int) -> int:
        return self.max_combo_late if self.late(k) else self.max_combo_early

    def kicks(self, k: int) -> int:
        return self.kicks_late if self.late(k) else self.kicks_early


def make_fatigue_session(seed=21, hand="rear", stance="orthodox", rounds=10, round_s=180.0, rest_s=60.0,
                         profile: Optional[FatigueProfile] = None):
    """N x M-minute kickboxing session with a realistic late-round fade (see FatigueProfile).
    Returns (session, labels) with labels as (t_s, label, note) incl. round/rest markers,
    calibration and truth:<type> ground truth."""
    pf = profile or FatigueProfile()
    lead_in = 12.0
    dur = lead_in + rounds * round_s + (rounds - 1) * rest_s + 8.0
    s = FatigueSession(int(dur * FS), hand, stance, seed)
    cal = calibration_preamble(s)
    r = s.rng
    labels = [(2.5, "sync", "clap"), (cal[0], "cal_start", "hold guard, then one straight"), (cal[1], "cal_end", "")]
    t = lead_in
    for k in range(rounds):
        late = pf.late(k) > 0
        hooks = int(round(28 * (1 - pf.late_hook_cut))) if late else 28
        mix = ["straight"] * 42 + ["hook"] * hooks + ["uppercut"] * 12 + ["overhand"] * 7 + ["spinning_backfist"] * 3
        t0, t1 = t, t + round_s
        labels += [(t0, "round", f"round {k+1} start"), (t1, "rest", f"round {k+1} end")]
        s.footwork(t0, t1)
        busy = []
        # tired fighters clinch more
        if r.random() < (0.9 if late else 0.5):
            c_lo = min(30.0, 0.3 * round_s)
            ca = t0 + r.uniform(c_lo, max(c_lo + 1.0, round_s - 25))
            s.clinch(ca, r.uniform(5, 9) * (1.4 if late else 1.0))
            busy.append((ca - 1, ca + 14))
        n_k = 0
        for _ in range(40):
            if n_k >= pf.kicks(k):
                break
            kt = t0 + r.uniform(8, round_s - 8)
            if not any(a - 1.5 <= kt <= b + 1.5 for a, b in busy):
                s.kick_or_body(kt)
                busy.append((kt - 0.6, kt + 0.6))
                n_k += 1
        start_f = pf.amp(k)
        tt = t0 + 2.0
        while tt < t1 - 2:
            prog = (tt - t0) / round_s
            s.f = start_f * (1.0 - pf.fade_within * prog) * r.uniform(0.95, 1.04)
            for _ in range(int(r.integers(1, pf.max_combo(k) + 1))):
                if not any(a <= tt <= b for a, b in busy):
                    base = mix[int(r.integers(len(mix)))]
                    tg = "body" if base in ("straight", "hook") and r.random() < 0.25 else None
                    s.strike(tt, base, target=tg, hard=(base == "hook" and r.random() < 0.3 * s.f))
                tt += r.uniform(0.3, 0.45) * (1 + 0.03 * k)
            tt += r.uniform(1.4, 3.6) * pf.pause(k)
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


# ---------------------------------------------------------------- two sensors (one per wrap)
LEAD_BASES = ("straight", "hook", "uppercut")


def make_two_hand_fatigue_session(seed=21, stance="orthodox", rounds=10, round_s=180.0, rest_s=60.0,
                                  profile: Optional[FatigueProfile] = None, lead_share=0.5,
                                  lead_share_late_drop=0.05, lead_late_fade=0.05, crosstalk_g=(0.5, 1.4)):
    """Same fight plan as make_fatigue_session, but every strike is thrown by the lead or the
    rear hand and rendered into that hand's sensor; the other sensor sees a small crosstalk
    pulse (body motion, < detector threshold). Kicks, clinches and footwork are whole-body and
    appear in both. Late rounds: both hands fade, the lead hand more (extra `lead_late_fade` of
    amplitude per late round and `lead_share_late_drop` less share), so the rear share rises.
    Returns ({"lead": FatigueSession, "rear": FatigueSession}, labels)."""
    pf = profile or FatigueProfile()
    lead_in = 12.0
    dur = lead_in + rounds * round_s + (rounds - 1) * rest_s + 8.0
    n = int(dur * FS)
    S = {"lead": FatigueSession(n, "lead", stance, seed + 1), "rear": FatigueSession(n, "rear", stance, seed + 2)}
    r = np.random.default_rng(seed)
    cal = (0.0, 0.0)
    for s in S.values():
        cal = calibration_preamble(s)
    labels = [(2.5, "sync", "clap"), (cal[0], "cal_start", "hold guard, then one straight (both hands)"), (cal[1], "cal_end", "")]

    def both(fn, *args):
        for s in S.values():
            getattr(s, fn)(*args)

    t = lead_in
    for k in range(rounds):
        late = pf.late(k)
        hooks = int(round(28 * (1 - pf.late_hook_cut))) if late else 28
        mix = ["straight"] * 42 + ["hook"] * hooks + ["uppercut"] * 12 + ["overhand"] * 7 + ["spinning_backfist"] * 3
        p_lead = lead_share - lead_share_late_drop * late
        t0, t1 = t, t + round_s
        labels += [(t0, "round", f"round {k+1} start"), (t1, "rest", f"round {k+1} end")]
        both("footwork", t0, t1)
        busy = []
        if r.random() < (0.9 if late else 0.5):
            c_lo = min(30.0, 0.3 * round_s)
            ca = t0 + r.uniform(c_lo, max(c_lo + 1.0, round_s - 25))
            cd = r.uniform(5, 9) * (1.4 if late else 1.0)
            both("clinch", ca, cd)
            busy.append((ca - 1, ca + 14))
        n_k = 0
        for _ in range(40):
            if n_k >= pf.kicks(k):
                break
            kt = t0 + r.uniform(8, round_s - 8)
            if not any(a - 1.5 <= kt <= b + 1.5 for a, b in busy):
                both("kick_or_body", kt)
                busy.append((kt - 0.6, kt + 0.6))
                n_k += 1
        tt = t0 + 2.0
        while tt < t1 - 2:
            prog = (tt - t0) / round_s
            f = pf.amp(k) * (1.0 - pf.fade_within * prog) * r.uniform(0.95, 1.04)
            for _ in range(int(r.integers(1, pf.max_combo(k) + 1))):
                if not any(a <= tt <= b for a, b in busy):
                    base = mix[int(r.integers(len(mix)))]
                    if base == "overhand":
                        hand = "rear"
                    elif base == "spinning_backfist":
                        hand = "lead" if r.random() < 0.5 else "rear"
                    else:
                        hand = "lead" if r.random() < p_lead else "rear"
                    other = "rear" if hand == "lead" else "lead"
                    s = S[hand]
                    s.f = f * (1.0 - lead_late_fade * late if hand == "lead" else 1.0)
                    tg = "body" if base in ("straight", "hook") and r.random() < 0.25 else None
                    s.strike(tt, base, target=tg, hard=(base == "hook" and r.random() < 0.3 * s.f))
                    ang = r.uniform(0, 2 * math.pi)
                    # small body-motion pulse on the other wrist; ~4 % are big enough to cross
                    # the detector threshold and must be removed by detector.merge_events
                    amp = r.uniform(4.0, 5.5) if r.random() < 0.04 else r.uniform(*crosstalk_g)
                    S[other].add_lin(tt + r.uniform(0.0, 0.02), 0.035,
                                     amp * np.array([math.cos(ang), math.sin(ang), 0.3]))
                tt += r.uniform(0.3, 0.45) * (1 + 0.03 * k)
            tt += r.uniform(1.4, 3.6) * pf.pause(k)
        t = t1 + rest_s
    seen_body = set()
    for role, s in S.items():
        for tr in s.truths:
            if tr.base == "clap" or (role == "rear" and tr.base in ("kick", "clinch")):
                continue
            note = f"synthetic ground truth; hand={role}" + (f"; target={tr.target}" if tr.target else "")
            if tr.base == "clinch":
                labels += [(tr.t_s, "clinch_start", note), (tr.t_end_s, "clinch_end", note)]
            else:
                labels.append((tr.t_s, f"truth:{tr.type}", note))
    return S, labels


@dataclass
class DeviceClock:
    """Device clock model: device_time_us = dev_t0_us + true_t * (1 + skew_ppm * 1e-6) * 1e6.
    The device starts logging `start_s` after true t = 0. BLE notifications carry 18 samples;
    the host receives each `latency_ms` (+ exponential jitter) after its last sample."""
    dev_t0_us: int
    skew_ppm: float
    start_s: float = 0.0
    latency_ms: float = 12.0
    jitter_ms: float = 4.0

    def dev_us(self, true_t):
        return self.dev_t0_us + np.round(np.asarray(true_t) * (1 + self.skew_ppm * 1e-6) * 1e6).astype(np.int64)


def write_raw_csv_clock(path, accel, gyro, sat, host_t0, clock: DeviceClock, rng, end_s=None):
    """Raw CSV as tools/logger.py writes it for one device of a two-sensor session: device
    timestamps follow `clock`; host_time_s uses the logger's fixed anchor (first packet rx)."""
    i0 = int(round(clock.start_s * FS))
    i1 = len(accel) if end_s is None else min(len(accel), int(end_s * FS))
    idx = np.arange(i0, i1)
    true_t = idx / FS
    dev = clock.dev_us(true_t)
    first_pkt_last = min(17, len(idx) - 1)
    a_host = host_t0 + true_t[first_pkt_last] + (clock.latency_ms + rng.exponential(clock.jitter_ms)) / 1e3
    a_dev = dev[first_pkt_last]
    host = a_host + (dev - a_dev) / 1e6
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(C.RAW_HEADER)
        for k, i in enumerate(idx):
            w.writerow([f"{host[k]:.6f}", int(dev[k]),
                        f"{accel[i,0]:.3f}", f"{accel[i,1]:.3f}", f"{accel[i,2]:.3f}",
                        f"{gyro[i,0]:.1f}", f"{gyro[i,1]:.1f}", f"{gyro[i,2]:.1f}", int(sat[i])])


SYNC_HEADER = ["device_id", "role", "host_time_s", "device_time_us", "rtt_ms", "source"]


def sync_rows(device_id, role, clock: DeviceClock, host_t0, dur_s, rng, every_s=10.0, burst=8, conn_ms=7.5):
    """Simulated time-sync exchanges (docs/gatt-spec.md 0x0008): at connect and every `every_s`,
    a burst of reads; host_time_s = request/response midpoint, rtt = 1-3 connection intervals,
    and the device stamps the read at an asymmetric point inside the round trip."""
    rows = []
    for ts in np.arange(clock.start_s, dur_s, every_s):
        for b in range(burst):
            t_req = ts + b * 0.05
            rtt = conn_ms * int(rng.integers(1, 4)) + rng.uniform(0, 1.0)
            t_dev = t_req + rtt / 1e3 * rng.uniform(0.35, 0.65)   # true time the device stamped it
            mid = t_req + rtt / 2e3
            rows.append([device_id, role, f"{host_t0 + mid:.6f}", int(clock.dev_us(t_dev)), f"{rtt:.2f}", "rtt"])
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", required=True, help="output prefix, e.g. analysis/samples/demo")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--hand", default="rear", choices=["lead", "rear"])
    ap.add_argument("--stance", default="orthodox", choices=["orthodox", "southpaw"])
    a = ap.parse_args(argv)
    s, cal, labels, _ = make_demo(a.seed, a.hand, a.stance)
    acc, gyr, sat, _ = s.render()
    host_t0 = datetime(2026, 10, 24, 18, 0, 0, tzinfo=timezone.utc).timestamp()
    Path(a.demo).parent.mkdir(parents=True, exist_ok=True)
    write_raw_csv(f"{a.demo}_raw.csv", acc, gyr, sat, host_t0)
    write_labels(f"{a.demo}_labels.csv", host_t0, labels)
    print(f"wrote {a.demo}_raw.csv ({len(acc)} samples, {sat.mean()*100:.2f}% saturated) and labels")


if __name__ == "__main__":
    main()
