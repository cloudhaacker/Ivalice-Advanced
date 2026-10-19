#!/usr/bin/env python3
"""build_apk.py — Android bootstrap: from a working checkout to a device-ready APK.

Mirrors build.py's step pattern for the Android target. The public app shell
imports the ROM through the phone's SAF picker at first run; the launch BIOS
is the bundled clean-room emibios (LGPL; committed at bios/ and staged into
the payload — issue #17), so no BIOS is ever picked or embedded. The
practical path is the **private test build** (ROM embedded, debug-signed),
which this script drives:

  1. preflight     JDK 21 on PATH or JAVA_HOME (Gradle 8.11.1 rejects 27),
                   ANDROID SDK platform+build-tools+NDK, the raylib Android
                   scaffold (gbarecompx/platform/android), `generated/`
                   corpus present and fresh (regenerate with build.py /
                   tools/cycle.py on desktop — an Android build cannot)
  2. gradle        ./gradlew :app:assembleDebug -PgbaAbis=<abi>
                   -PprivateRom (path relative to android/; the BIOS arrives
                   via the payload staging, not a private flag)
  3. content guard tools/android_apk_check.py --expect private
                   (payload matches staging, embedded ROM hash-verified
                   against the pin, packaging sanity)
  4. install+gate  optional (default on with a device attached): adb install
                   and the boot-health gate tools/validate_android.sh

Flags: --abi <abi> (default arm64-v8a), --jobs N (native compile parallelism),
       --install/--no-install (default: install when exactly one device is
       attached), --skip-check (skip the content guard), --no-gate (install
       without the device gate).

The private APK is debug-signed and named *-PRIVATE-rom-included.apk —
never commit or distribute it (.gitignore covers *.apk). Public builds
(drop the -PprivateRom flag) embed nothing user-supplied; the ROM arrives
via the phone UI.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
ANDROID = REPO / "android"
ROM = REPO / "game.gba"
ROM_SHA1 = "4ac05441f4de70a4ec3dd932116346c61b8783d9"
BIOS = REPO / "bios/emibios_gba_bios.bin"
BIOS_SHA1 = "0c0d404d16c6b55b3071aba714f82077da132f14"
ROM_SIZE = 16777216
BIOS_SIZE = 16384
GRADLE_MIN_JDK = (21, 21)  # Gradle 8.11.1: JDK 21 works; JDK 27 is too new
ANDROID_SCAFFOLD = REPO / "gbarecompx/platform/android/cpp/CMakeLists.txt"
APK_DIR = ANDROID / "app/build/outputs/apk/debug"
PRIVATE_MARKER = "-PRIVATE-rom-included.apk"
PACKAGE = "org.gbarecomp.fftarecomp"
# Sources the accepted APK must not be older than: if Gradle calls the build
# UP-TO-DATE while any of these are newer, the artifact is silently stale.
# (Payload-vs-staging drift is additionally caught by the content guard, which
# byte-compares the packaged payload against these sources.)
FRESHNESS_INPUTS = (
    REPO / "game.toml",
    REPO / "src/main.cpp",
    REPO / "CMakeLists.txt",
    ANDROID / "game_android.toml",
    ANDROID / "app/build.gradle",
    ANDROID / "payload/mods/state.toml",
)


class Fail(Exception):
    def __init__(self, msg, hint=None):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


def die(msg, hint=None):
    raise Fail(msg, hint)


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run(cmd, cwd=REPO, capture=True, timeout=3600):
    try:
        return subprocess.run([str(c) for c in cmd], cwd=str(cwd),
                              capture_output=capture, text=True,
                              timeout=timeout)
    except FileNotFoundError:
        die(f"command not found: {cmd[0]}",
            hint="install the build dependencies (android/README.md § Build)")


def run_ok(cmd, cwd=REPO):
    return run(cmd, cwd=cwd).returncode == 0


def tail(proc, n=20):
    text = (proc.stdout or "") + (proc.stderr or "")
    return "\n".join(text.strip().splitlines()[-n:])


# --- preflight ---------------------------------------------------------------

def find_java():
    """JDK >= 17 & < 27: JAVA_HOME first, then the `java` on PATH, then common
    distro locations. Gradle 8.11.1 caps at 23 in practice (21 verified)."""
    candidates = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]))
    which = shutil.which("java")
    if which:
        candidates.append(Path(which).resolve().parent.parent)
    candidates += [Path(p) for p in (
        "/usr/lib/jvm/java-21-openjdk",
        "/usr/lib/jvm/java-17-openjdk",
    )]
    for home in candidates:
        java = home / "bin/java"
        if not java.exists():
            continue
        r = run([java, "-version"])
        m = re.search(r'version "(\d+)', r.stderr or r.stdout)
        if not m:
            continue
        major = int(m.group(1))
        if major > 26:
            continue  # too new for Gradle 8.11.1
        return java, major
    return None, 0


def adb_devices_ready():
    r = run(["adb", "devices"], timeout=30)
    if r.returncode != 0:
        return -1
    lines = [l for l in r.stdout.splitlines()
             if l.strip() and not l.startswith("List of")]
    ready = [l for l in lines if l.split()[-1] == "device"]
    return len(ready)


def step_preflight(skip_stale=False, installing=True):
    java, major = find_java()
    if java is None:
        die("no usable JDK found (need >= 17 and <= 26 for Gradle 8.11.1)",
            hint="install JDK 21 (android/README.md § Build) "
                 "or set JAVA_HOME")
    # Gradle inherits this process' env, not our discovery: export what we
    # validated so the build below sees it. setdefault keeps an explicit
    # user export (or local.properties sdk.dir) authoritative.
    if "JAVA_HOME" not in os.environ:
        os.environ["JAVA_HOME"] = str(java.parent.parent)
        details = [f"JDK {major} ({java}; exported JAVA_HOME)"]
    else:
        details = [f"JDK {major} ({java})"]
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not sdk:
        # auto-discover the sdk
        for p in (Path.home() / "Android/Sdk", Path("/opt/android-sdk")):
            if p.is_dir():
                sdk = str(p)
                break
    if not sdk or not Path(sdk).is_dir():
        die("ANDROID SDK not found",
            hint="set ANDROID_HOME (android/README.md § Build)")
    ndk = Path(sdk) / "ndk"
    if not ndk.is_dir() or not any(ndk.iterdir()):
        die(f"no NDK under {ndk}",
            hint="install an NDK via sdkmanager (android/README.md)")
    if "ANDROID_HOME" not in os.environ:
        os.environ["ANDROID_HOME"] = sdk
        details.append(f"SDK {sdk} (exported ANDROID_HOME)")
    else:
        details.append(f"SDK {sdk}")
    # The raylib Android scaffold (the Gradle CMake root; Phase 4f retired
    # the shell submodule the old preflight pulled). The release always
    # builds the raylib/NativeActivity base.
    if not ANDROID_SCAFFOLD.is_file():
        die("raylib Android scaffold missing (gbarecompx/platform/android)",
            hint="the release builds the raylib/NativeActivity base; check "
                 "out the gbarecompx framework tree")
    details.append("Android scaffold ok (gbarecompx)")
    # dumps (re-checked by Gradle too, but fail early and clear): the ROM is
    # the user-supplied dump embedded by the private build; the BIOS is the
    # committed clean-room emibios staged into the payload (issue #17).
    for path, want, label, size in ((ROM, ROM_SHA1, "ROM", ROM_SIZE),
                                     (BIOS, BIOS_SHA1, "BIOS", BIOS_SIZE)):
        if not path.exists():
            die(f"{label} missing: {path}", hint="run build.py first "
                "(README § Quick start) — the private build embeds the ROM; "
                "the BIOS is committed repo material")
        if path.stat().st_size != size:
            die(f"{label} has the wrong size: {path}")
        if sha1_file(path) != want:
            die(f"{label} SHA-1 mismatch: {path}")
    details.append("dumps verified")
    # corpus freshness: an APK embeds the corpus via libmain.so's build;
    # generated/ must exist and not be older than game.toml
    generated = REPO / "generated/dispatch_table.cpp"
    if not generated.exists():
        die("no generated/ corpus", hint="run build.py (or tools/cycle.py) "
            "on desktop first — an Android build consumes it, cannot "
            "produce it")
    # Freshness gate: the recompiler preserves mtimes for byte-identical
    # output, so the emitted files cannot date a regen — build.py /
    # cycle.py stamp it (generated/.regen_stamp). No stamp = never regen'd
    # here; a stamp older than any build input = stale corpus.
    stamp = generated.parent / ".regen_stamp"
    if not stamp.exists():
        die("generated/ corpus has no regen stamp", hint="re-run build.py "
            "(or tools/cycle.py) on desktop — an Android build consumes "
            "the corpus, cannot produce it)")
    for source in FRESHNESS_INPUTS:
        if source.stat().st_mtime > stamp.stat().st_mtime:
            die("generated/ corpus is stale", hint="re-run build.py "
                "(%s is newer than the last regen)" % source.name)
    details.append("corpus present + fresh (regen stamp)")
    # Stale-device guard (2026-10-16 incident class): an installed APK older
    # than this checkout is how yesterday's bugs survive today's fixes — the
    # phone ran a build cut BETWEEN a menu bug and its fix for hours while
    # every local gate stayed green. Fail loudly; --skip-stale proceeds (and
    # installs this checkout, which is the cure anyway).
    if not skip_stale and device_attached():
        installed = installed_version_name()
        local = local_version_name()
        if installed and local and installed != local:
            # Installing IS the cure, so the default path warns and
            # proceeds; only a --no-install run (gating WITHOUT building —
            # the exposed path) dies, mirroring validate_android.sh 1b.
            msg = (f"device APK ({installed}) is not this checkout "
                   f"({local}) — a stale install hides fixed regressions "
                   "(the phone kept yesterday's menu bug for hours after "
                   "the fix landed)")
            if installing:
                print(f"      warn: {msg}; installing this checkout now")
                details.append(f"device APK stale ({installed}) — "
                               f"installing {local}")
            else:
                die(msg, hint="rebuild + install this checkout "
                    "(--skip-stale gates the stale build anyway)")
        if installed and local and installed == local:
            details.append(f"device APK matches this checkout ({installed})")
        elif not installed and local:
            details.append(f"device has no install yet (checkout {local})")
        if not submodule_pin_committed():
            print("      warn: gbarecompx checkout is NOT the recorded "
                  "submodule pin — the APK embeds an uncommitted engine "
                  "state; commit the bump so the device build is "
                  "reproducible")
    return ", ".join(details)


def device_attached():
    # Packaging runs on headless runners that may not have platform-tools
    # on PATH; no adb means no device to check, not a build failure.
    if shutil.which("adb") is None:
        return False
    r = run(["adb", "devices"], capture=True)
    if r.returncode != 0:
        return False
    for line in (r.stdout or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            return True
    return False


def installed_version_name():
    r = run(["adb", "shell", "dumpsys", "package", PACKAGE], capture=True)
    if r.returncode != 0:
        return None
    m = re.search(r"versionName=(\S+)", r.stdout or "")
    return m.group(1) if m else None


def local_version_name():
    r = run(["git", "describe", "--tags"], capture=True)
    if r.returncode != 0:
        return None
    out = (r.stdout or "").strip()
    if out.startswith("v"):
        out = out[1:]
    if out.endswith("-dirty"):
        out = out[: -len("-dirty")]
    return out or None


def submodule_pin_committed():
    r = run(["git", "submodule", "status", "gbarecompx"], capture=True)
    out = (r.stdout or "").strip()
    return r.returncode == 0 and bool(out) and not out.startswith("+")


# --- build -------------------------------------------------------------------

def step_gradle(abi, jobs):
    gradle = ANDROID / "gradlew"
    cmd = [gradle, ":app:assembleDebug",
           f"-PgbaAbis={abi}", f"-PgbaNativeJobs={jobs}",
           f"-PprivateRom={ROM}"]
    # Version from THIS checkout: the engine template falls back to the
    # identity block's static "0.1.0", which made every plain build look
    # stale against `git describe` (the stale-device guard's reference).
    version = local_version_name()
    if version:
        cmd.append(f"-PgbaVersionName={version}")
    r = run(cmd, cwd=ANDROID, capture=False)
    if r.returncode != 0:
        die("gradle assembleDebug failed (see output above)",
            hint="android/README.md § Build — JDK 21, SDK platform 35, "
                 "NDK, and the gbarecompx scaffold are the usual suspects")
    # An up-to-date Gradle build does not rewrite the APK; presence is enough,
    # but the artifact must not predate its sources (a bogus UP-TO-DATE
    # would otherwise ship silently stale output).
    apk = newest_apk()
    if not apk:
        die("gradle reported success but no APK found under "
            f"{APK_DIR.relative_to(REPO)}")
    newest_src = 0
    newest_name = ""
    for src in FRESHNESS_INPUTS:
        if src.exists():
            mtime = src.stat().st_mtime
            if mtime > newest_src:
                newest_src, newest_name = mtime, str(src.relative_to(REPO))
    if apk.stat().st_mtime < newest_src:
        die(f"APK {apk.name} is older than {newest_name} — Gradle called "
            "the build UP-TO-DATE but sources are newer (stale artifact)",
            hint="rm -rf android/app/build and rebuild (native objects "
                 "under android/app/.cxx are preserved)")
    return apk


def newest_apk():
    if not APK_DIR.is_dir():
        return None
    apks = sorted(APK_DIR.rglob(f"*{PRIVATE_MARKER}"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return apks[0] if apks else None


def step_check(apk):
    tool = REPO / "tools/android_apk_check.py"
    venv_py = REPO / ".venv/bin/python"
    py = venv_py if venv_py.exists() else sys.executable
    r = run([py, tool, "--apk", apk, "--expect", "private"], timeout=300)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    if r.returncode != 0:
        die("APK content guard failed", hint=last or tail(r))
    return last


def step_install_gate(apk, gate):
    ready = adb_devices_ready()
    if ready != 1:
        die(f"{ready} adb device(s) ready (need exactly 1 for --install)",
            hint="connect exactly one phone (or --no-install), "
                 "and accept the USB debugging prompt")
    r = run(["adb", "install", "-r", str(apk)], timeout=600)
    if r.returncode != 0:
        die("adb install failed", hint=tail(r))
    detail = f"installed {apk.name}"
    if gate:
        r = run([str(REPO / "tools/validate_android.sh"),
                 "--no-install"], timeout=600)
        if r.returncode != 0:
            die("device gate failed", hint=tail(r))
        detail += " — GATE PASSED"
    else:
        detail += " (--no-gate)"
    return detail


# --- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Android bootstrap: private test APK (ROM embedded) "
                    "→ content guard → install + device gate. Public "
                    "builds (ROM via phone UI) use gradlew directly.")
    ap.add_argument("--abi", default="arm64-v8a",
                    help="target ABI (default arm64-v8a; x86_64 for emulator)")
    ap.add_argument("--jobs", type=int,
                    default=min(12, os.cpu_count() or 4),
                    help="native compile parallelism (default min(12, cpus))")
    ap.add_argument("--no-install", action="store_true",
                    help="build + check only; skip install + gate")
    ap.add_argument("--no-gate", action="store_true",
                    help="install without running the device gate")
    ap.add_argument("--skip-check", action="store_true",
                    help="skip the APK content guard")
    ap.add_argument("--skip-stale", action="store_true",
                    help="skip the installed-vs-checkout version guard")
    a = ap.parse_args()

    print(f"build_apk.py — {REPO}")
    print("private test build: ROM embedded (BIOS is the bundled clean-room "
          "emibios), debug-signed. Never "
          "commit or distribute the *-PRIVATE-rom-included.apk.\n")
    t0 = time.time()
    # The plan runs sequentially; later steps receive the previous step's
    # result (the gradle step's APK path flows into the guard and install).
    plan = []

    def run_step(i, total, title, fn, *args):
        print(f"[{i}/{total}] {title} ... ", end="", flush=True)
        try:
            detail = fn(*args)
        except Fail as e:
            print("FAIL")
            print(f"    {e.msg}")
            if e.hint:
                print(f"    hint: {e.hint}")
            return None
        print(f"ok — {detail}")
        return detail

    total = 3 if a.no_install else 4
    if a.skip_check:
        total -= 1
    i = 0

    i += 1
    if run_step(i, total, "preflight", step_preflight, a.skip_stale,
                not a.no_install) is None:
        return 1

    i += 1
    apk = run_step(i, total, "gradle assembleDebug (private)",
                   step_gradle, a.abi, a.jobs)
    if apk is None:
        return 1
    mi = apk.stat().st_size / (1 << 20)
    print(f"      -> {apk.name} ({mi:.1f} MiB)")

    if not a.skip_check:
        i += 1
        if run_step(i, total, "APK content guard",
                    step_check, apk) is None:
            return 1

    if not a.no_install:
        i += 1
        if run_step(i, total, "install + device gate",
                    step_install_gate, apk, not a.no_gate) is None:
            return 1

    dur = time.time() - t0
    print(f"\nbuild_apk.py: DONE in {dur:.1f}s — {apk.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())