#!/usr/bin/env python3
"""win_cross_deps.py — pinned static cross-dependency prefix for the Windows build.

Builds the MinGW-x64 static libraries the release exe links (issue #3, R2):

  cross-prefix/lib/libSDL2.a + libSDL2main.a     engine (GBARECOMP_STATIC_RELEASE)
  cross-prefix/lib/libfreetype.a                recomp-ui color emoji (QUIET find)
  cross-prefix/lib/libharfbuzz.a                recomp-ui shaping (pkg-config)
  cross-prefix/lib/libzlib.a                    freetype compressed fonts

Why source builds: Arch ships no mingw-w64 binary library packages (AUR
satellite packages are unmaintained), and MSYS2 is Windows-only. Versions
mirror the MSYS2 repo (SDL2 2.32.10 = msys2 mingw64; harfbuzz 14.6.0) so the
result matches what the engine's reference recipe would link.

Consumed by tools/make_release.py --windows via the CMAKE_TOOLCHAIN_FILE
(tools/mingw-x64.cmake), which points CMAKE_PREFIX_PATH at this prefix.

Usage:
  .venv/bin/python tools/win_cross_deps.py fetch   # download + verify tarballs
  .venv/bin/python tools/win_cross_deps.py build   # configure+build+install
  .venv/bin/python tools/win_cross_deps.py status  # what is/isn't built
  .venv/bin/python tools/win_cross_deps.py clean   # drop build trees, keep prefix
  .venv/bin/python tools/win_cross_deps.py purge   # drop build trees + prefix

Idempotent: cross-prefix/.done/<name>-<version> markers record completed
installs; `build` skips present markers. The marker file records the exact
dep pin set, so a pin bump rebuilds only what changed. Gitignored:
cross-prefix/ and cross-build/ never enter git.
"""
import argparse
import hashlib
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PREFIX = REPO / "cross-prefix"
BUILD = REPO / "cross-build"
SRC = BUILD / "src"
TOOLCHAIN = REPO / "tools" / "mingw-x64.cmake"

# Pin set. url: codeload tag tarballs (stable, sha256-verified below).
# The tarball's sha256 is the pin; a tag retag/force-push changes it and
# fails here loudly.
DEPS = [
    {
        "name": "zlib",
        "repo": "madler/zlib",
        "tag": "v1.3.2",
        "sha256": "b99a0b86c0ba9360ec7e78c4f1e43b1cbdf1e6936c8fa0f6835c0cd694a495a1",
        "cmake": [
            # zlib's own option names (not BUILD_TESTING/BUILD_SHARED_LIBS):
            # ZLIB_BUILD_TESTING kills test/infcover (needs libgcov; tests
            # are upstream business), ZLIB_BUILD_SHARED kills libz.dll so
            # every consumer links the static archive (prune_dynamic stays
            # as belt-and-braces).
            "-DZLIB_BUILD_SHARED=OFF",
            "-DZLIB_BUILD_TESTING=OFF",
        ],
    },
    {
        "name": "freetype",
        "repo": "freetype/freetype",
        "tag": "VER-2-14-3",
        "sha256": "dc49de6b01a266eef4876a4dd34d9842c475d3e28ff2eff63bd2fb760ab56261",
        "cmake": [
            "-DBUILD_SHARED_LIBS=OFF",
            "-DFT_DISABLE_PNG=ON",        # no libpng cross-build; irrelevant
                                           # for the launcher font paths
            "-DFT_DISABLE_BZIP2=ON",
            "-DFT_DISABLE_BROTLI=ON",
            "-DFT_DISABLE_HARFBUZZ=ON",   # linked at the recomp-ui level,
                                           # not inside freetype
        ],
    },
    {
        "name": "harfbuzz",
        "repo": "harfbuzz/harfbuzz",
        "tag": "14.6.0",
        "sha256": "eca8581e5ad8e21dbda31556c0363f764b1a754c9c1bb33ca7cd56ca1c07ddc9",
        "meson": [
            # harfbuzz 14.x has no "fontconfig" toggle anymore (removed);
            # freetype is deliberately off here too (linked at the
            # recomp-ui level, not inside harfbuzz).
            "-Ddefault_library=static",
            "-Dglib=disabled", "-Dgobject=disabled", "-Dcairo=disabled",
            "-Dicu=disabled", "-Dfreetype=disabled",
            "-Dintrospection=disabled", "-Dtests=disabled", "-Ddocs=disabled",
            "-Dutilities=disabled",
        ],
    },
    {
        "name": "sdl2",
        "repo": "libsdl-org/SDL",
        "tag": "release-2.32.10",
        "sha256": "03f9d7c191a837525c9cda6406af2f2e48be02b5e7eb03d949cc9f1e9ca41c8b",
        "cmake": [
            "-DBUILD_SHARED_LIBS=OFF",
            "-DSDL_SHARED=OFF",
            "-DSDL_STATIC=ON",
            "-DSDL_TEST=OFF",
        ],
    },
]


