# Investigation: a real gutter-wait snapback failure, and why the harness never found it

**Date:** 2026-08-02  **Branch:** `investigate/restyle-cost-depth-and-narrowing`  **Status:**
Root cause found and precisely traced from a real session log, cross-referenced against a
screen recording. No fix implemented — investigation only. Distinct bug from, and unrelated to,
`review/Investigation_260802_double_fire_reentrancy.md`'s stash-drain/fallback mechanism —
that document's mechanism never applies here (see "Why the double-fire investigation is a red
herring for this bug" below).

## The reported symptom

Pryme hovered `Fire and Blood` in the Themes tab, then moved the cursor away from the swatch grid
into the gutter (the dismiss sliver) and held it there, static, for ~7 seconds before clicking to
dismiss Settings — confirmed via a screen recording showing the `Fire and Blood` cover-art label
still visible/active the entire wait. The preview never snapped back to the active theme
(`Goldfinch`) during that wait. Around the click, the correct theme did eventually show — but not
via a proper snapback fade; see below.

## Log correlation (2026-08-02, `~/.local/state/fabulor/log/fabulor.log`, 23:29:xx window)

Sequence, in order:

1. **23:29:45,038** — `ThemeItem.enterEvent PASSED theme_name='Fire and Blood' pos=(254, 259)`.
   `_on_theme_hovered` records `self._last_swatch_pos = QCursor.pos()` = `(254, 259)`
   (`theme_manager.py:1926`).
2. **23:29:45,122** — the 80ms debounce fires; `Fire and Blood`'s preview applies for real
   (`fade_ms=375`, hover=True).
3. **23:29:46,106** (same millisecond, both lines) —
   - `ThemeItem.leaveEvent theme_name='Fire and Blood' pos=(254, 259)` (title_bar.py)
   - `[SWATCH-LEAVE] suppressed leave — visible but cursor unmoved (0px <= 2) at (254, 259)`
     (`_on_themes_tab_left`, theme_manager.py:2083-2088)

   **This is the whole bug in one pair of lines.** The reported leave position is identical,
   pixel-for-pixel, to the recorded enter position. `_on_themes_tab_left`'s jitter guard
   (`_MOUSE_JITTER_PX = 2`) treats a leave reported within 2px of the last enter as a
   stylesheet-cascade artifact — not a real departure — and returns without calling
   `_on_theme_unhovered()`. **No snapback is issued.**
4. Nothing else touches this hover state for the next ~6 seconds while Pryme's cursor sits in the
   gutter. The mechanism is purely event-driven: nothing re-samples cursor position or re-checks
   whether the (justifiably or not) suppressed leave was actually real. If the one delivered
   `leaveEvent` is swallowed, there is no second chance.
5. **23:29:52,255** — `[BLEED-TRACE] _on_theme_changed theme_name='Goldfinch' hover=False
   bypass_panel_open_guard=True fade_in_flight=False` — a **direct, non-hover** theme-changed call,
   NOT a snapback via `_on_theme_unhovered`. This is most likely the click's own theme-restoring
   side effect (not traced further in this pass — the point already made is that the ordinary
   snapback path never ran). It takes the themes-tab-visible fade branch and starts a fresh 200ms
   fade — but the pipeline's own synchronous restyle work took 718ms before the animation clock
   even started (`fade_anim.start() at +718.2ms (after restyle) fade_ms=200`, confirmed in the same
   log — see "A second, unrelated finding" below).

## Root cause: the boundary-crossing case the 2px jitter guard cannot distinguish

`_on_themes_tab_left`'s jitter check (`theme_manager.py:2080-2088`) exists to protect against a
genuinely different failure: a leave event delivered while the cursor hasn't moved at all (a
stylesheet-repaint artifact). Its own docstring (lines 2041-2046) frames this explicitly as "a leave
delivered while VISIBLE with the cursor unmoved," anchored against the **last genuine ENTER**
position, and states the design reasoning that a real mouse-out always moves the cursor measurably
between enter and leave.

