# Investigation: theme fade animation latency — interrupt-clear vs. animation-start

**Date:** 2026-08-04  **Branch:** `investigate/restyle-cost-depth-and-narrowing`

## Context

Pryme's observation, predating this week's snapback-blocking sequencing fix (reverted this
session, see below): stopping an in-flight fade animation doesn't clear it promptly, and starting
a new one carries its own ~500ms-ish latency regardless of configured duration. If true, any
sequencing fix built on "stop() and start() take effect immediately" is unsound — this had to be
measured directly, live, before attempting any further sequencing fix.

## Preliminary step: revert

The Esc/gutter-dismiss snapback-blocking fix (`2abeab5` code, `9650a1f` docs — see
`review/Design_260804_snapback_timing.md`) was reverted via `git revert --no-commit 9650a1f
2abeab5`, committed as `0396f5b`. `git diff HEAD 9a82954` (the pre-fix commit) came back empty —
byte-for-byte identical. `pytest tests/ -q` confirmed 453 tests collected, full pass, exit 0,
matching the documented pre-fix baseline exactly.

## Methodology

New harness: `tools/animation_latency_probe.py`. Drives the real `ThemeManager._on_theme_changed`
entry point against a live, on-screen `MainWindow` (not offscreen) — the same real call path
`snap_theme_forward()`/a hover-out/a genuine selection all use.

Real paint evidence, not call-return timing or animation `state()` alone:
- **Interrupt-clear**: hook `QGraphicsOpacityEffect.draw()` (the actual composition call Qt makes
  every time the fade overlay's effect paints a frame), filtered to the specific `tm._fade_effect`
  instance. Start a long (3000ms) fade, let it run 150ms, call `.stop()` (the same call
  `snap_theme_forward()` makes), then watch for up to 1000ms of further real paints whose opacity
  differs from the stop-moment value by more than a 0.02 epsilon (clear of float/idle-repaint
  noise).
- **Animation-start**: trigger `_on_theme_changed(..., fade_ms=X)` for X in {0, 200, 1500} from a
  clean, fully-settled state, and find the first real paint showing the animation genuinely
  progressing (opacity < 1.0, i.e. the animation clock has ticked at least once — not just the
  static starting frame painted synchronously during `_apply_stylesheets`, before `.start()` is
  even reached).

Two measurement-harness bugs were found and fixed during this investigation, both material to the
result — recorded because either one alone would have produced a wrong answer:

1. **`QGraphicsOpacityEffect.draw` was patched at the class level**, so `paint_log` initially
   conflated the fade overlay's own effect with every other `QGraphicsOpacityEffect` instance in
   the running app (sliders, other panels). An early run's "stray paints after stop()" showed two
   interleaved near-1.0 value series — exactly what conflating two different effects' opacity
   looks like. Fixed by filtering to `self is effect` (the specific `tm._fade_effect` instance).
2. **Triggering immediately after opening Settings raced the panel's own 1500ms blur-in
   animation.** `_on_theme_changed`'s `_any_animating` guard (`theme_manager.py` ~1085) treats
   `blur_animation.state() == Running` as "a panel animation is in flight" and defers the whole
   call via `call_when_panels_settled` until it clears — a real, already-documented mechanism in
   this codebase (`panels.py` ~1189: "the first hover after opening Settings took ~2.1s to preview,
   every time"). An early harness version triggered right after a `pump(400)` open, while the
   blur-in was still running, and measured "how much of the blur-in settle window was left"
   (~950ms) instead of animation-start latency. Fixed by waiting for
   `not panel_manager._any_panel_animating()` before triggering — isolating the mechanism under
   test from this different, already-understood one.

A third, more minor fix: a tight Python loop of `pump(5)`-per-iteration (each constructing and
tearing down its own `QEventLoop`) was found to itself distort Qt's unified animation timer —
one such trace showed the fade frozen at a stale, unrelated opacity value for ~950ms before ever
moving, which did not match reality once measured with a single continuous `QEventLoop` +
interval `QTimer` sampler instead (the correct way to observe an animation without perturbing it).

## Results

Raw, chronological, 5 trials each (no sorting — per this project's own measurement discipline,
sorting is only valid for i.i.d. samples and would hide a first-call-in-process effect if one
existed):

**Interrupt-clear latency (ms):** `0.0, 0.0, 0.0, 0.0, 0.0`

**Animation-start latency (ms), by configured duration:**
| Configured duration | Trial 1 | Trial 2 | Trial 3 | Trial 4 | Trial 5 | Range |
|---|---|---|---|---|---|---|
| 0ms   | 703.8 | 688.7 | 676.4 | 707.5 | 678.8 | 676–708 |
| 200ms | 757.7 | 750.6 | 762.0 | 745.6 | 741.9 | 742–762 |
| 1500ms| 735.9 | 733.9 | 740.5 | 759.3 | 739.6 | 734–759 |

(A second independent run produced the same pattern: 674–691ms / 756–792ms / 750–808ms.)

## Findings

**Half of Pryme's observation is NOT confirmed: interrupting is genuinely instant.**
`QPropertyAnimation.stop()` clears the fade overlay immediately — 0.0ms of lingering old-animation
paint across every trial, once the harness's own effect-conflation bug was fixed. There is no
stale-animation-lingers problem to design around.

**The other half is confirmed exactly as described, and its source is fully identified.**
Animation-start latency clusters in the same ~680–810ms band regardless of configured duration —
0ms, 200ms, and 1500ms all cost essentially the same to *start*. This is not a mysterious Qt
scheduling overhead: it is `_apply_stylesheets`'s own already-documented synchronous cost
(CLAUDE.md: "~430–440ms live" baseline, "~590–620ms live" while a panel/Themes tab is open — this
harness's numbers, measured with Settings genuinely open and settled, land at the higher end of
and somewhat above that documented range, consistent with it plus this harness's own event-loop
overhead).

The mechanism is exactly what reading `_on_theme_changed`'s themes-tab-active branch predicts
(`theme_manager.py` ~1375–1420): `_apply_stylesheets(theme_name, hover=hover)` runs **synchronously
first**, and only once it returns does `self._fade_anim.start()` get called. So "starting an
animation" is never actually a cheap, fast operation on this codebase's critical path — every
animation start is gated behind a full synchronous restyle pass first. The animation itself, once
started, then runs and completes in genuinely close to its configured duration (confirmed by the
`200ms`-configured trial's own poll trace: opacity dropped smoothly from 1.0 to 0.0 over ~200–220ms
of `currentTime()`, immediately after the `_apply_stylesheets` block returned).

## Consequence for any future sequencing fix

**"Stop X and start Y take effect immediately" is unsound for the START half, sound for the STOP
half.** A sequencing fix that assumes a fresh animation begins compositing within a few
milliseconds of being triggered will be wrong by ~700ms — indistinguishable, from the user's
perspective, from the animation simply not having started yet. Any future fix in this area needs
to either (a) tolerate/design around this ~700ms pre-animation delay explicitly, or (b) attack the
underlying `_apply_stylesheets` cost directly (already an open, separately-tracked cost in this
branch's own investigation — see CLAUDE.md's `_apply_stylesheets` sections) since that is the
actual root of this latency, not a separate animation-subsystem problem.

No sequencing fix is proposed in this pass, per the task's explicit scope — this is measurement
and root-cause identification only.
