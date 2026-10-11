# PR body: TLDR + criticality, docs, open/update flow

## Body template (prepend header, keep existing body)

```md
> **TLDR:** <one sentence: what was broken → what this does>.
>
> **Criticality: P<n> — <label>.** <who it affects + blast radius. Risk note.>
>
> ---
>
<existing problem / change / notes / test note, unchanged>
```

## Criticality scale (as applied to the batch)

- **P0 — Critical.** Correctness corruption or silent data loss, any-game
  blast radius: #33 MMIO-cap, #34 SWI ledger.
- **P1 — High.** Hang/stack/crash/timing fix or major perf: arm-core#4 +
  #36 split-loop (perf + stack safety), #37 selfheal (crash safety +
  close liveness), #38 stack-guard (crash prevention), #39 IRQ close
  (hang fix), #43 pacer (timing correctness).
- **P2 — Medium.** Races and enablers, narrow or gated blast radius:
  #35 mod-state (parallel launches), #41 state-dir (fixes merged-but-broken
  flag; mobile/web enabler, engine half only).
- **P3 — Low.** Tooling or opt-in UX, no runtime impact by default:
  #40 oracle (differential tooling), #42 launcher (explicit-flag-only
  behavior change; mark as proposal).

## Docs convention

Default: **no docs update**. Upstream `docs/DEBUGGING.md` documents zero
`GBARECOMP_` flags; existing self-heal flags (`SELFHEAL_VERBOSE`,
`TRACE_ON_DISPATCH_MISS`) are code-comments only. Only perf-relevant flags
are tabled in `docs/RUNTIME_PERFORMANCE.md`. New default-off bring-up flags
(`MISS_FRAG`, `BRIDGE_ENTRY_FP`/`_ABORT_FP`) follow the code-comment
convention — thorough comments at the definition site, no table row. Add a
row only if the flag changes hot-path cost. State the decision in the
session, don't silently add docs.

## Open / update flow (one at a time)

1. Present the TLDR + criticality block and proceed only on approval.
   Prepend via `--body-file` (never inline `--body` — quoting breaks on backticks).
2. Same gate for PR creation: send the link, then ask whether to continue.
3. Prepend implementation: fetch current body
   (`gh pr view <n> --json body --jq .body`), write
   `header + body` to `/tmp/patch-prs/pr<n>-newbody.md` with python, then
   `gh pr edit <n> --body-file <file>`. Verify with a short `gh pr view`.
4. Amended commits: `commit --amend --no-edit` + `push --force-with-lease`,
   then refresh the body (test paragraph, stat line) the same way.
