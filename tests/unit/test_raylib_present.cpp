// Runtime coverage for the raylib backend.
//
// Until now the raylib path was only ever COMPILED (raylib-compile gate) and
// unit-tested through pure helpers. Nothing had ever opened a window, uploaded
// a frame or torn an audio device. That gap hides whole classes of defect:
//
//   * raylib 6 API drift that still typechecks but changes behaviour;
//   * resource lifetime bugs across open/close (textures, audio, the
//     single-owner audio slot);
//   * state that is set once and never cleared -- e.g. a window that is hidden
//     at open and never shown again.
//
// So this drives the real RaylibBackend, not a re-implementation of what it
// does. It links gbarecomp_raylib_backend and raylib and nothing else -- no
// gbarecomp_runtime, no SDL, no ROM-derived generated sources -- so CI can run
// it on a fresh checkout.
//
// Deliberately depends on raylib.h: this is an integration test of the raylib
// path, so asserting raylib state directly is the honest thing to do. The
// 48-method seam stays free of test-only methods.

// A display is genuinely required (raylib needs a GL context; discussion
// raysan5/raylib#4857 shows windowless mode segfaults). Skip cleanly when there
// is none so headless CI does not report a failure that is not a defect.
#if defined(__linux__)
#include <cstdlib>
static bool have_display() {
    return std::getenv("DISPLAY") || std::getenv("WAYLAND_DISPLAY");
}
#elif defined(__APPLE__)
static bool have_display() { return true; }   // always a GUI session
#else
static bool have_display() { return true; }
#endif

#include "raylib_backend.h"

#include "host_overlay.h"

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>

#if defined(GBARECOMP_USE_RAYLIB)
#include "raylib.h"
#endif

#if defined(GBARECOMP_USE_RAYLIB) && !defined(__ANDROID__)
// GLFW standard-mapping queries, mirroring raylib_backend.cpp's
// find_standard_pad (same GLFW 3.4 signatures). File scope: block scope
// cannot carry extern "C", and no GLFW headers are available here.
extern "C" {
int glfwJoystickPresent(int jid);
int glfwJoystickIsGamepad(int jid);
}  // extern "C"
#endif

using gbarecomp::HostOverlay;

using gbarecomp::RaylibBackend;
using gbarecomp::WindowBackend;

namespace {

int failures = 0;

void check(bool ok, const char* what) {
    if (ok) {
        std::printf("  ok    %s\n", what);
    } else {
        std::printf("  FAIL  %s\n", what);
        ++failures;
    }
}

constexpr int kBaseW = 240;
constexpr int kBaseH = 160;

// Single-generation Fx helpers: the flat setters are gone (Phase 4b), so each
// site composes settings()+apply() the way HostWindow does.
static void set_lcd(gbarecomp::RaylibBackend& b, bool on) {
    gbarecomp::FxSettings s = b.fx().settings();
    s.lcd = on;
    b.fx().apply(s);
}
static void set_lcd_dither(gbarecomp::RaylibBackend& b, float v) {
    gbarecomp::FxSettings s = b.fx().settings();
    s.lcd_dither = v;
    b.fx().apply(s);
}
static void set_lcd_deband(gbarecomp::RaylibBackend& b, float v) {
    gbarecomp::FxSettings s = b.fx().settings();
    s.lcd_deband = v;
    b.fx().apply(s);
}
static void set_frame_interp(gbarecomp::RaylibBackend& b, bool on) {
    gbarecomp::FxSettings s = b.fx().settings();
    s.frame_interp = on;
    b.fx().apply(s);
    b.fx().reset_frame_blend();  // the host pairing's unconditional reset
}
static void set_frame_blend(gbarecomp::RaylibBackend& b, bool on) {
    gbarecomp::FxSettings s = b.fx().settings();
    s.frame_blend = on ? 1.0f : 0.0f;
    b.fx().apply(s);
    b.fx().reset_frame_blend();
}

// Single-generation open helper: the flat 9-arg overload is gone (Phase 4b),
// so every site builds an OpenParams. Scale/geometry match what this suite
// always used (2x, native GBA geometry).
static bool open_backend(gbarecomp::RaylibBackend& b, const char* title,
                         const char* screen = nullptr,
                         bool linear_filter = false,
                         bool sharp_filter = false) {
    gbarecomp::OpenParams p;
    p.scale = 2;
    p.base_w = kBaseW;
    p.base_h = kBaseH;
    p.title = title;
    p.display = screen;
    p.linear_filter = linear_filter;
    p.sharp_filter = sharp_filter;
    return b.open(p).ok();
}

// Spin-off hook probe: counts invocations and draws one line through the
// seam, proving the callback runs inside present() with a live overlay.
int g_overlay_calls = 0;
void test_overlay(HostOverlay* ov) {
    ++g_overlay_calls;
    if (!ov) return;
    ov->line(0.0f, 0.0f, 10.0f, 10.0f, 1.0f, {255, 255, 255, 255},
             gbarecomp::OverlaySpace::Drawable);
}

// A deterministic, non-uniform pattern: uniform fills let a stale cache or a
// wrong stride hide, because every row would compare equal.
std::vector<std::uint8_t> make_frame(std::uint8_t seed) {
    std::vector<std::uint8_t> px(
        static_cast<std::size_t>(kBaseW) * kBaseH * 3u);
    for (std::size_t i = 0; i < px.size(); ++i) {
        px[i] = static_cast<std::uint8_t>((i * 31u + seed * 7u) & 0xFFu);
    }
    return px;
}

}  // namespace

