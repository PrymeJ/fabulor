# Debt Inventory

A flat index of known architectural/technical debt across the project. This file is an index,
not the source of truth — each entry links to its full writeup in CLAUDE.md ("Pending / Known
Debt") or NOTES.md ("Known Architectural Debt" and related sections). Update the source first,
then add/adjust the one-line pointer here. Don't duplicate prose into this file — that's the
same drift risk CLAUDE.md already warns about for `upsert_book`/`upsert_books_batch`.

Newest entries at the top within each section, matching SESSION.md/NOTES.md convention.

---

## Cover cache / rendering

- **`_sized_cover_cache` has no eviction, compounds `_cover_cache`'s debt below** (2026-06-24) — per-delegate-instance, keyed by `(book_id, device_w, device_h)`, grows by up to one extra entry per view-mode/DPR combination visited per book. Must be solved together with `_cover_cache` below, not independently. See NOTES.md "`_sized_cover_cache` has no eviction either".
- **`_cover_cache` has no eviction policy (unbounded growth)** — module-level dict, `book_id → QPixmap`, never pruned for the session's lifetime. Not realistic to hit in v1 given the 4-cover-per-book cap. See CLAUDE.md "Pending / Known Debt" and NOTES.md "`_cover_cache` has no eviction — unbounded growth".
- **`_lanczos_scale`'s `cover.toImage()` readback cost** (2026-06-24) — forces a `QPixmap` → CPU-memory `QImage` conversion once per cache miss; not measured, flagged as a plausible contributor if scroll-stutter/cover-load complaints come up later. See NOTES.md "`_lanczos_scale`'s `cover.toImage()` readback cost".
- **`CoverLoaderWorker` anonymous type objects in stats_panel/tag_manager** — path→ID migration context, deferred to next cover refactor. See CLAUDE.md "Pending / Known Debt".

## Theme system

- **Theme transitions** — long-term path is per-element `@Property(QColor)` animation; Themes tab QSS complexity makes it non-trivial today. `THEME_ANIM_TODO` comments mark instrumented widgets. See CLAUDE.md "Pending / Known Debt".
- **Spurious sidebar expand during theme hover — root cause unknown** (2026-05-26) — suspected race between the right-click handler and the panel animation guard; only mitigated (overlay mask unconditionally excludes sidebar geometry), not fixed. See NOTES.md "Theme System — Known Bugs (2026-05-26)".
- **`hide_all_panels` then open relies on a `QTimer.singleShot(320, ...)` magic number** instead of a real `all_panels_hidden` signal from `PanelManager`; silently breaks if any panel animation duration changes. Also has an unresolved design question (whether blur's 500ms should count toward "hidden"). Same item as CLAUDE.md's P6-D panel-construction debt — not a new entry, just the fuller writeup. See NOTES.md "`hide_all_panels` then open: timer vs signal (2026-05-26)".

## Stats / library UI

- **Semi-transparent session history rows — investigation dead end, not pursued** (2026-06-10) — goal was matching the Tags panel's row transparency; abandoned because `QScrollArea`'s internal viewport resists QSS/`WA_*` transparency attempts. Current baseline (solid alternating colors) is accepted. Root structural issue: a shared `get_stats_stylesheet()` makes this kind of scoped QSS override fragile — a dedicated stylesheet function for `BookDetailPanel` was named as a possible path but not pursued. Grey area: also reads as a deferred polish feature, not purely structural. See NOTES.md "Semi-transparent session history rows — investigation dead end".
- **Screen drag 4K→1080p: cover scaling doesn't update without scroll** — needs `QWindow.screenChanged`. See CLAUDE.md "Pending / Known Debt".
- **MP3 natural sort (2 before 10)** — out of scope for v1. See CLAUDE.md "Pending / Known Debt".

## Code structure / drift risk

- **`day_start_hour` date adjustment has no named helper** — `(datetime.now() - timedelta(hours=N)).date()` duplicated identically at 5 call sites (`db.py:784`, `db.py:1031`, `app.py:320`, `stats_panel.py:2615`, `stats_panel.py:2628`). Candidate for extraction to `_adjusted_today(day_start_hour)` when any site next needs touching. See CLAUDE.md "Pending / Known Debt".
- **`path_to_index()` lives on `LibraryPanel`, not `BookModel`** — noted as a location quirk, not yet a problem. See CLAUDE.md "Pending / Known Debt".
- **`library_panel_animation.finished` duplicate connection risk** — `_start_library_entry`/`_close_library_flow` (panels.py) connect `finished` with no guard against double-connection if called twice before the animation completes. Low frequency (most paths already guarded). See NOTES.md "`library_panel_animation.finished` duplicate connection risk".

## Error handling / robustness

- **Book switch state split on DB failure** — `_on_book_selected_from_library` (app.py:1449–1458) has no rollback if `db.update_last_played` raises mid-sequence; `current_file` can end up pointing at a book mpv isn't actually playing. Not a common failure mode. See NOTES.md "Book switch state split on DB failure".
- **`cover_path` can be an audio file path in an edge case** — only when thumbnail `img.save()` fails (disk full/permissions); `CoverLoaderWorker` then silently shows no cover rather than crashing. Accepted failure mode, no fix planned. See NOTES.md "cover_path can be an audio file path in edge case".
- **Known gaps — missing-file edge cases not yet exercised** (2026-06-08) — two scenarios identified but unverified: partial VT folder removal (some but not all multi-file book files deleted externally), and removable/network drive unmount mid-buffer (likely funnels through existing error handling, but timing/UX unconfirmed without real hardware). See NOTES.md "Known gaps — missing-file edge cases not yet exercised".
- **Config `balance` key has no bounds validation** — `config.set_balance()` has no clamp; a corrupted/manually-edited QSettings value could pass an out-of-range balance to mpv's audio filter silently. Fix: clamp `[-1.0, 1.0]` in `set_balance`, deferred to next config touch. See NOTES.md "Config — `balance` key has no bounds validation".
- **`upsert_cover` deletes the file before the DB row** — wrong order; if the DB delete fails, the DB still references a now-missing file (broken thumbnail). Correct order is DB-first. Address when cover panel is next touched. See NOTES.md "`upsert_cover` delete ordering — file before DB".
- **`_on_thumb_delete` doesn't check the file-delete return value** — a silent file-deletion failure leaves an orphaned file with no log. At minimum, log the failure. See NOTES.md "`_on_thumb_delete` does not check file delete return value".

## Database / queries

- **`get_listening_time_per_period` — orphaned sessions collapse under NULL `book_id`** (2026-05-27) — pre-migration sessions with a NULL `book_id` collapse into one GROUP BY row with an unreliable `book_path`. Low-impact, no fix planned — documented for awareness. See NOTES.md "`get_listening_time_per_period` — orphaned sessions collapse under NULL book_id".

## Cold-start / position-restore paths

- **Cover cache cold start still hits mutagen** — `_load_cover_art`'s cache check is keyed by the library-panel-populated cache; on a cold start (library never opened this session) the cache is empty and mutagen runs synchronously as before. Two fix options identified, neither implemented. See NOTES.md "Cover cache — cold start still hits mutagen".
- **Position-restore fragility** — `_restore_position` does an extra `db.get_book()` read purely as a workaround for `_current_book` potentially being stale relative to a config sync. Could be eliminated by reordering; "requires care." See NOTES.md "Position restore fragility".
- **mpv `loadfile start=` option does not work** — environmental limitation in the current mpv/python-mpv combination, not a Fabulor bug; position-restore relies on a separate `time_pos` assignment instead. Revisit if a future mpv/python-mpv version fixes upstream. See NOTES.md "mpv `loadfile start=` option does not work".

## ChapterList

- **`fade_out` signal accumulation** — double-calling `fade_out` before the animation completes can leave `_hide_connected` semantically stale; confirmed safe in practice today, but flagged as a future risk. Deferred until chapter-list animation is next refactored. See NOTES.md "ChapterList — Deferred Fixes (2026-05-15)".

## VT (multi-file) — fully deferred

- **Progress slider race on book switch** — traced, not a missing guard; residual is a guard-release-ordering timing overlap that self-corrects on the next 200ms tick. See CLAUDE.md "Pending / Known Debt" → "VT open issues".
- **M4B chapter stuck intermittently** — traced; likely mpv-native `chapter_list` readiness timing for specific files, not a Fabulor state leak. See CLAUDE.md "Pending / Known Debt" → "VT open issues".
- **Rapid book switch (VT → any) regression** — symptom of a double-handler invocation resetting progress; fixed via disconnect-before-connect in `load_book`, kept here as a regression-test reminder.

## Resolved (kept for history — remove once confident it won't regress)

- **Stats page sluggishness on Weekly/Monthly tabs** — RESOLVED: `BookDayRow`/`FinishedBookThumb` now load covers asynchronously via `CoverLoaderWorker` with placeholder fallback + `_cover_cache` hit check. See NOTES.md "Stats page sluggishness on Weekly and Monthly tabs".
