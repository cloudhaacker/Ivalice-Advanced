# spike-s1 — raylib 6 headless enablement proof (Phase 0, plan §4.3)

Result: **PASS (2026-10-14)** — 16/16 assertions with `DISPLAY` and
`WAYLAND_DISPLAY` unset. This directory is the Phase 0 proof harness; Phase 5
builds the headless tier into the port tree (`gbarecompx/`), reusing
this recipe.

## Route

raylib 6's own CMake supports the headless platform directly: configure with
`-DPLATFORM=Memory`. `cmake/LibraryConfigurations.cmake` maps it to
`PLATFORM_CPP=PLATFORM_MEMORY` + `GRAPHICS=GRAPHICS_API_OPENGL_SOFTWARE`
(exported PUBLIC by `cmake/CompileDefinitions.cmake`); `rcore_memory.c` +
`rlsw.h` provide the memory framebuffer and software renderer. No display, no
GPU, no injected defines, no second build tree.

## Build + run

```sh
# reuse the pinned source the app build already fetched
cmake -S spike-s1 -B spike-s1/build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DRAYLIB_SRC=build-raylib-only/_deps/raylib-src
cmake --build spike-s1/build --parallel 8
env -u DISPLAY -u WAYLAND_DISPLAY ./spike-s1/build/s1_headless   # exit 0
```

`glfw_stubs.cpp` supplies truthful "no gamepad" answers for the backend's
desktop GLFW calls — the one symbol set the Memory platform cannot satisfy
(Phase 2's `RaylibApi` seam replaces this stub).

## Findings (full list in the plan §4.3)

- `LoadImageFromScreen()` → 480x320 RGBA top-down frames that change with the
  presented frame (use this in tests). `swGetColorBuffer()` → **BGRA**.
- Shader loads fail softly under rlsw ("dither shader failed to compile");
  no crash. Audio can still initialize if a sound server exists.
- `copy_presented_frame()` round-trips staging bytes exactly; close/reopen
  works headless.
