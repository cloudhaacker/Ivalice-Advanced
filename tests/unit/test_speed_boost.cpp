// Host unit tests for the issue-#11 speed pill's pure logic
// (src/ffta_speed_boost.h): placement rect and press-to-toggle edges.
//
// No ROM/BIOS/SDL needed: geometry + tap tracker only. The live TouchHub
// polling, draw calls and latch live in src/ffta_speed_boost.cpp and are
// covered by review + device validation (the hub needs a window).
#include "../../src/ffta_speed_boost.h"

#include <cstdint>
#include <cstdio>

namespace {

int boost_failures = 0;

#define BOOST_CHECK(cond)                                                   \
    do {                                                                    \
        if (!(cond)) {                                                      \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);     \
            ++boost_failures;                                               \
        }                                                                   \
    } while (0)

}  // namespace

int run_speed_boost_tests() {
    using ffta::SpeedPillRect;
    using ffta::SpeedPillTaps;
    using ffta::speed_pill_hit;
    using ffta::speed_pill_rect;

    // ── placement: top-center, below the top inset ────────────────
    {
        // Phone-ish drawable: 2400x1080 landscape, 6 px/mm, 80 px top inset.
        const SpeedPillRect r = speed_pill_rect(2400, 1080, 80, 6.0f);
        BOOST_CHECK(r.w == 15.0f * 6.0f);
        BOOST_CHECK(r.h == 5.5f * 6.0f);
        BOOST_CHECK(r.x == (2400.0f - r.w) * 0.5f);  // centered
        BOOST_CHECK(r.y == 80.0f + 2.5f * 6.0f);     // below the inset
        // Clear of top-corner shoulders (18 mm wide at each corner).
        BOOST_CHECK(r.x > 18.0f * 6.0f);
        BOOST_CHECK(r.x + r.w < 2400.0f - 18.0f * 6.0f);
    }
    // Degenerate inputs never produce a drawable pill.
    {
        const SpeedPillRect r = speed_pill_rect(0, 0, 0, 0.0f);
        BOOST_CHECK(r.w == 0.0f && r.h == 0.0f);
    }
    // Tiny drawables clamp instead of overflowing.
    {
        const SpeedPillRect r = speed_pill_rect(40, 20, 0, 6.0f);
        BOOST_CHECK(r.w == 40.0f && r.h == 20.0f);
        BOOST_CHECK(r.x == 0.0f && r.y == 0.0f);
    }

    // ── hit test: inside + 2 mm slop, outside beyond it ───────────
    {
        const SpeedPillRect r = speed_pill_rect(2400, 1080, 80, 6.0f);
        BOOST_CHECK(speed_pill_hit(r, r.x + r.w * 0.5f, r.y + r.h * 0.5f, 6.0f));
        BOOST_CHECK(speed_pill_hit(r, r.x - 2.0f * 6.0f + 1.0f, r.y, 6.0f));
        BOOST_CHECK(!speed_pill_hit(r, r.x - 2.0f * 6.0f - 1.0f, r.y, 6.0f));
        BOOST_CHECK(!speed_pill_hit(r, 0.0f, 0.0f, 6.0f));
    }

    // ── edges: only the Down edge inside the pill toggles ─────────
    {
        const SpeedPillRect r = speed_pill_rect(2400, 1080, 80, 6.0f);
        const float cx = r.x + r.w * 0.5f, cy = r.y + r.h * 0.5f;
        SpeedPillTaps t;
        const std::int32_t id0 = 7;
        // New pointer inside -> toggle.
        BOOST_CHECK(t.update(r, &id0, &cx, &cy, 1, 6.0f));
        BOOST_CHECK(t.tracked() == 1);
        // Same pointer held (move) -> no re-toggle.
        const float moved = cx + 1.0f;
        BOOST_CHECK(!t.update(r, &id0, &moved, &cy, 1, 6.0f));
        // Second finger down outside the pill -> no toggle, but tracked.
        const std::int32_t ids[2] = {id0, 9};
        const float xs[2] = {moved, 10.0f};
        const float ys[2] = {cy, 10.0f};
        BOOST_CHECK(!t.update(r, ids, xs, ys, 2, 6.0f));
        BOOST_CHECK(t.tracked() == 2);
        // Both lift -> set drains; retap inside re-edges and toggles.
        BOOST_CHECK(!t.update(r, nullptr, nullptr, nullptr, 0, 6.0f));
        BOOST_CHECK(t.tracked() == 0);
        BOOST_CHECK(t.update(r, &id0, &cx, &cy, 1, 6.0f));
        // Tracker capacity is bounded: over-fill never toggles spuriously.
        SpeedPillTaps full;
        std::int32_t many[17];
        float px[17], py[17];
        for (int i = 0; i < 17; ++i) {
            many[i] = 100 + i;
            px[i] = 10.0f;
            py[i] = 10.0f;
        }
        BOOST_CHECK(!full.update(r, many, px, py, 17, 6.0f));
        BOOST_CHECK(full.tracked() == 16);
    }
    return boost_failures;
}
