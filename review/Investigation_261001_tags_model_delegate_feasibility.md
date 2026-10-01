# Investigation: feasibility of migrating Tags to a model/delegate pattern

**Date:** 2026-10-01
**Scope:** `src/fabulor/ui/tag_manager.py` (`TagManagerWidget`, `_TagBookGrid`, `_TagBookThumb`) as
of commit `4fd94f4`. Triggered by the TODO.md entry "Tags panel: count display and widget-per-row
architecture" (2026-09-17), which flagged — correctly, by reading the source rather than assuming
— that both the tag list and the per-tag book grid are widget-per-item, the same shape Stats had
before its 2026-08-05/09 migration to `StatsRowModel`/`StatsRowDelegate`
(`review/Spec_260805_stats_lazy_delegate.md`). This document answers the feasibility question that
TODO entry asked for, before the cheap "N/50" display feature is built on top of either shape.

## Verdict

**Migrating the tag LIST to a model/delegate pair is straightforward and worth doing if the cap is
ever raised. Migrating the per-tag THUMBNAIL GRID is not a good trade at today's scale — the
keyboard-navigation machinery built on top of widget-per-cell is large, already working, and has no
clean equivalent in a model/delegate world.** Recommend: migrate the list now or next time it's
touched; leave the grid as-is unless the per-book-tag limit (currently 5) or real usage patterns
change enough to make widget cost the bottleneck.

## What actually scales, and by how much

Two independent caps bound this feature today:

- `add_book_tag` (`db.py:1476`) enforces a **global cap of 50 distinct tags** (`global_count >= 50`)
  and a **per-book cap of 5 tags** (`count >= 5`).
- So the **tag list** can have at most 50 rows — not 5,000, not 500. This is the direct comparison
  point to Stats, which scales with *listening history* (unbounded, grows every session) — a
  structurally different growth curve. 50 widgets is not what the Stats migration was fixing.
- The **per-tag book grid** (`_TagBookGrid`) has no cap of its own: a single tag can be applied to
  every book in the library (each book just spends one of its 5 slots on it). This is the one place
  where "widget-per-row" could genuinely scale with library size (CLAUDE.md's own order-of-magnitude
  testing rule: design against 3000-5000+ books, not the ~400 on hand). **This is the part of the
  TODO entry's concern that is real** — a popular tag ("fiction", "finished", etc.) applied to
  hundreds of books would build hundreds of `_TagBookThumb` widgets at once.

So the TODO's framing ("both... are widget-per-row, the same shape Stats moved away from") is
correct as an architectural observation, but the two halves don't carry the same urgency:

| | Tag list | Book grid |
|---|---|---|
| Bound | Hard cap, 50 | None — can equal entire library |
| Current real-world size | ~dozens | Likely tens at most (from a ~400-book library), but no cap |
| Widget cost per item | 1 row (`QLabel`+`QLabel`+dot) | 1 thumbnail (`QLabel` + lazy cover load + focus ring) |
| Keyboard nav built on top | Yes — full kbdnav row/typeahead system | Yes — full kbdnav grid system (row/col, hover pickup) |

## Why the list is a clean migration candidate

`TagManagerWidget`'s tag list is already close to the shape `StatsRowModel`/`StatsRowDelegate`
wants: a flat, sorted, external list (`db.get_all_tags()`) painted into fixed-height rows
(`_TAG_ROW_HEIGHT`/`_TAG_ROW_PITCH`), with a single keyboard cursor index
(`_kbdnav_row_index`) and a single mouse-hover tracker (`ScrollHoverTracker`). This is structurally
the same problem Stats solved: `StatsRowModel` (a `QAbstractListModel`) backs `StatsRowListView` (a
real `QListView`), and `StatsRowDelegate` paints each row — including hover/keyboard-selected fill —
without a widget per row.

What would need to move, concretely:
- The row's visual content (dot, name, book-count badge) → delegate `paint()`, same pattern as
  `StatsRowDelegate`.
- `ScrollHoverTracker` → native `QListView` hover (a real `QListView` re-evaluates the hovered
  index on scroll correctly; the tracker exists specifically because the *old* widget-per-row shape
  needed it — see `hover_tracker.py`'s own docstring on why `:hover` QSS goes stale on scroll. A
  `QListView` with `setMouseTracking` + `entered`/row-under-cursor handling doesn't have this
  problem the same way).
- `_kbdnav_row_index`, Up/Down/PgUp/PgDn/Home/End, and the type-ahead buffer → straightforward,
  index-based, no change in shape (same index-into-a-list concept, just backed by a model row
  instead of a widget list).
