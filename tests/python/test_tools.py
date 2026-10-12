#!/usr/bin/env python3
"""Host-side tests for the Python tooling (stdlib unittest, no pytest).

Covers the pure logic the healing/audit flow depends on:
  - trace_split: backward-jump segmentation + header preservation
  - cache_harvest: recomp_cache unit-file parsing + game.toml address set
  - misspack.prologue_scan: thumb push-with-lr backscan on a synthetic ROM
  - TsvGuardTests: symbols/*.tsv shape, alignment, duplicate discipline
  - RomTruthTests: ROM-pinned facts behind the symbol tables (LOCAL-ONLY,
    skips without game.gba) — dispatch tables, pointer cells, party base,
    SWI veneers
  - EmibiosBytePinTests: the COMMITTED launch BIOS (clean-room emibios,
    issue #17) byte-pinned at its contract points — exception vectors, the
    IRQ trampoline + 0x138 epilogue, the SWI dispatcher + its halfword
    table, the .vc_irqh handler — plus the recompile TOML's seed
    inventory. Runs EVERYWHERE (repo material, not a dump): CI included.
  - RegenStampContractTests: the .regen_stamp cross-script contract
    (build.py/cycle.py write it after a regen; build_apk.py's freshness
    gate reads it — corpus mtimes cannot date a regen)

Run: .venv/bin/python tests/python/test_tools.py [-v]
Requires capstone (misspack dependency): use .venv per docs/manual-build.md,
or `pip install capstone==5.0.7` — CI installs that same pin.
"""
import pathlib
import re
import struct
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

try:
    import cache_harvest  # noqa: E402
    import misspack  # noqa: E402
except ModuleNotFoundError as exc:
    if exc.name == "capstone":
        raise SystemExit(
            "unit-py needs capstone (misspack dependency): run via "
            ".venv/bin/python (docs/manual-build.md) or `pip install "
            "capstone==5.0.7`") from None
    raise


