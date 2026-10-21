#pragma once
// FFTA orchestral music engine (feature "ffta.orchestra").
//
// A small MP2K/m4a *sequencer* (song bytecode read from the user's own ROM at
// run time -- no ROM bytes live in this repo) that drives a SoundFont synth
// (TinySoundFont) and produces 65536 Hz mono S16 PCM for the framework's mod
// audio pull stream. Header-only and host-testable: the ROM is read through a
// function pointer so tools/tests can feed a plain file buffer.
//
// Format facts (AGB SDK MusicPlayer2000, cross-checked on this ROM by
// tools/m4a_to_midi.py): song header = {u8 ntracks, u8 nblocks, u8 prio,
// u8 reverb, u32 voicegroup, u32 track[ntracks]}; wait commands 0x80..0xB0 use
// the 49-entry length table; 0xB1 FINE, B2 GOTO, B3 PATT, B4 PEND, B5 REPT,
// BB TEMPO(*2 = bpm, 24 ticks/beat), BC KEYSH, BD VOICE, BE VOL, BF PAN,
// C0 BEND, C1 BENDR, CE EOT, CF TIE, D0.. notes (length idx cmd-0xCF).
//
// Thread model: all entry points run on the emulation producer thread (the
// same thread that runs the generated game code and the mod-audio pull
// callback). Nothing here allocates after init() or blocks.
#include <cmath>
#include <cstdint>
#include <cstring>

#include "tsf.h"

namespace ffta {

class Orchestra {
public:
    using RomRead = uint8_t (*)(uint32_t addr);
    static constexpr int kRate = 65536;  // framework producer rate
    static constexpr int kMaxTracks = 16;
    static constexpr int kMaxNotes = 24;  // simultaneous notes per track

    // sf2 path; returns false if it cannot be loaded.
    bool init(RomRead rd, const char* sf2_path) {
        rom_ = rd;
        sf_ = tsf_load_filename(sf2_path);
        if (!sf_) return false;
        tsf_set_output(sf_, TSF_STEREO_INTERLEAVED, kRate, -9.0f);
        tsf_set_max_voices(sf_, 96);
        for (int c = 0; c < 16; ++c)  // allocate channel state up front
            tsf_channel_set_presetnumber(sf_, c, 0, c == 9);
        return true;
    }
    ~Orchestra() { if (sf_) tsf_close(sf_); }
    bool ready() const { return sf_ != nullptr; }
    bool playing() const { return playing_; }

    // header = guest address (0x08......) of the m4a song header.
    void start(uint32_t header) {
        if (!sf_) return;
        halt_notes();
        ntracks_ = rom_(header);
        if (ntracks_ < 1 || ntracks_ > kMaxTracks) { playing_ = false; return; }
        voicegroup_ = u32(header + 4);
        for (int i = 0; i < ntracks_; ++i) {
            Track& t = trk_[i];
            std::memset(&t, 0, sizeof t);
            t.pc = u32(header + 8 + 4 * i);
            t.vol = 100; t.pan = 64; t.bend = 64; t.bendr = 2; t.key = 60; t.vel = 100;
            t.ch = i % 16 == 9 ? 15 : i % 16;   // channel 9 is the drum channel
            t.active = true;
            tsf_channel_set_pitchrange(sf_, t.ch, 2.0f);
            apply_volume(t); apply_pan(t); apply_bend(t);
            tsf_channel_set_presetnumber(sf_, t.ch, 0, 0);
        }
        bpm_ = 150; tick_acc_ = 0; fade_total_ = 0; gain_ = 1.0f;
        playing_ = true;
    }
    void stop() { halt_notes(); playing_ = false; }
    // m4a MPlayFadeOut: 16 steps of `speed` frames at 59.7275 Hz.
    void fade_out(uint32_t speed) {
        if (!playing_) return;
        fade_total_ = double(speed ? speed : 1) * 16.0 / 59.7275 * kRate;
        fade_left_ = fade_total_;
    }

