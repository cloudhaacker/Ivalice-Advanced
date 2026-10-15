// HostWindow delegation contract (Phase 4a).
//
// HostWindow must prefer the V2 facade when the active backend implements it:
// with a V2-capable backend NOT ONE flat-generation method may be reached —
// the flat surface is only the SDL fallback until 4b deletes it. The
// flat-only case proves that fallback still lands, and proves this file's
// flat spy covers every HostWindow delegation (otherwise "zero flat calls"
// above would be vacuous: a missing spy override hides a missed delegation).
//
// Both cases drive the full public surface, so a delegation site left on the
// flat interface fails loudly here — even though it would be invisible in the
// raylib build at runtime (the flat forwarders do the same work).
//
// Same-signature methods exist on both generations (close/is_open/pump/
// wait_for_foreground/set_runtime_ui): C++ gives them ONE final overrider, so
// the two paths are literally indistinguishable there. Those forward to the
// V2 fake in the both-spy and the test asserts the recorded call; only
// flat-only methods (the other ~51) count as "flat reached".
//
// close() destroys the backend (HostWindow owns it), so anything about the
// post-close state is asserted through statics or captured before the call.
//
// A configuration with no window backend at all reports SKIP loudly (the
// framework standalone config cannot compile host_window.cpp — see CMake).

#include "host_window.h"
#include "support/fake_backend.h"

#include <cassert>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

using gbarecomp::HostWindow;
using gbarecomp::WindowBackend;
using gbarecomp::WindowBackendV2;

namespace {

// ── the flat half: count every reachable flat-generation-only call ───────
struct CountingFlat : WindowBackend {
    static int live;              // open instances (HostWindow owns them)
    static int close_calls_total; // survives destruction (post-close asserts)
    mutable int flat_calls = 0;   // const getters count too
    int last_volume = -1;

    CountingFlat() { ++live; }
    ~CountingFlat() override { --live; }

    // lifecycle: open has distinct signatures on the two generations, so the
    // flat overload counts; close/is_open collide with V2 (one final
    // overrider) — the flat-only spy counts them, the both-spy forwards.
    bool open(const gbarecomp::WindowBackendOpenParams&) override {
        ++flat_calls;
        return true;
    }
    bool open(int, int, int, const char*, const char*, bool, bool, bool,
              bool) override {
        ++flat_calls;
        return true;
    }
    void close() override {
        ++flat_calls;
        ++close_calls_total;
    }
    bool is_open() const override {
        ++flat_calls;
        return true;
    }
    gbarecomp::Events pump() override {
        ++flat_calls;
        return gbarecomp::Events{};
    }
    bool wait_for_foreground() override {
        ++flat_calls;
        return true;
    }

