# Fabulor — Claude Context

## What this file is for

This is a reference document for Claude and Claude Code. It records **what has been built**, key
architectural decisions, and current state — it is the single authoritative source for the
architecture rules and project state. (GEMINI.md was removed 2026-06-12 when Gemini left the
workflow; do not reference it.) This file answers "where are we now?"

---

## Running the app (Claude Code / Bash tool)

**Always activate the venv before running** — do not invoke `fabulorenv/bin/python` directly:

```bash
source fabulorenv/bin/activate && python main.py
```

Activation sets `LD_LIBRARY_PATH=/home/pryme/Coding/Python/fabulor/fabulorenv/lib/stub`, which
contains a `libcaca.so.0` shim that resolves a symbol-version conflict
(`_nc_curscr@NCURSES6_TINFO_5.7.20081102`) between the system's `libcaca` package and its
`libncursesw`/`libtinfo` packages — confirmed via `objdump -T` to be a genuine broken system
package mismatch (`libncursesw.so.6` imports `_nc_curscr` but `libtinfow.so.6` doesn't export it;
only the non-wide `libtinfo.so.6` does). Without the venv's `LD_LIBRARY_PATH`, `import mpv` raises
`OSError: .../libcaca.so.0: undefined symbol: _nc_curscr, version NCURSES6_TINFO_5.7.20081102`,
which `player.py`'s top-level `try/except` masks behind a generic "❌ libmpv not found" message —
so the real cause looks like a missing-library problem when it is actually an `LD_LIBRARY_PATH`
problem. Setting `LD_LIBRARY_PATH` to other values (e.g. `/usr/lib64`, or PySide6's bundled Qt lib
dir) does not fix this and can break Qt loading instead — the venv's `lib/stub` shim is the only
known-working path. This is unrelated to the MPV-init rule below; do not conflate the two.

To launch the app in the background and capture output without leaving stray processes:
```bash
source fabulorenv/bin/activate
python main.py > /tmp/fabulor_run.log 2>&1 &
# ... test, then:
kill %1   # or: pkill -f "python main.py" — but check `ps aux` first if an `entr` dev-loop is also running
```

---

## Critical Architecture Rules

These rules exist because violating them caused real bugs. The reasoning is documented in
SESSION.md. They are not arbitrary constraints — they are load-bearing until proven otherwise
in a specific context.

If you believe the cleanest solution requires crossing one of them, stop and explain why before
proceeding. Don't route around them silently. The bar for crossing one is: you've identified a
specific reason the rule doesn't apply in this case, not just that it would be simpler to ignore it.

---

### DO NOT modify, refactor, or touch any code related to MPV initialization under any circumstances. This includes the _ensure_mpv() method, the load_book() method's MPV init block, the locale.setlocale(locale.LC_NUMERIC, "C") call, and all MPV constructor arguments (vo, ao, vid, ytdl, keep_open). This code resolves a hard-won, non-obvious bug involving libcaca, libtinfo, and Qt's locale reset on Wayland/openSUSE. Any "improvement," "cleanup," or "fix" to this block will break the app. If you think something in this block needs changing, say so explicitly and wait for confirmation before touching it.

### DO NOT use self.player.chapter to derive which chapter the UI should display. It looks like the obvious choice but it is wrong — mpv updates the chapter property asynchronously and it will be ahead of or behind time_pos after any seek. Always derive the current chapter by walking self.player.chapter_list and finding the last entry whose time <= pos + _CHAPTER_WALK_TOLERANCE. As of Session 3 (2026-06-13) that tolerance is 0.5 (was 0.35); it must exceed mpv's measured ~0.37s PAUSED-seek undershoot, else a paused Next/Prev resolves the chapter just left and the chapter slider sticks. (The old "~0.25s short of nominal" rationale was disproven by measurement: mpv overshoots ~0.09s while playing and undershoots ~0.37s while paused.) This rule applies everywhere in _sync_chapter_ui and any future method that maps a playback position to a chapter index.

### DO NOT connect _on_file_ready to the file_loaded signal. It must only connect to book_ready. book_ready fires once per book (before any file for VT books; after file-loaded for non-VT). file_loaded fires on every mpv file-loaded event including VT file switches mid-book. If _on_file_ready runs on every file switch, it triggers position restore, which triggers another file switch, causing a quadruple-advance feedback loop. This was the root cause of two reverted stage 3 implementations.

**book_ready invariant:** For VT books, `book_ready` is emitted from `ungate_play` or `_on_playlist_resolved` (before any file loads, while VT state is ready). `_on_file_loaded` never emits `book_ready` for VT books — it emits `file_switched` instead. For non-VT books (M4B, single-file), `_on_file_loaded` is the only emitter of `book_ready`. These two paths are mutually exclusive and must never converge.

**Book-switch state machine (`book_switch.py`, `self._switch: BookSwitchState`):** The switch-specific transition flags live on one object, not as loose `MainWindow` attributes. `phase` (`IDLE`/`LOADING`/`RESTORING`) is *derived* from the sub-flags, so there is no fragile terminal transition. Flag mapping (old attr → SM): `_mpv_ready` → `in_deadzone` (inverted; set by `begin()` at selection, cleared by `library_revealed()` in `panels._on_library_hidden`); `_pre_switch_slider_value` → `flow_pending_progress` + `take_progress_target()`; `_pre_switch_chap_slider_value` → `flow_pending_chapter` + `take_chapter_target()`; `_chaps_dur_retried`/`_file_ready_deferred`/`_chaps_deferred` → same-named SM members. The SM owns ONLY switch-specific state. The **orthogonal** guards — `player._is_seeking`/`_seek_target`, the slider-drag flags, `_flow_anim` running state, `mp3_seek_reload_pending` — stay separate and the SM composes with them (e.g. `_sync_progress_sliders` reads `not is_seeking and not slider_animating and not self._switch.flow_pending_progress`). Do NOT fold those into the SM: they fire for chapter nav / manual seeks / theme color animations and are the fixes for the rules below. Known gap: no stale-book guard on rapid switching (the SM is the natural home for a future `generation` counter, deliberately not added). **Consume-once constraint:** `take_progress_target()`/`take_chapter_target()` are consuming reads — each captured value can be read exactly once, which is what flips `flow_pending_*` to False and tears the switch down. A future fix that needs to *inspect* a pre-value without consuming it must add a non-consuming peek property; do NOT read-then-restore via `take()`, and do NOT make a guard depend on `take()`'s side effect.

### DO NOT read self.progress_slider.value() (or any slider's .value()) in _on_file_ready to compute the "new position" for a switch animation. The slider value is stale at that point — _update_ui_sync's setValue call is gated on not slider_animating, not is_seeking, and not self._switch.flow_pending_progress, and may not have run yet. The legitimate pre-switch capture happens earlier, in self._switch.begin(...) at selection time; _on_file_ready consumes it via self._switch.take_progress_target(). Always compute the target slider value from the authoritative data: int((new_progress / self.player.duration) * 1000).

**Duration race corollary (also _on_file_ready and _on_file_loaded_populate_chapters):** For non-VT books, `player.duration` (`_cached_duration`) is populated by an mpv property observer on the mpv thread. In rare timing conditions it may be None when the queued `book_ready` signal is processed on the Qt main thread. Two rules apply: (1) in `_on_file_ready`, if `not dur`, set `new_val = None` and skip the animation entirely — never animate to 0 as a fallback, because `not dur` and `new_progress == 0` are different cases; (2) in `_on_file_loaded_populate_chapters`, if `not dur`, schedule a 150ms retry via the `self._switch.chaps_dur_retried` flag (reset on each book selection by `self._switch.begin(...)` in `_on_book_selected_from_library`) rather than calling `_set_chapter_ui_active(False)` prematurely — that makes the chapter label text transparent for the entire session.

**Chapter flow animation target:** `_on_file_loaded_populate_chapters` must compute `new_chap_val` from a chapter-list walk against `new_progress` (same algorithm as `_sync_chapter_ui`), NOT from `self.chapter_progress_slider.value()`. At the time this handler runs, the 200ms timer has not ticked; the slider still holds the previous book's chapter position, which equals `pre_chap`, making `pre_chap != new_chap_val` always False and degrading `animate_to` to `setValue`.

### DO NOT remove the animation-state guard in _sync_progress_sliders or _sync_chapter_ui. Both methods check whether the flow animation is running before calling setValue. If that check is removed, the 200ms UI timer will fight the animation frame-by-frame, causing visible jitter. The guard must survive any refactor of those methods.

### DO NOT remove the `self._switch.flow_pending_chapter` guard from `_sync_chapter_ui`
(Formerly `_pre_switch_chap_slider_value is not None` — same predicate, now read off the switch state machine.) Without this guard the 200ms timer can fire between the pre-switch capture in `self._switch.begin(...)` (`_on_book_selected_from_library`) and the `animate_to()` call in `_on_file_loaded_populate_chapters`, writing `setValue(chapter_at_pos_0)` to the slider. `animate_to()` then resets `_value = start` (= pre_chap) before animating, so the user sees: pre_chap → 0 (timer) → pre_chap (animate_to reset) → flow. This is the "blinks first, jumps, then flows" artifact. Mirrors the `flow_pending_progress` guard in `_sync_progress_sliders`. The capture is consumed once via `self._switch.take_chapter_target()`.

### DO NOT remove either gate from `_update_chapter_label_from_index`
Two gates must both survive: `player.is_seeking` and `self._switch.flow_pending_chapter`.

`is_seeking` suppresses VU-meter oscillation: intermediate `time_pos` events during a seek fire `chapter_changed` as mpv scans through chapter boundaries; the gate blocks all updates until the seek settles, then fires one clean update. The CUE-mode optimistic emit from `seek_async` is also suppressed — intentional; settle-time `time_pos` provides the update within ~100ms.

`flow_pending_chapter` covers the deferred populate path. When `_on_file_loaded_populate_chapters` is delayed until after `_on_library_hidden`, the seek can settle before the 50ms drain fires — leaving `_is_seeking` already False when `populate()` is called. `populate()` emits `currentRowChanged(0)`, which fires `chapter_changed(0)` and would write chapter 0's name to the label before `_sync_chapter_ui` corrects it. `flow_pending_chapter` is True throughout the `try` block of `_on_file_loaded_populate_chapters` (consumed only after it via `take_chapter_target()`), so this gate blocks the spurious index-0 write regardless of seek state.

