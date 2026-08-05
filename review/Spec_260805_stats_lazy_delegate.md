# Spec_260805_stats_lazy_delegate.md — Stats Day/Week/Month lazy delegate-painted rows

Design document only — no implementation in this pass. Produced from a read-only investigation
pass over the current codebase (post-commit `a2cc381`); every claim below is grounded in a
file:line citation gathered during that pass, not assumed.

## Context

`BookDayRow` represents one book entry and is reused identically across the Day/Week/Month tabs
(they differ only in which DB query feeds rows). `FinishedBookThumb` plays the same role for the
"Finished this period" strip. Direct measurement established that the dominant per-row cost when a
rebuild fires is **not** pixmap decode — covers already load asynchronously via `CoverLoaderWorker`
(fixed prior to this investigation) — but generic Qt widget/layout construction: nested
`QHBoxLayout`/`QVBoxLayout`, multiple `QLabel`s, `ElidedLabel` font/elision work, stylesheet/
object-name assignment, and a `findChildren` + `WA_TransparentForMouseEvents` sweep. Measured at
~70% of per-row time (median ~3.1ms of ~3.9ms total), scaling linearly at 8-13ms/row.

A rebuild-avoidance guard (commit `a2cc381`) already skips the full rebuild when a content
signature over the fetched rows is unchanged since the last build. That guard is **out of scope**
here — this document is specifically about replacing the per-row eager widget construction itself
with lazy delegate-painted rows for the cases where a rebuild still fires (a genuinely new/changed
period).

`StreakGrid` is explicitly out of scope — it's a 2D density grid with non-uniform per-cell content,
not a scrollable list, and doesn't fit this pattern.

Rows are uniform-height (one book per row), mapping cleanly onto Library's List-mode sizing
approach. This is not a variable-height/grouped-row design problem.

---

## 1. Model design

**Recommendation: one shared `StatsRowModel(QAbstractListModel)`, parameterized by period kind, not
three separate model classes.**

All three DB calls the current refresh methods use —
`get_daily_book_breakdown(date_str, day_start_hour)` (`db.py:640-674`),
`get_books_listened_in_period(granularity, period_label, day_start_hour)` (`db.py:872-908`), and
`get_finished_in_period(granularity, period_label, day_start_hour)` (`db.py:910-935`) — return
identically-shaped row dicts: `book_id`, `book_path`, `book_title`, `book_author`,
`book_duration`, `clock_seconds`, `book_seconds_advanced`, `furthest_position`, `cover_path`,
`is_deleted`, `is_excluded`, `is_missing`, `is_finished`, `period_position_start`,
`period_position_end` (confirmed at `db.py:644-673` and `db.py:878-907`). The only per-tab
difference is which `db.get_*` method is called and how the period label is formatted for display.
A single model class parameterized by which DB call it wraps avoids three near-duplicate classes
with no real behavioral difference.

**Roles exposed** — one role per field `BookDayRow.__init__` actually renders today (confirmed at
`stats_panel.py:438-598`): title (`512`), author (`544`), duration (`551`), clock_seconds (`528`),
period_position_start/end (`552-553`), is_finished (`507`), book_path (`471`), cover_path (`472`),
active_cover_path (`482`), book_id (`485`), and the three soft-delete flags (`458-461`). Two fields
returned by the DB but not rendered by `BookDayRow` — `book_seconds_advanced` and
`furthest_position` — are still consumed by the existing signature guard
(`_period_rows_signature`, `stats_panel.py:4159-4195`) and should remain available as roles even
though no paint code reads them directly, so the model stays a faithful mirror of the row dict
rather than a lossy projection.

**Data entry point**: `set_rows(rows, finished)`, called by `_refresh_*` in place of the current
widget-construction loop (see §4). The model does **not** own or duplicate
`_period_rows_signature`/the `_day_built_sig`-style cache — that logic stays exactly where
`a2cc381` put it, in `stats_panel.py`. The model is a dumb data holder; the decision of *whether*
to call `set_rows` at all is the caller's, unchanged from today's decision of whether to run the
widget-construction loop.

