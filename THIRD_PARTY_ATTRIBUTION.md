# Third-Party Attribution

FFTA Recomp's own code and documentation are licensed PolyForm
Noncommercial 1.0.0 (see `LICENSE`). This file lists the third-party work
the project builds on or derives from, and the terms that apply. **No game
content is included in this repository**: no ROMs, BIOS dumps, game
graphics/text/audio, saves, or recompiled output — everything runs from
the user's ROM dump plus the bundled clean-room BIOS below.

## Bundled clean-room BIOS (emibios)

`bios/emibios_gba_bios.bin` (16 KiB) is a build of
[coolbho3k/emibios](https://github.com/coolbho3k/emibios) `main @c4d5d71`
— a clean-room, *freely redistributable* GBA BIOS replacement, **LGPL-3.0-or-later**.
It is not a dump and not Nintendo code: it ships as repo material
(issue #17), is the launch BIOS pinned by `game.toml [bios]`, and is
staged into every Android payload. The committed binary is the **unmodified**
upstream build (SHA-256 verified against the upstream `bios.sha256` pin;
SHA-1 `0c0d404d16c6b55b3071aba714f82077da132f14`); its recompilation
config (`bios/emibios_gba_bios.toml`) documents the source URL and commit.

- License text: [`LICENSES/LGPL-3.0-or-later.txt`](LICENSES/LGPL-3.0-or-later.txt)
  (the FSF's combined LGPL-3.0 + GPL-3.0 document emibios ships as its
  `LICENSE`; verbatim copying of the license document is permitted by its
  own terms — the same class of exception as the GFDL texts below)
- Source: <https://github.com/coolbho3k/emibios> (Zig 0.16 build;
  `zig build` reproduces the binary)
- Modification rights under the LGPL are preserved: the binary is
  replaceable in place (`bios/emibios_gba_bios.bin` + the config pin), and
  any rebuild of emibios flows through `build.py`'s BIOS recompile step
  into the linked corpus without touching game code.

## Framework submodules

| Component | Upstream | License |
|---|---|---|
| `gbarecomp/` | <https://github.com/mstan/gbarecomp> | PolyForm Noncommercial 1.0.0, © 2026 Matthew Stanley |
| `recomp-ui/` | (same author) | MIT, © 2026 Matthew Stanley |

Working-tree patches in `tools/patches/` modify gbarecomp sources; patched
copies remain under gbarecomp's terms (see `tools/patches/README.md`).

## Runtime HLE (mGBA-derived)

The BIOS HLE services (`gbarecomp/src/runtime/bios_hle.cpp`, enabled by
`game.toml [bios].hle`) port SWI semantics from mGBA's `src/gba/bios.c`
([mgba-emu/mgba](https://github.com/mgba-emu/mgba), MPL-2.0 — notice retained
in the file header plus `third_party/MPL-2.0.txt` upstream). The object code
links into every build (the hook installs only when HLE is on); unhandled
SWIs fall through to the recompiled LLE BIOS. No mGBA sources are vendored
here.

## Cross dependencies (statically linked into the Windows release)

The Windows artifact (`FFTARecomp-*-windows-x64.zip`, built by
`tools/make_release.py --windows` via `tools/win_cross_deps.py`) is a
static MinGW build: the libraries below are **compiled in**, so their
code ships to players who download the zip. That is redistribution, and
the Linux build links the same libraries dynamically from distro
packages. All four are permissive-licensed; none taints the game's
PolyForm Noncommercial 1.0.0 terms. The pinned versions live as
tarball-sha256 pins in `tools/win_cross_deps.py` (verify any time by
rebuilding the prefix and re-hashing - determinism is gated in BRINGUP
section "R-track: R2").

| Library | Source built | License |
|---|---|---|
| zlib (compression, via freetype) | madler/zlib @ v1.3.2 | zlib/libpng license (permissive; attribution in `LICENSES/` below) |
| FreeType 2 (launcher font raster, via the engine's `recomp-ui` layer - `find_package(Freetype ...)`, color-emoji path) | freetype/freetype @ VER-2-14-3 | **FreeType License (FTL)** - the license's BSD-style permissive branch (we do not take the GPL branch); dual-licensing notice retained by the FTL terms |
| HarfBuzz (text shaping, via `recomp-ui` - `pkg_check_modules(harfbuzz)`) | harfbuzz/harfbuzz @ 14.6.0 | **MIT** |
| SDL2 (windowing/input/audio - engine `GBARECOMP_STATIC_RELEASE`, `libSDL2.a`+`libSDL2main.a`) | libsdl-org/SDL @ release-2.32.10 | **zlib license** |

- License texts: [`LICENSES/ZLIB.txt`](LICENSES/ZLIB.txt),
  [`LICENSES/FTL.txt`](LICENSES/FTL.txt), [`LICENSES/MIT-harfbuzz.txt`](LICENSES/MIT-harfbuzz.txt),
  [`LICENSES/ZLIB-SDL2.txt`](LICENSES/ZLIB-SDL2.txt) - each is the
  verbatim upstream license document (permissive-license documents are
  redistributed as-is by their own terms, same exception class as the
  GFDL/LGPL documents above). `tools/make_release.py` stages `LICENSES/`
  into every artifact.
- Windows-DLL note: SDL2's static build depends on Windows system
  libraries only (kernel32/user32/gdi32/opengl32/... - OS components, not
  third-party redistributables); the objdump import-table guard in
  `make_release.py --windows` fails the build on any non-system DLL.

## Oracle tooling

`gbarecomp/oracle/setup-mgba.sh` clones
[mgba-emu/mgba](https://github.com/mgba-emu/mgba) (MPL-2.0) into an ignored
`third_party/` directory to build the frame-diff oracle. Not tracked, not
redistributed here.

## Ported tool

| Our file | Upstream | What | Terms |
|---|---|---|---|
| `tools/m4a_detect.py` | Bregalad & loveemu — `sappy_detector.c` ("GBA Mus Ripper" lineage; forks: [berg8793](https://github.com/berg8793/gba-mus-ripper), [CaptainSwag101](https://github.com/CaptainSwag101/gba-mus-ripper)) | Faithful Python port of the Sappy/m4a engine-detection logic | Upstream states: "GBAMusRipper is free and open source software. Anyone is free to redistribute it ... but just give me (Bregalad) credit." Credit is given in the file header; no formal upstream license text exists. |

## Patterns (approach credited; no code copied)

| Our file | Pattern from | Note |
|---|---|---|
| `tools/attract_check.py` | [mstan/WarioWareTwistedRecomp](https://github.com/mstan/WarioWareTwistedRecomp) `tools/verify-attract.ps1` (PolyForm NC 1.0.0) | Same workflow — headless fixed-frame run with a pinned frame hash — independently implemented in Python. |
| `src/ffta_ram_dispatch.h` | [mstan/EmeraldRecomp](https://github.com/mstan/EmeraldRecomp) `src/emerald_ram_dispatch.h` (PolyForm NC 1.0.0) | Uses gbarecomp's sanctioned `g_runtime_ram_dispatch_hook` extension point; the FFTA-specific byte-verification logic is original. |

## Reference material (not redistributed)

Community research is used as reference only, with attribution (see
`BRINGUP.md` studies): Data Crystal wiki, LeonarthCG/FFTA_Engine_Hacks,
LeonarthCG/FFTA_Event_Editor (**GPL-3.0** — opcode semantics and table
structure referenced; its code is never copied or ingested),
spiiin/FFTAUtils, charlie-troy/ffta-decomp (**no license** — facts and
addresses referenced; its sources/logs are never ingested), and the
JoKyR / BCROBERT / GameFAQs guide authors (facts and brief attributed
quotes only; full copies are not distributed with this repository).

### Data Crystal pages (the one included exception)

`reference/datacrystal/` holds text extractions of recovered
`datacrystal.romhacking.net` wiki pages, redistributed under the **GNU Free
Documentation License 1.2** — full license text in
`reference/datacrystal/LICENSE-GFDL-1.2.txt`, attribution and source links in
`reference/datacrystal/README.md`. Those files stay under GFDL 1.2; the rest
of the repository is PolyForm Noncommercial 1.0.0. (The recovered
string-tables dump is **not** included — it is ROM-extracted game text,
and is not distributed with this repo.)
