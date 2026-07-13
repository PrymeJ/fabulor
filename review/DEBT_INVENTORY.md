# Debt Inventory — Consolidated

> **STALE — frozen snapshot, not the current debt index.** This file is part of the 2026-06-12
> `review/Review_260612_1–8.md` audit batch and was deliberately left untouched after that date
> (see SESSION.md, 2026-07-01 Session 3). The live, actively-maintained debt index is
> `/DEBT_INVENTORY.md` at the repo root — add new items there, not here.

> _Compiled 2026-06-12 against commit `a91f029` (HEAD at compile time). A single deduplicated view of every actionable debt item scattered across CLAUDE.md, NOTES.md, and review/Review_260612_1–8.md. Source-of-truth detail still lives in those files; this is the index. Severities are as already assigned by prior passes/notes, or my judgment where none was given (flagged "(judgment)"). Discrepancies with prior severities are called out, not silently changed._

**Status legend:** `not started` · `partially addressed` · `blocked-on-X` · `resolved` (kept briefly when resolved *this session* so the dedup is auditable).

**Already resolved this session (not carried below, listed here for traceability):**
- Pass 5 #2 — un-archive can't restore cover color → fixed in `c1ac7b0` (`_refresh_archived_state` reloads from disk).
- Pass 6 #1 — `Player.get_stable_position` dead code → removed in `c1ac7b0` (+ orphaned `_paused_time` init).
- Pass 7 #9 — stats `StreakGrid` stale after per-session delete → fixed in `57a6ef4` (emit existing `history_deleted`).

---

## 1. Blocks mandatory work (finished-book validation / streak-grid testing)

Nothing here is a code defect — the two items are **verification gaps**: the data paths audited clean, but the conclusions need hands-on confirmation before the features can be signed off.