**Transformation to preserve**: `_inject_active_covers(rows)` (`stats_panel.py:4152-4157`) must
still run before the model receives rows — it's a synchronous, uncached `db.get_active_cover_path`
call per row that adds `active_cover_path` in place. This is unrelated to the model/delegate
change and stays exactly as-is; it is called once per `_refresh_*` invocation today and would
continue to be. Likewise the ≥60s filter currently applied to `rows` (but not `finished`) —
`[r for r in rows if (r.get("clock_seconds") or 0.0) >= 60]` (`stats_panel.py:3470`, `3684`,
`3879`) — happens before `set_rows`, not inside the model.

---

## 2. Delegate design

**Recommendation: a new `StatsRowDelegate(QStyledItemDelegate)`, not a `BookDelegate` subclass.**

Confirmed non-reusability: `BookDelegate.paint()` (`library.py:2650-2675`) hardcodes `BookModel`'s
custom role contract (`ROLE_BOOK`, `ROLE_COVER`, etc., `library.py:1929-1934`) and dispatches
through five Library-only view-mode paint methods; `editorEvent()` (`library.py:2679-2728`)
implements Library-specific click-to-filter arming and remaining/total toggling keyed on
`book.path`/`book.id` from a `BookModel`-shaped model argument. None of this transfers to a single
uniform Stats row layout. `sizeHint()` reads `ITEM_DIMENSIONS`, a Library-only constant covering
Library's five view modes — not applicable here.

**Paint logic**: modeled on the single row layout `BookDayRow` currently builds via nested
`QHBoxLayout`/`QVBoxLayout` — title, author, duration/clock_seconds, a position indicator, cover
thumbnail — but hand-painted directly in `paint()` rather than built as child widgets. This is the
entire point of the change: it eliminates the per-row `QLabel`/layout/stylesheet construction cost
that measurement identified as ~70% of the per-row time.

**Cover sourcing** — reuse existing infrastructure exactly, do not invent a new mechanism:
- Read `_cover_cache` (`library.py:165`) directly. It's a genuine module-level singleton keyed by
  `book_id`, already imported and used directly by `stats_panel.py:20` and by
  `BookDayRow`/`FinishedBookThumb` today — no changes needed for a new delegate to read from it.
- On cache miss, dispatch `CoverLoaderWorker` in **raw mode** exactly as `BookDayRow` does today
  (`stats_panel.py:490-496` and equivalents) — construct with a duck-typed object exposing `.id`,
  `.path`, `.cover_path`, connect its `cover_loaded = Signal(int, QImage)` signal, `start()` via
  `QThreadPool.globalInstance()`. On completion, write to `_cover_cache` and emit `dataChanged` for
  the relevant model index (via `book_id → row index` lookup) instead of the current direct
  widget-repaint call — this is the one real mechanical change cover-loading needs, and it's a
  signal-target change, not a new loading mechanism.
- Explicitly **do not** touch `_sized_cover_cache` or the LANCZOS sized-pixmap path
  (`_get_sized_cover`/`_draw_cover`, `library.py:3260-3285`, `3343-...`) — those are per-`BookDelegate`-instance
  caches Stats has never used (Stats only ever calls `CoverLoaderWorker` in raw mode; no call site
  passes `sized_target=`). Out of scope per the brief, and unnecessary — Stats rows are small enough
  that raw covers with normal Qt scaling in `paint()` are sufficient, matching current behavior.
- `_lanczos_qimage`/`_lanczos_scale` (`library.py:3287-3334`) are true `@staticmethod`s and are
  available for direct call if a future pass wants sharper scaling, but nothing in current
  `BookDayRow` behavior requires them — not part of this migration.

**Visible-row-only painting**: comes for free from standard `QListView`/`QAbstractItemView`
viewport dispatch once the model/delegate/view are correctly wired — Qt only calls `paint()` for
rows currently in the viewport. No manual visible-range tracking is needed for *painting*, unlike
Library's `_load_visible_covers` scroll-driven logic, which solves a different problem (deciding
which covers to *load*, not which rows to *paint*).

---

## 3. FinishedBookThumb / the "Finished this period" strip

**Recommendation: leave as-is. Do not migrate in this pass.**

