# Design: confine theme reads by write path, not by after-the-fact correction

**Date:** 2026-08-04  **Branch:** `investigate/restyle-cost-depth-and-narrowing`  **Status:**
Design approved and implemented same day.

## Context

The `get_active_theme()` → `get_displayed_theme()` redesign (`review/Design_260804_hover_state_
computed_read_path.md`, shipped as `5630cf0`) set out to fix hover-preview colors leaking into
panels that should never show a live preview. It fixed the *external-reader* half of that problem,
but live testing the same day found the leak was never actually about `get_active_theme()`'s own
logic — it was about several consumers **never going through that function's confinement at all**.
`LibraryPanel._on_view_mode_changed`/`refresh`/`_refresh_search_match_state`, and Speed/Sleep's
`update_visuals()`/`update_panel_styling()` (each covering several of their own state-change call
sites), called `theme_manager.get_current_theme()` directly, from ordinary UI events — a view-mode
click, typing in search, clicking a preset button — that have no relationship to a theme change.
Since `get_current_theme()` now resolves through the live, hover-inclusive `get_displayed_theme()`,
any one of those unrelated clicks could bake a currently-hovered Themes-tab swatch's colors into a
panel the user isn't even looking at, with nothing to ever correct it except an unrelated later
theme-apply cycle (confirmed live: up to 78 seconds of staleness — see NOTES.md 2026-08-04).

Pryme rejected fixing this with a catch-up/re-sync call (already tried twice the same day —
`clear_stale_hover_state`, and a "add a catch-up call to each `_start_*_entry`" proposal) and named
the actual invariant that should hold: **"Anything invisible has no business calling anything to get
a new color. As long as there is no right-click, those other panels shouldn't even know what was
previewed. The active theme never changes unless there is a deliberate right-click."** The fix has
to be at the write/read path itself — these consumers should never be able to observe a hover in the
first place — not a mechanism that detects and corrects a wrong observation after it happens.

## Required-first-step finding: `_current_theme_name` was already correct and sufficient

Traced every write site directly (not inferred from the name):

- `theme_manager.py` `ThemeManager.__init__` — random pick from the rotation pool at app launch.
  Construction-time; no hover exists yet.
- `theme_manager.py` `_do_rotate` (auto-rotation timer, or the "Change now" button). Both are
  deliberate commit events, not a hover.
- `theme_manager.py` `toggle_theme_selection` (left-click add/remove from the rotation pool), only
  in the edge case where the removed theme was the current one and a replacement must be picked so
  the pool is never empty with no active theme. A left-click, not a hover.
- `theme_manager.py` `_on_theme_right_clicked` — the deliberate commit action named in Pryme's rule,
  verbatim.

**Confirmed negative**: `_mark_theme_applied` is, by its own docstring, the **sole writer of
`_active_display_theme_internal`/`_is_hover_active`** — never `_current_theme_name`. These are two
structurally disjoint fields with disjoint writers. No hover code path touches `_current_theme_name`
anywhere. It already was exactly the value Pryme described: written only on a deliberate
right-click/rotation-commit/pool-edit, never on a hover.

**No new field, method, signal, or synchronization mechanism was needed.** The fix: point every
identified leak site at the existing `_current_theme_name`, via one new thin accessor.

## Names introduced

Deliberately avoiding "current"/"active"/"displayed" in combination with each other, since that
confusion had already caused real reasoning mistakes the same day:

1. **`get_committed_theme()`** — new, thin accessor returning `self._current_theme_name` directly.
   The theme committed by a deliberate right-click/rotation/future Enter-equivalent, never
   hover-touched. What every "invisible panel" consumer should read.