class Fail(Exception):
    pass


def die(msg):
    raise Fail(msg)


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], **kw)
    if r.returncode != 0:
        die(f"failed ({r.returncode}): {' '.join(str(c) for c in cmd)}")
    return r


def tarball_url(dep):
    return f"https://codeload.github.com/{dep['repo']}/tar.gz/refs/tags/{dep['tag']}"


def tarball_path(dep):
    return SRC / f"{dep['name']}-{dep['tag']}.tar.gz"


def marker_path(dep):
    return PREFIX / ".done" / f"{dep['name']}-{dep['tag']}"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(dep):
    SRC.mkdir(parents=True, exist_ok=True)
    path = tarball_path(dep)
    if path.exists() and dep["sha256"] and \
            sha256_file(path) == dep["sha256"]:
        print(f"{dep['name']}: tarball present + pinned")
        return
    if path.exists():
        path.unlink()
    import urllib.request
    print(f"{dep['name']}: fetching {tarball_url(dep)} ...")
    urllib.request.urlretrieve(tarball_url(dep), path)
    got = sha256_file(path)
    if dep["sha256"]:
        if got != dep["sha256"]:
            die(f"{dep['name']}: sha256 mismatch: got {got}, pinned "
                f"{dep['sha256']}")
        print(f"{dep['name']}: sha256 OK ({got[:16]}...)")
    else:
        # No pin recorded yet — print it for pasting into DEPS.
        print(f"{dep['name']}: PIN NEEDED — sha256 = \"{got}\"")


def extract_dir(dep):
    # codeload names the top dir "<repo>-<tag>"; strip it away.
    return SRC / f"{dep['name']}-build"


def cmake_env():
    env = dict(**__import__("os").environ)
    env["PKG_CONFIG_PATH"] = str(PREFIX / "lib" / "pkgconfig")
    return env


def prune_dynamic():
    """Enforce the static-only contract: no .dll / .dll.a may live in the
    prefix — an import lib present here would make a consumer link the
    dynamic variant and silently reintroduce a DLL dependency into the
    "zero-DLL" exe (the exact failure mode the objdump guard in
    make_release.py --windows exists to catch, but structurally prevented
    at the prefix level first)."""
    for pattern in ("lib", "bin"):
        base = PREFIX / pattern
        if not base.is_dir():
            continue
        for p in base.rglob("*.dll.a"):
            p.unlink()
            print(f"pruned {p.relative_to(REPO)}")
        for p in base.rglob("*.dll"):
            p.unlink()
            print(f"pruned {p.relative_to(REPO)}")


def build_cmake(dep, extra):
    work = extract_dir(dep)
    if work.exists():
        shutil.rmtree(work)
    with tarfile.open(tarball_path(dep)) as tf:
        member = tf.getnames()[0]
    with tarfile.open(tarball_path(dep)) as tf:
        tf.extractall(SRC)  # noqa: S202 - pin-verified tarball
    src_dir = SRC / member
    src_dir = src_dir.resolve()
    src_dir.rename(work)
    run(["cmake", "-S", work, "-B", work / "out", "-G", "Ninja",
         f"-DCMAKE_TOOLCHAIN_FILE={TOOLCHAIN}",
         "-DCMAKE_BUILD_TYPE=Release",
         f"-DCMAKE_INSTALL_PREFIX={PREFIX}"]
        + dep["cmake"] + extra, env=cmake_env())
    run(["cmake", "--build", work / "out", "--parallel"],
        env=cmake_env())
    run(["cmake", "--install", work / "out"], env=cmake_env())
    prune_dynamic()


