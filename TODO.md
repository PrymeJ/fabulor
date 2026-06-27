# TODO

Deferred work — short, dated, status-tracked entries. Not for root-cause writeups (those go in
NOTES.md) or session logs (SESSION.md). When an entry is started, move it under "In Progress" with
the date; when done, delete it (the commit/SESSION.md entry is the permanent record).

## Pending

- **[2026-06-27] Distinct icon for `is_missing` books (gravestone vs. ghost).** `is_missing` (added
  this session to fix the excluded-books ping-pong) is currently folded into the existing
  `_is_archived`/`is_archived` checks in `stats_panel.py`/`book_detail_panel.py`/`tag_manager.py`, so
  a missing-from-disk book shows the same `ghost.svg` as a user-excluded or location-removed book.
  No `gravestone.svg` (or similar) asset exists yet; sourcing one was explicitly out of scope for the
  `is_missing` fix itself. Add the asset, then branch `BookDetailPanel._ghost_label`'s three call
  sites (init, refresh, theme-change — keep them in lockstep) on `is_missing` specifically.
- **[2026-06-27] Excluded Books popup (`ui/excluded_books.py`) theming gaps — four issues, found via
  live screenshot comparison on a flamboyant/cyberpunk-style theme:**
  - On at least one such theme, row text and the eye icon are barely visible against the popup's
    `bg_deep` background — needs a per-theme override (or a contrast-aware fallback) for this
    specific theme, not just the popup's general color keys.
  - The popup's `::item:selected` highlight (`dropdown_curr_chap`) and `settings_folder_list`'s own
    selection highlight read as visually inconsistent side-by-side in the same screenshot — different
    colors entirely (not just hue, looks like two different theme keys or fallback paths winning).
  - Corner radius mismatch: the popup's selection highlight is flat/square; `settings_folder_list`'s
    is rounded. Should match (one or the other) since they're both "selected row in a themed list"
    in the same panel.
  - Background color mismatch between the two same-panel list surfaces (popup vs. folder list) —
    they don't read as part of the same design system in a single screenshot even though each looks
    fine in isolation.
  Not urgent — deferred by explicit instruction ("not going to deal with these now"). Revisit
  together as one pass over `excluded_books.py`'s `set_theme` + `themes.py`'s `dropdown_curr_chap`/
  `bg_deep` keys, probably alongside the cyberpunk-style theme(s) that surfaced it.

- **[2026-06-25] Shimmer plays on speed right-click even when speed is already default.**
  `_on_speed_right_clicked` always plays the shimmer animation; it should skip it when current speed
  already equals the default speed, since there's nothing to reset. See NOTES.md "TODO (before
  release): suppress shimmer when speed is already the default" (~line 1006).
- **[2026-06-25] Tag action button's check→delete revert timer can fire mid-edit.** After a tag
  rename, an unguarded `QTimer.singleShot(2000, ...)` reverts the action button's visual state; if
  the user starts a new edit within that 2s window, the revert can fire mid-edit and silently undo
  the in-progress state. Low-priority UX papercut, not a correctness bug. Fix: capture/cancel the
  timer when a new edit starts. See NOTES.md "tag action button check → delete 2s timer" (~line
  1568).
- **[2026-06-25] Cover Panel: no duplicate-cover detection.** Adding the same cover image twice (via
  `_on_add_cover`, cover_panel.py:497) creates redundant files and DB rows with no content-hash or
  size/dimension check. Implement before the 4-slot cap becomes a felt constraint — a duplicate
  wastes a slot. See NOTES.md "Duplicate cover detection not implemented" (~line 2097).
- **[2026-06-25] Pre-release cleanup pass (bundle into one commit, not piecemeal):**
  - Remove the `Q`-key quote-rotation shortcut (`app.py`, testing-only — already flagged inline as
    `# TODO: remove before release — testing only` at app.py:1947).
  - Remove debug `print()`/timing instrumentation left over from VT debugging in `_close_session`,
    `_on_file_ready`, `_on_book_selected_from_library`.
  - Switch the VT playlist-resolution temp files (`ffmetadata`/`concat` in `_resolve_playlist`) from
    `delete=False` to `delete=True` (or add explicit cleanup) once VT is considered stable — they
    currently accumulate in `/tmp` across sessions.
  See NOTES.md "Cleanup Deferrals — Pre-existing, Deliberate" (~line 2108) for all three.
