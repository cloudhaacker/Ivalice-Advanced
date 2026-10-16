// HostWindow delegation contract (Phase 4a, single-generation since 4b).
//
// Every HostWindow method must reach the right seam concern through the
// facade: this drives the full public surface against a fake backend and
// asserts each recorded effect (title, scale, volume, Fx settings, touch
// config, pump, lifecycle). A delegation site wired to the wrong concern —
// or dropped entirely — fails loudly here.
//
// close() destroys the backend (HostWindow owns it), so anything about the
// post-close state is asserted through statics captured before the call; the
// V2 open-failure case proves error reporting + ownership on the failure path.
//
// A configuration with no window backend at all (raylib OFF) reports SKIP
// loudly: the delegation contract needs the product backend region.

#include "host_window.h"
#include "support/fake_backend.h"

#include <cassert>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

using gbarecomp::HostWindow;
using gbarecomp::WindowBackend;

namespace {

// ── the spy: the facade over the composable fakes, with statics that survive
//    destruction (post-close / open-failure asserts read those) ─────────────
struct SpyBackend : WindowBackend {
    static int live;              // open instances (HostWindow owns them)
    static int open_attempts;     // every open() call, even the failing ones
    static int close_calls_total; // every close() call

    gbarecomp::testing::FakeBackend inner;

    SpyBackend() { ++live; }
    ~SpyBackend() override { --live; }

    gbarecomp::Result open(const gbarecomp::OpenParams& p) override {
        ++open_attempts;
        return inner.open(p);
    }
    void close() override {
        ++close_calls_total;
        inner.close();
    }
    bool is_open() const override { return inner.is_open(); }
    gbarecomp::Caps caps() const override { return inner.caps(); }
    gbarecomp::Video& video() override { return inner.video(); }
    gbarecomp::Audio& audio() override { return inner.audio(); }
    gbarecomp::Input& input() override { return inner.input(); }
    gbarecomp::Fx& fx() override { return inner.fx(); }
    gbarecomp::Overlay& overlay() override { return inner.overlay(); }
    gbarecomp::Menu& menu() override { return inner.menu(); }
    gbarecomp::Events pump() override { return inner.pump(); }
    bool suspend() override { return inner.suspend(); }
    bool resume() override { return inner.resume(); }
    bool wait_for_foreground() override { return inner.wait_for_foreground(); }
};
int SpyBackend::live = 0;
int SpyBackend::open_attempts = 0;
int SpyBackend::close_calls_total = 0;

SpyBackend* g_spy = nullptr;
SpyBackend* g_fail = nullptr;
WindowBackend* make_spy() {
    g_spy = new SpyBackend;
    return g_spy;
}
WindowBackend* make_fail() {
    g_fail = new SpyBackend;
    g_fail->inner.open_fails = true;
    return g_fail;
}

}  // namespace

