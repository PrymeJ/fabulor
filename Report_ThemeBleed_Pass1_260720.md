# Theme-Bleed Containment — Pass 1 (State-Read Containment, Mechanism A)
**Branch:** `blur-composited-overlay`  **Date:** 2026-07-20

Scope: implement the state-read containment fix identified in `Audit_ThemeReach_260720.md` as
"Path A" — `MainWindow._set_bg_suppressed`'s direct, hover-unaware read of
`theme_manager._active_display_theme`. Out of scope (per instructions, not attempted): the
`_grab_and_blur()` pixel-capture bypass (Mechanism B) and re-verifying `complete_main_fade`'s
fade-orphan theory.

**UPDATE, same day, live-tested:** the user tested this fix live (blur ON) and the hover-pulsate
bleed was still visibly present (screenshot: transport-bar area still showing the hovered theme's
colors baked into the blur). This confirmed the live bug was actually Mechanism B
(`_grab_and_blur`), not the bypass this pass closed — Pass 1 was correct and necessary but not
sufficient, exactly as flagged in this report's "Explicit non-claims" section below. A follow-up
fix (Pass 2, hover gate in `refresh_dirty()`) was implemented the same session — see
`TODO.md`'s 2026-07-20 "Pass 2" entry for full detail. This file is left as the historical record
of Pass 1 specifically; it is not being rewritten to describe Pass 2's changes.

---

## 1. What was renamed

`ThemeManager._active_display_theme` → `ThemeManager._active_display_theme_internal`, every
occurrence within `theme_manager.py` (20 occurrences: the field declaration, `get_current_theme`,
`snap_theme_forward`, the `_on_theme_changed` no-op guard and its debug logging, the assignment at
the top of `_on_theme_changed`'s apply path, and every read/log line inside `complete_main_fade`,
including its `[BLEED-TRACE]` diagnostic logging added in an earlier session). No behavior change
within `theme_manager.py` — this is a pure rename; every internal caller still reads/writes the
same value at the same point in the same control flow.

## 2. What the accessor does

Added `ThemeManager.get_active_theme()`:

```python
def get_active_theme(self):
    if self._is_hover_active:
        if self._cover_theme_active and self._cover_theme is not None:
            return self._cover_theme
        return self._current_theme_name
    return self._active_display_theme_internal or self._current_theme_name
```

- While a hover preview is live, it returns the **actual** active theme — the live cover theme if
  one is active, else the named pool theme (`_current_theme_name`) — never the hovered preview
  name, regardless of who's asking or why.
- Outside a hover, it returns exactly what the old bypass used to read
  (`_active_display_theme_internal`, falling back to `_current_theme_name`), so non-hover behavior
  is unchanged.
- Return type matches the field's own type: a `str` theme name, or a `dict` (cover-derived theme)
  when a cover theme is active — `_set_bg_suppressed`'s existing cover-theme-flash-avoidance logic
  depends on this, and the accessor doesn't change it.

This is now the sole sanctioned way for code outside `theme_manager.py` to read current theme
state, per the audit's Mechanism A design.

## 3. The bypass fix

