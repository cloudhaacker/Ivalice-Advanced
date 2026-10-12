// Host unit tests for the issue-#14 left-stick-as-d-pad mapping
// (gbarecomp input_synth.h stick_to_dpad). Registry-free companion to
// test_ram_dispatch.cpp: run_stick_dpad_tests() is invoked from that
// harness's main, so the ffta_unit_tests binary keeps a single PASS/FAIL
// line for tools/check.py.
//
// Guards the gameplay contract: SDL axes are -32768..32767 with up/left
// negative; inside the deadzone nothing registers (drift safety), beyond it
// exactly the crossed direction registers, and diagonals set both bits.
// No SDL needed — the helper is pure integer math.
#include "input_synth.h"

#include <cstdint>
#include <cstdio>

// The helper lives in the stick-to-dpad.patch work (applied on the pinned
// gbarecomp submodule). A pristine checkout — CI — compiles the pinned
// input_synth.h, which does not declare it; compile this whole test away
// there instead of breaking the unit build (same policy as the pacer and
// host-stack-guard probes in CMakeLists.txt).
#ifdef STICK_DPAD_API

namespace {

int stick_failures = 0;

#define STICK_CHECK(cond)                                                   \
    do {                                                                    \
        if (!(cond)) {                                                      \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);     \
            ++stick_failures;                                               \
        }                                                                   \
    } while (0)

}  // namespace

int run_stick_dpad_tests() {
    using gbarecomp::kGbaKeyDown;
    using gbarecomp::kGbaKeyLeft;
    using gbarecomp::kGbaKeyRight;
    using gbarecomp::kGbaKeyUp;
    using gbarecomp::stick_to_dpad;

    constexpr int kDz = 8192;  // the host_window default (25% deflection)

    // ── at rest and inside the deadzone: no direction ─────────────────
    STICK_CHECK(stick_to_dpad(0, 0, kDz) == 0);
    STICK_CHECK(stick_to_dpad(kDz, kDz, kDz) == 0);          // boundary
    STICK_CHECK(stick_to_dpad(-kDz, -kDz, kDz) == 0);        // boundary
    STICK_CHECK(stick_to_dpad(kDz - 1, -(kDz - 1), kDz) == 0);
    STICK_CHECK(stick_to_dpad(4000, -3000, kDz) == 0);       // drift

    // ── cardinal directions: exactly the crossed bit ──────────────────
    STICK_CHECK(stick_to_dpad(-kDz - 1, 0, kDz) == kGbaKeyLeft);
    STICK_CHECK(stick_to_dpad(kDz + 1, 0, kDz) == kGbaKeyRight);
    STICK_CHECK(stick_to_dpad(0, -kDz - 1, kDz) == kGbaKeyUp);
    STICK_CHECK(stick_to_dpad(0, kDz + 1, kDz) == kGbaKeyDown);

    // SDL axis extremes stay a single direction each.
    STICK_CHECK(stick_to_dpad(-32768, 0, kDz) == kGbaKeyLeft);
    STICK_CHECK(stick_to_dpad(32767, 0, kDz) == kGbaKeyRight);
    STICK_CHECK(stick_to_dpad(0, -32768, kDz) == kGbaKeyUp);
    STICK_CHECK(stick_to_dpad(0, 32767, kDz) == kGbaKeyDown);

    // ── diagonals: both bits, like holding two d-pad contacts ─────────
    STICK_CHECK(stick_to_dpad(-20000, -20000, kDz) ==
                (kGbaKeyLeft | kGbaKeyUp));
    STICK_CHECK(stick_to_dpad(20000, -20000, kDz) ==
                (kGbaKeyRight | kGbaKeyUp));
    STICK_CHECK(stick_to_dpad(-20000, 20000, kDz) ==
                (kGbaKeyLeft | kGbaKeyDown));
    STICK_CHECK(stick_to_dpad(20000, 20000, kDz) ==
                (kGbaKeyRight | kGbaKeyDown));

    // One axis in, one axis inside the deadzone: single bit.
    STICK_CHECK(stick_to_dpad(-20000, -4000, kDz) == kGbaKeyLeft);

    // ── custom deadzone: 0 still ignores exactly-centered sticks ──────
    STICK_CHECK(stick_to_dpad(0, 0, 0) == 0);
    STICK_CHECK(stick_to_dpad(1, 0, 0) == kGbaKeyRight);
    STICK_CHECK(stick_to_dpad(0, -1, 0) == kGbaKeyUp);
    STICK_CHECK(stick_to_dpad(15000, 0, 16000) == 0);        // gbaref DZ
    STICK_CHECK(stick_to_dpad(17000, 0, 16000) == kGbaKeyRight);

    // Large custom deadzones beyond the axis range can never fire.
    STICK_CHECK(stick_to_dpad(32767, -32768, 40000) == 0);

    return stick_failures;
}

#else  // !STICK_DPAD_API

int run_stick_dpad_tests() {
    std::printf("stick-to-dpad: mapping API unavailable (pristine "
                "submodule); skipped\n");
    return 0;
}

#endif  // STICK_DPAD_API
