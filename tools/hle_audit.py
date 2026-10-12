#!/usr/bin/env python3
"""HLE audit: prove the BIOS HLE path services every SWI the game executes.

Forces HLE via GBARECOMP_BIOS_HLE=1 (independent of game.toml) and runs two
routes with the SWI census (GBARECOMP_SWI_LOG) + HLE-taken trace
(GBARECOMP_SWI_TRACE):

  - attract: 1200-frame boot run (intro movie — timing-chaotic content, so
    pixels are NOT pinned here, only coverage + fallback behavior).
  - route B: battle gameplay replay (load-state + input trace, 5094 frames)
    with a pinned final-frame hash (stable battle scene).

Pass criteria per route: exit 0, self_heal_coverage=FULLY_STATIC, every
executed SWI in the HLE-implemented set below, and every executed SWI
HLE-taken (trace count == log count — no silent LLE fallback). Any fallback
is a finding: it names the SWI number that still executes Nintendo BIOS
code, which is exactly what the release-hygiene story (issue #3) needs to
eliminate.

HLE_IMPLEMENTED mirrors the dispatch() switch in
gbarecomp/src/runtime/bios_hle.cpp (Div/DivARM, Sqrt, ArcTan/ArcTan2,
GetBiosChecksum, CpuSet/CpuFastSet, Bg/ObjAffineSet, BitUnpack, LZ77/Huff/
RL/Diff decompressors, SoundBias, MidiKey2Freq). Everything else (SoftReset,
RegisterRamReset, Halt/Stop, IntrWait/VBlankIntrWait, sound-driver SWIs,
MultiBoot, ...) transparently falls back to the recompiled LLE BIOS.

Usage:
  .venv/bin/python tools/hle_audit.py            # audit (exit 0/1)
  .venv/bin/python tools/hle_audit.py --repin    # adopt route-B HLE frame hash
Exit codes: 0 OK, 1 audit failure, 2 missing exe/fixtures.
"""
import argparse
import csv
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
EXE = REPO / "build/FFTARecomp"
BIOS = REPO / "bios/emibios_gba_bios.bin"
ROM = REPO / "game.gba"
REG = REPO / "saves/regress"
FIXTURE_SAVE = REG / "skyemu_20261007.sav"

# Mirror of bios_hle.cpp dispatch(): SWI numbers serviced in HLE.
HLE_IMPLEMENTED = frozenset([
    0x06, 0x07,                     # Div, DivARM
    0x08, 0x09, 0x0A,               # Sqrt, ArcTan, ArcTan2
    0x0D,                           # GetBiosChecksum
    0x0B, 0x0C,                     # CpuSet, CpuFastSet
    0x0E, 0x0F,                     # BgAffineSet, ObjAffineSet
    0x10,                           # BitUnpack
    0x11, 0x12, 0x13,               # LZ77 WRAM/VRAM, Huffman
    0x14, 0x15,                     # RL WRAM/VRAM
    0x16, 0x17, 0x18,               # Diff filters
    0x19,                           # SoundBias
    0x1F,                           # MidiKey2Freq
])

ATTRACT_FRAMES = 1200
ROUTEB_FRAMES = 5094  # trace end (29816) - state frame (24722)
EXPECTED_ROUTEB_HLE_SHA = "43D5B3B637BB9A89"


class Fail(Exception):
    pass


def clean_env():
    return {k: v for k, v in os.environ.items()
            if not k.startswith("GBARECOMP_")}


def run_case(name, cmd, workdir, save_src, replay=None):
    """Run the exe under forced HLE with SWI census + taken-trace. Returns
    (total_swis, taken_swis, uncovered_swis, output)."""
    env = clean_env()
    env["GBARECOMP_STRICT_STATIC"] = "1"
    env["GBARECOMP_BIOS_HLE"] = "1"
    env["GBARECOMP_SWI_TRACE"] = "1"
    if replay is not None:
        env["GBARECOMP_INPUT_REPLAY"] = str(replay)
    log_csv = workdir / f"{name}_swi.csv"
    env["GBARECOMP_SWI_LOG"] = str(log_csv)
    save = workdir / f"{name}.sav"
    shutil.copyfile(save_src, save)
    env["GBARECOMP_COVERAGE_JSON"] = str(workdir / f"{name}_cov.json")
    full_cmd = list(cmd) + ["--save-path", str(save)]
    r = subprocess.run(full_cmd, cwd=str(REPO), env=env,
                       capture_output=True, text=True, timeout=1800)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        raise Fail(f"{name}: exit {r.returncode}")
    cov = next((l for l in out.splitlines() if "self_heal_coverage" in l),
               "")
    if "FULLY_STATIC" not in cov:
        raise Fail(f"{name}: not FULLY_STATIC ({cov.strip() or 'no banner'})")
    if not log_csv.exists():
        raise Fail(f"{name}: no SWI census produced")
    with open(log_csv, newline="") as f:
        imms = [int(row["imm"]) for row in csv.DictReader(f)]
    taken = sum(1 for l in out.splitlines() if "HLE took swi=" in l)
    uncovered = sorted(set(imms) - HLE_IMPLEMENTED)
    return len(imms), taken, uncovered, out