    void set_title(const char*) override { ++flat_calls; }
    bool assist_tools_enabled() const override { ++flat_calls; return true; }
    int fast_forward_multiplier() const override { ++flat_calls; return 4; }
    void load_input_config(const char*, bool, int) override { ++flat_calls; }
    void set_volume(int pct) override {
        ++flat_calls;
        last_volume = pct;
    }
    int window_scale() const override { ++flat_calls; return 1; }
    void set_linear_filter(bool) override { ++flat_calls; }
    bool linear_filter_enabled() const override { ++flat_calls; return false; }
    void set_resize_driven_view(bool) override { ++flat_calls; }
    void set_view_margins(std::uint32_t, std::uint32_t, std::uint32_t,
                          std::uint32_t) override { ++flat_calls; }
    void configure_touch(bool, std::uint32_t, int, bool, int) override {
        ++flat_calls;
    }
    void set_touch_config_dir(const char*) override { ++flat_calls; }
    void set_host_overlay(void (*)(gbarecomp::HostOverlay*)) override {
        ++flat_calls;
    }
    float px_per_mm_value() const override {
        ++flat_calls;
        return 96.0f / 25.4f;
    }
    void set_presentation_anchor_top(bool) override { ++flat_calls; }
    void set_fps_readout(bool) override { ++flat_calls; }
    void haptic_pulse(int, float) override { ++flat_calls; }
    bool gamepad_connected() const override { ++flat_calls; return false; }
    bool gamepad_supports_rumble() const override { ++flat_calls; return false; }
    void gamepad_rumble(float, float, std::uint32_t) override { ++flat_calls; }
    bool fps_readout_value() const override { ++flat_calls; return false; }
    void set_touch_pad_visible(bool) override { ++flat_calls; }
    bool touch_pad_visible_value() const override { ++flat_calls; return false; }
    void set_frame_interp(bool) override { ++flat_calls; }
    bool frame_interp() const override { ++flat_calls; return false; }
    void set_lcd_shader(bool) override { ++flat_calls; }
    bool lcd_shader_enabled() const override { ++flat_calls; return false; }
    void set_lcd_boost(float) override { ++flat_calls; }
    float lcd_boost_value() const override { ++flat_calls; return 1.0f; }
    void set_lcd_dither(float) override { ++flat_calls; }
    float lcd_dither_value() const override { ++flat_calls; return 1.0f; }
    void set_lcd_deband(float) override { ++flat_calls; }
    float lcd_deband_value() const override { ++flat_calls; return 0.0f; }
    void set_frame_blend(bool) override { ++flat_calls; }
    bool frame_blend_value() const override { ++flat_calls; return false; }
    void reset_frame_blend() override { ++flat_calls; }
    void interp_display_tick(const std::uint8_t*, std::uint64_t) override {
        ++flat_calls;
    }
    void set_audio_enabled(bool) override { ++flat_calls; }
    bool audio_enabled() const override { ++flat_calls; return false; }
    void adjust_scale(int) override { ++flat_calls; }
    int volume_percent() const override { ++flat_calls; return 100; }
    void set_fullscreen(int) override { ++flat_calls; }
    int fullscreen_mode() const override { ++flat_calls; return 0; }
    bool set_surface_size(int, int) override { ++flat_calls; return true; }
    bool drawable_size(int* w, int* h) const override {
        ++flat_calls;
        if (w) *w = 720;
        if (h) *h = 480;
        return true;
    }
    void pump_events(gbarecomp::Events&) override { ++flat_calls; }
    void present(const std::uint8_t*, bool) override { ++flat_calls; }
    bool copy_presented_frame(std::vector<std::uint8_t>&, int&, int&) const
        override {
        ++flat_calls;
        return false;
    }
    void push_audio_samples(const std::int16_t*, std::size_t) override {
        ++flat_calls;
    }
};
int CountingFlat::live = 0;
int CountingFlat::close_calls_total = 0;

// ── V2 + flat: the V2 half forwards to the composable fakes ──────────────
struct BothSpy : CountingFlat, WindowBackendV2 {
    static int open_attempts;   // survives destruction (open-failure asserts)
    static int v2_close_calls;  // survives destruction (close asserts)
    gbarecomp::testing::FakeBackend v2;

    // same-signature collisions: one final overrider serves both generations
    void close() override {
        ++v2_close_calls;
        v2.close();
    }
    bool is_open() const override { return v2.is_open(); }
    gbarecomp::Events pump() override { return v2.pump(); }
    bool wait_for_foreground() override { return v2.wait_for_foreground(); }
    void set_runtime_ui(::RecompRuntimeUi* ui) override {
        v2.set_runtime_ui(ui);
    }

    // the V2 facade
    gbarecomp::Result open(const gbarecomp::OpenParams& p) override {
        ++open_attempts;
        return v2.open(p);
    }
    gbarecomp::Caps caps() const override { return v2.caps(); }
    gbarecomp::Video& video() override { return v2.video(); }
    gbarecomp::Audio& audio() override { return v2.audio(); }
    gbarecomp::Input& input() override { return v2.input(); }
    gbarecomp::Fx& fx() override { return v2.fx(); }
    gbarecomp::Overlay& overlay() override { return v2.overlay(); }
    gbarecomp::Menu& menu() override { return v2.menu(); }
    bool suspend() override { return v2.suspend(); }
    bool resume() override { return v2.resume(); }
};
int BothSpy::open_attempts = 0;
int BothSpy::v2_close_calls = 0;

struct FlatOnlySpy : CountingFlat {};

BothSpy* g_both = nullptr;
BothSpy* g_fail = nullptr;
FlatOnlySpy* g_flat = nullptr;
WindowBackend* make_both() {
    g_both = new BothSpy;
    return g_both;
}
WindowBackend* make_fail() {
    g_fail = new BothSpy;
    g_fail->v2.open_fails = true;
    return g_fail;
}
WindowBackend* make_flat() {
    g_flat = new FlatOnlySpy;
    return g_flat;
}

}  // namespace