2. **`get_displayed_theme()`** — unchanged, kept as-is. The live/hover-inclusive concept: "what is
   genuinely painted in Settings/the main window right now." `get_active_theme()`/`get_current_
   theme()` remain thin wrappers over it, unchanged, for genuine live-preview-rendering consumers.

## Full re-audit of every `get_current_theme()`/`get_active_theme()`/`get_displayed_theme()` call site

Re-grepped fresh rather than trusting the list assembled earlier the same day (which had already
missed one site once):

| Site | Trigger | Classification | Action |
|---|---|---|---|
| `library.py` `_resolve_theme_colors` (all 3 callers: `update_progress_bar_theme` via the TAIL, `_on_view_mode_changed`, `refresh`) | Mixed — one confinement-clean TAIL caller, two ordinary UI events | Leak (2 of 3 callers) | **Fixed**: whole method now reads `get_committed_theme()` — the TAIL caller loses nothing, since `_schedule_deferred_restyle` only ever fires `hover=False` anyway |
| `library.py` `_refresh_search_match_state` | Typing in the search field | Leak (found on re-audit, not in the original list) | **Fixed**: reads `get_committed_theme()` |
| `speed_controls.py` `_apply_preset_ramp_colors` (called from the TAIL and from `update_visuals()`'s 6 state-change sites) | Mixed, same shape as Library | Leak (6 of 7 callers) | **Fixed**: whole method now reads `get_committed_theme()` |
| `sleep_timer.py` `_apply_preset_ramp_colors` (called from the TAIL and from `update_panel_styling()`'s 3 state-change sites) | Mixed, same shape | Leak (3 of 4 callers) | **Fixed**: whole method now reads `get_committed_theme()` |
| `app.py` `_reload_excluded_books` | Settings-panel-open, Library tab (Excluded Books popup) | Leak — invisible during any hover (Library tab and Themes tab are mutually exclusive within Settings) | **Fixed**: reads `get_committed_theme()` |
| `app.py` `_setup_ui` (EOF revert-icon pixmaps) | App construction | Harmless (no hover exists at construction time) but conceptually a permanent-chrome consumer | Left unchanged — construction-only, out of the confinement's practical concern |
| `app.py` `restyle_for_backdrop_change` → `get_active_theme()` | Panel-backdrop mode click, while some panel is open | Live-preview consumer — documented 2026-07-28 bug if `_current_theme_name` is used here instead (doesn't resolve a live cover-theme dict) | **No change** |
| `app.py` `_set_bg_suppressed` → `get_active_theme()` | Book-load/empty-state transition, paints `content_container` | Live-preview consumer — main-window chrome is an intended preview surface; also structurally unreachable during hover (`is_overlay_open_or_committed()`) | **No change** |
| `app.py` `_on_speed_right_clicked` → `get_current_theme()` (main-window speed-button shimmer) | Right-click on the always-visible transport-bar button | Live-preview consumer — visible regardless of panel state | **No change** |
| `transport_bar_blur.py` `frost_panel_backdrop` → `get_current_theme()` | Every blur-grab tick while a panel is open | Live-preview consumer — always frosts whichever panel is currently open, including Settings mid-hover | **No change** |
| `main_window_builders.py` (Stats/Tags/Book Detail construction) | App construction only | Harmless — live updates go through the `theme_applied` signal, which carries the already-scheduled, confinement-clean `theme_name`, never a fresh live call | **No change** |
| `app.py` `_show_carousel`/`_placeholder_color` (already read `theme_manager._current_theme_name` directly, not through any public accessor) | Main-window no-book state / cover placeholder | Already correct — main-window chrome, an intended preview surface, and already bypassing `get_current_theme()` entirely via the private field | **No change** (noted as already-correct, not touched) |

**Six leak sites fixed.** The deferred-restyle TAIL and the three-drain-site confinement guard
(`_on_fade_finished`/`snap_theme_forward`/`complete_main_fade`) needed no change — confirmed clean:
`_schedule_deferred_restyle` is the sole writer of `_deferred_restyle_theme`, gated `if not hover` at
its one call site; `_flush_deferred_restyle_now` reads back that same captured value, never a live
one. The guard protects `_pending_fade_call` replay specifically, which was never the mechanism at
fault — none of the six leak sites went anywhere near it.

## The change, per leak site

One new method:

```python
def get_committed_theme(self) -> str:
    return self._current_theme_name
```

Then, at each leak site, the direct `theme_manager.get_current_theme()` call was replaced with
`theme_manager.get_committed_theme()` (resolving through `_resolve_theme()` where a dict was needed,
since `get_committed_theme()` deliberately returns a bare string — none of the six sites ever needed
a live cover-theme dict). No signature changes, no new parameters, no timing changes — a one-line
substitution (or, for the two ramp functions and `_resolve_theme_colors`, one substitution shared by
all of that method's callers, since none of them legitimately needed the hover-inclusive answer).

## Verification — synthetic, not live-manual, and why

Per the CLAUDE.md rule added the same day ("Settings' Themes tab and every other panel... are
mutually exclusive... verification of hover-confinement fixes must be synthetic/instrumented, never
assumed reachable by live manual interaction"): a live click sequence can only ever observe
"hover, then close Settings, then trigger the site" — by which point the hover has already ended,
and there is no way to distinguish "the fix worked" from "the hover ended for an unrelated reason
before the site fired." `tests/test_write_path_confinement.py` instead forces
`_is_hover_active=True` with `_active_display_theme_internal` set to a theme deliberately different
from `_current_theme_name`, calls each of the six fixed consumers directly (via minimal fakes
mirroring this project's existing `_FakeTM` pattern), and asserts the committed theme was used, never
the forced hover value. 8 tests, all passing; full suite 450/450 (442 baseline + 8 new), matching
baseline with no regressions.

The temporary probes added earlier the same day (`[LIBRARY-THEME-WRITE]`, `[COMBO-ARROW-PAINT]`,
`[PANEL-SHEET-STASH]`/`[PANEL-SHEET-CATCHUP]`) remain in place as an independent, live cross-check —
useful for confirming the ordinary case still looks right, but per the reasoning above, not a
substitute for the synthetic tests for the hover-confinement claim itself.
