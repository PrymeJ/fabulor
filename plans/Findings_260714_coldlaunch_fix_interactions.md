# Findings: two interaction surprises in the cold-launch theme fix, and the state table for resolving them

**Status: FINDINGS + DESIGN, not implemented.** Written per the stop-and-report discipline after
Change A + the redesigned Change B, in the working tree, produced two interaction surprises — both
tracing to the *same* stale assumption. This document establishes the full interaction surface
(state table, sweep, verified facts) BEFORE any predicate is chosen, so the fix is derived with the
same rigor as the jitter-key decision rather than patched into place. Companion to
`plans/Plan_260714_surgical_coldlaunch_theme_fix.md` (which this updates) and
`review/Report_260714_theme_apply_safety_feasibility.md`.

Temporary probes still in the tree (`[STUTTER-PROBE]`, `[APPLY-ORIGIN]`) — removed before any
commit.

---

## Current state of the working tree (what's implemented right now)

- **Change A (source-key skip gate):** `apply_cover_theme(..., source_key)` skips the full
  `_apply_stylesheets` when `source_key is not None AND _cover_theme_active AND source_key ==
  _last_cover_source`. `_last_cover_source` set only when an apply actually completes; reset in
  `clear_cover_theme`. Keys on cover SOURCE identity (jitter makes theme-dict equality useless —
  verified, see the plan's jitter caveat).
- **Change B (redesigned, unified trigger):** the cover-theme apply for BOTH cold-launch and
  book-switch now fires from the END of `_on_file_ready` (via `_apply_pending_cover_theme`), after
  `_restore_position`/`defer_vt_restore` (Race 3: guaranteed ordering) and after the flow animation
  starts (Regime B: the `when_animations_done` wait now actually waits). Cold-launch stashes the
  cover (`_load_cover_art(defer_theme=True)`) instead of applying in `__init__`. The old early
  trigger sites (`_on_library_hidden` non-deferred branch, `_drain_deferred_file_ready` tail) were
  removed.

## Verified results (measured, both book types)

| Config | Race 3 (restore loss) | Regime B (flow freeze >150ms) |
|--------|----------------------|-------------------------------|
| M4B-cover cold ×10 | (n/a — not VT) | **10/10 REGRESSED** |
| VT-cover @40% Colorless Tsukuru ×8 | **0/8 FIXED** | **7/8 REGRESSED** |
| VT-cover @75% Colorless Tsukuru ×8 | 0/8 | **8/8 REGRESSED** |

- **Race 3: closed on both paths.** The unified trigger's guaranteed-ordering piece works — 0
  losses across all VT-cover runs (was 1/8–1/10 before). This half of the redesign is SOUND and is
  not what these findings are about.
- **Regime B: regressed.** The redesigned Change B broke Change A's skip gate (mechanism below).

## The two interaction surprises — same root assumption

**Both surprises trace to one stale assumption: "the startup cover-theme apply completes
synchronously, before the library scan finishes."**

1. **Surprise 1 (already known):** Change A alone worked on M4B because the startup apply ran
   synchronously in `__init__`, setting `_last_cover_source` BEFORE the ~2s scan-finish — so the
   post-scan reload saw a matching source and skipped. Change A *depended* on that timing without
   stating it.
2. **Surprise 2 (this regression):** Change B deferred the startup apply to `_on_file_ready`
   (~+1837ms after animate-start, measured) to fix Race 3. But the post-scan reload fires at
   **+562ms after animate-start (measured) — DURING the flow, and BEFORE the deferred startup
   apply.** So when the post-scan reload checks the skip gate, `_last_cover_source` is still `None`
   (`active=False`) — the gate misses, and the post-scan reload runs a full ~400–700ms
   `_apply_stylesheets` mid-flow. That is the Regime-B regression (the "pause ~68%, jump, flash"
   the user observed at 75%).

**Measured proof (one 75% launch):** animate START t=0; **post-scan apply fires +562ms (mid-flow,
`last=None active=False` → runs full apply)**; deferred startup apply fires +1837ms (`last=<key>
active=True` — but too late, the damage is done). Both applies carry the IDENTICAL source_key.

**Position-dependence (user-found, verified):** the freeze location tracks restore distance,
because the post-scan apply fires at a ~fixed wall-clock time (scan duration, ~2s) while the flow's
position at that moment depends on how far it's traveling. At 40% the freeze landed near the flow's
end (~39.9%, easy to miss). At 75% it landed mid-flow (~68%, glaring). **Longer restore distance =
wider flow window = more consistent, more visible freeze** (40% was 7/8; 75% was 8/8). A fixed-40%
matrix would have under-reported this — the user's instinct to vary the position caught it.

**Meta-signal (explicitly noted):** two surprises in a row from the same unstated timing
assumption. Any other not-yet-directly-verified "X doesn't affect VT / X is unrelated" claim from
this session's theme-apply work now carries a mental asterisk until checked — the VT
non-reproduction claim was already wrong once tonight (this regression hits VT too, contra the
earlier note).

## Sweep: who reads the two flags (done, to rule out a third stale-assumption site)

- **`_last_cover_source`:** read/written ONLY in `apply_cover_theme` (the skip gate) and
  `clear_cover_theme` (reset). **No third scattered reader.** Safe to extend its semantics in those
  two sites without hunting for hidden dependents.
- **`_cover_theme_active`:** read in MANY places — `set_cover_art_mode` (off/with_pool/exclusive
  transitions), `_on_cover_pool_btn_*`, snapback (`_on_theme_unhovered`), `update_theme_list_visuals`,
  `_update_cover_pool_btn`, exclusive/with_pool mode logic. **`_cover_theme_active` CANNOT be
  overloaded to also mean "pending"** — all those readers depend on its current two-state meaning
  ("a cover theme is currently displayed"). A genuine third state (pending) needs its OWN
  representation. This is why the naive "set `_last_cover_source` at stash time but the predicate
  reads `_cover_theme_active`" patch is a trap — ruled out BEFORE implementing, not after.

---

## The state table — every case the fix must handle correctly

Three inputs define the space:
- **Applied state:** has a cover theme actually been applied yet this book-load? (never / pending-only / applied)
- **Incoming request's source** vs. the pending source vs. the last-applied source (same cover / different cover)
- **Which caller** is requesting (startup-deferred apply, book-switch-deferred apply, post-scan reload)

"Pending" = a cover has been STASHED (`_pending_cover_pixmap` set, source recorded) but the deferred
`_on_file_ready` trigger hasn't fired the apply yet. This is the third state that needs its own field.

| # | Applied state | Incoming request | Correct behavior | Why |
|---|---------------|------------------|------------------|-----|
| 1 | never applied | startup/book-switch deferred apply, first time | **APPLY** | The one apply that must run — brings the cover theme up. |
| 2 | **pending** (stashed, not yet applied) | **post-scan reload, SAME cover** | **SKIP** | ← THE REGRESSION CASE. Same cover as what's pending; re-applying is redundant AND lands mid-flow. Must skip even though nothing has been *applied* yet. |
| 3 | pending | post-scan reload, DIFFERENT cover (scan changed the active cover) | **defer/replace, don't apply-now** | The reload's legitimate purpose (Finding 2 in the plan): a cover that changed during scan. But it still must not apply mid-flow — it should replace the pending cover so the deferred trigger applies the NEW one, not apply immediately. |
| 4 | applied | post-scan reload, SAME cover | **SKIP** | Change A's original working case (cover unchanged since apply). |
| 5 | applied | post-scan reload, DIFFERENT cover | **APPLY** (or defer if a flow is running) | Cover genuinely changed; must re-theme. If no animation is running (common post-scan case), applying is fine; if one is, it should wait. |
| 6 | applied | mode toggle / cover-pool click (source_key=None) | **APPLY** | `source_key=None` never skips — deliberate (mode changes must always re-apply). Unchanged from Change A. |
| 7 | applied | `clear_cover_theme` then re-enable, same cover | **APPLY** | `clear_cover_theme` resets the source so re-enable isn't skipped. Unchanged from Change A. |

**The gap in the current implementation:** only rows 4/6/7 are handled (skip keys on
already-*applied* source). Rows **2 and 3** — the pending state — are unhandled, because there is no
representation of "pending source." Row 2 is the live regression.

---

## Two candidate fix directions — both to be weighed, not just the first that closes the gap

Per the instruction to make the state table show that the post-scan reload's own trigger was
reconsidered, not just the skip-gate patched:

### Direction 1 — give "pending" its own field; skip-gate checks pending OR applied

Add `_pending_cover_source` at the **theme_manager** level (distinct from app.py's existing
`_pending_cover_source`, or reuse/rename carefully — NOTE the name collision to resolve). Set it
when a cover is stashed. The skip gate becomes: skip if the incoming `source_key` matches EITHER the
pending source (row 2) OR the applied source (row 4). Handles rows 2/4; row 3 (different cover while
pending) replaces the pending source instead of applying.
- **Pro:** localized to the skip gate + stash path; the two-site sweep says that's safe.
- **Con:** adds a third state field and a compound predicate — must be checked against all 7 rows
  explicitly (the jitter-key-decision standard), and the app.py-vs-theme_manager
  `_pending_cover_source` name/ownership must be untangled so there's ONE source of truth for
  "pending," not two fields that can drift.

### Direction 2 — the post-scan reload should not attempt an apply while ANY cover apply is pending

Reframe: instead of teaching the skip gate to recognize the collision after the fact, prevent the
collision. Invariant: **"the post-scan reload never applies the cover theme while a startup/
book-switch cover apply is still pending (deferred but not yet fired)."** If a cover apply is
pending when the scan finishes, the post-scan reload either (a) does nothing theme-wise (the pending
apply will bring up the correct cover anyway — it reads the SAME active cover from the DB), or (b)
if the scan actually changed the active cover, replaces the pending cover's source so the pending
trigger applies the new one.
- **Pro:** simpler invariant; makes the skip gate's job smaller (it stops being responsible for the
  cross-caller collision). Matches the reload's actual purpose — it exists to pick up a
  scan-changed cover, which the pending apply can do just as well by reading the updated DB row.
