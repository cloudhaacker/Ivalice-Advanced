#!/usr/bin/env python3
"""Offline MP2K (m4a/Sappy) song -> Standard MIDI File extractor for FFTA (USA).

Reads the user's own ROM (never committed; outputs are ROM-derived, keep them
out of git).  Song table at 0x0814BB48 (8 bytes/entry: header ptr, u16, u16).
Usage: m4a_to_midi.py rom.gba outdir [--song N ...] [--loops N]
Writes song_NNNN.mid plus songs.json (per-song track/voice summary).
"""
import struct, sys, os, json
TABLE = 0x14BB48
LEN = [0]+list(range(1,25))+[28,30,32,36,40,42,44,48,52,54,56,60,64,66,68,72,76,78,80,84,88,90,92,96]
u32 = lambda d,o: struct.unpack_from('<I', d, o)[0]
isrom = lambda v: 0x08000000 <= v < 0x0A000000
def vlq(n):
    b=[n&0x7F]; n>>=7
    while n: b.append((n&0x7F)|0x80); n>>=7
    return bytes(reversed(b))

def parse_track(d, start, loops=1, maxticks=24*60*20):
    """Return (events, info). events: (tick, kind, a, b). Loops unrolled `loops` extra times."""
    pc = start; tick = 0; ev = []; stack = []; rept = {}
    last = 0; key = 60; vel = 100; gate = 0; seen = {}; loopinfo = None; looped = 0
    steps = 0
    while tick < maxticks and steps < 100000:
        steps += 1
        c = d[pc]; pc += 1
        if c < 0x80:                      # running status: repeat last command
            c = last; pc -= 1
            if c < 0x80: break
        if c < 0xB1 :
            tick += LEN[c-0x80]; continue
        if c >= 0xBD: last = c
        if c == 0xB1: break
        if c == 0xB2:
            tgt = u32(d, pc) - 0x08000000; pc += 4
            if tgt in seen and looped >= loops: break
            if tgt in seen: looped += 1
            if loopinfo is None: loopinfo = tick
            seen[tgt] = tick; pc = tgt; continue
        if c == 0xB3:
            stack.append(pc+4); pc = u32(d, pc) - 0x08000000; continue
        if c == 0xB4:
            if stack: pc = stack.pop()
            continue
        if c == 0xB5:
            n = d[pc]; a = u32(d, pc+1) - 0x08000000
            k = pc
            cnt = rept.get(k, 0)
            if cnt+1 < n: rept[k] = cnt+1; pc = a
            else: rept.pop(k, None); pc += 5
            continue
        if c in (0xB9,): pc += 3; continue
        if c == 0xBA: pc += 1; continue
        if c == 0xBB: ev.append((tick,'tempo',d[pc]*2,0)); pc += 1; continue
        if c == 0xBC: ev.append((tick,'keysh',d[pc] if d[pc]<128 else d[pc]-256,0)); pc += 1; continue
        if c == 0xBD: ev.append((tick,'voice',d[pc],0)); pc += 1; continue
        if c == 0xBE: ev.append((tick,'vol',d[pc],0)); pc += 1; continue
        if c == 0xBF: ev.append((tick,'pan',d[pc],0)); pc += 1; continue
        if c == 0xC0: ev.append((tick,'bend',d[pc],0)); pc += 1; continue
        if c == 0xC1: ev.append((tick,'bendr',d[pc],0)); pc += 1; continue
        if 0xC2 <= c <= 0xC5 or c == 0xC8: pc += 1; continue
        if c == 0xCE or c == 0xCF:       # EOT / TIE
            n = 0
            if d[pc] < 0x80:
                key = d[pc]; pc += 1
                if d[pc] < 0x80: vel = d[pc]; pc += 1
            if c == 0xCF: ev.append((tick,'note',key,(vel,-1)))
            continue
        if c >= 0xD0:
            ln = LEN[c-0xCF]
            if d[pc] < 0x80:
                key = d[pc]; pc += 1
                if d[pc] < 0x80:
                    vel = d[pc]; pc += 1
                    if d[pc] < 0x80: gate = d[pc]; pc += 1
            ev.append((tick,'note',key,(vel,ln+gate))); continue
        break   # unknown
    return ev, {'ticks': tick, 'loop_at': loopinfo}

