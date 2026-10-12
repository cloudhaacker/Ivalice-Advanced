// ffta_speed_boost.cpp — issue #11 speed-toggle touch pill (live side).
//
// Draws the "FF" pill (see ffta_speed_boost.h for geometry/edge logic),
// polls TouchHub for press-to-toggle edges, and owns the session latch.
//
// Threading: overlay draw and the engine's fast_forward_request poll both
// run on the guest thread, so the latch needs no lock. TouchHub::points()
// copies under its own mutex and is safe to call here.
//
// Touch routing note: pad/toggle touches never reach the hub (host_window
// consumes them first), so pad play cannot toggle the pill — but it also
// does not refresh the pill's hub-only idle timer. The pill therefore hides
// after 15 s of non-pad touches even mid-pad-play; any later touch reveals
// it and acts normally, exactly like the pad's own idle-hide contract. On
// Android the pill starts visible (the touch platform); elsewhere it appears
// on first touch, so desktop keyboard sessions never see it.

#include "ffta_speed_boost.h"

#include <algorithm>
#include <cstdint>
#include <vector>

#include "host_overlay.h"
#include "host_window.h"  // host_haptic_pulse
#include "touch_input.h"

namespace ffta {
namespace {

bool g_latched = false;
SpeedPillTaps g_taps;
bool g_have_touch = false;
std::uint32_t g_last_touch_ms = 0;
bool g_have_seen = false;
std::uint32_t g_last_seen_ms = 0;
#if defined(__ANDROID__)
bool g_seeded_visible = false;
#endif

}  // namespace

bool speed_boost_requested() { return g_latched; }

void speed_boost_overlay(gbarecomp::HostOverlay* overlay) {
    if (!overlay) return;
    using gbarecomp::OverlayAlign;
    using gbarecomp::OverlayColor;
    using gbarecomp::OverlaySpace;

    const std::uint32_t now = overlay->host_ms();
    if (g_have_seen && now - g_last_seen_ms > kSpeedPillStaleGapMs) {
        // Interrupted session (background/suspend/kill): never wake boosted.
        // The pacer is realigned by the engine's own resume path.
        g_latched = false;
        g_taps.reset();
    }
    g_have_seen = true;
    g_last_seen_ms = now;

#if defined(__ANDROID__)
    if (!g_seeded_visible) {
        // Touch platform: discoverable from boot, like the pad itself.
        g_seeded_visible = true;
        g_have_touch = true;
        g_last_touch_ms = now;
    }
#endif

    const int dw = overlay->drawable_width();
    const int dh = overlay->drawable_height();
    const float mm = overlay->drawable_px_per_mm();
    const auto insets = overlay->safe_insets();
    const SpeedPillRect pill = speed_pill_rect(dw, dh, insets.top, mm);

    const std::vector<gbarecomp::TouchPointSnapshot> points =
        gbarecomp::TouchHub::instance().points();
    if (!points.empty()) {
        g_have_touch = true;
        g_last_touch_ms = now;
    }

    // Press-to-toggle on new-pointer edges inside the pill, even on a
    // reveal-after-idle tap (same contract as the pad: revealing touches
    // are never swallowed).
    if (pill.w > 0.0f && pill.h > 0.0f && !points.empty()) {
        std::int32_t ids[16];
        float xs[16], ys[16];
        int n = 0;
        for (const auto& p : points) {
            if (n >= 16) break;
            ids[n] = p.pointer;
            xs[n] = p.drawable_x;
            ys[n] = p.drawable_y;
            ++n;
        }
        if (g_taps.update(pill, ids, xs, ys, n, mm)) {
            g_latched = !g_latched;
            gbarecomp::host_haptic_pulse(15, 0.5f);  // no-op sans vibrator
        }
    } else {
        // No fingers down: drop all tracked ids so the next contact
        // re-edges (equivalent to pruning against an empty set).
        g_taps.reset();
    }

    const bool visible =
        g_have_touch && now - g_last_touch_ms <= kSpeedPillIdleHideMs;
    if (!visible || pill.w <= 0.0f || pill.h <= 0.0f) return;

    const auto S = OverlaySpace::Drawable;
    const OverlayColor backing{12, 16, 28, 150};
    const OverlayColor outline{240, 244, 252, 210};
    const OverlayColor latched{255, 214, 74, 230};
    const OverlayColor label{255, 255, 255, 235};
    const float line = std::max(2.0f, 0.45f * mm);
    overlay->fill_rect(pill.x, pill.y, pill.w, pill.h, pill.h * 0.5f,
                       g_latched ? latched : backing, S);
    overlay->stroke_rect(pill.x, pill.y, pill.w, pill.h, pill.h * 0.5f, line,
                         outline, S);
    if (overlay->text_supported()) {
        float size = pill.h * 0.62f;
        const float cap = 3.4f * mm;
        if (size > cap) size = cap;
        overlay->text(pill.x + pill.w * 0.5f,
                      pill.y + (pill.h - size) * 0.5f, size, label, "FF",
                      OverlayAlign::Center, S);
    }
}

}  // namespace ffta
