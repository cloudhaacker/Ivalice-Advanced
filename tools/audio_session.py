#!/usr/bin/env python3
"""audio_session.py — live audio-fault triage for a running FFTARecomp.

One command around a play session: samples the guest audio path over the
TCP debug surface (audio_state + frame at 20 Hz, audio_trace at 4 Hz),
records the output sink's monitor, and prints a report at the end — so a
"ticking / crackle / dropout" report gets numbers instead of impressions.

  # terminal 1 (game):
  tools/play.sh --touch-emulation --tcp-observe 19888
  # terminal 2 (this tool, while you play and note times):
  .venv/bin/python tools/audio_session.py 19888

What the report covers:
  * producer rate — guest mixer samples_generated vs nominal 65536 Hz
  * frame cadence — guest stalls show as multi-frame poll gaps
  * FIFO A fill — count / bytes_remaining histograms, empty-FIFO events
    (count==0 && remaining==0: the emulation emits silence for that event)
  * the recording — broadband transient (click/tick) detection + a 0.3-5 Hz
    modulation spectrum (metronomic artifacts)
Logs + recording land in --out (default /tmp/opencode/audio_session):
  state.csv, trace.jsonl (deduped sample events), rec.raw, meta.txt.

Notes: reads are passive (no guest state is modified). Plain `--tcp` runs
headless by design — always use `--tcp-observe`. The recording captures the
whole sink mix, not just the game: close other players (or note them) for
clean attribution. Requires `parec` for recording (`--no-record` skips).
Stopping: close the game window (or SIGTERM) — the TCP `quit` command ends
only the debug connection in a windowed observe session and does not stop
the game (verified 2026-10-15; `host_quit` is fed by window events only).
"""
from __future__ import annotations

import argparse
import array
import datetime
import json
import math
import os
import pathlib
import re
import socket
import subprocess
import sys
import time
from collections import Counter

NOMINAL_HZ = 65536.0
REC_RATE = 48000


def call(sock, buf, **kw):
    sock.sendall(json.dumps(kw).encode() + b"\n")
    while b"\n" not in buf[0]:
        chunk = sock.recv(1 << 20)
        if not chunk:
            raise RuntimeError("connection closed")
        buf[0] += chunk
    line, _, buf[0] = buf[0].partition(b"\n")
    return json.loads(line.decode())


def connect(port, timeout_s=180.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=2.0)
            s.settimeout(20.0)
            return s
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(
        f"no debug server on port {port} after {timeout_s:.0f}s — launch the "
        f"game with --tcp-observe {port}")


def default_sink_monitor():
    """The default sink's monitor name via pactl, or None."""
    try:
        info = subprocess.run(["pactl", "info"], capture_output=True, text=True,
                              timeout=10).stdout
        m = re.search(r"Default Sink:\s*(\S+)", info)
        if not m:
            return None
        mon = m.group(1) + ".monitor"
        srcs = subprocess.run(["pactl", "list", "short", "sources"],
                              capture_output=True, text=True, timeout=10).stdout
        return mon if mon in srcs else None
    except Exception:
        return None


def start_recording(sink, path):
    if not sink:
        print("audio_session: no sink monitor found (use --sink) — recording "
              "skipped", file=sys.stderr)
        return None
    if subprocess.run(["which", "parec"], capture_output=True).returncode != 0:
        print("audio_session: parec not found — recording skipped",
              file=sys.stderr)
        return None
    f = open(path, "wb")
    p = subprocess.Popen(["parec", "--device=" + sink, "--rate=%d" % REC_RATE,
                          "--channels=1", "--format=s16le", "--raw"],
                         stdout=f, stderr=subprocess.DEVNULL)
    return p, f


def stop_recording(rec):
    if not rec:
        return
    p, f = rec
    p.terminate()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
    f.close()


# ---------------------------------------------------------------- report ---

