# Investigation: is the dispatcher-only stylesheet path sufficient for Sleep/Speed, or does it depend on the C4/C5 bypass?

**Date:** 2026-08-03  **Branch:** `investigate/restyle-cost-depth-and-narrowing`  **Status:**
Complete. Diagnostic only — the temporary patch was fully reverted (`git diff` confirmed empty)
before this document was written. No permanent fix implemented.

---

## Method

Temporarily short-circuited `PanelInterface.update_speed_panel_visuals`/
`update_sleep_panel_visuals` (`app.py`) to no-ops — these are the sole call sites for
`speed_controls.py`'s `update_visuals()` and `sleep_timer.py`'s `update_panel_styling()` (the C4/C5
bypasses), reached only via `sync_all_settings_visuals`'s theme-apply TAIL. The dispatcher path
(`_apply_stylesheets`'s step-6 loop, now calling the split `get_settings_stylesheet`/
`get_speed_stylesheet`/`get_sleep_stylesheet`) was left completely untouched. `sync_all_settings_visuals`
itself was NOT disabled wholesale — it also drives several unrelated Settings-tab pattern-button
syncs (scroll mode, hints, notches, blur, hover-fade, undo, digit-mode, chapter-source) that have
nothing to do with this investigation; disabling the whole method would have contaminated the test.

Built a live, on-screen probe (`c4c5_isolation_probe.py`, scratchpad, not committed) that: opens
Sleep, sets a distinguishable button state (fade selection; `disable_sleep_btn`'s active-timer state
set directly on the panel object, deliberately avoiding `set_sleep_timer()` itself — see the
methodology note below), samples every distinct button's rendered center-pixel color, fires a real,
full, non-hover `_on_theme_changed` to a different theme, and re-samples. Repeats for Speed. Finishes
with one hover-preview + hover-out cycle on Settings.

### A methodology correction made mid-investigation, worth recording

The first probe run showed every Sleep button "unchanged" after the theme change — which would have
been reported as "the whole panel is stone dead without the bypass" had it not been checked further.
Instrumenting `_apply_stylesheets` directly (wrapping it to print `sleep_panel.isVisible()` at call
time) showed the real cause: the probe's own setup called `sleep.set_sleep_timer(duration_minutes=15)`
to give `disable_sleep_btn` an active-looking state — but `set_sleep_timer()` is wired
(`app.py`: `self.sleep_panel.timer_started.connect(self.panel_manager._close_sleep_flow)`) to close
the Sleep panel automatically the instant a timer is set. **This is confirmed, correct, intentional
app behavior — not a bug found by this investigation** — but it meant the probe's "theme change while
Sleep is open" step was actually running against an already-closed, invisible panel, so of course
nothing visibly changed: the dispatcher's own `if not force_all_panels and not w.isVisible(): continue`
skip (added 2026-08-01) was correctly declining to restyle a panel nobody could see. Fixed by setting
`disable_sleep_btn`'s active state directly on the panel object instead of going through
`set_sleep_timer()`. The corrected run is what the results below reflect. Recorded here because it
is exactly the kind of self-inflicted false negative this branch's own methodology rules exist to
catch — verify the precondition (panel actually visible) before trusting a "no change" result.

---

## Per-button results

### Sleep panel

| Button / group | Dispatcher-only result | Mechanism when bypass is active |
|---|---|---|
| 14 duration-preset buttons (`_sleep_presets_buttons`, "2 min"–"90 min") | **UNCHANGED** — no coloring at all without the bypass | `preset_ramp_rgb(theme, index, count)` — a per-instance `setStyleSheet()` blending `bg_main` toward `accent` at a ratio that varies by the button's OWN INDEX in the row |
| `end_chap_btn` ("End of chapter") | **CHANGED** — correctly repainted | None needed — plain `QPushButton`, no object name, styled by the shared base's generic `QPushButton` rule (`_get_gradient_style(t, "accent", t['accent'])`) |
| `set_custom_btn` ("Set") | Not separately sampled, but same shape as `end_chap_btn` (plain `QPushButton`, no object name, no per-instance style, not touched by `update_panel_styling()`) — same conclusion applies | Same as `end_chap_btn` |
| 5 fade-duration buttons (`_sleep_fade_btns`, "Off"/"30s"/"1m"/"2m"/"5m") | **CHANGED** — correctly repainted, including the selected/default state's distinct coloring | Base coloring is pure dispatcher QSS (`pattern_button[selected="true"]`/`[is_default="true"]`, in `get_panel_base_stylesheet`). The bypass's role here is NOT coloring — it's setting the `selected`/`is_default` Qt *properties* and calling `unpolish()/polish()` so the already-correct QSS re-evaluates. Without it, colors are right but a live selection change wouldn't repaint — orthogonal to this investigation's theme-change question |
| `disable_sleep_btn` | **CHANGED** — correctly repainted | Pure dispatcher QSS (`#disable_sleep_btn`, in `get_sleep_stylesheet` post-split). No bypass dependency for coloring at all |

### Speed panel

| Button / group | Dispatcher-only result | Mechanism when bypass is active |
|---|---|---|
| 12 speed-preset buttons (`_speed_grid_buttons`, "1.00x"–"4.00x") | **UNCHANGED** — no coloring at all without the bypass | Identical mechanism to Sleep's duration presets: `preset_ramp_rgb`, per-instance, index-dependent |
| `def_speed_buttons`, `step_buttons`, `undo_buttons`, `skip_buttons`, `long_skip_buttons`, `smart_wait_buttons`, `smart_dur_buttons` (all `pattern_button`-styled) | **CHANGED** — correctly repainted | Same as Sleep's fade buttons: pure dispatcher QSS for color; bypass only flips the `selected` property and repolishes |

