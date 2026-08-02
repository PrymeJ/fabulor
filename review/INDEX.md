# Index of `review/`

One line per document: what it found. Scan this before starting a perf/theme/panel investigation —
`review/Report_260715_apply_stylesheets_avoidable_work.md` was missed for two weeks because nothing
like this existed. See `review/README.md` for naming rules. **Maintained alongside every new
`review/` document** — add a row in the same commit that adds the file.

Sorted by date, oldest first, grouped loosely by topic within a date where it helps.

| File | Date | Type | Finding |
|---|---|---|---|
| `Review_260612_1.md` | 06-12 | Review | Invariant audit vs CLAUDE.md's Critical Architecture Rules — findings folded into later CLAUDE.md passes |
| `Review_260612_2.md` | 06-12 | Review | DB/upsert consistency audit (`db.py`, upsert call sites) |
| `Review_260612_3.md` | 06-12 | Review | Player + SessionRecorder correctness audit |
| `Review_260612_4.md` | 06-12 | Review | Theme system / stylesheet entry-point audit (early ancestor of the 2026-08-02 restyle-cost work) |
| `Review_260612_5.md` | 06-12 | Review | Feature invariant audit — EOF/Finished, sort/filter, archived UI |
| `Review_260612_6.md` | 06-12 | Review | VT/MP3 seek + position-tracking invariant audit |
| `Review_260612_7.md` | 06-12 | Review | SessionRecorder, session-deletion, streak-grid data-path audit |
| `Review_260612_8.md` | 06-12 | Review | Tag Manager + ContextIconMenu + PanelManager audit |
| `Snapshot_260612_debt_inventory.md` | 06-12 | Snapshot | **STALE, frozen.** Consolidated debt index at the time of the above batch. The LIVE index is `/DEBT_INVENTORY.md` — do not confuse the two (this file collided with it by name until 2026-08-02). |
| `Runbook_260612_finished_flow_streak_grid.md` | 06-12 | Runbook | Hands-on manual validation checklist for Finished-Book flow (B2) + Streak-Grid (B1) |
| `Review_260703_1.md` | 07-03 | Review | Targeted audit of the 2026-06-19→HEAD window. Escalated: scan/missing-book teardown risk (HIGH) |
| `Review_260703_2.md` | 07-03 | Review | Full-codebase invariant compliance sweep — **17/17 PASS, zero failures** |
| `Review_260706_1.md` | 07-06 | Review | Full key-binding inventory, pre-`shortcuts.py` design input |
| `Review_260706_2.md` | 07-06 | Review | Root-caused the "two panels overlap" bug: **no single mutual-exclusion gate existed** for overlay-opening — led to `is_overlay_open_or_committed()` |
| `Review_260710_1.md` | 07-10 | Review | Verification pass on a week of fixes (idle preloader, scroll anchoring, theme-hover latency, dup-call removal) — **no FAIL, no escalations**, 88/88 tests |
| `Review_260710_2.md` | 07-10 | Review | Standing invariant sweep, 18 invariants — **all PASS**, 88/88 tests |
| `Spec_260713_cover_management.md` | 07-13 | Spec | Implementation spec for the Cover Management panel (4 covers/book, fit modes, `book_covers` table) — shipped |
| `Report_260714_synchronous_main_thread_work.md` | 07-14 | Report | Full inventory of synchronous main-thread work at start/book-load/theme-change/panel-slide. **RANK-1 finding: `_apply_stylesheets`'s ~400ms cost is the load-bearing hazard** — starves two P1↔P2 races. Everything else measured NEGLIGIBLE. Ancestor of the 2026-08-02 root-restyle investigation. |
| `Data_260714_flow_animation_stutter.md` | 07-14 | Data | Raw timing numbers backing the report above and its NOTES.md entry — no narrative |
| `Report_260714_theme_apply_safety_feasibility.md` | 07-14 | Report | Follow-on: is it SAFE to make `_apply_stylesheets` async? Splits the fix into RANK-1 (the ~400ms cost itself) and RANK-2 (removing the race precondition) as **two separate fixes, not one** |
| `Report_260715_apply_stylesheets_avoidable_work.md` | 07-15 | Report | **Direct prior art on the 2026-08-02 restyle question.** On a book-load trigger, ~55% of `_apply_stylesheets`'s pipeline styles surfaces that are not visible — real avoidable work, but not a free win (no restyle-on-open mechanism existed to catch up a skipped panel) |
| `Review_260720_theme_reach.md` | 07-20 | Review | Complete call-site inventory of everything that can `setStyleSheet()` `main_window`/`content_container`. Found two dispatcher bypasses (Path A: `_set_bg_suppressed`; Path D: `_grab_and_blur`'s hover-unaware grab) — **both since FIXED by `0439c76`**; §1's inventory is still current, re-verified 2026-08-02 |
| `Report_260720_theme_bleed_pass1.md` | 07-20 | Report | Implements the Path-A fix identified above (state-read containment) |
| `Investigation_260720_fade_orphan_race.md` | 07-20 | Investigation | Diagnosis of the 10-second `_pending_fade_call` orphan race (hover mid-fade → stash → unresolved) — addressed across later commits, see the CLAUDE.md stash-tuple rule |
| `Investigation_260720_noop_guard_masks_stashed_apply.md` | 07-20 | Investigation | Diagnosis: the no-op guard could mask a theme SELECTED but never APPLIED, stranding it unapplied for 75+ seconds — **FIXED by `933f7f2`** (`_mark_theme_applied`) |
| `Investigation_260720_snap_drain_deferred_gap.md` | 07-20 | Investigation | Diagnosis: `snap_theme_forward()`'s drain fix didn't reach the deferred-pass surfaces — fixed via a `fade_ms=0` re-call to `_on_theme_changed` |
| `Investigation_260721_hover_interrupts_hover.md` | 07-21 | Investigation | Diagnosis: a hover-confinement fix earlier the same night broke hover-on-hover (stashed instead of interrupting) — **FIXED by `e27d47c`/`57a7dd0`** |
| `Snapshot_260717_theming_state.md` | 07-17 | Snapshot | Full description of the theming/animation pipeline as of `5cfe3a3`. **Stale** — the fast/deferred split and panel-visibility gate have both changed since; read CLAUDE.md + NOTES.md 2026-08-01/02 for current behaviour |
| `Review_260802_CLAUDEMD.md` | 08-02 | Review | File-health audit of CLAUDE.md itself — categorized every changelog entry as superseded/narrative/duplicate/stale/scope-creep/load-bearing; estimated ~520-580 line reduction possible, none applied |

## Cross-references worth knowing about

- **The restyle-cost thread runs across five documents over three weeks**: `Review_260612_4` (2026-06-12, early theme-entry-point audit) → `Report_260714_synchronous_main_thread_work` (names `_apply_stylesheets` as RANK-1) → `Report_260714_theme_apply_safety_feasibility` (splits the fix) → `Report_260715_apply_stylesheets_avoidable_work` (measures the avoidable share) → NOTES.md 2026-08-01/02 (measures the root call itself: any `mw.setStyleSheet()` costs ~436ms live regardless of content; depth and visibility are the multipliers). None of the July reports were read before the August investigation started it over from greps.
- **The theme-bleed thread**: `Review_260720_theme_reach` (finds two bypasses) → `Report_260720_theme_bleed_pass1` (fixes Path A) → `0439c76` (ships both fixes) → three same-week `Investigation_*` files (diagnose three *separate* staleness/interrupt bugs found while verifying the bleed fix, all since fixed).