def report_state(path):
    rows = []
    with open(path) as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            p = line.strip().split(",")
            if len(p) >= 13:
                rows.append(p)
    if not rows:
        print("state log empty")
        return
    t0, t1 = float(rows[0][0]), float(rows[-1][0])
    fr0, fr1 = int(rows[0][1]), int(rows[-1][1])
    s0, s1 = int(rows[0][2]), int(rows[-1][2])
    span = t1 - t0 or 1.0
    fps = (fr1 - fr0) / span
    hz = (s1 - s0) / span
    print(f"polls {len(rows)} over {t1:.1f}s")
    print(f"frames {fr0} -> {fr1}  ({fps:.2f}/s)")
    print(f"producer {s0} -> {s1}  ({hz:.1f} Hz vs {NOMINAL_HZ:.0f} nominal, "
          f"{(hz / NOMINAL_HZ - 1.0) * 100:+.3f}%)")
    cnt = Counter(int(r[3]) for r in rows)
    print(f"fifo_a count at poll: {dict(sorted(cnt.items()))}")
    br = Counter(int(r[6]) for r in rows)
    print(f"fifo_a bytes_remaining at poll: {dict(sorted(br.items()))}")
    worst = max((float(rows[i][0]) - float(rows[i - 1][0])
                 for i in range(1, len(rows))), default=0.0)
    print(f"largest poll gap {worst * 1000:.0f}ms "
          f"(guest stalls show as >1 frame: 16.7ms nominal)")


def report_trace(path):
    entries = {}
    with open(path) as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            e = rec.get("e")
            if e:
                entries.setdefault((e.get("base"), e.get("until"),
                                    e.get("start")), (rec["t"], e))
    if not entries:
        print("trace log empty (--no-trace, or trace disabled at launch: "
              "GBARECOMP_AUDIO_FIFO_TRACE=1)")
        return
    print(f"trace: {len(entries)} sample events")
    slots = Counter(e["slots"] for _, e in entries.values())
    print(f"slots per event: {dict(sorted(slots.items()))}")
    empty = sorted(((t, e) for t, e in entries.values()
                    if e["count"] == 0 and e["remaining"] == 0),
                   key=lambda x: x[0])
    print(f"empty-FIFO events (count==0 && remaining==0): {len(empty)}")
    if empty:
        buckets = Counter(int(t * 2) for t, _ in empty)
        ks = sorted(buckets)
        shown = [(f"{k * 0.5:.1f}s", buckets[k]) for k in ks[:24]]
        print(f"  per 0.5s bucket (first 24): {shown}"
              + (f" … {len(ks)} buckets" if len(ks) > 24 else ""))


