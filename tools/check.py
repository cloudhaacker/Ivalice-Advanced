#!/usr/bin/env python3
"""One-command regression gate for the FFTA recomp worktree.

Runs: host unit tests (C++ + Python) -> recomp-ui runtime-UI tests (the
patched settings overlay) -> patch validity -> device-free Android checks ->
attract golden gate -> widescreen smoke (margin census / center-crop / stale
guard, needs the local game.state1/state2 fixtures) -> render-path cadence
gate (60 Hz scheduler invariants + no every-other-frame consumer on the
presented surfaces) -> strict route replays
(user save-load repro, session G, session K, battle movement route B) against
the frozen fixtures in saves/regress/.

The checks are independent processes, so they run concurrently by default
(--jobs; auto = min(8, cpus)). Each game run gets isolated outputs — its own
battery-save copy and its own GBARECOMP_COVERAGE_JSON path in the temp dir —
so concurrent runs can't race on the shared fixture save or the repo-root
coverage file. Use --jobs 1 for the old serial order.

Every check prints PASS/FAIL with a one-line summary; exit 0 only if all
pass. Fixtures are local-only (gitignored, like all saves/traces). The save
fixture is sha-verified so an accidental overwrite fails loudly instead of
silently redefining the baseline.

Usage:
  .venv/bin/python tools/check.py            # everything (~1.5-2 min)
  .venv/bin/python tools/check.py --fast     # unit tests + ui tests + android checks + raylib default probe + attract
  .venv/bin/python tools/check.py --jobs 1   # serial
  .venv/bin/python tools/check.py --only NAME[,NAME...]

CI tier 1 runs the no-private-material subset (no ROM/savestates needed;
the launch BIOS is committed clean-room repo material since the emibios
swap): `--only unit-cpp,unit-py,ui-tests,patches,android-static` — see
tests/README.md § Continuous integration.

Opt-in suite (not in the default run): `android-apk` — the content guard for
a built APK (`tools/android_apk_check.py`); it needs an Android build, so
select it explicitly with `--only android-apk`.
"""
import argparse
import concurrent.futures
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
EXE = REPO / "build/FFTARecomp"
BIOS = REPO / "bios/emibios_gba_bios.bin"
ROM = REPO / "game.gba"
REG = REPO / "saves/regress"
FIXTURE_SAVE = REG / "skyemu_20261007.sav"
FIXTURE_SHA_PREFIX = "65742af1"


def clean_env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GBARECOMP_")}


def run(cmd, env=None, timeout=600):
    return subprocess.run(cmd, cwd=str(REPO), env=env or clean_env(),
                          capture_output=True, text=True, timeout=timeout)


def check_unit_cpp():
    b = run(["cmake", "--build", "build", "--target", "ffta_unit_tests",
             "--parallel", "8"])
    if b.returncode != 0:
        return False, "build failed: " + b.stderr.strip()[-160:]
    r = run([str(REPO / "build/ffta_unit_tests")])
    line = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode == 0 and "PASS" in line, line


def check_unit_py():
    r = run([sys.executable, "tests/python/test_tools.py"])
    line = (r.stdout.strip().splitlines() or [""])[-1]
    if r.returncode != 0 and not line.strip():
        # unittest reports and import tracebacks go to stderr; without this
        # fallback the table shows an empty detail for those failures.
        err = [l for l in r.stderr.strip().splitlines() if l.strip()]
        line = next((l for l in reversed(err) if "error" in l.lower()),
                    err[-1] if err else f"exit {r.returncode}")
    return r.returncode == 0, line


def check_attract():
    r = run([sys.executable, "tools/attract_check.py"], timeout=900)
    line = next((l for l in r.stdout.splitlines() if "attract_verify" in l), "")
    return r.returncode == 0 and "PASS" in line, line or f"exit {r.returncode}"


def check_hle_audit():
    """BIOS HLE zero-fallback audit (tools/hle_audit.py): attract + battle
    route B under forced HLE must be FULLY_STATIC with every executed SWI
    HLE-taken (no silent LLE fallback) and the route-B frame matching its
    pin. Guards the release-hygiene story: HLE must actually service the
    SWIs, not just be enabled."""
    r = run([sys.executable, "tools/hle_audit.py"], timeout=1800)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    if r.returncode == 2:
        return False, line or "fixtures missing"
    return r.returncode == 0, line or f"exit {r.returncode}"


