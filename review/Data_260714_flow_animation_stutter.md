# Flow-animation stutter — raw measured data (2026-07-14)

Companion data file for the NOTES.md entry "App-start flow-animation stutter is TWO
mechanisms..." (2026-07-14) and the parent report
`review/Report_260714_synchronous_main_thread_work.md`. This file holds the actual numbers
so the NOTES prose can stay readable and the measurements survive independently of it.

**Method.** Temporary, DEBUG-gated, fully-removable `[STUTTER-PROBE]` instrumentation (since
reverted — `git diff` clean) on two animation paths:
- `ClickSlider.animate_to` / `_set_animated_value` (`ui/controls.py`) — the flow-animation glide
  (progress + chapter sliders). Logs per-frame wall-clock gaps; a smooth `QPropertyAnimation`
  ticks ~16ms, so a large gap = the main thread was blocked between frames.
- `library_panel_animation` (`ui/main_window_builders.py`, via a generic `valueChanged`/
  `stateChanged`/`finished` probe) — the panel slide.

All timings are wall-clock `perf_counter()` on the real app: 60 cold launches (10 × 3 book types ×
2 cover modes) via a scripted cold-relaunch harness, plus 12 deliberate live book-switches driven
manually by the developer (whose visual observations are recorded alongside and agreed with the
numbers). Test books: **The Sparrow** (embedded M4B), **Creature** (single MP3), **Doctor Zhivago**
(260-file VT). All three carried substantial saved progress, so the flow animation had a large
distance to travel (maximizing stutter visibility). "POOL" = `cover_art_theme_mode=with_pool`
(a cover-driven theme apply fires on load); "OFF" = `cover_art_theme_mode=off` (no theme apply).

---

## Cold launch — per-config summary (10 launches each)

`worst_gap` = largest single inter-frame gap during the flow animation (ms). `overrun` = wall-clock
duration minus the animation's nominal duration (ms). "apply-in-window" = how many of the 10
launches had a full `_apply_stylesheets` pass running *inside* the flow-animation's start→end window.

| Config           | n  | worst_gap median | worst_gap max | overrun median | #worst>60ms | #worst>150ms | apply-in-window | dev visual observation            |
|------------------|----|------------------|---------------|----------------|-------------|--------------|-----------------|-----------------------------------|
| MP3-single OFF   | 10 | 70.4ms           | 108.7ms       | +13.5ms        | 10          | 0            | 0/10            | 10/10 stutter (rough start)       |
| MP3-single POOL  | 10 | 74.5ms           | 82.7ms        | +14.4ms        | 9           | 0            | 0/10            | all 10 (same as OFF)              |
| M4B OFF          | 10 | 69.9ms           | 82.1ms        | +26.3ms        | 9           | 0            | 0/10            | ~half, less perceptible           |
| **M4B POOL**     | 10 | **594.6ms**      | **791.3ms**   | **+286.8ms**   | 10          | **10**       | **10/10**       | **worst so far, mid pause**       |
| VT OFF           | 10 | 76.3ms           | 84.0ms        | +66.5ms        | 10          | 0            | 0/10            | (light)                           |
| **VT POOL**      | 9  | **566.1ms**      | **577.4ms**   | **+531.5ms**   | 9           | **8**        | **8/9**         | **bad, mid-pause-then-flow; like the first batches** |

Two clean regimes, no overlap in magnitude:
- **Regime A** (all OFF configs + both MP3 configs): worst_gap ~70–76ms, overrun small, never
  >150ms, zero `_apply_stylesheets` in window.
- **Regime B** (M4B POOL, VT POOL): worst_gap ~560–595ms (max 791), overrun +287…+531ms, every
  launch >150ms, `_apply_stylesheets` in window on 10/10 and 8/9.

## Cold launch — offset from animate-START to theme-apply-BEGIN (POOL configs)

This is the "why is MP3 different" answer: the cover-theme apply fires at a different delay relative
to the animation per book type. Flow-animation nominal duration is ~380–423ms, so an offset below
that lands the ~400ms apply INSIDE the window.