    // Render n frames of mono S16 (n <= 1024 per call, bounded stack buffer).
    size_t render(int16_t* dst, size_t n) {
        if (!playing_ || !sf_) { std::memset(dst, 0, n * 2); return n; }
        size_t done = 0;
        while (done < n) {
            const double spt = double(kRate) / (double(bpm_) * 24.0 / 60.0);
            if (tick_acc_ <= 0.0) { run_tick(); tick_acc_ += spt; if (!playing_) break; }
            size_t chunk = n - done;
            const size_t until = size_t(std::ceil(tick_acc_));
            if (until < chunk) chunk = until ? until : 1;
            mix(dst + done, chunk);
            tick_acc_ -= double(chunk);
            done += chunk;
        }
        if (done < n) std::memset(dst + done, 0, (n - done) * 2);
        return n;
    }

private:
    struct Note { int16_t key; int32_t left; bool on; };
    struct Track {
        uint32_t pc; int32_t wait; uint32_t stack[3]; int depth;
        uint32_t rept_pc[3]; uint8_t rept_cnt[3];
        uint8_t last, key, vel, gate, vol, pan, bend, bendr, voice; int8_t keysh;
        uint8_t ch; bool active; int nnotes; Note notes[kMaxNotes];
    };
    static constexpr uint8_t kLen[49] = {0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,
        18,19,20,21,22,23,24,28,30,32,36,40,42,44,48,52,54,56,60,64,66,68,72,76,78,80,
        84,88,90,92,96};

    uint32_t u32(uint32_t a) const {
        return rom_(a) | (rom_(a + 1) << 8) | (rom_(a + 2) << 16) | (uint32_t(rom_(a + 3)) << 24);
    }
    void halt_notes() { if (sf_) tsf_note_off_all(sf_); for (auto& t : trk_) t.nnotes = 0; }
    void apply_volume(Track& t) { tsf_channel_set_volume(sf_, t.ch, t.vol / 127.0f); }
    void apply_pan(Track& t) { tsf_channel_set_pan(sf_, t.ch, t.pan / 127.0f); }
    void apply_bend(Track& t) {
        tsf_channel_set_pitchrange(sf_, t.ch, float(t.bendr ? t.bendr : 2));
        int v = 8192 + int((int(t.bend) - 64) / 64.0 * 8191);
        tsf_channel_set_pitchwheel(sf_, t.ch, v < 0 ? 0 : v > 16383 ? 16383 : v);
    }
    // FFTA voice -> GM program. Identity for now; refined by the instrument
    // map (docs/ORCHESTRA.md) once the user has auditioned them.
    int program_for(uint8_t voice) const { return voice & 0x7F; }

    void note_on(Track& t, int key, int vel, int len) {
        int k = key + t.keysh; if (k < 0) k = 0; if (k > 127) k = 127;
        for (int i = 0; i < t.nnotes; ++i)           // retrigger same key
            if (t.notes[i].key == k) { tsf_channel_note_off(sf_, t.ch, k); t.notes[i] = t.notes[--t.nnotes]; break; }
        if (t.nnotes >= kMaxNotes) {                  // steal the oldest
            tsf_channel_note_off(sf_, t.ch, t.notes[0].key);
            for (int i = 1; i < t.nnotes; ++i) t.notes[i - 1] = t.notes[i];
            --t.nnotes;
        }
        tsf_channel_note_on(sf_, t.ch, k, vel / 127.0f);
        t.notes[t.nnotes++] = Note{int16_t(k), len, len < 0};
    }
    void release(Track& t, int key_or_neg) {
        for (int i = 0; i < t.nnotes;) {
            if (t.notes[i].left < 0 && (key_or_neg < 0 || t.notes[i].key == key_or_neg + t.keysh)) {
                tsf_channel_note_off(sf_, t.ch, t.notes[i].key);
                t.notes[i] = t.notes[--t.nnotes];
            } else ++i;
        }
    }

    void run_tick() {
        bool any = false;
        for (int i = 0; i < ntracks_; ++i) {
            Track& t = trk_[i];
            for (int n = 0; n < t.nnotes;) {          // gate countdown
                if (t.notes[n].left > 0 && --t.notes[n].left == 0) {
                    tsf_channel_note_off(sf_, t.ch, t.notes[n].key);
                    t.notes[n] = t.notes[--t.nnotes];
                } else ++n;
            }
            if (!t.active) { any |= t.nnotes > 0; continue; }
            if (t.wait > 0) --t.wait;
            int guard = 4000;
            while (t.active && t.wait == 0 && guard--) step(t);
            if (!guard) t.active = false;
            any |= t.active || t.nnotes > 0;
        }
        if (!any) playing_ = false;
    }

