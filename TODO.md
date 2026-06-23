# TODO

Deferred work — short, dated, status-tracked entries. Not for root-cause writeups (those go in
NOTES.md) or session logs (SESSION.md). When an entry is started, move it under "In Progress" with
the date; when done, delete it (the commit/SESSION.md entry is the permanent record).

## Pending

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