def voices(d, vg, count=128):
    out = []
    for i in range(count):
        o = vg - 0x08000000 + 12*i
        if o+12 > len(d): break
        t = d[o]
        out.append({'type': t, 'key': d[o+1], 'w4': u32(d,o+4), 'w8': u32(d,o+8)})
    return out

def write_midi(path, tracks, bpm0=120):
    chunks = []
    for ti, evs in enumerate(tracks):
        ch = ti % 16
        if ch == 9: ch = 15
        raw = []     # (tick, order, bytes)
        prog = 0; ksh = 0; bendr = 2; bend = 64
        for (t, k, a, b) in evs:
            if k == 'tempo': raw.append((t,0,b'\xff\x51\x03'+struct.pack('>I', int(60_000_000/max(a,1)))[1:]))
            elif k == 'voice': raw.append((t,1,bytes([0xC0|ch, a & 0x7F])))
            elif k == 'vol': raw.append((t,1,bytes([0xB0|ch,7,min(a,127)])))
            elif k == 'pan': raw.append((t,1,bytes([0xB0|ch,10,min(a,127)])))
            elif k == 'keysh': ksh = a
            elif k == 'bendr': bendr = a
            elif k == 'bend':
                bend = a; v = int((a-64)/64*8191*bendr/2)+8192 if bendr else 8192
                v = max(0,min(16383,v)); raw.append((t,1,bytes([0xE0|ch,v&0x7F,v>>7])))
            elif k == 'note':
                vel, ln = b; key = max(0,min(127,a+ksh))
                if ln < 0: ln = 24
                raw.append((t,3,bytes([0x90|ch,key,max(1,vel)]))); raw.append((t+max(ln,1),2,bytes([0x80|ch,key,0])))
        raw.sort(key=lambda x:(x[0],x[1]))
        out = bytearray(); cur = 0
        for t,_,bs in raw: out += vlq(t-cur)+bs; cur = t
        out += b'\x00\xff\x2f\x00'
        chunks.append(b'MTrk'+struct.pack('>I',len(out))+bytes(out))
    with open(path,'wb') as f:
        f.write(b'MThd'+struct.pack('>IHHH',6,1,len(chunks),24)+b''.join(chunks))

def main():
    a = sys.argv[1:]
    if len(a) < 2: print(__doc__); sys.exit(1)
    rom, outdir = a[0], a[1]
    only = [int(a[i+1]) for i,x in enumerate(a) if x == '--song']
    loops = int(a[a.index('--loops')+1]) if '--loops' in a else 1
    d = open(rom,'rb').read(); os.makedirs(outdir, exist_ok=True)
    n = 0
    while isrom(u32(d, TABLE+8*n)) and n < 2000: n += 1
    summary = {}
    for s in range(n):
        if only and s not in only: continue
        h = u32(d, TABLE+8*s) - 0x08000000
        nt = d[h]; vg = u32(d, h+4)
        if not (1 <= nt <= 16) or not isrom(vg): continue
        try:
            tr = []; info = []
            for t in range(nt):
                ev, i = parse_track(d, u32(d, h+8+4*t)-0x08000000, loops)
                tr.append(ev); info.append(i)
            used = sorted({e[2] for t in tr for e in t if e[1]=='voice'})
            vgs = voices(d, vg)
            summary[s] = {'tracks': nt, 'ticks': max(i['ticks'] for i in info),
                          'voicegroup': hex(vg), 'voices_used': used,
                          'voice_types': {v: vgs[v]['type'] for v in used if v < len(vgs)}}
            if any(tr): write_midi(os.path.join(outdir, f'song_{s:04d}.mid'), tr)
        except Exception as e:
            summary[s] = {'error': repr(e)}
    json.dump(summary, open(os.path.join(outdir,'songs.json'),'w'), indent=1)
    print(f'{n} table entries, {sum(1 for v in summary.values() if "error" not in v)} songs written to {outdir}')
if __name__ == '__main__': main()
