#!/usr/bin/env python3
"""Self-tests for tools/check_raylib_backend_complete.py.

The completeness guard is load-bearing: if it silently passes, the raylib backend
silently drifts from the interface. So it gets tested like any other code --
including the cases that once broke it.

Run: python3 tools/tests/test_check_raylib_backend_complete.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import check_raylib_backend_complete as checker  # noqa: E402

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    if got != want:
        FAILURES.append(f"{label}: got {got!r}, want {want!r}")


IFACE_HEADER = """#pragma once
namespace gbarecomp {
class WindowBackend {
public:
    virtual ~WindowBackend() = default;
%s
};
}  // namespace gbarecomp
"""

BACKEND_HEADER = """#pragma once
#include "window_backend.h"
namespace gbarecomp {
class RaylibBackend final : public WindowBackend {
public:
%s
};
}
"""

# The SDL Backend lives inline inside an anonymous namespace in host_window.cpp,
# so the self-test feeds the checker a synthetic equivalent.
SDL_SOURCE = """#pragma once
namespace gbarecomp {
namespace {
struct Backend : public WindowBackend {
%s
};
}  // namespace
}
"""


def build(tmp: Path, iface_methods: str, backend_methods: str,
          sdl_methods: str | None = None) -> tuple[Path, Path, Path]:
    i = tmp / "iface.h"
    b = tmp / "backend.h"
    s = tmp / "sdl.cpp"
    i.write_text(IFACE_HEADER % iface_methods)
    b.write_text(BACKEND_HEADER % backend_methods)
    # Default: the SDL fixture mirrors the backend fixture, so a raylib result
    # is never masked by an unrelated SDL failure.
    s.write_text(SDL_SOURCE % (sdl_methods if sdl_methods is not None
                               else backend_methods))
    return i, b, s


def run(tmp: Path, iface_methods: str, backend_methods: str,
        sdl_methods: str | None = None) -> int:
    i, b, s = build(tmp, iface_methods, backend_methods, sdl_methods)
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return checker.main(["--iface", str(i), "--backend", str(b),
                             "--sdl", str(s)])


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # 1. Baseline: everything overridden -> clean.
        check("complete backend passes",
              run(tmp,
                  "    virtual void set_volume(int pct) { (void)pct; }\n"
                  "    virtual int volume_percent() const { return 100; }\n",
                  "    void set_volume(int pct) override;\n"
                  "    int volume_percent() const override;\n"),
              0)

        # 2. A missing override must be reported, not silently accepted.
        check("missing override fails",
              run(tmp,
                  "    virtual void set_volume(int pct) { (void)pct; }\n"
                  "    virtual void set_fps_readout(bool on) { (void)on; }\n",
                  "    void set_volume(int pct) override;\n"),
              1)

        # 3. REGRESSION: a function-pointer parameter contains its own parens.
        #    A naive [^)]* regex drops this and reports a false failure.
        check("function-pointer arg parses (regression)",
              run(tmp,
                  "    virtual void set_host_overlay(void (*overlay)(HostOverlay*)) {"
                  " (void)overlay; }\n",
                  "    void set_host_overlay(void (*overlay)(HostOverlay*)) override;\n"),
              0)

        # 4. REGRESSION: overloaded interface methods are distinct entries.
        check("overloads tracked separately",
              run(tmp,
                  "    virtual bool open(const WindowBackendOpenParams& p) {"
                  " (void)p; return false; }\n"
                  "    virtual bool open(int scale) { (void)scale; return false; }\n",
                  "    bool open(const WindowBackendOpenParams& p) override;\n"
                  "    bool open(int scale) override;\n"),
              0)

        # 5. REGRESSION: one open() override must not satisfy the other.
        check("overload mismatch fails",
              run(tmp,
                  "    virtual bool open(const WindowBackendOpenParams& p) {"
                  " (void)p; return false; }\n"
                  "    virtual bool open(int scale) { (void)scale; return false; }\n",
                  "    bool open(const WindowBackendOpenParams& p) override;\n"),
              1)

        # 6. const-ness drift must be caught (a const base virtual cannot be
        #    overridden by a non-const one, so this is a compile error anyway --
        #    but the checker should agree).
        check("const-ness mismatch fails",
              run(tmp,
                  "    virtual int value() const { return 0; }\n",
                  "    int value() override;\n"),
              1)

        # 7. Whitespace normalization must not create false mismatches.
        check("spacing tolerated",
              run(tmp,
                  "    virtual void drawable_size(int* w, int* h) const {"
                  " (void)w; (void)h; return false; }\n",
                  "    void drawable_size(int *w, int *h) const override;\n"),
              0)

        # 8. A non-virtual member in the interface must not be required.
        check("non-virtual ignored",
              run(tmp,
                  "    int helper_field = 0;\n"
                  "    virtual void set_volume(int pct) { (void)pct; }\n",
                  "    void set_volume(int pct) override;\n"),
              0)

        # 9. SDL Backend: a missing override there is exactly the bug that let
        #    audio_enabled_state() silently return the base default `false`.
        check("sdl backend missing override fails",
              run(tmp,
                  "    virtual bool audio_enabled() const { return false; }\n",
                  "    bool audio_enabled() const override;\n",
                  sdl_methods=""),          # SDL Backend defines nothing
              1)

        # 10. SDL Backend passes when it implements everything.
        check("sdl backend complete passes",
              run(tmp,
                  "    virtual bool audio_enabled() const { return false; }\n",
                  "    bool audio_enabled() const override;\n"),   # mirrors
              0)

    if FAILURES:
        print("check_raylib_backend_complete SELF-TESTS FAILED:")
        for f in FAILURES:
            print(f"  {f}")
        return 1
    print("check_raylib_backend_complete self-tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())