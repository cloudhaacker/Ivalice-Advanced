---
name: patch-prs
description: Turn local working-tree patches into upstream PRs, one at a time, without disturbing other agents in the repo. Covers isolated tmp-clone workflow, impact-first ordering, surgical scoping (strip project-specific hunks), drift porting, per-PR regression tests with negative controls, TLDR + criticality PR bodies, and docs conventions. Use when exporting tools/patches/*.patch to gbarecomp or arm-recomp-core as pull requests.
---

# Patch-to-PRs Playbook

Export local `tools/patches/*.patch` files as upstream PRs. Impact-sorted,
critical-first, one at a time, zero writes to the project repo during prep.

**Vocabulary.** The **pin** is the `gbarecomp` commit the game repo builds
against (e.g. `ecc9c55`). **Drift** is upstream `main` movement since the
pin. A **hunk** is one `@@` block. **Surgical scoping** means selecting only
the PR's owned hunks and excluding interleaved ones. A **negative control**
is the new test run against unpatched `main` (must FAIL) then with the fix
(must PASS).

## Invariants (never violate)

- Zero writes to the game repo during prep. All work in the isolated clone
  (`/tmp/patch-prs/gbarecomp-upstream-prep`). Never bump the game repo pin
  before PRs merge.
- Branches cut from `upstream/main` HEAD, not from the pin.
- Never use a consolidated patch as a PR diff. Per-feature files do not
  stack; each PR applies only its own patch file.
- Never auto-write config or edit generated code (game-repo rule carries
  over: curate, don't generate).
- One PR at a time: open, send the link, ask the user when to continue.
  Same gate for TLDR updates (present the block, proceed only on approval).

## Task router

Load the reference for the task at hand; do not read them all at once.

| Task | Reference |
|---|---|
| Clone/fork/branch setup, apply, drift porting, build | `references/workflow.md` |
| Impact ordering, strip/keep rules, cross-repo bundles, hunk ownership | `references/scoping.md` |
| Per-PR tests, patterns, negative controls, no-test justification | `references/testing.md` |
| PR body (TLDR + P0–P3), docs convention, open/update flow | `references/pr-body.md` |
