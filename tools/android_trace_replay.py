#!/usr/bin/env python3
"""android_trace_replay.py — replay a desktop input trace on device.

Pushes a savestate + optional battery save, (re)launches the app with
--tcp-observe, loads the state over TCP, then drives the trace's
(frame, keyinput) rows via set_keyinput, polling run_status frames.

Frame timing over adb-forward TCP is good to ~1-3 frames — fine for
gameplay/audio reproduction, not for cycle-exact oracle work.

Usage:
  .venv/bin/python tools/android_trace_replay.py \
      --state saves/regress/battle_move_start.state \
      --trace saves/regress/battle_move_trace.csv \
      [--save saves/regress/battle_move.sav] [--port 19888]
"""
import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGE = "org.gbarecomp.fftarecomp"
ACTIVITY = f"{PACKAGE}/org.gbarecomp.GbaSetupActivity"


def adb(*args, timeout=60):
    return subprocess.run(["adb", *args], capture_output=True, text=True,
                          timeout=timeout)


def call(sock, cmd, **kw):
    sock.sendall((json.dumps({"cmd": cmd, **kw}) + "\n").encode())
    sock.settimeout(60)
    buf = b""
    while b"\n" not in buf:
        d = sock.recv(1 << 22)
        if not d:
            raise ConnectionError("observe server closed the connection")
        buf += d
    return json.loads(buf.split(b"\n")[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19888)
    ap.add_argument("--state", required=True)
    ap.add_argument("--trace", required=True)
    ap.add_argument("--save", default=None)
    ap.add_argument("--serial", default=None)
    args = ap.parse_args()

    state = REPO / args.state
    trace = REPO / args.trace
    rows = []
    for line in trace.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        f, k = line.split(",")
        rows.append((int(f), int(k, 16)))
    rows.sort()
    print(f"trace: {len(rows)} rows frames {rows[0][0]}->{rows[-1][0]}")

    # Fresh setup: stop, stage files, arm observe TCP, launch.
    adb("shell", "am", "force-stop", PACKAGE)
    time.sleep(1.0)
    if args.save:
        ext = "/sdcard/Android/data/org.gbarecomp.fftarecomp/files/saves/ffta_us.sav"
        r = adb("push", str(REPO / args.save), ext)
        print("save pushed:", "OK" if r.returncode == 0 else r.stderr.strip())
    remote = "/data/local/tmp/ffta_replay_state.state"
    assert adb("push", str(state), remote).returncode == 0, "state push failed"
    assert adb("shell", "run-as", PACKAGE, "mkdir", "-p",
               "files/saves").returncode == 0
    r = adb("shell", "run-as", PACKAGE, "cp", remote,
            f"files/saves/{state.name}")
    assert r.returncode == 0, r.stderr
    adb("shell", "rm", "-f", remote)
    # debug-args.txt only accepts runtime args (per android/README.md).
    adb("shell", "run-as", PACKAGE, "sh", "-c",
        "'printf \"%s\" \"--tcp-observe 19888\" > files/debug-args.txt'")
    adb("shell", "am", "start", "-n", ACTIVITY,
        "--ez", "org.gbarecomp.extra.AUTOSTART", "true")
    adb("forward", f"tcp:{args.port}", f"tcp:{args.port}")

    sock = None
    for _ in range(30):
        try:
            sock = socket.create_connection(("127.0.0.1", args.port),
                                            timeout=5)
            break
        except OSError:
            time.sleep(2.0)
    if sock is None:
        print("FAIL: observe TCP never came up")
        return 1

    try:
        res = call(sock, "savestate_load", path=f"saves/{state.name}")
        print("load:", json.dumps(res)[:160])
        if res.get("ok") is not True:
            return 1
        call(sock, "set_keyinput", value=0x03FF)
        t0 = time.time()
        i = 0
        late = 0
        end_frame = rows[-1][0] + 120
        while time.time() - t0 < 240:
            st = call(sock, "run_status")
            cur = int(st.get("frame", 0))
            while i < len(rows) and rows[i][0] <= cur:
                if rows[i][0] < cur - 2:
                    late += 1
                call(sock, "set_keyinput", value=rows[i][1])
                i += 1
            if cur >= end_frame and i >= len(rows):
                break
            time.sleep(0.02)
        call(sock, "set_keyinput", value=0x03FF)
        st = call(sock, "run_status")
        print(f"done: rows_fed={i}/{len(rows)} late={late} "
              f"frame={st.get('frame')} elapsed={time.time()-t0:.1f}s")
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
