#!/usr/bin/env python3
"""Decode on-device event logs (GATT 0x000A, fetched with `logger.py --fetch-log`) and
build a schema-1.1.0 session.json from one or two sensors - no raw stream needed.

  python tools/evlog.py dump recordings/s1_lead_log.bin
  python tools/evlog.py session --log lead=recordings/s1_lead_log.bin \\
      --log rear=recordings/s1_rear_log.bin --stance orthodox --session-out s1_session.json

How device time becomes host time: the logger writes a time ANCHOR (host clock, device
clock, RTT of its best exchange) into each device's log at connect, every --sync-every
seconds while connected, and right before fetching. Anchors of the same boot are fitted
with analysis/detector.fit_clock (drift + offset). The device clock restarts at every
boot (including each wake from System OFF), so events can only be placed on the host
clock if their boot has at least one anchor; with a single anchor the offset is exact
but drift (+-20-40 ppm, i.e. up to ~0.1 s/h) is uncorrected. See docs/gatt-spec.md.

Event types come from the device: the calibration straight (jab for the lead sensor,
cross for the rear) and "unknown" for everything else - on-device classification is not
ported. gyro_int_dps_s is in the SENSOR frame (not the calibrated frame).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "analysis"))
import proto  # noqa: E402

REC = proto.LOG_REC.size


def read_records(data: bytes):
    """bytes (concatenated 32-byte records, e.g. a _log.bin) -> (records, n_bad_crc)."""
    out, bad = [], 0
    for i in range(0, len(data) - len(data) % REC, REC):
        try:
            r = proto.parse_log_record(data[i:i + REC])
        except ValueError:
            bad += 1
            continue
        if r["kind"] not in ("end", "empty"):
            out.append(r)
    out.sort(key=lambda r: r["seq"])
    dedup = []
    for r in out:  # overlapping fetches
        if not dedup or dedup[-1]["seq"] != r["seq"]:
            dedup.append(r)
    return dedup, bad


def _unwrap_boot(records):
    """Unwrap each record's 32-bit device time within one boot, in log order."""
    uw = proto.TimeUnwrapper()
    for r in records:
        for k in ("dev_t0_us", "dev_t_peak_us", "device_time_us", "dev_t_us"):
            if k in r:
                r[k + "_unwrapped"] = uw(r[k])


def boots(records):
    """Split into per-boot lists (consecutive records with the same boot_id)."""
    out = []
    for r in records:
        if not out or out[-1][0]["boot_id"] != r["boot_id"]:
            out.append([])
        out[-1].append(r)
    for b in out:
        _unwrap_boot(b)
    return out


def boot_clock(boot):
    import detector as D
    anchors = [r for r in boot if r["kind"] == "anchor"]
    if not anchors:
        return None
    fit = D.fit_clock([r["device_time_us_unwrapped"] for r in anchors], [r["host_time_s"] for r in anchors],
                      [r["rtt_ms"] for r in anchors], window_s=30.0)
    fit.source = "anchor"
    return fit


def device_sessions(records):
    """-> list of dicts {session_id, start, stop, events, rounds_marks, clock, boot_id}."""
    out = []
    for b in boots(records):
        clk = boot_clock(b)
        cur = None
        for r in b:
            if r["kind"] == "session_start":
                cur = {"session_id": r["session_id"], "start": r, "stop": None, "events": [], "marks": [],
                       "clock": clk, "boot_id": r["boot_id"]}
                out.append(cur)
            elif cur is None:
                continue
            elif r["kind"] == "event":
                cur["events"].append(r)
            elif r["kind"] == "round_mark":
                cur["marks"].append(r)
            elif r["kind"] == "session_stop":
                cur["stop"] = r
                cur = None
    return out


def _host(clk, dev_us):
    return float(clk.host(dev_us / 1e6))


