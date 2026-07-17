# Is `_apply_stylesheets`'s ~400ms cost inherent, or is it doing avoidable work?

**Investigation only. No code changed** — working tree clean (`git diff` empty), on `main`, `stash@{0}`
(the set-aside Change A/B fix) untouched and not popped. Temporary `[NARROW-PROBE]` instrumentation
was added and fully removed (confirmed by grep).

**Short answer: YES — there is real, measured, substantial avoidable work. On a book-load trigger,
~55% of the pipeline styles surfaces that are not visible. But it is NOT a free win: the naive
narrowing has a specific, confirmed edge case (no restyle-on-open mechanism exists), which any fix
must design around.**

---

## 1. Structural breakdown — what `_apply_stylesheets` actually does

It is **not** one monolithic apply. It is 9 sequential sub-steps, each targeting a different widget
subtree (`ui/theme_manager.py:665-768`):

| # | Sub-step | Target | Conditional on? |
|---|----------|--------|-----------------|
| 1 | `mw.setStyleSheet(get_base_stylesheet(...))` | whole window tree | **unconditional** |
| 2 | `title_bar` + `content_container` | main chrome | `hasattr` only |
| 3 | `_reload_button_icons` | transport icons | `hasattr` only |
| 4 | `library_panel` + `update_progress_bar_theme` | library | **`not hover`** |
| 5 | `chapter_list_widget.update_theme` | chapter overlay | **`not hover`** |
| 6 | `settings_panel`, `speed_panel`, `sleep_panel` | 3 panels, one shared QSS | **unconditional** |
| 7 | `excluded_books_section` / `popup` `set_theme` | popup | `hasattr` only |
| 8 | `stats_panel`, `book_detail_panel` | 2 panels, one shared QSS | **`not hover`** |
| 9 | `sidebar` + `_set_chapter_ui_active` | sidebar/chapter UI | `hasattr` only |

Plus a **TAIL** in the caller `_on_theme_changed` (`:459-464`), also gated only on `not hover`:
`_refresh_panel_visuals(theme_name)` → `theme_applied.emit(...)` (DirectConnection fan-out to
stats/tags/book_detail `on_theme_changed`) → `update_theme_list_visuals()`.

**The key structural finding: the ONLY conditionality in the entire pipeline is the `hover` flag.
There is no visibility-based conditionality anywhere.** Steps 6 and 8 restyle five panels on every
non-hover call whether or not any of them is on screen. `hasattr` guards are existence checks, not
visibility checks.

**Do different triggers run different subsets?** No — with exactly one exception. Measured across
logs: **hover-preview (`hover=True`) is the only trigger that narrows**, skipping steps 4, 5, 8 and
the whole TAIL. Every other trigger — book-load, book-switch, cover-theme apply, rotation, `T`,
hover-exit snapback — runs the **full** pipeline regardless of relevance. And note hover narrows by a
**hardcoded flag, not by visibility**: it still pays step 6 (settings/speed/sleep) because during a
hover preview the Settings panel genuinely *is* visible. That is a correctly-narrowed trigger; it is
the only one.

## 2. Measured: what a book-load trigger actually pays for

Instrumented cold launches, cover-theme on, VT book. **Every panel confirmed invisible** on every
sample (`[NARROW-PROBE] VISIBILITY settings=False speed=False sleep=False stats=False
book_detail=False library=False chapter_list=False sidebar_expanded=False`).

**n = 18 `_apply_stylesheets` calls (hover=False), all with zero panels visible:**

| | median |
|---|---|
| **total** | **532.1ms** |
| VISIBLE surfaces (base, title/content, icons, sidebar, chapter-UI) | 278.9ms (**52%**) |
| **INVISIBLE surfaces** (library, chapter_list, settings/speed/sleep, stats/book_detail) | **244.8ms (46%)** |

Per invisible sub-step (median):
- `settings/speed/sleep panels` — **105.2ms** ← all three invisible
- `stats + book_detail panels` — **106.8ms** ← both invisible
- `library_panel` — 15.6ms ← invisible
- `chapter_list_widget` — 0.1ms ← negligible

**Plus the TAIL** (measured separately, same trigger, `settings_visible=False any_panel_visible=False`):
`TAIL_total` **~100–132ms**, broken down as `_refresh_panel_visuals` **47.7ms** +
`theme_applied.emit` **36.1ms** + `update_theme_list_visuals` **26.9ms`. All of it styles surfaces
that are not on screen.

**Combined: on a book-load trigger, roughly 355ms of a ~640ms pipeline (~55%) is spent styling
things the user cannot see.**

## 3. The user's specific example — checked, and the answer is "yes, but not where you thought"

**The hypothesis was that Themes-tab styling is in the base stylesheet.** Checked: **it is not.**
`get_base_stylesheet` (149 lines) contains only main-window chrome — `QWidget#mainwindow`, tooltips,
status banner, scan progress bar, `#overall_progress` slider qproperties, chapter dropdown. No
Themes-tab selectors.