def main() -> int:
    ap = argparse.ArgumentParser(description="BIOS HLE zero-fallback audit")
    ap.add_argument("--repin", action="store_true",
                    help="adopt the route-B HLE final-frame hash")
    ap.add_argument("--exe", default=str(EXE))
    a = ap.parse_args()

    for p, label in ((pathlib.Path(a.exe), "exe"), (BIOS, "BIOS"),
                     (ROM, "ROM"), (FIXTURE_SAVE, "fixture save"),
                     (REG / "battle_move_trace.csv", "route-B trace"),
                     (REG / "battle_move_start.state", "route-B state"),
                     (REG / "battle_move.sav", "route-B save")):
        if not p.exists():
            print(f"hle_audit: SKIP missing {label} {p}", flush=True)
            return 2

    try:
        with tempfile.TemporaryDirectory(prefix="ffta_hle_audit_") as td:
            work = pathlib.Path(td)
            n_att, t_att, u_att, _ = run_case(
                "attract",
                [a.exe, "--bios", str(BIOS), "--rom", str(ROM),
                 "--frames", str(ATTRACT_FRAMES), "--no-window"], work,
                FIXTURE_SAVE)
            routeb_png = work / "routeb_hle.png"
            n_b, t_b, u_b, _ = run_case(
                "routeb",
                [a.exe, "--bios", str(BIOS), "--rom", str(ROM),
                 "--load-state", str(REG / "battle_move_start.state"),
                 "--frames", str(ROUTEB_FRAMES), "--no-window",
                 "--dump-png", str(routeb_png)], work,
                REG / "battle_move.sav", replay=REG / "battle_move_trace.csv")
            sha = (hashlib.sha256(routeb_png.read_bytes()).hexdigest().upper()
                   if routeb_png.exists() else None)
    except Fail as e:
        print(f"hle_audit: FAIL {e}", flush=True)
        return 1

    problems = []
    if t_att != n_att or u_att:
        problems.append(
            f"attract fallback (taken {t_att}/{n_att}, "
            f"uncovered={['0x%02X' % u for u in u_att]})")
    if t_b != n_b or u_b:
        problems.append(
            f"routeB fallback (taken {t_b}/{n_b}, "
            f"uncovered={['0x%02X' % u for u in u_b]})")
    if sha is None:
        problems.append("routeB produced no frame dump")
    elif a.repin:
        src = pathlib.Path(__file__).read_text()
        new_src = src.replace(
            f'EXPECTED_ROUTEB_HLE_SHA = "{EXPECTED_ROUTEB_HLE_SHA}"',
            f'EXPECTED_ROUTEB_HLE_SHA = "{sha[:16]}"')
        assert new_src != src, "repin anchor missing"
        pathlib.Path(__file__).write_text(new_src)
        print(f"hle_audit: repinned routeB sha={sha[:16]}...")
        return 0
    elif not sha.startswith(EXPECTED_ROUTEB_HLE_SHA):
        # Prefix-pin convention (matches check.py FIXTURE_SHA_PREFIX and the
        # ws fixture states): a deliberate visual change is adopted with
        # --repin, never by editing the constant silently.
        problems.append(f"routeB frame sha mismatch (got {sha[:16]}..., "
                        f"expected {EXPECTED_ROUTEB_HLE_SHA[:16]}...)")

    if problems:
        print("hle_audit: FAIL " + "; ".join(problems), flush=True)
        return 1
    print(f"hle_audit: OK attract {t_att}/{n_att} HLE, routeB {t_b}/{n_b} "
          f"HLE, FULLY_STATIC x2, routeB frame {sha[:16]}...", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