def strict_route(trace, frames):
    if not trace.exists():
        return False, f"missing fixture {trace.name}"
    env = clean_env()
    env["GBARECOMP_STRICT_STATIC"] = "1"
    env["GBARECOMP_INPUT_REPLAY"] = str(trace)
    # Parallel safety: each run gets its own save copy (the runner flushes
    # "<save>.tmp" then renames; runs sharing one path would race) and its own
    # coverage-json path (runs otherwise clobber recomp_coverage_*.json in the
    # repo root).
    save = FIXTURE_SAVE
    if FIXTURE_SAVE.exists():
        save = pathlib.Path(tempfile.gettempdir()) / f"ffta_check_{trace.stem}.sav"
        shutil.copyfile(FIXTURE_SAVE, save)
    env["GBARECOMP_COVERAGE_JSON"] = str(
        pathlib.Path(tempfile.gettempdir()) / f"ffta_check_{trace.stem}_cov.json")
    r = run([str(EXE), "--bios", str(BIOS), "--rom", str(ROM),
             "--save-path", str(save), "--frames", str(frames),
             "--no-window"], env=env, timeout=1800)
    cov = next((l for l in r.stdout.splitlines()
                if "self_heal_coverage" in l), "")
    return r.returncode == 0 and "FULLY_STATIC" in cov, cov or f"exit {r.returncode}"


def strict_route_state(trace, state, save, frames):
    for p in (trace, state, save):
        if not p.exists():
            return False, f"missing fixture {p.name}"
    env = clean_env()
    env["GBARECOMP_STRICT_STATIC"] = "1"
    env["GBARECOMP_INPUT_REPLAY"] = str(trace)
    # Parallel safety: own save copy (the runner flushes "<save>.tmp" then
    # renames) and own coverage-json path (see strict_route).
    run_save = pathlib.Path(tempfile.gettempdir()) / f"ffta_check_{trace.stem}.sav"
    shutil.copyfile(save, run_save)
    env["GBARECOMP_COVERAGE_JSON"] = str(
        pathlib.Path(tempfile.gettempdir()) / f"ffta_check_{trace.stem}_cov.json")
    r = run([str(EXE), "--bios", str(BIOS), "--rom", str(ROM),
             "--save-path", str(run_save), "--load-state", str(state),
             "--frames", str(frames),
             "--no-window"], env=env, timeout=1800)
    cov = next((l for l in r.stdout.splitlines()
                if "self_heal_coverage" in l), "")
    return r.returncode == 0 and "FULLY_STATIC" in cov, cov or f"exit {r.returncode}"


def check_ws_smoke():
    # Inner --jobs stays small: this check runs inside the outer pool, so
    # 8x8 nested engine runs would oversubscribe the machine.
    r = run([sys.executable, "tools/ws_check.py", "--jobs", "4"], timeout=1800)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    if r.returncode == 2:
        # Missing or sha-changed local savestate fixtures; the tool's SKIP
        # line carries the reason (fresh clones have no states by design).
        return False, line or "fixtures missing (saves/ws_fixtures)"
    return r.returncode == 0, line or f"exit {r.returncode}"


def check_cadence():
    """Render-path cadence gate (tools/cadence_probe.py): the
    compute-at-60/read-at-30 detector. Steps one VBlank at a time on the
    battle-overview pan fixture and asserts the 60 Hz scheduler
    invariants (frame_step staging parities toggle per VBlank,
    gVblankCounter +1/step) plus no every-other-frame consumer on the
    presented surfaces (io/oam/pal/vram + display-reg shadow). Guards the
    BRINGUP § 2026-10-12 (late 12) verdict: ffta's render path is 60 Hz
    end to end (no 30 Hz read gate to patch)."""
    r = run([sys.executable, "tools/cadence_probe.py", "--frames", "96",
             "--strict", "--state", str(REPO / "game.state1")], timeout=600)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    if r.returncode == 2:
        # Missing local state fixture (fresh clones have none by design).
        return False, line or "fixtures missing (game.state1)"
    return r.returncode == 0 and "cadence_probe: PASS" in line, line