| Config    | offsets animate_START → `_on_theme_changed GUARD` (ms, sorted) | median | verdict                    |
|-----------|----------------------------------------------------------------|--------|----------------------------|
| M4B-POOL  | 147, 150, 154, 184, 187, 188, 193, 202, 229, 263               | 188ms  | mid-anim → freeze (10/10)  |
| VT-POOL   | 67, 337, 349, 352, 368, 368, 369, 383, 385                     | 368ms  | late but still catches it  |
| MP3-POOL  | (no GUARD between animate START and END)                        | —      | apply fires AFTER the anim; window clean (0/10) |

## Cold launch — one fully-traced M4B-POOL launch (Regime B, the smoking gun)

```
17:29:27,492  overall_progress animate_to START 0->559 nominal_dur=423ms
17:29:27,538  overall_progress FRAME GAP=46.1ms val=0          ← Regime A start roughness
              (populate + repeated _update_chapter_label_from_index setCurrentRow at 27,493–27,504)
17:29:27,694  [_on_theme_changed GUARD] any_panel_animating=False   ← cover-theme apply begins (+200ms)
17:29:27,743  [mask-build slider-animation path] mask set
17:29:28,156  [_apply_stylesheets hover=False] total=412.6ms  mw.setStyleSheet(base)=228.9ms ...
17:29:28,226  [_on_theme_changed hover=False] pipeline=531.8ms
17:29:28,227  overall_progress FRAME GAP=599.5ms val=559        ← frozen 600ms, snapped to end
17:29:28,227  overall_progress animate_to END nominal=423ms wall=735.9ms overrun=+312.9ms frames=9 worst_gap=599.5ms
```

## Cold launch — one MP3-POOL launch (Regime A only; theme apply lands after)

```
17:27:49,297  overall_progress animate_to START 0->454 nominal_dur=381ms
17:27:49,629  overall_progress FRAME GAP=69.9ms val=448         ← Regime A only
17:27:49,694  overall_progress animate_to END nominal=381ms wall=396.6ms overrun=+15.6ms frames=22 worst_gap=69.9ms
              (the _on_theme_changed GUARD for this launch fires only AFTER this END)
```

## Cold launch — three `_apply_stylesheets` passes per POOL launch

An M4B-POOL cold launch fires `_apply_stylesheets` three times; only the third lands in the
animation window:

```
17:29:26,453  [_apply_stylesheets] total=112.6ms   ← #1: initial theme setup in __init__
17:29:26,494  [_on_theme_changed GUARD]            ← #2: cover-theme apply from _load_cover_art (in __init__, BEFORE anim)
17:29:26,852  [_apply_stylesheets] total=358.3ms
17:29:27,449  _on_file_ready: entry                ← flow animation starts here
17:29:27,694  [_on_theme_changed GUARD]            ← #3: a SECOND cover-theme apply, ~245ms after file-ready
17:29:28,156  [_apply_stylesheets] total=412.6ms   ← THIS one lands in the anim window (Regime B)
```
(The exact trigger of the third/second-cover apply after file-ready was not chased to ground — the
Regime B mechanism is proven regardless of which re-apply fires it. Flagged as a loose thread in
NOTES.md, not load-bearing for the conclusion.)

---

## Book-switch — manual, developer-driven (the faithful path)

**Important methodology note:** an earlier scripted driver that called
`_on_book_selected_from_library` directly was DISCARDED as unfaithful — it bypassed the real
library-panel-open → slide-out → `_on_library_hidden` → `ungate_play`/`_apply_pending_cover_theme`
sequencing that positions the theme apply on a real switch. The numbers below are from the
developer manually clicking book-to-book in the running app, cover-on then cover-off. Log rotated
mid-test; data reassembled from `fabulor.log.1` + `fabulor.log` by timestamp.

### Flow-animation on manual book-switches (window 20:31:30–20:41:00)

