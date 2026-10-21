# Orchestral music (experimental) — `ffta.enhancement.orchestra`

Replaces the game's **background music** with the same songs played through a
SoundFont. Sound effects, jingles on other players and everything else are
untouched. Off by default.

## How it works
* The game's m4a player is observed at three reviewed seams (game.toml
  `[[mod_function_hook]]`): `MPlayStart` 0x081458AC, `MPlayStop` 0x08145990,
  `MPlayFadeOut` 0x0814511C. Only the BGM player (0x0200F2A0, player 0 of the
  table at 0x0814BB24) is taken over — its `MPlayStart` is skipped, so the
  native BGM never starts while SFX players run as usual.
* `src/ffta_orchestra.h` is a small MP2K sequencer (song bytecode read live
  from the player's own ROM; nothing ROM-derived is stored in the repo) driving
  TinySoundFont (`third_party/tsf`, MIT). Output is 65536 Hz mono S16 through
  the framework's mod-audio pull stream.
* `src/ffta_orchestra_plugin.cpp` is the glue; `tools/orchestra_render.cpp`
  renders any song offline to WAV with the identical engine.
* `tools/m4a_to_midi.py` dumps every song to MIDI for auditioning.

## Setup
This build has no Mods screen yet (the raygui launcher/menu does not expose
the mod provider), so selections live in `mods/state.toml` beside the exe.
On Windows put `FluidR3_GM.sf2` (SHA-1 `4fd467af...`, 148 398 306 bytes; not
redistributed) next to `FFTARecomp.exe` and run
`tools/windows/enable_orchestra.bat`, which writes that file. Delete
`mods/state.toml` to turn the feature off. A real in-game Mods page is the
planned follow-up.

## Known gaps (MVP)
* Instrument map is identity (FFTA voice number = GM program); to be refined
  by ear. Drum/percussion voices are not yet routed to a drum kit.
* No vibrato/LFO/tuning, reverb or per-track priority; mono output only.
* Player pause/continue, tempo and volume-control calls are not mirrored.
* Songs that a script waits on (jingles) may behave differently because the
  native BGM player never runs while this is enabled.