- **[2026-06-25] Re-verify: chapter nav undo/restore near boundaries.** A 2026-05-16 NOTES.md entry
  ("Deferred — chapter nav undo/restore near boundaries", ~line 2087) lists three bugs: Undo doesn't
  appear after Next, Undo after Prev drifts the chapter slider to the far right, and
  `apply_smart_rewind`/Undo restore used raw `time_pos =` assignment in some paths. This predates the
  Session 3 (2026-06-13) chapter-seek precision rework, which unified chapter nav (including
  embedded-M4B clicks) onto `seek_async` with calibrated offsets — these bugs may already be fixed as
  a side effect. Confirm whether they still reproduce before doing any work; if fixed, delete this
  entry instead of carrying it forward.

- **[2026-06-23] Volume slider/muted icon don't accept wheel-scroll while visible.** Only
  `visual_area` (the cover art) currently handles volume wheel events (`wheelEvent` in `app.py`).
  Scrolling directly over the volume slider or the muted icon while either is visible/showing is a
  no-op, which is surprising — muscle memory expects scrolling over a volume control to adjust it,
  especially right after it's been shown. Needs care: if the empty space *around* where the slider
  appears (within `vol_stack`'s 104×24 box) also accepts scroll, that could itself feel inconsistent
  once the box is empty/hidden again. Decide the exact hit-region before implementing.
- **[2026-06-23] Slider→muted-icon transition is abrupt.** When volume hits 0% with no sleep timer
  active, `_show_volume_overlay` jumps straight to the muted icon with no transition (see
  `ed563a4`/`81734d3` — this was a deliberate choice to skip the slider preview, not an oversight).
  Visually it reads as a hard cut. Idea floated: a quick two-sided mask/wipe that conceals the
  volume bar first, then reveals the muted icon, rather than an instant swap. Needs a concrete
  animation design before implementing — not just "add a fade."
- **[2026-06-23] Clicking the muted icon (and a future `M` key) should restore volume — to what
  value?** Naive "restore to 100%" is probably wrong. Likely wants the same kind of "value before
  manipulation started" capture that `Player.save_seek_position`/`undo_seek` already use for
  seeking (one-level undo, captured at the start of a manipulation). Needs its own capture point
  for volume — probably at the first wheel/drag/key event of a manipulation "session," not on every
  change. Design this alongside the `M` key shortcut, not before — see git history around
  `ed563a4` for the muted-icon work this builds on.
- **[2026-06-23] Arrow-key volume control (if/when added) must integrate with the auto-hide timer
  the same way wheel/click/drag do.** Whatever wires up arrow keys for volume needs to call through
  the same path as `_on_volume_changed`/`_show_volume_overlay` (see `64e75cc`), not a separate one —
  otherwise the overlay could disappear mid-keypress the same way dragging used to before that fix.

- **[2026-06-19] Remove theme inheritance from "The Color Purple."** Every theme currently resolves
  via `_resolve_theme()` as `THEMES["The Color Purple"].copy()` overlaid with the requested theme's
  own dict — any key a theme doesn't define falls back to Purple's literal value, not to that
  theme's own derived fallback (e.g. an accent-derived color). `_NO_BASE_INHERIT_KEYS` in
  `themes.py` is a manually-maintained escape hatch for keys where this is wrong, and it's easy to
  forget to update when adding a new optional key (see CLAUDE.md rule on `_NO_BASE_INHERIT_KEYS`,
  added 2026-06-19). Made sense early when Purple was a stable default; doesn't anymore — Purple
  probably won't even ship as the default theme. Target design: no theme inherits literal values
  from another theme; every key is either required (defined in all themes) or has a documented
  code-level fallback chain, never "whatever the base template happened to set."
  **Blocked on:** user's planned full pass over every theme (adding keys where current fallbacks
  don't look right) — doing the inheritance refactor before that pass would only have a partial
  picture of which keys actually need it. Revisit once that pass is done.

## In Progress

(none)
