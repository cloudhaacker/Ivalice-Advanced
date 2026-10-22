#!/usr/bin/env python3
"""Instrument audition pack for the music player (player 0) songs.

For every voice the BGM songs use, writes the ORIGINAL GBA sample as WAV plus
voices.csv (usage, note range, current GM program).  ROM-derived output: keep
it out of git.   usage: m4a_voices.py rom.gba outdir
"""
import sys, os, struct, collections, wave, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m4a_to_midi as m
u32 = m.u32

def leaf(d, vg, v, key=60, depth=0):
    o = vg - 0x08000000 + 12 * v
    t = d[o]
    if t == 0x40 and depth < 3:           # key split: u32 subgroup, u32 keymap
        sub = u32(d, o + 4); km = u32(d, o + 8) - 0x08000000
        return leaf(d, sub, d[km + key], key, depth + 1)
    if t == 0x80 and depth < 3:           # every key
        return leaf(d, u32(d, o + 4), key, key, depth + 1)
    return t, d[o + 1], u32(d, o + 4), o

def main():
    rom, out = sys.argv[1:3]
    d = open(rom, 'rb').read(); os.makedirs(out, exist_ok=True)
    use = collections.defaultdict(lambda: {'songs': set(), 'notes': 0, 'keys': []})
    for s in range(640):
        if struct.unpack_from('<H', d, m.TABLE + 8*s + 4)[0] != 0: continue
        h = u32(d, m.TABLE + 8*s) - 0x08000000
        if not 1 <= d[h] <= 16: continue
        vg = u32(d, h + 4)
        for t in range(d[h]):
            ev, _ = m.parse_track(d, u32(d, h + 8 + 4*t) - 0x08000000, 0)
            v = 0
            for e in ev:
                if e[1] == 'voice': v = e[2]
                elif e[1] == 'note':
                    u = use[(vg, v)]; u['songs'].add(s); u['notes'] += 1; u['keys'].append(e[2])
    rows = []
    for (vg, v), u in sorted(use.items(), key=lambda kv: kv[0][1]):
        o = vg - 0x08000000 + 12*v
        top = d[o]; keys = sorted(u['keys'])
        t, basekey, ptr, lo = leaf(d, vg, v)
        wavfile = ''
        if t in (0x00, 0x08, 0x10) and 0x08000000 <= ptr < 0x0A000000:
            w = ptr - 0x08000000
            status = struct.unpack_from('<H', d, w + 2)[0]; freq = u32(d, w + 4) / 1024.0
            size = u32(d, w + 12)
            if 0 < size < 400000 and freq > 1000:
                pcm = bytes((b + 128) & 255 for b in d[w + 16:w + 16 + size])
                if size < freq * 0.5: pcm = pcm * int(freq * 1.0 / size + 1)   # short: repeat
                wavfile = f'voice_{v:03d}.wav'
                with wave.open(os.path.join(out, wavfile), 'wb') as f:
                    f.setnchannels(1); f.setsampwidth(1); f.setframerate(int(freq)); f.writeframes(pcm)
        kind = {0:'sample',8:'sample(fixed)',1:'square1',2:'square2',3:'wave',4:'noise',9:'square1',10:'square2',11:'wave',12:'noise',0x40:'key-split',0x80:'drum/every-key'}.get(top, hex(top))
        rows.append([v, kind, len(u['songs']), u['notes'], keys[0], keys[len(keys)//2], keys[-1], wavfile, v & 0x7F])
    with open(os.path.join(out, 'voices.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['voice','kind','songs','notes','lowest_key','median_key','highest_key','sample_wav','current_gm_program']); w.writerows(rows)
    print(len(rows), 'voices written to', out)
main()
