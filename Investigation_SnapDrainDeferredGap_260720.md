# Investigation: `snap_theme_forward()`'s drain fix is incomplete — deferred-pass surfaces never refresh

**Date:** 2026-07-20  **Branch:** `blur-composited-overlay`  **Status:** diagnosis only, no fix applied yet.

This directly implicates code shipped earlier in this same session (the `snap_theme_forward()`
stash-drain fix for the settings-panel-dismiss theme-bleed race). Write-up-first, per standing
practice tonight, specifically because a second change is about to land on top of the first.

---

## What was confirmed live, with exact trace evidence

Reproduced via the user's `22:56:36`–`22:58:12` panel-cycling sequence (Stats, Tags, Library,
Speed, Sleep ×3, Settings), screenshotted with Sleep showing two themes' preset-button colors
mixed in one panel. Full log trace pulled from `fabulor.log.1`.

**Root sequence, `Rose Code` theme selection:**

1. `22:56:32,736` — hover preview fires for `Rose Code` (`_on_theme_changed(..., hover=True)`).
2. `22:56:33,205` — the unhover snap-back call arrives (`hover=False`), but `fade_in_flight=True`
   (a fade from the hover preview is still running) — so this call is **stashed** into
   `_pending_fade_call`, per `_on_theme_changed`'s `_fade_running` guard branch.
3. `22:56:33,514` onward — the (separately tracked, still-open) heartbeat bug fires repeatedly
   (`EARLY-RETURN no-op guard`), consistent with earlier tonight's `Anomander` trace — burns
   cycles without reaching any drain path.
4. `22:56:34,461` — `hide_for_panel ENTRY active_panel='settings_panel'` — the Settings panel
   dismisses. This is `_close_settings_flow()` (`panels.py:777`) running: it calls
   `_on_theme_unhovered()` then `snap_theme_forward()`, synchronously.
5. `snap_theme_forward()`'s drain (shipped earlier this session) correctly fires and resolves the
   stash: `_active_display_theme_internal='Rose Code'`, `_is_hover_active=False` are set, and
   `_apply_stylesheets('Rose Code', hover=False)` is called directly — confirmed by
   `complete_main_fade ENTRY` at `22:56:34,557` showing `_pending_fade_call=None` and
   `_active_display_theme_internal='Rose Code'` already correct.

**Confirmed via grep of the full trace window: `_flush_deferred_restyle_now: ENTRY theme='Rose Code'`
never appears anywhere.** The deferred pass for `Rose Code` never ran. Every subsequent panel open
in the user's sequence (Stats `22:56:36`ish, Tags `22:57:00`, Library `22:57:11`, Speed `22:57:23`,
Sleep ×3, Settings `22:58:11`) called `_flush_pending_restyle()` and got
`flush_deferred_restyle: NOOP (nothing pending)` every single time — because nothing was ever
scheduled as pending for `Rose Code` in the first place, not because a pending batch failed to run.

## Why: `snap_theme_forward()`'s drain only does half of what a normal theme-change call does

`_on_theme_changed()`'s three apply branches (themes-tab overlay fade, slider-animated fade,
instant no-fade) are followed unconditionally by one shared line, applying to all three:

```python
# theme_manager.py:666-667
if not hover:
    self._schedule_deferred_restyle(theme_name)
```

`_schedule_deferred_restyle` is what eventually leads to `_apply_stylesheets_deferred`
(Stats/Library's panel-level QSS), the `theme_applied` signal (Stats/Tags/Book-Detail's
`on_theme_changed`, which drives their accent-derived colors), and `_refresh_panel_visuals` /
`sync_all_settings_visuals` (which calls `update_speed_panel_visuals`/`update_sleep_panel_visuals`
— confirmed both ARE wired, `settings_controller.py:149-150` — these are not missing connections).