`FinishedBookThumb` (`stats_panel.py:655-757`) is structurally simpler than `BookDayRow`: a single
child (`cover_label`) inside a `QVBoxLayout`, no separate text labels, no `WA_Hover` attribute, and
critically no container-level click-boundary workaround — `BookDayRow`'s
`_claim_container_input` (`stats_panel.py:3381-3436`) exists specifically to catch clicks on
inter-row boundary pixels that a documented live Qt bug fails to deliver, wired only for the
Day/Week/Month row containers (`stats_panel.py:3276`, `3595`, `3792`), never for
`FinishedScrollRow`. That problem doesn't apply here because there's only one child widget and no
adjacent-row boundary gap of the same shape.

Additionally, `FinishedScrollRow.set_items` already has its own signature-guard-style behavior per
the existing code comment (`stats_panel.py:3507-3509`) — it isn't paying the same "rebuild every
visit" cost `BookDayRow` was paying before `a2cc381`, and even before that fix its per-item cost is
inherently smaller (one `QLabel`-free cover widget vs. `BookDayRow`'s multiple labels + elision
work). The win from delegate-painting it would be proportionally smaller, and it introduces its own
risk (the missing container-fallback problem doesn't apply, but a new one might, unverified).
Migrating it is not worth the same treatment in this pass — it can be revisited separately if Day
tab's proof of concept proves the pattern out and there's appetite to extend it.

---

## 4. Migration plan

**Shape of the change to `_refresh_daily`/`_refresh_weekly`/`_refresh_monthly`:**

The `else` branch each currently runs when the rebuild-avoidance guard decides a rebuild is needed
— today, the `BookDayRow` construction loop (`stats_panel.py:3486-3500` daily, `3693-3706` weekly,
`3888-3901` monthly: clear layout down to the trailing stretch, `for i, row in enumerate(rows):
book_row = BookDayRow(row, ...); book_row.clicked.connect(...); self._add_row_safely(...)`) —
becomes a single `model.set_rows(rows, finished)` call instead.

**The guard's meaning shifts, but the guard itself does not change.** `_period_rows_signature`
(`stats_panel.py:4159-4195`) is reused **verbatim** — this migration does not redesign or
duplicate it. What changes is only what the `if`/`else` branches *do*: today, "skip" means "don't
run the widget-construction loop"; after migration, "skip" means "don't call `set_rows`" (i.e.
don't reset the model, so the view doesn't repaint and no `CoverLoaderWorker` dispatches
redundantly). The comparison logic, the cached `_day_built_period`/`_day_built_sig` fields (+
week/month equivalents), and their invalidation semantics are untouched.

**Must survive unchanged, cited per current line ranges:**

- **Empty-period branch** (`stats_panel.py:3443-3455` daily, `3656-3668` weekly, `3853-3865`
  monthly) — clears the view/model to empty, resets `_*_built_period`/`_*_built_sig` to `None`,
  sets the `"No activity yet"` label, clears the total label, disables both nav buttons, hides the
  Finished section, returns early. This branch's early-return means it should bypass model
  reset/paint entirely, same as today it bypasses widget construction.
- **Nav button enable/disable formula** (`stats_panel.py:3465-3466` daily, `3678-3679` weekly,
  `3873-3874` monthly) — `prev.setEnabled(index < len(periods) - 1)`,
  `next.setEnabled(index > 0)`. Entirely unrelated to the model/delegate change; must keep running
  every call, not gated on the rebuild guard.
- **Total-time label formula** (`stats_panel.py:3502-3505` daily, `3708-3709` weekly, `3903-3904`
  monthly) — sum of `clock_seconds` over the ≥60s-filtered `rows`, blank (not `"0m"`) when `rows`
  is empty but the day exists via a playback-finish with no qualifying session. Computed from the
  same `rows` list passed into `set_rows`, so this stays a plain Python computation next to the
  `set_rows` call, unaffected by whether the guard skipped the model reset.