**That premise is false at a widget boundary.** `Fire and Blood`'s swatch sits at (or very near) the
edge of `swatch_box` itself. Leaving the swatch by crossing directly into the adjacent gutter can
cross both the swatch's own boundary AND `swatch_box`'s outer boundary at nearly the same pixel —
so `ThemeItem.leaveEvent` and `swatch_box.leaveEvent` (`_on_themes_tab_left`) can both fire in the
same event-loop tick, at a position that is, by construction, within a few pixels of the swatch's
own enter position — not because the cursor didn't move, but because the boundary crossing itself
is small relative to the 2px tolerance. The two log lines above are timestamped to the same
millisecond, which rules out the "stale/delayed cursor sample" theory this investigation initially
suspected — the position genuinely was `(254, 259)` at both firings; it's a real edge-crossing
distance problem, not a synthetic-event or staleness problem.

**Consequence:** a real, deliberate mouse-out that happens to cross a widget boundary at a shallow
angle or short distance is swallowed exactly like the synthetic case the guard was built for. Since
there is no periodic re-check — this is purely reactive to the one `leaveEvent` Qt delivers — a
single false suppression here strands the hover state until some unrelated event (in this session,
apparently the eventual click) forces a theme re-application through a different path entirely.

## A second, unrelated finding surfaced in the same trace: the fade's own pipeline eats its budget

Independent of the suppression bug, the `Goldfinch` theme-change at 23:29:52,255 shows
`[_apply_stylesheets hover=False] total=684.5ms ... [_on_theme_changed hover=False] pipeline=718.3ms
fade_anim.start() at +718.2ms (after restyle) fade_ms=200`. The synchronous restyle block that MUST
run before `_fade_anim.start()` (`theme_manager.py:1168-1170`, `_apply_stylesheets` then
`.start()`) took 684.5ms on its own here — well over 3x the fade's own 200ms nominal duration.
This means: even when a snapback fade DOES get correctly triggered, on this machine under this
load, most of its wall-clock life can be spent in the pre-animation synchronous restyle, not the
animated fade itself. This is a real, measured data point (not new — CLAUDE.md's `_apply_stylesheets`
cost investigation already covers the general cost, ~430-620ms live depending on panel-open state)
but concretely confirms the two effects compound: a fade "starting" doesn't mean the animation clock
started anywhere near instantly.

## Why the double-fire/stash-drain investigation is a red herring for this bug

`review/Investigation_260802_double_fire_reentrancy.md` traced a real, separate mechanism —
`snap_theme_forward`'s stash-drain path firing when `_on_theme_unhovered()` is called TWICE in
quick succession while a fade is in flight. **That mechanism requires `_on_theme_unhovered()` to
have been called at least once to begin with.** In this session's actual bug, `_on_theme_unhovered()`
was never called at all — the jitter guard in `_on_themes_tab_left` returned before ever reaching
it. The two investigations are about genuinely different code paths reached under genuinely
different conditions; neither explains the other, and the harness built for the double-fire
investigation cannot reproduce this bug because it drives `_on_theme_unhovered()` directly rather
than through the real `swatch_box.leaveEvent` → `_on_themes_tab_left` → jitter-check → (maybe)
`_on_theme_unhovered()` chain.

## Second, independent repro (same session, ~14 minutes later) — confirms the pattern

Pryme reproduced it again deliberately: hovered `Fire and Blood` (active theme `Rivendell` this
time — confirmed against the screenshot, swatch underlined), "edged it slowly" toward the gutter,
held there, then dismissed. Log (`23:42:4x`-`23:43:2x` window):

- **23:42:47,854** — `ThemeItem.leaveEvent theme_name='Fire and Blood' pos=(255, 249)` and, same
  millisecond, `[SWATCH-LEAVE] suppressed leave — visible but cursor unmoved (2px <= 2) at
  (255, 249)`. Same mechanism as the first repro: reported leave position within the jitter
  tolerance of the last recorded enter, genuine departure swallowed.
- **Nothing else touches the theme system for the next ~33 seconds** — no further hover, no
  `_on_theme_unhovered`, no snapback fade, confirmed by grepping the full window for every
  theme-related trace line between 23:42:48,241 and 23:43:21,268 and finding zero.
- **23:43:21,268** — a **direct, non-hover** `_on_theme_changed(theme_name='Rivendell', hover=False,
  bypass_panel_open_guard=True, fade_in_flight=False)` fires — not preceded by any
  `_on_theme_unhovered()` call or `[SWATCH-LEAVE] genuine leave` line. This is the dismiss action
  itself forcing the theme back.
- **23:43:22,570** — `transport_bar_blur`'s `hide_for_panel ENTRY active_panel='settings_panel'`
  confirms the Settings panel genuinely began closing ~1.3s after that theme-change call started
  (consistent with the ~600-700ms synchronous restyle pipeline measured throughout this session
  delaying the panel-close sequence, same effect as the "second, unrelated finding" above).

