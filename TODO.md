# TODO

Deferred work — short, dated, status-tracked entries. Not for root-cause writeups (those go in
NOTES.md) or session logs (SESSION.md). When an entry is started, move it under "In Progress" with
the date; when done, delete it (the commit/SESSION.md entry is the permanent record).

## Pending

- **[2026-06-21] StreakGrid left-gutter date labels clip "J" ("Jun 21"/"Jul 20" -> "un 21"/"ul 20").**
  `AlignRight`-anchored "Mon DD" text at 9pt is wider than the 29px gutter rect; the overflow is
  normally invisible (side-bearing whitespace) but "J"'s descender hook is real ink that sits in the
  overflow band and gets clipped at the widget's left edge. See NOTES.md "HourlyHeatmap top date
  labels: 'J' clipped" (2026-06-21) for the four approaches tried and rejected (widening the rect
  pushes the other end into the cell grid; 8pt alone still clips; 7pt fixes it but was rejected as
  illegibly small with too much dead gutter whitespace). **Blocked on:** a format/layout idea that
  keeps the label readable at a normal size without widening past `GUTTER_W` (shared, fixed-size
  with `HourlyHeatmap` for the tab transition). Candidate not yet tried: numeric `M/D` format
  (shorter; digits don't have "J"'s ink-outside-advance-box problem) — flagged to the user, not yet
  decided on.

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
