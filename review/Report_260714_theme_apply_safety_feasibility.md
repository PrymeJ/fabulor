# Making `_apply_stylesheets`/theme-apply safe to run without starving anything — feasibility findings

**Investigation only. No fix code, no behavior change. Working tree clean throughout** (`git diff`
empty; two temporary DEBUG probes — `[APPLY-ORIGIN]` stack-origin logging on `apply_cover_theme`,
plus the earlier reverted `[STUTTER-PROBE]` — were used and fully removed, confirmed by grep).

Builds on `review/Report_260714_synchronous_main_thread_work.md` (the timing map, RANK-1/RANK-2
split) and its flow-animation-stutter follow-up (`review/Data_260714_flow_animation_stutter.md`,
the Regime A/B split). This report answers: is the ~400ms synchronous theme-apply cost fixable
without starving the things it currently starves, and is the underlying P1↔P2 race pattern
separately closeable? The **fix plan is a later, separate step** — this is findings and
feasibility only.

---

## Phase 0 (mandatory) — what `_any_panel_animating` was actually built for

**Answer: DELIBERATE, for a specific reason — protecting a running panel/slider animation from
being disrupted by a synchronous theme apply. NOT built for, and never considered against, the
flow animation. Its Regime-B protection on book-switch is a genuine same-class effect, but reached
incidentally; cold-launch was never in scope because the guard is about panels, and cold launch has
no panel animating.** Evidence, not guess:

- **Origin commit `a5cf753` (2026-04-18), "perf: add guard against theme changes during panel
  animation."** Its own message states the intent twice: the code comment is *"Guard against theme
  changes during panel animation to prevent hitches,"* and the commit body explains the deferral
  is *"safe deferral: ... when the animation finally settles, the theme application follows the full
  logic ... rather than just a raw setStyleSheet call."* The concern is explicitly **the panel
  animation being hitched by a theme apply mid-slide.** (Companion `033510d`, 2026-05-15, converted
  the `QTimer.singleShot(150, ...)` retry into the deduplicated `_panel_guard_timer` at
  `_PANEL_ANIM_GUARD_MS = 700`.)

- **The "many approaches tried" history the user recalls is real and is a DIFFERENT, deeper
  layer** than this one guard — and it establishes *why* a theme apply hitches a moving animation
  in the first place. Two NOTES.md entries are load-bearing:
  - *"Theme fade must not start while any slider value animation is running"* (2026-06-05): the
    theme transition is a **full-window overlay fade with mask punch-through for the sliders**. If a
    slider's fill is animating (`animate_to`) while the fade overlay is active, *"the moving fill
    produces a ghost image"* against the static overlay screenshot. This is a **correctness/visual
    artifact**, not merely cosmetic jank — it produces a visible ghost. The fix
    (`_apply_pending_cover_theme`) deliberately chains `progress_slider.when_animations_done()` →
    `chapter_progress_slider.when_animations_done()` → `apply_cover_theme`, an explicit invariant:
    *"cover art theme fade starts only after BOTH sliders' animations have finished."*
  - *"Main-window theme fade interrupt ... full color-animation rework DEFERRED"* (2026-06-19): the
    reason theme changes are restricted to "main window, no panel open, nothing moving" is that the
    transition is a **heavyweight full-window animated fade** (overlay snapshot + frozen labels +
    slider color tweens). The lightweight alternative — pure per-element `@Property` color
    animation, which *"could run freely even with a panel open"* — was **started in a prior session
    and abandoned as ~40–80h+ with high regression risk** (every QSS-styled widget's
    `:hover`/`:pressed`/`:disabled` states would need hand-reimplementation in custom-paint land).
    The cheaper middle path (snap panel chrome instantly, keep slider tweens) was **explicitly
    rejected by the user** — instant theme snaps *"look jarring/violent."*

**So the protective effect is deliberate in KIND (protect a moving animation from theme-apply
ghosting/hitching) but the guard's SCOPE is panels only.** The flow animation is protected on
book-switch by a *separate, also-deliberate* mechanism — `_apply_pending_cover_theme`'s
`when_animations_done()` chain — not by `_any_panel_animating`. This distinction is the crux of the
whole cold-launch bug (next section) and it corrects a framing in the parent report.

---

## Correction to the parent report: cold-launch Regime B is a MISSING `when_animations_done()`
chain, not primarily the absent `_any_panel_animating` guard

