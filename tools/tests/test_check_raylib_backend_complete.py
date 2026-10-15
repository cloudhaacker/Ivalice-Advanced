#!/usr/bin/env python3
"""Self-tests for tools/check_raylib_backend_complete.py.

The completeness guard is load-bearing: if it silently passes, the seam
silently drifts from its contract. So it gets tested like any other code --
including the cases that once broke it (the function-pointer argument, the
overload pair) and the Phase 4b checks (pure interfaces, single generation,
per-interface scanning).

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
struct HostOverlay;
class WindowBackend {
public:
    virtual ~WindowBackend() = default;
%s
};
class Video {
public:
    virtual ~Video() = default;
%s
};
class Audio {
public:
    virtual ~Audio() = default;
};
class Input {
public:
    virtual ~Input() = default;
};
class Fx {
public:
    virtual ~Fx() = default;
};
class Overlay {
public:
    virtual ~Overlay() = default;
};
class Menu {
public:
    virtual ~Menu() = default;
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
}  // namespace gbarecomp
"""

BACKEND_CPP = """#include "raylib_backend.h"
namespace gbarecomp {
class RaylibBackend::VideoImpl final : public Video {
public:
%s
};
}  // namespace gbarecomp
"""

CLEAN_HOST = "// host_window.cpp fixture: no SDL markers\n"
CLEAN_FACTORY = "// factory fixture: no SDL markers\n"


def build(tmp: Path, facade_methods: str, backend_h_methods: str,
          backend_cpp_methods: str = "", video_methods: str = "",
          host_window: str = CLEAN_HOST,
          factory: str = CLEAN_FACTORY) -> dict[str, Path]:
    paths = {
        "iface": tmp / "window_backend.h",
        "backend_h": tmp / "raylib_backend.h",
        "backend_cpp": tmp / "raylib_backend.cpp",
        "host_window": tmp / "host_window.cpp",
        "factory": tmp / "host_backend_factory.cpp",
    }
    paths["iface"].write_text(IFACE_HEADER % (facade_methods, video_methods))
    paths["backend_h"].write_text(BACKEND_HEADER % backend_h_methods)
    paths["backend_cpp"].write_text(BACKEND_CPP % backend_cpp_methods)
    paths["host_window"].write_text(host_window)
    paths["factory"].write_text(factory)
    return paths


def run(tmp: Path, facade_methods: str, backend_h_methods: str,
        backend_cpp_methods: str = "", video_methods: str = "",
        host_window: str = CLEAN_HOST, factory: str = CLEAN_FACTORY) -> int:
    paths = build(tmp, facade_methods, backend_h_methods, backend_cpp_methods,
                  video_methods, host_window, factory)
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return checker.main([
            "--iface", str(paths["iface"]),
            "--backend-h", str(paths["backend_h"]),
            "--backend-cpp", str(paths["backend_cpp"]),
            "--host-window", str(paths["host_window"]),
            "--factory", str(paths["factory"]),
        ])


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # 1. Baseline: pure interface, everything overridden -> clean.
        check("complete backend passes",
              run(tmp,
                  "    virtual void set_volume(int pct) = 0;\n"
                  "    virtual int volume_percent() const = 0;\n",
                  "    void set_volume(int pct) override;\n"
                  "    int volume_percent() const override;\n"),
              0)

        # 2. A missing override must be reported, not silently accepted.
        check("missing override fails",
              run(tmp,
                  "    virtual void set_volume(int pct) = 0;\n"
                  "    virtual void set_fps_readout(bool on) = 0;\n",
                  "    void set_volume(int pct) override;\n"),
              1)

        # 3. REGRESSION: a function-pointer parameter contains its own parens.
        #    A naive [^)]* regex drops this and reports a false failure.
        check("function-pointer arg parses (regression)",
              run(tmp,
                  "    virtual void set_host_overlay(void (*overlay)(HostOverlay*)) = 0;\n",
                  "    void set_host_overlay(void (*overlay)(HostOverlay*)) override;\n"),
              0)

        # 4. REGRESSION: overloaded interface methods are distinct entries.
        check("overloads tracked separately",
              run(tmp,
                  "    virtual bool open(int scale) = 0;\n"
                  "    virtual bool open(long scale) = 0;\n",
                  "    bool open(int scale) override;\n"
                  "    bool open(long scale) override;\n"),
              0)

        # 5. REGRESSION: one open() override must not satisfy the other.
        check("overload mismatch fails",
              run(tmp,
                  "    virtual bool open(int scale) = 0;\n"
                  "    virtual bool open(long scale) = 0;\n",
                  "    bool open(int scale) override;\n"),
              1)

        # 6. const-ness drift must be caught.
        check("const-ness mismatch fails",
              run(tmp,
                  "    virtual int value() const = 0;\n",
                  "    int value() override;\n"),
              1)

        # 7. Whitespace normalization must not create false mismatches.
        check("spacing tolerated",
              run(tmp,
                  "    virtual bool drawable_size(int* w, int* h) const = 0;\n",
                  "    bool drawable_size(int *w, int *h) const override;\n"),
              0)

        # 8. A non-virtual member in the interface must not be required.
        check("non-virtual ignored",
              run(tmp,
                  "    int helper_field = 0;\n"
                  "    virtual void set_volume(int pct) = 0;\n",
                  "    void set_volume(int pct) override;\n"),
              0)

        # 9. REGRESSION (Phase 4b): an interface method with a defaulted body is
        #    the silent-inheritance bug class (audio_enabled_state()). It must
        #    fail even when the backend overrides it.
        check("impure interface method fails",
              run(tmp,
                  "    virtual bool audio_enabled() const { return false; }\n",
                  "    bool audio_enabled() const override;\n"),
              1)

        # 10. Phase 4b: the flat generation must be gone.
        check("flat marker fails",
              run(tmp,
                  "    virtual bool open(const WindowBackendOpenParams& p) = 0;\n",
                  "    bool open(const WindowBackendOpenParams& p) override;\n"),
              1)

        # 11. Phase 4b: the SDL factory hook must be gone.
        check("sdl factory marker fails",
              run(tmp,
                  "    virtual void close() = 0;\n",
                  "    void close() override;\n",
                  host_window="WindowBackend* host_make_sdl_backend() { return nullptr; }\n"),
              1)

        # 12. Phase 4b: the SDL compile define must be gone from the runtime.
        check("sdl define marker fails",
              run(tmp,
                  "    virtual void close() = 0;\n",
                  "    void close() override;\n",
                  host_window="#if defined(GBARECOMP_HAVE_SDL2)\n#endif\n"),
              1)

        # 13. Phase 4b: an inline SDL `Backend` struct must be gone.
        check("sdl backend struct fails",
              run(tmp,
                  "    virtual void close() = 0;\n",
                  "    void close() override;\n",
                  host_window="struct Backend : public WindowBackend {};\n"),
              1)

        # 14. Phase 4b: concern interfaces are scanned too (not just the facade).
        check("concern interface missing override fails",
              run(tmp,
                  "    virtual void close() = 0;\n",
                  "    void close() override;\n",
                  video_methods="    virtual void present(const std::uint8_t* p) = 0;\n"),
              1)

        # 15. Phase 4b: a concern implemented in the nested impl (the .cpp) passes.
        check("concern implemented in cpp passes",
              run(tmp,
                  "    virtual void close() = 0;\n",
                  "    void close() override;\n",
                  backend_cpp_methods="    void present(const std::uint8_t* p) override;\n",
                  video_methods="    virtual void present(const std::uint8_t* p) = 0;\n"),
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
