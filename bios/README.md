# bios/ — the bundled clean-room GBA BIOS

`emibios_gba_bios.bin` is the project's **launch BIOS** (pinned by
`game.toml` / `android/game_android.toml [bios]`): a build of
[coolbho3k/emibios](https://github.com/coolbho3k/emibios) `main @c4d5d71` —
a clean-room, freely redistributable BIOS replacement, **LGPL-3.0-or-later**
(license text: `../LICENSES/LGPL-3.0-or-later.txt`; attribution:
`../THIRD_PARTY_ATTRIBUTION.md` § Bundled clean-room BIOS).

This is **not** a Nintendo BIOS dump and contains no Nintendo code — that
class of file is never committed (`.gitignore`; `android-static`'s
tracked-artifact hygiene check still rejects a file named `gba_bios.bin`
outright). Integrity is pinned by the `android-static` suite: exactly
16 KiB, SHA-1 `0c0d404d16c6b55b3071aba714f82077da132f14`, matching the
`[identity]` pin in `emibios_gba_bios.toml`.

`emibios_gba_bios.toml` is the recompilation config (`build.py` step_bios →
`gba_recompile --bios`): named functions from the build ELF's symbol table,
modes from the `$a`/`$t` mapping symbols, plus the exception-vector tail and
the two statically-undiscoverable fragments (`.vc_irqh` @ `0x3E74` —
emibios's runtime-installed interim VBlank handler — and the
`after_interrupt` trampoline epilogue @ `0x138`), each with its
disassembly-evidence note.

Rebuilding after an emibios update: place the new 16 KiB binary here, update
the `[identity]` pin, the `[bios]` pins in both game TOMLs, the
`biosSha1` manifest pin in `android/app/build.gradle`, and the
`EMIBIOS_SHA1` constant in `tools/android_static_check.py`; then re-run
`build.py` (BIOS recompile → corpus → build) and the full gate
(`tools/check.py`).
