#!/usr/bin/env python3
"""compat_build.py — build the Steam-Deck-compatible desktop binary.

Why this exists
---------------
A binary built on a rolling distro inherits that distro's glibc symbol
versions. The 2026-10 CachyOS build needed ``GLIBC_2.43`` (the new
C23 math symbols), which current SteamOS does not provide. The Steam Deck
target is therefore built inside a pinned Debian 12 container
(``tools/compat/Containerfile``, glibc 2.36) and checked explicitly: no
required glibc symbol may be newer than ``--max-glibc`` (default 2.36).

Output
------
``build-compat/FFTARecomp`` (gitignored). Consumed by::

    tools/make_release.py --binary build-compat/FFTARecomp --apk ...
    tools/make_appimage.py --binary build-compat/FFTARecomp ...

The container image is built on first use and reused afterwards. Both
Podman and Docker are supported. On a rootless Podman whose default
storage cannot use overlayfs on btrfs, the script falls back to a private
vfs storage root under ``$XDG_CACHE_HOME/ffta-recomp/podman``.

Usage:
  .venv/bin/python tools/compat_build.py [--jobs N] [--rebuild-image]
                                        [--check-only] [--max-glibc 2.36]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONTAINERFILE = REPO / "tools" / "compat" / "Containerfile"
BUILD = REPO / "build-compat"
BINARY = BUILD / "FFTARecomp"
IMAGE = "ffta-compat:debian12"
DEFAULT_MAX_GLIBC = "2.36"


class Fail(Exception):
    pass


def die(msg):
    raise Fail(msg)


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], **kw)


def runtime_name():
    explicit = os.environ.get("FFTA_CONTAINER_RUNTIME")
    for name in ([explicit] if explicit else []) + ["podman", "docker"]:
        if name and shutil.which(name):
            return name
    die("no container runtime found — install podman or docker "
        "(or set FFTA_CONTAINER_RUNTIME)")


def podman_base():
    """Podman argv prefix, with the btrfs/overlay vfs fallback.

    Rootless Podman on btrfs can fail to configure its default overlay
    storage (the host this was developed on does). Probe ``info``; when it
    fails for that reason, use a private vfs store that does not touch the
    user's normal container storage.
    """
    if not shutil.which("podman"):
        return None
    probe = subprocess.run(["podman", "info"], capture_output=True, text=True)
    if probe.returncode == 0:
        return ["podman"]
    text = (probe.stdout + probe.stderr).lower()
    if "overlay" not in text or "btrfs" not in text:
        return ["podman"]                       # let the real command explain
    cache = Path(os.environ.get("XDG_CACHE_HOME",
                                Path.home() / ".cache")) / "ffta-recomp"
    root = cache / "podman-root"
    runroot = cache / "podman-run"
    root.mkdir(parents=True, exist_ok=True)
    runroot.mkdir(parents=True, exist_ok=True)
    print("compat: podman overlay-on-btrfs unavailable; using private "
          f"vfs storage at {cache}", flush=True)
    return ["podman", "--root", str(root), "--runroot", str(runroot),
            "--storage-driver=vfs"]


def container_base():
    name = runtime_name()
    if name == "podman":
        base = podman_base()
        if base is None:
            die("podman not found")
        return name, base
    return name, [name]


def image_exists(base):
    r = subprocess.run(base + ["image", "inspect", IMAGE],
                       capture_output=True, text=True)
    return r.returncode == 0


def containerfile_parts():
    """(base image, RUN command) from tools/compat/Containerfile."""
    text = CONTAINERFILE.read_text(encoding="utf-8")
    m = re.search(r"^FROM\s+(\S+)", text, re.MULTILINE)
    if not m:
        die("Containerfile has no FROM")
    run = re.search(r"^RUN\s+(.+?)(?=\n\n|\Z)", text,
                    re.MULTILINE | re.DOTALL)
    if not run:
        die("Containerfile has no RUN block")
    cmd = run.group(1).replace("\\\n", " ").strip()
    return m.group(1), cmd


def build_image_podman(base, rebuild=False):
    """Prepare the pinned image with run+commit.

    ``podman build`` cannot use an overlay build context on a btrfs
    home (this host's rootless store): buildah fails before executing a
    single instruction. Running the Containerfile's install command in a
    regular rootless container and committing it produces the same image
    without buildah's overlay context.
    """
    if image_exists(base):
        if not rebuild:
            print(f"compat: image {IMAGE} present", flush=True)
            return
        subprocess.run(base + ["rmi", "-f", IMAGE],
                       capture_output=True, text=True)
    from_image, install = containerfile_parts()
    name = "ffta-compat-prep"
    subprocess.run(base + ["rm", "-f", name],
                   capture_output=True, text=True)
    cmd = "export DEBIAN_FRONTEND=noninteractive\n" + install
    r = run(base + ["run", "--name", name, "--network=host", from_image,
                    "bash", "-lc", cmd])
    if r.returncode != 0:
        subprocess.run(base + ["rm", "-f", name], capture_output=True,
                       text=True)
        die("container image preparation failed")
    r = run(base + ["commit", name, IMAGE])
    subprocess.run(base + ["rm", "-f", name], capture_output=True, text=True)
    if r.returncode != 0:
        die("container image commit failed")


def build_image_docker(base, rebuild=False):
    if image_exists(base) and not rebuild:
        print(f"compat: image {IMAGE} present", flush=True)
        return
    if not CONTAINERFILE.is_file():
        die(f"missing {CONTAINERFILE.relative_to(REPO)}")
    cmd = base + ["build", "--network=host", "-f", str(CONTAINERFILE),
                  "-t", IMAGE, str(CONTAINERFILE.parent)]
    r = run(cmd)
    if r.returncode != 0:
        die("container image build failed")


def build_image(base, rebuild=False, runtime="podman"):
    if runtime == "podman":
        build_image_podman(base, rebuild=rebuild)
    else:
        build_image_docker(base, rebuild=rebuild)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def parse_glibc_versions(objdump_text):
    """Versions in ``objdump -T`` output as sorted (major, minor) tuples."""
    versions = set()
    for m in re.finditer(r"\(GLIBC_(\d+)\.(\d+)(?:\.\d+)?\)", objdump_text):
        versions.add((int(m.group(1)), int(m.group(2))))
    return sorted(versions)


def version_tuple(text):
    m = re.fullmatch(r"(\d+)\.(\d+)", text.strip())
    if not m:
        die(f"bad --max-glibc value: {text!r} (want MAJOR.MINOR)")
    return int(m.group(1)), int(m.group(2))


def check_glibc(binary, max_version):
    objdump = shutil.which("objdump")
    if not objdump:
        die("objdump not found (binutils)")
    r = subprocess.run([objdump, "-T", str(binary)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die(f"objdump failed on {binary}")
    versions = parse_glibc_versions(r.stdout)
    if not versions:
        die(f"no GLIBC symbol versions found in {binary}")
    newest = versions[-1]
    want = version_tuple(max_version)
    detail = ", ".join(f"{a}.{b}" for a, b in versions[-4:])
    if newest > want:
        die(f"{binary} requires GLIBC_{newest[0]}.{newest[1]} "
            f"(newest symbols: {detail}); max is {max_version} — "
            "rebuild in the compat container, do not ship this binary")
    print(f"compat: {binary.relative_to(REPO)} requires <= "
          f"GLIBC_{newest[0]}.{newest[1]} (limit {max_version}; "
          f"newest symbols: {detail})", flush=True)
    return newest


def check_binary(path, max_version):
    if not path.is_file():
        die(f"missing {path} — run without --check-only first")
    check_glibc(path, max_version)


def build(base, jobs):
    # A build-compat/ created outside the container has a host source path
    # in its cache; CMake rejects the /src source move. Reconfigure cleanly.
    cache = BUILD / "CMakeCache.txt"
    if cache.is_file():
        text = cache.read_text(errors="ignore")
        if "CMAKE_HOME_DIRECTORY:INTERNAL=/src" not in text:
            print("compat: build-compat/ has a host cache — removing",
                  flush=True)
            shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True, exist_ok=True)
    script = "\n".join([
        "set -euo pipefail",
        "cmake -S /src -B /src/build-compat -G Ninja "
        "-DCMAKE_BUILD_TYPE=Release -DGBARECOMP_ENABLE_MODS=ON",
        f"cmake --build /src/build-compat --target FFTARecomp "
        f"--parallel {jobs}",
    ])
    cmd = base + ["run", "--rm", "--network=host",
                  "-v", f"{REPO}:/src:Z", "-w", "/src",
                  "-e", f"JOBS={jobs}", IMAGE, "bash", "-lc", script]
    r = run(cmd)
    if r.returncode != 0:
        die("compat build failed (see output above)")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Build the glibc-compatible Steam Deck desktop binary.")
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 4))
    ap.add_argument("--rebuild-image", action="store_true",
                    help="rebuild the pinned container image")
    ap.add_argument("--check-only", action="store_true",
                    help="only verify build-compat/FFTARecomp glibc")
    ap.add_argument("--max-glibc", default=DEFAULT_MAX_GLIBC,
                    help="highest GLIBC symbol version allowed "
                         f"(default {DEFAULT_MAX_GLIBC})")
    a = ap.parse_args(argv)
    if a.check_only:
        check_binary(BINARY, a.max_glibc)
        return 0
    name, base = container_base()
    print(f"compat: runtime={name} image={IMAGE} jobs={a.jobs}", flush=True)
    build_image(base, rebuild=a.rebuild_image, runtime=name)
    build(base, a.jobs)
    if not BINARY.is_file():
        die(f"container build produced no {BINARY.relative_to(REPO)}")
    check_binary(BINARY, a.max_glibc)
    print(f"compat: {BINARY.relative_to(REPO)} "
          f"sha256={sha256_file(BINARY)} size={BINARY.stat().st_size}",
          flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fail as exc:
        print(f"compat_build: {exc}", file=sys.stderr)
        sys.exit(1)