### DO NOT restore the `_seek_target is None` branch in `_on_time_pos_change`
The original `if self._seek_target is None or abs(...) < 1.0` condition caused a race: `load_book` sets `_is_seeking=True` with `_seek_target=None`; the first `time_pos=0` from the new file cleared `_is_seeking=False` immediately; `_sync_progress_sliders` (which guards on `not is_seeking`) was then unblocked before `_on_file_ready` ran, and the 200ms timer wrote 0 to the slider. The fix: only clear `_is_seeking` when `_seek_target is not None` AND position is within 1.0s. `load_book` also now resets `_seek_target = None` (alongside `_cached_time_pos` and `_cached_duration`) to clear any stale target from an interrupted seek on the previous book. `_restore_position` explicitly clears `is_seeking=False` for the no-progress case (where no `seek_async` is called and `_seek_target` stays None), so the slider can update during normal playback. Do NOT add the asymmetric-clear back — it was the root cause of the "0% flash before the flow animation" bug.

### DO NOT store `_seek_target` in LOCAL coordinate space (it must be GLOBAL)
The settle in `_on_time_pos_change` is `abs((value + _file_offset) − _seek_target) < 1.0` — `_seek_target` is compared against the GLOBAL position, so it MUST be global. The VT cross-file follow-up seek in `_on_file_loaded` previously stored `_seek_target = pending` (a LOCAL offset into the just-loaded file); for any file past the first, `abs(global − local) ≈ cumulative_start` never fell below 1.0, so `is_seeking` stuck True forever → permanent chapter-UI freeze (FIXED 2026-06-15, `29b266c`). Correct form there: `_seek_target = pending + target_file['cumulative_start']` (use the timeline entry, self-consistent with `_current_vt_index`, not the bare `_file_offset` field); the mpv `command_async('seek', pending, ...)` stays LOCAL. The `[VT-DESYNC]` tripwire in `_on_file_loaded` guards the assumption that VT loads are serialized (verified — see NOTES).

### DO NOT set `is_seeking = True` outside of `seek_async` / a path that also sets `_seek_target`
`is_seeking` and `_seek_target` are cleared together by the settle (`...and _seek_target is not None`), so any path that sets `is_seeking = True` WITHOUT a matching `_seek_target` strands the flag → settle can never clear it → permanent freeze. This bit twice: the chapter-list-click native path (fixed) and `handle_prev`/`handle_next`/`_on_prev_right_click` setting `is_seeking = True` unconditionally after a nav call that no-ops at the chapter[0]/last-chapter boundary (FIXED 2026-06-15, `29b266c`). Rule: let `seek_async` own `is_seeking` — it sets both together, and ONLY when it actually seeks. Do not re-add app-level `is_seeking = True` to nav handlers.

### Automated tests exist (`tests/`, pytest, dev-only)
`_on_time_pos_change`/seek-state is a near-pure state machine (no mpv, no QApplication). Run `source fabulorenv/bin/activate && pytest tests/ -q`. Keep green on any seek-path change — these encode the `is_seeking`/`_seek_target` invariants whose violations caused repeated freezes/regressions. pytest is in `requirements-dev.txt` (NOT runtime `requirements.txt`).

### DO NOT let `_do_fade_with_slider_animation` iterate `chapter_progress_slider` when `_chapter_ui_active` is False
The slider loop in `_do_fade_with_slider_animation` must skip `chapter_progress_slider` when `mw._chapter_ui_active` is `False`. The theme overlay punch-through re-exposes the slider during the window between `_apply_stylesheets` (which repolishes child widgets and overwrites transparent colors with theme colors) and the `_set_chapter_ui_active` reapplication at the end of `_apply_stylesheets`. Without the guard the slider briefly renders at full opacity, causing a visible flash. Guard: `if attr == 'chapter_progress_slider' and not mw._chapter_ui_active: continue`.

### DO NOT restore `show_metadata=False` to `library_controller.apply_library_state`
The `show_metadata=False` argument was removed from the `apply_library_state` call in
`library_controller.py` on 2026-05-11. Do not restore it. It was silently overriding cover
display on every book switch — `_load_cover_art` owns `metadata_label` visibility and the
call was fighting it. If you think metadata visibility needs to be controlled at the
`apply_library_state` call site, stop and explain why before touching it.

### DO NOT use `self.chapter = idx` for chapter navigation anywhere
Always navigate to a chapter by seeking to its boundary with a position-based walk of `chapter_list`, never by native `self.chapter = idx` assignment (mpv's native chapter assignment undershoots boundaries and causes drift). This applies in `chapter_list.py`, `player.py`, and anywhere else chapter navigation is triggered. The seek target is `nominal + _chapter_seek_offset()`, where `_chapter_seek_offset()` is mode-aware: `_EMBEDDED_CHAPTER_SEEK_OFFSET` (−0.09, cancels mpv's ~0.09s overshoot) for embedded M4B, `_CHAPTER_BOUNDARY_EPSILON` (+0.35) for VT/CUE.

**As of 2026-06-13 (Session 3 cont.), embedded-M4B chapter-LIST clicks NO LONGER use `self.chapter = idx`.** The old exception ("embedded clicks use native nav because mpv owns boundaries") was carved out (git `e243193`, 2026-05-17) because the *then-current* `seek_async + 0.35` drifted on embedded M4B. The Session-3 calibrated-offset model (−0.09) made that obsolete: embedded clicks now route through `Player.activate_chapter_index(idx)` → `seek_async`, same as Prev/Next and VT/CUE clicks. This was required to fix a freeze — native `self.chapter = idx` never set `_seek_target`, so the chapter-UI's `is_seeking` guard never cleared and the chapter slider/labels stayed frozen until a manual slider click. Do NOT restore the native-click path. The native `chapter` *setter* is now only reachable via the `chapter` property (unused for navigation); the native `chapter` *getter* is still read by `apply_smart_rewind` to clamp to chapter start — that read is valid (mpv updates its native chapter from playback position regardless of how the seek was issued).

### DO NOT restore any emit in `_on_chapter_change` — it is fully suppressed as of 2026-06-01
`_on_chapter_change` now contains only `return`. `_on_time_pos_change` drives `chapter_changed` universally for all book types (VT, CUE, embedded M4B) via position walk. The old `_is_seeking` guard on `_on_chapter_change` was insufficient: `_on_time_pos_change` clears `_is_seeking` first, so by the time `_on_chapter_change` fires the guard is already False — it emitted stale mpv native chapter values, causing snap-back on Prev/Next while paused. Do not add back any emit here.

### DO NOT set `_virtual_timeline` for CUE books
CUE mode is indicated solely by `_chapter_list` being non-`None` with `_virtual_timeline` remaining `None`. Setting `_virtual_timeline` would activate VT file-switching machinery on a single-file book.

### DO NOT simplify `Player.terminate()`
It must store the instance reference, clear `self.instance`, call `terminate()`, then `wait_for_shutdown()`. Without `wait_for_shutdown()`, libmpv's internal threads outlive Qt's cleanup and crash in `avformat_close_input`. This was masked for an unknown period by a debug print. The sequence is intentional — do not reorder or remove steps.

### DO NOT hard-delete from the `books` table
`remove_scan_location` soft-deletes via `UPDATE books SET is_deleted = 1` — never `DELETE FROM books`. All rows, progress, covers, `book_files`, and session history must survive a location removal so they can be resurrected when the location is re-added. Any query that drives the library view must include `WHERE is_deleted = 0 AND is_excluded = 0`. Stats queries must not — they key off `book_path`/`book_title` in the sessions tables directly and must see all historical rows.

### DO NOT conflate `is_deleted` and `is_excluded`
They are two independent soft-delete flags on `books`. `is_deleted = 1` is set by `remove_scan_location` (location removed from scan list). `is_excluded = 1` is set by `set_book_excluded` (user explicitly removed a book via the trash button). Both reset to `0` in the `upsert_book`/`upsert_books_batch` ON CONFLICT blocks. Stats queries are intentionally unfenced by both flags — listening history and progress survive removal permanently.

**Scanner resurrection behaviour:** `scanner.py` builds `known_paths` from `get_all_book_paths()` (unfenced — all rows regardless of flags). Excluded/deleted books are therefore recognised as known and skipped during non-force scans, so they are NOT automatically resurfaces. A force rescan (`force_refresh=True`, triggered by the Rescan button) re-processes all paths and will call `upsert_books_batch`, resetting both flags. Do NOT change `known_paths` to use `get_all_books()` or any fenced query — doing so caused excluded books to be silently resurfaces on every scan (2026-06-06 bug).

**Location-readd resurrection (`restore_books_under_path`, 2026-06-08):** Re-adding a previously-removed scan location used to leave its books permanently hidden — `remove_scan_location` soft-deletes (`is_deleted=1`) but the scanner's `known_paths` skip (above) means a routine scan never re-processes those paths to flip the flag back, forcing a manual force rescan. `db.restore_books_under_path(path)` un-soft-deletes (`is_deleted=0`) books under `path`, called from `_on_scan_now_clicked` immediately after `add_scan_location`. It is intentionally narrower than a force rescan: it only flips `is_deleted`, gated on `is_excluded = 0`, so user-trashed books stay hidden and still require a manual force rescan — it must NOT touch `is_excluded`. This is a different code path from the scanner/`upsert_books_batch` resurrection above; keep them conceptually separate.

### DO NOT swap `get_book_count()` and `get_visible_book_count()` — they serve different purposes
`get_book_count()` queries `SELECT COUNT(*) FROM books` — all rows, including `is_deleted=1` and `is_excluded=1`. Correct for stats (which must see all historical rows). `get_visible_book_count()` queries with `WHERE is_deleted = 0 AND is_excluded = 0` — only rows visible in the library. `compute_library_state` uses `get_visible_book_count()` for `has_indexed_books`; never change it to `get_book_count()`. Using the unfenced count would make `has_indexed_books=True` even when the library panel shows 0 books (soft-deleted rows from a prior scan remain in the DB), routing the empty state into the no-book carousel instead of the scan/quote prompt.

### DO NOT pass `0.0` as `progress` to `upsert_book` or `upsert_books_batch`
The scanner does not know a book's saved playback position. Pass `None` if progress is unknown. The `COALESCE(NULLIF(excluded.progress, 0.0), books.progress)` in both upserts is a safety net against accidental `0.0` — it is not a contract that callers can rely on. Passing `0.0` would overwrite saved progress on any future DB engine that handles `NULLIF` differently.