def check_ui_tests():
    """recomp-ui's runtime-UI tests (tools/ui_check.py): the settings overlay
    is a patched submodule, so its model + ImGui presentation tests must run,
    not just the diff be validated by the patches check."""
    r = run([sys.executable, "tools/ui_check.py"], timeout=900)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode == 0 and "ui_check: OK" in line, line


def check_savecheck():
    r = run([sys.executable, "tools/savecheck.py", str(FIXTURE_SAVE)], timeout=120)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode == 0 and "savecheck: OK" in line, line


def check_patches():
    """tools/patches/*.patch must be real diffs matching the pinned submodules:
    apply-able forward to a pristine tree, or reversible from the patched dev
    tree. Catches mangled/empty exports (2026-10-08 regression). Patches named
    arm-recomp-core-* target the nested external/arm-recomp-core repo and
    recomp-ui-* the recomp-ui submodule; all others target gbarecomp itself."""
    details = []
    ok = True
    names = sorted(p.name for p in (REPO / "tools" / "patches").glob("*.patch"))
    if not names:
        return False, "no *.patch files found"
    for name in names:
        p = REPO / "tools/patches" / name
        if not p.exists():
            ok = False
            details.append(f"{name}: missing")
            continue
        if name.startswith("arm-recomp-core"):
            root = "gbarecomp/external/arm-recomp-core"
        elif name.startswith("recomp-ui"):
            root = "recomp-ui"
        else:
            root = "gbarecomp"
        fwd = run(["git", "-C", root, "apply", "--check", str(p)])
        if fwd.returncode == 0:
            details.append(f"{name}: forward-ok")
            continue
        rev = run(["git", "-C", root, "apply", "--check",
                   "--reverse", str(p)])
        if rev.returncode == 0:
            # Reverse-ok on a local dev tree is NOT enough for CI: a fresh
            # checkout validates the SAME file forward against the pristine
            # pin, and a dev-based export (context interleave from other
            # local features) goes INVALID there (2026-10-09: both
            # regenerated reference diffs broke tier-1 this way). A pristine
            # submodule has no local edits, so forward-apply there is the
            # cheap equivalent of the pin-based export — enforce it.
            pin_ok = None
            with tempfile.TemporaryDirectory(prefix="gbpin.") as td:
                pr = subprocess.run(
                    ["bash", "-c",
                     f"git -C {root} archive HEAD | tar -x -C {td}"],
                    cwd=str(REPO), capture_output=True, text=True)
                if pr.returncode == 0:
                    pf = subprocess.run(
                        ["git", "-C", td, "apply", "--check", str(p)],
                        capture_output=True, text=True)
                    if pf.returncode != 0:
                        ok = False
                        details.append(
                            f"{name}: INVALID on pristine pin "
                            f"(CI condition; rebase pin-based)")
                    else:
                        pin_ok = True
            details.append(f"{name}: reverse-ok (applied)"
                           + (", pin-forward-ok" if pin_ok else ""))
        else:
            ok = False
            details.append(f"{name}: INVALID")
    # Replay integrity: pin + the consolidated patch must byte-match the dev
    # tree. This catches submodule drift (unrecorded edits) and any mangling
    # the per-file forward/reverse checks would miss. The per-feature files
    # are reference diffs and deliberately are NOT stacked here (their
    # contexts interleave after historical re-exports; the consolidated
    # patch is the canonical re-apply unit). Same for the nested
    # arm-recomp-core repo with its own consolidated patch.
    for root, cons_name, label in (
            ("gbarecomp", "gbarecomp-local.patch", "gbarecomp-local"),
            ("gbarecomp/external/arm-recomp-core",
             "arm-recomp-core-local.patch", "arm-recomp-core-local"),
            ("recomp-ui", "recomp-ui-local.patch", "recomp-ui-local")):
        cons = REPO / "tools" / "patches" / cons_name
        if not cons.exists():
            continue
        with tempfile.TemporaryDirectory(prefix="gbpatch.") as td:
            arch = subprocess.run(
                ["bash", "-c", f"git -C {root} archive HEAD | tar -x -C {td}"],
                cwd=str(REPO), capture_output=True, text=True)
            app = subprocess.run(
                ["patch", "-p1", "-s", "-f", "--no-backup-if-mismatch",
                 "-i", str(cons)], cwd=td, capture_output=True, text=True)
            if arch.returncode != 0 or app.returncode != 0:
                ok = False
                details.append(f"{label} replay: apply FAILED")
            else:
                # The byte-compare below is a LOCAL-dev-tree guarantee: pin+
                # patch must equal the submodule tree that carries the
                # uncommitted framework edits. A pristine checkout (CI) has
                # no local edits — its tree IS the pin, so the clean apply
                # above already proved patch<->pin fidelity and the compare
                # would false-red on every patched file. Skip it there.
                # Tracked modifications only (-uno): untracked build junk
                # must not force the compare.
                pristine = not run(
                    ["git", "-C", root, "status", "--porcelain", "-uno"]
                ).stdout.strip()
                if pristine:
                    details.append(
                        f"{label} replay: apply-ok (pristine submodule)")
                    continue
                tracked = run(["git", "-C", root, "ls-files"]).stdout.split()
                bad = []
                for f in tracked:
                    dev = REPO / root / f
                    if not dev.is_file():
                        continue  # gitlinks and directories
                    rep = pathlib.Path(td) / f
                    if not rep.exists() or rep.read_bytes() != dev.read_bytes():
                        bad.append(f)
                if bad:
                    ok = False
                    details.append(
                        f"{label} replay: {len(bad)} file(s) differ "
                        f"(e.g. {', '.join(bad[:3])})")
                else:
                    details.append(
                        f"{label} replay: {len(tracked)}-file tree matches")
    return ok, " ".join(details)