def session_from_logs(logs, stance="orthodox", session_id=None, p=None):
    """logs: [(role, device_id, records)] -> (session_doc, info). Picks the given session id
    (default: the most recent one present in any log)."""
    import common as C
    import detector as D
    p = p or D.Params(stance=stance)
    found = {}
    for role, dev_id, recs in logs:
        for s in device_sessions(recs):
            found.setdefault(s["session_id"], []).append((role, dev_id, s))
    if not found:
        raise SystemExit("no session in the logs")
    sid = session_id if session_id is not None else max(found)
    if sid not in found:
        raise SystemExit(f"session {sid} not in the logs (have {sorted(found)})")
    parts = found[sid]
    per_dev, devices, starts, ends, marks = [], [], [], [], []
    for role, dev_id, s in parts:
        clk = s["clock"]
        if clk is None:
            raise SystemExit(f"{role}: no time anchor in boot {s['boot_id']} - cannot place its events on the "
                             "host clock (record with tools/logger.py so anchors get written)")
        t0 = _host(clk, s["start"]["dev_t0_us_unwrapped"])
        t1 = _host(clk, s["stop"]["dev_t_us_unwrapped"]) if s["stop"] else None
        starts.append(t0)
        ends.append(t1)
        marks += [(_host(clk, m["dev_t_us_unwrapped"]), m["round"]) for m in s["marks"]]
        wrist = s["start"]["wrist"] or C.hand_worn(role, stance)
        evs = []
        for e in s["events"]:
            tp = _host(clk, e["dev_t_peak_us_unwrapped"])
            evs.append({"t_peak_s": tp, "t_start_s": tp - e["pre_ms"] / 1000, "t_end_s": tp + e["post_ms"] / 1000,
                        "type": e["type"], "confidence": e["confidence"], "target": e["target"], "hand": wrist,
                        "peak_g": e["peak_g"], "speed_mps_est": e["speed_mps_est"],
                        "duration_ms": float(e["pre_ms"] + e["post_ms"]),
                        "gyro_int_dps_s": e["gyro_int_deg_sensor"], "saturated": e["saturated"],
                        "device_id": dev_id, "_uncal": e["uncalibrated"]})
        per_dev.append(evs)
        devices.append({"device_id": dev_id, "hand": role, "wrist": wrist,
                        "firmware_version": s["start"]["firmware_version"], "sample_rate_hz": C.ODR_HZ,
                        "calibrated": any(not e["_uncal"] for e in evs),
                        "clock": {"source": "anchor", "offset_s": 0.0, "skew_ppm": round(clk.skew_ppm, 2),
                                  "residual_ms": clk.residual_ms, "sync_points": clk.n}})
    T0 = min(starts)
    T1 = max([t for t in ends if t is not None] + [e["t_end_s"] for evs in per_dev for e in evs] + [T0])
    for d, t0 in zip(devices, starts):
        d["clock"]["offset_s"] = round(t0 - T0, 4)
    for evs in per_dev:
        for e in evs:
            for k in ("t_peak_s", "t_start_s", "t_end_s"):
                e[k] -= T0
    events, n_x = D.merge_events(per_dev)
    # rounds: ROUND_MARK n > 0 starts round n, 0 starts a rest; none -> one round
    marks = sorted(set((round(t - T0, 3), n) for t, n in marks))
    spans, rounds = [], []
    if marks:
        edges = marks + [(T1 - T0, None)]
        for (a, n), (b, _) in zip(edges, edges[1:]):
            if b > a:
                spans.append((a, b, "round" if n else "rest"))
    else:
        spans = [(0.0, T1 - T0, "round")]
    rounds = [{"index": i, "t_start_s": a, "t_end_s": b, "kind": k} for i, (a, b, k) in enumerate(spans)]
    for k, e in enumerate(events):
        e["id"] = k
        e.pop("_uncal", None)
        e["round_index"] = next((r["index"] for r in rounds if r["kind"] == "round"
                                 and r["t_start_s"] <= e["t_peak_s"] <= r["t_end_s"]), None)
    rec = SimpleNamespace(t=np.array([T1 - T0]), sat=np.zeros(1, bool), host_t0=T0, fs=C.ODR_HZ)
    cal = SimpleNamespace(ok=False)
    pp = D.Params(**{**p.__dict__, "hand": devices[0]["hand"], "stance": stance})
    doc = D.session_doc(rec, events, rounds, cal, pp, str(sid), devices)
    doc["generator"] = {"name": "tools/evlog.py (on-device event log)", "version": D.GENERATOR_VERSION}
    if len(devices) > 1:
        doc["session"]["hand"] = None
        doc["session"]["hand_worn"] = None
    th = {s["start"]["threshold_g"] for _, _, s in parts}
    doc["detector_params"]["threshold_g"] = th.pop() if len(th) == 1 else p.threshold_g
    return doc, {"session_id": sid, "crosstalk_dropped": n_x, "devices": devices}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump", help="print the records of a _log.bin")
    d.add_argument("path")
    s = sub.add_parser("session", help="build session.json from one or two logs")
    s.add_argument("--log", action="append", required=True, metavar="ROLE=LOG_BIN[@DEVICE_ID]")
    s.add_argument("--stance", choices=["orthodox", "southpaw"], default="orthodox")
    s.add_argument("--session-id", type=int, help="session to export (default: latest)")
    s.add_argument("--session-out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "dump":
        recs, bad = read_records(Path(a.path).read_bytes())
        for r in recs:
            print(json.dumps(r))
        print(f"# {len(recs)} records, {bad} bad CRC", file=sys.stderr)
        return recs
    logs = []
    for spec in a.log:
        role, _, rest = spec.partition("=")
        if role not in ("lead", "rear"):
            ap.error(f"--log expects lead=... or rear=..., got {spec!r}")
        path, _, dev_id = rest.partition("@")
        recs, bad = read_records(Path(path).read_bytes())
        if bad:
            print(f"{role}: {bad} record(s) with a bad CRC skipped", file=sys.stderr)
        logs.append((role, dev_id or role, recs))
    doc, info = session_from_logs(logs, a.stance, a.session_id)
    Path(a.session_out).write_text(json.dumps(doc, indent=1))
    sm = doc["summary"]
    print(f"session {info['session_id']}: {sm['punch_count']} strikes from {len(logs)} device(s), "
          f"{info['crosstalk_dropped']} crosstalk peak(s) dropped -> {a.session_out}")
    return doc


if __name__ == "__main__":
    main()