### DO NOT keep upsert_book and upsert_books_batch out of sync
Both methods share identical SQL logic — any schema or ON CONFLICT guard change in one MUST be applied to the other. They differ only in execute vs executemany. The `CASE WHEN books.X_locked` guards for title, author, narrator, year are load-bearing: they prevent rescans from overwriting user-edited metadata. Skipping this sync causes silent data loss on rescans. (Implementation uses the bare-truthy form `CASE WHEN books.title_locked THEN ...`, not `= 1` — equivalent in SQLite since the column is `INTEGER NOT NULL DEFAULT 0`.)

### DO NOT remove the CASE WHEN books.X_locked guards from upsert ON CONFLICT
The guards `CASE WHEN books.title_locked THEN books.title ELSE excluded.title END` (and narrator/author/year equivalents) protect user-edited metadata from being overwritten by rescans. They must survive any future refactor. (The guard reads `books.title` on the locked branch and `excluded.title` on the unlocked branch; the bare-truthy `WHEN books.title_locked` is equivalent to `= 1` in SQLite.)

### DO NOT add separate save/lock widgets to BookDetailPanel
The metadata action button state is driven exclusively by `_MetaActionState` enum. Do not add `_save_label` or `_lock_btn` widgets — use `_set_meta_state()` to manage appearance.

### DO NOT set cursor or stylesheet on chapter widgets outside `_set_chapter_ui_active`
`_set_chapter_ui_active(active: bool)` is the sole owner of chapter slider cursor, chapter label stylesheets, and `WA_TransparentForMouseEvents` state. Do not set these directly in `_build_secondary_controls`, theme application, or any other call site. Theme changes repolish child widgets and clear instance stylesheets — `_apply_stylesheets` reapplies the correct state by calling `mw._set_chapter_ui_active(mw._chapter_ui_active)` at its end. The `_chapter_ui_active` flag tracks the logical state and must stay in sync: always route through `_set_chapter_ui_active`, never set flag or widget state separately.

### DO NOT call `_set_chapter_ui_active(False)` unconditionally at book selection time
For chaptered→chaptered switches, the chapter slider must remain visible and at the old position — it is the flow animation's start point. Hiding it unconditionally kills the flow: the slider clears, blinks, then animates from the old position instead of flowing smoothly. Protection against the `_set_bg_suppressed` repolish is handled by a lightweight `bg_color`/`fill_color` re-assert in `_set_bg_suppressed` itself, guarded by `not _chapter_ui_active`. That re-assert fires only when the slider is already inactive and is the correct and only place for this protection. The preemptive `_set_chapter_ui_active(False)` that previously lived in `_on_book_selected_from_library` was removed for exactly this reason — do not restore it.

---

## Tech Stack

PySide6 (Qt) + mpv via python-mpv. Python. SQLite. Mutagen for metadata.

---

## Collaboration Model

- **Claude**: architecture, decisions, code review, documentation, root-cause investigation
- **Windsurf / Copilot**: code generation
- **GPT**: critique

(Gemini was previously used for pipeline scripts / folder-naming conventions, kept in lane by a
GEMINI.md guardrail file; both were retired 2026-06-12.) The working model is "flag, confirm, then act."

## Conventions

- **SESSION.md entries are always prepended** (newest at the top), not appended.
- **All git commit messages must start with a verb** (e.g. `feat:`, `fix:`, `docs:`, `refactor:`).
- **After completing a task, flag if SESSION.md, NOTES.md, CLAUDE.md, or TESTING.md would benefit from an update** — but only when there is something specific and non-obvious worth recording, not as a reflexive offer after every change.

---

## Window

Fixed size: 300×564px (`setFixedSize(300, 564)` in app.py:379). Cover label has no minimum size
so it fills the fixed window. Do not fight this with per-widget minimum sizes.

---

## What's Built

A factual reference of what the app does, by subsystem. Reflects the code as audited 2026-06-13.

### Player — playback modes

All mode detection happens in `_resolve_playlist()` (run async on a `QThreadPool` worker; result delivered to the Qt thread via the internal `_playlist_resolved` signal, then `_on_playlist_resolved`). Audio extensions: `.m4b`, `.mp3`, `.flac`, `.m4a`.

- **Single-file M4B/M4A, embedded chapters** — one audio file, `chapter_list_source == 'embedded'` (default). Chapter boundaries come from mpv's native `instance.chapter_list`, which is snapshotted into `_chapter_list` once at file-loaded time by `cache_chapter_list()` (called from `_on_file_loaded_populate_chapters`). This sets `_is_embedded_m4b = True`. After that point `_chapter_list` is non-None for chaptered embedded M4B, just like CUE/VT — the `chapter_list` property returns it without ever touching `instance.chapter_list` again during playback. Unchaptered embedded M4B: `cache_chapter_list()` sees an empty list and leaves `_chapter_list = None` / `_is_embedded_m4b = False`.
- **Single-file M4B/M4A, CUE chapters** — same single-file condition but source is `'cue'`. `_select_cue_file` matches a `.cue` by the Title part of the `"Author - Title"` folder name (exact then substring). `_parse_cue` validates: FILE stem matches the audio stem, first timestamp = 0.0, strictly increasing, no chapter ≥ file duration, ≥ 2 chapters; reads with `utf-8-sig` (Windows ripper BOM). On success `_chapter_list` is populated and `_virtual_timeline` stays `None` — that combination is the CUE-mode flag. On failure: silent fallback to embedded.
- **Multi-file (MP3/M4A/FLAC) via Virtual Timeline (VT)** — folder has multiple audio files and `db.get_book_files` returns rows. `_virtual_timeline` is a list of `{file_path, cumulative_start, duration}`; `_chapter_list` is synthesized from each file row's `cumulative_start_ms` + `title`; `_book_duration` is the sum. Plays the first file directly. If `book_files` is empty, falls back to playing the folder path as-is. State: `_file_offset`, `_current_vt_index`, `_pending_local_pos`, `_is_vt_file_switch`, `_last_vt_chapter`.
- **Single MP3** — one `.mp3`, no `_chapter_list`.
- **No audio files** — `_resolve_playlist` returns the raw folder path; `_on_playlist_resolved` sees a directory and emits `load_failed("no audio files in folder")`.

### Player — playback behaviors

- **Gate/ungate** — `load_book` sets `_play_gated = True` before resolving. If resolve finishes while gated, the result is held in `_held_play`; `ungate_play()` (called from `_on_library_hidden` after the library slide finishes) clears the gate and fires `instance.play()`. Lets panel animations finish before audio starts.
- **Property caching** — `time_pos`, `duration`, `pause`, `speed` cached via `observe_property` (`_cached_*`). `time_pos` getter adds `_file_offset` under VT; `duration` getter returns `_book_duration` under VT, else `_cached_duration`.
- **Async seeking** — `seek_async(pos)` issues `command_async('seek', pos, 'absolute+exact')` for in-file seeks, triggers a VT file switch for cross-file seeks, or routes to `_mp3_stop_and_load` for long MP3 seeks. Used by all UI-driven seeks (slider, chapter, right-click, undo, VT cross-file, chapter nav) **and** smart rewind. Skip buttons and position restore stay on the sync `time_pos =` path.
- **MP3 stop-and-load** — for VBR single `.mp3`: `seek_async` intercepts displacements > `_MP3_SEEK_THRESHOLD` (60s) and calls `_mp3_stop_and_load`, which pauses and issues `loadfile … start=X` (positions via Xing/TOC header, not stream-scan). VT same-file variant additionally gates on file size > `_VT_MP3_SIZE_THRESHOLD` (40 MB) and `2.0 < local_pos < duration − 5.0`. State vars (all reset in `load_book`): `_play_target`, `_mp3_seek_reload_pending` (guards the `_on_file_loaded` early-return + blocks concurrent reloads), `_mp3_seek_was_playing`, `_mp3_seek_visual_lock` (suppresses play/pause icon flicker). `book_ready` is NOT re-emitted during reload. VT same-file sets `_cached_time_pos = local_pos` (not global), else the `time_pos` getter double-counts `_file_offset`. Both `seek_async` call sites include `and not self._mp3_seek_reload_pending`.
- **Chapter navigation** — `previous_chapter` / `next_chapter` / `seek_within_chapter` all do a position-based forward walk over `chapter_list` and `seek_async(nominal + _chapter_seek_offset())`; never `self.chapter = idx`. Chapter-LIST clicks (all book types, embedded M4B included as of 2026-06-13) route through `Player.activate_chapter_index(idx)` → `seek_async` — no native-nav exception anymore. `previous_chapter` threshold is `2.0 × speed`s past chapter start (within → previous chapter; outside → restart current). `next_chapter` is a no-op at EOF.
- **Chapter-seek constants (three, split Session 3, 2026-06-13)** — the old single `_CHAPTER_BOUNDARY_EPSILON = 0.35` was overloaded as both a position→index walk tolerance AND a seek-target epsilon, which clipped the first word of embedded-M4B chapters (~0.44s skipped). Measured across 5 M4Bs / 67 seeks: mpv's exact seek *overshoots* the nominal boundary by ~0.09s while **playing**, and *undershoots* by ~0.37s while **paused**. The three constants:
  - **`_CHAPTER_WALK_TOLERANCE = 0.5`** — tolerance for every position→chapter-index walk (`time <= pos + X`) in `player.py` and `app.py` (`_sync_chapter_ui`, label paths). Must exceed the ~0.37s paused undershoot or paused Next/Prev resolves the chapter just left and the slider sticks; 0.5 is still far under the ~2s minimum real chapter spacing. **This is the value used in all walks now — NOT `_CHAPTER_BOUNDARY_EPSILON`.**
  - **`_EMBEDDED_CHAPTER_SEEK_OFFSET = -0.09`** — seek-target offset for embedded-M4B chapter nav (via `_chapter_seek_offset()`); cancels mpv's natural +0.09 overshoot so the first word plays.
  - **`_PAUSED_SEEK_UNDERSHOOT_COMP = 0.37`** — forward correction added to the mpv seek command (only) when paused, embedded only, in `seek_async`. Compensates the paused undershoot so undo/notch/nav land on target. Applied to the command; `_seek_target`/`_cached_time_pos` keep the logical position. Guarded against the near-EOF deadzone.
  - **`_CHAPTER_BOUNDARY_EPSILON = 0.35`** — now ONLY the legacy seek-target epsilon for **VT/CUE** chapter-boundary seeks (kept to preserve their landing). Do NOT reuse it for walks (use `_CHAPTER_WALK_TOLERANCE`) or embedded seeks (use `_EMBEDDED_CHAPTER_SEEK_OFFSET`). A `seek_async` target floor of `0.05` prevents the negative embedded offset from producing a negative absolute seek (which mpv lands at EOF).