def _acceptance_lock():
    """Cross-process lock so concurrent check runs never race two acceptance
    games (they share evidence paths and would collide regardless of port)."""
    import fcntl
    lock_dir = REPO / "logs" / "desktop_accept"
    lock_dir.mkdir(parents=True, exist_ok=True)
    f = open(lock_dir / ".lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def check_desktop_accept():
    """Opt-in TCP-observed free-run acceptance of the suspend-save press
    (tools/desktop_accept.py --mode tcp). Skips without game.state3 /
    saves/playtest.sav, or while another acceptance holds the lock."""
    if not (REPO / "game.state3").exists() or not (REPO / "saves" / "playtest.sav").exists():
        return True, "skipped (needs game.state3 + saves/playtest.sav)"
    lock = _acceptance_lock()
    if lock is None:
        return True, "skipped (another acceptance running)"
    try:
        r = run([sys.executable, "tools/desktop_accept.py", "--mode", "tcp",
                 "--port", "19878", "--work", "logs/desktop_accept/tcp",
                 "--observe", "60"], timeout=300)
    finally:
        lock.close()
    if r.returncode == 77:
        return True, "skipped (prerequisites missing)"
    if r.returncode == 0:
        return True, "PASS: desktop acceptance (tcp free-run)"
    return False, f"FAIL: desktop acceptance rc={r.returncode}"


def check_desktop_accept_window():
    """Opt-in WINDOWED acceptance (present-in-place path): play.sh +
    --tcp-observe + ydotool press, scored identically. This is the path
    where the abandon-resume one-unwind hook and mode coherence matter
    (present-in-place never unwinds on VBlank by design). Skips (rc 77)
    without a display / ydotool / state3 / playtest.sav."""
    if not (REPO / "game.state3").exists() or not (REPO / "saves" / "playtest.sav").exists():
        return True, "skipped (needs game.state3 + saves/playtest.sav)"
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return True, "skipped (needs a display)"
    if shutil.which("ydotool") is None:
        return True, "skipped (needs ydotool)"
    lock = _acceptance_lock()
    if lock is None:
        return True, "skipped (another acceptance running)"
    try:
        r = run([sys.executable, "tools/desktop_accept.py", "--mode", "window",
                 "--port", "19879", "--work", "logs/desktop_accept/window",
                 "--observe", "60"], timeout=300)
    finally:
        lock.close()
    if r.returncode == 77:
        return True, "skipped (prerequisites missing)"
    if r.returncode == 0:
        return True, "PASS: desktop acceptance (windowed present-in-place)"
    return False, f"FAIL: windowed desktop acceptance rc={r.returncode}"


def check_hangrepro():
    """Opt-in deterministic press repro (tools/hangrepro.py): the state3
    suspend->A hang must stay bounded (pre-guard it SIGSEGV'd at ~+26 steps;
    now the process survives with host-stack guard unwinds). Needs the
    gitignored game.state3 + saves/playtest.sav; reports skipped otherwise."""
    r = run([sys.executable, "tools/hangrepro.py"], timeout=600)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    if r.returncode == 77:
        return True, "skipped (no game.state3 / saves/playtest.sav)"
    return r.returncode == 0, line or f"exit {r.returncode}"


def check_raylib_compile():
    """Compile the RaylibBackend against real raylib 6 (opt-in).

    Phase 4c made raylib the DEFAULT: this configures the canonical `build/`
    dir with NO raylib flag and asserts the framework's effective flag. If the
    default regresses to OFF, that assertion fails and names the regression
    (the present-test target would also vanish, but its error would read
    "unknown target" instead).

    Nothing else builds the raylib path on a fresh checkout, so it could
    silently stop compiling while every other gate stays green. Builds just the
    backend target -- not raylib itself, not the game.

    It ALSO compiles the backend with the flag OFF (stub build, second build
    dir). The backend file must compile in both configurations: Slice B/C
    helpers were once declared inside `#if defined(GBARECOMP_USE_RAYLIB)` but
    called from unguarded setters, which broke the other configuration while
    the raylib tree stayed green -- and no gate built that configuration, so it
    survived several sessions. This is the gate that closes that class, and the
    explicit OFF is what keeps a default flip from silently dropping this half.

    Opt-in rather than default: the first configure fetches and builds raylib,
    which is minutes. Once cached in build/ it is a few seconds. The stub dir
    needs no raylib at all (flag OFF skips the fetch), so it is cheap and
    offline from the first run.

    Needs network on first run (raylib is fetched by SHA). Skips cleanly when
    the raylib tree is absent (CI before Phase 7)."""
    if not (REPO / "gbarecompx/src/runtime/raylib_backend.cpp").exists():
        return True, "skipped (no gbarecompx tree)"

    # Configure from the ROOT project with DEFAULTS ONLY -- the no-flag
    # configure IS the Phase 4c contract (raylib is the product backend), and
    # this is the same dir every app suite runs from. It wires GBARECOMP_ROOT /
    # mods / the app target the runtime needs. A build dir caches its source
    # directory, so pointing a -S at the framework subdir against the same dir
    # is rejected by CMake.
    build = REPO / "build"
    src = REPO
    # NB: cmake, not sys.executable -- "-S" is also a Python flag and would be
    # silently swallowed as one, turning this into `python -S <dir>`.
    cfg = ["cmake", "-S", str(src), "-B", str(build), "-G", "Ninja",
           "-DCMAKE_BUILD_TYPE=Release"]
    r = run(cfg, timeout=900)
    if r.returncode != 0:
        return False, f"configure failed (raylib fetched by SHA; needs network)"

    # The effective flag, not the request: "GBARECOMP_USE_RAYLIB was requested"
    # is not the same claim as "raylib was fetched and linked".
    if "GBARECOMP_RAYLIB_ENABLED:INTERNAL=ON" not in (
            build / "CMakeCache.txt").read_text():
        return False, ("default configure did not select raylib: the Phase 4c "
                       "default flip regressed (GBARECOMP_RAYLIB_ENABLED is "
                       "not ON)")

    r = run(["cmake", "--build", str(build), "--target",
             "gbarecomp_raylib_backend", "--parallel", "4"], timeout=900)
    if r.returncode != 0:
        errs = [ln for ln in (r.stdout + r.stderr).splitlines()
                if "error:" in ln]
        return False, (errs[0].strip() if errs else "raylib backend build failed")

    # The OFF half: same file must compile as a stub. Uses its own build dir
    # (a dir caches its source AND its flag set -- reconfiguring build/ OFF
    # and back would thrash the cached raylib build).
    # Explicit OFF rather than relying on the default, so a default flip can
    # never silently drop this half. No raylib fetch happens with the flag
    # off, so this half is offline-cheap.
    stub = REPO / "build-raylib-stub"
    r = run(["cmake", "-S", str(src), "-B", str(stub), "-G", "Ninja",
             "-DCMAKE_BUILD_TYPE=Release", "-DGBARECOMP_USE_RAYLIB=OFF"],
            timeout=900)
    if r.returncode != 0:
        return False, "stub configure failed"
    r = run(["cmake", "--build", str(stub), "--target",
             "gbarecomp_raylib_backend", "--parallel", "4"], timeout=900)
    if r.returncode != 0:
        errs = [ln for ln in (r.stdout + r.stderr).splitlines()
                if "error:" in ln]
        return False, ("stub (USE_RAYLIB=OFF) backend build failed: " +
                       (errs[0].strip() if errs
                        else "raylib_backend.cpp does not compile as a stub"))

    # Compiling is not running. Build and run the integration test too: it opens
    # a real GL context, uploads frames and closes, which is the only thing that
    # catches a raylib call that typechecks but misbehaves. (This already earned
    # its keep: it found that open() hid the window whenever linear filtering was
    # off -- the default -- so a default launch was invisible.)
    r = run(["cmake", "--build", str(build), "--target",
             "ffta_raylib_present_tests", "--parallel", "4"], timeout=900)
    if r.returncode != 0:
        errs = [ln for ln in (r.stdout + r.stderr).splitlines()
                if "error:" in ln]
        return False, (errs[0].strip() if errs else "raylib present test build failed")

    exe = build / "ffta_raylib_present_tests"
    if not exe.exists():
        return True, "backend compiles (ON+OFF; raylib present test not built)"

    # Finding a display is part of the gate. A real one is the strongest signal,
    # so prefer it; otherwise fall back to Xvfb with Mesa's software rasterizer
    # (llvmpipe), which is the standard headless recipe for GL on a CI runner
    # that has no GPU and no /dev/dri. Only if neither exists do we skip.
    env = clean_env()
    cmd = [str(exe)]
    how = "real display"
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        if shutil.which("xvfb-run") is None:
            return True, ("backend compiles; present test SKIPPED "
                          "(no display and no xvfb-run)")
        cmd = ["xvfb-run", "-a", "--server-args=-screen 0 1280x800x24",
               str(exe)]
        # No GPU here, so ask Mesa for the software rasterizer explicitly
        # instead of relying on driver autodetection. GL 4.5 covers raylib's
        # 3.3 core requirement; the override is belt-and-braces for older Mesa.
        env["LIBGL_ALWAYS_SOFTWARE"] = "1"
        env["GALLIUM_DRIVER"] = "llvmpipe"
        env["MESA_GL_VERSION_OVERRIDE"] = "4.5"
        how = "Xvfb + llvmpipe"

    r = run(cmd, env=env, timeout=300)
    tail = (r.stdout + r.stderr).strip().splitlines() or [""]
    if r.returncode != 0:
        bad = [ln.strip() for ln in tail if "FAIL" in ln]
        return False, (bad[0] if bad else tail[-1].strip() or "present test failed")
    ran = "running against a real GL context" in (r.stdout + r.stderr)
    if not ran:
        return True, f"backend compiles (ON+OFF); present test SKIPPED (no {how})"
    return True, f"backend compiles (ON+OFF); present test PASSED ({how})"


def check_raylib_backend():
    """RaylibBackend completeness + guard self-test.

    The WindowBackend seam only pays off if the backend implements the WHOLE
    interface. `override` catches signature drift but NOT a newly-added virtual
    the backend fails to override -- that silently inherits the default.
    tools/check_raylib_backend_complete.py closes that gap with three checks:
    the single-generation markers, purity of every interface method, and
    per-interface attribution (each method overridden at ITS OWN impl site -- a
    method implemented in the wrong impl class is caught since Phase 4d). Its
    self-test covers the parser cases that have bitten us (function-pointer
    args, pointer spacing, overloads) plus the attribution cases.

    Runs where the raylib tree exists; elsewhere it skips (the pinned
    gbarecomp/ has no raylib backend). Cheap -- pure Python, no build."""
    if not (REPO / "gbarecompx/src/runtime/raylib_backend.h").exists():
        return True, "skipped (no gbarecompx tree)"

    r = run([sys.executable, "tools/tests/test_check_raylib_backend_complete.py"],
            timeout=120)
    if r.returncode != 0:
        line = (r.stdout.strip().splitlines() or [""])[-1]
        return False, f"guard self-test failed: {line}"

    r = run([sys.executable, "tools/check_raylib_backend_complete.py"], timeout=120)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode == 0, line or f"exit {r.returncode}"


def check_android_static():
    """Device-free Android checks (tools/android_static_check.py): identity
    pin consistency, the mods payload contract, tracked-file hygiene, and a
    fake-adb self-test of the device gate script. Needs only the checkout —
    no SDK, no device, no private material."""
    r = run([sys.executable, "tools/android_static_check.py"], timeout=300)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode == 0, line or f"exit {r.returncode}"


def check_android_apk():
    """Content guard for a built APK (tools/android_apk_check.py): payload
    vs staging sources, private-embed pins, per-ABI libs, manifest facts,
    duplicate/stray/oversize zip entries. Opt-in — it needs a built APK
    (--only android-apk; build first: android/README.md § Build)."""
    r = run([sys.executable, "tools/android_apk_check.py"], timeout=600)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode == 0, line or f"exit {r.returncode}"


def check_release():
    """Desktop release packager (tools/make_release.py): allowlist stage ->
    private-material sweep -> deterministic portable zip (issue #3, R-track).
    Opt-in — it needs a built (and fresh) tree, but never the ROM: the sweep
    would reject the ROM anyway (--only release)."""
    r = run([sys.executable, "tools/make_release.py"], timeout=900)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode == 0, line or f"exit {r.returncode}"


def check_backend_default():
    """The canonical build dir is the raylib product build (Phase 4c).

    The default flip is only real if the dir every app suite runs from was
    configured with it: `build/` must carry the framework's effective raylib
    flag, and (when built) the selection predicate must agree. Cheap: reads the
    cache and runs one small binary; no configure, no fetch. Skips cleanly when
    the raylib tree is absent (CI before Phase 7) or the canonical dir is not
    configured (tier-1-only checkouts)."""
    if not (REPO / "gbarecompx/src/runtime/raylib_backend.cpp").exists():
        return True, "skipped (no gbarecompx tree)"
    cache = REPO / "build/CMakeCache.txt"
    if not cache.exists():
        return True, "skipped (build/ not configured)"
    if "GBARECOMP_RAYLIB_ENABLED:INTERNAL=ON" not in cache.read_text():
        return False, ("build/ is not the raylib product build: "
                       "GBARECOMP_RAYLIB_ENABLED is not ON (Phase 4c default "
                       "regressed, or the dir was configured with "
                       "-DGBARECOMP_USE_RAYLIB=OFF)")
    exe = REPO / "build/ffta_backend_select_tests"
    if not exe.exists():
        return True, "build/ is raylib (selection binary not built)"
    r = run([str(exe)])
    line = (r.stdout.strip().splitlines() or [""])[-1]
    if r.returncode != 0 or "raylib=1" not in line:
        return False, f"backend_select disagrees: {line or f'exit {r.returncode}'}"
    return True, "build/ is raylib; backend_select raylib=1"


CHECKS = {
    "unit-cpp": check_unit_cpp,
    "unit-py": check_unit_py,
    "ui-tests": check_ui_tests,
    "savecheck": check_savecheck,
    "patches": check_patches,
    "android-static": check_android_static,
    "raylib-backend": check_raylib_backend,
    "backend-default": check_backend_default,
    "raylib-compile": check_raylib_compile,
    "hangrepro": check_hangrepro,
    "desktop-accept": check_desktop_accept,
    "desktop-accept-window": check_desktop_accept_window,
    "android-apk": check_android_apk,
    "release": check_release,
    "cadence": check_cadence,
    "attract": check_attract,
    "hle-audit": check_hle_audit,
    "ws_smoke": check_ws_smoke,
    "user_load": lambda: strict_route(REG / "user_load_trace.csv", 1600),
    "route_G": lambda: strict_route(REG / "sessionG_trace.csv", 19400),
    "route_K": lambda: strict_route(REG / "sessionK_trace.csv", 29884),
    "route_B": lambda: strict_route_state(REG / "battle_move_trace.csv",
                                          REG / "battle_move_start.state",
                                          REG / "battle_move.sav", 5600),
}
FAST = ["unit-cpp", "unit-py", "ui-tests", "savecheck", "patches",
        "android-static", "raylib-backend", "backend-default", "attract"]
# Opt-in suites, left out of the default run (they need local artifacts a
# desktop-only worktree may not have); --only NAME runs them explicitly.
# release: the zip packager — needs a built tree (no ROM), and its output
# is a public artifact contract, so it runs explicit, never by default.
# raylib-compile is opt-in locally (its first run fetches + builds raylib, minutes)
# but IS run by CI: the raylib-backend job in .github/workflows/ci.yml needs no ROM
# and no display, so it is cheap enough to gate every push. It skips cleanly while
# gbarecompx/ is untracked.
OPTIONAL = {"android-apk", "release", "raylib-compile"}
# Checks that execute the game binary (require it to exist); the others run
# on a fresh clone without the ROM (CI tier 1: unit-cpp, unit-py, ui-tests,
# patches).
NEEDS_EXE = {"attract", "hle-audit", "ws_smoke", "user_load", "route_G",
             "route_K", "route_B", "cadence"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--only",
                    help="comma-separated subset, e.g. "
                         "unit-cpp,unit-py,patches,android-static")
    ap.add_argument("--jobs", type=int, default=0,
                    help="concurrent checks (default: auto = min(8, cpus); "
                         "1 = serial)")
    a = ap.parse_args()
    names = []
    if a.only:
        names = [n.strip() for n in a.only.split(",") if n.strip()]
        unknown = [n for n in names if n not in CHECKS]
        if unknown:
            print("check: unknown check(s): " + ", ".join(unknown) +
                  " (known: " + ", ".join(sorted(CHECKS)) + ")")
            return 1
    needs_exe = [n for n in names if n in NEEDS_EXE]
    if needs_exe and not EXE.exists():
        print(f"check: {EXE} missing - build the game first "
              f"(needed by: {', '.join(needs_exe)}; see AGENTS.md)")
        return 1
    if FIXTURE_SAVE.exists():
        h = hashlib.sha256(FIXTURE_SAVE.read_bytes()).hexdigest()
        if not h.startswith(FIXTURE_SHA_PREFIX):
            print(f"check: regress save sha256 {h[:12]}... != frozen "
                  f"{FIXTURE_SHA_PREFIX} - regenerate fixtures deliberately "
                  "before trusting results")
            return 1
    names = names if a.only else (
        FAST if a.fast else [n for n in CHECKS if n not in OPTIONAL])
    jobs = a.jobs if a.jobs > 0 else min(8, os.cpu_count() or 4)
    jobs = max(1, min(jobs, len(names)))
    print(f"check: {len(names)} check(s), jobs={jobs}", flush=True)

    def run_one(name):
        t0 = time.time()
        try:
            ok, detail = CHECKS[name]()
        except Exception as exc:  # keep the gate summarizing on crashes/timeouts
            ok, detail = False, f"exception: {exc}"
        return name, ok, detail, time.time() - t0

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(run_one, n) for n in names]
        for fut in concurrent.futures.as_completed(futures):
            n, ok, detail, dt = fut.result()
            print(f"[{'PASS' if ok else 'FAIL'}] {n:9s} {dt:6.1f}s  {detail}",
                  flush=True)
            results.append((n, ok))
    failed = [n for n, ok in results if not ok]
    print(f"check: {'ALL PASS' if not failed else 'FAILED: ' + ', '.join(failed)} "
          f"({len(results) - len(failed)}/{len(results)})")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
