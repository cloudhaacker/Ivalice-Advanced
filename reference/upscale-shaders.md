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

## What landed here (2026-10-16)

- **Sharp scaling** toggle: prescale integer factor → RT (bilinear-filtered
  target), plain bilinear finish. POINT→BILINEAR change is the whole >3×
  fix; see the finish comment in `raylib_backend.cpp`
  (`ensure_sharp_target`).
- **Pixel grid** + **Grid opacity** toggles: LADXHD border on the shared
  LCD program, `lcd_border`/`lcd_grid_alpha` in `[video]`.
- Not landed (candidates, in order of cost): MMPX 2× pre-pass before the
  prescale (even-scale quality tier); ScaleFX-style multi-pass edge
  interpolation (needs multi-pass plumbing); one-axis-integer snapping
  (dosbox-staging's `integer_scaling = vertical` shape) if a windowed
  aspect-correctness debate ever comes up.
