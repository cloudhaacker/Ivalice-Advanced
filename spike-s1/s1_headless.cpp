// Spike S1 — raylib 6 PLATFORM_MEMORY + rlsw proof (plan §4.3).
//
// Drives the REAL RaylibBackend through open -> present -> readback -> close
// (and reopen) on raylib's memory platform, with no DISPLAY and no GPU, and
// asserts the properties Phase 5's headless tier will rely on:
//
//   Q1  the backend works unmodified on the Memory platform;
//   Q2  the rendered output is readable (LoadImageFromScreen, swGetColorBuffer)
//       and changes when the presented frame changes;
//   Q3  the staging readback (copy_presented_frame) round-trips exactly;
//   Q4  close/reopen works (tier-3 lifecycle coverage claim).
//
// TDD shape: every claim is an ok/FAIL assertion; exit code is non-zero on any
// failure. Run with DISPLAY and WAYLAND_DISPLAY unset — that is the point.
#include "raylib_backend.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#if defined(GBARECOMP_USE_RAYLIB)
#include "raylib.h"
// rlsw's color-buffer accessor (SWAPI is empty; extern symbol in the static
// lib under GRAPHICS_API_OPENGL_SOFTWARE). Declared here because raylib.h
// does not export it.
extern "C" void* swGetColorBuffer(int* width, int* height);
#endif

using gbarecomp::RaylibBackend;

namespace {

int failures = 0;

void check(bool ok, const char* what) {
    std::printf(ok ? "  ok    %s\n" : "  FAIL  %s\n", what);
    if (!ok) ++failures;
}

constexpr int kBaseW = 240;
constexpr int kBaseH = 160;

// Deterministic, non-uniform: uniform fills hide stride/orientation bugs.
std::vector<std::uint8_t> make_frame(std::uint8_t seed) {
    std::vector<std::uint8_t> px(
        static_cast<std::size_t>(kBaseW) * kBaseH * 3u);
    for (std::size_t i = 0; i < px.size(); ++i)
        px[i] = static_cast<std::uint8_t>((i * 31u + seed * 7u) & 0xFFu);
    return px;
}

bool any_nonzero(const void* data, std::size_t bytes) {
    const auto* p = static_cast<const std::uint8_t*>(data);
    for (std::size_t i = 0; i < bytes; ++i) {
        if (p[i] != 0) return true;
    }
    return false;
}

}  // namespace

