# GameFAQs code compilations — reference summary (25621 / 26118 / 27385 / 22129)

Four community documents swept 2026-10-07 (facts extracted with
attribution; the documents themselves are not distributed with this repo):

| FAQ | Author | What it holds | Harvest |
|---|---|---|---|
| 27385 | TetrisTheMovie | Clan/Hero name changer: name buffers + 16-bit letter table | `gClanNameBuffer` (+ letter mapping), clan-name terminator trick |
| 25621 | Adrammelech | Codebreaker compilation: per-slot stat codes, money, laws, clan skills, abilities | field-map addresses (see below) |
| 26118 | labmaster | 350 KB patch-code list (items, monsters, clan, battle, slot modifiers) | **queued deep-mine** — the full copy is archived |
| 22129 | Vegikachu | GSA codes (US + JP) | mostly redundant; JP section noted |

## Verified live on our build (state2, 2026-10-07)

- `gMoney` = **0x02001F64** — read **5000** (the player's actual gold).
- `gClanNameBuffer` = **0x020021A0** — decoded `BD80 DE80 DD80 DC80 E280 0000`
  via the 16-bit table = **"Nutsy"** (the default clan name) — exact match.
- `gClanSkills` = 0x020021B6 (8 × u16) — read `[1,0,…]` (plausible).
- `gBattleLaws` = 0x02003C34 (3 bytes) — read 0 in state2 (caveat: laws may
  live elsewhere / judge-off context).

## Unit-record field offsets (two guides agree; base+stride verified in the

JoKyR note: base 0x02000000, stride 0x108)