    void step(Track& t) {
        uint8_t c = rom_(t.pc++);
        if (c < 0x80) { c = t.last; --t.pc; if (c < 0x80) { t.active = false; return; } }
        if (c <= 0xB0) { t.wait = kLen[c - 0x80]; return; }
        if (c >= 0xBD) t.last = c;
        switch (c) {
        case 0xB1: t.active = false; return;
        case 0xB2: t.pc = u32(t.pc); return;
        case 0xB3: if (t.depth < 3) t.stack[t.depth++] = t.pc + 4; t.pc = u32(t.pc); return;
        case 0xB4: if (t.depth > 0) t.pc = t.stack[--t.depth]; return;
        case 0xB5: {
            const uint8_t n = rom_(t.pc); const uint32_t a = u32(t.pc + 1); const uint32_t here = t.pc;
            int s = -1; for (int i = 0; i < 3; ++i) if (t.rept_pc[i] == here && t.rept_cnt[i]) s = i;
            if (s < 0) for (int i = 0; i < 3; ++i) if (!t.rept_cnt[i]) { s = i; t.rept_pc[i] = here; t.rept_cnt[i] = 0; break; }
            if (s < 0) { t.pc += 5; return; }
            if (t.rept_cnt[s] + 1u < n) { ++t.rept_cnt[s]; t.pc = a; if (t.rept_cnt[s] == 0) t.rept_pc[s] = 0; }
            else { t.rept_cnt[s] = 0; t.rept_pc[s] = 0; t.pc += 5; }
            return; }
        case 0xB9: t.pc += 3; return;
        case 0xBA: t.pc += 1; return;
        case 0xBB: bpm_ = rom_(t.pc++) * 2; if (bpm_ < 8) bpm_ = 8; return;
        case 0xBC: t.keysh = int8_t(rom_(t.pc++)); return;
        case 0xBD: {
            t.voice = rom_(t.pc++);
            tsf_channel_set_presetnumber(sf_, t.ch, program_for(t.voice), 0);
            return; }
        case 0xBE: t.vol = rom_(t.pc++); apply_volume(t); return;
        case 0xBF: t.pan = rom_(t.pc++); apply_pan(t); return;
        case 0xC0: t.bend = rom_(t.pc++); apply_bend(t); return;
        case 0xC1: t.bendr = rom_(t.pc++); apply_bend(t); return;
        case 0xC2: case 0xC3: case 0xC4: case 0xC5: case 0xC8: t.pc += 1; return;  // LFO/TUNE: TODO
        case 0xCE: {
            int key = -1;
            if (rom_(t.pc) < 0x80) key = rom_(t.pc++);
            release(t, key); return; }
        default: break;
        }
        if (c == 0xCF || c >= 0xD0) {
            if (rom_(t.pc) < 0x80) {
                t.key = rom_(t.pc++);
                if (rom_(t.pc) < 0x80) {
                    t.vel = rom_(t.pc++);
                    if (c >= 0xD0 && rom_(t.pc) < 0x80) t.gate = rom_(t.pc++);
                }
            }
            if (c == 0xCF) note_on(t, t.key, t.vel, -1);
            else { int len = kLen[c - 0xCF] + t.gate; note_on(t, t.key, t.vel, len > 0 ? len : 1); }
            return;
        }
        t.active = false;  // unknown command: end the track rather than desync
    }

    void mix(int16_t* dst, size_t n) {
        float buf[2 * 256];
        size_t o = 0;
        while (o < n) {
            const size_t m = (n - o) > 256 ? 256 : (n - o);
            tsf_render_float(sf_, buf, int(m), 0);
            for (size_t i = 0; i < m; ++i) {
                float g = gain_;
                if (fade_total_ > 0) {
                    g = float(fade_left_ / fade_total_);
                    fade_left_ -= 1.0;
                    if (fade_left_ <= 0) { fade_total_ = 0; gain_ = 0; playing_ = false; halt_notes(); }
                }
                float s = 0.5f * (buf[2 * i] + buf[2 * i + 1]) * g * kMaster;
                s = std::tanh(s);  // soft limiter
                dst[o + i] = int16_t(s * 32767.f);
            }
            o += m;
        }
    }

    static constexpr float kMaster = 1.5f;
    RomRead rom_ = nullptr;
    tsf* sf_ = nullptr;
    Track trk_[kMaxTracks];
    int ntracks_ = 0; uint32_t voicegroup_ = 0; int bpm_ = 150;
    double tick_acc_ = 0, fade_total_ = 0, fade_left_ = 0; float gain_ = 1.0f;
    bool playing_ = false;
};

}  // namespace ffta
