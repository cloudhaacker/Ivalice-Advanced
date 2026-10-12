#!/usr/bin/env python3
"""make_release.py — assemble the distributable desktop zip (issue #3, R1).

The stage is built from an ALLOWLIST, never by copying a tree: every file
that enters the release is named here, so nothing can leak in by accident.
After staging, sweep_stage() rejects private material, and the zip writer
produces a deterministic, portable archive (fixed timestamps, sorted
entries, forward-slash names, permissions preserved).

Layout — everything resolves beside the executable at runtime
(launcher_seam state_path + GBARECOMP_DEFAULT_GAME_CONFIG="game.toml"):

    FFTARecomp-<version>-linux-x64/
      FFTARecomp                    stripped copy of build/FFTARecomp
      assets/                       recomp-ui launcher fonts/img
      mods/                         preloaded mod catalog (default-enabled)
      game.toml
      bios/emibios_gba_bios.bin     committed clean-room BIOS (LGPL)
      bios/README.md
      README.md                     generated, self-contained (no dead links)
      LICENSE, LICENSES/, THIRD_PARTY_ATTRIBUTION.md

config.ini/keybinds.ini/rom.cfg and saves/ are created beside the
executable at runtime — extract to a writable folder.

Sweep (sweep_stage, unit-tested in tests/python/test_tools.py):
  - forbidden extensions .gba/.agb/.sav/.srm/.apk
  - .bin allowed only at the emibios SHA-1 pin (a retail dump fails)
  - no staged file may hash to the ROM SHA-1 or the retail BIOS SHA-1
    under ANY name
  - no symlinks (a staged link could point outside the tree)
  - the required set present: binary (+ exec bit), config, pinned BIOS,
    assets, mod manifest, README, LICENSE, LICENSES/LGPL, THIRD_PARTY

Refuses a stale artifact (the build_apk.py gate, mirrored): no regen stamp
→ refuse; any regen input newer than generated/.regen_stamp → refuse (a
pull that rewrites unchanged files lands here too — one cycle.py run
clears it, and the gate never packages a maybe-stale tree); binary older
than the corpus → refuse.

Usage:
  .venv/bin/python tools/make_release.py [--version V] [--no-strip] [--clean]

Output zip: release-stage/FFTARecomp-<version>-linux-x64.zip (gitignored).
The last stdout line is "release: <name> sha1=<sha1> ..." for check.py.
"""
import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUILD = REPO / "build"
BINARY = BUILD / "FFTARecomp"
OUT_DIR = REPO / "release-stage"

ROM_SHA1 = "4ac05441f4de70a4ec3dd932116346c61b8783d9"
EMIBIOS_SHA1 = "0c0d404d16c6b55b3071aba714f82077da132f14"
RETAIL_BIOS_SHA1 = "300c20df6731a33952ded8c436f7f186d25d3492"

FORBIDDEN_EXTS = {".gba", ".agb", ".sav", ".srm", ".apk"}

REQUIRED_FILES = [
    "FFTARecomp",
    "game.toml",
    "bios/emibios_gba_bios.bin",
    "bios/README.md",
    "README.md",
    "LICENSE",
    "LICENSES/LGPL-3.0-or-later.txt",
    "THIRD_PARTY_ATTRIBUTION.md",
    "mods/packages/ffta.enhancement.widescreen/1.0.0/manifest.toml",
]
REQUIRED_DIRS = [
    "assets/fonts",
    "assets/img",
]

# The zip README: self-contained (no links into repo folders that do not
# ship). The repo README § "Using a release binary" is the same story for
# users browsing the repository.
README_TEMPLATE = """# Final Fantasy Tactics Advance — Recomp (desktop release)

A static recompilation of *Final Fantasy Tactics Advance* (USA): the GBA
machine code was translated ahead-of-time into a native Linux binary. This
is not an emulator. **No game data is included** — you provide your own
legally obtained ROM.

## Requirements

Linux x86-64, plus system libraries (packages):

| Distro | Packages |
|---|---|
| Debian/Ubuntu | `libsdl2-2.0-0 libopengl0 libfreetype6 libharfbuzz0b` |
| Fedora | `SDL2 mesa-libGL freetype harfbuzz` |
| Arch | `sdl2 libgl freetype2 harfbuzz` |

## Run

1. Extract the folder anywhere **writable** — launcher settings and saves
   are kept beside the executable.
2. Run `./FFTARecomp`.
3. In the launcher, pick your legally obtained *Final Fantasy Tactics
   Advance* (USA) ROM, then **Play**.

The launch BIOS is bundled (`bios/emibios_gba_bios.bin` — a clean-room,
freely redistributable build, LGPL-3.0-or-later). You never need a Nintendo
BIOS dump.

The ROM is hash-verified at launch (SHA-1 `{rom_sha1}`). A mismatch error
means the file is not the expected USA dump — re-dump your own cartridge.

## Widescreen (validated)

`./FFTARecomp --view-width 448` (240–448 px) or `--resize-view` for a
window-aspect-driven view; `--scale N` sets the window size
(N×240 × N×160 px). The default stays faithful 240×160.

## Where files land (beside the executable)

- `config.ini`, `keybinds.ini`, `rom.cfg` — launcher state, created on
  first run
- `saves/ffta_us.sav` — the cartridge battery save

## Legal

Unofficial, non-commercial preservation project — PolyForm Noncommercial
1.0.0, see `LICENSE`. Not affiliated with or endorsed by Square Enix or
Nintendo. No ROM or Nintendo BIOS data ships in this archive; the bundled
BIOS is clean-room (`bios/README.md`). Third-party terms and credits:
`THIRD_PARTY_ATTRIBUTION.md`, `LICENSES/`.
"""


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