The gap-closure report attributed book-switch's Regime-B immunity to `_any_panel_animating` and
called cold-launch's exposure "the guard's gap." **That's incomplete.** Traced precisely this
session (`[APPLY-ORIGIN]` stack logging on a cold M4B-cover launch):

- `_apply_main_cover` (`app.py:2507`) branches on `is_any_panel_visible()`:
  - **panel visible** (book-switch, library open) → stash `_pending_cover_pixmap`, applied later via
    `_apply_pending_cover_theme`, which **waits for both sliders' `when_animations_done()`** before
    firing the theme. Immune to Regime B by construction — the flow animation has finished before
    the theme apply starts.
  - **no panel visible** (cold launch, in `__init__`) → `apply_cover_theme` **immediately**, with
    **no slider-animation wait at all.** Regime B exposed.
- The actual Regime-B trigger on cold launch is a **second** cover-theme apply: `__init__`'s
  `_load_cover_art` fires one apply immediately (t=26751.15, before the animation), then the startup
  library scan finishes ~2.4s in and `_on_scan_finished` (`library_controller.py:158-161`)
  unconditionally calls `load_cover_art(current)` again — *"ensures the active book_covers entry is
  used, not a stale cache entry from before the scan"* — which re-enters `_apply_main_cover`'s
  no-panel branch and fires a full `_apply_stylesheets` (t=26753.53) that lands squarely in the
  flow-animation window.