- **`chapter_changed` driving** — `_on_time_pos_change` is the universal driver for all book types (VT walks `_chapter_list` against global pos; CUE walks `_chapter_list`; embedded M4B walks `_chapter_list` — the cached snapshot, not `instance.chapter_list` live), emitting only when the index changes. `_on_chapter_change` (the mpv `chapter` observer) is fully suppressed (always returns). `seek_async` also emits `chapter_changed` synchronously for CUE mode as an optimistic paused-case update. On seek settle (`abs(global_pos − _seek_target) < 1.0`) both `_last_*_chapter` reset to −1 to force one clean emit.
- **Smart rewind on resume** — `apply_smart_rewind(last_pause_ts, wait_min, rewind_sec)` only fires if away ≥ `wait_min` minutes; rewinds `rewind_sec × speed`, clamped to current chapter start; via `seek_async`. Config `smart_rewind_wait` / `smart_rewind_duration` (0 = disabled).
- **Undo (one level)** — `save_seek_position(old_pos, duration_limit)` stores `_undo_pos` if unset or if more than `duration_limit`s since last undo click. `undo_seek()` seeks back via `seek_async` and clears `_undo_pos`. `duration_limit == 0` disables (config `undo_duration`, default 3s).
- **EOF / keep_open** — mpv runs `keep_open='always'`, so nothing auto-advances/closes. `_on_end_file(reason 0)` and a secondary `_on_pause_test` check (pause True and `pos ≥ dur − 1.5`) both call `_advance_or_finish()`: VT advances to the next file (sets `_eof` on the last), non-VT sets `_eof` immediately.
- **Seek guards** — near-EOF: `seek_async` returns early if `dur − pos < 2.0` (single-file) / `target_file['duration'] − local_pos < 2.0` (VT same-file); stop-and-load keeps its own 5s buffer. mpv hangs silently when seeked within ~2s of EOF.
- **Per-book speed / volume** — speed keyed `speed_{path}` in QSettings (None → `default_speed`). Volume is log-scaled: `_base_volume × _fade_ratio` (the fade ratio is the sleep-timer multiplier 0.0–1.0).
- **Signals** — `book_ready` (non-VT: from `_on_file_loaded`; VT: from `ungate_play` / `_on_playlist_resolved`, before `instance.play`), `file_switched` (VT cross-file), `chapter_changed(int)`, `load_failed(str)`. `file_loaded` is declared but driven by mpv's event, not re-emitted here.

### App shell (`app.py`, `MainWindow`)

`MainWindow` is a `QWidget` (not `QMainWindow`), frameless, fixed 300×564.

- **Three UI states**, reconciled by `LibraryController.apply_current_state()` (called at startup, on book select/remove, on library-status change):
  - **Empty library** — scan prompt + rotating literary quote (`book_quotes`, 60s `quote_timer`); player chrome and Library button hidden; bg image suppressed; carousel may show DB covers.
  - **No book selected (books exist)** — transport/sliders hidden via `_set_interface_visible(False)`; `no_book_section` ("go to library") shown; bg suppressed; carousel shown.
  - **Has book** — full chrome via `_set_interface_visible(True)`; bg restored; carousel hidden; `_load_cover_art` runs.
- **Carousel** — `CoverCarousel` built lazily in `_show_carousel()` (guards: not already shown, no current file, `no_book_section` visible). Slides in (220 ms OutCubic), stacked under `visual_area`. Paused/resumed around theme fades via `_on_fade_state_changed`. `_hide_carousel` tears it down; it never touches bg suppression (owned by the state machine).
- **`_set_bg_suppressed`** — sets `_bg_suppressed` (read by `ThemeManager._apply_stylesheets`), toggles `visual_area.setAutoFillBackground`, and regenerates `content_container`'s stylesheet with `get_player_stylesheet(theme, suppress_bg_image=…)` (uses `_active_display_theme` when a cover theme is live, to avoid a pool-color flash). Re-asserts transparent chapter-slider colors when `_chapter_ui_active` is False.
- **Right-click suppression after folder dialog** — `_get_new_folder_path` restarts `_dialog_close_time` (`QElapsedTimer`); `_on_drag_area_pressed` ignores right-clicks within 500 ms of the dialog closing. Drag-area right-click is also only forwarded when `db.get_book_count() > 0`.
- **Drag-area press** — `visual_area.mousePressEvent` is monkey-patched to `_on_drag_area_pressed`: left-click closes open panels, else toggles play/pause; empty library short-circuits. (No window-move logic lives here.)
- **Cover scaling** — `_update_cover_art_scaling()` implements four fit modes (`fit` KeepAspectRatio / `stretch` IgnoreAspectRatio / `crop` center-crop / `top` top-aligned on black canvas), all sized to `COVER_AREA_HEIGHT` (module constant), not the live label height. No-cover books render a themed `fabulor.svg` placeholder. Cover-theme application defers while a panel is open (`_pending_cover_pixmap` → `_apply_pending_cover_theme`).
- **200 ms `ui_timer` (`_update_ui_sync`)** — the heartbeat. Reads time/dur/pause/speed/eof; feeds `session_recorder.update_furthest_position`; on EOF synthesizes `pos = dur`, sets the restart icon, writes one `'finished'` event, shows the revert/close banner, and closes the session. Delegates to `_sync_playback_state`, `_sync_ui_render`, `_sync_progress_sliders` (skips setValue during flow anim / seeking / `flow_pending_progress`), `_sync_chapter_ui` (derives chapter from `pos`, skips during reload / no chapters / `flow_pending_chapter` / seeking), `_sync_persistence` (saves position every 0.1%, skips during drag / deadzone). Stopped during the flow animation; resumed via `_resume_ui_timer`.
- **Keyboard** — `C` opens the chapter dropdown; `T` rotates theme (2s cooldown, pends if mid-cooldown); `Q` rotates the no-book quote (testing-only).
- **Wheel zones** — over `visual_area`: volume ±5 (2s overlay); over `speed_button`: speed ±`speed_increment`, clamped 0.25–8.0; over `chapter_progress_slider`: seek by `max(10, chap_dur × 0.05)` with undo capture.
- **Module-level interface classes** — thin one-way facades so controllers don't hold a raw `MainWindow`: `UIInterface` + `AppInterface` + `BrowserInterface` (→ `LibraryController`); `VisualsInterface` + `PanelInterface` + `UICallbackInterface` + `LibraryInterface` + `PlayerInterface` (→ `SettingsController`).
- **Startup** (`__init__`) — build core objects → seed streak-grid cache → `_setup_ui` → wire timers/signals → instantiate `LibraryController` → restore last book (validated against active locations + `os.path.exists`) → `_check_library_status` → `ui_timer.start(200)` → instantiate `SettingsController` → `show()` → defer `start_idle_preload` by 4 s.
- **Teardown** — `_on_book_removed` zeroes labels/sliders, stops animations, deactivates chapter UI, clears cover; `closeEvent` saves volume + last book/position, terminates the player, stops/joins the scanner, closes the recorder.

### UI — Player view

- Cover art (four fit modes, above). Themed SVG placeholder for no-cover books.
- **Chapter list overlay** (`chapter_list.py`, `ChapterList`) — `QListWidget` child positioned absolutely; fade in 450 ms / out 300 ms (opacity → 0.94); `ROW_HEIGHT 24`, default `VISIBLE_ROWS 5`. Expand/collapse (button shown only when count > visible; Left/Right arrows toggle). Keyboard: Up/Down nav, Enter activate (no force-play), Space activate (force-play), Esc/`C` close. Digit jump: buffer + 800 ms debounce; `by_index` (1-based) or `by_name` (word-boundary regex); autoplay configurable. Activation uses `seek_async(+epsilon)` for VT/CUE, native `chapter = idx` for embedded M4B.
- Progress slider with chapter notch markers + notch reveal animation; separate chapter-progress slider; flow animation on book switch (both sliders animate between positions); UI-timer guards skip setValue during animation.
- `self._switch.in_deadzone` (`book_switch.py`) prevents stale position display during the library slide-out.
- Scrolling title/author labels (`ScrollingLabel`). Speed-controls panel, sleep-timer panel, sidebar (stats/settings/cover/detail access).

### Book Detail Panel (`book_detail_panel.py`)

`QTabWidget` (`stats_tabs`) with four tabs + a header:

- **Header** — four inline-editable `_ElidingLineEdit` fields (title/author/narrator/year, read-only at rest, click to edit; year has a `-?\d*` validator; narrator+year always shown in edit mode). Escape / click-outside cancels via the app event filter. 80px-wide / 120px-max header cover (`_render_logo_placeholder` fallback, grayscale for archived books). `_finished_label` (always visible) toggles manual finish/unfinish with a 7s confirm. `_remove_btn` excludes the book (7s confirm); archived books show `_ghost_label` instead.
- **Metadata locks** — `_locks` dict (title/author/narrator/year). The unified `_meta_action_btn` (24×24) is driven by `_MetaActionState`: `HIDDEN` / `DIRTY` (save icon → save + lock changed fields) / `LOCKED` (lock icon → clear all locks) / `UNLOCKED` (lock-open, auto-reverts after 2500 ms).
- **Stats tab** — furthest-position `_RangeBar` + %; a grid of Remaining (speed-aware) / Total listened / Sessions / Last session / Started / Finished; a non-scrolling `_RecentHistoryWidget` (up to 4 recent sessions).
- **History tab** — full scrollable `_HistoryRow` list; per-row hover-reveal trash → slide-in "Delete this session?" confirm; "Delete listening history" with a 7s confirm; emits `history_deleted`.
- **Tags tab** — `FlowLayout` chip container + input with a debounced (200 ms) case-insensitive `QCompleter`; per-book limit 5 (input hidden at 5); a tag display strip above the tabs (clickable colored dots → `tag_filter_requested` in library context).
- **Cover tab** — embeds a `CoverPanel`.
- **Duration label** (`_ClickableLabel`) — wall-clock by default; click toggles to speed-adjusted ("Xh Ym at N.Nx"); cursor/toggle disabled at 1.0×.
- Signals: `close_requested`, `history_deleted`, `metadata_saved`, `tags_changed`, `active_cover_changed(book_path, cover_path)`, `book_removed`, `tag_filter_requested(str)`, `open_tag_manager_requested`.

### Cover Panel (`cover_panel.py`)

