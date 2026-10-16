# tools/ — the harness

The developer/testing harness around the game: playtest instrumentation,
the coverage/healing loop, regression gates, Android checks, and
ROM-analysis utilities.

**For playing, run the built binary directly** — see
[docs/README.md](../docs/README.md). `tools/play.sh` is the *testing*
entry, not the play entry. For when-to-run-what (workflows, gates, CI), see
[tests/README.md](../tests/README.md).

| Tool | What |
|---|---|
| `play.sh` | Instrumented windowed playtest: input recording, live miss journaling, persistent battery save, previous-session archiving. Extras: `--tcp-observe PORT`, `--scale N`, `--fullscreen` |
| `check.py` | Full regression gate: host unit tests, attract hash, widescreen smoke, strict route replays (`--fast`, `--only a,b`, `--jobs N`) |
| `make_release.py` | Desktop release packager (issue #3 R-track): allowlist stage → private-material sweep (hash-pinned ROM/BIOS rejection) → deterministic portable zip; refuses a stale build. `--apk` adds the guarded public Android APK artifact (clean repackage, ROM-less, `--expect public`). `--windows` adds the static cross-compiled Windows exe artifact (MinGW static, zero DLLs, objdump-guarded, wine-smoked; ROM-less). Runs as `check.py --only release` |
| `win_cross_deps.py` | Pinned static cross-dependency prefix for `--windows`: raylib only (raylib-only since the 2026-10 launcher track) into `cross-prefix/` (idempotent markers; sha256-pinned tarballs). Why source builds: Arch has no mingw binary library packages (and MSYS2 is Windows-only). `fetch` / `build` / `status` / `clean` / `purge` |
| `mingw-x64.cmake` | CMake cross toolchain for `--windows` (x86_64-w64-mingw32, prefix-first search) |
| `cycle.py` | Change cycle after `game.toml`/`src/` edits: cold regen → dispatch sanity → build → attract gate |
| `resolve.py` | Strict-replay miss seeder — seeds a trace's misses through a temp overlay, repeats until FULLY_STATIC (`--trace <csv>`, `--load-state`) |
| `cache_harvest.py` | Post-crash miss harvesting (`--out logs/proposal.frag`) |
| `misspack.py` | Evidence pack for a miss fragment (`--stubs`, `--pc 0x...`) |
| `attract_check.py` | Attract golden gate (`--repin` only for deliberate changes) |
| `ws_check.py` | Widescreen smoke test (fixtures `saves/ws_fixtures/`) |
| `savecheck.py` | Save-image validation |
| `desktop_accept.py` | Headless free-run acceptance scoring (`--mode tcp` / `--mode window`) |
| `coverage_report.py` | Coverage report, three lenses |
| `framediff.py` / `dualrun.py` | Oracle frame-diff / lockstep differential runs |
| `cadence_probe.py` | Render-path update-cadence gate (the compute-at-60/read-at-30 detector): pauses the pacer on `--tcp`, steps exactly one VBlank at a time, asserts the 60 Hz scheduler invariants (frame_step parities, `gVblankCounter`) and no every-other-frame consumer on the presented surfaces (io/oam/pal/vram + display-reg shadow; IWRAM staging alternation is the double-buffer slot write and only reported). `--strict`, `--regions`, `--json`; `check.py --only cadence` |
| `ringscan.py` | Instruction-ring query (`--file`, `--pc`, `--reg-range`) |
| `keyprobe.py` | Live debug-port inspector |
| `audio_session.py` | Live audio-fault triage around a play session: samples `audio_state`+`frame` (20 Hz) and `audio_trace` (4 Hz; launch the game with `GBARECOMP_AUDIO_FIFO_TRACE=1`), records the sink monitor, then prints a report (producer rate vs 65536 Hz, frame cadence, FIFO fill/empty events, broadband-transient + 0.3-5 Hz modulation scan). Use with `play.sh --tcp-observe PORT`; `--max-seconds`, `--no-record`, `--sink` |
| `trace_split.py` | Split mid-session reload traces |
| `disarm.py` | ROM disassembler — the evidence source behind every address claim in the project |
| `m4a_detect.py` | m4a audio-engine detection (Bregalad lineage) |
| `android_static_check.py` | Device-free Android checks: identity pins, payload contract, hygiene (CI tier 1) |
| `android_apk_check.py` | APK content guard for built APKs (`--expect public/private`) |
| `validate_android.sh` | On-device acceptance gate: install → launch → assertions → evidence |
| `android_press_test.py`, `android_lifecycle_test.py`, `android_touch_test.py`, `android_trace_replay.py` | On-device gates — see [android/README.md](../android/README.md) |

The remaining scripts (`chunkprobe.py`, `hangprobe.py`, `hangrepro.py`,
`spinhunt.py`, `pc0_hunt.py`, `eventcrawl.py`, `hle_audit.py`,
`livewatch.py`, `readseq_probe.py`, `derail_loop.sh`, `quit.py`, …) are
one-off probes from bring-up sessions; the table above is the maintained
harness.