name-ptr **+0x80** · level **+0x89** (0x8A appears in one code — likely XP
byte; JoKyR's 0x89 verified live) · HP cur/max **+0x98/+0x9A** · MP
**+0x9C/+0x9E** · Atk **+0xA0** · Def **+0xA2** · Pow **+0xA4** · Res
**+0xA6** · abilities bitmap **+0xC0** (0x90 bytes) · Speed **+0x152** ·
JP **+0x156**.

## Cross-checks & notes

- The stat map agrees across 25621 / 26118 / 22129 (independent code sets) —
  strong convergence.
- "All Jobs & All Abilities" code = 0x48 repeats of 0xEEEE step 2 from
  +0xC0 → the abilities area is 0x90 bytes per unit.
- Code guides encode addresses in printable RAM-order; treat any single
  unverified address as a lead (verify live like `gMoney`/`gClanNameBuffer`).

## Queued

- Deep-mine `faq_26118_full.md` sections: Items (slot modifiers, item IDs),
  Monsters (bank, stats), Clan (mission items, law cards), Battle (ally
  status table), Appendices (race & job modifier) — extract further
  verified-able labels in a later pass.

## 26118 deep-mine — CLOSED (2026-10-07)

Scanned the full 350 KB copy: every code is an **encrypted CodeBreaker pair**
(8+8 hex); there are no raw addresses to extract (apparent "03xx" hits are
encrypted code-word fragments, not addresses). The usable content (per-slot
stat map) was already captured via 25621/22129, which cross-agree with it —
see Section 7 of `symbols/ffta_data_symbols.tsv`. Re-open only if a CBA
decryption is ever wired up; not needed today.

# Cheat-code pages sweep — AlmAR / gamehacking.org / SuperCheats (2026-10-12)

Three code databases swept (facts + addresses extracted with attribution;
no page text redistributed):

| Source | What it holds | Harvest |
|---|---|---|
| AlmAR CodeBreaker (USA/AUS) + 22 sub-pages (Character 1-20, AllCharacters, Misc, ShopsSellEverything) | raw CodeBreaker/Xploder codes | address-bearing — decode scheme below; per-slot unit map × 20 |
| AlmAR Action Replay (USA/AUS) | GSA v1/v2 encrypted 8+8 | labels only |
| gamehacking.org game 4576 | 262 entries: GSA/AR-MAX/CBA-12 formats + ~6 raw CB lines | slot naming (Marche/Montblanc/No 3-24 = 24 roster slots) + raw shop/money lines |
| SuperCheats FFTA (landing + GameShark page) | GSA-encrypted + one raw "Gameshark Infinite Codes" block + a **Europe** set | 3 raw all-slot codes; EUR codes must never be decoded against AFXE |

## CodeBreaker/Xploder decode scheme (empirical; anchored to verified symbols)

- `8AAAAAAA VVVV` — 16-bit write to `0x0|AAAAAAA` (addr nibble 2=EWRAM,
  3=IWRAM, 4=I/O). Verified against `gMoney` and the unit-record map.
- `42AAAAAA VVVV / 0000NNNN YYYY` — multi-write of VVVV, NNNN+1 times,
  stride YYYY (whether VVVV slides +1 per iteration is unverified).
- `32AAAAAAA VVVV` — 16-bit write; auto-increment variant suspected
  ("Quick Level Up" keeps XP climbing).
- `74000130 xxxx` / `D0000020 xxxx` — button conditionals (KEYINPUT).
- Everything else (GSA v1/v2 8+8, AR MAX 8+8, CBA/Xploder 12+12) is
  encrypted — labels only, no addresses.

## Field harvest + verification (2026-10-12, offline GBAS reads)

Protocol: savestate file bytes at `addr - 0x02000000 + 0xFC`
(`reference/jokyr-hack-guide.md` § live-read notes; live TCP form in BRINGUP
2026-10-11 annotation). States: `saves/state2_prev_20261007_114607.state`
(gMoney=5000), `saves/ws_fixtures/world_map.state` (gMoney=4700),
`saves/ws_fixtures/battle_overview.state` (mid-battle).

| Candidate | Verdict |
|---|---|
| XP byte = record +0x8A old / +0x0A corrected | **VERIFIED** — slot0 lvl 3 / XP 18; "Quick Level Up" writes 0x63 here (closes the §7 "likely XP" open item) |
| 0x02001F54/56 "money" pair (AlmAR) | **REFUTED** in field context — zero while gMoney varies 5000→4700 at 0x02001F64; stale code, EUR drift, or battle scratch |
| Totema flags 0x02001FB6 (u16) | **Plausible** — 0x0007 → 0x0807 across saves (bitfield grows with progress); "Have All Totema" writes 0xFFFF |
| gClanSkills 0x020021B6 = 8 × u16 | **Shape confirmed** (values [1×8]); the 8 "Max Appraise/Combat/Craft/Gather/Magic/Negotiate/Smithing/Track" codes = 8 encrypted writes into this array — **slot order unverified**. SuperCheats dispatch hints independently call "smithing level" a real dispatch skill |
| Shop cluster 0x020273C9/0x020273CC/0x0202745C/0x02027460/0x02024434 (cat/init, price mode, item list stride 4, length) + 0x02001F6C unlock | Code-derived only — reads 0 in field states, graphics garbage in battle states (scene scratch, populated when shop UI opens). **Not live-verified** (no shop scene fixture) |
| 0x02024A38 mission-info price | Weak-plausible (0 / 300 in field states) — same scratch caveat |
| Battle enemy units | **NEW SYMBOL** `gBattleEnemyUnits` 0x02002FD8 + i×0x108 (7 slots in battle_overview), name-ptr aligned, party-identical record layout (name +0x00, lvl +0x09, XP +0x0A, u32 +0x14 = 1, HP +0x18/1A, MP +0x1C/1E, name-mode +0x106 = 0 → gNamePtrTableB). EH's gFirstEnemyUnit 0x02002FC4 = same slots framed +0x14 earlier |
| Cheat targets on that array | "Instantly Win Battle" zeroes u16 at record +0x14 (u32 =1 on every live slot; semantics unknown); "Weaken Enemies" writes at +0x04/+0x05 — byte +0x05 tracks an atk-power-like value (party 80, enemies 10-45) |
| +0x102 old (+0x182) "No Cards" target | Reads 0 on all 24 slots in both field states — plausible "cards held" counter, **semantics unverified** |

Fresh corroboration of § 12: record +0x106 name-mode dispatch works on
battle enemies too (mode 0 → random-name table; party slot0 mode 2 →
gPartyNameBuffer).

## Shop-cluster cells demoted to cheat-private scratch (2026-10-12, live TCP)

**SUPERSEDED same day — see "Shop-stock system pinned" below.** Kept for
the record: an in-store probe read all six cells 0, and an exact-address
ROM literal scan found no references, which suggested cheat-private
scratch. Both observations were real; the inference was wrong (below).

## Shop-stock system pinned (2026-10-12, live TCP + disasm) — CORRECTS the above

A full transaction (buy potion −50g, sell bandage +100g) probed read-only
mid-scene flipped the verdict: 0x0202745C = 100 (the sold item's price),
0x02027460 = a 14×4 {id u16, count u8, pad} working stock list, 0x020273CC
= 3 (menu page; the cheat conditional 720273CC 0004 gates on page 4),
0x02024434 = list length (9 in buy menu, 4 after). Party inventory slot0
count tracked the buy exactly (gMoney 4700→4750 ✓).

Decisive positive: the engine reaches the canonical stock array by
**literal base 0x02001EE4** (= gInventory 0x02001940 + 0x5A4) — two
predicates loop 14 slots × 4 B over it: stock-full @0x08061E1C (count ==
0x63) and has-stock @0x080680B4 (id != 0 && count != 0). That base+offset
access pattern is why the exact-address literal scan failed. The menu
cells are engine UI state mirroring/working-copying that array.

New symbols (symbols/ffta_data_symbols.tsv § 20): gShopStock 0x02001EE4
(14×4), gShopMenuStock 0x02027460 (working copy), gShopMenuPage 0x020273CC,
gShopMenuStockCount 0x02024434, gShopPrice 0x0202745C. The 0x02024420-7F
block remains UI/cursor machinery (blinker 0x08017F04 / draw 0x08017E80),
not shop data. Issue #22 consequence: "Shops Sell Everything" needs no
runtime injection — a cheat layer writing these live cells (page-gated)
reproduces it.

Method note for future sweeps: exact-address ROM literal scans fail for
any base-relative cell; scan for plausible bases (region windows) instead,
and never settle engine-vs-cheat-scratch from single-scene reads.

Session-notes discipline: probes of a user-launched session must be
read-only (`read_ewram` etc.); `quit` in observe mode closes the debug
listener permanently without touching the game (runtime.cpp spawns the
observe server in its own thread; the game survives).