**Implication for the fix:** cold-launch Regime B has a narrower, more surgical shape than "the
panel guard doesn't cover cold launch." It is specifically: *the no-panel branch of
`_apply_main_cover` applies the cover theme without the `when_animations_done()` protection its
sibling (panel-visible) branch relies on, and the post-scan cover reload re-triggers it during the
flow animation.* This is worth stating because it means Regime B might be closeable narrowly
(route the no-panel branch through the same slider-wait, or don't re-apply the full theme on a
post-scan cover reload when the cover hasn't actually changed) **without** touching the
theme-apply cost at all — a different, cheaper fix than "make `_apply_stylesheets` async." That is a
finding, not a recommendation to do it; see the RANK-1-vs-RANK-2 section.

---

## RANK-1 (narrow): the ~400ms `_apply_stylesheets` cost — caller audit + what "async" can mean

### Caller audit — does every trigger need the FULL pipeline?

Every entry point that reaches `_on_theme_changed` (→ `_apply_stylesheets`, median 442ms pipeline):

| Trigger | Path | Needs full pipeline? |
|---|---|---|
| Auto rotation (20-min timer, `T` key) | `_do_rotate` → `_on_theme_changed` (fade_ms>0, non-themes-tab → `_do_fade_with_slider_animation`) | **Yes** — genuinely changes the whole theme; full restyle + fade required |
| Cover-art book-switch/cold-load | `apply_cover_theme` → `_on_theme_changed` | **Yes** — new cover = new palette across the whole UI |
| Themes-tab click (activate) | `toggle_theme_selection`/`_on_theme_right_clicked` → `_on_theme_changed` | **Yes** — deliberate full theme change |
| Themes-tab hover preview / unhover | `_on_theme_hovered`/`_unhovered` → `_on_theme_changed(hover=True/False)` | **Partial** — `hover=True` ALREADY skips library/chapter-list/stats/book-detail panels (`_apply_stylesheets`'s `if not hover` branches). This is the one caller already running a reduced pipeline. |
| Cover-art mode toggle | `set_cover_art_mode` → `_on_theme_changed`/`apply_cover_theme` | **Yes** |
| Panel-open fade completion | `complete_main_fade` → `_apply_stylesheets` directly | **Yes** — re-polishes stranded slider `@Property` colors (documented correctness fix, 2026-06-19) |
| `_set_bg_suppressed` (book-switch, empty/no-book state) | regenerates `content_container` QSS only — **NOT** `_apply_stylesheets` | **No** — already a narrow, single-widget apply |

**Finding:** almost every caller genuinely needs the full restyle, because a theme/cover change
really does re-color the entire widget tree (buttons, panels, sliders, labels, all QSS-driven). The
only already-reduced caller is hover-preview (`hover=True`). **So "most callers only need something
cheaper" is NOT the situation here** — this is not a case where the expensive path was a lazy
simplification applied to narrow operations. The cost is intrinsic: `mw.setStyleSheet(base)` alone
is median ~180ms (max 355ms) because Qt must re-polish every descendant against the new global
stylesheet, and there are ~8 more `setStyleSheet` calls on sub-panels. This means the realistic
RANK-1 lever is **reducing/reshaping the cost of a full apply**, not "call something narrower."

### Does Qt allow "true async"? — No. `setStyleSheet` is synchronous main-thread by Qt architecture.

`QWidget.setStyleSheet` / `QStyle` polish runs on the GUI thread and cannot be moved to a worker
thread (Qt widgets are not thread-safe; touching them off the GUI thread is undefined behavior —
the same constraint documented for the cover-pixmap step in the parent report). **"Async" here
cannot mean "threaded."** The achievable shapes are:

1. **Chunking across event-loop iterations** — split the ~8 `setStyleSheet` calls (base, title,
   content, library, chapter-list, settings/speed/sleep, stats/book-detail, sidebar) so they run
   one-per-tick via `QTimer.singleShot(0, ...)` chains, letting animation frames interleave. Reduces
   *per-tick* block to the largest single sub-step (still ~180ms for the base stylesheet — see the
   caveat below) rather than the full ~400ms. Feasible but partial: the base `setStyleSheet` is the
   dominant chunk and can't itself be subdivided (it's one Qt call).
2. **Deferral away from the racing moment** — don't run the apply *during* the animation/restore
   window at all; run it before or after. This is exactly what `_apply_pending_cover_theme`'s
   `when_animations_done()` chain already does for book-switch, and it's the cheapest, lowest-risk
   shape. Extending that same deferral to the cold-launch no-panel branch (and/or suppressing the
   redundant post-scan re-apply) closes Regime B without changing the cost at all.
3. **Reducing the cost's magnitude** — the abandoned per-element `@Property` color-animation rework
   (2026-06-19, ~40–80h, user-rejected middle path). Out of scope to redo; noted only because it's
   the *only* path to actually making the apply cheap enough to run freely.

**So "async" is the wrong word for what's achievable. The realistic RANK-1 fix is deferral (shape 2)
or chunking (shape 1), not threading.** Deferral is strictly the safer of the two and already has a
proven in-codebase implementation to mirror.

### `theme_applied.emit`'s DirectConnection fan-out (P4)

Confirmed removable-from-the-hot-path if desired: `theme_applied.emit`'s return value is **never
used or awaited** (both emit sites, `theme_manager.py:377` and `:463`, are bare statements), and the
three consumers (`stats_panel`/`tags_panel`/`book_detail_panel.on_theme_changed`) only restyle
**hidden** panels. Nothing depends on the fan-out completing before the emit returns. It contributes
a meaningful slice of the ~124ms pipeline−`_apply_stylesheets` delta and could be deferred to a
`singleShot(0, ...)` or run lazily on panel-open without correctness risk. **Caveat:** making
`_apply_stylesheets` deferred does NOT automatically defer this — it's a separate synchronous chain
off the same emit and would need its own handling.

---

## RANK-2 (structural): can the P1↔P2 race precondition be removed, not just shrunk?

The race is P1 (`_vt_restore_pending` write, Qt-queued via `book_ready`→`_on_file_ready`
QueuedConnection, `app.py:389`) losing to P2 (`_on_file_loaded`'s read of it, on the mpv thread)
when a long sync op starves the Qt queue. The structural question: does `book_ready`→`_on_file_ready`
*have* to be a QueuedConnection?

**Finding — the answer is thread-dependent and asymmetric:**
- **Non-VT path:** `book_ready` is emitted from `_on_file_loaded`, which runs on the **mpv event
  thread**. A cross-thread signal to a Qt-thread slot **must** be Queued (or Auto, which resolves to
  Queued) — this is mandatory thread-marshaling and cannot be made Direct. **P2's own read is on the
  mpv thread**, so for non-VT the ordering is inherently a cross-thread affair.
- **VT path:** both `book_ready` emit sites (`ungate_play` and `_on_playlist_resolved`) run on the
  **Qt main thread** (confirmed: `_on_playlist_resolved` is the Qt-side slot of the QThreadPool
  worker's `_playlist_resolved` signal; `ungate_play` is called from `_on_library_hidden`, a Qt
  slot). The emit is same-thread. A Direct connection for the VT path would run `_on_file_ready` →
  `_restore_position` → `defer_vt_restore` **synchronously inside `ungate_play`, before the
  subsequent `_apply_pending_cover_theme()` call in `_on_library_hidden`** — meaning `_vt_restore_pending`
  would be written *before* any theme apply could start, **removing the race precondition entirely
  for VT restore-on-book-switch** rather than shrinking the window.

**BUT — this lever is not free and is not clearly in bounds:**
- The connection is a single `book_ready.connect(self._on_file_ready, QueuedConnection)` shared by
  BOTH paths. You cannot make it Direct for VT and Queued for non-VT without either a second signal
  or per-emit connection-type juggling — a real design change, not a one-liner.
- The VT `book_ready` emit is deliberately placed **before `instance.play()`** (the "book_ready
  invariant" in CLAUDE.md). Running `_on_file_ready`/`_restore_position` synchronously at that point
  changes *when* `defer_vt_restore` runs relative to `play()` — and the whole `_vt_restore_pending`
  mechanism, plus the shipped `_on_vt_file_switched` gated clear and `_on_end_file` ERROR reset, was
  designed and verified against the *current* ordering. **The task explicitly forbids proposing
  changes to `_on_vt_file_switched`, the settle branch, `_logical_pos`, or the shipped VT fixes** —
  and a Direct VT connection, while technically on the P1/emit side, would alter the timing those
  fixes were verified against. That makes it a change that *touches the blast radius* of the
  protected code even if it doesn't edit those functions.

**Feasibility verdict for RANK-2:** the precondition *can* in principle be removed for the VT path
(same-thread emit makes synchronous restore possible), but doing so is a genuine re-architecture of
the `book_ready` connection with direct interaction with this session's verified VT fixes — high
enough risk that it should NOT be bundled with the RANK-1 cost fix, and should only be attempted, if
at all, with the full VT+Undo verification bar (the harnesses + live checklist) re-run. For the
non-VT path the QueuedConnection is mandatory and the precondition cannot be removed at all —
non-VT's only protection is "don't run a long sync op in the window," i.e. the RANK-1 fix.

---

## Recommendation: RANK-1 and RANK-2 are TWO separate fixes, not one

**They should not be combined, for three reasons:**

1. **Different blast radius.** RANK-1 (deferral/chunking of theme-apply) is confined to
   `theme_manager.py` + the two cover-apply call sites in `app.py`, and mirrors an existing,
   verified pattern (`when_animations_done()`). RANK-2 (removing the P1↔P2 precondition) re-architects
   the `book_ready` connection and interacts directly with the shipped VT fixes' verified timing —
   the highest-risk zone in the codebase (the "VT+Undo known-fragile" rule).

2. **RANK-1 alone closes all three CURRENTLY-OBSERVED victims.** Race 3 (VT progress reset), Regime B
   (flow-anim freeze), and the Themes-tab fade bug are all "a long sync op ran in a bad window."
   Deferring/chunking the theme apply so it doesn't land in those windows fixes all three without
   touching the race machinery. RANK-2 is about the *next, not-yet-observed* victim — a future
   ~100ms+ sync op that isn't theme-apply. That's real and worth a plan, but it's insurance against a
   hypothetical, not a fix for a live bug, and it shouldn't gate the live-bug fix.

3. **RANK-1 has a cheap, low-risk shape available; RANK-2 does not.** The single most surgical
   finding here is that cold-launch Regime B is a *missing `when_animations_done()` chain* on
   `_apply_main_cover`'s no-panel branch plus a redundant post-scan re-apply — both closeable without
   changing the theme-apply cost or any race machinery. RANK-2 has no equivalently cheap shape; its
   cheapest option still re-architects a connection.

**Suggested sequencing (for the LATER plan step, not decided here):**
- **First, RANK-1 as deferral** (shape 2): extend the `when_animations_done()` protection to the
  cold-launch cover-apply path and/or suppress the redundant post-scan full re-apply. Closes Regime B
  and reduces Race-3 exposure with the lowest risk. Optionally add chunking (shape 1) and defer the
  `theme_applied` fan-out if more headroom is wanted.
- **Separately and later, RANK-2 as its own investigate-then-plan cycle** if the structural race is
  judged worth closing at the source — treated as a VT-fragile-zone change with the full verification
  bar, not folded into RANK-1.

**Do NOT** generalize `_any_panel_animating` to cold-launch as the fix: Phase 0 established it's a
panel-scoped guard, and the real cold-launch mechanism is the missing slider-wait on a different code
path — generalizing the guard would be treating the wrong lever.

---

## What was NOT done (per constraints)

No fix code written. No behavior changed. `_on_vt_file_switched` / settle branch / `_logical_pos` /
shipped VT fixes untouched and not proposed for change (the RANK-2 finding explicitly flags the VT
Direct-connection lever as interacting with their verified timing and defers it). Temporary probes
removed; tree clean. The fix plan is the next, separate step.