- Up to 4 user covers (slots 1–4) + 1 locked scanner cover (slot 0). Add via `QFileDialog` (`.jpg/.jpeg/.png`, validated ≤ 5 MB), saved as JPEG; first user cover auto-activates. Locked covers can't be deleted; `_add_btn` hidden at 4 user covers.
- `CoverThumbnail` 72×72 with a 17px bottom hover overlay (× delete / ✓ set-active, both suppressed when not applicable; overlay fully suppressed when the sole cover is locked); 2px accent border on the active cover.
- Preview `QLabel` fixed **208×266**, four fit modes (`fit` letterbox / `stretch` / `top` top-anchored crop / `crop` center-crop), persisted per cover via `db.set_fit_mode`. Fit buttons (exclusive `QButtonGroup`) hidden until a cover is selected.
- `_left_col` height = `n × 72 + max(n−1, 0) × 6`. Active-cover change persists via `db.set_active_cover` and emits `active_cover_changed(file_path)` (`""` when none remain).

### Library Panel (`library.py`)

- `BookModel(QAbstractListModel)` + `BookDelegate(QStyledItemDelegate)` + `LibraryPanel`. Shared module-level `_cover_cache` keyed by `book.id` (int).
- **Five view modes** (`VIEW_MODES`): 1-per-row, 2-per-row, 3-per-row, Square, List. Display names are randomized literary puns (reshuffle on `hideEvent`). List mode draws an animated left-edge stripe (`_pulse_timer` 40 ms) on the playing book and supports hover-fade (Off/Slow/Normal/Fast); 1- and 2-per-row support hover text-scroll.
- **Sort** (`SORT_KEY_MAP`): Title, Author, Last Played, Progress, Duration, Year, Finished. "Progress"/"Finished" appear only when such books exist (`has_books_with_progress` / `has_finished_books`). Direction toggle (`↑`/`↓`) defaults per key via `_SORT_DIRECTION_DEFAULTS`, persisted to config.
- **Search/filter** — plain text (title/author/narrator/exact 4-digit year), `#tag` prefix (`get_paths_for_tag_prefix`; `#` alone = all), year filters `>NNNN` (≥) / `<NNNN` (≤) / ranges (both orderings). No-match: search field turns dark-red and the model falls back to the full list (never empty); incomplete year expressions never show red. Right-click clears the field; persistence is per-classification (`persist_filter_tag/year/text`).
- **Cover loading** — `_load_visible_covers` binary-searches visual rects (±5 row pad), dispatches `CoverLoaderWorker` (caps to 226×344). Idle preloader: `start_idle_preload` queues in sort order, `PRELOAD_BATCH_SIZE = 3` every `PRELOAD_INTERVAL_MS = 50` ms, starts 4s after launch, pauses on interaction. `_on_cover_loaded` skips the `dataChanged` emit while `_is_animating`.
- `BookDelegate._resolve_playback` returns `(pos, dur, dur_disp, pct, has_progress, speed)`; `has_progress` (gated on `progress > MIN_PROGRESS` = 1.0s) is what shows the elapsed/bar/percentage and applies per-book speed to the displayed duration. Clicking the time label toggles remaining/total. All delegate colors are injected `Property(QColor)` for theme animation.

### Stats Panel (`stats_panel.py`)

- **Tabs**: Overall, Timeline, Day, Week, Month, ⚙.
  - **Overall** — `BarChartWidget` (last 7 days; click a bar → Day tab at that date); stat grid (Listening time, Books started, Sessions, Longest/Last/Average session, Current/Longest streak); "Recently finished" `FinishedScrollRow` (≤ 20, hidden when empty).
  - **Timeline** — both `HourlyHeatmap` and `StreakGrid` built, one visible (default from `config.get_default_timeline_view()`); `TasselOverlay` toggles them with a conceal→reveal transition.
  - **Day / Week / Month** — ‹/› nav (right-click jumps to oldest/newest), wheel-scroll header (Day optionally accelerated), `BookDayRow` list (rows < 60s excluded), total label, "Finished" `FinishedScrollRow`.
  - **⚙** — day-start hour `QSpinBox` (0–23, rebuilds streak cache), period scroll-acceleration toggle, default-timeline-view toggle, "Reset all stats" (7s confirm).
- **`HourlyHeatmap`** — 14-day × 24-hour grid (CELL 14, GAP 1), today leftmost; cell alpha `40 + intensity×215` (intensity = `min(1, sec/3600)`); hover highlights + per-hour tooltip (date, total, per-book table). Mexico-wave reveal (1000 ms) / conceal (600 ms) + cascading column labels.
- **`StreakGrid`** — 26×14 = 364-day calendar, today top-left, backed by `streak_grid_cache`. Listened days filled accent; finished days get a small centered dot (`_finished` set, `streak_finished_dot` per-theme override); the longest consecutive run is highlighted with a **derived `_longest_fill` color** (hue/sat/value shift, `streak_longest_fill` override), computed in-widget by `_compute_longest_run` (most-recent run wins on tie). Left gutter shows the current-streak icon + count (dimmed when today not yet listened). Same wave animation as the heatmap.
- **`TasselOverlay`** — sliver tab pinned top-left (~7px peek), slides down → holds 1200 ms → switches view → retreats; clock icon ↔ calendar icon. `_switch_timeline_view` uses a 2-counter seam so the visibility flip waits for both conceal and label-out.
- **Widgets**: `BookDayRow` (48×48 cover, elided title/author, `pct_start · pct_end | +delta`; archived dimmed, finished/deleted styled), `FinishedBookThumb` (47×47 crop), `SessionListWidget` (scrollable session rows: timestamp / delta% / `_RangeBar` / end%), `_RangeBar` (flat start→end fill bar with animatable colors; also used by the detail panel).
- **Data flow** — period caches (`_cached_active_days/weeks/months`) invalidated on tab change / `refresh_all`. `_inject_active_covers(rows)` adds `active_cover_path` from `book_covers` (must run at every `BookDayRow`/`FinishedBookThumb` site). `on_cover_changed(book_path, cover_path)` does a targeted refresh of the visible tab only (`_iter_day_rows` / `_iter_finished_thumbs` → `refresh_cover`); empty cover restores the placeholder without a worker.

### Tag Manager (`tag_manager.py`, `TagManagerWidget`)

- Two alternating child widgets (not a `QStackedWidget`): **list view** (tag rows: colored dot, name ≤ 20 chars, book-count badge) and **tag panel** (back, name edit, reserved 21px row, book grid).
- **Rename** — typing flips the single `_action_btn` to save mode; Enter/click → `db.rename_tag`; success shows a check for 2000 ms; name-taken shows a red save icon (`save_error`); Escape/click-outside reverts.
- **Delete** — trash → reserved row shows a "Click to delete the tag" confirm (7s), grid locked; confirm → `db.delete_tag`.
- **Color** — clicking the dot shows a 9-swatch + neutral picker (`db.set_tag_color`); mutually exclusive with delete-confirm.
- **Remove book from tag** — left-click a `_TagBookThumb` → `db.remove_book_tag` (deletes the tag if it was the last book); right-click → `detail_requested`.
- `TAG_COLORS`: 9 named (coral/peach/lemon/lime/mint/sky/lavender/rose/white) + neutral. `MAX_TAG_LENGTH = 20`. Per-book limit 5, global 50 unique (enforced in `db.add_book_tag`). `_TagBookGrid` 5 columns; `set_locked` routes clicks through the parent. Completer popup styled by `_style_completer_popup` on each keystroke + theme change.

### Theme System (`theme_manager.py`)

- 50+ named themes (`themes.py`); per-component stylesheets — never `main_window.setStyleSheet()` globally. `_apply_stylesheets(theme_name, hover)` dispatches to: base/main window, title bar, `content_container` (`get_player_stylesheet`, `suppress_bg_image` flag), library (skipped during hover), chapter list (skipped during hover), settings/speed/sleep panels, stats + book-detail panels, sidebar; then `_reload_button_icons` + `_set_chapter_ui_active`.
- **Hover preview + snapback** — hover applies at half the fade duration; un-hover snaps back to the cover theme (if active) or current theme at `_SNAPBACK_FADE_MS = 200`.
- **Overlay fade** — `_fade_overlay` `QLabel` + `_fade_anim` (opacity 1→0, `_THEME_SWITCH_FADE_MS = 750`). When the Themes tab is inactive, sliders are punched out of the overlay mask and their `bg_color`/`fill_color`/`notch_color` animate separately; time/chapter labels are frozen (`FreezableLabel`) before the grab to prevent ghosting. `snap_theme_forward()` (panel open) and `abort_theme_fade()` (panel close) short-circuit the fade.
- **Rotation** — `rotation_timer` every `interval` minutes; `_rotate_theme` skips in `exclusive` cover mode and defers (`_pending_rotation`) while a panel is open (`_fire_pending_rotation` retries 3s after close). Selection excludes the current theme + recent (`deque(maxlen=10)`), relaxes below `_MIN_POOL = 4`, then inverse-distance-weights by perceptual distance (`_EXCLUSION_THRESHOLD = 0.5`). Automatic changes snap instantly when the Themes tab is active. `_PANEL_ANIM_GUARD_MS = 700`.
- **Cover-art dynamic theme** — `apply_cover_theme(pixmap)` (modes `off` / `with_pool` / `exclusive`); `clear_cover_theme` reverts. `_cover_pool_btn`: left-click toggles off↔with_pool, right-click activates immediately.

### Panels (`panels.py`, `PanelManager`)

- Manages sidebar, library, settings, speed, sleep, stats, tags, book-detail, and chapter-list visibility. All slide via `QPropertyAnimation` on position; re-entry guarded.
- Library slides full-width from the left (sets `_is_animating` to suppress cover emits; `refresh()` on shown). Settings/speed/sleep/stats/tags slide from the left at 90% width, fixed 500px height. **Book detail uniquely enters from the right.** Optional blur animation (`blur_effect.blurRadius` 0↔10) per `config.get_blur_enabled`.
- Sidebar uses a queued-open pattern (closes first, then dispatches the panel). `_on_library_hidden` ends the deadzone (`mw._switch.library_revealed`), calls `ungate_play`, then drains deferred file-ready events or applies the pending cover theme.

### Controls & widgets (`controls.py`, `audio_controls.py`, `carousel.py`, `icon_utils.py`, `text_context_menu.py`)

