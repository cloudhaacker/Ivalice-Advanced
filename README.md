# Final Fantasy Tactics Advance Recomp

> **Experimental preview.** This recompilation is built on
> [gbarecomp](https://github.com/mstan/gbarecomp), the reusable
> static-recompilation framework whose reference games are its proving
> ground. This is not a finished commercial port, so expect rough edges and
> please report problems. For more context, read
> [Recomp + AI: 5 Months Later »](https://1379.tech/recomp-ai-5-months-later/).

Static recompilation of **Final Fantasy Tactics Advance** for Linux and
Android, with a validated widescreen view and strict fully-static execution.

The game ROM is **not included**. You must provide your own legally obtained
dump of *Final Fantasy Tactics Advance* (USA). The launch BIOS **is**
included: a clean-room, freely redistributable
[emibios](https://github.com/coolbho3k/emibios) build committed at `bios/` —
no Nintendo BIOS dump is required.

## Features

- Native Linux, PC, and Android builds
- Keyboard, controller, and touchscreen controls
- Windowed and fullscreen desktop play
- Validated widescreen view up to 448 px
- Cartridge saves and save states
- Fast-forward speed boost — hold `Tab` / right trigger, tap the `FF`
  touch pill, or latch it from the menu; speed (2–10x) set in Assist Tools
- Strict fully-static execution — zero interpreter fallback on any executed
  path, kept that way by a self-healing coverage loop
- GBA screen simulation: `raw`, `unlit`, `frontlit`, `backlit`, `classic`
- Launch screen with box art and a native file-dialog ROM picker; ROM and
  BIOS hashes verified at launch

## Controls

| GBA control | Keyboard | Controller |
|---|---|---|
| D-Pad | Arrow keys | D-Pad / left stick |
| A / B | X / Z | A / B |
| Start | Enter | Start |
| Select | Backspace | Back (Select) |
| L / R | C / V | LB / RB |
| Fast-forward (hold) | Tab | Right trigger |
| In-game menu | Esc | Guide button |

Controllers are detected automatically, and button mappings can be changed
in the in-game menu. The left analog stick doubles as the D-Pad.
Fast-forward runs the game faster while held; its speed (2–10x) and
key/pad bindings are configurable in the in-game menu. On Android, use the
on-screen touch controls — tap the `FF` pill at the top of the screen to
toggle the speed boost; open the menu with a long-press, three-finger tap,
or the system Back gesture (Esc again steps back inside the menu).

## Quick start

### Using a release binary (no build)

Grab the latest release zip from [releases](../../releases) — Linux x64
(`FFTARecomp-*-linux-x64.zip`) or Windows x64
(`FFTARecomp-*-windows-x64.zip`, statically linked, no DLLs) — then:

1. Extract the folder anywhere **writable** — the ROM pick, menu
   settings, and saves are kept beside the executable.
2. Run it — `./FFTARecomp` on Linux, `FFTARecomp.exe` on Windows (no
   DLLs to install; everything is statically linked). The launch screen
   opens; the first boot opens the native file picker right away.
3. Pick your legally obtained *Final Fantasy Tactics Advance* (USA) ROM
   and select **Play**. The pick is remembered, so later boots open ready
   to play — **Select ROM** re-picks, and dropping a `.gba` file onto the
   window works too.

The launch BIOS is bundled — a clean-room, freely redistributable
**emibios** build
([`bios/`](bios/) in the zip, LGPL-3.0-or-later) — so you never need a
Nintendo BIOS dump. Your ROM is hash-verified at launch: a mismatch error
means the file is not the expected USA dump.

System requirements — Linux x86-64 with OpenGL and an X11/Wayland desktop
(Debian/Ubuntu: `libgl1 libglu1-mesa libx11-6` — preinstalled on desktop
systems); Windows 10+ x86-64 with nothing extra (static exe).
Display and widescreen options (`--view-width 448`,
`--resize-view`, `--scale`, fullscreen) are listed in
[docs/README.md](docs/README.md).

### Desktop (Linux)

1. Clone with submodules and place your legally obtained ROM dump at the
   repo root:

   ```sh
   git clone --recurse-submodules https://github.com/james2doyle/ffta-recomp.git
   cd ffta-recomp
   cp /path/to/ffta-usa.gba game.gba
   ```

2. Build with the idempotent bootstrap script (dependencies → framework
   patches → recompilation → build → strict smoke test):

   ```sh
   python3 build.py
   ```

3. Run the self-built binary. With no arguments it opens the launch
   screen (the first boot opens the file picker) — pick your
   **Final Fantasy Tactics Advance (USA)** ROM and select **Play**:

   ```sh
   ./build/FFTARecomp
   ```

The BIOS is pre-filled from the bundled clean-room build and your ROM is
hash-verified at launch. Pass the paths directly — or run with any
headless flag (`--no-window`, `--frames`, `--load-state`, `--tcp`) — to
start the game without the launch screen:

```sh
./build/FFTARecomp --bios bios/emibios_gba_bios.bin --rom game.gba
```

Display and window options (`--scale`, `--screen`, fullscreen, widescreen)
are listed in [docs/README.md](docs/README.md).

### Android

1. Complete the desktop quick start first — the APK build consumes the
   generated corpus and embeds your ROM.
2. Build the app:

   ```sh
   python3 build_apk.py
   ```

3. With a device attached, the script installs the APK and runs the
   boot-health gate. The ROM is embedded, so the app boots straight into the
   game. Full build, install, and device-validation instructions live in
   [`android/README.md`](android/README.md).

## Building from source

Desktop development requires CMake ≥ 3.20, Ninja, GCC or Clang (C++17),
git, Python 3.10+, and OpenGL + X11 development headers (Debian/Ubuntu:
`libgl-dev libx11-dev libxrandr-dev libxinerama-dev libxcursor-dev
libxi-dev libxkbcommon-dev`).

`python3 build.py` is the one-command route; re-running after a pull skips
finished steps. The raw pipeline it wraps — every step by hand, with
troubleshooting — is documented in
[`docs/manual-build.md`](docs/manual-build.md):

```sh
cmake -S gbarecomp -B gbarecompx/build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build gbarecompx/build --target gba_recompile gba_scan --parallel 8
./gbarecompx/build/gba_recompile --rom game.gba --config game.toml \
  --symbols symbols/ffta_symbols.tsv --data-symbols symbols/ffta_data_symbols.tsv \
  --out generated --max-functions 65536
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGBARECOMP_ENABLE_MODS=ON
cmake --build build --target FFTARecomp --parallel 8
```

Android build and device-validation instructions live in
[`android/README.md`](android/README.md).

> **Contributors:** the `gbarecompx` submodule **is** the framework —
> [james2doyle/gbarecompx](https://github.com/james2doyle/gbarecompx), the
> fork carrying the launch screen, the tinyfiledialogs picker, the emibios
> default BIOS, and every former local patch as committed history. A plain
> `--recurse-submodules` clone builds everything (no patches to apply).
> Framework changes land as fork commits (pushed), then the game repo's
> gitlink moves — see [`reference/dev-gotchas.md`](reference/dev-gotchas.md)
> § Submodules.

Generation requires the supported ROM revision — *Final Fantasy Tactics
Advance* (USA, AFXE), SHA-1 `4ac05441f4de70a4ec3dd932116346c61b8783d9`,
16,777,216 bytes — pinned in [`game.toml`](game.toml); the launch BIOS is
the bundled clean-room emibios ([`bios/README.md`](bios/README.md)).
ROM-derived generated code, saves, patches, frame dumps, and build output
remain local and are never committed.

Contributors can run `.venv/bin/python tools/check.py` for the automated
regression gate (host unit tests, attract hash, widescreen smoke, strict
route replays) and `tools/play.sh` for an instrumented playtest session.
Testing, debugging, coverage, and CI workflows live in
[`tests/README.md`](tests/README.md); the repository map in
[`docs/README.md`](docs/README.md); project rules in
[`AGENTS.md`](AGENTS.md).

## License

PolyForm Noncommercial 1.0.0 — see [`LICENSE`](LICENSE). Third-party
components retain their own licenses; see
[`THIRD_PARTY_ATTRIBUTION.md`](THIRD_PARTY_ATTRIBUTION.md).

## Legal

This is an unofficial, non-commercial preservation and research project. It
is not affiliated with or endorsed by Square Enix or Nintendo. Final Fantasy
Tactics Advance and related names, characters, artwork, and game data are
trademarks or copyrights of their respective owners.

No copyrighted game ROM or Nintendo BIOS data is distributed by this
project. The bundled BIOS is a clean-room replacement, not a Nintendo dump.

---

Part of the **R.A.I.D. — Retro AI Development** static-recompilation
community.
