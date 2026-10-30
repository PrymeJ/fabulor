# Spec: stop a hover preview from landing after Settings starts closing

**Date:** 2026-10-30 · **Status:** implemented after review, live-checked by Pryme 2026-10-30 · **Code as of:** `bcfa3f7`
**Reviewer brief:** this is a change in the theme-hover machinery, which CLAUDE.md treats as
fragile. The ask is a second pair of eyes on the mechanism, the two guards, and the CLAUDE.md
rules listed in §5 before any code is written.

## 1. The bug

Seen live 2026-10-30 at 06:04 (fabulor.log). Pryme selected Anomander in Settings > Themes and
dismissed Settings. The main window and title bar stayed on **Yellow Wallpaper** (confirmed by
exact pixel values against the theme dict), while Stats and the other panels showed Anomander.
Reopening Settings cleared it. A hover preview only restyles the main window, title bar and
Settings (the "hover confinement" rule), so a preview that lands with Settings closed leaves the
app in two themes at once, and nothing can end it: the Themes tab, whose leave events and backstop
timer normally end a preview, is no longer on screen.

Pryme's requirement, quoted from the session: *no preview may be pending when Settings starts to
slide.* Every hover preview, including one still in its debounce, must be drained or cancelled
before the slide begins. Re-applying the active theme afterwards is not a fix: by then the main
window has already shown the wrong theme.

The bug is a latent race (the queuing path dates from `8c348b0`, 2026-07-28, unchanged since), not
a regression. It needs a hover debounce to expire inside a ~450ms window, so it is rare; it last
appeared about two months earlier and was believed fixed.

## 2. The trace (fabulor.log, 2026-10-30)

| Time | Event |
|---|---|
| 06:04:42.958 | `_close_settings_flow` ENTRY. Calls `_on_theme_unhovered()`, which stops `_hover_debounce_timer` and issues a snapback. Waits via `call_when_theme_settled`. |
| 06:04:43.182 | Settle confirmed (`_theme_genuinely_settled_on_committed`); `_SNAPBACK_SETTLE_GAP_MS` (150ms) timer starts. |
| 06:04:43.198 / .236 / .250 | `ThemeItem.enterEvent PASSED` for Pink Institute, Castle Dracula, **Yellow Wallpaper**: the cursor crossed swatches on its way to the dismiss area. Settings is still visible, so each enter calls `_on_theme_hovered`, which **restarts the 150ms debounce**. |
| 06:04:43.341 | `_close_settings_flow_after_settle_gap`: slide-out starts; `_settings_close_pending` cleared. |
| 06:04:43.397 | Debounce fires: `_fire_pending_hover` → `_on_theme_changed('Yellow Wallpaper', hover=True)`. A panel is animating, so it is **queued** via `call_when_panels_settled(..., coalesce_key="theme_change")`. |
| 06:04:43.647 | Slide finished. `[SWATCH-LEAVE-SUSPECT]` correction calls `_on_theme_unhovered()`; Anomander applied directly (not through the queue, so it does not replace the queued waiter). |
| 06:04:43.933 | `[settle-watch] panels settled, draining 1 waiter(s)`: the queued Yellow Wallpaper preview applies. `_active_display_theme_internal='Yellow Wallpaper'`, `_is_hover_active=True` from here on. |

## 3. Mechanism

- The close flow stops the debounce **once**, at entry. It does not stop hover input. For the
  whole settle wait plus the 150ms gap (~400ms here), swatches stay live and any enter re-arms the
  debounce. The 2026-08-05 settle predicate already handles a hover that *applies* during the
  wait; this one arrived after the predicate passed, inside the gap.
- Three call sites arm the debounce, all into one sink:
  - `ThemeManager._on_theme_hovered` (mouse swatch, `main_window_builders.py:886`; keyboard swatch
    arrival, `theme_manager.py:2384`)
  - `ThemeManager._on_cover_pool_btn_hovered` (`theme_manager.py:3089`)
  - sink: `ThemeManager._fire_pending_hover` (`theme_manager.py:2446`), the only caller of the
    preview `_on_theme_changed(..., hover=True)`.