### Settings hover-preview + hover-out (control — should be unaffected)

Confirmed unaffected, as expected: the hover-preview apply (`Goldfinch`, `hover=True`) and the
snapback apply on hover-out both ran through `_apply_stylesheets` normally, with C4/C5 disabled the
entire time. This path never called `update_speed_panel_visuals`/`update_sleep_panel_visuals` even on
stock code (both `speed_panel`/`sleep_panel` are hidden during any Settings-open interaction, and the
TAIL that calls them is `if not hover:`-gated) — so disabling them had, correctly, zero observable
effect on this path. Verified rather than assumed, per the task's own instruction.

---

## Classification: which of the three cases each dependent button falls into

Per the updated task scope, three cases were checked explicitly rather than a binary
dynamic-vs-duplicated split:

**1. Genuinely dynamic/state-dependent (selection, active, hover) — bypass legitimate as-is:**
The `selected`/`is_default` PROPERTY-SETTING half of the fade/pattern-button mechanism (Sleep's fade
buttons, all of Speed's `pattern_button` groups). This is real application state (which duration is
currently selected) that only the panel's own code can know — a static QSS rule cannot discover it.
This part of the bypass is legitimate and is not a duplication candidate. **Its actual base coloring,
however, is already 100% dispatcher QSS** — the bypass here is not re-implementing color logic, only
triggering Qt's repolish after a property change. Not a candidate for consolidation because there is
nothing to consolidate: the color rule already lives in one place (the dispatcher stylesheet).

**2. Static but intentionally visually distinct (per Pryme: `end_chap_btn`/`set_custom_btn`) — check theme-awareness specifically:**
Checked directly, not assumed: `end_chap_btn` and `set_custom_btn` are plain `QPushButton`s with no
object name and are **never touched by `update_panel_styling()` at all** — confirmed by reading the
full method body, which only iterates `_sleep_presets_buttons` and `_sleep_fade_btns`. Their
distinct-looking gradient treatment (visible in Pryme's earlier screenshot as a warmer/differently-
shaped color band than the plain preset buttons) comes entirely from the shared base's generic
`QPushButton` rule, which itself already uses `_get_gradient_style(t, "accent", t['accent'])` — a
genuine, live, theme-derived gradient (reads `gradient_accent_start`/`gradient_accent_end`/`angle`/
`split` from the ACTIVE theme dict). **This coloring is already fully theme-aware today, via the
dispatcher alone, with zero bypass involvement.** The visual distinctness Pryme correctly identified
as intentional is real, but it is not produced by C4/C5 — it is an emergent effect of these two
buttons being the only plain, un-ramped, un-pattern-classed `QPushButton`s left visible in the Sleep
panel once the ramp and pattern-button treatments are subtracted out. There is nothing to preserve
here in a future consolidation, because there is nothing bypass-owned to lose.

**3. Static, no apparent reason for distinctness, likely duplicated/stale — genuine deletion candidate:**
None of the checked buttons fall cleanly into this case. The only remaining bypass-owned mechanism —
the preset/speed ramp coloring itself — was checked against this case and does NOT qualify: it is
theme-derived (both endpoints of the blend, `bg_main` and `accent`, come from the active theme dict,
confirmed by reading `preset_ramp_rgb`'s signature and body) and it is genuinely per-widget-index
dynamic (each button's blend ratio depends on its position among its siblings, `i / (n-1)`), which a
single static QSS selector cannot express without either 14 (Sleep) / 12 (Speed) separate hardcoded
per-button-ID rules (defeating the point of a ramp — it would need updating by hand every time a
preset is added/removed) or a Qt mechanism this codebase doesn't use elsewhere for this purpose.

---

## Conclusion

**C4/C5 is legitimate for exactly one thing across both panels: the per-instance, per-index preset
color ramp (14 Sleep duration buttons, 12 Speed speed buttons).** Every other button in both panels
is already fully served by the dispatcher's split stylesheet functions with zero coloring
contribution from the bypass — including the two buttons (`end_chap_btn`, `set_custom_btn`) whose
visual distinctness might have suggested a bypass dependency; checked directly and found to be a
side effect of the shared base's own already-theme-aware gradient rule, not bypass output. The
`selected`/`is_default` state-sync half of the bypass (shared by Sleep's fade buttons and every
`pattern_button` group in Speed) is legitimate for a different reason — it's driving Qt property
state, not color — and its underlying color rule is likewise already 100% dispatcher-owned.

This substantially narrows what a future consolidation pass would actually need to touch: not "unify
two panels' worth of styling logic," but specifically "give the preset/speed ramp a home that isn't
a hand-rolled per-instance `setStyleSheet()` duplicated near-verbatim in two files" — everything else
in both panels is already single-sourced in `themes.py`.

## What this investigation is NOT

Not a fix, not a consolidation proposal, not a recommendation on HOW to eventually handle the ramp
buttons (a QSS-expressible pattern, a shared helper the two files both call, or leaving them as-is)
— that is future work, explicitly out of scope here per the task. The temporary patch used to run
this investigation was fully reverted; `git diff` confirmed empty before this document was written.