**But the underlying instinct is correct, and the cost is real — it lives in two other places:**
1. **`get_settings_stylesheet`** (273 lines) *does* carry the Themes-tab styling — `QPushButton#theme_item`
   plus its `:disabled`, `[selected="true"]`, `:hover`, `[active_display="true"]` states — and it is
   applied to `settings_panel`/`speed_panel`/`sleep_panel` **unconditionally**, at **~105ms median**,
   on every book-load.
2. **`update_theme_list_visuals()`** loops over **all 58 theme pool buttons**, doing
   `setProperty` + `style().unpolish(btn)` + `style().polish(btn)` **per button** — a full per-widget
   style recomputation of the Themes-tab pool — at **~27ms median**, on every non-hover theme change,
   with the Settings panel closed.

So: the Themes-tab-specific work alone is ~27ms (measurable, not negligible, but not the headline).
The **panel-restyle work it sits inside is ~212ms** (settings/speed/sleep + stats/book_detail), and
the full invisible-surface total is ~355ms. **The user's framing understated the finding** — it is not
just the Themes tab, it is the entire family of invisible-surface restyling.

## 4. Is narrowing safe? — NO, not naively. One confirmed edge case.

**The precedent that works:** the `hover` skip is safe *because it has a compensating mechanism*.
`_on_theme_unhovered` **always** fires a full `hover=False` restyle on exit (`theme_manager.py`,
both branches call `_on_theme_changed(..., hover=False)`), so every surface skipped during hover is
guaranteed restyled before it can become visible. The code comment states this invariant explicitly,
and it holds.

**Why a visibility-based skip does NOT inherit that safety — confirmed, not assumed:** panels are
**not restyled when they open.** Grepping every open path in `ui/panels.py` for
`setStyleSheet`/`_apply_stylesheets`/`update_theme` returns **no call sites** (the single grep hit is
a comment). Panels rely entirely on having been styled by an earlier `_apply_stylesheets`. So:

> If a theme change (rotation, cover-switch, book-load) skipped an invisible panel, and the user then
> opened that panel, it would show **stale, previous-theme colors** until the next full restyle.

This is a **real, reachable state**, not hypothetical: theme rotation fires on a timer with all panels
closed, and any panel can be opened immediately afterward.

**Therefore a narrowing fix requires a companion mechanism** — restyle-on-open (or an equivalent
"dirty theme" marker consumed at open time). That is the design work a narrowing fix implies; it is
not free, but it is *bounded and local* (every panel already funnels through `_open_*_flow` /
`_start_*_entry` in `panels.py`, which is exactly where such a hook would live), and it is far smaller
than the set-aside deferral fix's state machine.

**Second-order note (for whoever designs it, not resolved here):** `_reload_button_icons` (step 3,
~2.5–11ms) and the `excluded_books` `set_theme` (step 7) also touch surfaces of varying visibility;
they are small and were not separately isolated. The two big wins are steps 6 and 8 plus the TAIL.

## 5. Answer to the framing question: inherent vs. avoidable

**Not inherent. Roughly half is avoidable in principle.**

- **The genuinely inherent floor** is step 1, `mw.setStyleSheet(get_base_stylesheet(...))` — median
  ~180ms across the earlier 70-run sample, 60–483ms observed here. Qt owns this: setting a stylesheet
  on the top-level widget re-polishes every descendant, and (per the earlier feasibility report)
  `setStyleSheet` is GUI-thread-only, so it can be neither threaded nor subdivided. **A theme change
  that must recolor the visible main window cannot avoid paying this.**
- **Everything above that floor is trigger-relevance work**, and on a book-load trigger ~355ms of it
  is spent on invisible surfaces.

**This is materially different from the deferral direction.** Narrowing reduces the cost itself, which
helps **every** victim simultaneously — Regime A (less main-thread work during the animation window),
Regime B, Race 3 (a shorter starvation window), and the 2026-07-01 hover-preview regression — without
rescheduling anything. The set-aside fix rearranged *when* a maximal-cost operation fires; this would
reduce *what it costs*. **Note it does not reduce the cost to zero:** the ~180ms base floor remains, so
narrowing alone would shrink the pipeline from ~640ms to roughly ~280ms on a book-load trigger — a
~55% reduction, not an elimination. Whether that is sufficient on its own for any given victim is a
question for the decision this report feeds, not for this report.

## 6. Evidence summary (for the decision, which is NOT made here)

| Question | Answer | Evidence |
|---|---|---|
| Monolithic or sub-stepped? | 9 sub-steps + a caller TAIL | code read, `theme_manager.py:665-768` |
| Already trigger-conditional? | Only `hover`, and by flag not visibility | code read + 20 `hover=True` vs 51 `hover=False` log samples |
| Themes-tab styling in the base? | **No** — it's in `get_settings_stylesheet` | `get_base_stylesheet` selector dump |
| Themes-tab work on book-load? | **Yes** — `update_theme_list_visuals`, 58 buttons repolished, ~27ms | `[NARROW-PROBE] TAIL` |
| Invisible-surface cost on book-load? | **~355ms of ~640ms (~55%)** | n=18, all panels confirmed invisible |
| Safely avoidable? | **Not naively** — no restyle-on-open exists; needs a companion mechanism | grep of every open path in `panels.py` |
| Is the cost inherent? | **No** — but a ~180ms base floor is (Qt-owned, GUI-thread-only) | this report + earlier feasibility report |
