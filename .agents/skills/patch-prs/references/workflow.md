# Workflow: isolated clone, apply, drift, build

All PR prep happens outside the game repo.

## Setup (once per batch)

```sh
mkdir -p /tmp/patch-prs/gbarecomp-upstream-prep
gh repo fork mstan/gbarecomp --clone=false          # james2doyle/gbarecomp
git clone https://github.com/james2doyle/gbarecomp.git \
  /tmp/patch-prs/gbarecomp-upstream-prep/gbarecomp
git -C /tmp/patch-prs/gbarecomp-upstream-prep/gbarecomp \
  remote add upstream https://github.com/mstan/gbarecomp.git
git -C /tmp/patch-prs/gbarecomp-upstream-prep/gbarecomp fetch upstream main
git -C /tmp/patch-prs/gbarecomp-upstream-prep/gbarecomp \
  submodule update --init --depth 1
# SSH for push (https clone hits auth prompts):
git -C /tmp/patch-prs/gbarecomp-upstream-prep/gbarecomp \
  remote set-url origin git@github.com:james2doyle/gbarecomp.git
```

Same shape for `mstan/arm-recomp-core` when a bundle needs it
(`--clone=false` fork, clone to `.../arm-recomp-core`, `upstream/master`).

## Per-PR branch

```sh
git -C <clone> checkout -B <branch> upstream/main
git -C <clone> submodule update --checkout external/arm-recomp-core
cp <game-repo>/tools/patches/<feature>.patch /tmp/patch-prs/.../<name>-orig.patch
git -C <clone> apply --check /tmp/patch-prs/.../<name>-orig.patch
```

- `apply --check` clean → `git apply`, done.
- Fails on drift (e.g. pin ~30 commits behind; `swi_enter` refactor,
  `emit_exit_diagnostics` lambda, `--state-dir` already merged): use
  `git apply --reject` to take the clean hunks, then **hand-port** the
  rejected hunk into the new context. Delete any `.rej` after porting.
- Filtering a consolidated/interleaved patch: split on `^diff --git` and
  keep only owned files/hunks (see `scoping.md`). Prefer
  `apply --include=<path>` for whole-file keeps; hand-edit for hunk-level
  keeps. Verify with `git diff --stat` — only owned files listed.

## Build (upstream targets only, in tmp clone)

```sh
cmake -S <clone> -B /tmp/patch-prs/.../build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/patch-prs/.../build --target <lib-or-test> --parallel 8
```

- Re-run cmake configure after adding a test target (new `add_executable`).
- `-DGBARECOMP_ENABLE_MODS=ON` needs a separate build dir
  (`build-mods`) for `mod_runtime_tests`.
- `RECOMP_LAUNCHER` regions never compile in upstream CI: force-check with
  `-DRECOMP_LAUNCHER -fsyntax-only` on the including TU.
- The oracle target needs `third_party/mgba` (off by default) — no build
  possible; say so in the PR.
- Pre-existing warnings (e.g. `g_ws_view_width`) are not yours; ignore
  unless your hunk introduced them.

## Commit / push / open

```sh
git -C <clone> add <owned files only> && git commit -m "<imperative summary>"
git -C <clone> push -u origin <branch>
gh pr create --repo mstan/gbarecomp --head james2doyle:<branch> --base main \
  --title "<title>" --body-file /tmp/patch-prs/.../body.md
```

- Amendments: `commit --amend --no-edit` then `push --force-with-lease`.
- Body edits: `gh pr edit <n> --repo mstan/gbarecomp --body-file <file>`.
- Never `git add -A` blindly — untracked test files are intended, but
  submodule bumps (`external/arm-recomp-core`) only when the PR owns them.
