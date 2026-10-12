// ffta_speed_boost.h — issue #11 speed-toggle touch pill.
//
// FFTA-owned fast-forward control: a small "FF" pill drawn top-center by the
// game-owned host overlay. Tap toggles a session-only latch that the engine
// polls through RunOptions::fast_forward_request (see
// tools/patches/speed-toggle-ff-seam.patch) and ORs with the physical
// hold paths (Tab / Assist key / pad trigger) and the runtime-menu latch.
//
// Pure presentation + input-edge logic lives here as inline code so the host
// unit suite links it without SDL (same pattern as ffta_ram_dispatch.h /
// ffta_lzss_guard.h). The live TouchHub polling + draw call is
// ffta_speed_boost.cpp; the latch itself is a bool set only on the guest
// thread (overlay draw and the seam poll both run there).

#pragma once

#include <cstddef>
#include <cstdint>

namespace gbarecomp {
class HostOverlay;
}  // namespace gbarecomp

namespace ffta {

// Idle-hide mirrors the pad's configured 15 s (src/main.cpp
// touch_pad_idle_hide_seconds): the pill shows only within this window after
// touch activity, so a touch-only UI never clutters a keyboard session.
inline constexpr std::uint32_t kSpeedPillIdleHideMs = 15000;
// A gap in overlay presents longer than this means the session was
// interrupted (background / suspend / kill) — the latch clears rather than
// waking up boosted.
inline constexpr std::uint32_t kSpeedPillStaleGapMs = 5000;
// Hit-test padding around the pill, same 2 mm the pad uses.
inline constexpr float kSpeedPillHitPadMm = 2.0f;

struct SpeedPillRect {
    float x = 0.0f, y = 0.0f, w = 0.0f, h = 0.0f;
};

// Pill placement in drawable pixels: top-center, below the top safe inset.
// Height fits the same glyph size the pad pills use; width fits "FF" with
// breathing room. Kept clear of the pad's top-corner L/R shoulders by
// centering (shoulders live at the drawable corners).
inline SpeedPillRect speed_pill_rect(int drawable_w, int drawable_h,
                                     int inset_top, float px_per_mm) {
    SpeedPillRect r;
    if (drawable_w <= 0 || drawable_h <= 0 || px_per_mm <= 0.0f) return r;
    r.h = 5.5f * px_per_mm;
    r.w = 15.0f * px_per_mm;
    if (r.w > static_cast<float>(drawable_w)) r.w = static_cast<float>(drawable_w);
    if (r.h > static_cast<float>(drawable_h)) r.h = static_cast<float>(drawable_h);
    r.x = (static_cast<float>(drawable_w) - r.w) * 0.5f;
    r.y = static_cast<float>(inset_top) + 2.5f * px_per_mm;
    const float max_y = static_cast<float>(drawable_h) - r.h;
    if (r.y > max_y) r.y = max_y > 0.0f ? max_y : 0.0f;
    return r;
}

inline bool speed_pill_hit(const SpeedPillRect& r, float px, float py,
                           float px_per_mm) {
    const float pad = kSpeedPillHitPadMm * px_per_mm;
    return px >= r.x - pad && px <= r.x + r.w + pad &&
           py >= r.y - pad && py <= r.y + r.h + pad;
}

// Press-to-toggle edge tracker: reports true once per call when a pointer id
// appears that was not present on the previous call AND lands in the pill.
// Sliding onto the pill never toggles (only the Down edge counts); a finger
// that lifts and retaps is a new edge. Fixed capacity, no allocation.
class SpeedPillTaps {
public:
    // Returns true if any new pointer in this frame hits the pill.
    bool update(const SpeedPillRect& r, const std::int32_t* ids,
                const float* xs, const float* ys, int n, float px_per_mm) {
        bool toggled = false;
        for (int i = 0; i < n; ++i) {
            if (!known(ids[i])) {
                if (add(ids[i]) && speed_pill_hit(r, xs[i], ys[i], px_per_mm))
                    toggled = true;
            }
        }
        // Prune lifted pointers so a later reuse of the id re-edges.
        for (int i = 0; i < count_;) {
            bool still = false;
            for (int j = 0; j < n; ++j) {
                if (ids_[i] == ids[j]) {
                    still = true;
                    break;
                }
            }
            if (!still) {
                ids_[i] = ids_[--count_];
            } else {
                ++i;
            }
        }
        return toggled;
    }

    void reset() { count_ = 0; }
    int tracked() const { return count_; }

private:
    static constexpr int kMax = 16;
    bool known(std::int32_t id) const {
        for (int i = 0; i < count_; ++i)
            if (ids_[i] == id) return true;
        return false;
    }
    bool add(std::int32_t id) {
        if (count_ >= kMax) return false;
        ids_[count_++] = id;
        return true;
    }
    std::int32_t ids_[kMax] = {};
    int count_ = 0;
};

// Live hooks (ffta_speed_boost.cpp): draw + poll the hub, and the seam
// getter installed as RunOptions::fast_forward_request.
void speed_boost_overlay(gbarecomp::HostOverlay* overlay);
bool speed_boost_requested();

}  // namespace ffta