This is the "fallback fires" Pryme described: the correct theme (`Rivendell`) IS eventually shown,
but via a direct forced re-apply triggered by the dismiss action, not via the snapback fade that
should have run the instant the cursor left `Fire and Blood`. Two independent repros, two different
swatch/active-theme pairs (`Fire and Blood`→`Goldfinch` and `Fire and Blood`→`Rivendell`), same exact
suppression signature (`leaveEvent` position identical or within 2px of the recorded enter position,
same millisecond as the suppression log line) — this is a repeatable mechanism, not a one-off fluke.

## Why no harness reproduced this

Every batch of the `snapback_dismiss_harness.py` sweep calls `tm._on_theme_unhovered()` directly
(see `hover_swatch`/`do_trial` in `tools/snapback_dismiss_harness.py`), deliberately bypassing
`_on_themes_tab_left`'s jitter guard entirely, per that harness's own design goal (exercising the
*real signal path* for hover/dismiss, which at the time was understood to start at
`_on_theme_unhovered`). That was the correct scope for what it was built to test — but it means the
harness structurally cannot see this bug, since the bug lives entirely in the layer ABOVE
`_on_theme_unhovered`, deciding whether to call it at all.

Pryme's own report supplied what the harness never could: "waiting in the gutter... it is not
possible to time the fade... I can do a run with hover, hover-out, dismiss right away" — a live,
human-timed repro is the only way this class of Qt boundary-crossing event timing surfaces, matching
the CLAUDE.md rule that live geometry/paint/event-timing issues are not reliably reproducible in a
synthetic harness.

## What this investigation is NOT

Not a fix. The two candidate directions — narrowing the jitter check further (risky; two prior
narrowing attempts at this exact guard already failed and are documented in CLAUDE.md's "Only
`swatch_box.leaveEvent` may call `_on_themes_tab_left`" rule) or adding a periodic re-check that
doesn't depend on a single event being correctly classified — are not evaluated here. Any fix
attempt MUST re-read that CLAUDE.md rule's full history first: this exact area has broken twice
before via plausible-seeming cursor-delta redesigns, both live-confirmed regressions.

## Next step

Not yet started. Options worth weighing before touching this code, per the standing branch
discipline (investigate first, fix only when asked): (a) a periodic timer-based re-check of cursor
position vs. `swatch_box`'s bounds, independent of whether a `leaveEvent` fired at all, as a
belt-and-suspenders backstop; (b) widen the jitter check's reference to also consider whether the
CURRENT cursor position (not just the reported leave position) is outside `swatch_box`'s rect,
which the hidden-widget branch already does (`SWATCH-LEAVE-SUSPECT`, lines 2062-2073) but the
visible-widget jitter branch does not. Both need to be checked against the two previously-failed
redesigns' exact failure modes before being attempted live.

## Confirmed independent of panel-backdrop mode / blur (2026-08-03)

Pryme reproduced the same escape-to-gutter symptom under both Frosty glass and Transparent
panel-backdrop modes, then asked whether the transport-bar blur's grab/hide cycle could be
disturbing the hover/hover-out/preview mechanism differently under each mode — worth checking
given CLAUDE.md's own history of blur/theme-hover interactions elsewhere in this codebase.

It doesn't apply here, and not just by testing — the code structurally rules it out.
`_on_themes_tab_left`'s `if not visible:` branch (`theme_manager.py:2049-2079`) is the ONLY place
this method consults widget visibility/hidden-by-blur-grab state at all — that branch handles
the OTHER known failure mode (a synthetic leave from the blur grab's hide/show cycle, guarded by
`isVisible()` and, when suspicious, by the `SWATCH-LEAVE-SUSPECT` position check). **Both
confirmed repros hit the sibling branch instead** — the `visible=True` jitter check at lines
2080-2088 — which never reads blur state, panel-backdrop mode, or anything about the transport
bar at all. It is a pure two-cursor-position comparison (last recorded enter vs. reported leave).
Since the mechanism that actually failed doesn't consult blur/backdrop state in either direction,
there is no code-level reason for backdrop mode to change its behavior — consistent with Pryme's
live observation that the escape reproduced identically in both modes. No further log
correlation needed for this question; it's a structural ruling-out, not a coincidence needing
more samples.