- A hover call that meets a running panel animation is queued and later re-calls
  `_on_theme_changed` in full. A later *direct* snapback does not cancel it.

## Review outcome (added after a second-instance review, 2026-10-30)

- **`_settings_close_pending` ownership:** confirmed a `PanelManager` attribute (set in
  `PanelManager._close_settings_flow`, cleared at the top of `_close_settings_flow_after_settle_gap`
  on every path, including its early return). It is not set in `__init__`, so the predicate's
  `getattr(..., False)` default is load-bearing, matching how the close flow already reads it.
- **Correction (found while checking the above):** the first draft used `_is_closing("settings")`
  for the slide-out. That only checks that `settings_panel_animation` is running, and Settings uses
  the same animation for its OPEN slide (end `QPoint(0, y)`) and its close slide (end
  `QPoint(-panel_w, y)`). The draft would have dropped legitimate hovers while Settings slides in
  and written false tripwire lines. The predicate now reads the slide direction from the
  animation's end value. The animation is one object for the app's lifetime, never replaced or
  `None`.
- Test cases split per state with explicit ids; §7 lists both tripwire tags.

## 4. The change (as implemented)

### 4.1 Primary guard: the debounce cannot fire a preview once Settings is closing

New predicate on `PanelManager` (panels.py), next to `_is_closing`:

```python
def settings_accepts_hover_preview(self):
    """True only while Settings is open and not closing. An opening slide counts as open;
    a close counts from its start: the settle wait, the slide-out, and hidden."""
    anim = self.settings_panel_animation
    sliding_out = (anim.state() == QAbstractAnimation.State.Running
                   and anim.endValue().x() < 0)
    return (self.settings_panel.isVisible()
            and not getattr(self, "_settings_close_pending", False)
            and not sliding_out)
```

In `ThemeManager._fire_pending_hover`, after `self._pending_hover_theme = None` and before the
`_on_theme_changed` call:

```python
pm = getattr(self.main_window, "panel_manager", None)
if pm is not None and not pm.settings_accepts_hover_preview():
    logger.warning(f"[HOVER-TRACE] preview for {theme_name!r} DROPPED: Settings is closing")
    record_tripwire("HOVER-PREVIEW-DROPPED-SETTINGS-CLOSING", f"preview {theme_name!r} dropped")
    return
```

