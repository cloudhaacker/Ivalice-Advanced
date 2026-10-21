// Offline renderer for the orchestra engine: song N of a ROM -> 16-bit mono WAV
// at 65536 Hz, exactly what the in-game pull stream produces.
// build: c++ -O2 -std=c++17 -Isrc -Ithird_party/tsf tools/orchestra_render.cpp -o orchestra_render
// usage: orchestra_render game.gba soundfont.sf2 song_index out.wav [seconds]
#define TSF_IMPLEMENTATION
#include "ffta_orchestra.h"
#include <cstdio>
#include <cstdlib>
#include <vector>
static std::vector<uint8_t> g_rom;
static uint8_t rd(uint32_t a) { uint32_t o = a - 0x08000000u; return o < g_rom.size() ? g_rom[o] : 0; }
int main(int argc, char** argv) {
    if (argc < 5) { std::fprintf(stderr, "usage: %s rom sf2 song out.wav [sec]\n", argv[0]); return 1; }
    FILE* f = std::fopen(argv[1], "rb"); if (!f) return 1;
    std::fseek(f, 0, SEEK_END); g_rom.resize(std::ftell(f)); std::fseek(f, 0, SEEK_SET);
    if (std::fread(g_rom.data(), 1, g_rom.size(), f) != g_rom.size()) return 1; std::fclose(f);
    ffta::Orchestra o;
    if (!o.init(rd, argv[2])) { std::fprintf(stderr, "soundfont load failed\n"); return 1; }
    const int song = std::atoi(argv[3]);
    const double sec = argc > 5 ? std::atof(argv[5]) : 60.0;
    const uint32_t hdr = rd(0x0814BB48u + 8 * song) | rd(0x0814BB48u + 8 * song + 1) << 8 |
                         rd(0x0814BB48u + 8 * song + 2) << 16 | uint32_t(rd(0x0814BB48u + 8 * song + 3)) << 24;
    o.start(hdr);
    const size_t total = size_t(sec * 65536);
    std::vector<int16_t> pcm(total);
    for (size_t i = 0; i < total; i += 1024) o.render(pcm.data() + i, std::min<size_t>(1024, total - i));
    FILE* w = std::fopen(argv[4], "wb");
    uint32_t bytes = uint32_t(total * 2), rate = 65536, br = rate * 2; uint16_t one = 1, bits = 16, ba = 2, fmt = 1;
    uint32_t sixteen = 16, riff = 36 + bytes;
    std::fwrite("RIFF", 1, 4, w); std::fwrite(&riff, 4, 1, w); std::fwrite("WAVEfmt ", 1, 8, w);
    std::fwrite(&sixteen, 4, 1, w); std::fwrite(&fmt, 2, 1, w); std::fwrite(&one, 2, 1, w);
    std::fwrite(&rate, 4, 1, w); std::fwrite(&br, 4, 1, w); std::fwrite(&ba, 2, 1, w); std::fwrite(&bits, 2, 1, w);
    std::fwrite("data", 1, 4, w); std::fwrite(&bytes, 4, 1, w); std::fwrite(pcm.data(), 2, total, w); std::fclose(w);
    return 0;
}