int main() {
    if (!HostWindow::is_available()) {
        std::printf("host_window_delegation tests: SKIP (no window backend "
                    "in this configuration; the delegation contract needs "
                    "the SDL or raylib backend region)\n");
        return 0;
    }

    // ══ case A: V2-capable backend — the flat surface must stay cold ═════
    {
        g_both = nullptr;
        HostWindow w(&make_both);
        assert(g_both == nullptr);  // the factory runs at open, not before
        assert(w.backend_v2() == nullptr);

        assert(w.open(3, 240, 160, "delegation", nullptr, false, false, false,
                      false));
        BothSpy& spy = *g_both;
        assert(spy.v2.open_calls == 1);
        assert(spy.v2.last_open.scale == 3);
        assert(spy.v2.last_open.base_w == 240 && spy.v2.last_open.base_h == 160);
        assert(spy.v2.last_open.title &&
               std::string(spy.v2.last_open.title) == "delegation");
        assert(spy.flat_calls == 0);  // ← the contract, first checkpoint
        assert(w.backend_v2() == &spy);
        assert(w.is_open());

        // window / video
        w.set_title("delegation-2");
        assert(spy.v2.recording_video.title == "delegation-2");
        w.adjust_scale(1);
        assert(spy.v2.recording_video.scale() == 4);
        w.set_linear_filter(true);
        assert(spy.v2.recording_video.linear_filter());
        assert(w.linear_filter());
        w.set_fullscreen(2);
        assert(spy.v2.recording_video.fullscreen() == 2);
        assert(w.fullscreen() == 2);
        w.set_resize_driven_view(true);
        assert(spy.v2.recording_video.resize_driven);
        w.set_view_margins(1, 2, 3, 4);
        assert(spy.v2.recording_video.margin_l == 1 &&
               spy.v2.recording_video.margin_b == 4);
        w.set_presentation_anchor_top(true);
        assert(spy.v2.recording_video.anchor_top);
        assert(w.px_per_mm() == 96.0f / 25.4f);
        assert(spy.flat_calls == 0);

        // frame surface (sized to the 320x240 base set just above)
        assert(w.set_surface_size(320, 240));
        assert(spy.v2.recording_video.base_w == 320);
        int dw = 0, dh = 0;
        assert(w.drawable_size(&dw, &dh) && dw == 720 && dh == 480);
        std::vector<std::uint8_t> frame(320u * 240u * 3u, 7);
        w.present(frame.data(), true);
        assert(spy.v2.recording_video.present_calls == 1);
        w.interp_display_tick(frame.data(), 123456);
        assert(spy.v2.recording_video.interp_calls == 1);
        assert(spy.v2.recording_video.last_deadline_ns == 123456);
        std::vector<std::uint8_t> back;
        int bw = 0, bh = 0;
        assert(w.copy_presented_frame(back, bw, bh));
        assert(bw == 320 && bh == 240 && back.size() == 320u * 240u * 3u);
        assert(spy.flat_calls == 0);

        // audio
        w.set_volume(42);
        assert(spy.v2.tapped_audio.volume() == 42);
        assert(w.volume() == 42);
        w.set_audio_enabled(false);
        assert(!spy.v2.tapped_audio.enabled());
        assert(!w.audio_enabled());
        std::int16_t samples[4] = {1, 2, 3, 4};
        w.push_audio_samples(samples, 4);
        assert(spy.v2.tapped_audio.push_calls == 1 &&
               spy.v2.tapped_audio.pushed == 4);
        assert(spy.flat_calls == 0);

        // fx
        w.set_frame_interp(true);
        assert(spy.v2.fake_fx.stored.frame_interp);
        assert(spy.v2.fake_fx.reset_calls == 1);  // flat-parity reset
        assert(w.frame_interp());
        w.set_frame_blend(true);
        assert(spy.v2.fake_fx.stored.frame_blend == 1.0f);
        assert(spy.v2.fake_fx.reset_calls == 2);
        assert(w.frame_blend());
        w.reset_frame_blend();
        assert(spy.v2.fake_fx.reset_calls == 3);
        w.set_lcd_shader(true);
        assert(spy.v2.fake_fx.stored.lcd);
        assert(w.lcd_shader());
        w.set_lcd_boost(1.25f);
        assert(spy.v2.fake_fx.stored.lcd_boost == 1.25f);
        assert(w.lcd_boost() == 1.25f);
        w.set_lcd_dither(0.5f);
        assert(spy.v2.fake_fx.stored.lcd_dither == 0.5f);
        assert(w.lcd_dither() == 0.5f);
        w.set_lcd_deband(2.0f);
        assert(spy.v2.fake_fx.stored.lcd_deband == 2.0f);
        assert(w.lcd_deband() == 2.0f);
        assert(spy.flat_calls == 0);

        // input + config (the two config entries: Input and Fx)
        w.load_input_config("/tmp/delegation", true, 4);
        assert(spy.v2.scripted_input.load_config_calls == 1);
        assert(spy.v2.scripted_input.last_config_dir == "/tmp/delegation");
        assert(spy.v2.fake_fx.load_config_calls == 1);
        assert(spy.v2.fake_fx.config_dir == "/tmp/delegation");
        assert(w.assist_tools_enabled());
        assert(w.fast_forward_multiplier() == 4);
        spy.v2.caps_override.rumble = true;
        assert(w.gamepad_supports_rumble());  // caps are the source
        w.gamepad_rumble(0.5f, 0.25f, 120);
        assert(spy.v2.scripted_input.rumble_calls == 1 &&
               spy.v2.scripted_input.last_duration_ms == 120);
        w.haptic_pulse(10, 0.5f);
        assert(spy.v2.scripted_input.haptic_calls == 1);
        assert(spy.flat_calls == 0);

        // overlay / touch
        static void (*const kOverlay)(gbarecomp::HostOverlay*) = nullptr;
        w.set_host_overlay(kOverlay);
        assert(spy.v2.fake_overlay.host_overlay == kOverlay);
        w.configure_touch(true, 0xFFu, 1, true, 30);
        assert(spy.v2.fake_overlay.touch.policy);
        assert(spy.v2.fake_overlay.touch.claims == 0xFFu);
        assert(spy.v2.fake_overlay.touch.pad_idle_hide_seconds == 30);
        w.set_touch_config_dir("/tmp/delegation");
        assert(spy.v2.fake_overlay.config_dir == "/tmp/delegation");
        w.set_touch_pad_visible(true);
        assert(spy.v2.fake_overlay.pad_visible);
        assert(w.touch_pad_visible());
        assert(spy.flat_calls == 0);

        // title-bar readout + lifecycle
        w.set_fps_readout(true);
        assert(spy.v2.recording_video.fps_readout());
        assert(w.fps_readout());
        assert(w.wait_for_foreground());
        (void)w.pump();
        assert(spy.v2.pump_calls == 1);
        w.service_events();  // V2: raylib services its own queue — a no-op
#if defined(GBARECOMP_RUNTIME_UI)
        w.set_runtime_ui(nullptr);
        assert(spy.v2.runtime_ui == nullptr);
#endif
        assert(spy.flat_calls == 0);

        // close: capture what post-close asserts need (close deletes the spy)
        const int flat_before_close = spy.flat_calls;
        const int v2_before_close = spy.v2.close_calls;
        w.close();
        assert(v2_before_close == 0);
        assert(BothSpy::v2_close_calls == 1);
        assert(flat_before_close == 0);
        assert(CountingFlat::close_calls_total == 0);  // flat close never ran
        assert(!w.is_open());
        assert(w.backend_v2() == nullptr);
        assert(CountingFlat::live == 0);  // close() owns and destroys
    }

    // ══ case B: flat-only backend — every delegation lands flat ══════════
    // Also the spy-coverage proof: the count must equal the number of
    // delegating calls this sequence makes, or case A's zero is vacuous.
    {
        g_flat = nullptr;
        HostWindow w(&make_flat);
        int expected = 0;
        auto bump = [&] { ++expected; };

        assert(w.open(3, 240, 160, "flat", nullptr, false, false, false,
                      false));
        bump();
        assert(w.backend_v2() == nullptr);
        assert(g_flat != nullptr);
        FlatOnlySpy& spy = *g_flat;
        assert(spy.flat_calls == expected);
        assert(w.is_open());  // host state, no delegation

        w.set_title("flat-2");                       bump();
        w.adjust_scale(1);                           bump();
        w.set_linear_filter(true);                   bump();
        (void)w.linear_filter();                     bump();
        w.set_fullscreen(1);                         bump();
        (void)w.fullscreen();                        bump();
        w.set_resize_driven_view(true);              bump();
        w.set_view_margins(1, 2, 3, 4);              bump();
        w.set_presentation_anchor_top(true);         bump();
        (void)w.px_per_mm();                         bump();
        (void)w.set_surface_size(320, 240);          bump();
        int dw = 0, dh = 0;
        (void)w.drawable_size(&dw, &dh);             bump();
        std::uint8_t frame[3] = {1, 2, 3};
        w.present(frame, true);                      bump();
        w.interp_display_tick(frame, 1);             bump();
        std::vector<std::uint8_t> back;
        int bw = 0, bh = 0;
        (void)w.copy_presented_frame(back, bw, bh);  bump();
        w.set_volume(42);                            bump();
        (void)w.volume();                            bump();
        w.set_audio_enabled(false);                  bump();
        (void)w.audio_enabled();                     bump();
        std::int16_t samples[4] = {1, 2, 3, 4};
        w.push_audio_samples(samples, 4);            bump();
        w.set_frame_interp(true);                    bump();
        (void)w.frame_interp();                      bump();
        w.set_frame_blend(true);                     bump();
        (void)w.frame_blend();                       bump();
        w.reset_frame_blend();                       bump();
        w.set_lcd_shader(true);                      bump();
        (void)w.lcd_shader();                        bump();
        w.set_lcd_boost(1.5f);                       bump();
        (void)w.lcd_boost();                         bump();
        w.set_lcd_dither(0.5f);                      bump();
        (void)w.lcd_dither();                        bump();
        w.set_lcd_deband(1.0f);                      bump();
        (void)w.lcd_deband();                        bump();
        w.load_input_config("/tmp/x", true, 4);      bump();
        (void)w.assist_tools_enabled();              bump();
        (void)w.fast_forward_multiplier();           bump();
        (void)w.gamepad_supports_rumble();           bump();
        w.gamepad_rumble(1.0f, 1.0f, 100);           bump();
        w.haptic_pulse(10, 0.5f);                    bump();
        w.set_host_overlay(nullptr);                 bump();
        w.configure_touch(false, 0u, 0, false, 30);  bump();
        w.set_touch_config_dir("/tmp/x");            bump();
        w.set_touch_pad_visible(true);               bump();
        (void)w.touch_pad_visible();                 bump();
        w.set_fps_readout(true);                     bump();
        (void)w.fps_readout();                       bump();
        (void)w.wait_for_foreground();               bump();
        (void)w.pump();                              bump();
        w.service_events();                          // no delegation
        assert(spy.flat_calls == expected);          // ← coverage proof
        assert(spy.last_volume == 42);

        const int before_close = CountingFlat::close_calls_total;
        w.close();
        assert(CountingFlat::close_calls_total == before_close + 1);
        assert(CountingFlat::live == 0);
    }

    // ══ case C: V2 open failure is reported and owns nothing ═════════════
    {
        const int attempts_before = BothSpy::open_attempts;
        const int closes_before = CountingFlat::close_calls_total;
        HostWindow w(&make_fail);
        assert(!w.open(3, 240, 160, "t", nullptr, false, false, false, false));
        assert(BothSpy::open_attempts == attempts_before + 1);
        assert(!w.is_open());
        assert(w.backend_v2() == nullptr);
        assert(CountingFlat::live == 0);  // the failed backend was destroyed
        assert(CountingFlat::close_calls_total == closes_before);  // no close
        g_fail = nullptr;  // dangling by contract; never read
    }

    std::printf("host_window_delegation tests: PASS\n");
    return 0;
}