def build_meson(dep):
    work = extract_dir(dep)
    if work.exists():
        shutil.rmtree(work)
    with tarfile.open(tarball_path(dep)) as tf:
        member = tf.getnames()[0]
    with tarfile.open(tarball_path(dep)) as tf:
        tf.extractall(SRC)  # noqa: S202 - pin-verified tarball
    src_dir = (SRC / member).resolve()
    src_dir.rename(work)
    cross = BUILD / "harfbuzz-cross.ini"
    cross.write_text(f"""[binaries]
c = 'x86_64-w64-mingw32-gcc'
cpp = 'x86_64-w64-mingw32-g++'
ar = 'x86_64-w64-mingw32-ar'
strip = 'x86_64-w64-mingw32-strip'
pkg-config = 'pkg-config'

[host_machine]
system = 'windows'
cpu_family = 'x86_64'
cpu = 'x86_64'
endian = 'little'
""", encoding="utf-8")
    env = dict(**__import__("os").environ)
    env["PKG_CONFIG_PATH"] = str(PREFIX / "lib" / "pkgconfig")
    run(["meson", "setup", work / "out", work, f"--cross-file={cross}",
         f"--prefix={PREFIX}"]
        + dep["meson"], env=env)
    run(["meson", "compile", "-C", work / "out"], env=env)
    run(["meson", "install", "-C", work / "out"], env=env)
    prune_dynamic()


def cmd_fetch():
    for dep in DEPS:
        fetch(dep)


def build(dep):
    if marker_path(dep).exists():
        print(f"{dep['name']}: up to date ({dep['tag']})")
        return
    print(f"{dep['name']}: building {dep['tag']} ...")
    if "meson" in dep:
        build_meson(dep)
    else:
        build_cmake(dep, [])
    (PREFIX / ".done").mkdir(parents=True, exist_ok=True)
    marker_path(dep).write_text(
        f"{dep['repo']} @ {dep['tag']}\nsha256 {dep['sha256']}\n",
        encoding="utf-8")
    print(f"{dep['name']}: installed -> {PREFIX}")


def cmd_build(force=False):
    missing_tarballs = [d["name"] for d in DEPS if not tarball_path(d).exists()]
    if missing_tarballs:
        die("missing tarballs: " + ", ".join(missing_tarballs)
            + " — run `fetch` first")
    unpinned = [d["name"] for d in DEPS if not d["sha256"]]
    if unpinned:
        die("unpinned deps (sha256 empty in DEPS): " + ", ".join(unpinned)
            + " — run `fetch`, record the printed sha256 values")
    for dep in DEPS:
        if force and marker_path(dep).exists():
            marker_path(dep).unlink()
        build(dep)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["fetch", "build", "status", "clean",
                                     "purge"])
    ap.add_argument("--force", action="store_true",
                    help="build: rebuild even when markers are present")
    a = ap.parse_args()
    if a.cmd == "fetch":
        cmd_fetch()
    elif a.cmd == "build":
        cmd_build(a.force)
    elif a.cmd == "status":
        for dep in DEPS:
            state = ("built" if marker_path(dep).exists()
                     else ("tarball present" if tarball_path(dep).exists()
                           else "missing"))
            print(f"{dep['name']:10} {dep['tag']:18} {state}")
    elif a.cmd == "clean":
        if BUILD.exists():
            shutil.rmtree(BUILD)
        print("removed cross-build/ (prefix kept)")
    elif a.cmd == "purge":
        if BUILD.exists():
            shutil.rmtree(BUILD)
        if PREFIX.exists():
            shutil.rmtree(PREFIX)
        print("removed cross-build/ + cross-prefix/")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fail as exc:
        print(f"win_cross_deps: {exc}", file=sys.stderr)
        sys.exit(1)