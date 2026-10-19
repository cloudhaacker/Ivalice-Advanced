#!/usr/bin/env python3
"""publish_release.py — build locally, verify, and upload a GitHub release.

The public release never needs the ROM on GitHub: this script runs on the
machine that has the dump, builds the four public artifacts, verifies them,
and uploads them with the `gh` CLI. The tag-triggered workflow only creates
a draft release shell (`.github/workflows/release.yml`); it never checks out
the game tree or asks for private material.

Usage:
  .venv/bin/python tools/publish_release.py --version v1.7
  .venv/bin/python tools/publish_release.py --version v1.7 --upload-only
  .venv/bin/python tools/publish_release.py --version v1.7 --publish

Defaults: build all four artifacts (Linux zip, public APK, static Windows
zip, Steam Deck AppImage), upload them to the draft release, and leave the
release as a draft. Pass --publish to make it live.

Prerequisites for a full build are the ones the artifacts already need:
build/ (host gate binary), the Android SDK/NDK/JDK 21, mingw-w64 + wine +
cross-prefix, and podman or docker for the SteamOS-compatible binary.
`--upload-only` validates/uploading existing files under release-stage/.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import make_release as mr  # noqa: E402
import make_appimage as ai  # noqa: E402

OUT = REPO / "release-stage"


class Fail(Exception):
    pass


def die(msg, hint=None):
    raise Fail(msg + (f"\nhint: {hint}" if hint else ""))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def artifact_names(version):
    return {
        "linux": f"FFTARecomp-{version}-linux-x64.zip",
        "windows": f"FFTARecomp-{version}-windows-x64.zip",
        "appimage": f"FFTARecomp-{version}-linux-x86_64.AppImage",
        "apk": f"FFTARecomp-{version}-android-arm64-v8a.apk",
    }


def sums_text(paths):
    lines = []
    for p in sorted(paths, key=lambda q: q.name):
        lines.append(f"{sha256_file(p)}  {p.name}")
    return "\n".join(lines) + "\n"


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], **kw)


def tag_exists(version):
    r = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--verify",
                        f"refs/tags/{version}"], capture_output=True, text=True)
    return r.returncode == 0


def tag_matches_head(version):
    tag = subprocess.run(["git", "-C", str(REPO), "rev-parse",
                          f"{version}^{{commit}}"], capture_output=True,
                         text=True)
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    return (tag.returncode == 0 and head.returncode == 0
            and tag.stdout.strip() == head.stdout.strip())


def build_all(version, compat=True, want=None):
    want = want or {"linux": True, "windows": True, "appimage": True,
                    "apk": True}
    if compat:
        r = run([sys.executable, "tools/compat_build.py", "--jobs",
                 str(min(16, os.cpu_count() or 8))], cwd=REPO)
        if r.returncode != 0:
            die("compat build failed")
        binary = "build-compat/FFTARecomp"
    else:
        binary = "build/FFTARecomp"
        print("publish: WARNING: --no-compat uses the host binary; it may "
              "require a newer glibc than SteamOS", flush=True)
    cmds = []
    if want["linux"] or want["apk"]:
        cmd = [sys.executable, "tools/make_release.py", "--version", version,
               "--binary", binary]
        if want["apk"]:
            cmd.append("--apk")
        cmds.append(cmd)
    if want["windows"]:
        cmds.append([sys.executable, "tools/make_release.py", "--windows",
                     "--version", version])
    if want["appimage"]:
        cmds.append([sys.executable, "tools/make_appimage.py",
                     "--version", version, "--binary", binary])
    for cmd in cmds:
        r = run(cmd, cwd=REPO)
        if r.returncode != 0:
            die(f"packaging failed: {' '.join(cmd)}")


def verify_linux_zip(path):
    with tempfile.TemporaryDirectory(prefix="ffta-publish-linux-") as td:
        with zipfile.ZipFile(path) as zf:
            zf.extractall(td)
        roots = [p for p in Path(td).iterdir() if p.is_dir()]
        if len(roots) != 1:
            die(f"{path.name}: expected one top-level folder, got {len(roots)}")
        violations = mr.sweep_stage(roots[0])
        if violations:
            die(f"{path.name} rejected:\n  " + "\n  ".join(violations))


def verify_windows_zip(path):
    objdump = shutil.which("x86_64-w64-mingw32-objdump")
    if not objdump:
        die("x86_64-w64-mingw32-objdump not found (mingw-w64-binutils)")
    with tempfile.TemporaryDirectory(prefix="ffta-publish-win-") as td:
        with zipfile.ZipFile(path) as zf:
            zf.extractall(td)
        roots = [p for p in Path(td).iterdir() if p.is_dir()]
        if len(roots) != 1:
            die(f"{path.name}: expected one top-level folder, got {len(roots)}")
        violations = mr.sweep_stage(roots[0], platform="windows")
        if violations:
            die(f"{path.name} rejected:\n  " + "\n  ".join(violations))
        exe = roots[0] / "FFTARecomp.exe"
        r = subprocess.run([objdump, "-p", str(exe)], capture_output=True,
                           text=True)
        if r.returncode != 0:
            die("objdump failed on the Windows executable")
        bad = mr.static_link_violations(mr.parse_import_dlls(r.stdout))
        if bad:
            die(f"{path.name} imports third-party DLLs: {', '.join(bad)}")


def verify_appimage(path):
    ai.guard_appimage(path)


def verify_apk(path):
    r = run([sys.executable, "tools/android_apk_check.py", "--apk", str(path),
             "--expect", "public"], cwd=REPO)
    if r.returncode != 0:
        die(f"{path.name}: android_apk_check --expect public failed")


def verify(paths, version):
    names = artifact_names(version)
    for key, p in paths.items():
        if not p.is_file() or p.stat().st_size == 0:
            die(f"missing/empty artifact: {p}")
        print(f"publish: verifying {p.name} ({p.stat().st_size} B)", flush=True)
        if key == "linux":
            verify_linux_zip(p)
        elif key == "windows":
            verify_windows_zip(p)
        elif key == "appimage":
            verify_appimage(p)
        elif key == "apk":
            verify_apk(p)
    return names


def gh(*args, **kw):
    return run(["gh", *args], cwd=REPO, **kw)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Build/verify/upload a FFTA Recomp GitHub release.")
    ap.add_argument("--version", required=True,
                    help="existing git tag (e.g. v1.7)")
    ap.add_argument("--upload-only", action="store_true",
                    help="skip builds; verify/upload existing release-stage "
                         "artifacts")
    ap.add_argument("--no-compat", action="store_true",
                    help="use build/FFTARecomp instead of the Debian 12 "
                         "compat binary (not recommended for SteamOS)")
    ap.add_argument("--no-linux", action="store_true")
    ap.add_argument("--no-windows", action="store_true")
    ap.add_argument("--no-appimage", action="store_true")
    ap.add_argument("--no-apk", action="store_true")
    ap.add_argument("--publish", action="store_true",
                    help="flip the draft release to published")
    ap.add_argument("--notes-file", default=None,
                    help="release notes file (passed to gh release edit)")
    a = ap.parse_args(argv)

    version = a.version
    if not tag_exists(version):
        die(f"tag not found: {version}",
            hint=f"create and push it first: git tag -a {version} -m "
                 f"\"FFTARecomp {version}\" && git push origin {version}")
    if not tag_matches_head(version):
        die(f"HEAD is not {version} — build the release from its tag commit",
            hint="git checkout the release tag (or cherry-pick the fixes) "
                 "before publishing")
    if subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                      capture_output=True, text=True).stdout.strip():
        die("working tree is dirty — commit the release tree before "
            "building/publishing")

    selected = {}
    want = {
        "linux": not a.no_linux,
        "windows": not a.no_windows,
        "appimage": not a.no_appimage,
        "apk": not a.no_apk,
    }
    names = artifact_names(version)
    if want["linux"]:
        selected["linux"] = OUT / names["linux"]
    if want["windows"]:
        selected["windows"] = OUT / names["windows"]
    if want["appimage"]:
        selected["appimage"] = OUT / names["appimage"]
    if want["apk"]:
        selected["apk"] = OUT / names["apk"]
    if not selected:
        die("nothing selected to publish")

    if not a.upload_only:
        build_all(version, compat=not a.no_compat, want=want)

    paths = {}
    for key, p in selected.items():
        if not p.is_file():
            die(f"missing artifact: {p}",
                hint="build it first (omit --upload-only) or check the "
                     "version")
        paths[key] = p
    verify(paths, version)

    sums = OUT / f"SHA256SUMS-{version}.txt"
    sums.write_text(sums_text(list(paths.values())), encoding="utf-8")
    print(f"publish: wrote {sums.name}", flush=True)

    view = gh("release", "view", version, capture_output=True)
    if view.returncode != 0:
        gh("release", "create", version, "--draft", "--generate-notes",
           "--title", f"FFTARecomp {version}", check=False)
    if a.notes_file:
        gh("release", "edit", version, "--notes-file", a.notes_file)
    upload = [str(p) for p in paths.values()] + [str(sums)]
    gh("release", "upload", version, *upload, "--clobber")
    if a.publish:
        gh("release", "edit", version, "--draft=false")
        print(f"publish: {version} is live", flush=True)
    else:
        print(f"publish: {version} uploaded as a DRAFT — inspect it, then "
              "run --publish", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fail as exc:
        print(f"publish_release: {exc}", file=sys.stderr)
        sys.exit(1)
