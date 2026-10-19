# Fast-forward and speed

Fast-forward runs the emulated game faster than normal play. It is inert
until you ask for it, and the selected speed is saved for later sessions.

## Quick reference

| Action | Desktop | Controller | Android / touch |
|---|---|---|---|
| Fast-forward while held | `Tab` (or `2`) | right trigger | — |
| Latch fast-forward | touchscreen: tap the `FF` pill | — | tap the `FF` pill |
| Open the settings menu | `Del` | Guide button | long-press, three-finger tap, or system Back |
| Change the speed | **Assist → Fast-forward speed** | same menu | same menu |

`2` is the default Assist fast-forward key; `Tab` is the separate Turbo
binding. Both are hold-to-run. The `FF` pill is the touch latch: tap once to
turn fast-forward on and again to turn it off.

## Set the speed

1. Open the in-game menu (`Del`, Guide, or the Android gesture above).
2. Open the **Assist** section.
3. Select **Fast-forward speed**.
4. Use Left/Right (D-Pad/arrows or controller) to choose **2x–10x**.
5. Resume the game. The change applies immediately.

The default is **4x**. The value is persisted as
`fast_forward_multiplier` under `[Menu]` in `config.ini`, so it survives a
restart. On the desktop zip the file is beside the executable; for the
Steam Deck AppImage it is inside the unpacked app folder described in the
[README](../README.md#quick-start).

The same speed applies to every fast-forward source: the keyboard hold, the
controller trigger, and the touch latch.

## What to expect

- The multiplier is a **target**, not a guarantee: at 10x a slow host CPU
  can still fall short.
- Fast-forward decimates presentation: the game runs several emulated frames
  per displayed frame, so motion looks choppy while active. Normal play is
  unchanged.
- Audio output is muted during fast-forward; it resumes when you stop.
- Frame interpolation is suspended while fast-forwarding (the frames are
  presented as-is).
- The touch `FF` pill is session-only. It clears when the app is suspended,
  backgrounded, or relaunched rather than waking up boosted.
- On desktop the `FF` pill appears after touch activity and hides after
  about 15 seconds without touch. On Android it is visible from boot.
- Fast-forward requires the engine's Assist feature to be enabled; it is on
  by default.

## Troubleshooting

- **Speed changes but nothing gets faster** — the speed only affects
  fast-forward. Hold `Tab`/`2`/right trigger, or tap the `FF` pill.
- **The holds do nothing** — check that Assist Tools were not disabled with
  `[Launcher] assist_tools = 0` in `config.ini`; set it to `1` and restart.
- **The touch pill is missing** — on desktop, touch the screen once to reveal
  it; it hides after the idle timeout. On Android it starts visible.
- **The latch turned itself off** — that is intentional after a suspend or
  background interruption. Tap the pill again after resuming.
- **Audio is silent while fast-forwarding** — expected; it returns when
  fast-forward ends.
- **The game is not reaching the chosen multiplier** — the multiplier is a
  target and the host may be CPU/GPU-bound. Lower it if needed.
- **The setting was not remembered** — the menu writes `[Menu]` in the
  `config.ini` beside the executable (AppImage: the unpacked app folder;
  Android: the app's files directory, so use the menu there). Make sure the
  folder is writable.