def report_recording(path):
    if not os.path.exists(path) or os.path.getsize(path) < 2:
        print("recording: absent")
        return
    with open(path, "rb") as fh:
        data = fh.read()
    a = array.array("h")
    a.frombytes(data[: len(data) // 2 * 2])
    n = len(a)
    print(f"recording: {n / REC_RATE:.1f}s @ {REC_RATE} Hz mono s16le")
    win = REC_RATE // 1000  # 1 ms
    env, hf = [], []
    for i in range(win, n - win, win):
        s_env = 0
        for x in a[i : i + win]:
            s_env += x * x
        env.append(math.sqrt(s_env / win))
        s_hf = 0
        prev = a[i - 1]
        for x in a[i : i + win]:
            d = x - prev
            s_hf += d * d
            prev = x
        hf.append(math.sqrt(s_hf / win))
    hm = len(hf)
    if hm < 1000:
        print("recording too short to analyze")
        return
    hf_med = sorted(hf)[hm // 2]
    # broadband transients: HF spike vs local (1 s) median
    W, peaks = 500, []
    for i in range(hm):
        loc = sorted(hf[j] for j in range(max(0, i - W), min(hm, i + W), 7))
        lm = loc[len(loc) // 2] if loc else 1.0
        if lm <= 0.0:
            lm = 1.0
        if hf[i] > 6.0 * lm and hf[i] > 3.0 * hf_med:
            peaks.append(i)
    ded = []
    for p in peaks:
        if not ded or p - ded[-1] > 60:
            ded.append(p)
    secs = hm / 1000.0
    print(f"broadband transient peaks (>6x local hf median): {len(ded)} "
          f"({len(ded) / secs:.2f}/s)")

    def goertzel(series, f, fs=1000.0):
        w = 2.0 * math.pi * f / fs
        c = 2.0 * math.cos(w)
        s1 = s2 = 0.0
        for x in series:
            s0 = x + c * s1 - s2
            s2 = s1
            s1 = s0
        return s1 * s1 + s2 * s2 - c * s1 * s2

    sub = hf[500 : min(hm, 500 + 60000)]  # first 60 s
    best = []
    f = 0.3
    while f <= 5.001:
        best.append((goertzel(sub, f), f))
        f = round(f + 0.05, 4)
    top = max(p for p, _ in best) or 1.0
    best.sort(reverse=True)
    print("top modulation frequencies (0.3-5 Hz, first 60s, share of peak): "
          + ", ".join(f"{fr:.2f}Hz {p / top * 100:.0f}%" for p, fr in best[:4]))
    verdict = ("no broadband click/tick pattern"
               if len(ded) / secs < 0.5 else
               f"{len(ded)} transient peaks — inspect against session notes")
    print(f"verdict: {verdict}")


# ------------------------------------------------------------------ main ---

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("port", nargs="?", type=int, default=19888,
                    help="the game's --tcp-observe port (default 19888)")
    ap.add_argument("--out", default="/tmp/opencode/audio_session",
                    help="log/recording directory")
    ap.add_argument("--sink", default=None,
                    help="PulseAudio/PipeWire monitor source "
                         "(default: the default sink's monitor)")
    ap.add_argument("--no-record", action="store_true",
                    help="skip the sink-monitor recording")
    ap.add_argument("--no-trace", action="store_true",
                    help="skip audio_trace sampling")
    ap.add_argument("--trace-every", type=float, default=0.5,
                    help="audio_trace poll interval seconds (default 0.5)")
    ap.add_argument("--max-seconds", type=float, default=0.0,
                    help="stop after N seconds (default: until the game closes)")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.csv"
    trace_path = out / "trace.jsonl"
    rec_path = out / "rec.raw"
    meta_path = out / "meta.txt"

    print(f"audio_session: waiting for the debug server on port {args.port}…")
    sock = connect(args.port)
    buf = [b""]
    for _ in range(240):
        try:
            if call(sock, buf, cmd="presented").get("ok"):
                break
        except Exception:
            pass
        time.sleep(0.5)

    rec = None
    if not args.no_record:
        sink = args.sink or default_sink_monitor()
        rec = start_recording(sink, rec_path)
        if rec:
            print(f"audio_session: recording {sink}")

    t0 = time.time()
    wall = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(meta_path, "w") as fh:
        fh.write(f"start {wall}\nport {args.port}\nrec {rec_path}\n")
    print(f"audio_session: SAMPLING from {wall} — play; the report prints "
          f"when the game closes (or --max-seconds)")

    state_f = open(state_path, "w")
    state_f.write("# t,frame,samples,fifo_count,fifo_write,fifo_read,"
                  "bytes_remaining,dma1_runs,dma1_words,cycles_until,"
                  "cycle_acc,s0,s15\n")
    trace_f = open(trace_path, "w")
    seen = set()
    last_trace = 0.0
    polls = 0
    try:
        while True:
            loop_start = time.time()
            if args.max_seconds and loop_start - t0 >= args.max_seconds:
                break
            try:
                st = call(sock, buf, cmd="audio_state")
                fr = call(sock, buf, cmd="frame")
            except Exception as e:
                print(f"audio_session: connection closed after "
                      f"{time.time() - t0:.1f}s ({e})")
                break
            t = time.time() - t0
            fa = st.get("fifo_a") or {}
            d1 = st.get("dma1") or {}
            smp = fa.get("samples") or [0] * 16
            state_f.write(
                f"{t:.3f},{fr.get('frame')},{st.get('samples_generated')},"
                f"{fa.get('count')},{fa.get('write')},{fa.get('read')},"
                f"{fa.get('bytes_remaining')},{d1.get('runs')},"
                f"{d1.get('words')},{st.get('cycles_until_event')},"
                f"{st.get('cycle_accumulator')},{smp[0]},{smp[-1]}\n")
            polls += 1
            if polls % 20 == 0:
                state_f.flush()
            now = time.time()
            if not args.no_trace and now - last_trace >= args.trace_every:
                last_trace = now
                try:
                    tr = call(sock, buf, cmd="audio_trace", max=256)
                    for e in tr.get("entries", []):
                        key = (e.get("base"), e.get("until"), e.get("start"))
                        if key not in seen:
                            seen.add(key)
                            trace_f.write(json.dumps({"t": t, "e": e}) + "\n")
                    trace_f.flush()
                except Exception:
                    pass
            dt = time.time() - loop_start
            if dt < 0.05:
                time.sleep(0.05 - dt)
    finally:
        dur = time.time() - t0
        stop_recording(rec)
        state_f.close()
        trace_f.close()
        with open(meta_path, "a") as fh:
            fh.write(f"end {datetime.datetime.now():%Y-%m-%d %H:%M:%S} "
                     f"dur {dur:.1f}s polls {polls}\n")

    print()
    print("=== audio session report ===")
    report_state(state_path)
    if not args.no_trace:
        report_trace(trace_path)
    if not args.no_record:
        report_recording(rec_path)
    print(f"artifacts: {out}")


if __name__ == "__main__":
    main()