def git_version():
    r = subprocess.run(["git", "describe", "--tags", "--always", "--dirty"],
                       cwd=str(REPO), capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return "untagged"


def newest_mtime(paths):
    """Newest mtime under the given roots (files only, symlink-safe)."""
    newest = 0.0
    for root in paths:
        root = Path(root)
        if root.is_file():
            newest = max(newest, root.stat().st_mtime)
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                p = Path(dirpath) / name
                if p.is_symlink():
                    continue
                try:
                    newest = max(newest, p.stat().st_mtime)
                except OSError:
                    pass
    return newest


def check_freshness():
    """Refuse to package a stale artifact (mirrors build_apk.py's gate).

    Three rules:
      1. generated/.regen_stamp exists — no stamp = never regen'd here;
      2. no regen input (game.toml, symbols/, src/, CMakeLists.txt,
         generated/) is newer than the stamp — an input newer than the
         last regen means the corpus predates it. Git checkouts smudge
         mtimes on unchanged files (branch switches/pulls) and that
         lands here too — deliberately: a cycle.py run clears it, and
         the gate never packages a maybe-stale tree;
      3. the binary is newer than the newest corpus file — the
         recompiler preserves mtimes for byte-identical output, so a
         no-op regen moves nothing and this stays true; a real corpus
         change is only linked by a rebuild, which moves the binary.
    """
    if not BINARY.is_file():
        die(f"missing {BINARY}",
            hint="build first: python3 build.py (or AGENTS.md § Commands)")
    stamp = REPO / "generated/.regen_stamp"
    if not stamp.is_file():
        die("generated/ corpus has no regen stamp",
            hint="run tools/cycle.py (cold regen + build) before packaging")
    symbols = sorted((REPO / "symbols").glob("*.tsv"))
    src = [p for p in (REPO / "src").rglob("*") if p.is_file()]
    inputs = ([REPO / "game.toml", REPO / "CMakeLists.txt", REPO / "generated"]
              + symbols + src)
    missing = [str(p) for p in inputs if not p.exists()]
    if missing:
        die("regen inputs missing: " + ", ".join(missing),
            hint="run tools/cycle.py (cold regen) first")
    stamp_mtime = stamp.stat().st_mtime
    for source in inputs:
        if newest_mtime([source]) > stamp_mtime:
            die(f"regen input {source} is newer than the last regen stamp",
                hint="re-run tools/cycle.py (regen + build), then package — "
                     "the gate never ships a maybe-stale tree (a pull that "
                     "rewrites files lands here too; one cycle clears it)")
    corpus_newest = newest_mtime([REPO / "generated"])
    if BINARY.stat().st_mtime < corpus_newest:
        die("build/FFTARecomp is older than the generated/ corpus",
            hint="re-run tools/cycle.py (rebuild), then package")


def sweep_stage(stage):
    """Return the list of private-material / completeness violations.

    Empty list = clean. Pure function of the staged tree: unit-tested
    directly (tests/python/test_tools.py) with synthetic stages.
    """
    stage = Path(stage)
    violations = []

    # 1. Required set present (and the binary carries its exec bit).
    for rel in REQUIRED_FILES:
        p = stage / rel
        if not p.is_file():
            violations.append(f"missing required file: {rel}")
    for rel in REQUIRED_DIRS:
        p = stage / rel
        if not (p.is_dir() and any(p.iterdir())):
            violations.append(f"missing required (non-empty) dir: {rel}")
    bin_mode = (stage / "FFTARecomp").stat().st_mode \
        if (stage / "FFTARecomp").is_file() else 0
    if bin_mode and not (bin_mode & stat.S_IXUSR):
        violations.append("FFTARecomp lost its exec bit")

    # 2. Forbidden material — walk everything staged.
    for dirpath, dirnames, filenames in os.walk(stage):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            if p.is_symlink():
                violations.append(f"symlink in stage: {p.relative_to(stage)}")
        for name in filenames:
            p = Path(dirpath) / name
            rel = p.relative_to(stage).as_posix()
            ext = p.suffix.lower()
            if ext in FORBIDDEN_EXTS:
                violations.append(f"forbidden extension: {rel}")
                continue
            try:
                digest = sha1_file(p)
            except OSError as exc:
                violations.append(f"unreadable file: {rel} ({exc})")
                continue
            if digest == ROM_SHA1:
                violations.append(f"ROM material under disguised name: {rel}")
            if digest == RETAIL_BIOS_SHA1:
                violations.append(f"retail BIOS dump material: {rel}")
            if ext == ".bin" and digest != EMIBIOS_SHA1:
                violations.append(
                    f".bin that is not the pinned clean-room BIOS: {rel}")
    return violations


README_NOTE = """
*(This README is generated by tools/make_release.py at packaging time; the
canonical project README lives in the source repository.)*
"""


def stage_release(version, strip=True):
    """Build the allowlisted stage. Returns (stage_dir, folder_name)."""
    folder = f"FFTARecomp-{version}-linux-x64"
    stage = OUT_DIR / folder
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    def cp_file(src, rel):
        dst = stage / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # Binary (stripped in-stage; build/FFTARecomp keeps its symbols for
    # dev-side addr2line crash triage).
    cp_file(BINARY, "FFTARecomp")
    if strip:
        r = subprocess.run(["strip", str(stage / "FFTARecomp")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            die("strip failed: " + r.stderr.strip(), hint="--no-strip skips it")
    os.chmod(stage / "FFTARecomp", 0o755)

    shutil.copytree(BUILD / "assets", stage / "assets")
    shutil.copytree(BUILD / "mods", stage / "mods")

    cp_file(REPO / "game.toml", "game.toml")
    cp_file(REPO / "bios/emibios_gba_bios.bin", "bios/emibios_gba_bios.bin")
    cp_file(REPO / "bios/README.md", "bios/README.md")
    cp_file(REPO / "LICENSE", "LICENSE")
    shutil.copytree(REPO / "LICENSES", stage / "LICENSES")
    cp_file(REPO / "THIRD_PARTY_ATTRIBUTION.md", "THIRD_PARTY_ATTRIBUTION.md")

    readme = (README_TEMPLATE.format(rom_sha1=ROM_SHA1) + README_NOTE)
    (stage / "README.md").write_text(readme, encoding="utf-8")
    return stage, folder


def write_portable_zip(stage, folder, zip_path):
    """Deterministic zip: fixed timestamps, sorted entries, '/' names.

    Two packaging runs over the same tree produce byte-identical archives
    (unit-tested), so CI can hash and users can diff releases.
    """
    files = sorted((p for p in stage.rglob("*") if p.is_file() and
                    not p.is_symlink()),
                   key=lambda p: p.relative_to(stage).as_posix())
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for p in files:
            rel = p.relative_to(stage).as_posix()
            zi = zipfile.ZipInfo(f"{folder}/{rel}",
                                date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.create_system = 3  # unix, so external_attr carries the mode
            mode = 0o755 if rel == "FFTARecomp" else 0o644
            zi.external_attr = (0o100000 | mode) << 16
            zf.writestr(zi, p.read_bytes())
    return len(files)


def verify_zip(zip_path, expected_count):
    """Read back: portable names, count match, exec bit survived."""
    problems = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if len(names) != expected_count:
            problems.append(f"entry count {len(names)} != {expected_count}")
        for info in zf.infolist():
            name = info.filename
            if "\\" in name or name.startswith("/") or ".." in name.split("/"):
                problems.append(f"non-portable entry name: {name}")
            if name.rsplit("/", 1)[-1] == "FFTARecomp":
                mode = (info.external_attr >> 16) & 0o777
                if mode & stat.S_IXUSR != stat.S_IXUSR:
                    problems.append(f"FFTARecomp lost exec bit in zip: {mode:o}")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Assemble the distributable desktop release zip.")
    ap.add_argument("--version", default=None,
                    help="override the version (default: git describe)")
    ap.add_argument("--no-strip", action="store_true",
                    help="ship the binary with symbols")
    ap.add_argument("--clean", action="store_true",
                    help="remove the stage dir after zipping")
    a = ap.parse_args(argv)

    t0 = time.time()
    check_freshness()
    version = a.version or git_version()
    OUT_DIR.mkdir(exist_ok=True)

    stage, folder = stage_release(version, strip=not a.no_strip)
    violations = sweep_stage(stage)
    if violations:
        shutil.rmtree(stage)
        die("release stage rejected:\n  " + "\n  ".join(violations),
            hint="nothing private may enter a public artifact "
                 "(AGENTS.md § Public-repo hygiene)")

    zip_path = OUT_DIR / f"{folder}.zip"
    if zip_path.exists():
        zip_path.unlink()
    count = write_portable_zip(stage, folder, zip_path)
    problems = verify_zip(zip_path, count)
    if problems:
        die("zip verification failed:\n  " + "\n  ".join(problems))

    if a.clean:
        shutil.rmtree(stage)
    digest = sha1_file(zip_path)
    print(f"staged {count} files, zip {zip_path}")
    print(f"release: {zip_path.name} sha1={digest} "
          f"size={zip_path.stat().st_size} "
          f"({time.time() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fail as exc:
        print(f"make_release: {exc.msg}", file=sys.stderr)
        if exc.hint:
            print(f"hint: {exc.hint}", file=sys.stderr)
        sys.exit(1)