- **`ClickSlider`** — animatable `bg_color`/`fill_color`/`notch_color`/`notch_opacity`/`animatedValue` properties; `animate_to` (200–600 ms distance-scaled); `when_animations_done` chains flow then reveal; chapter-notch reveal animation (`revealedCount`, mirrored to seek direction, alternating tick halves); optional center mark + snap-to-center; right-click emits a ratio and snaps to markers.
- **`FreezableLabel`** — `setText` is a no-op while frozen (pins labels during theme fades). **`ScrollingLabel`** (extends it) — horizontal marquee with Slow/Normal/Off modes, animatable `text_color`, `clicked`. **`HoverButton`** — `hovered`/`unhovered`/`rightClicked`. **`ShimmerButton`** — `play_shimmer()` runs an 800 ms diagonal glint.
- **`AudioSettingsTab`** — normalisation, voice boost, stereo/mono, channel swap, L/R balance slider (−100..100, snap-to-center). Each change calls `player.apply_audio_processing(...)`; a reset button appears only when something is non-default.
- **`CoverCarousel`** — decorative scrolling strip, fixed 300px wide; static when ≤ 3 covers, else gapless looping scroll (`_TICK_MS = 33`, time-delta based); staggered reveal (first at 375 ms, then every 75 ms) with a fade-in; 1px top/bottom stripe lines; `set_stripe_color` / `stop` / `start`.
- **`icon_utils`** — `render_logo_placeholder` (themed `fabulor.svg`), `render_logo_placeholder_bordered`, `load_themed_icon` (LRU 64; swaps `#000000` fills/strokes — for black-paint icons), `load_currentcolor_icon` (LRU 64; regex-replaces all non-`none` fills/strokes — for `currentColor` SVGs like clock/calendar).
- **`ContextIconMenu`** — single shared frameless popup with Cut/Copy/Paste/Delete (each enabled by selection/clipboard/read-only state), themed, clamped within the window.

### Settings Panel

- Themes tab, Controls tab (chapter digit mode by_name/by_index, autoplay/jump-only toggle), Audio tab, Library tab (naming pattern, folder management, chapter source Embedded/.cue). Bound dynamically via `SettingsController` through the five interface facades.

### Library state machine, scan & covers (`library_controller.py`, `library/`)

- **`compute_library_state`** → `{mode, has_book, has_locations, has_indexed_books}`. `mode` is `empty` (no locations OR no visible indexed books), `scanning` (locations + indexed + scanner running), or `ready`. `has_book` derives from `app.get_current_file()`; `has_indexed_books` from `get_visible_book_count()`.
- **`apply_library_state`** branches: **empty** (hide chrome/Library button/carousel, suppress bg, rotate quote, set prompt by sub-state: no-locations / scanning / no-books); **no-book** (show Library button, hide prompts, show metadata "go to library", suppress bg, show reshuffled carousel); **has-book** (show Library button, hide carousel, restore bg, delegate metadata visibility to `_load_cover_art`).
- **`apply_current_state`** is the sole compute+apply entry point (no scan side effects). **`_check_library_status(manual, force_refresh)`** = `apply_current_state` + `handle_background_tasks` (starts a scan when manual, force, or no indexed books, and not already scanning).
- **Location flows** — add (`_on_scan_now_clicked`): abspath-normalize, dedupe against sub/parent existing locations, `add_scan_location`, then **synchronous** `restore_books_under_path` (un-soft-deletes `is_deleted=1, is_excluded=0` books under the path), refresh, `_check_library_status(manual=True)`. Remove: `remove_scan_location` (soft-delete), unload the current book if it was under a removed folder, refresh. Excluded books stay hidden through both.
- **Scanner** (`scanner.py`) — `LibraryScanner` owns a `QThread`; `ScannerWorker` does the work, cancellable via a `threading.Event`. Phase 1 discovers one-level-deep book folders (any audio extension). Phase 2 builds `known_paths` from `get_all_book_paths()` (ALL rows regardless of flags) — on a non-force scan, known (incl. excluded/deleted) paths are skipped and NOT resurrected; a force scan re-extracts everything and `upsert_books_batch` resets both flags. Extracts cover (external image file → embedded tag), narrator/title/author/year (tag priority chains → folder-name fallback), `book_files` (multi-file only), summed duration; generates a 226×344 JPEG thumbnail under the cache dir and upserts a locked scanner cover (slot 0) if none exists.
- **Cover manager** (`cover_manager.py`) — `get_covers_dir` (user data dir), `save_cover_image`, `delete_cover_file`, `validate_cover_file` (size-only ≤ 5 MB).

### Database (`db.py`)

