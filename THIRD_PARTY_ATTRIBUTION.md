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

## Framework

| Component | Upstream | License |
|---|---|---|
| `gbarecompx/` (pinned submodule) | <https://github.com/james2doyle/gbarecompx> — a fork of <https://github.com/mstan/gbarecomp> | PolyForm Noncommercial 1.0.0, © 2026 Matthew Stanley (upstream); fork changes by James Doyle under the same terms |

The submodule **is** the framework fork: it carries the former
working-tree patch set as committed history (the launch screen, the
tinyfiledialogs asset picker, the emibios default BIOS, the host-stack
guard, the SWI-return ledger, the MMIO cap fix, …) plus the in-game menu
and LCD work — there are no local patches to apply. Its nested
`external/arm-recomp-core` points at
<https://github.com/james2doyle/arm-recomp-core> (`cd010b5`,
`feat/in-body-forward-goto`). The recomp-ui dependency (former
launcher/runtime UI, MIT) was removed in the 2026-10 launcher track: the
pre-boot surface is the fork's raygui launch screen
(`src/runtime/launcher*.cpp`), and the in-game settings UI is the
framework's generic menu.

## Runtime HLE (mGBA-derived)

The BIOS HLE services (`gbarecompx/src/runtime/bios_hle.cpp`, enabled by
`game.toml [bios].hle`) port SWI semantics from mGBA's `src/gba/bios.c`
([mgba-emu/mgba](https://github.com/mgba-emu/mgba), MPL-2.0 — notice retained
in the file header plus `third_party/MPL-2.0.txt` upstream). The object code
links into every build (the hook installs only when HLE is on); unhandled
SWIs fall through to the recompiled LLE BIOS. No mGBA sources are vendored
here.

## Cross dependencies (statically linked into the release binaries)

The desktop release artifacts (`FFTARecomp-*-linux-x64.zip`,
`FFTARecomp-*-windows-x64.zip`, built by `tools/make_release.py` via
`tools/win_cross_deps.py`) link the libraries below. On Windows they are
**compiled in** (static MinGW build) and so ship inside the exe; on Linux
the same libraries come from distro packages. All are permissive-licensed;
none taints the game's PolyForm Noncommercial 1.0.0 terms. Versions live as
tarball-sha256 pins in `tools/win_cross_deps.py` (raylib is fetched by
pinned SHA at configure time — `gbarecompx/CMakeLists.txt`) or as vendored
files with recorded SHA-256s.

| Library | Source | License | Role |
|---|---|---|---|
| raylib | <https://github.com/raysan5/raylib> @ 6.0 | **zlib license**, © Ramon Santamaria (@raysan5) | window/input/audio backend (`src/runtime/raylib_backend.cpp`), since the 4c backend flip |
| tinyfiledialogs | <https://tinyfiledialogs.sourceforge.net> v3.21.2 | **zlib license**, © Guillaume Vareille | native open-file/message dialogs for the asset picker (`src/runtime/asset_picker.cpp`); vendored at `gbarecompx/third_party/tinyfiledialogs/`, unmodified |
| raygui | <https://github.com/raysan5/raygui> (5.1-dev) | **zlib license**, © Ramon Santamaria (@raysan5) | the pre-boot launch screen (`src/runtime/launcher_raygui.cpp` behind `src/runtime/launcher.h`); vendored at `gbarecompx/src/vendor/raygui/`, unmodified |

- License texts: [`LICENSES/ZLIB-raylib.txt`](LICENSES/ZLIB-raylib.txt),
  [`LICENSES/ZLIB-tinyfiledialogs.txt`](LICENSES/ZLIB-tinyfiledialogs.txt),
  [`LICENSES/ZLIB-raygui.txt`](LICENSES/ZLIB-raygui.txt) - each is the
  verbatim upstream license document (permissive-license documents are
  redistributed as-is by their own terms, same exception class as the
  GFDL/LGPL documents above). `tools/make_release.py` stages `LICENSES/`
  into every artifact.
- Windows-DLL note: raylib's static build depends on Windows system
  libraries only (kernel32/user32/gdi32/winmm/opengl32/... - OS components,
  not third-party redistributables); the objdump import-table guard in
  `make_release.py --windows` fails the build on any non-system DLL.
- The launcher's in-app file dialog is tinyfiledialogs with the
  console-input fallback disabled at runtime via the `tinyfd_query` probe
  (headless environments fail with a message instead of blocking on stdin).

## Launch-screen box art

`recomp/launcher/boxart.png` (also staged beside the release binaries as
`assets/img/boxart.png`) is the *Final Fantasy Tactics Advance* (USA) box
art from [Justme488/3-D-Box-Art](https://github.com/Justme488/3-D-Box-Art)
(`Nintendo - Game Boy Advance/Named_Boxarts/Final Fantasy Tactics Advance
(USA).png`).

- **License: none upstream.** The repository publishes no license text; the
  README states the images were not created by its maintainer and credits
  the EmuMovies Community. Provenance is therefore **unknown** and no
  license can be asserted for the image.
- **SHA-256:** `b375d9884033d55995bacc93cd8dfe34d48bfbac85d5e81fb2a9064b2f7db766`
  (the committed file must stay byte-identical to the upstream download; no
  re-encodes).
- **Posture decision:** this repo's default posture is "no game content in
  this repository". Shipping retail cover art of unknown provenance is a
  deliberate, explicitly signed-off exception (2026-10-16) made for the
  launch screen, with the upstream credits disclosed above. Rights holders
  who want the image removed can ask, and the launch screen degrades to its
  text fallback when the file is absent.

## Oracle tooling

`gbarecompx/oracle/setup-mgba.sh` clones
[mgba-emu/mgba](https://github.com/mgba-emu/mgba) (MPL-2.0) into an ignored
`third_party/` directory to build the frame-diff oracle. Not tracked, not
redistributed here.

(The `m4a_detect.py` ported-tool credit moved with the tool into the
framework's `gbarecompx/THIRD_PARTY_ATTRIBUTION.md`, 2026-10-18.)

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
