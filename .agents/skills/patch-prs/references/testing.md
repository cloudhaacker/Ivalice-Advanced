# Testing: every PR gets a test if possible

Default: add or extend a regression test. Exception: document *why not* in
the PR body under `Test note:` — never silently skip.

## Proven patterns (tmp-clone paths)

| PR | Test | Shape |
|---|---|---|
| mmio (#33) | `tests/dma/test_main.cpp` | Extend `TestBus` with `set_io` forwarding IO-range writes to `GbaIo`; 32-bit CNT_L+CNT_H store kicking immediate DMA to WAITCNT must record delta 4 (3×size-4 + 1×size-2) with addr/size/value asserts |
| swi-ledger (#34) | `tests/armv4t/tail_dispatch_test.cpp::test_swi_return_ledger` | Drive real `runtime_swi`/`runtime_exception_return` via stub harness; corrupted return overridden, legal untouched, empty ledger (post-`runtime_fp_reset`) never overrides |
| split-loop (#36) | `function_finder_tests` + `link_branch_tests` | Finder: host extent covers back-edge block + alias entry, no standalone fn. Emit: count `goto L_..` == 2 (resume prologue + branch), assert no `GBARECOMP_TAIL_DISPATCH` to the block |
| stack-guard (#38) | `tests/runtime/stack_guard_test.cpp` (new) | Unarmed predicates false; armed 4 MiB reserve, ~1500-frame descent trips budget before critical tier |
| pacer (#43) | `tests/runtime/pacer_test.cpp` (new, 1 kHz) | wait(1) prompt; wait(4) sleeps all periods; wait(100000) clamps; uncapped immediate |

Existing-suite anchors: `tail_dispatch_tests` (SWI parity),
`interpreter_smoke`, `codegen_tests` (131/131), `codegen_shards_tests`,
`selfheal_cluster_test`, `diagnostic_capture_tests --enabled/--disabled`,
`mod_state_tests`, `mod_runtime_tests` (needs `build-mods`),
`bootstrap_test.js` (web `--state-dir` plumbing).

## Test-writing traps hit

- Tail-call collapse: a `return descend(d+1)` loop reuses one frame —
  make the call non-tail (use the result after return) and keep a
  `volatile char pad[4096]` live across it. Verify depth with a frame
  counter before trusting the test.
- `static` env caching (`mmio_cap_enabled` reads env once): `setenv`
  before the first record call in that process; separate binaries are
  naturally hermetic.
- Counting `goto L_..`: the resume prologue legitimately holds one —
  assert == 2, not >= 1, and assert the tail-dispatch is *absent*.
- Pool bytes decode as instructions: keep test ROMs tiny and assert on
  the quantities you own (extents, aliases, labels), not full bodies.
- `git stash push -- <src>` for a negative control also stashes nothing
  when files are already committed — use `git show upstream/main:<path>`
  overwrite + rebuild instead, then `checkout HEAD -- <path>` to restore.
- Untracked test files survive `stash`/`checkout --`; a stray `sed` on
  them needs a rewrite via `write`, not `checkout`.

## Negative control (required for every new test)

1. New test + fix → PASS (run 3× for timing tests).
2. Revert *only* the `src/` hunk(s) (`git show upstream/main:<file> > ...`),
   rebuild, run → must FAIL on the key assertion
   (e.g. delta 3 vs 4, `back-edge block became its own function`,
   `did not lower to a goto`, unarmed-always-false).
3. Restore (`apply` the bundle patch or `checkout HEAD --`), rebuild →
   PASS again.
4. Quote the FAIL→PASS pair in the PR body.

## Legitimate no-test cases (template)

- TU-local state (`record_and_log_miss`/`g_misses`, `Runtime`/`save_state`
  in anonymous namespaces) with no seams — a test would expand the diff.
- Thread-timing properties (heal-worker shutdown bound).
- Live-harness-only behavior (IRQ roundtrip — upstream `irq_tests` is a
  Phase-3 stub; launcher UI — flows straight into UI code).
- Missing closed artifacts (oracle needs `third_party/mgba` + ROM + `.sav`).
- CLI parsing (`parse_cli` TU-local) — cite build + adjacent suite instead.
- Two-process races (pid-temp) — cite both mod suites passing + byte-identical
  single-process output shape.