- **Con:** needs a reliable "is a cover apply pending?" signal at the `_on_scan_finished` site
  (`library_controller`), which currently has no visibility into that — some plumbing. Must confirm
  the pending apply genuinely re-reads the DB active cover (so a scan-changed cover is still picked
  up) rather than caching the pre-scan pixmap.

### Recommendation for the decision (the deciding fact is now established from the code)

The open question — *does the deferred apply re-read the DB active cover at APPLY time, or carry a
STASH-time pixmap?* — is **answered: it carries a stash-time pixmap.** `_apply_pending_cover_theme`
(`app.py:1639`) applies `self._pending_cover_pixmap`, the exact QPixmap captured when
`_apply_main_cover` stashed it in `__init__` — no DB re-read at apply time. So a cover that the scan
CHANGES between stash and the deferred apply would NOT be picked up by the pending apply on its own.

What that means for the two directions:
- **Direction 2's clean advantage is narrowed, but it is still viable and arguably still cleaner.**
  Because the pending apply carries a pre-scan pixmap, the reload cannot simply "stand down" in the
  cover-CHANGED case (row 3) — it would have to refresh the pending pixmap/source (a small, bounded
  addition), OR the pending apply would have to be made to re-read the DB at apply time (which would
  ALSO independently fix row 3 for free and is worth considering on its own merits). In the common
  case (row 2, cover UNCHANGED — the overwhelming majority: the active cover already exists at
  startup, verified in the plan's Finding 2), Direction 2 lets the reload stand down cleanly and the
  pending apply brings up the correct (identical) cover.
- **Direction 1** handles rows 2/4 by matching the incoming source against a pending-source field,
  and row 3 by replacing the pending source — it does not care whether the apply re-reads the DB,
  because it keys on source identity either way. It's more self-contained but adds the third state
  field + compound predicate.

**Provisional lean: Direction 2, with the pending apply changed to re-read the DB active cover at
apply time** — because that single change (re-read at apply, not stash-time pixmap) simultaneously
(a) lets the post-scan reload stand down whenever an apply is pending, removing the collision at its
source, and (b) fixes row 3 (scan-changed cover) for free, since the pending apply would then pick up
whatever the DB says post-scan. This turns "carries a stale pixmap" from a con into a non-issue.
BUT this is a lean, not a decision — it must be checked against all 7 rows AND against the
book-switch path (which also uses `_apply_pending_cover_theme` with a stash-time pixmap — does
re-reading at apply time change any book-switch behavior? e.g. a user changing the active cover in
the Cover panel mid-switch). That book-switch cross-check is the remaining open question before
committing to Direction 2.

---

## Book-switch cross-check (the last gate before Direction 2) — CLEAN, traced

**Question:** if a user changes the active cover in the Cover panel during a book-switch's deferred
window, can the deferred apply's new DB re-read race the Cover panel's write?

**Answer: no, safe — for three independent reasons, the decisive one being thread-locality:**
1. **Thread-locality (decisive):** `set_active_cover` is called ONLY from `cover_panel.py` (3
   sites), which has NO worker/thread machinery — all main-thread UI click handlers (verified by
   grep). The deferred apply's proposed DB re-read also runs on the Qt main thread. **Two main-thread
   operations cannot interleave** — the re-read atomically sees either the pre-write or post-write
   active cover, both valid complete states. This is categorically unlike P1↔P2, which was dangerous
   *because* it crossed the mpv thread boundary; there is no cross-thread write to race here.
2. **Write-before-emit ordering:** in `cover_panel.py`, `set_active_cover` (DB write) completes
   before `active_cover_changed.emit` — the DB always reflects the new cover before any handler
   reacts. No torn state.
3. **Structural non-overlap:** a book-switch starts from the Library panel and calls
   `hide_all_panels()` at its very start (`_on_book_selected_from_library`, line 1412), which closes
   the Book Detail panel (that hosts the Cover panel). So the Cover panel is not interactively open
   during the deferred window; the one-overlay-at-a-time gate reinforces this.

Worst case is therefore a benign ordering (the re-read sees the old or new complete cover), never a
corrupt/torn read. **Direction 2 with apply-time DB re-read is cleared to implement.**

## What is NOT in question

- **Race 3's fix (the unified `_on_file_ready` trigger, guaranteed ordering) is sound and verified
  (0 losses both paths).** These findings are ONLY about the Regime-B regression from the skip
  gate's pending-state gap. Do not re-open the ordering design.
- `_any_panel_animating` (panel-slide ghost guard) — untouched, not involved.
- The shipped VT fixes (`_vt_restore_pending`, gated `_on_vt_file_switched`, `_on_end_file` ERROR
  reset, `_logical_pos`) — untouched.
- RANK-2 (structural P1↔P2) — still deferred/tracked; not this.

## Next step

Decide Direction 1 vs 2 by answering the DB-re-read question from the code, check the chosen
direction against all 7 state-table rows explicitly, THEN implement, THEN re-run the full matrix —
crucially **at multiple restore positions (≥40% and ≥75%), not just one** — for both victims on both
entry points, plus the `new_val is None` duration-race edge case (cover-present book that themes
correctly despite the duration race). The position-dependence finding means the matrix's restore
position is now a required test dimension, not a fixed constant.