Gating the one sink covers all three arm sites (mouse, keyboard, cover-theme button) and both
windows (settle wait/gap via `_settings_close_pending`, slide-out via the animation's direction). The arm sites are
untouched: an armed debounce that cannot fire is harmless, and changing the entry points would mean
touching the swatch enter/leave machinery CLAUDE.md warns about. Nothing is applied on the drop
path, so there is nothing to undo; the close flow's own entry snapback already restored the
committed theme.

### 4.2 Backstop: no queued hover replay applies once Settings is closing

At the very top of `ThemeManager._on_theme_changed`, before every branch:
`if self._hover_call_is_stale(theme_name, hover): return`. The helper returns False for any
non-hover call and for a hover while Settings accepts previews; otherwise it logs, records the
`HOVER-REPLAY-DROPPED-SETTINGS-CLOSING` tripwire, and returns True. Split out so the "never stops
a selection or snapback" property is directly testable.

`_on_theme_changed` is where every deferred hover call resumes (queued waiter, panel-guard timer,
fade-stash drains all re-call it in full), so this one check covers every replay path, including
any not yet known. With 4.1 in place nothing should reach it: a `HOVER-REPLAY-...` line in
`TRIPWIRES.txt` would mean another path exists. Hover previews only originate inside the open
Themes tab, so a `hover=True` call while Settings is not accepting previews is stale by
construction.

`record_tripwire` is `logger_setup.record_tripwire` (`bcfa3f7`): it appends a dated, tagged line to
an untracked `TRIPWIRES.txt` in the repo root, which never rotates and shows in `git status`.

### 4.3 What is deliberately not changed

- The close flow's ordering (`_on_theme_unhovered()` before anything else) and its settle wait.
- `_on_theme_unhovered`, the snapback, `snap_theme_forward`, the `_pending_fade_call` stash and its
  three drains, `call_when_panels_settled` and its coalesce key.
- The swatch enter/leave handlers, `_on_themes_tab_left`, the `SWATCH-LEAVE-SUSPECT` correction,
  the 500ms swatch backstop timer.

## 5. CLAUDE.md rules checked

| Rule | Why this change keeps it |
|---|---|
| Hover-preview theme application must never reach `_schedule_deferred_restyle` or any panel-level stylesheet | Only drops hover calls; adds no apply path. |
| `_pending_fade_call`'s stash tuple must carry every parameter | Stash untouched. A stashed hover call that drains while Settings is closing is now dropped at 4.2, the intended outcome. |
| Do not resume a panel-animation wait via `finished`; keep `blur_animation` in `_any_panel_animating()` | Waiter mechanism untouched. |
| Do not make a panel-dismiss path depend on a stashed snapback | Dismiss ordering untouched; the entry snapback is still issued fresh. |
| Themes tab hover vs blur-grab synthetic events (four consequences) | No leave/enter handler changes, no new `_on_theme_unhovered` lambda, no cursor-delta test, `swatch_box` remains the sole leave trigger. |
| Settings' Themes tab and every other panel are mutually exclusive; verification must be synthetic | Tests below are synthetic by design. |

Open slide: `settings_accepts_hover_preview` is True while Settings slides in (visible, close not
pending, animation heading to x = 0), so a hover during the open slide still applies, as before.
The bug report concerns the close path only; the open path has no known problem.

## 6. Tests (written first; `tests/test_settings_close_hover_guard.py`)

Synthetic, in the style of `tests/test_panel_settle_resume.py` (`ThemeManager.__new__` /
`PanelManager.__new__` with stand-ins), redirected tripwires (autouse fixture in `conftest.py`):

1. Predicate truth table, ids `open_idle`, `opening_slide`, `close_pending`, `slide_out`, `hidden`.
2. `_fire_pending_hover`, ids `close_pending` / `slide_out` / `hidden`: no
   `_on_theme_changed(hover=True)`; a `HOVER-PREVIEW-DROPPED-...` line.
3. Real `_on_theme_changed(hover=True)` with Settings hidden: returns before any branch; a
   `HOVER-REPLAY-DROPPED-...` line.
4. Controls: `open_idle` and `opening_slide` still fire the preview; `_hover_call_is_stale` is
   False for `hover=False` in every state and for a hover while Settings is open; no tripwire file.
5. Fail-first, done: with HEAD's unguarded `theme_manager.py` (predicate kept), cases 2-4's guard
   and helper tests fail and the predicate/control tests pass. Two existing tests' stand-in panel
   managers gained `settings_accepts_hover_preview` (True: their scenarios hover with Settings
   open). Full suite green.

## 7. Live verification

Like the sidebar race, Pryme cannot produce this on demand. The tests and the tripwires stand in:
- `HOVER-PREVIEW-DROPPED-SETTINGS-CLOSING` in `TRIPWIRES.txt`: the race happened and the primary
  guard caught it.
- `HOVER-REPLAY-DROPPED-SETTINGS-CLOSING`: a hover call reached `_on_theme_changed` during a close
  by some path other than the debounce. The backstop held, but that path should be found. A live pass should still confirm ordinary hover browsing and dismiss feel unchanged
(hover previews fire, snapback on leave, dismiss with a preview showing restores the active theme).
