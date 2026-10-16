// Host unit tests for the FramePacer banked wait (host_platform.{h,cpp}).
// Registry-free companion to test_ram_dispatch.cpp: run_frame_pacer_tests()
// is invoked from that harness's main, so the ffta_unit_tests binary keeps a
// single PASS/FAIL line for tools/check.py.
//
// Guards the issue-#8 pacer fix: wait_for_next_frame(frames) must throttle
// the banked count, not a single period. A present covering k>1 guest
// frames (after stale-frame present skips) that waited one period let the
// banked frames escape throttling (+5% guest wall-clock in battle, with an
// audio-bridge flood as the audible symptom).
//
// No ROM/BIOS needed. Timing margins are wide (lower bounds at ~75% of the
// nominal wait, upper bounds 100x+) so loaded CI machines don't flake.
#include "host_platform.h"

#include <chrono>
#include <cstdint>
#include <cstdio>

// The banked-wait API lives in the framework submodule (the gbarecompx
// fork — frame-pacer banked wait as committed code). A checkout whose
// framework declares wait_for_next_frame() with no parameters compiles
// this whole test away there instead of breaking the
// unit build. The patch-applied tree builds and runs it as before.
#if defined(PACER_BANKED_API)
#define PACER_BANKED_TESTING 1
#endif

namespace {

int pacer_failures = 0;

#define PACER_CHECK(cond)                                                   \
    do {                                                                    \
        if (!(cond)) {                                                      \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);     \
            ++pacer_failures;                                               \
        }                                                                   \
    } while (0)

#if PACER_BANKED_TESTING
double wait_ms(gbarecomp::FramePacer& p, uint64_t frames = 1) {
    const auto t0 = std::chrono::steady_clock::now();
    p.wait_for_next_frame(frames);
    const auto t1 = std::chrono::steady_clock::now();
    return std::chrono::duration<double, std::milli>(t1 - t0).count();
}
#endif

}  // namespace

int run_frame_pacer_tests() {
#if !PACER_BANKED_TESTING
    std::printf("frame pacer: banked-wait API unavailable (pristine "
                "submodule); skipped\n");
    return 0;
#else
    // 2 ms period keeps the suite fast (whole test < 100 ms).
    {
        gbarecomp::FramePacer p(500.0);
        const double e = wait_ms(p, 1);
        PACER_CHECK(e >= 1.0 && e < 500.0);
    }
    {
        // THE regression: a 4-frame present must throttle ~4 periods
        // (~8 ms), not one (~2 ms). Single-period behavior here was the
        // +5% fast guest clock.
        gbarecomp::FramePacer p(500.0);
        const double e = wait_ms(p, 4);
        PACER_CHECK(e >= 6.0 && e < 1000.0);
    }
    {
        // Default argument paces exactly one frame.
        gbarecomp::FramePacer p(500.0);
        const double e = wait_ms(p);
        PACER_CHECK(e >= 1.0 && e < 500.0);
    }
    {
        // Uncapped (fast-forward): immediate regardless of count.
        gbarecomp::FramePacer p(500.0);
        p.set_uncapped(true);
        const double e = wait_ms(p, 4);
        PACER_CHECK(e < 500.0);
    }
    {
        // Absurd banks clamp (16 periods max = 32 ms here) instead of
        // sleeping for seconds; the behind-resync still bounds real
        // stalls, so only an upper bound is asserted.
        gbarecomp::FramePacer p(500.0);
        const double e = wait_ms(p, 1000000u);
        PACER_CHECK(e < 1000.0);
    }

    if (pacer_failures) {
        std::printf("frame pacer: %d failure(s)\n", pacer_failures);
    }
    return pacer_failures;
#endif
}
