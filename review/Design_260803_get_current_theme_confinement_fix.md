# Design (implemented): close the `get_current_theme()` confinement gap

**Date:** 2026-08-03  **Branch:** `investigate/restyle-cost-depth-and-narrowing`  **Status:**
Implemented and verified — full `pytest tests/ -q` at 440/440 passing (435 baseline + 5 new), all
7 confirmed runtime call sites individually spot-checked live and confirmed corrected.

## Context

This session's investigation (live log 20:07:23–20:09:30) confirmed the root cause of the
hover-preview confinement regression: `ThemeManager.get_current_theme()` returns
`_active_display_theme_internal` with **no hover check at all**, and that field legitimately holds
the *hovered* theme's name for as long as a preview is showing. A hover can complete, then get
silently un-corrected — the Settings panel transitions away (opening another panel, expanding the
sidebar) via a path that fires a *synthetic* (blur-grab-hidden) `leaveEvent` on the swatch rather
than a genuine mouse-out, so `_on_theme_unhovered()` never runs — leaving
`_active_display_theme_internal`/`_is_hover_active=True` stuck indefinitely. Every caller of
`get_current_theme()` after that point reads the stale hover theme back, regardless of what's
visibly happening in Settings.

The safe accessor, `get_active_theme()`, already exists and was **built for exactly this class of
bug** on 2026-07-20 (commit `0439c76`, `review/Review_260720_theme_reach.md`) — but that fix added
`get_active_theme()` as an *additional*, sanctioned path without ever touching, restricting, or
even flagging `get_current_theme()`. The unsafe accessor was left fully public, equally easy to
reach for, and reads more naturally by name — which is exactly why it kept accumulating new callers
(seven runtime call sites, plus four startup-only ones) over the following two weeks.

---

## 1. Exhaustive call-site audit

`grep -rn "get_current_theme()" src/ tools/` — every result, classified:

| Site | Reachable at runtime, independent of hover state? | Notes |
|---|---|---|
| `library.py:482` (`_resolve_theme_colors`, called from `refresh()` and `_on_view_mode_changed()`) | **Yes** | Feeds `BookDelegate`'s per-item `@Property(QColor)` fields. `refresh()` runs on every Library open. Originally-confirmed leak. |
| `library.py:1556` (`_refresh_search_match_state`) | **Yes** | Search-field no-match error-color. **Not in the original four** — found by this audit's exhaustive grep. |
| `transport_bar_blur.py:575` (panel-backdrop frost wash) | **Yes** | Runs on every blur-grab tick while any panel is open. Originally-confirmed leak (matches "main chrome"). |
| `sleep_timer.py:188` (preset-ramp color) | **Yes** | "Called on every theme change... AND on every fade/timer state change." Originally-confirmed leak. |
| `speed_controls.py:271` (preset-ramp color) | **Yes** | "Called on every theme change... AND on every speed/step/undo/skip/smart-rewind state change." Originally-confirmed leak. |
| `app.py:875` (`_reload_excluded_books`) | **Yes** | "Called on each settings-panel open." **Not in the original four.** |
| `app.py:2630` (`_on_speed_right_clicked`) | **Yes** | Speed-button shimmer color, reachable from main-window chrome with no panel open at all. **Not in the original four.** |
| `app.py:491` (`_setup_ui`) | No — startup only | One-shot EOF revert icon construction. |
| `main_window_builders.py:579/594/627` | No — startup only | One-shot `build_*` construction calls. |

**7 runtime call sites (3 more than the original four), 4 startup-only.** No other occurrences
exist anywhere in `src/` or `tools/` — exhaustive, not sampled.

---

## 2. Structural fix implemented: make `get_current_theme()` itself safe by construction

```python
def get_current_theme(self) -> dict:
    from ..themes import _resolve_theme
    return _resolve_theme(self.get_active_theme())
```

One-line internal change, zero call-site churn — every call site keeps its `.get(...)`-style
access unmodified; `_resolve_theme` already accepts both a `str` and a `dict` (confirmed at current
HEAD, `themes.py:3030-3044`).

Rejected alternatives: **(a)** migrate every call site to `get_active_theme()` directly — rejected
because that accessor returns a raw name/dict, not resolved, so every site would need its own added
`_resolve_theme(...)` wrap — more surface area for the exact mistake this bug already demonstrated.
**(b)** rename `get_current_theme()` to signal danger — rejected because it keeps a live foot-gun
under a new name; only helps if every future caller reads the name correctly, which is exactly how
the original gap formed. **(c) wins**: the safe behavior becomes the only behavior reachable under
either name, unconditionally, for every current and future caller.

