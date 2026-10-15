#!/usr/bin/env bash
# play.sh — interactive desktop playtest of FFTA Recomp.
#
# Launches the windowed build with the audit instrumentation already on:
#   * input recording  -> logs/playthrough.csv        (replayable keystate trace)
#   * miss logging     -> logs/playtest_misses.frag   (self-heal proposals)
#   * persistent save  -> saves/playtest.sav          (flash image)
#
# Self-heal is ON (not strict): unmapped code is bridged instead of aborting,
# so the session never hard-stops; every miss is recorded and later runs
# through tools/misspack.py -> game.toml seeds.
#
# Controls: arrows = D-pad, X = A, Z = B, Enter = Start, Backspace = Select,
#           C = L, V = R. Close the window (or Ctrl-C the terminal) to quit.
#           (Or your keybinds.ini rebinds — config is read from the exe's
#           directory, so each build dir has its own copy.)
#
# Backend: raylib (`build-raylib-only/FFTARecomp`) while it is under active
# validation. Pass --sdl to run the SDL build (`build/FFTARecomp`) instead;
# --sdl is consumed here, everything else passes through to the game.
#
# Extras:  tools/play.sh --fullscreen            windowed fullscreen
#          tools/play.sh --tcp-observe 19850     window + live debug port;
#              inspect from another terminal: .venv/bin/python tools/keyprobe.py
#              19850   NOTE: plain --tcp is structurally headless (the TCP
#              branch returns before window init) — never combine it with a
#              window.
#          tools/play.sh --launcher       run the settings UI first
#          tools/play.sh --scale 8        bigger window: Nx240 x Nx160
#              pixels (scale 1-8; 8 = 1920x1280 on a 4K-class display)
#          tools/play.sh --fullscreen     borderless desktop fullscreen
#              NOTE: --view-width is the widescreen *view* feature, NOT
#              window size; FFTA is unsupported there (clamps to 240).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs saves
# Preserve the previous session's savestates + input trace before they get
# overwritten (states are destructive across sessions; the trace is replay
# evidence for the last session's route).
ts=$(date +%Y%m%d_%H%M%S)
for slot in game.state1 game.state2; do
  n="${slot#game.state}"
  [ -f "$slot" ] && cp "$slot" "saves/state${n}_prev_${ts}.state" || true
done
[ -f logs/playthrough.csv ] && cp logs/playthrough.csv "saves/trace_prev_${ts}.csv" || true
# The miss proposal is journaled live while the session runs (durable across
# unclean closes) and rewritten with final counts on a clean exit — archive
# it too, so back-to-back sessions can't clobber the previous proposals.
[ -f logs/playtest_misses.frag ] && cp logs/playtest_misses.frag "saves/frag_prev_${ts}.frag" || true
# Backend selection: raylib by default (see header), --sdl for the SDL build.
# The flag is filtered out before "$@" reaches the game.
EXE=./build-raylib-only/FFTARecomp
ARGS=()
for a in "$@"; do
  if [ "$a" = "--sdl" ]; then
    EXE=./build/FFTARecomp
  else
    ARGS+=("$a")
  fi
done
if [ ! -x "$EXE" ]; then
  echo "play.sh: $EXE missing. Build it first:" >&2
  if [ "$EXE" = "./build-raylib-only/FFTARecomp" ]; then
    echo "  cmake -S . -B build-raylib-only -G Ninja -DCMAKE_BUILD_TYPE=Release -DGBARECOMP_USE_RAYLIB=ON" >&2
    echo "  cmake --build build-raylib-only --target FFTARecomp --parallel 8" >&2
  else
    echo "  cmake --build build --target FFTARecomp --parallel 8" >&2
  fi
  exit 1
fi
exec env -u GBARECOMP_STRICT_STATIC \
  GBARECOMP_INPUT_RECORD="$PWD/logs/playthrough.csv" \
  GBARECOMP_MISS_FRAG="$PWD/logs/playtest_misses.frag" \
  "$EXE" --bios bios/emibios_gba_bios.bin --rom game.gba \
  --save-path saves/playtest.sav "${ARGS[@]}"
