// Host glue for the orchestral-music feature (package ffta.enhancement.orchestra,
// plugin "ffta.orchestra"). Engine: src/ffta_orchestra.h.
//
// Seams (game.toml [[mod_function_hook]], disassembly evidence in BRINGUP.md):
//   MPlayStart   0x081458AC thumb  r0 = MusicPlayerInfo*, r1 = song header
//   MPlayStop    0x08145990 thumb  r0 = MusicPlayerInfo*
//   MPlayFadeOut 0x0814511C thumb  r0 = MusicPlayerInfo*, r1 = speed
//   MPlayMain    0x08144B2C thumb  r0 = MusicPlayerInfo* (per-frame tick)
// The game NEEDS its native BGM player to keep running (title/scene logic
// waits on its state -- skipping MPlayStart hung the title screen, see
// BRINGUP 2026-10-21). So the native player runs untouched but is made
// silent: before each BGM MPlayMain tick every track's volX/volMR/volML are
// zeroed and VOLCHG set, and native PCM is gated to 0 for the first frames
// after a start (the track-start code re-inits volX itself). Our sequencer
// plays the same song header and the stream carries the sound. SFX players
// are untouched.
#define TSF_IMPLEMENTATION
#include "ffta_orchestra.h"

#include <cstdio>
#include <string>

#include "mod_audio.h"
#include "mod_function_hooks.h"
#include "mod_runtime.h"
#include "runtime_arm.h"

namespace {

constexpr uint32_t kBgmPlayer = 0x0200F2A0u;
constexpr int kStartGateFrames = 3;
int g_gate_frames = 0;
ffta::Orchestra g_orch;
std::string g_loaded_sf2;
bool g_active = false;
GBAModAudioStream g_stream = GBA_MOD_AUDIO_STREAM_INVALID;

uint8_t rom_u8(uint32_t a) { return bus_read_u8(a); }

void set_native_gain(int pct) {
    if (g_stream != GBA_MOD_AUDIO_STREAM_INVALID)
        gba_mod_audio_stream_set_native_gain_percent(g_stream, pct);
}

int hook_start(uint32_t, int, ArmCpuState* cpu) {
    if (!g_active || !g_orch.ready() || cpu->R[0] != kBgmPlayer) return 0;
    const uint32_t hdr = cpu->R[1];
    if ((hdr >> 24) != 0x08) return 0;  // not a ROM song header: leave native
    g_orch.start(hdr);
    g_gate_frames = kStartGateFrames;
    set_native_gain(0);
    std::fprintf(stderr, "[ffta] orchestra: BGM start header=0x%08X\n", hdr);
    return 0;  // native start still runs (the game depends on its state)
}

// Per-frame BGM player tick: keep the native BGM silent while we play.
int hook_main(uint32_t, int, ArmCpuState* cpu) {
    if (!g_active || cpu->R[0] != kBgmPlayer) return 0;
    if (g_gate_frames > 0 && --g_gate_frames == 0) set_native_gain(100);
    if (!g_orch.playing()) return 0;  // ours ended: let native be heard
    const uint32_t player = kBgmPlayer;
    const uint32_t tracks = bus_read_u32(player + 0x2C);
    uint32_t n = bus_read_u8(player + 8);
    if (n > 16 || (tracks >> 24) < 2) return 0;
    for (uint32_t i = 0; i < n; ++i) {
        const uint32_t t = tracks + i * 0x50;
        const uint8_t flags = bus_read_u8(t);
        if (!(flags & 0x80)) continue;        // track not in use
        bus_write_u8(t + 0x10, 0);            // volMR
        bus_write_u8(t + 0x11, 0);            // volML
        bus_write_u8(t + 0x13, 0);            // volX
        bus_write_u8(t, flags | 0x03);        // VOLCHG: recompute with 0
    }
    return 0;
}

int hook_stop(uint32_t, int, ArmCpuState* cpu) {
    if (g_active && cpu->R[0] == kBgmPlayer) g_orch.stop();
    return 0;  // native stop still runs (harmless on an idle player)
}

int hook_fade(uint32_t, int, ArmCpuState* cpu) {
    if (g_active && cpu->R[0] == kBgmPlayer) g_orch.fade_out(cpu->R[1] & 0xFFFFu);
    return 0;
}

size_t pull(void*, int16_t* dst, size_t max_frames) {
    return g_orch.render(dst, max_frames);  // always a full block (silence idle)
}

void orchestra_reset() {
    g_active = false;
    g_orch.stop();
    gba_mod_set_function_hook_enabled("ffta.orchestra.start", 0);
    gba_mod_set_function_hook_enabled("ffta.orchestra.stop", 0);
    gba_mod_set_function_hook_enabled("ffta.orchestra.fade", 0);
    gba_mod_set_function_hook_enabled("ffta.orchestra.main", 0);
}

void orchestra_activate() {
    const char* sf2 = gba_mod_required_asset_path("ffta.enhancement.orchestra", "soundfont");
    if (!sf2) {
        std::fprintf(stderr, "[ffta] orchestra: no SoundFont asset; feature inert\n");
        return;
    }
    if (g_loaded_sf2 != sf2) {
        if (!g_orch.init(rom_u8, sf2)) {
            std::fprintf(stderr, "[ffta] orchestra: SoundFont load failed: %s\n", sf2);
            return;
        }
        g_loaded_sf2 = sf2;
    }
    g_stream = gba_mod_audio_stream_register_s16_mono(pull, nullptr);
    if (g_stream == GBA_MOD_AUDIO_STREAM_INVALID) return;
    gba_mod_audio_stream_set_enabled(g_stream, 1);
    gba_mod_audio_stream_play(g_stream, 100);
    g_active = true;
    gba_mod_set_function_hook_enabled("ffta.orchestra.start", 1);
    gba_mod_set_function_hook_enabled("ffta.orchestra.stop", 1);
    gba_mod_set_function_hook_enabled("ffta.orchestra.fade", 1);
    gba_mod_set_function_hook_enabled("ffta.orchestra.main", 1);
    std::fprintf(stderr, "[ffta] orchestra: active (%s)\n", sf2);
}

}  // namespace

GBA_MOD_CONSTRUCTOR(register_ffta_orchestra) {
    gba_mod_register_function_entry_plugin("ffta.orchestra.start", 0x081458ACu, 1, hook_start);
    gba_mod_register_function_entry_plugin("ffta.orchestra.stop", 0x08145990u, 1, hook_stop);
    gba_mod_register_function_entry_plugin("ffta.orchestra.fade", 0x0814511Cu, 1, hook_fade);
    gba_mod_register_function_entry_plugin("ffta.orchestra.main", 0x08144B2Cu, 1, hook_main);
    gba_mod_register_reset_callback(orchestra_reset);
    gba_mod_register_activation_plugin("ffta.orchestra", orchestra_activate);
}