- SQLite, WAL per connection, `sqlite3.Row` factory, auto-commit/rollback context manager.
- **Tables**: `scan_locations`; `books` (+ `progress`, `year`, `started_at`/`finished_at`, `chapter_source`, soft-delete `is_deleted`/`is_excluded`, four `*_locked` flags); `listening_sessions` (+ `book_id` FK, `furthest_position`); `book_events` (+ `book_id`, `event_type`, `source`); `book_tags` (`book_id`); `tags` (name PK, color); `book_covers` (locked/active/fit_mode/sort_order); `book_files` (sort_order, duration_ms, cumulative_start_ms, title); `streak_grid_cache` (date PK, listened) — a 364-row rolling window.
- **Soft-delete flags** — `is_deleted` set by `remove_scan_location`, cleared by `restore_books_under_path` (only when `is_excluded=0`) or any upsert; `is_excluded` set by `set_book_excluded`, untouched by removal/restore, cleared only by a force-rescan upsert. "Visible" = both 0. `get_book_count()` (all rows, for stats) vs `get_visible_book_count()` (library); `get_all_book_paths()` is unfenced (drives the scanner's `known_paths`).
- **Upserts** — `upsert_book` / `upsert_books_batch` share identical SQL (execute vs executemany). ON CONFLICT guards: title/author updated only if not `*_locked`; narrator/year additionally NULLIF-guarded against empty/null; `progress` via `COALESCE(NULLIF(excluded.progress, 0.0), books.progress)`; `is_deleted`/`is_excluded` always reset to 0. The two must stay in lockstep.
- **Sessions/events** — `write_session` dual-writes `book_path` + `book_id` and updates the streak grid for the start and end dates; `write_book_event` writes events (only `source='playback'` finished events light a grid cell). `unfinish_book` / `clear_finished` / `delete_session` / `delete_book_stats` all re-evaluate the affected grid cells. `set_started_at` only writes when NULL.
- **Stats queries** — `get_book_stats`, `get_overall_stats`, `get_last_n_days` (zero-fills gaps in Python), `get_active_periods`, `get_listening_time_per_period`, `get_books_listened_in_period`, `get_daily_book_breakdown`, `get_finished_in_period`, `get_recently_finished`, `get_streaks`, `get_hourly_heatmap` (splits sessions across clock-hour boundaries in Python, caps 3600s/hour, wall-clock with no day-start offset). Stats queries are intentionally unfenced by the soft-delete flags and use `COALESCE(b.title, ls.book_title)` over LEFT JOINs so deleted books keep their title. Per-book period positions use correlated subqueries (and `has_finished_books` uses `EXISTS`) to avoid cartesian fan-out.
- **Streak grid** — `build_streak_grid_cache` seeds 364 dates at 0 then flips any date with a qualifying session (start OR end) or `source='playback'` finished event to 1; `_update_streak_grid_cache_for_date` does incremental updates; all date attribution uses a SQL `day_start_hour` offset (passed in, never read from config). **Invariant: a finished day is always a listened day** — a playback-finish lights its cell even with no session; manual (`source='manual'`) finishes never touch the grid (visible in Finished tab/detail only).
- **Tags** — `add_book_tag` (lowercased, ≤ 20 chars; per-book 5, global 50 limits), `remove_book_tag`, `get_all_tags` (LEFT JOIN color), `get_books_by_tag`, `get_paths_for_tag_prefix`, `rename_tag`, `delete_tag`, `set_tag_color`, `get_tag_suggestions`. **Covers** — `get_active_cover[_path]`, `get_covers_for_book`, `upsert_cover`, `set_active_cover` (maintains the single-active invariant manually), `set_fit_mode`, `delete_cover`.

### Session Recording (`session_recorder.py`)

`SessionRecorder(QObject)` owns all session state/persistence; `MainWindow` holds one and delegates. `_current_book` stays on `MainWindow` (passed via `get_book_fn`); day-start hour via `get_day_start_hour_fn`.

- **Lifecycle**: `open()` (start, seed furthest position, start checkpoint timer), `resume()` (after a short pause), `pause()` (accumulate the segment, start the 3-min `_pause_timer`), `close()` (accumulate, flush to DB if `listened ≥ 60`, reset). `is_active` property.
- **Thresholds**: 60s wall-clock minimum (else discarded), 3-min pause timeout (auto-close), 15s **seek credit** — a forward seek past the furthest sets `_post_seek_pending_position` and starts `_seek_credit_timer`; staying 15s promotes it (a backward seek cancels). `notify_seek(new_pos)` from slider-released handlers feeds this; `update_furthest_position(pos)` from the 200 ms loop advances the furthest only when no seek credit is pending.
- **Persistence**: `write_session` dual-writes `book_id` + `book_path` + title/author/duration + start/end/positions + `furthest_position` + `listened_seconds` + `day_start_hour`; sets `started_at` if unset; runs on a daemon thread and emits **`session_written`** (lives on the recorder, not `MainWindow`). A `session_checkpoint.json` is written every 30s and recovered on startup (writes a session if ≥ 60s, without emitting `session_written`).

### Config (`config.py`)

`QSettings("Fabulor", "Fabulor")`; `_safe_int`/`_safe_float` guard list-typed returns.

- **Playback**: `volume` (100), `skip_duration` (10s), `long_skip_duration` (1 min), `smart_rewind_wait`/`smart_rewind_duration` (0 = off), `speed_increment` (0.1), `default_speed` (1.0), `speed_{path}` (per-book, None), `pos_{path}` (0.0), `last_book` (""), `sleep_duration` (30 min), `sleep_mode` ("timed" | "end_of_chapter"), `sleep_fade_duration` (0s), `undo_duration` (3s), `chapter_list_source` ("embedded" | "cue").
- **Audio**: `voice_boost_enabled`, `norm_enabled`, `mono_enabled`, `channels_swapped`, `balance` (0.0).
- **Library**: `naming_pattern` ("Author - Title"), `library_sort_key`/`library_sort_ascending`/`library_view_mode`, `persist_filter_enabled`/`persist_filter_tag`/`persist_filter_text`/`persist_filter_year`.
- **UI/Theme**: `theme`, `blur_enabled`, `theme_fade_duration` (750 ms), `theme_rotation_interval` (0 = off), `cover_art_theme_mode` ("off"|"with_pool"|"exclusive"), `show_remaining_time` (true), `scroll_mode`, `hover_fade_mode`, `chapter_hints_mode`, `chapter_notches_enabled`, `chapter_notch_animation_enabled`, `chapter_digit_mode` ("by_name"), `chapter_digit_autoplay`.
- **Stats/Timeline**: `day_start_hour` (0), `default_timeline_view` ("heatmap"|"streak"), `streak_grid_cache_date`, `stats_accel_scroll`.

### Assets & quotes

- `assets.py` — `get_asset_path(relative)` resolves into the bundled `assets/` dir; `ICON_PATH` for the app icon.
- `book_quotes.py` — `BOOK_QUOTES`: 32 `(text, title, text_size, title_size, color, text_align)` literary quotes; `LibraryController._rotate_quote` picks one and renders it as HTML in the empty state.

---

## Critical Architecture Rules

### DO NOT use `self.player.chapter` for chapter display
Always derive chapter by walking `self.player.chapter_list`, finding last entry where `time <= pos + _CHAPTER_WALK_TOLERANCE` (0.5 as of Session 3, 2026-06-13 — was 0.35). mpv updates chapter property asynchronously.

### DO NOT use `self.chapter = idx` for chapter navigation
Always use `seek_async(nominal + _chapter_seek_offset())` with a position-based walk. No native-nav exception: embedded-M4B chapter-list clicks now route through `Player.activate_chapter_index(idx)` → `seek_async` (changed 2026-06-13 — native `self.chapter = idx` left the chapter UI frozen because it never set `_seek_target`). See the fuller rule above.

### DO NOT restore any emit in `_on_chapter_change` — it is fully suppressed
`_on_chapter_change` always returns immediately. `_on_time_pos_change` is the sole driver of `chapter_changed` for all book types. The old `_is_seeking` guard was insufficient — it cleared before `_on_chapter_change` fired, causing paused-state snap-back.

### DO NOT set `_virtual_timeline` for CUE books
CUE mode = `_chapter_list is not None` and `_virtual_timeline is None`. Setting `_virtual_timeline` activates VT file-switching on a single-file book.

### DO NOT simplify `Player.terminate()`
Must store instance, clear `self.instance`, call `terminate()`, then `wait_for_shutdown()`. Without `wait_for_shutdown()`, libmpv threads crash in `avformat_close_input`.

### DO NOT connect `_on_file_ready` to `file_loaded`
Must only connect to `book_ready`. `file_loaded` fires on every mpv file load including VT mid-book switches; causes quadruple-advance feedback loop.

### DO NOT read `progress_slider.value()` in `_on_file_ready` for animation
Slider value is stale. Always compute from `int((new_progress / self.player.duration) * 1000)`.

### DO NOT seek to a position within 2 seconds of a file's duration
mpv hangs silently when seeked within ~2s of EOF — no error, no event, no recovery. Every `command_async('seek', ...)` or `loadfile start=X` call must be preceded by a guard that returns early if `duration - pos < 2.0`. Guards currently live in `seek_async` (player.py): VT same-file branch checks `target_file['duration'] - local_pos < 2.0`; non-VT branch checks `self._cached_duration - pos < 2.0`. The stop-and-load path has its own 5s buffer. If any new seek path is added, the buffer must be present.

### DO NOT join `book_events` directly into a query that aggregates `listening_sessions`
The join produces a cartesian product (sessions × finished events per book) before GROUP BY, inflating `SUM(listened_seconds)` by the finished event count. Always use a correlated scalar subquery: `(SELECT MAX(CASE WHEN be.event_type = 'finished' THEN 1 ELSE 0 END) FROM book_events be WHERE be.book_id = b.id) as is_finished`. Applies to `get_daily_book_breakdown`, `get_books_listened_in_period`, and any future query with the same shape.

### DO NOT query `books.finished_at` for finished state — it is never written
`books.finished_at` exists in the schema but is only ever reset to NULL (`reset_stats`/`delete_book_stats`); nothing populates it. The authoritative source is `book_events` with `event_type = 'finished'`. All finished-book queries use it (`get_finished_book_data`, `get_recently_finished`, `get_streak_grid_finished_dates`). Querying `books.finished_at` returns silently empty.

### DO NOT keep `StreakGrid` from cross-checking its longest run against `get_streaks()['longest']`
`get_streaks(day_start_hour)` returns only counts (`current`/`longest`), not which days. `StreakGrid._compute_longest_run(cache)` derives the longest-run **date set** independently (ISO sort + consecutive scan; most-recent wins on tie via `>=`). The invariant `len(self._longest_dates) == streak_info['longest']` must hold — two independent paths over the same **listened-day set** (SQL `get_streaks` union vs. Python scan over `streak_grid_cache`). As of 2026-06-12 a "listened day" is `session OR 'finished' book_event` (finished ⟹ listened), so **both** paths must include finished adjusted-dates: `get_streaks` unions them into its day set; the cache write sites add them to `streak_grid_cache`. A divergence means the two drifted — an attribution change applied to some of the six finished⟹listened sites but not all (`build_streak_grid_cache`, `_update_streak_grid_cache_for_date`, `write_book_event`, `unfinish_book`, `delete_book_stats`, `get_streaks` — see NOTES.md "StreakGrid invariant: a 'finished' day is ALWAYS a listened day"). That mismatch is the diagnostic; do NOT clamp one to the other to hide it.

### DO NOT fold `animate_conceal` duration logic into `HourlyHeatmap.animate_reveal`
`animate_conceal` (on both `HourlyHeatmap` and `StreakGrid`) is **additive-only**: it reuses the `reveal_progress` property in reverse (1.0→0.0, 600ms) and is the streak↔heatmap transition's drain phase. `HourlyHeatmap.animate_reveal` and `paintEvent` stay byte-for-byte unchanged. `animate_conceal` restores the 1000ms reveal duration in its `finished` callback so the following construct wave runs full-length, and tracks its pending slot in `self._conceal_slot` (disconnect only when present — avoids `Failed to disconnect (None)`). The asymmetric duration restore is the whole point; do NOT share a `setDuration(600)` between the two methods. Relatedly: `StreakGrid.set_data` must NOT call `animate_reveal()` — the caller (`_switch_timeline_view` / `_on_tab_changed`) fires exactly one reveal on the visible grid, else the tab-change reveal double-fires and hitches.

### DO NOT use `load_themed_icon` for `currentColor` SVGs — use `load_currentcolor_icon`
clock.svg / calendar.svg use `fill="currentColor"`. `load_themed_icon` only swaps `fill="#000000"`; it happens to tint these anyway via its `<style>`-injection fallback, but that is incidental, not contractual. `load_currentcolor_icon` recolors `currentColor` explicitly via regex (mirrors `render_logo_placeholder`). Use it for these icons; do not "simplify" back to `load_themed_icon` on the theory they're equivalent.

### DO NOT remove animation-state guards in `_sync_progress_sliders` / `_sync_chapter_ui`
Both check whether animation is running before setValue. Removing causes jitter from 200ms timer fighting animation.

### DO NOT touch MPV init block
`_ensure_mpv()`, `load_book()` MPV block, `locale.setlocale(LC_NUMERIC, "C")`, all MPV constructor args. Hard-won Wayland/libcaca/libtinfo/Qt locale bug fix. Changing anything breaks the app.

### DO NOT restore `show_metadata=False` to `library_controller.apply_library_state`
Removed in 2026-05-11 — it was silently overriding cover display on every book switch. `_load_cover_art` owns `metadata_label` visibility.

### DO NOT use `active_cover_changed` on `BookDetailPanel` as a single-arg signal
It emits `(book_path, cover_path)` — both args required at all call sites. `CoverPanel.active_cover_changed` remains `Signal(str)`; the intermediate slot `_on_cover_panel_changed` in `BookDetailPanel` injects `self._book_path` and re-emits. Do not connect `CoverPanel.active_cover_changed` directly to `BookDetailPanel.active_cover_changed`.

### DO NOT pass raw DB rows directly to `BookDayRow` or `FinishedBookThumb`
Always call `StatsPanel._inject_active_covers()` on the row list first. Raw rows carry only `cover_path` (scanner thumbnail); `_inject_active_covers` adds `active_cover_path` from `book_covers`. Skipping it causes stats panel thumbnails to show scanner art instead of the user-selected cover.

### DO NOT remove the `has_progress` gate on speed application in `BookDelegate._resolve_playback`
Speed is only applied to `dur_disp` when `has_progress` is `True`. Books with no progress always show total duration at 1x regardless of per-book speed. Removing this gate causes incorrect duration display in the library view.

### DO NOT replicate `apply_library_state(compute_library_state())` at a call site
`apply_current_state()` on `LibraryController` is the sole entry point for reconciling library UI state without scan side effects. Any call site that needs compute-and-apply (but not a scan trigger) must call `self.library_controller.apply_current_state()` — never inline the two-liner. Inlining the compute+apply pair creates sync-drift risk identical to the `upsert_book` / `upsert_books_batch` invariant: the pairing can drift independently from `apply_current_state`'s implementation. `_check_library_status` delegates to `apply_current_state` internally and additionally calls `handle_background_tasks`; use it only when a scan trigger is appropriate.

### DO NOT suppress the theme `bg_image` by overriding `visual_area` — regenerate the stylesheet without it
The theme `bg_image` is painted by `content_container`'s `QWidget#visual_area { background-image: url(...) }` rule in `get_player_stylesheet`. It is stripped in the no-book and empty-library states (where it overlapped the prompts/carousel/quote). The ONLY working suppression is `get_player_stylesheet(theme_name, suppress_bg_image=True)`, which omits the image at generation time. Do NOT attempt to cancel it with a child override (`visual_area` instance stylesheet, a `background-image: none` rule, or a dynamic property like the removed `carouselActive`): Qt's QSS cascade treats `background-image: none` as "unspecified", so the ancestor `url()` wins on the child per-property and the image survives (verified — a child `background-color` override applied while the image layered on top). `MainWindow._set_bg_suppressed(suppressed)` is the sole authority: it sets `_bg_suppressed`, sets `setAutoFillBackground(not suppressed)`, and re-applies the regenerated stylesheet. `apply_library_state` drives it (`True` for empty + no-book, `False` for has_book) and `ThemeManager._apply_stylesheets` reads `_bg_suppressed` so a theme change in those states keeps the image stripped. `_show_carousel`/`_hide_carousel` must NOT touch background or `autoFillBackground` — suppression is owned by the state machine, not the carousel.

### DO NOT revert `_update_cover_art_scaling` to reading `cover_art_label.height()` for `target_h`
`_update_cover_art_scaling` uses `COVER_AREA_HEIGHT` (a module-level constant in `app.py`) as `target_h`, not `self.cover_art_label.height()`. The live allocated height is transient and state-dependent — it reflects whatever the layout engine allocated at the moment of the call, which can be wrong during any state transition (empty→book, no-cover→cover, panel open/close). The constant decouples scaling from layout state and prevents any cover aspect ratio or state transition from breaking the layout. `cover_art_label` is also pinned with `setFixedHeight(COVER_AREA_HEIGHT)` in `_build_cover_art`. If the window layout ever changes, re-calibrate `COVER_AREA_HEIGHT` empirically by testing covers of various aspect ratios and confirming no bottom clipping in fit mode.

---

## Pending / Known Debt

- `_cover_cache` has no eviction policy (unbounded LRU). Deferred.
- Theme transitions — long-term path is per-element `@Property(QColor)` animation, but Themes tab QSS complexity makes it non-trivial. `THEME_ANIM_TODO` comments mark instrumented widgets.
- `CoverLoaderWorker` anonymous type objects in stats_panel/tag_manager (path→ID migration context). Deferred to next cover refactor.
- Sleep timer state not persisted across restarts (`get_sleep_duration`/`get_sleep_mode` never read on startup). Product decision deferred.
- Screen drag 4K→1080p: cover scaling doesn't update without scroll (needs `QWindow.screenChanged`).
- MP3 natural sort (2 before 10) — out of scope for v1.
- Book detail panel background opacity — user wants it opaque eventually. Not in current scope.
- **Deleted/excluded book UI in stats panel** — stats panel shows sessions and history for excluded books (via `listening_sessions` join, which is unfenced by `is_excluded`). No visual differentiation currently. Duration label not clickable for books no longer in the library. Cover monochrome, metadata read-only, Cover+Tags tabs hidden — deferred to Session 7.
- **Session recording gaps (fully deferred):**
  - VT file switches — `session_recorder.close/open` wiring doesn't account for mid-book VT file transitions. `file_switched` is not threaded into the session recorder.
  - Sleep timer — sleep feature prevents session recording during the sleep window. Deferred.
- **`path_to_index()`** is in `library.py` (`LibraryPanel`, not `BookModel`).
- **`day_start_hour` date adjustment has no named helper** — `(datetime.now() - timedelta(hours=N)).date()` appears inline at `db.py:784`, `db.py:1031`, `app.py:320`, `stats_panel.py:2615`, `stats_panel.py:2628`. Five identical copies; drift risk if one site is touched and the others aren't. Candidate for extraction to a `_adjusted_today(day_start_hour)` helper when any of these sites next needs touching.
- **VT open issues (multi-file MP3) — fully deferred:**
  - Progress slider race on book switch — **traced** (review/Review_260612_6.md §7, NOTES.md): not a missing guard. The authoritative `_on_file_ready` set is protected by three composable guards (`slider_animating`, `is_seeking`, `_switch.flow_pending_progress`); the residual is a guard-release-ordering timing overlap that self-corrects on the next 200ms tick. Lever (if determinism wanted): hold the timer resume until both the flow animation finished AND the restore seek settled.
  - M4B chapter stuck intermittently — **traced** (review/Review_260612_6.md §6, NOTES.md): NOT a Fabulor state-leak. `load_book` resets all VT/chapter state before the M4B loads. The freeze may originate in mpv-native `chapter_list` readiness/timing for specific M4Bs at load time — but note that as of 2026-06-16, `_on_time_pos_change`'s embedded M4B branch now reads `_chapter_list` (the cached snapshot) rather than `self.instance.chapter_list` live, so the original "gated on `instance.chapter_list` being populated" rationale no longer fully applies. If this re-surfaces: check whether `cache_chapter_list()` returned an empty list for the affected file (unchaptered path), and whether the 150ms retry in `_on_file_loaded_populate_chapters` resolves it.
  - Rapid book switch (VT → any) regression: test that the newly selected book's progress slider shows the correct position and not 0%. Symptom of a double-handler invocation resetting progress; fixed via disconnect-before-connect in `load_book`, but should be part of regression runs.

---

## Files and Responsibilities

```
src/fabulor/
├── app.py                    # MainWindow wiring + module-level interface classes (VisualsInterface, PanelInterface, UICallbackInterface, LibraryInterface, PlayerInterface, BrowserInterface, UIInterface, AppInterface)
├── player.py                 # MPV wrapper, VT, async seek, gate/ungate
├── db.py                     # SQLite layer
├── config.py                 # QSettings wrapper
├── themes.py                 # Theme dicts + per-component QSS functions (get_player_stylesheet accepts suppress_bg_image)
├── library_controller.py     # Library logic, scan wiring, apply_library_state, _set_bg_suppressed
├── settings_controller.py    # Settings logic (dynamic binding)
├── session_recorder.py       # SessionRecorder — session open/pause/resume/close, checkpoint, furthest-pos tracking
├── book_switch.py            # BookSwitchState — single authority for the book-switch transition lifecycle (phase, deadzone, pre-switch captures, deferred flags)
├── book_quotes.py            # Quote pool for the empty/no-book state rotation
├── assets.py                 # get_asset_path helper (resolves paths into the assets/ bundle)
├── library/
│   ├── scanner.py            # Async file scan (threading.Event for cancel)
│   └── cover_manager.py      # Cover extraction and DB persistence helpers
├── models/
│   └── book.py               # Book dataclass
└── ui/
    ├── controls.py           # ClickSlider (animatedValue, when_animations_done), HoverButton, FreezableLabel
    ├── chapter_list.py       # Chapter list overlay (child widget, not popup)
    ├── library.py            # BookModel, BookDelegate, LibraryPanel (owns evict_cover/get_cached_cover — app.py must not access _cover_cache directly), _cover_cache
    ├── cover_loader.py       # CoverLoaderWorker: Signal(int, QImage)
    ├── cover_panel.py        # Cover management panel
    ├── cover_theme.py        # Dominant color extraction
    ├── theme_manager.py      # ThemeManager — overlay, snapback, rotation; reads _bg_suppressed on theme change
    ├── panels.py             # PanelManager — all panel open/close flows
    ├── book_detail_panel.py  # Book detail (stats, history, tags, cover header, inline edit)
    ├── stats_panel.py        # Stats panel, SessionListWidget, _RangeBar, HourlyHeatmap, StreakGrid, TasselOverlay
    ├── tag_manager.py        # TagManagerWidget — tag list, tag panel, book grid, color picker
    ├── title_bar.py          # Custom title bar
    ├── speed_controls.py     # Speed panel
    ├── sleep_timer.py        # Sleep timer panel
    ├── audio_controls.py     # Audio settings panel (normalisation, voice boost, balance, stereo/mono)
    ├── carousel.py           # CoverCarousel — ambient scrolling strip in no-book state
    ├── flow_layout.py        # FlowLayout (heightForWidth implemented)
    ├── icon_utils.py         # render_logo_placeholder, render_logo_placeholder_bordered — SVG logo placeholder renderers
    └── text_context_menu.py  # Right-click Cut/Copy/Paste/Delete context menu for metadata and tag fields
```

---

## Stylesheet Architecture

Each major component owns its stylesheet. Never call `main_window.setStyleSheet()` with a full-app stylesheet.

| Widget | Function |
|---|---|
| `main_window` | `get_base_stylesheet()` — bg, tooltips, chapter_dropdown, undo overlay |
| `title_bar` | `get_title_bar_stylesheet()` |
| `content_container` | `get_player_stylesheet()` — cover, sliders, playback buttons, metadata labels |
| `library_panel` | `get_library_stylesheet()` — skipped during hover |
| `settings_panel`, `speed_panel`, `sleep_panel` | `get_settings_stylesheet()` |
| `sidebar` | `get_sidebar_stylesheet()` |
| `stats_panel` | `get_stats_stylesheet()` |
| `tags_panel` (`TagManagerWidget`) | `get_tags_stylesheet()` |

### Wrapping a layout in a `QWidget` for naming purposes requires explicit `setSpacing`

When a `QHBoxLayout` is added directly to a parent layout via `addLayout`, it fills the full available width and inherits style-derived spacing. When the same layout is wrapped in a `QWidget` (for `setObjectName`, `setVisible`, etc.) and added via `addWidget`, two things change: (1) the widget shrinks to its children's fixed sizes unless given `setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)`, and (2) spacing is no longer guaranteed by style inheritance. Always call `setSpacing(N)` explicitly on any layout inside a named `QWidget` wrapper.

### `WA_StyledBackground` required for QSS on plain `QWidget` containers

Any `QWidget` subclass (not `QFrame`, not `QLabel`) that owns a background-color QSS rule **must** call `setAttribute(Qt.WA_StyledBackground, True)`. Without it Qt silently ignores the background rule — the widget appears either fully transparent or painted by the system palette. This applies to every panel root widget and any intermediate container that needs its own background. Child containers that should be transparent must NOT set `WA_StyledBackground` — set it only on the root. Verified on `TagManagerWidget` (2026-05-24).

---

*Last updated: 2026-06-13 (Session 3) — chapter-seek precision rework: split the overloaded `_CHAPTER_BOUNDARY_EPSILON` into three measured constants (`_CHAPTER_WALK_TOLERANCE` 0.5, `_EMBEDDED_CHAPTER_SEEK_OFFSET` −0.09, `_PAUSED_SEEK_UNDERSHOOT_COMP` 0.37); revised all chapter-nav rules; removed the embedded-M4B native-click exception (embedded chapter-list clicks now route through `Player.activate_chapter_index` → `seek_async`, fixing the chapter-UI freeze). Corrected the disproven "~0.25s short" rationale (mpv overshoots ~0.09s playing, undershoots ~0.37s paused).*

*Previously: 2026-06-13 — replaced the stale "Implemented Features (complete)" section with a full "What's Built" audit (5-agent factual sweep over app.py, player.py, session_recorder.py, config.py, db.py, scanner.py, cover_manager.py, library_controller.py, and all ui/ panels). Corrections vs. the old section: cover preview is 208×266 (not 205×270); StreakGrid longest-run uses a derived `_longest_fill` color with `streak_longest_fill`/`streak_finished_dot` per-theme overrides (not an `accent.lighter(150)` border / `streak_longest_border`); `write_session`/`write_book_event` still dual-write `book_path` + `book_id` (the old section claimed `book_path` was no longer written). Added previously-undocumented subsystems: app-shell UI states/wiring, carousel, controls/widgets, audio controls, icon utils, context menu, panels, full DB query inventory, scanner internals, cover manager, config key map, checkpoint recovery.*
