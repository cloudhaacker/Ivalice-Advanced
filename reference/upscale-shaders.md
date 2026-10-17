# Upscale-shader study — pixel snapping, grids, and the >3× problem

Notes from the 2026-10-16 session that landed **Sharp scaling** and
**Pixel grid / Grid opacity** (fork `dbef4fe`). Sources are summarized and
attributed, not quoted (public-repo hygiene); every external claim links the
primary source.

## Why scales above ~3× look bad

Two mechanisms, both confirmed by the sources below:

1. **Nearest-neighbour at a fractional scale** makes game-pixel widths
   alternate (at 6.75×, pixels alternate 7-6-7-6 drawable px). Dither
   patterns — which FFTA uses heavily — crawl and shimmer because the
   pattern's duty cycle is no longer uniform.
2. **Plain bilinear everywhere** blurs uniformly. Soft, but consistent.

The quantified crossover (dosbox-staging issue #2448, "Kill pixel-perfect
mode with fire"): the interpolation band of a *sharp-bilinear*-style scaler
is ~1 output pixel per game-pixel boundary — a `1/scale` fraction of each
pixel. Below ~3–3.5× that band is a third of a pixel and visibly "dirty";
above it, invisible. That thread also argues (persuasively) that
always-integer "pixel-perfect" modes sacrifice aspect correctness and
produce semi-random pixel aspect ratios while resizing — the wrong trade
for a windowed PC game. Middle ground: **snap ONE axis** (they use
vertical) to integer and let the other axis ride a tamed bilinear.

## The recipes

| Recipe | Mechanics | Notes |
|---|---|---|
| **Integer prescale + bilinear finish** ("sharp-bilinear"; TheMaister/ rsn8887, libretro `interpolation/sharp-bilinear*`; DOSBox Staging's default `sharp`) | Prescale by `floor(scale)` into a texture, then scale the remaining fraction with (tamed) bilinear | What our Sharp scaling toggle now does. The libretro shader's texel-clamp math (`region_range = 0.5 − 0.5/scale`) lets the *hardware* bilinear sampler do the prescale without sampling neighbors; our path uses a real RT, so the finish is plain bilinear on prescaled texels — same result, simpler. |
| **MMPX** (McGuire & Gagiu, JCGT 2021; mmpx.glsl in libretro, mgba) | EPX-derived rule set, exactly 2×; preserves palette exactly, rebuilds diagonals/corners | Stackable to even scales (2/4/8), then any remainder. ~0.5 ms/frame on GPU. Best general default for style preservation. |
| **xBR / xBRZ** (Hyllian / Zenju) | Pattern-matching bilateral filter | Integer 2–6× only; self-stacking invalid (per the Stasik & Balcerek 2019 study in *Future Computing and Data Science* — "Extensible Implementation of Reliable Pixel Art Interpolation"). Heavy. |
| **ScaleFX / ScaleFX+rAA** (Sp00kyFox, libretro) | 5-pass edge interpolation up to level-6 stairs; only original colors | 3× base, stackable to 9× at full speed. Built for pixel art, ambiguous-junction disambiguation is the core idea. |
| **EPX / Scale2x** (Johnston 1992 / Mazzoleni) | The 5-rule corner filter | Trivially cheap, rounds everything; best for LucasArts-era bubbly content. |
| **p-lin + TAR** (Stasik & Balcerek 2019) | Proximity-corrected linear kernel + transition-area restriction | Any ratio, sharp corners, consistent look; ~15 % over bilinear. The academic answer to "any scale, no artifacts". |
| **Cifaldi split** (via 30fps.net's write-up) | Vertical integer NN + horizontal linear | CRT-flavored horizontal softness; for GBA's square pixels and 3:2 aspect, less applicable than for 320×200 DOS content. |

MMPX paper's decision tree (summarized): EPX for rounded-corner content;
base xBR for corners+lines; HQx/AA-xBR for large palettes and gradients
(introduces colors); MMPX as the general default. Edge-directed filters do
NOT address fractional window scales at all — the prescale+remainder path is
the one that does, which is why Sharp scaling landed first.

## Pixel grids (LCD overlays)

- **LADXHD "PixelGrid"** (gitlab `bighead.0/ladxhd_updated`; source
  recovered from its vcdiff asset patch — MonoGame GLSL effects embed
  readable source in the XNB): `gridUV = uv * TextureSize + Offset; cell =
  frac(gridUV); fw = fwidth(gridUV); line = step(cell, fw) +
  step(1 − cell, fw)` — a 1-screen-px black line on every game-pixel
  boundary at any scale, opacity-lerped. Applied on render-target *blits*
  only, gated `PixelSnapping && PixelGrid && scale >= 2`. Their Android
  build patches `precision highp` into the compiled shader post-build
  (`ShaderPatch.cs`) — mediump broke fwidth grids on mobile GPUs.
- **libretro handheld family** (`zfast_lcd`, `lcd-grid-v2`, `simpletex_lcd`,
  mGBA's `ags001`/`lcd.shader`): the same wall — grid alignment is a
  function of where game pixels land — solved with game-anchored
  coordinates + sub-pixel offset uniforms + scale gates. `simpletex_lcd`'s
  line weighting `y = 48·(x⁴ − (8/3)·x⁶)` over cell-normalized distance is
  the nicest single-formula grid of the family.
- **Ours** (`gbarecompx/src/runtime/lcd_shader.h`): the RGB-triad grille
  (Shadertoy ldBfDd lineage) was already game-grid-anchored via
  `PresentGrid` (origin + per-axis drawable-px-per-game-px). The 2026-10-16
  port added the LADXHD border as a second mask on the same program
  (`uMaskMode` 0/1/2), with AA'd 1px lines (their hard `step()` shimmers
  under fractional scales) and the same `>= 2` gate.

## LADXHD's pixel-snapping architecture (worth stealing wholesale someday)

Their chain (MonoGame `Camera.cs`/`Game1.cs` in the repo):

1. Camera position quantized in **game-pixel units** when snapping is on
   (`Round((Location + shake·Scale)/Scale)·Scale`), screen shake rounded
   before folding in.
2. Auto-scale computes the fractional ideal, then renders at
   **`ceil(scale)`** into a proportionally larger render target
   (`_scaleMultiplier = ceil(scale)/scale`) — all fractional error
   concentrated into ONE final resample. This is the same shape as our
   sharp prescale, but chosen automatically.
3. The grid shader's offset is **derived from the same camera math** as the
   transform (`((−tx) mod Scale)/Scale`), so grid and world can never
   disagree.
4. Parallax layers snap only their own movement to an exact integer cadence
   (`snapped − round(snapped·(1−factor))`) — smooth sub-pixel relationships
   between layers without breaking the grid.

## What landed here (2026-10-16; sharp verified 2026-10-17)

- **Sharp scaling** toggle: prescale integer factor → RT (bilinear-filtered
  target), plain bilinear finish. POINT→BILINEAR change is the whole >3×
  fix; see the finish comment in `raylib_backend.cpp`
  (`ensure_sharp_target`).
- **Sharp scaling verified at the pixels (2026-10-17)**, after the user's
  "does nothing, even at scale 8" challenge: the GL present test now
  reads the REAL framebuffer (`LoadImageFromScreen`) — at a fractional
  layout (700×500 → units 233, factor 2) sharp off/on differ (>5% of
  layout pixels); at the exact 2× control they are pixel-identical. The
  inertness at exact scales is the recipe's DESIGN (rsn8887/TheMaister:
  automatic integer prescale + bilinear remainder — at a whole multiple
  there is nothing to even out), and the DEFAULT window (960×480 → 3×)
  plus every `--scale N` sit exactly there. It engages whenever the 3:2
  fit is not a whole multiple (any 16:9 window → 6.75×, the phone's
  case). The menu's status line now says "Sharp scaling: inert at exact
  scale" when it would be a no-op.
- **Pixel grid** + **Grid opacity** toggles: LADXHD border on the shared
  LCD program, `lcd_border`/`lcd_grid_alpha` in `[video]`.
- Not landed (candidates, in order of cost): MMPX 2× pre-pass before the
  prescale (even-scale quality tier); ScaleFX-style multi-pass edge
  interpolation (needs multi-pass plumbing); one-axis-integer snapping
  (dosbox-staging's `integer_scaling = vertical` shape) if a windowed
  aspect-correctness debate ever comes up.

## MMPX work plan (investigated 2026-10-16; landed the same day)

The plan below was executed within the day: the fork's
`src/runtime/mmpx.{h,cpp}` + GLSL, the "Edge smoothing" toggle, and the
differential oracle. Kept for the shape of the investigation.

Feasibility: **clean** — the engine already has every primitive (multi-pass
present chain, RT lifecycle, FxSettings→menu→`[video]` persistence,
glslangValidator dev-time validation, ES 1.00 dual-dialect pattern).

**Reference material (all MIT, all in hand):**
- C99 reference: `ITotalJustice/mmpx` `mmpx.c` — 186 lines, the complete
  rule cascade (McGuire & Gagiu copyright header, MIT). Local copy at
  `/tmp/opencode/mmpx_ref.c` at investigation time.
- Fragment-shader precedent: libretro `edge-smoothing/scalenx/shaders/
  mmpx.slang` (hunterk's adaptation, MIT header, 303 lines) — proves the
  fragment form; do not copy (dialect differs, attribution hygiene).
- Paper: JCGT 0010/02/04 (open access) — the rule definitions + the
  font-sheet guidance (dark-foreground ambiguity bias).

**Algorithm shape (from the C99):** each source pixel → 4 output quadrant
pixels (J/K/L/M). Inputs: 3×3 neighborhood (A..I) + 2-away probes (P,Q,R,S)
+ occasional ±3 probes in the intersection rules — ≤17 taps, worst case.
Exact RGB equality tests (FFTA: opaque RGB888, byte-exact in float — no
threshold needed); luma with a dark-foreground bias for ambiguous corners;
`src()` clamps out-of-range taps to the border. Output = always SOME source
pixel's value (palette-exact, no blends).

**Design in our engine:**
- New pure header `gbarecompx/src/runtime/mmpx.h` (the lcd_shader.h
  pattern): the CPU mirror of the cascade + both GLSL sources (GLSL330
  desktop with `texelFetch` for byte-exact taps; ES 1.00 Android with
  `texture2D` at `(floor(coord)+0.5)/size` — highp is exact at 8-bit
  values; ES 1.00 has no uint bitwise ops, so equality = chained `==`).
- **Tap clamping in-shader** (manual UV clamp), NOT sampler wrap: the game
  texture's wrap state is raylib's default REPEAT (only the filter is ever
  set) — a repeat tap at the top row wraps to the bottom row and corrupts
  every rule at image edges. (Side observation: the deband pass has the
  same latent issue today — default-off, unnoticed; fix it there too when
  touched.)
- Pass placement: FIRST in the present chain, before the sharp prescale —
  MMPX changes *what* is scaled (reconstructed art), sharp/finish change
  *how*. Verified with the production layout function: the prescale factor
  against the doubled dims is just
  `compute_sharp_prescale_factor(layout, base_w*2, base_h*2)` — at the
  phone's 6.75× it yields 3 (RT 1920×960 = identical size to today's 6×
  logical; same 1.125 remainder). Exact scales: both inert (integer_scale>0
  → 0) and the POINT blit of the MMPX tex at exact 2×-per-MMPX-texel is
  already perfect. No new math.
- RT lifecycle: `ensure_mmpx_target`/`release` keyed on base dims ×2 like
  `ensure_sharp_target`; POINT-filtered (its output must be sampled
  nearest downstream).
- Stage/rect bookkeeping: the existing stage chain already handles "stage
  ≠ game texture" (the sharp target case) — MMPX just reassigns
  `stage_tex`/`stage_rect` before the sharp block. Deband's 1/game-px
  texel step spans exactly 2 MMPX texels (the property its comment already
  documents for the sharp target) ✓; dither/LCD index by `gl_FragCoord` in
  game space — texel-density-agnostic ✓.
- Settings: `FxSettings::edge_smoothing` (bool), menu row **"Edge
  smoothing"** in Graphics gated `caps.shaders` (row count 19→20; no-
  shaders stays 13), `[video]` key `edge_smoothing` in the merge family,
  `Bind::EdgeSmoothing`, `HostWindow::set_edge_smoothing` (+ stub), boot
  apply after the sharp filter apply. No CLI flag (menu+config only).
- **MMPX without sharp at a fractional layout repeats the uneven-column
  artifact at 2× scale** — allowed, documented ("pairs with Sharp
  scaling"); no coercion, the user drives.

**Test plan (red-first):**
1. `mmpx_test.cpp`: **differential testing against the vendored MIT C99
   reference** (test-only copy under `tests/`, attributed, never shipped):
   random noise + structured patterns, our CPU mirror must match the
   reference byte-for-byte (this is the strongest transcription-bug net).
   Plus hand-derived pins of the canonical patterns: flat region → nearest
   passthrough; 1px-thin line stays 1px; sharp corner reconstruction;
   diagonal continuation; isolated dark pixel wins its corners (the luma
   rule).
2. Fake-api present pins: MMPX pass allocates the 2× RT, engages at ≥2×
   display, inert below; uniform (texel size) uploaded; readback stays
   pre-shader (attract-hash contract).
3. glslangValidator both dialects at dev time (the existing six-source
   validation pattern — manual, not CI-wired).
4. `menu_settings` round-trip for `edge_smoothing`; `host_menu` row counts.

**Effort estimate:** ~1000 lines incl. tests (mmpx.h ~350, backend ~120,
settings stack ~80, vendored ref 186, tests ~300). One focused session —
comparable to the two-toggle landing this came from — plus a desktop/phone
visual A/B. Perf: ≤17 taps × 150k fragments ≈ trivial on desktop and the
Adreno 740 (the LCD pass already runs there).

**Risks:** rule transcription (mitigated by differential testing); tap
edge semantics (in-shader clamp, matched to the reference's `src()`);
ES 1.00 precision (highp + half-texel convention; byte-exact at 8-bit);
the style question itself is the user's call (visible change, unlike sharp
on the phone).