`app.py`, `_set_bg_suppressed`: replaced the direct `getattr(self.theme_manager,
'_active_display_theme', None) or self.theme_manager._current_theme_name` read with
`self.theme_manager.get_active_theme()`. `_set_bg_suppressed`'s own
`content_container.setStyleSheet(...)` call was left untouched, as instructed — routing it through
`_apply_stylesheets()` instead would be a materially bigger change (it would need to reconcile with
`_apply_stylesheets`'s own suppress-bg-image handling and its animation/fade-state guards, none of
which `_set_bg_suppressed`'s call graph currently participates in). Flagging as a follow-up
recommendation, not attempted here: unifying this call site with `_apply_stylesheets` would also
close it as a structural (not just data) bypass of invariant #4, but that's a separate, larger
design question the audit didn't scope this pass to answer.

## 4. Grep verification

Repo-wide grep for the old bare name (`_active_display_theme` not followed by `_internal`) after
the rename:

```
src/fabulor/ui/theme_manager.py:193   — my own new accessor docstring, references the OLD name
                                          historically ("the old (pre-rename) bare
                                          _active_display_theme field") — expected, not a bug.
src/fabulor/ui/library.py:2100        — a comment, not code: "...that never equals
                                          _active_display_theme, so..." — plain English prose
                                          inside an unrelated comment about cover-theme cache
                                          invalidation, not an actual attribute reference. No
                                          code at this site touches ThemeManager's field at all.
```

No other occurrences anywhere in `*.py`. The audit's claim that `_set_bg_suppressed` was the only
cross-file reader is confirmed correct — the rename did not surface anything the audit missed. (A
grep across `*.md` also turned up mentions in `NOTES_THEMING_CURRENT_STATE.md`, `NOTES.md`,
`SESSION.md`, `CLAUDE.md`, and a `plans/` doc — all historical prose, not code; left as-is, since
docs are out of scope for this pass.)

## 5. Test suite result

`pytest tests/ -q`: **212 passed, 4 failed.** The 4 failures (all in
`tests/test_cover_theme_pending.py`: `test_no_animation_running_applies_immediately`,
`test_flag_stays_true_across_wait_then_clears_on_apply`, `test_reentrancy_guard_no_double_wait`,
`test_rapid_switch_stale_callback_does_not_apply_or_clear_new_pending`) were confirmed
**pre-existing and unrelated** — verified by `git stash`ing this pass's changes and re-running the
same file against the unmodified branch tip (`a531d7c`), which reproduces the identical 4 failures
with identical assertion output. Not touched, not investigated further (out of scope for this
pass); no test was weakened or deleted.

(Test count is 216 total, not the 174 CLAUDE.md's last full audit cited — consistent with several
sessions of test additions since that count was last updated; not a discrepancy introduced by this
pass.)

## 6. Did `complete_main_fade` interact with this field? (informational only, not fixed)

Yes — but not as an external bypass. `complete_main_fade()`'s fallback-reapply path
(`theme_manager.py`, the block after the `_pending_fade_call is not None` handoff) reads
`self._active_display_theme_internal`/`self._is_hover_active` and passes them straight into
`self._apply_stylesheets(...)` — entirely internal to `theme_manager.py`, going through the
dispatcher, not around it. This is **not an invariant-#4 bypass** and was correctly left untouched
by this pass's scope (privatizing the field doesn't change its behavior, only who's allowed to read
it from outside the class).

Per the audit and per NOTES.md, this fallback path is a **separate, already-partially-mitigated,
still-unverified** contributor to the theme-bleed bug (the "Path B" in
`Audit_ThemeReach_260720.md` / the fade-orphan theory from an earlier session): if
`_active_display_theme_internal` is still holding a hover-preview theme name at the moment a panel
opens mid-fade with no call stashed in `_pending_fade_call`, this fallback reapplies that stale
hover value through the fast synchronous path (which includes `main_window`/`content_container`).
This pass's rename/accessor does not touch, fix, or re-verify that mechanism — it remains open, as
instructed.

---

## Explicit non-claims

- Theme-bleed is **not** being reported as fixed or closed. This pass closes one of (at least)
  three independent causes the audit identified (`_set_bg_suppressed`'s bypass). The
  `_grab_and_blur()` pixel-capture path and the `complete_main_fade` fallback-reapply path are both
  still open, per the Do-Not list.
- No live/blur-ON verification was performed as part of this pass — that is explicitly a separate
  step for the user, per instructions.
- No timing, caching, or debouncing logic was added.
- `_is_hover_active`'s semantics and every site that sets it are unchanged — the new accessor only
  reads it.

## Files changed

- `src/fabulor/ui/theme_manager.py` — field rename (20 sites) + new `get_active_theme()` accessor.
- `src/fabulor/app.py` — `_set_bg_suppressed` now calls `theme_manager.get_active_theme()`.
- `TODO.md` — new entry recording this pass's scope and status (not closed).