No caller anywhere needs a hover-inclusive read — verified directly: the Themes tab's own live
preview goes through `_apply_stylesheets`'s hover-aware fast path with explicit `theme_name`/`hover`
arguments, never through either accessor.

---

## 3. Stuck-state clearing: `clear_stale_hover_state()`, hooked into `_on_settings_hidden`

```python
def clear_stale_hover_state(self):
    if self._is_hover_active:
        self._mark_theme_applied(self._current_theme_name, False)
```

Hooked into `PanelManager._on_settings_hidden` — confirmed by grep to be the **sole**
`settings_panel.hide()` call site anywhere in the codebase, so every close path (Esc, dismiss
click, `hide_all_panels`, opening a different panel) funnels through it regardless of trigger.

Deliberately **not** merged into `_check_swatch_still_hovered` (a narrow, periodic backstop for a
different question — "is the cursor still on the swatch," not "is Settings even open" — with its
own design doc explaining why it must stay narrow).

Reuses `_mark_theme_applied` (the sole writer of both fields) rather than setting them directly, so
it correctly also stops `_swatch_leave_backstop_timer` via that method's existing arm/disarm side
effect. Confirmed via direct read of `_close_settings_flow`/`snap_theme_forward` that
`_fade_in_flight` is guaranteed `False` by the time `_on_settings_hidden` fires — `snap_theme_forward`
clears it unconditionally, synchronously, before the close-slide animation even starts.

Independent of the July 21/22 confinement fix's three `_pending_fade_call` drain sites, of
`_panels_settled_waiters`/`coalesce_key="theme_change"`, and of `check_cursor_on_settle` (open-only,
never close) — confirmed by direct code reading, no shared state or call graph.

---

## 4. Cost

Zero new cost. Both changes are internal substitutions — no new restyle, no new object
construction, no new timer.

---

## 5. Verification — full results

- **Full test suite**: baseline 435/435 passing before any change; 440/440 passing after (435 + 5
  new), zero regressions.
- **Live repro** (`_on_settings_hidden()` called directly against a deliberately-stuck hover state):
  `_active_display_theme_internal`/`_is_hover_active` corrected to the real active theme
  **immediately**, not eventually.
- **Non-hover regression check**: `get_current_theme()` and `_resolve_theme(get_active_theme())`
  confirmed byte-identical across three themes in the ordinary non-hover case.
- **All 7 runtime call sites, individually, live-verified** with genuinely discriminating
  active-vs-hover theme values (`Alzabo` for the Speed shimmer's `button_speed_shimmer`, `Hear Me
  Roar` for the search-error color — both customize keys most themes leave at the shared default,
  so the first pass's two "coincidentally identical" results were re-run against themes that
  actually diverge): every site returns the active theme's value while `_is_hover_active=True` is
  forced, and after `clear_stale_hover_state()` runs.
- **New test file** `tests/test_get_current_theme_hover_safety.py` (5 tests): core hover-safety pin,
  non-hover equivalence, live-cover-theme-while-hovering behavior inherited correctly from
  `get_active_theme()`, `clear_stale_hover_state()`'s field correction + backstop-timer stop, and its
  no-op behavior when hover isn't active.

## Confirmation this closes the July 20 audit's gap

The July 20 audit's own inventory already listed `get_current_theme()` as an existing unsafe read
path serving multiple callers at the time `get_active_theme()` was introduced — the fix left it
completely untouched. This design closes it structurally: after this fix, `get_current_theme()` and
`get_active_theme()` return hover-safe results by construction, from every call site, present and
future — there is no longer a third, easier-to-reach, unsafe name anyone could accidentally use
instead.

## Files changed

- `src/fabulor/ui/theme_manager.py` — `get_current_theme()` redefined; new
  `clear_stale_hover_state()`.
- `src/fabulor/ui/panels.py` — one new call in `_on_settings_hidden`.
- `tests/test_get_current_theme_hover_safety.py` — new, 5 tests.

No changes to any of the 7 runtime call sites, `get_active_theme()` itself, `_mark_theme_applied`,
`_check_swatch_still_hovered`, the three `_pending_fade_call` drain sites, `check_cursor_on_settle`,
or `_panels_settled_waiters`/`coalesce_key`.
