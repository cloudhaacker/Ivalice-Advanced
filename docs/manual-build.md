# Manual build (what `build.py` automates)

Prefer `python3 build.py` (see the [Quick start](../README.md#quick-start)) —
it runs every step below idempotently and stops with an actionable hint when
something is off. This page is the reference + troubleshooting route: what the
script does, in order, so a broken step can be run by hand.

The sequence was verified end-to-end from a fresh clone on 2026-10-08
(submodules → tools → patches → BIOS → corpus → build → strict smoke +
attract gate).

**1. Clone with submodules.**
```sh
git clone <repo-url> ffta-recompiled && cd ffta-recompiled
git submodule update --init --recursive
# If a submodule worktree comes up empty, re-run with --checkout --recursive
```

**2. Place your ROM dump** — `game.gba` at the repo root (FFTA USA). Launch
verifies the ROM hash (SHA-1 in the root README § Building from source) and
fails loudly if it is
wrong or missing. No BIOS dump is needed: the launch BIOS is the bundled
clean-room emibios at `bios/emibios_gba_bios.bin` (issue #17). The Windows
release build needs the **same** ROM for its corpus translation (the ROM
is never embedded — the packaged sweep proves it); it cross-compiles from
this tree, it does not rerun these steps on a second machine.

**3. Python venv for the tooling** (the harness scripts):
```sh
uv venv .venv
#   (or: python3 -m venv .venv)
```

**4. Build the framework tools** (one-time; re-run only after submodule
changes):
```sh
cmake -S gbarecomp -B gbarecompx/build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build gbarecompx/build --target gba_recompile gba_scan --parallel 8
```

**5. Recompile the BIOS (one-time).** Run it *from `gbarecompx/`* so the
output lands in `gbarecompx/src/runtime/generated_bios/`, and pass the
project's BIOS config — it seeds the named emibios functions from the build
ELF (plus the two statically-unreachable fragments: the `after_interrupt`
trampoline epilogue and the runtime-installed `.vc_irqh` boot handler) and
identity-checks the committed clean-room BIOS (issue #17):
```sh
cd gbarecompx && ./build/gba_recompile \
  --bios ../bios/emibios_gba_bios.bin \
  --config ../bios/emibios_gba_bios.toml && cd ..
```

**6. Generate the game's static code corpus** (also after every `game.toml`
change — `tools/cycle.py` wraps this with the sanity checks and the attract
gate):
```sh
./gbarecompx/build/gba_recompile --rom game.gba --config game.toml \
  --symbols symbols/ffta_symbols.tsv --data-symbols symbols/ffta_data_symbols.tsv \
  --out generated --max-functions 65536
```

**7. Configure and build the game binary:**
```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGBARECOMP_ENABLE_MODS=ON
cmake --build build --target FFTARecomp --parallel 8
```

The `gbarecomp` submodule **is** the framework: james2doyle/gbarecompx —
the fork carrying the raygui launch screen, the tinyfiledialogs asset
picker, the emibios default BIOS, and every former local patch as
committed history. A plain `--recurse-submodules` clone builds everything;
there are no working-tree patches to apply.

(`GBARECOMP_ENABLE_MODS=ON` links the framework's mod lifecycle APIs —
activation/reset plugins, view-width requests — used by the game's
widescreen hooks; verified gate-neutral.)

**8. Sanity.** Strict, headless, no input — expect `FULLY_STATIC` in the
banner:
```sh
GBARECOMP_STRICT_STATIC=1 ./build/FFTARecomp \
  --bios bios/emibios_gba_bios.bin --rom game.gba --frames 2400 --no-window
```
And optionally the attract gate, which pins the exact frame hash:
```sh
.venv/bin/python tools/attract_check.py    # PASS + exit 0 expected
```

Then play — run the built binary (`./build/FFTARecomp`; running and display
options: [README.md](README.md)). For an *instrumented playtest session*
use `tools/play.sh` (guide: [`tests/README.md`](../tests/README.md)).

## Troubleshooting

- `build.py` stops at **dumps** → the ROM or BIOS is missing or has the
  wrong hash (ROM SHA-1: root README § Building from source; BIOS pin:
  `bios/README.md`); it never downloads them.
- `build.py` stops at **framework patches** → the submodule drifted from
  its pin; check `git -C gbarecompx status`.
- `gba_recompile: command not found` → step 4 was not run in this checkout.
- `generated_bios/` stays empty / BIOS never loads → step 5 was run from the
  wrong directory (`cd gbarecompx` first). If strict runs instead abort with
  a dispatch miss near pc `0x300`, step 5 ran without
  `--config ../bios/emibios_gba_bios.toml`.
- Launch aborts with an identity/hash error → wrong or missing dump; compare
  against the pinned SHA-1s (ROM: root README § Building from source; BIOS:
  `bios/README.md`).
- CMake cannot find OpenGL/X11 development headers → install them (the
  Debian/Ubuntu set is listed in the root README § Building from source).
- MinGW cross (static Windows build, R2): the toolchain is
  `mingw-w64-toolchain` from pacman (`x86_64-w64-mingw32-gcc` — check with
  `command -v`); the dependency prefix is built from pinned sources, not
  packages (`tools/win_cross_deps.py build` — Arch ships no mingw binary
  library packages, MSYS2 is Windows-only). A dynamic third-party DLL
  import in the exe (libstdc++/winpthread/…) means the prefix leaked a
  DLL and the objdump guard will say so — rebuild the prefix after
  pruning, then the exe.
- a tool fails to import its deps → step 3's venv (use
  `.venv/bin/python tools/...`).
- A submodule directory is empty after cloning → step 1's retry line.
- Window refuses to close, or a session wedges → `gbarecompx/tools/quit.py <port>`; see
  `tests/README.md` § Playtesting & debugging.
- After `game.toml` edits: regenerate (step 6) → rebuild → attract gate, i.e.
  `.venv/bin/python tools/cycle.py`.

## mGBA oracle (optional)

The mGBA oracle used by the frame-diff harness (needs network
once; distinct from a system mGBA):

```sh
cd gbarecompx && bash oracle/setup-mgba.sh \
  && cmake -B build -S . -DGBARECOMP_BUILD_ORACLE=ON \
  && cmake --build build --target gbarecomp_oracle --parallel 8
```