int main() {
    if (!HostWindow::is_available()) {
        std::printf("host_window_delegation tests: SKIP (no window backend "
                    "in this configuration; the delegation contract needs "
                    "the raylib product region)\n");
        return 0;
    }

    // ══ case A: every HostWindow method reaches its concern ══════════════
    {
        g_spy = nullptr;
        HostWindow w(&make_spy);
        assert(g_spy == nullptr);  // the factory runs at open, not before
        assert(w.backend_v2() == nullptr);

        assert(w.open(3, 240, 160, "delegation", nullptr, false, false, false,
                      false));
        SpyBackend& spy = *g_spy;
        assert(spy.inner.open_calls == 1);
        assert(spy.inner.last_open.scale == 3);
        assert(spy.inner.last_open.base_w == 240 && spy.inner.last_open.base_h == 160);
        assert(spy.inner.last_open.title &&
               std::string(spy.inner.last_open.title) == "delegation");
        assert(w.backend_v2() == &spy);
        assert(w.is_open());

        // window / video
        w.set_title("delegation-2");
        assert(spy.inner.recording_video.title == "delegation-2");
        w.adjust_scale(1);
        assert(spy.inner.recording_video.scale() == 4);
        w.set_linear_filter(true);
        assert(spy.inner.recording_video.linear_filter());
        assert(w.linear_filter());
        w.set_fullscreen(2);
        assert(spy.inner.recording_video.fullscreen() == 2);
        assert(w.fullscreen() == 2);
        w.set_resize_driven_view(true);
        assert(spy.inner.recording_video.resize_driven);
        w.set_view_margins(1, 2, 3, 4);
        assert(spy.inner.recording_video.margin_l == 1 &&
               spy.inner.recording_video.margin_b == 4);
        w.set_presentation_anchor_top(true);
        assert(spy.inner.recording_video.anchor_top);
        assert(w.px_per_mm() == 96.0f / 25.4f);

        // frame surface (sized to the 320x240 base set just above)
        assert(w.set_surface_size(320, 240));
        assert(spy.inner.recording_video.base_w == 320);
        int dw = 0, dh = 0;
        assert(w.drawable_size(&dw, &dh) && dw == 720 && dh == 480);
        std::vector<std::uint8_t> frame(320u * 240u * 3u, 7);
        w.present(frame.data(), true);
        assert(spy.inner.recording_video.present_calls == 1);
        w.interp_display_tick(frame.data(), 123456);
        assert(spy.inner.recording_video.interp_calls == 0);  // no runtime-ui (Phase 5)
        assert(spy.inner.recording_video.last_deadline_ns == 0); // no runtime-ui (Phase 5)
        std::vector<std::uint8_t> back;
        int bw = 0, bh = 0;
        assert(w.copy_presented_frame(back, bw, bh));
        assert(bw == 320 && bh == 240 && back.size() == 320u * 240u * 3u);

        // audio
        w.set_volume(42);
        assert(spy.inner.tapped_audio.volume() == 42);
        assert(w.volume() == 42);
        w.set_audio_enabled(false);
        assert(!spy.inner.tapped_audio.enabled());
        assert(!w.audio_enabled());
        std::int16_t samples[4] = {1, 2, 3, 4};
        w.push_audio_samples(samples, 4);
        assert(spy.inner.tapped_audio.push_calls == 1 &&
               spy.inner.tapped_audio.pushed == 4);

        // fx
        w.set_frame_interp(true);
        assert(spy.inner.fake_fx.stored.frame_interp);
        assert(spy.inner.fake_fx.reset_calls == 1);  // unconditional reset
        assert(w.frame_interp());
        w.set_frame_blend(true);
        assert(spy.inner.fake_fx.stored.frame_blend == 1.0f);
        assert(spy.inner.fake_fx.reset_calls == 2);
        assert(w.frame_blend());
        w.reset_frame_blend();
        assert(spy.inner.fake_fx.reset_calls == 3);
        w.set_lcd_shader(true);
        assert(spy.inner.fake_fx.stored.lcd);
        assert(w.lcd_shader());
        w.set_lcd_boost(1.25f);
        assert(spy.inner.fake_fx.stored.lcd_boost == 1.25f);
        assert(w.lcd_boost() == 1.25f);
        w.set_lcd_dither(0.5f);
        assert(spy.inner.fake_fx.stored.lcd_dither == 0.5f);
        assert(w.lcd_dither() == 0.5f);
        w.set_lcd_deband(2.0f);
        assert(spy.inner.fake_fx.stored.lcd_deband == 2.0f);
        assert(w.lcd_deband() == 2.0f);

        // input + config (the two config entries: Input and Fx)
        w.load_input_config("/tmp/delegation", true, 4);
        assert(spy.inner.scripted_input.load_config_calls == 1);
        assert(spy.inner.scripted_input.last_config_dir == "/tmp/delegation");
        assert(spy.inner.fake_fx.load_config_calls == 1);
        assert(spy.inner.fake_fx.config_dir == "/tmp/delegation");
        assert(w.assist_tools_enabled());
        assert(w.fast_forward_multiplier() == 4);
        spy.inner.caps_override.rumble = true;
        assert(w.gamepad_supports_rumble());  // caps are the source
        w.gamepad_rumble(0.5f, 0.25f, 120);
        assert(spy.inner.scripted_input.rumble_calls == 1 &&
               spy.inner.scripted_input.last_duration_ms == 120);
        w.haptic_pulse(10, 0.5f);
        assert(spy.inner.scripted_input.haptic_calls == 1);

        // overlay / touch
        static void (*const kOverlay)(gbarecomp::HostOverlay*) = nullptr;
        w.set_host_overlay(kOverlay);
        assert(spy.inner.fake_overlay.host_overlay == kOverlay);
        w.configure_touch(true, 0xFFu, 1, true, 30);
        assert(spy.inner.fake_overlay.touch.policy);
        assert(spy.inner.fake_overlay.touch.claims == 0xFFu);
        assert(spy.inner.fake_overlay.touch.pad_idle_hide_seconds == 30);
        w.set_touch_config_dir("/tmp/delegation");
        assert(spy.inner.fake_overlay.config_dir == "/tmp/delegation");
        w.set_touch_pad_visible(true);
        assert(spy.inner.fake_overlay.pad_visible);
        assert(w.touch_pad_visible());

        // title-bar readout + lifecycle
        w.set_fps_readout(true);
        assert(spy.inner.recording_video.fps_readout());
        assert(w.fps_readout());
        assert(w.wait_for_foreground());
        (void)w.pump();
        assert(spy.inner.pump_calls == 1);
        w.service_events();  // raylib services its own queue — a no-op

        // close: capture what post-close asserts need (close deletes the spy)
        const int closes_before = SpyBackend::close_calls_total;
        w.close();
        assert(SpyBackend::close_calls_total == closes_before + 1);
        assert(!w.is_open());
        assert(w.backend_v2() == nullptr);
        assert(SpyBackend::live == 0);  // close() owns and destroys
    }

    // ══ case B: open failure is reported and owns nothing ════════════════
    {
        const int attempts_before = SpyBackend::open_attempts;
        const int closes_before = SpyBackend::close_calls_total;
        HostWindow w(&make_fail);
        assert(!w.open(3, 240, 160, "t", nullptr, false, false, false, false));
        assert(SpyBackend::open_attempts == attempts_before + 1);
        assert(!w.is_open());
        assert(w.backend_v2() == nullptr);
        assert(SpyBackend::live == 0);  // the failed backend was destroyed
        assert(SpyBackend::close_calls_total == closes_before);  // no close
        g_fail = nullptr;  // dangling by contract; never read
    }

    std::printf("host_window_delegation tests: PASS\n");
    return 0;
}