int main() {
    std::printf("s1_headless: raylib platform=Memory (rlsw), no display needed\n");
    if (std::getenv("DISPLAY") || std::getenv("WAYLAND_DISPLAY")) {
        std::printf("note: DISPLAY is set; rerun with it unset for the proof\n");
    }

    RaylibBackend b;
    check(!b.is_open(), "backend starts closed");

    const bool opened = b.open(/*scale=*/2, kBaseW, kBaseH, "s1 headless",
                               /*screen=*/nullptr, /*linear_filter=*/false,
                               /*sharp_filter=*/false,
                               /*resize_driven_view=*/false,
                               /*freely_resizable_window=*/false);
    check(opened, "open() succeeded on PLATFORM_MEMORY");
    if (!opened) return 1;
    check(b.is_open(), "is_open() after open");

    int dw = 0, dh = 0;
    check(b.drawable_size(&dw, &dh) && dw > 0 && dh > 0,
          "drawable_size() reported positive size");
    std::printf("  drawable: %dx%d\n", dw, dh);

    // ---- present + staging readback (Q3) ----------------------------------
    const auto frame_a = make_frame(1);
    b.present(frame_a.data(), /*fresh=*/true);

    std::vector<std::uint8_t> got;
    int rw = 0, rh = 0;
    check(b.copy_presented_frame(got, rw, rh),
          "copy_presented_frame() served a frame");
    check(rw == kBaseW && rh == kBaseH, "staging readback is native geometry");
    check(got == frame_a, "staging bytes round-trip exactly");

    // ---- rendered readback (Q2) -------------------------------------------
    Image img = LoadImageFromScreen();
    check(img.width > 0 && img.height > 0,
          "LoadImageFromScreen() returned a rendered image");
    std::printf("  screen image: %dx%d (drawable %dx%d)\n", img.width,
                img.height, dw, dh);
    if (img.data && img.width > 0 && img.height > 0) {
        const std::size_t n =
            static_cast<std::size_t>(img.width) * img.height * 4u;
        check(any_nonzero(img.data, n), "rendered image is non-blank");
    } else {
        check(false, "rendered image is non-blank");
    }

    // A different frame must change the rendered output — this is what proves
    // the rendered path is live, not a frozen first buffer.
    const auto frame_b = make_frame(200);
    check(frame_a != frame_b, "the two test frames really differ");
    b.present(frame_b.data(), /*fresh=*/true);
    Image img2 = LoadImageFromScreen();
    bool differs = false;
    if (img.data && img2.data && img.width == img2.width &&
        img.height == img2.height && img.width > 0) {
        const std::size_t n =
            static_cast<std::size_t>(img.width) * img.height * 4u;
        const auto* p1 = static_cast<const std::uint8_t*>(img.data);
        const auto* p2 = static_cast<const std::uint8_t*>(img2.data);
        for (std::size_t i = 0; i < n && !differs; ++i) {
            differs = p1[i] != p2[i];
        }
    }
    check(differs, "second present changed the rendered readback");

    // ---- swGetColorBuffer (the rlsw accessor Phase 5 can use) -------------
    int sw = 0, sh = 0;
    void* buf = swGetColorBuffer(&sw, &sh);
    check(buf != nullptr && sw > 0 && sh > 0,
          "swGetColorBuffer() returned the framebuffer");
    std::printf("  swGetColorBuffer: %dx%d\n", sw, sh);
    if (buf && sw > 0 && sh > 0) {
        const std::size_t n = static_cast<std::size_t>(sw) * sh * 4u;
        check(any_nonzero(buf, n), "color buffer is non-blank");
    }

    // Orientation diagnostic (not an assertion): rlReadScreenPixels flips
    // assuming GL's bottom-left origin; record whether rlsw's color buffer
    // agrees or is flipped relative to the LoadImageFromScreen result. Both
    // are captured after the same (frame B) present.
    if (buf && img2.data && sw == img2.width && sh == img2.height && sw > 0 &&
        sh > 1) {
        const auto* fbc = static_cast<const std::uint8_t*>(buf);
        const auto* top = static_cast<const std::uint8_t*>(img2.data);
        const std::size_t row = static_cast<std::size_t>(sw) * 4u;
        const bool same_first_row = std::memcmp(fbc, top, row) == 0;
        const bool flipped_first_row =
            std::memcmp(fbc, top + row * (sh - 1), row) == 0;
        const auto* bottom = top + row * (sh - 1);
        std::printf("  orientation: first-row match=%d flipped-match=%d\n",
                    same_first_row ? 1 : 0, flipped_first_row ? 1 : 0);
        std::printf("  px probe: buf=%02x%02x%02x%02x img_top=%02x%02x%02x%02x "
                    "img_bottom=%02x%02x%02x%02x\n",
                    fbc[0], fbc[1], fbc[2], fbc[3], top[0], top[1], top[2],
                    top[3], bottom[0], bottom[1], bottom[2], bottom[3]);
    }

    if (img.data) UnloadImage(img);
    if (img2.data) UnloadImage(img2);

    // ---- lifecycle: close + reopen (Q4) -----------------------------------
    b.close();
    check(!b.is_open(), "close() leaves the backend closed");

    const bool reopened = b.open(2, kBaseW, kBaseH, "s1 headless 2", nullptr,
                                 false, false, false, false);
    check(reopened, "reopen() succeeded (close/reopen works headless)");
    if (reopened) {
        b.present(frame_a.data(), true);
        std::vector<std::uint8_t> got2;
        int rw2 = 0, rh2 = 0;
        check(b.copy_presented_frame(got2, rw2, rh2) && got2 == frame_a,
              "present after reopen round-trips");
        b.close();
    }

    std::printf("s1_headless: %s (%d failure%s)\n", failures ? "FAIL" : "PASS",
                failures, failures == 1 ? "" : "s");
    return failures ? 1 : 0;
}