`snap_theme_forward()`'s drain branch (added this session, `theme_manager.py:280-284`) sets
`_active_display_theme_internal`/`_is_hover_active` and lets the method's own existing tail call
`_apply_stylesheets(...)` directly — but it never calls `_schedule_deferred_restyle(...)`, and
nothing else in `snap_theme_forward()`'s body does either. So the fast-pass surfaces
(main window, content_container, sidebar, and — this is the part that matters here — the
settings/speed/**sleep** panels' own top-level `setStyleSheet()`) become correct immediately, but
every surface that depends on the deferred batch stays on whatever theme was active the last time
that batch genuinely ran.

## Confirms this is one root cause, not four separate panel bugs

Checked whether Stats/Tags/Library/Sleep each independently mis-wire their own colors (the user's
original hypothesis, worth checking before assuming one shared cause): **no** — every one of them
is correctly wired to the deferred-pass/`theme_applied`/`_refresh_panel_visuals` machinery already:

- `stats_panel`/`tags_panel`/`book_detail_panel`: `theme_applied.connect(...on_theme_changed)`,
  `main_window_builders.py:570/585/617`.
- `library_panel`: styled directly inside `_apply_stylesheets_deferred`
  (`library_panel.setStyleSheet(...)`, `theme_manager.py:1111-1112`).
- `sleep_panel`'s preset-button colors (`update_panel_styling()`, `sleep_timer.py:163-184`, a
  direct per-button `setStyleSheet()` call reading `self.theme_manager.get_current_theme()`) — IS
  called from theme-change events, via `settings_controller.py:150`
  (`self.panels.update_sleep_panel_visuals()`, itself called from `sync_all_settings_visuals`,
  which IS `_refresh_panel_visuals`, called from `_flush_deferred_restyle_now`'s tail,
  `theme_manager.py:1208-1209`).
- `speed_panel`'s equivalent (`update_visuals(theme_name=None)`, `speed_controls.py:247-256`, same
  per-button pattern) — same wiring, `app.py:262`.

**None of these four panels has a broken/missing connection to the theme system.** All four are
correctly downstream of the SAME single mechanism — `_schedule_deferred_restyle` /
`_flush_deferred_restyle_now` — which `snap_theme_forward()`'s drain simply never reaches. One root
cause, confirmed, not four independent construction mistakes.

Also independently confirmed, per the user's direction: not blur-specific (the deferred-pass
mechanism and `snap_theme_forward()` are pure `theme_manager.py`/`panels.py` logic, no blur-overlay
code involved in this trace at all) and not a hover-preview bleed (this is current-theme vs.
previous-theme, `_is_hover_active=False` throughout the visible symptom window — a materially
different bug shape from tonight's earlier hover-bleed fixes).

---

## Proposed fix shape — and a real complication found while sizing it

**The requested question, answered directly: should the fix add two direct calls
(`_schedule_deferred_restyle` + something to reach `theme_applied`/`_refresh_panel_visuals`), or
should it route through `_on_theme_changed(*pending)` itself (matching `complete_main_fade`'s
existing approach) via a forced `fade_ms=0`?**

Tracing `_on_theme_changed`'s actual branch structure (`theme_manager.py:646-667`) confirms the
single-call approach is structurally available: the `fade_ms == 0` branch (line 650-654) applies
`_apply_stylesheets` synchronously with no new animation — exactly the "instant, no animation"
behavior `snap_theme_forward()`'s drain deliberately chose — and the `_schedule_deferred_restyle`
call at line 666-667 sits AFTER the three-way if/elif/else, applying uniformly to all three
branches including the instant one. So `_on_theme_changed(pending_theme_name, save=False,
fade_ms=0, hover=pending_hover, user_initiated=...)` would, in one call, both apply the theme
instantly (matching what the current two-line drain does today) AND correctly schedule the
deferred batch — a single call replacing two separate, currently-missing concerns, rather than
duplicating `_on_theme_changed`'s own apply logic a second time inside `snap_theme_forward()`.

**However — a real correctness risk found while checking this, not assumed:**
`snap_theme_forward()` never reads or writes `_fade_in_flight` anywhere in its own body (confirmed
by grep — every read/write site of `_fade_in_flight` in the file is elsewhere). `_on_theme_changed`'s
`_fade_running` guard (the same guard that caused the ORIGINAL stash in step 2 above) checks
`getattr(self, '_fade_in_flight', False)` fresh, on every call. Since `snap_theme_forward()` is
called immediately after `_on_theme_unhovered()` — the very call that set `_fade_in_flight=True`
in the first place — in the same call stack, with no intervening event-loop turn, **`_fade_in_flight`
is very likely still `True` at the exact moment `snap_theme_forward()`'s drain would fire.** If the
drain called `_on_theme_changed(*pending)` (even with `fade_ms=0` forced) without first clearing
`_fade_in_flight`, it would immediately re-hit the SAME `_fade_running` guard branch and re-stash
the call it was just trying to resolve — silently doing nothing, reproducing the exact bug this
session already fixed once, in a new disguise.

**This means the single-call approach is correct in principle but is NOT a drop-in
`_on_theme_changed(*pending)` call as-is** — it requires `snap_theme_forward()` to also clear
`_fade_in_flight = False` before making that call (mirroring what `complete_main_fade()` already
does at its own drain site, `theme_manager.py:868`, right before its own `_on_theme_changed(*pending)`
call at line ~887). This is not a new/independent finding — it's the same precondition
`complete_main_fade()`'s existing, working drain already satisfies, that a naive port of the
single-call approach into `snap_theme_forward()` would need to satisfy too, and does not
automatically get for free just by calling the same method. Recommending: clear `_fade_in_flight`
explicitly right before the `_on_theme_changed(*pending-with-fade_ms=0)` call, and confirm via a
fresh live trace (mirroring tonight's `[SNAP-DRAIN-TRACE]` verification pattern) that the call
actually proceeds past both guards on the first attempt, not re-stashing.

## Confirmed: this does NOT reopen the panel-dismiss/blur-grab race

The original constraint (from earlier tonight) was specifically that the FAST-pass surfaces
(main_window, content_container, sidebar, and the settings/speed/sleep panels' own `setStyleSheet`)
must be resolved synchronously before `_close_settings_flow` starts the panel slide-out/blur-reduction
animation, because the blur overlay's grab captures whatever those surfaces show at that instant.
The deferred-pass surfaces (Stats/Tags/Library/Book-Detail, plus Sleep/Speed's per-button colors)
were never part of that constraint — they are not what the blur overlay grabs on settings-dismiss
(they're not visible/composited into that grab at all), and nothing about scheduling
`_schedule_deferred_restyle` from inside the drain changes the FAST-pass application, which still
happens synchronously via the `fade_ms=0` branch's `_apply_stylesheets` call, before
`_schedule_deferred_restyle` is even reached (per the branch ordering in `_on_theme_changed`,
lines 646-667). Scheduling the deferred batch to run on the next event-loop turn (its normal,
existing behavior — a `QTimer.singleShot(0, ...)`) is exactly as safe here as it is for every other
non-hover theme change in the app; this fix does not need to make the deferred pass synchronous
too, only make sure it gets scheduled at all, which it currently never does from this one call site.

## Files/lines involved

- `src/fabulor/ui/theme_manager.py:250-294` — `snap_theme_forward()`, the method to change.
- `src/fabulor/ui/theme_manager.py:502-667` — `_on_theme_changed()`, whose `fade_ms=0` branch
  (650-654) and shared `_schedule_deferred_restyle` tail (666-667) are the mechanism being reused.
- `src/fabulor/ui/theme_manager.py:798-903` — `complete_main_fade()`, the existing reference
  implementation for the "clear `_fade_in_flight` then call `_on_theme_changed(*pending)`" pattern
  (lines 868, 887).
- `src/fabulor/ui/panels.py:777-798` — `_close_settings_flow()`, the caller context this all serves.
- `src/fabulor/ui/sleep_timer.py:163-184`, `src/fabulor/ui/speed_controls.py:247-264` — the
  downstream per-button styling methods confirmed correctly wired but never reached by this path.
- `src/fabulor/settings_controller.py:135-151` — `sync_all_settings_visuals` (aliased to
  `_refresh_panel_visuals`), confirmed to already call both `update_speed_panel_visuals` and
  `update_sleep_panel_visuals`.
