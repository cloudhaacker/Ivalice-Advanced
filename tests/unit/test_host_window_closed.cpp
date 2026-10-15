// HostWindow closed-state contract.
//
// The seam routing change rewrote 41 delegation sites from
// `static_cast<Backend*>(impl_)` to `static_cast<WindowBackend*>(impl_)` and typed
// `impl_` as `WindowBackend*`. That is a lot of identical guard clauses, and a
// typo in any of them is invisible: the method still compiles, still links, and
// still "works" — it just returns the wrong fallback on a closed window.
//
// This test needs no backend at all. Every HostWindow method must be safe to call
// on a never-opened window and must return its documented fallback, never crash
// and never dereference a null impl_.

#include "host_backend_factory.h"
#include "host_window.h"

#include <cassert>
#include <cstdio>
#include <vector>

using gbarecomp::HostWindow;

int main() {
    HostWindow w;  // never opened: open_ == false, impl_ == nullptr

    assert(!w.is_available() || w.is_available());  // must not crash either way

    // ---- getters: documented fallbacks on a closed window ------------------
    assert(w.fullscreen() == 0);
    assert(w.volume() == 100);
    assert(w.window_scale() == 1);
    assert(!w.linear_filter());
    assert(!w.frame_interp());
    assert(!w.frame_blend());
    assert(!w.lcd_shader());
    assert(w.lcd_boost() == 1.0f);
    assert(w.lcd_dither() == 1.0f);
    assert(w.lcd_deband() == 0.0f);
    assert(!w.audio_enabled());
    assert(!w.resize_driven_view());
    assert(!w.touch_pad_visible());
    assert(!w.fps_readout());
    assert(w.assist_tools_enabled());          // enhancement defaults ON
    assert(w.fast_forward_multiplier() == 4);
    assert(w.px_per_mm() == 96.0f / 25.4f);

    int w_out = 0, h_out = 0;
    assert(!w.drawable_size(&w_out, &h_out));
    assert(w.set_surface_size(240, 160) == false);

    // gyro_delta_x / mouse_gyro_active ride along on Events
    assert(w.pump().keyinput == 0x03FF);       // nothing pressed
    assert(!w.pump().quit == false);           // closed => quit requested

    std::vector<std::uint8_t> frame;
    int fw = 0, fh = 0;
    assert(!w.copy_presented_frame(frame, fw, fh));

    // ---- setters / mutators: must be no-ops, never crashes ----------------
    w.set_title("ignored");
    w.set_volume(0);
    w.adjust_scale(5);
    w.set_linear_filter(true);
    w.set_frame_interp(true);
    w.set_frame_blend(true);
    w.reset_frame_blend();
    w.set_lcd_shader(true);
    w.set_lcd_boost(2.0f);
    w.set_lcd_dither(0.0f);
    w.set_lcd_deband(6.0f);
    w.set_audio_enabled(false);
    w.set_resize_driven_view(true);
    w.set_view_margins(1, 2, 3, 4);
    w.set_presentation_anchor_top(true);
    w.set_fps_readout(true);
    w.set_host_overlay(nullptr);
    w.set_touch_pad_visible(true);
    w.configure_touch(true, 0xFFu, 1, true, 30);
    w.set_touch_config_dir("/tmp/does-not-exist");
    w.load_input_config("/tmp/does-not-exist", true, 4);
    w.present(nullptr, true);
    w.push_audio_samples(nullptr, 0);
    w.service_events();
    w.wait_for_foreground();                   // returns false, must not hang

    // ---- lifecycle: close() on a never-opened window is a safe no-op ------
    w.close();
    w.close();                                 // idempotent

    // Fallbacks must be unchanged after all that: nothing leaked into state.
    assert(w.volume() == 100);
    assert(w.window_scale() == 1);
    assert(!w.linear_filter());
    assert(!w.frame_blend());
    assert(!w.lcd_shader());
    assert(w.lcd_boost() == 1.0f);
    assert(w.lcd_dither() == 1.0f);
    assert(w.lcd_deband() == 0.0f);
    assert(!w.touch_pad_visible());
    assert(!w.fps_readout());

    // ---- backend factory -------------------------------------------------
    // The factory is the single place that decides which backend a build uses.
    // Constructing and destroying through the base pointer exercises the virtual
    // destructor, which is how HostWindow::close() releases the backend.
    {
        gbarecomp::WindowBackend* b = gbarecomp::host_make_backend();
        assert(b != nullptr);
        assert(!b->is_open());            // freshly constructed, never opened
        assert(!b->gamepad_connected());  // nothing to claim before open()
        delete b;                         // must go through ~WindowBackend()

        // The predicate must agree with what this build actually compiles.
#if defined(GBARECOMP_USE_RAYLIB)
        assert(gbarecomp::host_using_raylib_backend());
#else
        assert(!gbarecomp::host_using_raylib_backend());
#endif
    }

    // Two backends must be independent objects, not a shared singleton: a
    // leaked instance would silently share window/audio state.
    {
        gbarecomp::WindowBackend* a = gbarecomp::host_make_backend();
        gbarecomp::WindowBackend* c = gbarecomp::host_make_backend();
        assert(a && c && a != c);
        delete a;
        delete c;
    }

    std::printf("host_window_closed tests: PASS\n");
    return 0;
}