| # | Title | Location(s) | Issue (now) | Severity | Status |
|---|-------|-------------|-------------|----------|--------|
| B1 | Streak-grid hands-on validation | review/Review_260612_7.md (whole pass); NOTES.md "StreakGrid — four facts" (~L3) | Data-path audit passed (cache invalidation transactional, day_start_hour consistent, finished-status survives session delete), but no end-to-end UI run confirmed the grid renders correctly after delete/day-boundary/finish across real sessions. The cross-check invariant `len(_longest_dates) == get_streaks()['longest']` is asserted but only verified once against the live DB. | medium (judgment — gates feature sign-off, not a known bug) | blocked-on hands-on streak-grid testing |
| B2 | Finished-book flow validation | review/Review_260612_5.md (#1–#8, all (a)); CLAUDE.md L414 region | EOF→finished write, `unfinish_book`, `_eof_book_id` lifecycle all audited correct, but the finished/unfinish/re-finish + revert sequence (and the EOF banner dismiss triggers) were traced statically, not exercised live. | low–medium (judgment — audit clean, residual is "unverified," not "broken") | blocked-on hands-on finished-book testing |
| B3 | `closeEvent` does not clear `_eof_book_id` | review/Review_260612_5.md Findings #1 ([app.py:2412]) | Benign today (event persisted, process exits) — flagged only because it sits in the finished-book dismiss-trigger family that B2 validates. Add `_dismiss_eof_prompt()` to `closeEvent` only if transient banner state ever persists across restarts. | low | not started |

---

## 2. Independent — small (< ~30 min fixes)

| # | Title | Location(s) | Issue (now) | Severity | Status |
|---|-------|-------------|-------------|----------|--------|
| S1 | `KEY_Q` quote-rotation shortcut — remove before release | NOTES.md L558-560 & L1215-1216 (`app.py` keyPressEvent) | Testing-only shortcut (`_rotate_quote` on `Key_Q` in empty state). Tagged `# TODO: remove before release`. | low (release-blocker by category, trivial fix) | not started |
| S2 | Speed shimmer fires when speed already default | NOTES.md L112-114 (`_on_speed_right_clicked`) | Right-click always plays shimmer + re-sets default even when current == default. Add float-tolerant guard (`round(...,9)` like `sync_btn`). | low | not started |
| S3 | Tag action button `check→delete` 2s timer clobbers a slow edit | NOTES.md L674-676; review/Review_260612_8.md Findings #1 ([tag_manager.py:622]) | Unguarded `singleShot(2000, →"delete")` reverts the save-affordance if the user types a new rename within 2s (visible to a slow single-keystroke edit). Fix: cancel/invalidate the timer in `_on_tag_name_changed` on `→save`. | low (UX papercut, not correctness) | not started |
| S4 | `_on_thumb_delete` ignores file-delete return value | NOTES.md L1203-1204 ([cover_panel.py:444]) | Silent failure leaves an unreferenced cover file on disk; at minimum log it. | low | not started |
| S5 | `cover_panel` delete ordering — file before DB | NOTES.md L1200-1201 | On delete, file is removed before the DB row; a failed DB delete leaves a broken-image reference. Correct order: DB row first, then file. | low | not started |
| S6 | `library_panel_animation.finished` duplicate-connection risk | NOTES.md L871-872 ([panels.py:86] / [panels.py:223]) | `_start_library_entry` / `_close_library_flow` connect `finished` with no disconnect-before-connect; double-call before completion accumulates a connection. Low frequency (most paths guarded). Apply the disconnect-before-connect pattern. | low | not started |

---

## 3. Independent — larger (refactors)

| # | Title | Location(s) | Issue (now) | Severity | Status |
|---|-------|-------------|-------------|----------|--------|
| L1 | **P6-D** — `singleShot(320ms)` panel reopen → `all_panels_hidden` signal | NOTES.md L549-550 (P6-D) + L652-660 ("timer vs signal"); review/Review_260612_8.md #6 ([app.py:1075]) | Magic 320ms (longest 300ms close + 20 margin) in `_on_open_tag_manager_from_detail`; silently breaks if a panel duration changes. Fix: emit `all_panels_hidden` from `PanelManager` when the last close animation completes. **Design must decide whether 500ms `blur_animation` counts toward "hidden"** (recommend: no — reopen contract is "off-screen," not "idle"). Single site, no duplication. | medium | not started (fix-with: mini-player panel-construction pass) |
| L2 | **P6-A** — `book_ready` two-slot deferred mechanism | NOTES.md L546-547 | `book_ready` drives both `_on_file_ready` and `_on_file_loaded_populate_chapters` via two independent deferred flags (`_file_ready_deferred`/`_chaps_deferred`); if one drains and the other doesn't (VT load-order race), state is inconsistent. | medium | not started (bundle with L1/L3) |
| L3 | **P2-C** — `PanelManager` patched post-construction | NOTES.md L543-544 | `book_detail_panel` + its animation are monkey-patched onto `PanelManager` after construction; it doesn't own all panels at init. Fragile, not broken. | low | not started (bundle with L1/L2 — "fix all three together") |
| L4 | VT sessions not recorded across file switches | NOTES.md L1178-1179; CLAUDE.md L409 | `file_switched` (mid-book VT transition) isn't threaded into `SessionRecorder`; a VT file boundary is treated as a new play event, mis-attributing listening time. | medium (judgment — real data-accuracy gap, deferred) | not started (do when session recording next touched) |
| L5 | Sleep timer blocks session recording | CLAUDE.md L410; NOTES.md (session-gaps) | Sleep window prevents session recording entirely. Product/architecture decision deferred. | low–medium (judgment) | not started |
| L6 | Drop deprecated `book_path` args (write_session / write_book_event) | NOTES.md L531-533 | Both still accept+write `book_path` alongside `book_id` (kept for rollback). Remove params + column writes, then run the column-drop pass (L7). | low | not started (prerequisite for L7) |
| L7 | Drop deprecated `book_path` columns (sessions/events/tags) | NOTES.md L628-630 | `listening_sessions`/`book_events`/`book_tags` retain unused `book_path TEXT`. Migration via `CREATE TABLE … AS SELECT` (SQLite < 3.35 has no `DROP COLUMN`). All queries already use `book_id`. | low | blocked-on L6 (stop writing first) |
| L8 | Migrate `book_files` to `book_id` FK | NOTES.md L535-537 & L632-634 | `book_files` still keyed on `(book_path, file_path)`. Isolated to VT/scanner path. | low | not started (do when VT next worked on) |
| L9 | `_update_pattern_visuals` duplication | NOTES.md L554-556 | `app.py` and `settings_controller.py` both update the pattern-button visual state with overlapping responsibility. | low | not started (next settings-panel pass) |
| L10 | `_cover_cache` unbounded (no eviction) | CLAUDE.md L400; NOTES.md L878-879 ([library.py:43]) | Module-level `book_id→QPixmap` dict never pruned; ~300KB/entry. Not realistic at the 4-per-book cap, but revisit if cap raised. Fix: LRU ~200 entries. | low | not started |
| L11 | `CoverLoaderWorker` anonymous `type()` objects | CLAUDE.md L402 | stats_panel/tag_manager build throwaway `type('_X',(),{...})()` shims to pass path/id to the worker (path→ID migration residue). Clean up in next cover refactor. | low | not started |
| L12 | `chapter_list._activate_item` reads private `player._virtual_timeline` | NOTES.md L981-982 ([chapter_list.py:283]) | UI coupling to a private Player attr. Fix: public `Player.is_virtual_timeline` (or route activation through one Player method). | low | not started (Player public-API pass) |
| L13 | Book-switch state split on DB failure | NOTES.md L883-884 ([app.py:1449-1458]) | `_on_book_selected_from_library` sets `current_file` then does 4 unguarded DB/config side effects; a mid-sequence DB raise leaves `current_file` pointing at the new book while mpv plays the old. Needs rollback or deferred `current_file` assignment. | low (rare — needs DB already failing) | not started |

---

## 4. Documentation only

| # | Title | Location(s) | Issue (now) | Severity | Status |
|---|-------|-------------|-------------|----------|--------|
| D1 | Tag reserved-row height 32px→21px | CLAUDE.md (tag-manager desc); NOTES.md L662-668; review/Review_260612_8.md #2 | The real fixed height is **21px** (`tag_manager.py:336`); "32px" was only ever in an audit checklist. | n/a | **done this task** — corrected in CLAUDE.md (added the 21px fact to the tag-manager description) |
| D2 | M4B chapter-stuck — trace recorded, needs instrumentation | CLAUDE.md L414; NOTES.md L1160-1167; review/Review_260612_6.md #6 | Confirmed NOT a Fabulor state-leak (`load_book` reset is clean). Next step is to **instrument mpv-native `chapter_list` readiness** at first `_on_time_pos_change` for affected M4Bs. Doc is current; the open work is investigation, not more documentation. | informational (doc) / medium (the underlying bug) | doc current; investigation not started |
| D3 | Progress-slider switch race — trace recorded | CLAUDE.md L413; NOTES.md L1169-1176; review/Review_260612_6.md #7 | Confirmed not a missing guard (three composable guards hold; residual is guard-release-ordering timing, self-corrects next tick). Lever documented if determinism ever wanted. No action unless it becomes user-visible. | informational (doc) | doc current; no fix planned |
| D4 | Pass-5 naming drifts (revert-btn QSS owner; `_current_sig`) | review/Review_260612_5.md Findings #3 | Audit-checklist wording was stale (QSS lives in `get_base_stylesheet`, guard is `_current_sig` not `_current_ids`); code is correct. Recorded so future audits don't re-flag. | n/a | resolved (noted in the pass; no doc owns a wrong claim) |

---

## 5. Out of scope / parked (not actionable as debt — listed to prevent re-discovery)

These appear in the sources but are explicit product decisions or won't-fix, not pending work:
- Sleep-timer state not persisted across restarts — CLAUDE.md L403 (product decision deferred).
- Book-detail panel background opacity — CLAUDE.md L406 (wanted eventually; not in scope).
- MP3 natural sort (2 before 10) — CLAUDE.md L405 (out of scope for v1).
- Screen drag 4K→1080p cover scaling needs `QWindow.screenChanged` — CLAUDE.md L404 (parked).
- Theme transitions via per-element `@Property(QColor)` — CLAUDE.md L401 (long-term; `THEME_ANIM_TODO` markers; Themes-tab QSS complexity makes it non-trivial).
- Deleted/excluded book UI in stats panel (monochrome cover, read-only metadata, hidden Cover+Tags) — CLAUDE.md L407 (deferred to "Session 7").
- "J"-glyph clip in Timeline date labels — NOTES.md L54 (marked unresolved, but a follow-up "Resolution" note exists; treat as fixed unless a regression appears).
- Semi-transparent history rows — NOTES.md L88-108 (investigation dead-end; cosmetic; effort/risk poor).
- Missing-file edge cases (partial VT folder removal; removable-drive unmount mid-buffer) — NOTES.md L164-188 (logged-not-patched; need real removable media to test).
- Cover-panel duplicate-cover detection — NOTES.md L1197-1198 (implement before the 4-slot cap becomes user-visible).
- Chapter-nav undo/restore near boundaries — NOTES.md L1187-1191 (deferred; needs boundary testing).
- Cold-start cover cache still hits mutagen — NOTES.md L898-899 (deferred; needs on-disk thumbnails or independent cache warm).
- Spurious sidebar expand during theme hover — NOTES.md L1080-1101 (root cause unknown, sporadic, not reliably reproduced; mitigation in place).

---

## Discrepancy / judgment notes

1. **No severity disagreements with prior passes.** Every severity above either matches what the source assigned or is a fresh judgment where none existed (marked "(judgment)"). I did **not** change any prior assignment.
2. **B1/B2 severity is mine to assign** — prior passes graded the *audit checks* (a)/(b)/(c), not the "needs live testing" residual. I set B1 medium / B2 low–medium because the audits found no defects; the risk is unverified-conclusion, not known-broken. Flagging in case you'd weight feature sign-off higher.
3. **D2's two severities are intentional:** the *documentation* is current (informational), but the *underlying M4B chapter-stuck bug* is medium and unfixed — the debt is "do the instrumentation," which is investigation work, not a doc gap. Listed under Documentation-only because that's where the prior passes filed it, with the split called out so it isn't mistaken for closed.
4. **L1/L2/L3 are one fix unit** per NOTES.md ("fix all three together in one deliberate structural pass — do not touch individually"). Listed separately for completeness but should be scheduled as a single task, ideally with the mini-player work.
5. **L6→L7 ordering is a hard dependency:** stop writing `book_path` (L6) before dropping the columns (L7), or rollback safety is lost.