- Rename/color-picker/delete-confirm UI stays exactly as-is — those live in the DETAIL sub-panel
  (`_panel_widget`), which is untouched either way.

At 50 rows max, this migration is not solving a performance problem today — it would be justified
by (a) removing per-row widget construction/teardown cost on every `refresh()` (currently rebuilds
all N row widgets from scratch, same "destroy and rebuild everything" pattern Stats' row list used
to have), and (b) making a future cap increase (explicitly "a real possibility this feature
invites," per the TODO) cheap instead of linearly worse.

## Why the book grid is a much larger, worse-trade migration

The thumbnail grid's widget-per-cell shape is carrying real, working functionality that has no
equivalent in the model/delegate world without being rebuilt from scratch:

- **`_ThumbFocusRing`/`_DotFocusRing`** are separate *sibling* widgets layered on top of each thumb
  specifically because "Qt paints a parent before its children" (documented in the thumb's own
  constructor comment) — a delegate-painted cell has no child widgets to layer a sibling over; this
  would become a second paint branch inside `StatsRowDelegate`-style `paint()`, which is doable but
  is new code, not a port.
- **`GridHoverTracker`** (`_thumb_hover`) answers "which thumbnail is the mouse over" for
  keyboard-cursor hover-pickup (`_handle_thumb_grid_keys`) — this logic is 2-D (row, col) aware,
  unlike Stats' 1-D row list. `QListView`'s `IconMode`/grid layout exists, but this codebase has
  already hit — and documented — that native `QListView` IconMode arrow traversal is unreliable for
  a custom grid shape (see CLAUDE.md: "native `QListView` IconMode arrow traversal was unreliable
  against this app's custom `sizeHint`/uniform sizing," which is why Library's own grid modes use
  hand-coded `±1-column moves` rather than native grid traversal). A migration here would be
  re-implementing the same hand-rolled 2-D nav Library already needed, on top of a *new* model/
  delegate pair, not reusing Stats' pattern directly.
- **Cover loading** (`CoverLoaderWorker`, `_cover_cache`) is already async/cached at the pixmap
  level — the per-widget cost isn't the cover I/O, it's the `QWidget` instances themselves
  (`_TagBookThumb.__init__` builds a layout + 2 labels + a focus ring per book). A delegate would
  remove that per-instance construction cost, which is the one piece of this that genuinely does
  scale with library size.
- **Per-session state that assumes "the widget still exists"**: `_kbdnav_pos` is re-applied onto
  freshly-rebuilt widgets after `_rebuild()` (clamping row/col to the new, possibly shorter list) —
  this pattern would need to become index-into-model-row the same way, which is fine in principle,
  but every one of the five `_TagBookGrid` methods that currently do `self._grid.itemAtPosition(...)`
  to find a widget (`_apply_kbdnav_visual`, `pos_of`, `kbdnav_current_path`, etc.) would need a
  parallel model-row rewrite.

None of this is impossible — it's the same category of work the Stats migration already proved
tractable. But the investigation's job is to weigh cost against benefit, and here the benefit is
speculative (no cap exists to raise, and real per-tag book counts are nowhere near library-scale in
practice) while the cost is a full rebuild of a non-trivial, already-debugged keyboard/mouse
coexistence system (`ScrollHoverTracker`/`GridHoverTracker`, two focus-ring widget classes, hover-
pickup, 2-D arrow nav) with several previously-fixed live bugs riding on the current shape (see this
file's own in-code history: the `set_kbdnav_pos` ordering bug fixed 2026-09-15, the Tab/eventFilter
reinstall-on-blur-grab fix, etc.) — each of which would need to be re-verified, not assumed to carry
over, against new code.

## Recommendation

- **Don't migrate the book grid now.** No cap exists on it, so there's no scaling number driving
  this analogous to Stats' unbounded listening history. Revisit only if real usage shows a single
  tag routinely applied to hundreds of books (would need a live report or telemetry, not a
  hypothetical), or if the per-book tag limit is raised well beyond 5 (unlikely — that limit is
  about keeping a book's own tag set scannable, not an architectural constraint).
- **The list migration is cheap enough to bundle with the cap-raise question, not before it.** Since
  the list is hard-capped at 50 today and the display feature (N/50, cap notification) doesn't
  itself require any architecture change, ship the display feature against the current widget-per-
  row list as planned. Treat the list's model/delegate migration as a prerequisite ONLY if/when the
  50-tag cap is actually raised — that is the trigger condition the original TODO entry was really
  pointing at, not the current size.
- **Net effect on the original TODO item:** the "N/50" display feature is unblocked and can proceed
  against the current architecture with no refactor first. The architecture question is answered,
  not deferred: migrate the list only when/if the cap changes; leave the grid alone.