- **Finished-section show/hide + viewport cap pairing** (`stats_panel.py:3510-3521` daily,
  `3711-3718` weekly, `3906-3913` monthly) — `_day_finished_scroll.set_items(...)` then
  `show()`/`hide()` on `bool(finished)`, followed by `_cap_rows_viewport(...)` and a
  `QTimer.singleShot(0, ...)`-deferred `_fixup_scroll_policy(...)`. This is the **highest-risk**
  piece to get wrong: the cap depends on a paired trailing `addStretch()` in the outer layout
  (`stats_panel.py:3361-3374`), and the existing code comment explicitly documents that
  `setFixedHeight`/`setMaximumHeight` alone were tried and reverted elsewhere in this codebase for
  the same "content drifts down from the top" failure mode. Swapping the rows area from a
  widget-per-row `QVBoxLayout` to a `QListView` changes what "viewport" and "cap" mean structurally
  — this needs explicit re-verification against the live app, not an assumption that the same
  cap/stretch trick still applies unchanged to a `QListView`.

---

## 5. Risk/unknowns

- **`_claim_container_input`'s fate is the single biggest open question.** It exists to work around
  a documented live Qt hit-testing bug where clicks on inter-*widget*-boundary pixels aren't
  delivered to the row widget underneath. A `QAbstractItemView`/delegate has no child widgets and
  no equivalent boundary gap — Qt's own item-view hit-testing may make this workaround entirely
  unnecessary. This should be verified empirically during the Day-tab proof of concept, not assumed
  away before building it.
- **Right-click parity is not free.** Today, both left- and right-click on `BookDayRow` trigger the
  identical `clicked.emit(row_data)` (`stats_panel.py:642-652`) — a `QStyledItemDelegate`/view
  combo needs this explicitly reimplemented (e.g. in the view's mouse event handling or
  `editorEvent`), it does not fall out of standard `QListView` click handling, which by default
  only reacts to left-click selection.
- **Hover visual feedback is QSS-driven today** (`:hover` on `objectName`s
  `stats_book_day_row`/`stats_book_day_row_alt`) — a delegate has no per-row QSS pseudo-state. This
  needs an explicit hovered-index property on the delegate/view plus a repaint-on-hover-change,
  following the pattern Library's own `BookDelegate` already uses for its hover states
  (`library.py`) — cite that as the model to follow rather than inventing a new hover mechanism.
- **`_inject_active_covers`'s per-row synchronous DB call is an existing cost this migration does
  not fix.** It's unrelated to widget-construction cost and stays exactly as-is (§1) — flagged here
  only as a candidate for a possible future batching pass, explicitly out of scope for this design.
- **No `eventFilter` was found installed by `stats_panel.py` on either widget class** — all
  interactivity is either baked into the widget's own handlers or (for `BookDayRow` only) the
  container-level fallback above. This means the delegate/view migration has a relatively small,
  fully-enumerated interactivity surface to replicate — not an open-ended "what else might the
  parent be doing to this widget" risk.

---

## 6. Incremental implementation order

1. **Day tab first**, as a proof of concept. Smallest data volume of the three tabs and the
   simplest period-label logic (`d.strftime("%A, %B") + " " + d.day`, `stats_panel.py:3461-3462`,
   vs. week's Monday–Sunday `strptime` computation or month's `strftime("%B %Y")`). Build
   `StatsRowModel`/`StatsRowDelegate` behind the Day tab only; Week and Month keep their current
   `BookDayRow`-construction path unchanged until Day is verified.
2. **Re-measurement checkpoint before extending further.** Re-run the same live, real-app,
   QTest-driven per-row timing methodology already used to establish the baseline numbers this
   document cites (median ~3.1ms/~3.9ms per row, 8-13ms/row at scale) against the Day tab only,
   post-migration. If the delegate-painted Day tab doesn't measurably beat the baseline, that's an
   explicit stop-and-reassess point — not a reason to proceed to Week/Month regardless.
3. Only after the Day-tab checkpoint passes: extend the same `StatsRowModel`/`StatsRowDelegate`
   pair to Week and Month, reusing the period-kind parameterization from §1 (no new model/delegate
   classes needed, only new `_refresh_weekly`/`_refresh_monthly` wiring following the Day tab's
   proven shape).
4. `FinishedBookThumb`/the Finished strip stays out of scope for the duration of this whole
   sequence, per §3 — revisit only as a separate, later decision if there's appetite after Day/Week/
   Month land.