class TraceSplitTest(unittest.TestCase):
    def test_backward_jump_splits_and_headers_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            t = pathlib.Path(td) / "trace.csv"
            t.write_text("# gbarecomp-keyinput-v1\n# frame,keyinput_active_low\n"
                         "0,0x03FF\n10,0x03F7\n20,0x03FF\n5,0x03FE\n15,0x03FF\n")
            r = subprocess.run(
                [sys.executable, "tools/trace_split.py", "--trace", str(t),
                 "--out-dir", td, "--prefix", "seg"],
                cwd=str(REPO), capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            seg1 = (pathlib.Path(td) / "seg1.csv").read_text()
            seg2 = (pathlib.Path(td) / "seg2.csv").read_text()
            self.assertIn("# gbarecomp-keyinput-v1", seg1)
            self.assertIn("20,0x03FF", seg1)
            self.assertNotIn("5,0x03FE", seg1)
            self.assertIn("5,0x03FE", seg2)
            self.assertIn("15,0x03FF", seg2)
            self.assertNotIn("20,0x03FF", seg2)

    def test_monotonic_single_segment(self):
        with tempfile.TemporaryDirectory() as td:
            t = pathlib.Path(td) / "trace.csv"
            t.write_text("0,0x03FF\n5,0x03F7\n")
            r = subprocess.run(
                [sys.executable, "tools/trace_split.py", "--trace", str(t),
                 "--out-dir", td, "--prefix", "m"],
                cwd=str(REPO), capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((pathlib.Path(td) / "m1.csv").exists())
            self.assertFalse((pathlib.Path(td) / "m2.csv").exists())


class CacheHarvestTest(unittest.TestCase):
    def test_collect_parses_unit_filenames(self):
        with tempfile.TemporaryDirectory() as td:
            repo = pathlib.Path(td)
            d = repo / "recomp_cache" / "x" / "y"
            d.mkdir(parents=True)
            (d / "005F0000_DEADBEEF_t.c").write_text("")
            (d / "005F0000_DEADBEEF_t.log").write_text("")
            (d / "805F0000_FEEDFACE_a.c").write_text("")
            (d / "not-a-unit.txt").write_text("")
            units = cache_harvest.collect(repo)
            self.assertEqual(units, {0x005F0000: "t", 0x805F0000: "a"})

    def test_game_addrs_reads_game_toml(self):
        with tempfile.TemporaryDirectory() as td:
            repo = pathlib.Path(td)
            (repo / "game.toml").write_text(
                '[[extra_func]]\naddr = 0x005F0000\nmode = "thumb"\n')
            self.assertEqual(cache_harvest.game_addrs(repo), {0x005F0000})


class PrologueScanTest(unittest.TestCase):
    def test_thumb_push_backscan_finds_prologue(self):
        rom = bytearray(0x400)
        struct.pack_into("<H", rom, 0x40, 0xB510)  # push {r4, lr}
        hits = misspack.prologue_scan(bytes(rom), misspack.ROM_BASE + 0x60,
                                      "thumb", limit=0x100)
        self.assertEqual(hits[0][0], misspack.ROM_BASE + 0x40)
        self.assertTrue(hits[0][1].startswith("push"))

    def test_no_prologue_returns_empty(self):
        hits = misspack.prologue_scan(bytes(0x400), misspack.ROM_BASE + 0x60,
                                      "thumb", limit=0x100)
        self.assertEqual(hits, [])


class SaveCheckTest(unittest.TestCase):
    """savecheck.py end-to-end on synthetic saves (real-ROM checksum table)."""

    @classmethod
    def setUpClass(cls):
        if not (REPO / "game.gba").exists():
            raise unittest.SkipTest("game.gba missing (checksum table needed)")
        sys.path.insert(0, str(REPO / "tools"))
        import savecheck
        savecheck.crc_tab = savecheck.load_crc_table()
        cls.savecheck = savecheck

    def _raw_save(self):
        """Valid 64 KiB image: header group in sectors 3..0 (header = 3)."""
        f = bytearray(0x10000)
        for i in range(16):
            for j in range(0, 0x1000, 16):
                f[i * 0x1000 + j] = (i * 7 + j) & 0xFF
        hdr = 3 * 0x1000
        f[hdr:hdr + 8] = b"FFTEX000"
        struct.pack_into("<I", f, hdr + 0x08, 7)      # counter
        struct.pack_into("<I", f, hdr + 0x0C, 0)      # checksum placeholder
        f[hdr + 0x12:hdr + 0x16] = bytes([3, 2, 1, 0])
        group = bytes().join(bytes(f[s * 0x1000:(s + 1) * 0x1000])
                             for s in (3, 2, 1, 0))
        struct.pack_into("<I", f, hdr + 0x0C, self.savecheck.group_checksum(group))
        return f

    def _run(self, td, data, name="t.sav"):
        p = pathlib.Path(td) / name
        p.write_bytes(data)
        return subprocess.run([sys.executable, "tools/savecheck.py", str(p)],
                              cwd=str(REPO), capture_output=True, text=True)

    def test_valid_save_ok(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._run(td, bytes(self._raw_save()))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("checksum=0x", r.stdout)
            self.assertIn("OK", r.stdout)

    def test_corrupted_group_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._raw_save()
            data[0x1100] ^= 0xFF  # sector 1, inside the checksummed 0x2FC4 prefix
            r = self._run(td, bytes(data))
            self.assertEqual(r.returncode, 1)
            self.assertIn("MISMATCH", r.stdout)

    def test_rtn5_container_ok_and_crc_flagged(self):
        import zlib
        raw = bytes(self._raw_save())
        payload = zlib.compress(raw)
        hdr = struct.pack("<IHHIIII", 0x354E5452, 1, 1, len(raw),
                          len(payload), 24, zlib.crc32(raw) & 0xFFFFFFFF)
        with tempfile.TemporaryDirectory() as td:
            r = self._run(td, hdr + payload, "c.sav")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("RTN5", r.stdout)
            bad = bytearray(hdr + payload)
            bad[20] ^= 0xFF  # corrupt the stored CRC32
            r2 = self._run(td, bytes(bad), "bad.sav")
            self.assertEqual(r2.returncode, 1)
            self.assertIn("CRC32 mismatch", r2.stdout)


class BuildPyTest(unittest.TestCase):
    """Root bootstrap script stays runnable on the system python (stdlib)."""

    def test_help_runs(self):
        r = subprocess.run([sys.executable, "build.py", "--help"],
                           cwd=str(REPO), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--force", r.stdout)
        self.assertIn("--no-smoke", r.stdout)


class RepoHygieneTests(unittest.TestCase):
    """Tracked files must stay portable: no absolute home-directory paths
    (they leak the author's layout and break on every other checkout)."""

    def test_no_absolute_home_paths(self):
        if not (REPO / ".git").exists():
            self.skipTest("not a git checkout")
        # git grep exits 1 when there are no matches (the good case).
        # The pathspec excludes THIS file: its source necessarily contains
        # the pattern string and would otherwise match itself.
        r = subprocess.run(
            ["git", "-C", str(REPO), "grep", "-n", "-I", "-E",
             r"/home/|/Users/", "--", ".",
             ":(exclude)tests/python/test_tools.py"],
            capture_output=True, text=True)
        self.assertIn(r.returncode, (0, 1), r.stderr)
        if r.returncode == 0:
            self.fail("absolute home paths in tracked files:\n" + r.stdout)


class TsvGuardTests(unittest.TestCase):
    """symbols/*..tsv must stay machine-parseable: a malformed line or a
    non-identifier name breaks gba_recompile --symbols at regen time (or,
    worse, silently mislabels an emitted unit). Cheap structural sweep."""

    def _tsv_rows(self, path):
        rows = []
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if not line or line.startswith("#"):
                continue
            rows.append((i, line.split("\t")))
        return rows

    def test_ffta_symbols_tsv_shape(self):
        path = REPO / "symbols" / "ffta_symbols.tsv"
        self.assertTrue(path.exists())
        for i, f in self._tsv_rows(path):
            self.assertEqual(len(f), 3, f"symbols line {i}: 3 fields")
            self.assertRegex(f[0], r"^0x[0-9A-Fa-f]{8}$",
                             f"symbols line {i}: address")
            self.assertIn(f[1].lower(), ("arm", "thumb"),
                          f"symbols line {i}: mode")
            self.assertRegex(f[2], r"^[A-Za-z_][A-Za-z_0-9]*$",
                             f"symbols line {i}: C identifier name")
            self.assertGreater(len(f[2]), 2, f"symbols line {i}: name")

    def test_ffta_data_symbols_tsv_shape(self):
        path = REPO / "symbols" / "ffta_data_symbols.tsv"
        self.assertTrue(path.exists())
        for i, f in self._tsv_rows(path):
            self.assertEqual(len(f), 4, f"data symbols line {i}: 4 fields")
            self.assertRegex(f[0], r"^0x[0-9A-Fa-f]{8}$",
                             f"data symbols line {i}: address")
            self.assertIn(f[1].lower(), ("ewram", "iwram", "rom", "pal", "oam",
                                         "vram", "sram", "bio", "irq"),
                          f"data symbols line {i}: region")
            self.assertRegex(f[2], r"^0x[0-9A-Fa-f]+$",
                             f"data symbols line {i}: size")
            self.assertRegex(f[3], r"^[A-Za-z_][A-Za-z_0-9]*$",
                             f"data symbols line {i}: C identifier name")

    def test_no_duplicate_symbol_names(self):
        seen = {}
        for name in ("ffta_symbols", "ffta_data_symbols"):
            path = REPO / "symbols" / f"{name}.tsv"
            for i, f in self._tsv_rows(path):
                sym, addr = f[-1], f[0]
                if sym in seen and seen[sym][0] != addr:
                    self.fail(f"duplicate name {sym} ({seen[sym][0]} vs "
                              f"{addr}, {name} line {i})")
                seen[sym] = (addr, name)

    def test_thumb_arm_alignment(self):
        # Mirrors cycle.py's dispatch sanity at the source: a thumb seed
        # must be even, an ARM seed 4-aligned. An odd address means a raw
        # interworking pointer slipped into the TSV.
        for name in ("ffta_symbols", "ffta_data_symbols"):
            path = REPO / "symbols" / f"{name}.tsv"
            for i, f in self._tsv_rows(path):
                addr = int(f[0], 16)
                if name == "ffta_symbols":
                    if f[1].lower() == "thumb":
                        self.assertEqual(addr & 1, 0,
                                         f"{name} line {i}: odd thumb {f[0]}")
                    else:
                        self.assertEqual(addr & 3, 0,
                                         f"{name} line {i}: misaligned arm "
                                         f"{f[0]}")

    def test_no_duplicate_symbol_addrs(self):
        # Two rows for one address split the debug meaning (and one of the
        # names silently loses in symbol_map.cpp). Four overlaps are
        # tolerated, all deliberate and documented in the TSVs: the three
        # accessor entries (function seed doubles as table label —
        # UnitStat/AbilityProp/AbilityMpCost, data-symbols § 3) and
        # 0x085680DC (gNamePtrTableB starts where gTextRandomUnitNames
        # lives — same bytes, two views).
        allowed = {"0X080C7EA4", "0X080CCD50", "0X0812ED98", "0X085680DC"}
        seen = {}
        for name in ("ffta_symbols", "ffta_data_symbols"):
            path = REPO / "symbols" / f"{name}.tsv"
            for i, f in self._tsv_rows(path):
                addr = f[0].upper()
                if addr in seen and addr not in allowed:
                    self.fail(f"duplicate address {f[0]} ({seen[addr]} vs "
                              f"{name} line {i})")
                seen.setdefault(addr, f"{name} line {i}")

    def test_patches_readme_rows_match_files(self):
        readme = (REPO / "tools" / "patches" / "README.md").read_text()
        listed = set()
        for line in readme.splitlines():
            if line.startswith("| `") and ".patch" in line:
                listed.add(line.split("`")[1])
        present = {p.name for p in (REPO / "tools" / "patches").glob("*.patch")}
        self.assertTrue(present, "no *.patch files?")
        self.assertEqual(present, listed,
                         f"README rows vs patch files drift: "
                         f"{sorted(present ^ listed)}")


class BiosBytePinTests(unittest.TestCase):
    """gba_bios.bin must stay byte-stable at the contract points our engine
    code cites. These exact words are pinned by armv4t runtime comments/logic
    (vector targets, the IRQ wrapper epilogue, the SWI dispatcher's
    System-mode service switch and epilogue — BRINGUP 2026-10-09); a
    replaced or patched BIOS silently invalidates them.

    NOTE (issue #17 swap): this is the RETAIL dump — local-only REFERENCE
    material (the launcher-accepted alternative + the oracle's default),
    no longer the launch BIOS. The launch BIOS is the committed clean-room
    emibios, pinned EVERYWHERE by EmibiosBytePinTests above. The dump is
    ROM/BIOS-derived and never in git (gbarecomp/.gitignore bios/*.bin)
    — these tests stay LOCAL-ONLY and skip on any checkout without it
    (CI included)."""

    BIOS = REPO / "gbarecomp" / "bios" / "gba_bios.bin"

    @classmethod
    def setUpClass(cls):
        if not cls.BIOS.exists():
            raise unittest.SkipTest(
                "gba_bios.bin absent (gitignored by design, never in git; "
                "local-only test)")

    def _u32(self, off):
        with self.BIOS.open("rb") as f:
            f.seek(off)
            return struct.unpack("<I", f.read(4))[0]

    def test_sha1_pin(self):
        import hashlib
        self.assertEqual(
            hashlib.sha1(self.BIOS.read_bytes()).hexdigest(),
            "300c20df6731a33952ded8c436f7f186d25d3492",
            "gba_bios.bin replaced/patched — every engine BIOS citation is "
            "now suspect")

    def test_vectors(self):
        # Exception vector table: B (0xEA...) targets computed from each slot.
        # 0x1C is the shared Undefined/Abort/FIQ handler's entry (not a B).
        cases = {0x00: 0x68, 0x08: 0x140, 0x18: 0x128, 0x1C: None}
        for off, target in cases.items():
            if target is not None:
                w = self._u32(off)
                self.assertEqual(w >> 24, 0xEA,
                                 f"vector at {off:#05x} not a B")
                self.assertEqual(off + 8 + ((w & 0xFFFFFF) << 2), target,
                                 f"vector at {off:#05x} target")

    def test_irq_wrapper_epilogue(self):
        # IRQ wrapper (0x128..): pop {r0-r3,ip,lr} then subs pc,lr,#4.
        self.assertEqual(self._u32(0x138), 0xE8BD500F, "IRQ pop")
        self.assertEqual(self._u32(0x13C), 0xE25EF004, "IRQ subs pc,lr,#4")

    def test_swi_dispatcher_service_switch_and_epilogue(self):
        # SWI dispatcher (0x140): switch to System mode for the service
        # (msr cpsr_fc), restore SVC, pop {fp,ip,lr}, movs pc,lr.
        self.assertEqual(self._u32(0x160), 0xE129F00B, "msr cpsr_fc,fp")
        self.assertEqual(self._u32(0x174), 0xE3A0C0D3, "mov ip,#0xd3")
        self.assertEqual(self._u32(0x184), 0xE8BD5800, "SWI pop")
        self.assertEqual(self._u32(0x188), 0xE1B0F00E, "SWI movs pc,lr")


class EmibiosBytePinTests(unittest.TestCase):
    """bios/emibios_gba_bios.bin — the LAUNCH BIOS since the issue #17
    swap — byte-pinned at the contract points the engine cites.

    Unlike BiosBytePinTests above (the retail dump: local-only, skips on
    CI), emibios is COMMITTED clean-room repo material (LGPL-3.0-or-later,
    bios/README.md), so these pins run EVERYWHERE — a fresh clone carries
    the file and a replaced/rebuilt-different emibios must fail loudly,
    not skip: it would silently invalidate the game.toml [bios] pin, the
    build.gradle biosSha1 manifest pin, the launcher pin-set acceptance,
    the corpus seeds' addresses/names, and the BIOS-address prose in
    reference/dev-gotchas.md. emibios deliberately mirrors retail's
    layout (its dispatcher.s documents the contract), so most pins share
    retail's addresses — but 0x1C differs (a real reserved handler at
    0x1FC, not retail's shared entry) and the SWI number is read from
    bits 23..16 (lr-2) instead of retail's low byte.

    Missing file = broken checkout (repo material): FAIL, never skip.
    """

    BIOS = REPO / "bios" / "emibios_gba_bios.bin"
    TOML = REPO / "bios" / "emibios_gba_bios.toml"
    SHA1 = "0c0d404d16c6b55b3071aba714f82077da132f14"
    # emibios main @c4d5d71 (LGPL-3.0-or-later; the only build these pins
    # have been derived against — a bump re-derives every one of them).

    @classmethod
    def setUpClass(cls):
        # Committed repo material: absence is a broken checkout, not the
        # local-only skip the retail dump takes.
        import hashlib
        if not cls.BIOS.is_file():
            raise AssertionError(
                "bios/emibios_gba_bios.bin missing — the committed "
                "clean-room BIOS (issue #17) is repo material; a "
                "checkout without it is broken, restore it")
        cls.data = cls.BIOS.read_bytes()

    def _u32(self, off):
        return struct.unpack_from("<I", self.data, off)[0]

    def _u16(self, off):
        return struct.unpack_from("<H", self.data, off)[0]

    def test_sha1_pin(self):
        import hashlib
        self.assertEqual(
            hashlib.sha1(self.data).hexdigest(), self.SHA1,
            "emibios replaced/rebuilt — every pin below and every config "
            "pin (game.toml [bios], build.gradle biosSha1, "
            "android_static EMIBIOS_SHA1) is now suspect")

    def test_size(self):
        self.assertEqual(len(self.data), 16384,
                         "not a 16 KiB BIOS image anymore")

    def test_vectors(self):
        # Exception vectors: B (0xEA...) targets computed from each slot.
        # 0x00/0x08/0x18 mirror retail deliberately; 0x1C is emibios's own
        # reserved handler (retail: shared Undefined/Abort/FIQ entry).
        cases = {0x00: 0x68, 0x08: 0x140, 0x18: 0x128, 0x1C: 0x1FC}
        for slot, target in cases.items():
            w = self._u32(slot)
            self.assertEqual(w >> 24, 0xEA,
                             f"vector at {slot:#05x} not a B")
            self.assertEqual(slot + 8 + ((w & 0xFFFFFF) << 2), target,
                             f"vector at {slot:#05x} target")

    def test_irq_trampoline(self):
        # IRQ wrapper 0x128..: push {r0-r3,ip,lr}; mov r0,#0x4000000;
        # add lr,pc,#0 (installs 0x138 as the handlers' runtime return
        # target — the `after_interrupt` seed); ldr pc,[r0,#-4] (jumps
        # the [0x03FFFFFC] mirror of [0x03007FFC]); pop; subs pc,lr,#4.
        words = {0x128: 0xE92D500F, 0x12C: 0xE3A00301,
                 0x130: 0xE28FE000, 0x134: 0xE510F004,
                 0x138: 0xE8BD500F, 0x13C: 0xE25EF004}
        for off, want in words.items():
            self.assertEqual(self._u32(off), want,
                             f"IRQ trampoline word at {off:#05x}")

    def test_swi_dispatcher(self):
        # SWI dispatcher 0x140..: push {fp,ip,lr}; ldrb ip,[lr,#-2]
        # (the number, bits 23..16 at lr-2 — the commercial `swi #(n<<16)`
        # encoding FFTA uses); table lookup via add/ldrh (base 0x194);
        # msr cpsr_fc (System-mode service switch, caller's IRQ/FIQ mask
        # carried); mov ip,#0xd3 (restore SVC); pop; movs pc,lr.
        words = {0x140: 0xE92D5800, 0x144: 0xE55EC002,
                 0x148: 0xE08FB08C, 0x14C: 0xE1DBC4B4,
                 0x160: 0xE129F00B, 0x174: 0xE3A0C0D3,
                 0x184: 0xE8BD5800, 0x188: 0xE1B0F00E}
        for off, want in words.items():
            self.assertEqual(self._u32(off), want,
                             f"SWI dispatcher word at {off:#05x}")

    def test_swi_table(self):
        # The halfword handler table at 0x194 (0x140+0x54), entries
        # 0x00..0x2A (43), mixed-mode (bit0 set = Thumb handler). Pinned
        # as a 44-halfword blob: 43 entries plus the boundary word, so a
        # table-size/extent change also fails here; the bounds check
        # covers the real entries only.
        import hashlib
        blob = bytes(struct.pack("<44H",
                                 *[self._u16(0x194 + 2 * i)
                                   for i in range(44)]))
        self.assertEqual(
            hashlib.sha1(blob).hexdigest(),
            "e1a8dd82c2b3a8062663990bc892da074cb46abf",
            "SWI handler table changed — re-derive the table pins (and "
            "the game.toml [[jump_table]] analog if one is seeded)")
        for i in range(43):
            t = self._u16(0x194 + 2 * i)
            self.assertLess(t, 0x4000,
                            f"SWI 0x{i:02X} target {t:#06x} out of image")

    def test_vc_irqh(self):
        # .vc_irqh at 0x3E74: emibios's own interim VBlank IRQ handler,
        # installed into [0x03007FFC] at runtime by boot_final_burn — the
        # statically-undiscoverable seed from the 2026-10-11 device-resume
        # harvest (game.toml extra_func of the same name).
        words = {0x3E74: 0xE3A03004, 0x3E78: 0xE1C130B2,
                 0x3E7C: 0xE3A03000, 0x3E80: 0xE1C130B8,
                 0x3E84: 0xE12FFF1E}
        for off, want in words.items():
            self.assertEqual(self._u32(off), want,
                             f".vc_irqh body word at {off:#06x}")

    def test_toml_seed_inventory(self):
        # The recompile TOML must keep the essential dispatch seeds — the
        # runtime-critical vectors, the trampoline epilogue, and the two
        # statically-undiscoverable fragments. Accidental deletion of any
        # one breaks strict-static on the next regen; this fails first,
        # with the name attached.
        text = self.TOML.read_text(encoding="utf-8")
        entries = {}
        for block in text.split("[[extra_func]]")[1:]:
            ma = re.search(r'addr\s*=\s*(0x[0-9A-Fa-f]+)', block)
            mn = re.search(r'name\s*=\s*"([^"]+)"', block)
            if ma and mn:
                entries[int(ma.group(1), 16)] = mn.group(1)
        for addr, name in ((0x00000000, "bios_reset_vector"),
                           (0x00000008, "bios_swi_vector"),
                           (0x00000018, "bios_irq_vector"),
                           (0x00000068, "exception_reset"),
                           (0x00000128, "exception_irq"),
                           (0x00000138, "after_interrupt"),
                           (0x00003E74, "vc_irqh")):
            self.assertEqual(
                entries.get(addr), name,
                f"bios/emibios_gba_bios.toml seed {name} @ {addr:#010x} "
                "missing or renamed — strict-static breaks on regen")


class RegenStampContractTests(unittest.TestCase):
    """The .regen_stamp contract spans three scripts (2026-10-11): build.py
    and tools/cycle.py stamp generated/ after a regen; build_apk.py's
    freshness gate reads it. Corpus mtimes cannot date a regen — the
    recompiler (commit_generated_file) preserves them for byte-identical
    output, so the pre-fix gate said 'stale' forever after a
    content-neutral game.toml touch. A rename in any one script breaks the
    other two silently; pin the token everywhere it appears, and keep the
    gate from ever comparing an emitted corpus file's own mtime again.
    """

    def test_stamp_writers_and_reader_agree(self):
        for script in ("build.py", "tools/cycle.py", "build_apk.py"):
            text = (REPO / script).read_text(encoding="utf-8")
            self.assertIn('".regen_stamp"', text,
                          "%s must use the .regen_stamp token — the "
                          "regen-date contract shared with build.py, "
                          "cycle.py and build_apk.py" % script)

    def test_freshness_inputs_are_regen_inputs_only(self):
        text = (REPO / "build_apk.py").read_text(encoding="utf-8")
        m = re.search(r"FRESHNESS_INPUTS = \((.*?)\)", text, re.S)
        self.assertTrue(m, "FRESHNESS_INPUTS missing from build_apk.py")
        self.assertNotIn("generated", m.group(1),
                         "FRESHNESS_INPUTS must not compare emitted corpus "
                         "mtimes (the recompiler preserves them for "
                         "byte-identical output — the 2026-10-11 lesson); "
                         "the .regen_stamp is the regen date")


class RomTruthTests(unittest.TestCase):
    """game.gba words pinned behind symbols/*.tsv rows (BRINGUP 2026-10-11).

    Every value here was read from the ROM during the Event-Editor /
    Engine-Hacks import and cross-checked against vanilla code. The pins
    exist so the two traps found then can never silently regress: the
    editor's EUR handler addresses (importing one breaks the table-hash
    and handler-membership tests) and the inherited 0x02000000 party base
    (moving gPartyUnits back breaks the literal pins). LOCAL-ONLY like
    BiosBytePinTests: skips without game.gba (CI included)."""

    ROM = REPO / "game.gba"
    SCENE_TABLE = 0x083A7EE4  # 115 entries x (u16 size, u32 thumb handler)
    COND_TABLE = 0x0836D5A4  # 17 entries x (u16 size, u32 thumb handler)

    @classmethod
    def setUpClass(cls):
        if not cls.ROM.exists():
            raise unittest.SkipTest("game.gba absent (local-only test)")
        cls.rom = cls.ROM.read_bytes()

    def _u16(self, addr):
        return struct.unpack_from("<H", self.rom, addr - 0x08000000)[0]

    def _u32(self, addr):
        return struct.unpack_from("<I", self.rom, addr - 0x08000000)[0]

    def _table_handlers(self, base, count):
        return {self._u32(base + i * 6 + 2) & ~1 for i in range(count)}

    def test_vm_dispatch_tables_hash(self):
        # Both opcode dispatch tables byte-for-byte (sizes + handlers).
        # Entry 0x72 of the scene table is garbage in-ROM; it is included
        # because the pin is over bytes, not semantics.
        import hashlib
        blob = (self.rom[0x3A7EE4:0x3A7EE4 + 115 * 6]
                + self.rom[0x36D5A4:0x36D5A4 + 17 * 6])
        self.assertEqual(
            hashlib.sha256(blob).hexdigest(),
            "91c1ce0d51b1882da5d6e3b3eb2edca7d520b7ab319e5baa33145bba4604686a",
            "event VM dispatch tables changed — every scene_*/cond_* row "
            "and gSceneOpcodeTable/gCondOpcodeTable is now suspect")

    def test_tsv_handlers_in_rom_tables(self):
        # Each scene_*/cond_* TSV row must name a handler the ROM tables
        # actually dispatch to (even entry address; table holds thumb +1).
        # An EUR address can never satisfy this.
        handlers = (self._table_handlers(self.SCENE_TABLE, 114)
                    | self._table_handlers(self.COND_TABLE, 17))
        rows = 0
        for line in (REPO / "symbols" / "ffta_symbols.tsv"
                     ).read_text().splitlines():
            if not line or line.startswith("#"):
                continue
            addr_s, _, name = line.split("\t")[:3]
            if not (name.startswith("scene_") or name.startswith("cond_")):
                continue
            if name == "scene_gfx_load":
                continue  # not a VM handler (scene-load pipeline, § 14)
            rows += 1
            self.assertIn(int(addr_s, 16), handlers,
                          f"{name} {addr_s} not a ROM table handler")
        self.assertGreater(rows, 100, "scene_/cond_ rows went missing?")

    def test_event_pointer_cells(self):
        # USA cells (the EUR cells at 0x08009AAC/0x08125ED0/0x0800A234 hold
        # region garbage — correctly excluded from the data symbols).
        cases = {0x08009A20: 0x08A19970,  # gEventListPtrCell
                 0x081223C0: 0x089A5D54,  # gSceneBanksPtrCell
                 0x0800A148: 0x08A1A908,  # gCondTypeListPtrCell
                 0x08009A88: 0x089C1484}  # gTextBankEnPtrCell
        for cell, target in cases.items():
            self.assertEqual(self._u32(cell), target,
                             f"pointer cell {cell:#010x}")

    def test_event_list_pad_bytes(self):
        # 234 x {script, scene, text, pad}; pad must be 0 (gEventList 0x3A8).
        for i in range(234):
            self.assertEqual(self.rom[0xA19970 + i * 4 + 3], 0,
                             f"event {i} pad byte")

    def test_party_base_literals(self):
        # The mission-end heal loop bases its 24x0x108 party walk at
        # 0x02000080 (never 0x02000000): pool words of 0x0802D824/0x0802D934.
        self.assertEqual(self._u32(0x0802D878), 0x02000080)
        self.assertEqual(self._u32(0x0802D9E4), 0x02000080)
        # Enemy loop base: 0x02000080 + 0x2F44 = gFirstEnemyUnit.
        self.assertEqual(self._u32(0x0802D9F8), 0x00002F44)
        # UnitStat dispatcher reads its table base from 0x080C7EBC, and
        # index-0 (name) reads struct+0x00 — the corrected framing.
        self.assertEqual(self._u32(0x080C7EBC), 0x080C7EC0)
        self.assertEqual(self._u16(0x080C7FD4), 0x6810, "ldr r0,[r2]")

    def test_swi_veneer_table(self):
        # 0x08141860+: (svc #N, bx lr) pairs; 0x0814186C = SWI 0x0B = CpuSet
        # (NOT CpuFastSet — the fill-mode bit24 calls prove it).
        for addr, svc in ((0x08141860, 0x0A), (0x08141864, 0x0E),
                          (0x08141868, 0x0C), (0x0814186C, 0x0B)):
            self.assertEqual(self._u16(addr), 0xDF00 | svc,
                             f"veneer {addr:#010x} svc imm")
            self.assertEqual(self._u16(addr + 2), 0x4770,
                             f"veneer {addr:#010x} bx lr")


if __name__ == "__main__":
    unittest.main(verbosity=1)


