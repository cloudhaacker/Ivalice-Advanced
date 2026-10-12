#!/usr/bin/env python3
"""ui_check.py — build and run recomp-ui's runtime-UI tests.

The in-game settings overlay is recomp-ui's runtime UI (`src/common/
recomp_runtime_ui.c` plus the ImGui presentation in `src/common/backends/
imgui/runtime_ui_imgui.cpp`), framework code pinned as a submodule and
patched in-tree. `tools/check.py --only patches` validates the diff; this
suite validates its behavior, so a recorded patch cannot silently rot:

  recomp-runtime-ui-test          the model: input handling, values,
                                  text editing, status/toast
  recomp-runtime-ui-imgui-test    the ImGui presentation: layout geometry,
                                  and the list follow / drag-scroll paths
                                  (issue #24)

No ROM, no BIOS, no SDL: the presentation only needs a C/C++ compiler and
the vendored sources, so this runs in the CI subset too.

  .venv/bin/python tools/ui_check.py [--verbose] [--force]

The build is cached under build/recomp-ui-tests/ against the inputs' mtimes;
--force rebuilds. One summary line on stdout, exit 0 only when every binary
ran clean.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
UI = REPO / "recomp-ui"
OUT = REPO / "build" / "recomp-ui-tests"

SRC = UI / "src"
MODEL = [SRC / "common/recomp_runtime_ui.c",
         SRC / "common/recomp_runtime_settings.c"]
IMGUI = [SRC / "third_party/imgui/imgui.cpp",
         SRC / "third_party/imgui/imgui_draw.cpp",
         SRC / "third_party/imgui/imgui_tables.cpp",
         SRC / "third_party/imgui/imgui_widgets.cpp"]
BACKEND = SRC / "common/backends/imgui/runtime_ui_imgui.cpp"
INCLUDES = [str(SRC), str(SRC / "common"), str(SRC / "third_party/imgui")]

# (binary, test source, subject sources, language)
BINARIES = [
    ("recomp-runtime-ui-test", UI / "tests/runtime_ui_test.c", MODEL, "c"),
    ("recomp-runtime-ui-imgui-test", UI / "tests/runtime_ui_imgui_test.cpp",
     MODEL + [BACKEND] + IMGUI, "c++"),
]


def compiler(lang):
    if lang == "c":
        return os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc")
    return (os.environ.get("CXX") or shutil.which("c++")
            or shutil.which("g++"))


def stamp(inputs):
    return "|".join(f"{p}:{p.stat().st_mtime_ns}" for p in inputs)


def build(binary, test, sources, lang, verbose):
    """Compile one test binary; returns (ok, detail)."""
    cc = compiler(lang)
    if not cc:
        return False, f"no {lang} compiler (set CC/CXX)"
    exe = OUT / binary
    inputs = [test] + sources
    marker = OUT / f".{binary}.stamp"
    want = stamp(inputs) + f"|{cc}"
    if (exe.exists() and marker.exists() and marker.read_text() == want
            and not FORCE):
        return True, "cached"
    cmd = [cc, "-O1", "-g0", "-o", str(exe), str(test)] + \
        [str(s) for s in sources] + [f"-I{i}" for i in INCLUDES]
    if lang == "c++":
        cmd += ["-Wall", "-Wextra"]
    r = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    if verbose and r.stderr.strip():
        print(r.stderr.strip())
    if r.returncode != 0:
        err = [l for l in r.stderr.strip().splitlines() if l.strip()]
        return False, "build failed: " + (err[-1] if err else "?")
    marker.write_text(want)
    return True, "built"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true",
                    help="show compiler and test output")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even when the cache stamp matches")
    a = ap.parse_args()

    global FORCE
    FORCE = a.force
    if not (UI / "CMakeLists.txt").exists():
        print("ui_check: FAIL recomp-ui submodule missing "
              "(git submodule update --init)")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    ran, failed = [], []
    for binary, test, sources, lang in BINARIES:
        if not test.exists():
            failed.append(f"{binary}: missing {test.name}")
            continue
        ok, detail = build(binary, test, sources, lang, a.verbose)
        if not ok:
            failed.append(f"{binary}: {detail}")
            continue
        r = subprocess.run([str(OUT / binary)], cwd=str(REPO),
                           capture_output=True, text=True)
        if a.verbose:
            print(f"--- {binary} ---")
            print(r.stdout.strip())
            if r.stderr.strip():
                print(r.stderr.strip())
        last = (r.stdout.strip().splitlines() or [""])[-1]
        if r.returncode != 0:
            err = [l for l in (r.stderr or r.stdout).strip().splitlines()
                   if l.strip()]
            failed.append(f"{binary}: exit {r.returncode} "
                          f"({err[-1] if err else 'no output'})")
        else:
            ran.append(f"{binary}: {last or 'ok'}")

    secs = time.time() - t0
    if failed:
        print("ui_check: FAIL " + " ".join(failed))
        return 1
    print(f"ui_check: OK recomp-ui runtime UI tests "
          f"({len(ran)} binaries, {secs:.1f}s)"
          + (" - " + "; ".join(ran) if a.verbose else ""))
    return 0


FORCE = False

if __name__ == "__main__":
    sys.exit(main())
