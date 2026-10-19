# Final Fantasy Tactics Advance Recomp

> **Experimental preview.** This recompilation is built on
> [gbarecompx](https://github.com/james2doyle/gbarecompx), the actively
> developed fork of [gbarecomp](https://github.com/mstan/gbarecomp) — the
> reusable static-recompilation framework whose reference games are its
> proving ground. This is not a finished commercial port, so expect rough
> edges and please report problems. For more context, read
> [Recomp + AI: 5 Months Later »](https://1379.tech/recomp-ai-5-months-later/).

Static recompilation of **Final Fantasy Tactics Advance** for Linux,
Windows, Android, and Steam Deck, with a validated widescreen view and
strict fully-static execution.

The game ROM is **not included**. You must provide your own legally obtained
dump of *Final Fantasy Tactics Advance* (USA). The launch BIOS **is**
included: a clean-room, freely redistributable
[emibios](https://github.com/coolbho3k/emibios) build committed at `bios/` —
no Nintendo BIOS dump is required.

## Features

- Native Linux, Windows, Android, and Steam Deck builds — portable Linux
  zip, Steam Deck/SteamOS AppImage, static Windows exe, and an Android APK
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
| In-game menu | Del | Guide button |

Controllers are detected automatically, and button mappings can be changed
in the in-game menu. The left analog stick doubles as the D-Pad. Inside the
menu, the D-Pad/arrows move, A selects, and B goes back; `Del` or the Guide
button opens and closes it. Fast-forward runs the game faster while held;
its speed (2–10x) and key/pad bindings are configurable in the in-game menu.

On Android, use the on-screen touch controls — tap the `FF` pill at the top
of the screen to toggle the speed boost; open the menu with a long-press,
three-finger tap, or the system Back gesture. Use the on-screen A/B buttons
to select and go back inside the menu.

## Quick start

Release builds are ROM-less: download one, supply your own legally obtained
*Final Fantasy Tactics Advance* (USA) dump, and pick it on the launch screen.
The clean-room BIOS is bundled and verified, so no Nintendo BIOS dump is
needed.

Grab the latest release from the
[releases page](https://github.com/james2doyle/ffta-recomp/releases).

### Linux

1. Download `FFTARecomp-*-linux-x64.zip` and extract it anywhere
   **writable** — the ROM pick, menu settings, and saves are kept beside
   the executable.
2. Run `./FFTARecomp`.
3. The launch screen opens; the first boot opens the native file picker
   right away. Pick your USA ROM and select **Play**. The pick is
   remembered, so later boots open ready to play — **Select ROM** re-picks,
   and dropping a `.gba` file onto the window works too.

Requires an x86-64 Linux desktop with OpenGL and X11/XWayland.

### Windows

1. Download `FFTARecomp-*-windows-x64.zip` and extract it anywhere
   **writable**.
2. Run `FFTARecomp.exe` — it is statically linked, with no DLLs or
   installer.
3. Pick your USA ROM on the launch screen and select **Play**.

Requires Windows 10 or newer, x86-64.

### Steam Deck / SteamOS (AppImage)

1. Download `FFTARecomp-*-linux-x86_64.AppImage`, mark it executable
   (`chmod +x`), and run it from Desktop Mode or add it as a non-Steam
   game.
2. The first run unpacks the game beside your user data under
   `~/.local/share/ffta-recomp/app` (or `$XDG_DATA_HOME/ffta-recomp/app`)
   and runs from there, because the game writes `rom.cfg`, settings, and
   saves beside the executable and an AppImage mount is read-only.
   Updating the AppImage refreshes the game files but keeps those player
   files.
3. Pick your USA ROM on the launch screen and select **Play**.

In Game Mode the AppImage defaults to borderless fullscreen with the
resize-driven widescreen view; pass `--window`, `--scale`, or
`--view-width` to override, or set `FFTA_APPIMAGE_NO_DECK_DEFAULTS=1`.
The launch-screen file picker uses the system dialog (zenity/kdialog on
SteamOS). If that is unavailable, add `--rom /path/to/ffta.gba` as a Steam
launch option once; the pick is remembered. If FUSE is unavailable, run
with `APPIMAGE_EXTRACT_AND_RUN=1` or `--appimage-extract-and-run`.

The AppImage and Linux zip are built in a pinned Debian 12 container
(`tools/compat_build.py`) and require **glibc 2.35 or newer**, which
SteamOS 3.x provides. A binary built on a rolling host can require a newer
glibc than SteamOS ships.

### Android

1. Download `FFTARecomp-*-android-arm64-v8a.apk` and sideload it on an
   arm64 Android device. The current release APK is debug-signed, so allow
   installation from your browser or file manager when prompted.
2. Open the app and tap **Select ROM**; choose your USA dump. The ROM is
   hash-verified at launch, and the bundled BIOS needs no separate pick.
3. Select **Play**. Settings and saves live in the app's data directory.

Requires Android 9 or newer (API 28), arm64-v8a.

### System requirements

| Platform | Runs on |
|---|---|
| Linux | x86-64 with OpenGL and X11/XWayland. Debian/Ubuntu: `libgl1 libglu1-mesa libx11-6` (normally preinstalled on desktops) |
| Steam Deck | SteamOS 3.x, x86-64; AppImage (FUSE) |
| Windows | Windows 10+ x86-64; static executable, nothing extra |
| Android | Android 9+ (API 28), arm64-v8a |

Apart from the system OpenGL/X11 stack (and the standard C++ runtime), the
release builds are self-contained; no additional game runtime libraries
need to be installed.

Display and widescreen options (`--view-width 448`, `--resize-view`,
`--scale`, fullscreen) are listed in [docs/README.md](docs/README.md).

## Building from source

Release players do not need this. Source-build requirements, the
one-command `python3 build.py` route, the manual pipeline, the Android
build, and contributor notes are documented in
[docs/manual-build.md](docs/manual-build.md).

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