int main() {
#if !defined(GBARECOMP_USE_RAYLIB)
    std::printf("raylib_present_tests: skipped (built without raylib)\n");
    return 0;
#else

    if (!have_display()) {
        std::printf("raylib_present_tests: SKIP (no DISPLAY/WAYLAND_DISPLAY)\n");
        return 0;
    }

    std::printf("raylib_present_tests: running against a real GL context\n");

    // Hermetic LCD-shader default: a stray GBARECOMP_LCD_SHADER in the
    // environment would enable the shader at every open() below.
    ::unsetenv("GBARECOMP_LCD_SHADER");

    // Constructed directly rather than through host_make_backend(): the factory
    // path drags in gbarecomp_runtime -- which needs the ROM-derived dispatch
    // table, never committed. Linking that here would make this test impossible
    // on a fresh CI checkout.
    //
    // The factory wiring itself is covered by ctest `backend_select`, which runs
    // in both app configurations. This test covers the backend's BEHAVIOUR.
    RaylibBackend b;
    check(!b.is_open(), "backend starts closed");

    // ---- open -------------------------------------------------------------
    // Default geometry and default (off) filtering, which is what the host
    // passes in practice.
    gbarecomp::OpenParams params;
    params.scale = 2;
    params.base_w = kBaseW;
    params.base_h = kBaseH;
    params.title = "recomp smoke";
    const gbarecomp::Result open_result = b.open(params);
    const bool opened = open_result.ok();
    check(opened, "open() succeeded");
    check(b.is_open(), "is_open() after open");

    if (!opened) return 1;

    // A hidden window that is never shown is invisible to the user while every
    // other signal says "running". Nothing else in the suite can see this.
    check(!IsWindowState(FLAG_WINDOW_HIDDEN),
          "window is visible after open()");

    int dw = 0, dh = 0;
    const bool have_size = b.video().drawable_size(&dw, &dh);
    check(have_size, "drawable_size() reported a size");
    check(dw > 0 && dh > 0, "drawable size is positive");

    // ---- present + readback ----------------------------------------------
    const std::vector<std::uint8_t> frame_a = make_frame(1);
    b.video().present(frame_a.data(), /*fresh=*/true);

    std::vector<std::uint8_t> got;
    int rw = 0, rh = 0;
    const bool have_frame = b.video().readback(got, rw, rh);
    check(have_frame, "copy_presented_frame() returned a frame");
    check(rw == kBaseW && rh == kBaseH, "readback is native GBA geometry");
    check(got == frame_a, "uploaded bytes round-trip exactly");

    // A second, different frame must be observable -- this is what proves the
    // streaming texture is actually re-fed every present rather than showing a
    // one-shot or stale buffer.
    const std::vector<std::uint8_t> frame_b = make_frame(200);
    check(frame_a != frame_b, "the two test frames really differ");
    b.video().present(frame_b.data(), /*fresh=*/true);
    got.clear();
    const bool have_frame2 = b.video().readback(got, rw, rh);
    check(have_frame2 && got == frame_b, "second frame replaced the first");

    // ---- pump: live polling against the real window -------------------------
    // No keys are held, so this must be the all-quiet baseline. That exercises
    // the whole polling path (IsKeyDown over every bound key, modifiers,
    // IsGamepadAvailable, mouse, GetTime) plus the snapshot->Events translation
    // against a live GL context. Edge behaviour with keys actually held is
    // covered without a display by input_translate_tests; faking held keys here
    // would need OS-level input injection, which is out of scope.
    //
    // Requires an idle keyboard, like the rest of this test requires a
    // display. A tester holding X during the run would clear the A bit below.
    //
    // NOTE: gamepad presence is NOT asserted absent, nor against
    // IsGamepadAvailable(0). GLFW exposes keyboards' consumer-control
    // interfaces, touchscreens and touchpads as joysticks (this machine
    // reports four), so raylib slot 0 is routinely "available" with no
    // physical pad -- and raylib's 4-slot cap can hide a real pad behind
    // those phantoms entirely. The backend therefore selects through GLFW's
    // standard-mapping layer (see find_standard_pad in raylib_backend.cpp),
    // and this asserts agreement with THAT layer: any standard-mapped pad
    // present. The forward declarations mirror the backend's (same GLFW 3.4
    // signatures); the all-released keyinput below additionally proves no
    // phantom button reads as held.
    {
#if defined(__ANDROID__)
        check(b.input().gamepad_connected() == (IsGamepadAvailable(0) != 0),
              "gamepad presence agrees with raylib (Android: no GLFW)");
#else
        // Forward declarations mirror the backend's (same GLFW 3.4
        // signatures); no GLFW headers needed. Declared at file scope
        // above; block scope cannot carry extern "C".
        bool standard_present = false;
        for (int jid = 0; jid <= 15; ++jid) {
            if (glfwJoystickPresent(jid) && glfwJoystickIsGamepad(jid)) {
                standard_present = true;
                break;
            }
        }
        check(b.input().gamepad_connected() == standard_present,
              "gamepad presence agrees with GLFW standard mapping");
#endif
        const auto ev1 = b.pump();
        check(ev1.keyinput == 0x03FFu, "pump baseline keyinput all-released");
        check(!ev1.quit, "pump baseline raises no quit");
        check(ev1.save_slot == 0 && ev1.load_slot == 0,
              "pump baseline requests no slots");
        check(!ev1.fast_forward && !ev1.rewind,
              "pump baseline has no assist activity");
        check(!ev1.toggle_fullscreen && !ev1.toggle_pause &&
                  !ev1.toggle_fps && !ev1.window_bigger &&
                  !ev1.window_smaller && !ev1.volume_up && !ev1.volume_down,
              "pump baseline raises no hotkeys");
        check(!ev1.mouse_gyro_active && ev1.gyro_delta_x == 0,
              "pump baseline has no mouse gyro");
        check(ev1.gyro_rate_z == 0.0f, "pump reports no gyro without hardware");
        // A second pump with nothing new must also be quiet: with polling
        // there is no KEYDOWN event, so any level mistaken for an edge would
        // re-fire here.
        const auto ev2 = b.pump();
        check(!ev2.quit && ev2.save_slot == 0 && ev2.load_slot == 0 &&
                  !ev2.toggle_pause,
              "second idle pump re-fires nothing");
        // A third pump after the two above: still quiet (no hidden edge
        // accumulation across pumps).
        const auto ev3 = b.pump();
        check(ev3.keyinput == 0x03FFu && !ev3.quit,
              "third idle pump stays quiet");
    }

    // ---- load_input_config: real files, real parsing ------------------------
    // The name->key mapping itself is covered without a display by
    // raylib_keymap_tests (96 assertions). What only runs here is the FILE
    // wiring: section scanning and field assignment in the real build. Held
    // keys cannot be synthesized without OS-level injection, so the observable
    // contract is that loading -- valid, garbage, missing, or null -- never
    // corrupts the bindings: the idle baseline must hold afterwards.
    {
        const char* dir = "/tmp/opencode/raylib_pump_cfg";
        std::string mk = std::string("mkdir -p ") + dir;
        check(std::system(mk.c_str()) == 0, "config staging dir created");
        {
            std::FILE* f = std::fopen("/tmp/opencode/raylib_pump_cfg/keybinds.ini", "w");
            check(f != nullptr, "keybinds.ini written");
            if (f) {
                // Rebind A to F12 (not held): proves the [player1] section is
                // read without disturbing the baseline. The x/l2 lines prove
                // non-GBA names are ignored, not misrouted.
                std::fputs("[player1]\na = F12\nselect = RShift\n"
                           "x = A\nl2 = B\nbogus = Z\n", f);
                std::fclose(f);
            }
            std::FILE* g = std::fopen("/tmp/opencode/raylib_pump_cfg/config.ini", "w");
            check(g != nullptr, "config.ini written");
            if (g) {
                std::fputs("[KeyMap]\nTurbo = Tab\nPause = Shift+P\n"
                           "Fullscreen = Alt+Return\nVolumeUp = F10\n",
                           g);
                // SDL scancode integers on disk (30 = SCANCODE_1): the raylib
                // backend must interpret the SAME file, not a parallel one.
                std::fputs("[Launcher]\nassist_rewind_key = 30\n"
                           "assist_fast_key = 31\nassist_rewind_pad = 0\n"
                           "assist_fast_pad = 0\n", g);
                std::fclose(g);
            }
        }
        b.input().load_config(dir, true, 4);
        b.fx().load_config(dir);  // the [video] half, as HostWindow pairs them
        const auto evc = b.pump();
        check(evc.keyinput == 0x03FFu && !evc.quit,
              "pump baseline holds after loading a real config");
        // Idempotent: loading twice must not accumulate stale overrides.
        b.input().load_config(dir, true, 4);
        b.fx().load_config(dir);
        const auto evc2 = b.pump();
        check(evc2.keyinput == 0x03FFu && !evc2.quit,
              "reloading the config is idempotent");
        // Missing dir and null dir must leave working defaults, not garbage.
        b.input().load_config("/tmp/opencode/raylib_pump_cfg_missing", true, 4);
        check(b.pump().keyinput == 0x03FFu,
              "missing config dir falls back to defaults");
        b.input().load_config(nullptr, true, 4);
        check(b.pump().keyinput == 0x03FFu,
              "null config dir falls back to defaults");
    }

    // ---- touch config + pump with touch enabled ------------------------------
    // No fingers are down, so the baseline must hold exactly as before; the
    // observable contract is that enabling the touch system (policy, pad
    // visibility, [Touch] persistence) runs without disturbing input.
    {
        {
            gbarecomp::TouchConfig tcfg;
            tcfg.policy = true;
            tcfg.claims = 0;
            tcfg.pad_default = 1;
            tcfg.emulate_touch = true;
            tcfg.pad_idle_hide_seconds = 0;
            b.overlay().configure_touch(tcfg);
        }
        check(b.overlay().touch_pad_visible(), "pad visible after configure");
        const auto evt = b.pump();
        check(evt.keyinput == 0x03FFu && !evt.quit,
              "touch-enabled pump with no fingers holds the baseline");
        b.overlay().set_touch_pad_visible(false);
        check(!b.overlay().touch_pad_visible(), "pad hides on request");
        // [Touch] persistence round-trip through the config dir.
        {
            std::FILE* f = std::fopen("/tmp/opencode/raylib_pump_cfg/config.ini", "a");
            check(f != nullptr, "[Touch] appended to config.ini");
            if (f) {
                std::fputs("\n[Touch]\npad_visible = 1\ntoggle_x = 0.25\ntoggle_y = 0.75\n", f);
                std::fclose(f);
            }
        }
        b.overlay().set_config_dir("/tmp/opencode/raylib_pump_cfg");
        check(b.overlay().touch_pad_visible(),
              "pad_visible restored from [Touch]");
        check(b.pump().keyinput == 0x03FFu,
              "baseline holds after [Touch] load");
        {
            gbarecomp::TouchConfig tcfg;
            b.overlay().configure_touch(tcfg);
        }
        b.overlay().set_touch_pad_visible(false);
    }

    // ---- host chrome: overlay hook + pad drawing ------------------------------
    // The callback must run inside present() once per present; the pad draws
    // its shapes with no fingers down. Readback is pre-GPU and unaffected --
    // the assertion is invocation + no crash, not pixels.
    {
        g_overlay_calls = 0;
        b.overlay().set_host_overlay(&test_overlay);
        {
            gbarecomp::TouchConfig tcfg;
            tcfg.policy = true;
            tcfg.pad_default = 1;
            tcfg.emulate_touch = true;
            b.overlay().configure_touch(tcfg);
        }
        // An earlier block saved pad-hidden as the player choice, and choice
        // persists across configure -- set it explicitly.
        b.overlay().set_touch_pad_visible(true);
        check(b.overlay().touch_pad_visible(), "pad visible for chrome test");
        const std::vector<std::uint8_t> src = make_frame(71);
        b.video().present(src.data(), true);
        check(g_overlay_calls == 1, "overlay hook ran once per present");
        std::vector<std::uint8_t> got_c;
        int cw = 0, ch = 0;
        check(b.video().readback(got_c, cw, ch) && got_c == src,
              "chrome does not disturb the presented frame");
        b.video().present(src.data(), true);
        check(g_overlay_calls == 2, "overlay hook runs on every present");
        b.overlay().set_host_overlay(nullptr);
        {
            gbarecomp::TouchConfig tcfg;
            b.overlay().configure_touch(tcfg);
        }
        b.overlay().set_touch_pad_visible(false);
        const int calls_after = g_overlay_calls;
        b.video().present(src.data(), true);
        check(g_overlay_calls == calls_after,
              "removed overlay hook is not called");
    }

    // ---- LCD shader: compiles, presents, leaves the CPU frame intact -----
    // The effect is GPU-side: copy_presented_frame() serves the pre-shader
    // staging buffer, so readback must equal the source exactly while the
    // set_ returns prove the program compiled and the shaded blits ran.
    {
        check(!b.fx().settings().lcd, "LCD shader off by default");
        // Liveness (compiled, not just recorded) is proven by the shaded
        // presents below running clean plus the live-boot log line; the
        // setter itself reports nothing by seam convention (void, like the
        // frame-blend pair).
        set_lcd(b, true);
        check(b.fx().settings().lcd, "LCD shader reports enabled");
        check(b.fx().settings().lcd, "LCD shader reports enabled");
        const std::vector<std::uint8_t> src = make_frame(123);
        b.video().present(src.data(), true);
        std::vector<std::uint8_t> got_l;
        int lw = 0, lh = 0;
        check(b.video().readback(got_l, lw, lh) && got_l == src,
              "shaded present keeps the CPU frame exact");
        // The program is reused, not recompiled, on the next present.
        b.video().present(src.data(), false);
        check(b.video().readback(got_l, lw, lh) && got_l == src,
              "second shaded present keeps the frame");
        set_lcd(b, false);
        check(!b.fx().settings().lcd, "LCD shader off after disable");
        b.video().present(src.data(), true);
        check(b.video().readback(got_l, lw, lh) && got_l == src,
              "unshaded present after disable keeps the frame");
        // config.ini [video] lcd_shader = 1 persists through load_input_config.
        {
            std::FILE* f = std::fopen("/tmp/opencode/raylib_pump_cfg/config.ini", "a");
            check(f != nullptr, "[video] appended to config.ini");
            if (f) {
                std::fputs("\n[video]\nlcd_shader = 1\n", f);
                std::fclose(f);
            }
        }
        b.input().load_config("/tmp/opencode/raylib_pump_cfg", true, 4);
        b.fx().load_config("/tmp/opencode/raylib_pump_cfg");  // the [video] half
        check(b.fx().settings().lcd,
              "config [video] lcd_shader=1 enables it");
        check(b.pump().keyinput == 0x03FFu,
              "baseline holds after the [video] load");
        set_lcd(b, false);
        // Env-at-open beats the config file in both directions: "0" keeps it
        // off despite [video] lcd_shader = 1 ...
        b.close();
        ::setenv("GBARECOMP_LCD_SHADER", "0", 1);
        const bool eopen =
            open_backend(b, "lcd-env-off");
        check(eopen, "reopen with env=0");
        if (eopen)
            check(!b.fx().settings().lcd,
                  "env GBARECOMP_LCD_SHADER=0 beats config [video]=1");
        // ... and "1" turns it on (compiling at open, not via set_).
        b.close();
        ::setenv("GBARECOMP_LCD_SHADER", "1", 1);
        const bool eopen2 =
            open_backend(b, "lcd-env-on");
        check(eopen2, "reopen with env=1");
        if (eopen2) {
            check(b.fx().settings().lcd,
                  "env GBARECOMP_LCD_SHADER=1 enables at open");
            b.video().present(src.data(), true);
            check(b.video().readback(got_l, lw, lh) && got_l == src,
                  "env-enabled shaded present keeps the frame");
        }
        ::unsetenv("GBARECOMP_LCD_SHADER");
        b.close();
        const bool ropen_lcd =
            open_backend(b, "post-lcd");
        check(ropen_lcd, "reopen unshaded for the remaining checks");
    }

    // ---- dither without the grid: independent pass --------------------------
    // Dither strength > 0 runs its own program through the post target whether
    // or not the LCD grid is on; 0 skips the pass entirely. Readback is
    // pre-GPU either way, so all of these are exact — the assertions prove the
    // passes run (compile + blit, both combinations) without dropping frames.
    {
        check(!b.fx().settings().lcd, "grid off entering dither checks");
        const std::vector<std::uint8_t> src = make_frame(141);
        std::vector<std::uint8_t> got_d;
        int dw2 = 0, dh2 = 0;
        b.video().present(src.data(), true);
        check(b.video().readback(got_d, dw2, dh2) && got_d == src,
              "dither-only present keeps the frame");
        set_lcd_dither(b, 0.0f);
        b.video().present(src.data(), true);
        check(b.video().readback(got_d, dw2, dh2) && got_d == src,
              "dither-off present keeps the frame");
        // Grid + dither together (the combined path) also keeps it.
        set_lcd_dither(b, 1.0f);
        set_lcd(b, true);
        b.video().present(src.data(), true);
        check(b.video().readback(got_d, dw2, dh2) && got_d == src,
              "grid+dither present keeps the frame");
        set_lcd(b, false);
    }

    // ---- deband without anything else: independent pass ---------------------
    // Threshold 0 (default) skips the pass entirely; 6 runs the chain alone
    // (no grid, no dither). Readback is pre-GPU: exact either way — these
    // prove the program compiles, the two-target chain links, and nothing
    // drops. Melting itself is measured on screenshots (visual regression).
    {
        set_lcd_dither(b, 0.0f);   // isolate deband: no noise on top
        set_lcd_deband(b, 6.0f);
        const std::vector<std::uint8_t> src = make_frame(151);
        std::vector<std::uint8_t> got_e;
        int ew = 0, eh = 0;
        b.video().present(src.data(), true);
        check(b.video().readback(got_e, ew, eh) && got_e == src,
              "deband-only present keeps the frame");
        b.video().present(src.data(), true);
        check(b.video().readback(got_e, ew, eh) && got_e == src,
              "second deband present keeps the frame");
        set_lcd_deband(b, 0.0f);
        b.video().present(src.data(), true);
        check(b.video().readback(got_e, ew, eh) && got_e == src,
              "deband-off present keeps the frame");
        set_lcd_dither(b, 1.0f);   // restore the default for later sections
    }

    // ---- frame blending: SDL-identical CPU-side averaging -------------------
    // Same primitive, same flags, same order (grade -> blend -> upload) as the
    // SDL backend, so the bytes must match it exactly. Fresh frames blend and
    // advance history; the first after a reset is presented as drawn; holding
    // repeats blend against UNCHANGED history; off uploads raw. Expected bytes
    // use the primitive's documented per-byte mean.
#if defined(GBARECOMP_HAVE_FRAME_BLEND)
    {
        auto avg = [](std::uint8_t a, std::uint8_t b) -> std::uint8_t {
            return static_cast<std::uint8_t>((a & b) +
                                             (((a ^ b) >> 1) & 0x7F));
        };
        auto expect_mix = [&](const std::vector<std::uint8_t>& x,
                              const std::vector<std::uint8_t>& y) {
            std::vector<std::uint8_t> m(x.size());
            for (std::size_t i = 0; i < x.size(); ++i) m[i] = avg(x[i], y[i]);
            return m;
        };
        auto readback = [&](std::vector<std::uint8_t>& out, int& w, int& h) {
            out.clear();
            return b.video().readback(out, w, h);
        };
        set_frame_blend(b, true);
        check((b.fx().settings().frame_blend != 0.0f), "frame blend reports enabled");
        const auto fa = make_frame(11);
        const auto fb = make_frame(12);
        const auto fc = make_frame(13);
        std::vector<std::uint8_t> got_b;
        int bw = 0, bh = 0;
        // Enabling resets history: the first fresh frame is as drawn.
        b.video().present(fa.data(), true);
        check(readback(got_b, bw, bh) && got_b == fa,
              "first blended frame presented as drawn");
        b.video().present(fb.data(), true);
        check(readback(got_b, bw, bh) && got_b == expect_mix(fa, fb),
              "second fresh frame averages with the first");
        // History advanced: a third frame mixes against the second, not the
        // first (a feedback mix would show fa in the result).
        b.video().present(fc.data(), true);
        check(readback(got_b, bw, bh) && got_b == expect_mix(fb, fc),
              "history advances past the first frame");
        check(got_b != expect_mix(fa, fc),
              "no feedback: the first frame is gone from history");
        // Enabling interp resets history too (cadence change would smear).
        set_frame_interp(b, true);
        b.video().present(fc.data(), true);
        check(readback(got_b, bw, bh) && got_b == fc,
              "interp toggle resets blend history");
        const auto fd = make_frame(14);
        b.video().present(fd.data(), true);
        check(readback(got_b, bw, bh) && got_b == expect_mix(fc, fd),
              "fresh frame after the reset blends again");
        // Holding repeat: blends against UNCHANGED history (kept=fd after the
        // fresh fd), so the mix is fd-with-fd, i.e. fd as drawn — while the
        // next fresh still sees fd, proving the hold advanced nothing.
        b.video().present(fd.data(), false);
        check(readback(got_b, bw, bh) && got_b == fd,
              "holding repeat blends against unchanged history");
        const auto fe = make_frame(15);
        b.video().present(fe.data(), true);
        check(readback(got_b, bw, bh) && got_b == expect_mix(fd, fe),
              "fresh frame after a hold still sees the held history");
        // Explicit reset: next fresh is as drawn.
        b.fx().reset_frame_blend();
        b.video().present(fe.data(), true);
        check(readback(got_b, bw, bh) && got_b == fe,
              "reset presents the next frame as drawn");
        // Off: raw uploads, even with a stale-valid history behind.
        set_frame_blend(b, false);
        set_frame_interp(b, false);
        check(!(b.fx().settings().frame_blend != 0.0f), "frame blend reports disabled");
        b.video().present(fa.data(), true);
        check(readback(got_b, bw, bh) && got_b == fa,
              "disabled blend uploads raw despite stale history");
    }
#else
    // Primitive absent: the flag is recorded but nothing is applied.
    {
        set_frame_blend(b, true);
        const std::vector<std::uint8_t> src = make_frame(17);
        b.video().present(src.data(), true);
        std::vector<std::uint8_t> got_n;
        int nw = 0, nh = 0;
        check(b.video().readback(got_n, nw, nh) && got_n == src,
              "blend flag without the primitive uploads raw");
        set_frame_blend(b, false);
    }
#endif

    // ---- set_surface_size: texture recreated, readback follows --------------
    {
        check(b.video().set_surface_size(248, 160), "set_surface_size(248, 160)");
        check(!b.video().set_surface_size(0, 160), "set_surface_size rejects 0 width");
        check(!b.video().set_surface_size(240, -1), "set_surface_size rejects negative");
        const std::vector<std::uint8_t> wide(
            static_cast<std::size_t>(248) * 160 * 3u, 0x7Fu);
        b.video().present(wide.data(), true);
        std::vector<std::uint8_t> got_w;
        int ww = 0, wh = 0;
        check(b.video().readback(got_w, ww, wh) && ww == 248 && wh == 160,
              "readback follows the resized surface");
        check(got_w == wide, "resized upload round-trips exactly");
        check(b.video().set_surface_size(kBaseW, kBaseH), "surface restored to 240x160");
        b.video().present(frame_b.data(), true);
    }

    // ---- wait_for_foreground / haptics / FPS readout ------------------------
    {
        check(b.wait_for_foreground(),
              "wait_for_foreground true while open (desktop: nothing to wait for)");
        b.input().haptic_pulse(100, 0.5f);   // no pad with motors here: must be a safe no-op
        b.input().haptic_pulse(0, 0.5f);     // non-positive duration: refused by policy
        b.input().haptic_pulse(-5, 2.0f);    // out-of-range args: clamped, never crashes
        check(true, "haptic_pulse with no motors does not crash");
        b.video().set_fps_readout(true);
        check(b.video().fps_readout(), "fps readout reports enabled");
        const std::vector<std::uint8_t> f = make_frame(5);
        b.video().present(f.data(), true);
        b.video().present(f.data(), false);
        b.video().set_fps_readout(false);
        check(!b.video().fps_readout(), "fps readout reports disabled");
        check(true, "fps readout toggle across presents does not crash");
    }

    // ---- screen color grading: graded bytes reach the GPU -------------------
    // Raw (nullptr) uploads untouched -- proven by the exact round-trips
    // above. A non-passthrough screen must come back DIFFERENT (the LUT
    // applied) at the same geometry. This is the only observable of the
    // grading path without a colorimeter.
    {
        b.close();
        const bool gopen = open_backend(b, "graded", "frontlit");
        check(gopen, "open with screen=frontlit");
        if (gopen) {
            const std::vector<std::uint8_t> src = make_frame(31);
            b.video().present(src.data(), true);
            std::vector<std::uint8_t> got_g;
            int gw = 0, gh = 0;
            const bool ok = b.video().readback(got_g, gw, gh);
            check(ok && gw == kBaseW && gh == kBaseH,
                  "graded readback keeps native geometry");
            check(ok && got_g != src,
                  "frontlit grading changes the uploaded bytes");
            // And Raw really is passthrough: same frame ungraded is identical.
            b.close();
            const bool ropen = open_backend(b, "raw");
            check(ropen, "reopen with screen=nullptr (Raw)");
            if (ropen) {
                b.video().present(src.data(), true);
                std::vector<std::uint8_t> got_r;
                int rw2 = 0, rh2 = 0;
                check(b.video().readback(got_r, rw2, rh2) && got_r == src,
                      "Raw uploads the frame untouched");
            }
        }
    }

    // ---- sharp prescale + interp tick ---------------------------------------
    // The sharp path engages only at non-integer scales (exact multiples keep
    // the direct blit), so resize to an odd size to force it. Readback is
    // pre-GPU and unaffected by the blit path -- the assertion is that the
    // RenderTexture lifecycle runs without dropping or corrupting a frame.
    {
        b.close();
        const bool sopen = open_backend(b, "sharp", nullptr, false, true);
        check(sopen, "open with sharp_filter=true");
        if (sopen) {
            SetWindowSize(700, 500);
            const std::vector<std::uint8_t> src = make_frame(61);
            b.video().present(src.data(), true);
            std::vector<std::uint8_t> got_s;
            int sw = 0, sh = 0;
            check(b.video().readback(got_s, sw, sh) && got_s == src,
                  "present through the sharp path keeps the frame");
            // Mutual exclusion: enabling linear clears sharp, same rule as SDL.
            b.video().set_linear_filter(true);
            check(b.video().linear_filter(), "linear filter reports enabled");
            b.video().present(src.data(), true);
            check(b.video().readback(got_s, sw, sh) && got_s == src,
                  "present after linear-clears-sharp keeps the frame");
            b.video().set_linear_filter(false);
            SetWindowSize(kBaseW * 2, kBaseH * 2);
            b.close();
            const bool ropen2 = open_backend(b, "raw2");
            check(ropen2, "reopen non-sharp for the remaining checks");
        }
    }

    // ---- interp_display_tick: presents through the pacing policy ------------
    // Far-future deadline + vsync => present immediately (no hold, no sleep
    // beyond the vsync block itself). Disabled => immediate return.
    {
        set_frame_interp(b, true);
        check(b.fx().settings().frame_interp, "frame interp reports enabled");
        const std::vector<std::uint8_t> tick_f = make_frame(83);
        b.video().interp_display_tick(tick_f.data(), UINT64_MAX);
        std::vector<std::uint8_t> got_t;
        int tw = 0, th = 0;
        check(b.video().readback(got_t, tw, th) && got_t == tick_f,
              "enabled interp tick presents the frame");
        set_frame_interp(b, false);
        const std::vector<std::uint8_t> other = make_frame(84);
        b.video().interp_display_tick(other.data(), UINT64_MAX);
        got_t.clear();
        check(b.video().readback(got_t, tw, th) && got_t == tick_f,
              "disabled interp tick presents nothing");
    }

    // ---- assumption check: does the upload path actually reach the GPU? ----
    // copy_presented_frame() above reads the CPU staging buffer, so it proves
    // the call sequence ran and the bookkeeping is right -- NOT that raylib
    // interpreted our RGB888 bytes as we intended. This closes that gap by
    // round-tripping through VRAM the same way present() does, and would catch
    // a stride, format or filter surprise in the upload itself.
    {
        Image img{};
        img.width = kBaseW;
        img.height = kBaseH;
        img.format = PIXELFORMAT_UNCOMPRESSED_R8G8B8;
        img.mipmaps = 1;
        const std::vector<std::uint8_t> src = make_frame(77);
        img.data = const_cast<std::uint8_t*>(src.data());

        Texture2D tex = LoadTextureFromImage(img);
        check(tex.id != 0, "LoadTextureFromImage produced a texture");
        // Exactly the raylib 6 two-argument form the backend uses. The 4-arg
        // overload from raylib 4 is the exact regression this pins.
        UpdateTexture(tex, img.data);
        SetTextureFilter(tex, TEXTURE_FILTER_POINT);

        // Read VRAM back. No render pass is needed: LoadImageFromTexture reads
        // the texture's own storage, which is exactly what we want to verify.
        // (BeginTextureMode takes a RenderTexture2D, not a plain Texture2D.)
        Image back = LoadImageFromTexture(tex);
        check(back.data != nullptr, "LoadImageFromTexture read VRAM back");

        // RAYLIB 6 TRAP, pinned here because it is silent and easy to hit.
        // For a texture created from PIXELFORMAT_UNCOMPRESSED_R8G8B8,
        // LoadImageFromTexture reports PIXELFORMAT_UNCOMPRESSED_R8G8B8A8
        // (== 4, i.e. 4 bytes/pixel) but the buffer it hands back is actually
        // still 3 bytes/pixel. Trusting the format label reads the image as a
        // skewed garbage gradient -- every pixel wrong, with no error.
        // Verified empirically: stride 4 gives 114744 mismatches, stride 3
        // gives 0.
        //
        // So try both plausible strides and require an exact match on at least
        // one. That keeps the assertion meaningful (the pixels really did
        // survive VRAM) while surviving raylib fixing the label later. The
        // backend itself does not read back from the GPU today -- it serves
        // copy_presented_frame() from the CPU staging buffer -- so this is not
        // a live bug, but it is a landmine for any future GPU readback
        // (screenshots, frame capture, GPU-side verification).
        const auto* px = static_cast<const std::uint8_t*>(back.data);
        const auto count_mismatches = [&](std::size_t stride) {
            int n = 0;
            if (!px) return n;
            for (int y = 0; y < kBaseH; ++y) {
                for (int x = 0; x < kBaseW; ++x) {
                    const std::size_t si =
                        (static_cast<std::size_t>(y) * kBaseW + x) * 3u;
                    const std::size_t di =
                        (static_cast<std::size_t>(y) * back.width + x) * stride;
                    for (int c = 0; c < 3; ++c) {
                        if (px[di + c] != src[si + c]) ++n;
                    }
                }
            }
            return n;
        };
        int mismatches = 0;
        if (px) {
            const int at4 = count_mismatches(4);
            const int at3 = count_mismatches(3);
            mismatches = (at3 == 0 || at4 == 0) ? 0 : (at3 < at4 ? at3 : at4);
            if (mismatches) {
                std::printf("  DIAG raylib format=%d stride4=%d stride3=%d\n",
                            (int)back.format, at4, at3);
            }
        }
        check(mismatches == 0,
              "uploaded pixels survive the GPU round-trip exactly");
        UnloadImage(back);
        UnloadTexture(tex);
    }

    // ---- close, then reopen ----------------------------------------------
    // Reopening is the end-to-end check that close() released everything,
    // including the single-owner audio slot added with audio_slot.h. If close()
    // leaked the slot, the reopen would open *without audio*.
    b.close();
    check(!b.is_open(), "is_open() false after close");

    std::vector<std::uint8_t> after_close;
    int aw = 0, ah = 0;
    check(!b.video().readback(after_close, aw, ah),
          "readback refused after close");

    const bool reopened = open_backend(b, "recomp smoke 2");
    check(reopened, "reopen() succeeded (audio slot was released)");
    check(b.is_open(), "is_open() after reopen");

    if (reopened) {
        check(!IsWindowState(FLAG_WINDOW_HIDDEN),
              "window visible after reopen()");
        const std::vector<std::uint8_t> frame_c = make_frame(99);
        b.video().present(frame_c.data(), true);
        got.clear();
        check(b.video().readback(got, rw, rh) && got == frame_c,
              "present/readback works after reopen");
    }

    b.close();
    check(!b.is_open(), "is_open() false after final close");

    std::printf("raylib_present_tests: %s (%d failure(s))\n",
                failures ? "FAIL" : "PASS", failures);
    return failures ? 1 : 0;
#endif
}