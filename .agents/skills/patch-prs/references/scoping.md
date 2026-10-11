# Scoping: ordering, strip/keep, bundles, ownership

## Impact order (critical first)

Agreed order for the gbarecomp batch (supersedes any big-to-small ask):

1. mmio-cap-dma-reentrancy (P0) — silent oracle data loss
2. swi-return-ledger (P0) — wrong-PC corruption
3. split-loop codegen bundle (P1) — arm-recomp-core + finder/emit
4. irq-abandon-close, simplified (P1) — hang fix
5. selfheal-journal-close-hardening (P1) — crash safety
6. host-stack-guard-desktop, stripped (P1)
7. mod-state-publish-race (P2)
8. oracle-save-autoload (P3)
9. android-external-state-dir / state-dir (P2, upstream part only)
10. touch-pad-idle-hide (skipped on request — do not revive unasked)
11. launcher-force-ui (P3, proposal)
12. frame-pacer-banked-wait (P1, added late — timing correctness)

Excluded outright: `yield-gate-probe` (diagnostic-only, never upstream).

## Strip / keep rules

- Keep generic env/diagnostic hooks: `GBARECOMP_MISS_FRAG`,
  `GBARECOMP_BRIDGE_ENTRY_FP` / `_ABORT_FP`, `GBARECOMP_BREAK_FP`,
  `GBARECOMP_SWI_TRACE` (if genuinely generic), bridge-entry log lines.
- Strip project-specific machinery: `g_abandon_resume_pc/T` redirect,
  `runtime_abandon_resume_pending` hook, game-named comments (`play.sh`
  → reword to "scripted wrappers"), abandon-resume one-unwind hook.
- Hunk ownership when patches interleave in `runtime.cpp` /
  `runtime_bus_bridge.cpp`:
  - `selfheal` owns the `emit_exit_diagnostics()`-before-join swaps.
    Every other PR drops those hunks on rebase.
  - `host-stack-guard` owns guard arming + `BREAK_FP`; excludes
    exit-ordering and abandon-resume.
  - `irq-abandon` is detect + close only; excludes resume redirect and
    unrelated SWI_TRACE instrumentation.
  - `selfheal` PR excludes stack-guard arming and touch idle-hide hunks.

## Cross-repo bundles (split-loop pattern)

- PR A (arm-recomp-core): `CodegenCtx.in_body_goto_targets` + forward-goto
  lowering. `nullptr` preserves old behavior. No test suite in that repo —
  coverage lands in the companion PR; `-fsyntax-only` suffices there.
- PR B (gbarecomp): finder gap roll-in + `emit_function` population,
  submodule pinned to PR A's commit. Body links the companion
  (`Companion to mstan/arm-recomp-core#N — happy to re-pin onto master
  once that merges`).
- Never let a stale submodule checkout leak into an unrelated PR:
  `submodule update --checkout` at each branch start; `git status --short`
  must show the submodule modified only on the bundle PR.
