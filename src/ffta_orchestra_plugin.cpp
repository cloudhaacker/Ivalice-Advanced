// Host glue for the orchestral-music feature (package ffta.enhancement.orchestra,
// plugin "ffta.orchestra"). Engine: src/ffta_orchestra.h.
//
// Seams (game.toml [[mod_function_hook]], disassembly evidence in BRINGUP.md):
//   MPlayStart   0x081458AC thumb  r0 = MusicPlayerInfo*, r1 = song header
//   MPlayStop    0x08145990 thumb  r0 = MusicPlayerInfo*
//   MPlayFadeOut 0x0814511C thumb  r0 = MusicPlayerInfo*, r1 = speed
// Only the BGM player (0x0200F2A0 = player 0 in the table at 0x0814BB24) is
// taken over: its MPlayStart is skipped (native BGM never starts, SFX players
// are untouched) and our sequencer plays the same song header instead.
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
ffta::Orchestra g_orch;
std::string g_loaded_sf2;
bool g_active = false;
GBAModAudioStream g_stream = GBA_MOD_AUDIO_STREAM_INVALID;

uint8_t rom_u8(uint32_t a) { return bus_read_u8(a); }

int hook_start(uint32_t, int, ArmCpuState* cpu) {
    if (!g_active || !g_orch.ready() || cpu->R[0] != kBgmPlayer) return 0;
    const uint32_t hdr = cpu->R[1];
    if ((hdr >> 24) != 0x08) return 0;  // not a ROM song header: leave native
    g_orch.start(hdr);
    std::fprintf(stderr, "[ffta] orchestra: BGM start header=0x%08X\n", hdr);
    cpu->R[15] = cpu->R[14] & ~1u;  // return to the guest caller
    return 1;                       // native BGM start skipped
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
    std::fprintf(stderr, "[ffta] orchestra: active (%s)\n", sf2);
}

}  // namespace

GBA_MOD_CONSTRUCTOR(register_ffta_orchestra) {
    gba_mod_register_function_entry_plugin("ffta.orchestra.start", 0x081458ACu, 1, hook_start);
    gba_mod_register_function_entry_plugin("ffta.orchestra.stop", 0x08145990u, 1, hook_stop);
    gba_mod_register_function_entry_plugin("ffta.orchestra.fade", 0x0814511Cu, 1, hook_fade);
    gba_mod_register_reset_callback(orchestra_reset);
    gba_mod_register_activation_plugin("ffta.orchestra", orchestra_activate);
}