| time     | nominal | wall | overrun | worst_gap | note |
|----------|---------|------|---------|-----------|------|
| 20:32:02 | 436 | 461 | +25 | 35 | clean |
| 20:32:32 | 436 | 478 | +42 | 30 | clean |
| 20:33:32 | 430 | 443 | +13 | 27 | clean |
| 20:33:56 | 430 | 464 | +34 | 31 | clean |
| 20:34:06 | 336 | 339 | +3  | 19 | clean |
| 20:34:41 | 336 | 362 | +26 | 25 | clean |
| **20:35:19** | 381 | **727** | **+346** | **356** | **Regime B on book-switch — NOT a deliberate switch; theme apply cleared the panel guard just as the flow anim ran** |
| 20:35:26 | 302 | 313 | +11 | 24 | clean |
| 20:35:44 | 302 | 307 | +5  | 18 | clean |
| 20:35:53 | 302 | 314 | +12 | 26 | clean |
| 20:36:21 | 302 | 306 | +4  | 18 | clean |
| 20:37:25 | 381 | 429 | +48 | 61 | clean |
| 20:37:38 | 432 | 437 | +5  | 29 | clean |
| 20:38:04 | 432 | 477 | +45 | 61 | clean |
| 20:38:45 | 330 | 339 | +9  | 18 | clean |
| 20:39:05 | 330 | 372 | +42 | 52 | clean |
| 20:39:40 | 330 | 339 | +9  | 19 | clean |
| 20:39:48 | 302 | 325 | +23 | 36 | clean |
| 20:40:09 | 302 | 306 | +4  | 18 | clean |
| 20:40:30 | 302 | 325 | +23 | 36 | clean |
| 20:40:34 | 302 | 307 | +5  | 19 | clean |
| 20:40:38 | 242 | 304 | +62 | 64 | clean |
| 20:40:42 | 201 | 215 | +14 | 29 | clean |
| 20:40:46 | 342 | 358 | +16 | 20 | clean |
| 20:40:50 | 335 | 356 | +21 | 35 | clean |
| 20:40:53 | 233 | 242 | +9  | 18 | clean |
| 20:40:58 | 233 | 264 | +31 | 39 | clean |

Developer's 12 deliberate switches (cover-on then cover-off, both directions across all three type
pairs): **all clean by eye.** The only cover-on symptom was the known VT progress reset (Race 3),
not an animation stutter. Every deliberate switch's worst_gap is 18–64ms (Regime A only). The one
Regime-B row (20:35:19) is an incidental/extra switch, not one of the 12; its trace confirms
book-switch CAN hit Regime B when file-ready lands just after the panel-animation guard clears.

### The 20:35:19 Regime-B book-switch, traced

```
20:35:18,843  _on_book_selected_from_library: VT (Zhivago) -> MP3 (Creature)
20:35:18,868  [_on_theme_changed GUARD] any_panel_animating=True -> queuing deferred retry  ← guard defers theme apply
20:35:19,196  _on_file_ready: entry  ← flow animation starts
20:35:19,603  [_on_theme_changed GUARD] any_panel_animating=False   ← guard clears, apply fires
20:35:19,899  [_apply_stylesheets hover=False] total=293.4ms
20:35:19,951  overall_progress FRAME GAP=356.0ms val=454   ← flow anim froze 356ms
```

### Library-panel SLIDE on manual book-switches — 54 slides, rock-solid

Every slide (open and close, both cover modes): nominal 300ms, wall 302–355ms, frames 16,
**worst frame gap 17–19ms** — a clean ~16ms/frame, zero mid-slide freezes. Confirms the developer's
"no panel-slowness" observation. Even the 20:35:19 switch whose flow-anim froze had a clean slide
(wall 341ms, worst 17ms).

Reason slides never hit Regime B: the `_any_panel_animating` guard in `_on_theme_changed` defers
the theme apply until the slide finishes (`any_panel_animating=True -> queuing deferred retry`), so
the ~400ms apply is structurally prevented from running *during* a slide. Nothing defers it away
from the flow animation that starts right after the slide ends — hence flow-anim is exposed on
book-switch (rarely) and slides are not.

---

## Regime A — what the ~70ms baseline gap actually is

Present on every cold launch, every book type, cover on or off, with no `_apply_stylesheets` in the
window. The gap lands at animation start and coincides (per the M4B trace above, 27,493–27,504) with
synchronous main-thread work firing right as the animation begins: chapter-list `populate`, repeated
`_update_chapter_label_from_index setCurrentRow` calls, and the first mpv `time_pos` samples.
Magnitude ~70ms (≈4 dropped frames), never observed above 108.7ms. Real but sub-perceptible to mild
— a rough *start*, distinct from Regime B's mid-animation *freeze-then-snap*.
