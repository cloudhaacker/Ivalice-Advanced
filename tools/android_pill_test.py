#!/usr/bin/env python3
"""android_pill_test.py — issue #11 touch-pill validation on a live device.

State-machine proof via screenshots + frame-rate behavior, all through the
observe TCP (no dependence on adb-tap OS filtering):
  shot0: pill visible, dark (unlatched), ~60/s
  touch_down/up @ pill -> shot1: pill GOLD (latched) + rate >> 60/s
  touch_down/up @ pill -> shot2: pill dark (unlatched) + rate back to ~60/s
  touch_down/up @ empty area -> shot3: still dark (no spurious toggle)

Immediate Down/Up is used deliberately: scripted touch_tap releases through
the frame drain, which policy-less games (no input_frame) never run, so the
steps would sit in script_pending forever. Holds are SHORT (0.25 s): past
the 450 ms long-press threshold the runtime menu opens and eats later taps.

Requires: a device session running with --tcp-observe (adb forward set),
e.g. write files/debug-args.txt via run-as, force-stop, relaunch with
AUTOSTART. Geometry (drawable, px_per_mm, insets) is read LIVE from
touch_status — the boot log goes stale once JNI physical DPI lands.

Usage:
  .venv/bin/python tools/android_pill_test.py [--port 19888]

Exit 0 = PASS. Evidence (shots) in android/artifacts/pill-test/.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=19888)
ap.add_argument("--pull-dir", default="android/artifacts/pill-test")
ARGS = ap.parse_args()
PORT = ARGS.port
OUT = ARGS.pull_dir
os.makedirs(OUT, exist_ok=True)

fails = []
def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)
    if not ok:
        fails.append(name)

def adb(*args):
    return subprocess.run(["adb", *args], capture_output=True, text=True, timeout=60)

# ── geometry: LIVE values from touch_status (density arrives via JNI after
# boot and insets settle with immersive mode — the boot log is stale) ──
adb("forward", f"tcp:{PORT}", f"tcp:{PORT}")
sock = socket.create_connection(("127.0.0.1", PORT), timeout=10)
def call(cmd, **kw):
    sock.sendall((json.dumps({"cmd": cmd, **kw}) + "\n").encode())
    sock.settimeout(30)
    buf = b""
    while b"\n" not in buf:
        d = sock.recv(1 << 22)
        if not d:
            raise ConnectionError("observe closed")
        buf += d
    return json.loads(buf.split(b"\n")[0])

st = call("touch_status")
dw, dh = st["drawable"]
ppmm = st["px_per_mm"]
it = st["insets"][1]
pw, ph = 15.0 * ppmm, 5.5 * ppmm
px, py = dw / 2.0, it + 2.5 * ppmm + ph / 2.0
print(f"[info] live drawable={dw}x{dh} ppmm={ppmm} insets-top={it} pill=c({px:.0f},{py:.0f}) {pw:.0f}x{ph:.0f}")

def shot(name):
    p = f"{OUT}/{name}.png"
    with open(p, "wb") as f:
        r = subprocess.run(["adb", "exec-out", "screencap", "-p"], stdout=f, timeout=60)
    assert r.returncode == 0, "screencap failed"
    return p

def pill_gold(path):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    assert im.size == (dw, dh), f"screenshot size {im.size} != drawable"
    # center third of the pill: avoids edges and game bleed
    x0, x1 = int(px - pw / 6), int(px + pw / 6)
    y0, y1 = int(py - ph / 6), int(py + ph / 6)
    pxs = list(im.crop((x0, y0, x1, y1)).get_flattened_data())
    n = len(pxs)
    mr = sum(p[0] for p in pxs) / n
    mg = sum(p[1] for p in pxs) / n
    mb = sum(p[2] for p in pxs) / n
    gold = mr > 180 and mg > 150 and mb < 160  # gold {255,214,74} vs dark backing
    return gold, (mr, mg, mb)

def rate():
    a = call("run_status")["frame"]
    t0 = time.monotonic()
    time.sleep(2.0)
    b = call("run_status")["frame"]
    dt = time.monotonic() - t0
    return (b - a) / dt

def tap(x, y, ptr):
    # Immediate (non-scripted) Down/Up: hub.submit() needs no frame drain,
    # which policy-less games (no input_frame) never run — scripted
    # touch_tap would sit in script_pending forever.
    # Hold is SHORT (0.25 s): anything past the 450 ms long-press threshold
    # opens the runtime menu instead, which then eats later taps modally.
    r = call("touch_down", x=x, y=y, space="drawable", pointer=ptr)
    assert r.get("ok"), r
    time.sleep(0.25)
    r = call("touch_up", x=x, y=y, space="drawable", pointer=ptr)
    assert r.get("ok"), r
    time.sleep(1.5)

# ── sequence ──
s0 = shot("pill0_boot")
g0, rgb0 = pill_gold(s0)
check("boot: pill visible unlatched (dark)", not g0, f"mean=({rgb0[0]:.0f},{rgb0[1]:.0f},{rgb0[2]:.0f})")
r0 = rate()
check("boot: frame rate ~60/s", 50 <= r0 <= 75, f"{r0:.0f}/s")

tap(px, py, 7)
s1 = shot("pill1_latched")
g1, rgb1 = pill_gold(s1)
check("tap1: pill GOLD (latched)", g1, f"mean=({rgb1[0]:.0f},{rgb1[1]:.0f},{rgb1[2]:.0f})")
r1 = rate()
check("tap1: frame rate boosted", r1 > r0 * 1.5, f"{r1:.0f}/s vs base {r0:.0f}/s")

tap(px, py, 8)
s2 = shot("pill2_unlatched")
g2, rgb2 = pill_gold(s2)
check("tap2: pill dark (unlatched)", not g2, f"mean=({rgb2[0]:.0f},{rgb2[1]:.0f},{rgb2[2]:.0f})")
r2 = rate()
check("tap2: frame rate back to normal", 50 <= r2 <= 75, f"{r2:.0f}/s")

tap(2500, 1300, 9)  # empty area: dpad/b/pad/toggle all clear of this point
s3 = shot("pill3_control")
g3, rgb3 = pill_gold(s3)
check("control tap away: still dark (no spurious toggle)", not g3,
      f"mean=({rgb3[0]:.0f},{rgb3[1]:.0f},{rgb3[2]:.0f})")

print(f"shots: {s0} {s1} {s2} {s3}")
print("PILL-TEST:", "PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
