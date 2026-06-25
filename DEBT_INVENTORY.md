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

## Session recording

- **VT file switches not threaded into session recording** — `session_recorder.close/open` wiring doesn't account for mid-book VT file transitions; `file_switched` isn't fed in. Fully deferred. See CLAUDE.md "Pending / Known Debt".
- **Sleep timer suppresses session recording during the sleep window** — fully deferred. See CLAUDE.md "Pending / Known Debt".
- **Sleep timer state not persisted across restarts** — `get_sleep_duration`/`get_sleep_mode` never read on startup. Product decision deferred. See CLAUDE.md "Pending / Known Debt".

## Stats / library UI

- **Deleted/excluded book UI in stats panel** — sessions/history for excluded books show with no visual differentiation; duration label, cover, metadata, Cover+Tags tabs all need treatment. Deferred to Session 7. See CLAUDE.md "Pending / Known Debt".
- **Screen drag 4K→1080p: cover scaling doesn't update without scroll** — needs `QWindow.screenChanged`. See CLAUDE.md "Pending / Known Debt".
- **Book detail panel background opacity** — user wants it opaque eventually; not in current scope. See CLAUDE.md "Pending / Known Debt".
- **MP3 natural sort (2 before 10)** — out of scope for v1. See CLAUDE.md "Pending / Known Debt".

## Code structure / drift risk

- **`day_start_hour` date adjustment has no named helper** — `(datetime.now() - timedelta(hours=N)).date()` duplicated identically at 5 call sites (`db.py:784`, `db.py:1031`, `app.py:320`, `stats_panel.py:2615`, `stats_panel.py:2628`). Candidate for extraction to `_adjusted_today(day_start_hour)` when any site next needs touching. See CLAUDE.md "Pending / Known Debt".
- **`path_to_index()` lives on `LibraryPanel`, not `BookModel`** — noted as a location quirk, not yet a problem. See CLAUDE.md "Pending / Known Debt".
- **`library_panel_animation.finished` duplicate connection risk** — `_start_library_entry`/`_close_library_flow` (panels.py) connect `finished` with no guard against double-connection if called twice before the animation completes. Low frequency (most paths already guarded). See NOTES.md "`library_panel_animation.finished` duplicate connection risk".

## Error handling / robustness

- **Book switch state split on DB failure** — `_on_book_selected_from_library` (app.py:1449–1458) has no rollback if `db.update_last_played` raises mid-sequence; `current_file` can end up pointing at a book mpv isn't actually playing. Not a common failure mode. See NOTES.md "Book switch state split on DB failure".
- **`cover_path` can be an audio file path in an edge case** — only when thumbnail `img.save()` fails (disk full/permissions); `CoverLoaderWorker` then silently shows no cover rather than crashing. Accepted failure mode, no fix planned. See NOTES.md "cover_path can be an audio file path in edge case".

## VT (multi-file) — fully deferred

- **Progress slider race on book switch** — traced, not a missing guard; residual is a guard-release-ordering timing overlap that self-corrects on the next 200ms tick. See CLAUDE.md "Pending / Known Debt" → "VT open issues".
- **M4B chapter stuck intermittently** — traced; likely mpv-native `chapter_list` readiness timing for specific files, not a Fabulor state leak. See CLAUDE.md "Pending / Known Debt" → "VT open issues".
- **Rapid book switch (VT → any) regression** — symptom of a double-handler invocation resetting progress; fixed via disconnect-before-connect in `load_book`, kept here as a regression-test reminder.

## Resolved (kept for history — remove once confident it won't regress)

- **Stats page sluggishness on Weekly/Monthly tabs** — RESOLVED: `BookDayRow`/`FinishedBookThumb` now load covers asynchronously via `CoverLoaderWorker` with placeholder fallback + `_cover_cache` hit check. See NOTES.md "Stats page sluggishness on Weekly and Monthly tabs".
