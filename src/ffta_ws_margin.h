// FFTA widescreen margin policy — the pure decision logic, split out of
// src/main.cpp so the unit tests can pin it without a window, ROM, or
// engine. The live policy (ffta_ws_margin_policy in main.cpp) applies these
// results to the engine's provider seam every frame.
//
// Evidence trail (2026-10-16, BRINGUP § "UI-layer margin suppression"):
// the wide compositor samples 256-px (BGxCNT size==0) tilemaps with
// (x - extra_left + hofs) mod 256, so FFTA's UI panels — chat bubbles,
// portrait plates, pub rumor/law screens, confirm dialogs — repeat their
// edge columns in the wide margins. Pinned pixel-exact on four device
// captures + the desktop pub replay; the battle move/pan state keeps its
// margins because all four of its layers are the 512-px ring (no size-0
// layer). Disconfirmed gate conditions (captured, do not re-add without new
// evidence): BLDCNT==0 (the pub conversation blends), window-enable bits
// (device conversations run them clear, the desktop pub sets them — same
// UI, different enable routing). The only stable discriminator is size==0.
//
// Summon safety is inherited: the 2026-10-15 withdrawal's A/B replay shows
// the summon window pixel-identical with a width rule strictly SUPERSET of
// this one enabled (that rule had no window condition and suppressed the
// same size-0 effect layers) — suppressing nothing the guest draws.
#pragma once

#include <cstddef>
#include <cstdint>

namespace ffta {

// Layers whose margin samples must be suppressed: enabled (DISPCNT bit 8+bg)
// AND 256-px-wide (BGxCNT size bits == 0). Bit i = BG{i}. The caller gates
// on windows-enable separately if it wants the (never-observed-necessary)
// extra condition — see the disconfirmation note above.
inline std::uint32_t ws_ui_gate_layers(const std::uint8_t* io,
                                       std::size_t io_size) {
    if (!io || io_size < 0x10) return 0;  // fail safe: no IO, no gate
    const std::uint32_t dispcnt = io[0x00] | (io[0x01] << 8);
    std::uint32_t mask = 0;
    for (std::uint32_t bg = 0; bg < 4; ++bg) {
        if (!((dispcnt >> (8 + bg)) & 1u)) continue;
        const std::uint32_t cnt = io[0x08 + bg * 2] | (io[0x09 + bg * 2] << 8);
        if (((cnt >> 14) & 3u) == 0u) mask |= 1u << bg;
    }
    return mask;
}

// The per-sample action for an admitted (size-0) layer, mirroring the
// engine's g_ws_bg_x_provider contract: -1 suppresses the sample, 0 keeps
// the hardware X. `output_x` is the physical wide-view X; the native span
// is [extra_left, extra_left + 240). Faithful 240 views (extra 0) never
// suppress.
inline int ws_ui_gate_sample(int extra_left, int output_x) {
    return (output_x < extra_left || output_x >= extra_left + 240) ? -1 : 0;
}

}  // namespace ffta
