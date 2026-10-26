"""The on-device strike detector (firmware/src/punch_detect.c) must find the same peaks as
analysis/detector.py find_peaks on the same quantized samples, with the same features
(peak g, speed estimate, gyro integral, saturation). Compiles the C module on the host."""
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

import common as C
import detector as D
import synth

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "firmware"


@pytest.fixture(scope="module")
def pd_cli(tmp_path_factory):
    cc = shutil.which("gcc") or shutil.which("cc")
    if not cc:
        pytest.skip("no C compiler")
    exe = tmp_path_factory.mktemp("fw") / "pd_cli"
    src = FW / "src"
    subprocess.run([cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-O1", f"-I{src}", "-o", str(exe),
                    str(FW / "tests" / "host" / "pd_cli.c"), str(src / "punch_detect.c"), "-lm"], check=True)
    return exe


def _quantize(acc, gyr, t0_us=4_294_000_000):
    a = np.clip(np.round(acc / C.ACCEL_G_PER_LSB), -32768, 32767).astype(np.int64)
    g = np.clip(np.round(gyr / C.GYRO_DPS_PER_LSB), -32768, 32767).astype(np.int64)
    t_us = (t0_us + np.round(np.arange(len(a)) * 1e6 / C.ODR_HZ).astype(np.int64)) & 0xFFFFFFFF
    return a, g, t_us


def _run_c(exe, a, g, t_us):
    lines = "\n".join(f"{t} {x[0]} {x[1]} {x[2]} {y[0]} {y[1]} {y[2]}" for t, x, y in zip(t_us, a, g))
    out = subprocess.run([str(exe)], input=lines, capture_output=True, text=True, check=True).stdout
    ev = []
    for line in out.splitlines():
        f = line.split()
        if f and f[0] == "EV":
            ev.append(dict(ip=int(f[1]), a=int(f[2]), b=int(f[3]), t_us=int(f[4]), peak_g=float(f[5]),
                           speed=float(f[6]), gpk=float(f[7]), gint=[float(x) for x in f[8:11]],
                           asat=f[11] == "1", gsat=f[12] == "1"))
    return ev


def _python(a, g):
    acc = a * C.ACCEL_G_PER_LSB
    gyr = g * C.GYRO_DPS_PER_LSB
    t = np.arange(len(a)) / C.ODR_HZ
    p = D.Params()
    dyn = D.dyn_g(acc)
    out = []
    dt = 1.0 / C.ODR_HZ
    for ip, lo, hi in D.find_peaks(dyn, t, p):
        a0, b0 = D.event_bounds(dyn, ip, lo, hi, 0.25 * p.threshold_g)
        out.append(dict(ip=ip, a=a0, b=b0, peak_g=float(dyn[ip]),
                        speed=float(np.clip(dyn[a0:ip + 1], 0, None).sum() * dt * 9.81),
                        gint=(gyr[lo:hi].sum(0) * dt).tolist(),
                        asat=bool((np.abs(a[lo:hi]) >= C.ACCEL_SAT_RAW).any())))
    return out


def _session(name):
    if name == "straight":
        return synth.make_class_session("straight", 30, "lead", "orthodox", seed=3, gap=0.9, hard_frac=0.3)[0]
    if name == "hook_fast":
        return synth.make_class_session("hook", 30, "rear", "orthodox", seed=4, gap=0.6)[0]
    return synth.make_demo(seed=11, rounds=1, round_s=90.0, rest_s=10.0)[0]


@pytest.mark.parametrize("name", ["straight", "hook_fast", "demo"])
def test_c_detector_matches_python(pd_cli, name):
    s = _session(name)
    acc, gyr, _sat, _ = s.render()
    a, g, t_us = _quantize(acc, gyr)
    if name == "straight":  # one clipped impact (16 g rail) in a quiet stretch
        k = int(len(a) - 1.5 * C.ODR_HZ)
        a[k - 3:k + 4, 0] = [9000, 20000, 32767, 32767, 32767, 21000, 8000]
    py = _python(a, g)
    c = _run_c(pd_cli, a, g, t_us)
    assert len(py) > 20
    py_ip = {e["ip"]: e for e in py}
    matched = [e for e in c if e["ip"] in py_ip]
    # float32 on the device vs float64 here: allow a rare flip right at the threshold
    assert len(matched) >= 0.99 * len(py) and len(c) <= len(py) + max(1, len(py) // 100)
    for e in matched:
        q = py_ip[e["ip"]]
        assert e["peak_g"] == pytest.approx(q["peak_g"], abs=1e-3)
        assert e["speed"] == pytest.approx(q["speed"], rel=1e-3, abs=1e-3)
        assert (e["a"], e["b"]) == (q["a"], q["b"])
        assert np.allclose(e["gint"], q["gint"], rtol=1e-3, atol=0.05)
        assert e["asat"] == q["asat"]
        assert e["t_us"] == int(t_us[e["ip"]])  # device timestamp of the peak (wraps at 2^32)
    if name == "straight":
        assert sum(e["asat"] for e in c) == 1
