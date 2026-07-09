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

### The user sees the rendered pixels. You do not. When they say something is visually off, that is ground truth — your calculation is what's wrong.
On any visual/layout/pixel matter, the user's eyes are authoritative and your arithmetic is not.
When a live observation (a screenshot, a measurement like "W: 282", "it's 4px off", "move it right")
disagrees with your computed values, **the computation is the suspect, not the observation.** Do NOT
re-derive, re-measure with a script, or re-question the user to defend your numbers — offscreen
harnesses use default styles/sizes and silently diverge from the real rendered app (e.g. the
scrollbar is 8px via QSS, not the 14px Qt default; assumed widths are wrong). When the user says
"nudge it Npx" or "it ends here," just make that change and let them verify live. Asking them to
reconcile your math against what they can plainly see is not rigor — it wastes their time and
erodes trust. Take the visual correction at face value, apply it, move on. (Added 2026-07-06 after
exactly this failure: clinging to a wrong SCROLLBAR_EXTENT/window-width calculation and repeatedly
questioning the user instead of applying a simple 4px nudge they'd already measured and mocked up.)

---

### DO NOT modify, refactor, or touch any code related to MPV initialization under any circumstances. This includes the _ensure_mpv() method, the load_book() method's MPV init block, the locale.setlocale(locale.LC_NUMERIC, "C") call, and all MPV constructor arguments (vo, ao, vid, ytdl, keep_open, audio_client_name). This code resolves a hard-won, non-obvious bug involving libcaca, libtinfo, and Qt's locale reset on Wayland/openSUSE. Any "improvement," "cleanup," or "fix" to this block will break the app. If you think something in this block needs changing, say so explicitly and wait for confirmation before touching it.

`audio_client_name='fabulor'` (added 2026-06-26) sets mpv's `--audio-client-name`, which maps to the PulseAudio/PipeWire sink-input `application.name` property. Without it, mpv's `ao='pulse'` stream gets an unstable name (`mpv` or PID-derived), so `module-stream-restore` can't reliably remember a per-app volume across launches — symptom: openSUSE/PulseAudio resets the app's OS-level volume to some stale value (e.g. 5%) on every load, independent of the in-app volume which is correctly persisted. This does NOT fix an already-poisoned stream-restore entry — that must be cleared once via `pavucontrol` or the PipeWire/Pulse stream-restore DB; this just makes the restore key stable going forward.

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

### DO NOT move the checkpoint `unlink` back into `SessionRecorder.close()`'s daemon thread, and DO NOT make `closeEvent`'s `clear_checkpoint()` conditional
`close()` flushes the session to DB on a daemon thread and RETURNS that thread (or `None` on the sub-60s/no-book discard). The checkpoint deletion is NOT inside that daemon closure — it is a separate synchronous `SessionRecorder.clear_checkpoint()` that `closeEvent` calls **unconditionally** after `flush_thread.join(timeout=0.5)`. Ordering is load-bearing: `t = close(); if t: t.join(timeout=0.5); clear_checkpoint(); event.accept()` — all before `event.accept()` (the point of no return). The original code did the `unlink` inside the daemon `_write` after the DB write; on graceful close the process exits right after `close()` returns, killing that daemon thread before the unlink but AFTER the DB write landed → stale checkpoint → next startup's `_recover_checkpoint()` re-wrote the SAME session as a **duplicate** (FIXED 2026-06-21; see NOTES.md "Session recorded twice on graceful app close"). Two independent guards with two distinct jobs: the **join** gives the DB write a bounded chance to land (it can be lost only if a single-row WAL insert exceeds 500ms — DB-broken territory); the **unconditional synchronous clear** makes the duplicate impossible regardless of how the join resolved. If the clear were left inside `_write` (or made conditional on the join completing), a join *timeout* could strand a checkpoint after a committed write and resurrect the bug. `losing-at-worst` beats `duplicating`; the prior behavior was a guaranteed duplicate. The recovery-path `unlink` in `_recover_checkpoint`'s `finally` is a DIFFERENT path (runs at startup while the app stays alive) — leave it as-is.

### DO NOT call `session_recorder.close()` after nulling `_current_book` / `current_file`
`SessionRecorder` is constructed with `get_book_fn=lambda: self._current_book` (`app.py`). `close()`
reads the book through that lambda at call time and gates its entire flush on
`listened >= 60 and book is not None` — if the book is already `None`, the flush is skipped
regardless of how long the session ran, and ONLY the misleading "< 60s threshold" log line prints
(it doesn't distinguish "too short" from "no book"). `_on_book_removed` (the helper called by
scan-location removal, the book-detail trash button, and confirmed-missing handling) used to null
`_current_book`/`current_file` BEFORE calling `close()`, silently discarding every active session —
including multi-hour ones — on any removal of the currently-playing book (FIXED 2026-06-25; see
NOTES.md "`_on_book_removed` nulled `_current_book` before calling `session_recorder.close()`").
Correct order, and the one any future teardown helper must follow: call `close()` FIRST (book and
player both still valid, so the position read is also correct), THEN clear `_current_book` /
`current_file`, THEN `player.terminate()`. `tests/test_session_recorder.py` pins this contract —
keep it green on any change to `_on_book_removed` or to `SessionRecorder.close()`'s guard.

### DO NOT hard-delete from the `books` table
`remove_scan_location` soft-deletes via `UPDATE books SET is_deleted = 1` — never `DELETE FROM books`. All rows, progress, covers, `book_files`, and session history must survive a location removal so they can be resurrected when the location is re-added. Any query that drives the library view must include `WHERE is_deleted = 0 AND is_excluded = 0 AND is_missing = 0`. Stats queries must not — they key off `book_path`/`book_title` in the sessions tables directly and must see all historical rows.

### DO NOT conflate `is_deleted`, `is_excluded`, and `is_missing`
Three independent soft-delete-ish flags on `books`. `is_deleted = 1` is set by `remove_scan_location` (location removed from scan list). `is_excluded = 1` is set by `set_book_excluded` (user explicitly removed a book via the trash button) — ONLY. `is_missing = 1` is set by `set_book_missing`/`mark_books_missing` (confirmed gone from disk) — a separate flag, added 2026-06-27 specifically to stop conflating it with `is_excluded` (see the ping-pong bug below). `is_deleted` and `is_missing` both reset to `0` in the `upsert_book`/`upsert_books_batch` ON CONFLICT blocks (self-healing — the upsert only ever runs for a path the scanner just found on disk, so rediscovery is unambiguous); **`is_excluded` is sticky and does NOT reset on upsert** (`is_excluded=CASE WHEN books.is_excluded THEN 1 ELSE 0 END`). Stats queries are intentionally unfenced by all three flags — listening history and progress survive removal permanently.

**The ping-pong bug (2026-06-27) — why `is_missing` exists as its own flag:** `mark_books_missing`/`_mark_book_missing` used to write `is_excluded=1` for a book confirmed gone from disk (same flag as user-trash). The Excluded Books popup's eye-click restore (`set_book_excluded(path, False)`) treated every row identically — for a missing-flagged row, that put a file-less book back in the visible library; the user tried to load it; `_mark_book_missing` fired again (still no file) and put it right back in Excluded Books. Infinite loop ("Schrödinger's audiobook"). Fix: missing-detection now writes the dedicated `is_missing` flag instead, and `get_excluded_books()` filters `is_missing=1` rows out entirely — there's no restore action that makes sense for a book that isn't there. **Accepted edge case, not a bug:** a book can be both `is_excluded=1` AND `is_missing=1` (trashed an already-missing book, or trashed before discovery). While missing it's correctly hidden from the popup; when the file returns, `is_missing` self-heals on upsert but `is_excluded` stays sticky — the book reappears in the popup (visible again) but not the library, with no proactive notification. The user could forget about it. Out of scope, accepted.

**Scanner resurrection behaviour:** `scanner.py` builds `known_paths` from `get_all_book_paths()` (unfenced — all rows regardless of flags). Excluded/deleted/missing books are therefore recognised as known and skipped during non-force scans, so they are NOT automatically resurfaces. A force rescan (`force_refresh=True`, triggered by the Rescan button) re-processes all paths and calls `upsert_books_batch`, which resets `is_deleted` and `is_missing` to 0 (resurrecting location-removed/rediscovered books) but **keeps `is_excluded` sticky**. Do NOT change `known_paths` to use `get_all_books()` or any fenced query — doing so caused excluded books to be silently resurfaces on every scan (2026-06-06 bug).

**Sticky `is_excluded` (2026-06-27):** Both upserts use `is_excluded=CASE WHEN books.is_excluded THEN 1 ELSE 0 END`, NOT a bare `is_excluded=0`. A user-trashed book stays excluded across any number of rescans. The ONLY restore path is `set_book_excluded(path, False)` — called from the **Excluded Books** popup in the Library settings tab (`ui/excluded_books.py`, driven by `db.get_excluded_books()`); `restore_books_under_path` is NOT one (it only touches `is_deleted`). Keep both upserts in lockstep on this (the "DO NOT keep upsert_book and upsert_books_batch out of sync" rule covers it). `is_missing` is the OPPOSITE — see below — do not give it the same sticky treatment.

**Scanner missing-book detection (force rescan only, 2026-06-26, flag corrected 2026-06-27):** A force rescan also *creates* `is_missing=1` rows (it is no longer purely additive/resurrective). After Phase 1, for each location whose root `exists()` (`walked_locations`), `ScannerWorker.run_scan` diffs `db.get_visible_book_paths_under(loc)` (currently-visible books, `is_deleted=0 AND is_excluded=0 AND is_missing=0`) against the folders rediscovered on disk and calls `db.mark_books_missing(paths)` (batch `is_missing=1`) for any visible book whose folder is gone. **This writes `is_missing`, NOT `is_excluded`** — see the ping-pong bug note above for why that distinction is load-bearing. The book stays in DB/stats and self-heals (is_missing clears) the moment a later scan rediscovers the folder — no sticky-flag exception needed for that, unlike `is_excluded`. Two guards are load-bearing and must survive any refactor: (1) it runs ONLY on `force_refresh=True`, never on non-force scans; (2) it is scoped to `walked_locations` ONLY — an offline/unmounted location (root `exists()` False) is never in that list, so its books are NEVER falsely flagged when its drive is detached. The inner per-folder `entry.iterdir()` audio check is wrapped in `try/except (PermissionError, OSError)`; skipped folders accumulate in a function-scoped `skipped_dirs` set (initialized once at the top of `run_scan`, only `.add()`ed, never reassigned) that is folded into the `discovered` set, so a transient per-folder I/O error never reads as "folder gone". Do NOT scope `skipped_dirs`/`walked_locations` inside the loop or the except block.

**Location-readd resurrection (`restore_books_under_path`, 2026-06-08):** Re-adding a previously-removed scan location used to leave its books permanently hidden — `remove_scan_location` soft-deletes (`is_deleted=1`) but the scanner's `known_paths` skip (above) means a routine scan never re-processes those paths to flip the flag back, forcing a manual force rescan. `db.restore_books_under_path(path)` un-soft-deletes (`is_deleted=0`) books under `path`, called from `_on_scan_now_clicked` immediately after `add_scan_location`. It is intentionally narrower than a force rescan: it only flips `is_deleted`, gated on `is_excluded = 0`, so user-trashed books stay hidden and still require a manual force rescan — it must NOT touch `is_excluded`. This is a different code path from the scanner/`upsert_books_batch` resurrection above; keep them conceptually separate.

### DO NOT swap `get_book_count()` and `get_visible_book_count()` — they serve different purposes
`get_book_count()` queries `SELECT COUNT(*) FROM books` — all rows, including `is_deleted=1` and `is_excluded=1`. Correct for stats (which must see all historical rows). `get_visible_book_count()` queries with `WHERE is_deleted = 0 AND is_excluded = 0` — only rows visible in the library. `compute_library_state` uses `get_visible_book_count()` for `has_indexed_books`; never change it to `get_book_count()`. Using the unfenced count would make `has_indexed_books=True` even when the library panel shows 0 books (soft-deleted rows from a prior scan remain in the DB), routing the empty state into the no-book carousel instead of the scan/quote prompt.

### DO NOT pass `0.0` as `progress` to `upsert_book` or `upsert_books_batch`
The scanner does not know a book's saved playback position. Pass `None` if progress is unknown. The `COALESCE(NULLIF(excluded.progress, 0.0), books.progress)` in both upserts is a safety net against accidental `0.0` — it is not a contract that callers can rely on. Passing `0.0` would overwrite saved progress on any future DB engine that handles `NULLIF` differently.

### DO NOT keep upsert_book and upsert_books_batch out of sync
Both methods share identical SQL logic — any schema or ON CONFLICT guard change in one MUST be applied to the other. They differ only in execute vs executemany. The `CASE WHEN books.X_locked` guards for title, author, narrator, year are load-bearing: they prevent rescans from overwriting user-edited metadata. Skipping this sync causes silent data loss on rescans. (Implementation uses the bare-truthy form `CASE WHEN books.title_locked THEN ...`, not `= 1` — equivalent in SQLite since the column is `INTEGER NOT NULL DEFAULT 0`.)

### DO NOT remove the CASE WHEN books.X_locked guards from upsert ON CONFLICT
The guards `CASE WHEN books.title_locked THEN books.title ELSE excluded.title END` (and narrator/author/year equivalents) protect user-edited metadata from being overwritten by rescans. They must survive any future refactor. (The guard reads `books.title` on the locked branch and `excluded.title` on the unlocked branch; the bare-truthy `WHEN books.title_locked` is equivalent to `= 1` in SQLite.)

### DO NOT remove the lock guard from `reparse_library`
`reparse_library(pattern)` re-splits every book's `title`/`author` from `folder_name_raw` when the Library tab's naming-pattern button is clicked. Its `UPDATE` MUST keep the `CASE WHEN title_locked THEN title ELSE ? END` / `CASE WHEN author_locked THEN author ELSE ? END` guards (added 2026-06-27) — without them a naming-pattern click silently clobbers user-edited, locked title/author for the WHOLE library (it was the one write path that ignored locks; every other path — both upserts — guards them). `folder_name_raw` still re-stores unconditionally (it is the raw source string, not user-editable metadata). Param order is `(new_title, new_author, raw, id)`; the CASE WHEN handles preservation. `tests/test_reparse_library.py` pins this (both-locked preserved, title-only, author-only) — keep it green.

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
- **Deferred work goes in `TODO.md`** (added 2026-06-19), not buried in NOTES.md prose or an external scratchpad. Short dated entries: what, why deferred, what it's blocked on. NOTES.md stays for root-cause writeups of things already done; TODO.md is for things not yet started.

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
- **Keyboard** — global keys route through `ShortcutDispatcher` (`shortcuts.py`), wired in `MainWindow.keyPressEvent`. `C` opens/closes the chapter dropdown (2+ chapters only); `T` rotates theme (`COOLDOWN_COALESCE` 2s — leading fire, repeats coalesce to one trailing fire, migrated from the old `_theme_rotate_cooldown`/`_pending` attrs); `Q` rotates the no-book quote (testing-only); `L` opens the library (`COOLDOWN_DROP` 500ms — open-only, no-op if the library/any full panel is already open or in the empty state, sidebar-open flows via `_open_library_flow`). The dispatcher owns binding + spam-guard ONLY; each action's app-state gating stays in its handler. Full input map (incl. chapter-list keys, text-field Escape handlers, mouse/wheel) in `KEYBINDINGS.md`.
- **Wheel zones** — over `visual_area`: volume ±5 (2s overlay); over `speed_button`: speed ±`speed_increment`, clamped 0.25–8.0; over `progress_slider`: chapter Prev/Next (up → next chapter, down → previous; no-op when no chapters or at last/first boundary — delegates to `handle_next`/`handle_prev` so all guards are inherited); over `chapter_progress_slider`: seek by `max(10, chap_dur × 0.05)` with undo capture.
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

- `BookModel(QAbstractListModel)` + `BookDelegate(QStyledItemDelegate)` + `LibraryPanel`. Shared module-level `_cover_cache` keyed by `book.id` (int) holds one native-resolution pixmap per book. `BookDelegate` additionally holds its own per-instance `_sized_cover_cache` keyed by `(book_id, device_w, device_h)` — a LANCZOS-prescaled pixmap per grid-cell size, built lazily by `_get_sized_cover` (on the paint path) AND warmed ahead of time by the idle preloader (off-thread, 2026-07-04), consumed by `_draw_cover` so the final paint-time `drawPixmap` is a near-1:1 blit rather than a large bilinear downscale (added 2026-06-24, see CLAUDE.md rules below and NOTES.md for the full root-cause writeup).
- **Five view modes** (`VIEW_MODES`): 1-per-row, 2-per-row, 3-per-row, Square, List. Display names are randomized literary puns (reshuffle on `hideEvent`). List mode draws an animated left-edge stripe (`_pulse_timer` 40 ms) on the playing book and supports hover-fade (Off/Slow/Normal/Fast); 1- and 2-per-row support hover text-scroll.
- **Sort** (`SORT_KEY_MAP`): Title, Author, Last Played, Progress, Duration, Year, Finished. "Progress"/"Finished" appear only when such books exist (`has_books_with_progress` / `has_finished_books`). Direction toggle (`↑`/`↓`) defaults per key via `_SORT_DIRECTION_DEFAULTS`, persisted to config.
- **Search/filter** — plain text (title/author/narrator/exact 4-digit year), `#tag` prefix (`get_paths_for_tag_prefix`; `#` alone = all), year filters `>NNNN` (≥) / `<NNNN` (≤) / ranges (both orderings). No-match: search field turns dark-red and the model falls back to the full list (never empty); incomplete year expressions never show red. Right-click clears the field; persistence is per-classification (`persist_filter_tag/year/text`).
- **Cover loading** — `_load_visible_covers` finds the topmost visible row via `_first_visible_row()` (a visualRect binary search — shared with the view-mode-switch scroll-preservation capture, see rule below) then binary-searches the bottom (±5 row pad), dispatches `CoverLoaderWorker` (caps to 320×480, raised from 226×344 on 2026-06-24). Idle preloader (`start_idle_preload`): queues in sort order, `PRELOAD_BATCH_SIZE = 4` every `PRELOAD_INTERVAL_MS = 50` ms (batch was 3, raised to 4 on 2026-07-04 — measured ceiling before main-thread jank; see the constant's comment), **warms BOTH `_cover_cache` (raw) AND `_sized_cover_cache` (current view mode's cell size, off-thread — 2026-07-04)**, pauses per `_preload_paused()` (scan / theme-fade / cover-art flow anim / any panel slide — NOT static panels/Stats-Month/playback/seek), and no longer starts on an app-start timer: it's armed once after `_finish_startup` and only runs after 5s of genuine no-interaction (the eventFilter's idle-restart timer). `_on_cover_loaded` / `_on_preload_sized_cover_loaded` skip the `dataChanged` emit while `_is_animating`.
- `BookDelegate._resolve_playback` returns `(pos, dur, dur_disp, pct, has_progress, speed)`; `has_progress` (gated on `progress > MIN_PROGRESS` = 1.0s) is what shows the elapsed/bar/percentage and applies per-book speed to the displayed duration. Clicking the time label toggles remaining/total. All delegate colors are injected `Property(QColor)` for theme animation.
- **Click-to-filter on author/narrator/year (1-per-row/2-per-row only, added 2026-07-05)** — clicking author/narrator/year text sets the library search field to that value (year via the existing `<YYYY>YYYY` range-string convention) instead of selecting/playing the book. Title is never clickable. `_field_filter_target_at(book, pos)` is the single source of truth for both the click grab (`editorEvent`) and the hand-cursor decision, so they can't diverge. Multi-value author/narrator (e.g. `"Feist, Wurts"`) is split into clickable per-name segments (`_split_field_value`/`_segment_bounds`/`_segment_under_point`, on `,` `;` `" and "` `" & "`); a click in the separator gap between names is a dead zone (default cursor, falls through to normal selection) rather than grabbing the full joined string. No hover affordance beyond cursor shape — no underline, no color change, on any field. 1-per-row's title/author/narrator/year rows are fixed per-field-type slots (not redistribute-to-fill): a missing field leaves its row blank rather than letting adjacent fields shift, and the stored hit-rect height is the real font height (tight vertical hit-testing).
- **Click-filter toggle-off/revert semantics** — clicking a value that exactly matches the field's current text (author/narrator/year re-click, or reopening the library, or left-clicking into the field) reverts to `LibraryPanel._explicit_filter_text` — the user's last genuinely typed or right-click-cleared text — never to `""`. `_explicit_filter_text` is updated only on a real edit (`textChanged` while `not self._programmatic_search_update`); `set_search()` sets that guard around its `setText()` call, and every OTHER direct `search_field.setText(...)` call site (`clear_tag_filter_if_active`, `focusInEvent`'s handler) must go through the same guard or through `clear_tag_filter_if_active()` itself — an unguarded direct `setText` on this field is read by `_on_search_changed` as real typing and silently destroys `_explicit_filter_text` (this exact bug hit two separate pre-existing call sites the same day the guard was introduced; see NOTES.md). Right-click (`_on_search_right_click`) is the one deliberate hard nuke to `""` and sets `_explicit_filter_text = ""` explicitly — unaffected by any of the above. A Book Detail Panel tag chip (library context only) whose tag exactly matches the active filter renders inert (regular cursor, no click, no `<a href>`) via a one-time `active_search_text` snapshot passed through `open_book_detail`/`load_book` — see `panels.py`.
- **Keyboard navigation (added 2026-07-09)** — `_list_view` gets real `Qt.StrongFocus` and grabs focus in `showEvent`, so arrows work the instant the panel opens (no click/Tab needed first). Up/Down delegate to native `QListView.keyPressEvent` (no custom model `flags()` needed — `BookModel` already inherits `Qt.ItemIsSelectable | Qt.ItemIsEnabled`); Left/Right are hand-coded ±1-column moves (`_move_selection_by`, using `ITEM_DIMENSIONS[mode]["cols"]`) in grid modes (2-per-row/3-per-row/Square) and a no-op in the two single-column modes (1-per-row/List) — native `QListView` IconMode arrow traversal was unreliable against this app's custom `sizeHint`/uniform sizing. Enter/Space reuse `_on_item_clicked` (the same click-to-play path); Alt+Enter reuses the `detail_requested` signal (the same right-click-to-detail path) — neither duplicates its target's logic. Tab is an exclusive two-way toggle between `search_field` and `_list_view` only (`_focus_list_from_search`); it never reaches `sort_combo`/`style_combo`/`sort_dir_btn`/`back_button`, because Tab-focus routing here is fully custom (not Qt's native tab-order chain), so those widgets are simply never in the path. Mouse hover ALSO sets `currentIndex()` (`_on_view_entered`) — a single source of truth for "which book is highlighted," so Enter/Alt+Enter always act on whatever's visually lit, and a later arrow press resumes from wherever the mouse last was, not a stale keyboard position.
- **Keyboard-selection visual, per view mode** — 1-per-row keeps its own tint fill (`_kbd_selected_path`/`_kbd_alpha` on `BookDelegate`, theme keys `library_item_keyboard_color`/`_alpha`, default `accent`/0.25). 2-per-row/3-per-row/Square deliberately have **no separate tint** — they reuse the same duration/progress `_draw_hover_overlay` mouse hover already shows (`hovered or is_kbd_selected`), since a second highlight there was redundant (removed 2026-07-09 after live feedback — do not re-add a `_kbd_fill_color()` fill to these three modes). List mode reuses the mouse's own `on_list_hover_enter`/`on_list_hover_leave` hover-fade mechanism (`_flash_keyboard_selection_list`) so it honors the user's Hover-fade setting (Fast/Normal/Slow/Off) exactly like a real hover would — with its own `BookDelegate._kbd_hover_path` (independent of `_kbd_selected_path`/`_kbd_alpha`, which List mode ignores entirely) as the Off-mode instant-fill fallback, mirroring hover's own Off-mode fallback. Keyboard-move handling calls `_on_view_left()` (the same teardown a real mouse-Leave uses) before showing the keyboard highlight, and mouse hover entering a DIFFERENT book calls a quick fade-out (or an instant clear if it's the SAME book) on whatever keyboard highlight was showing — so only one highlight is ever visible, never both at once.

### Stats Panel (`stats_panel.py`)

- **Tabs**: Overall, Timeline, Day, Week, Month, ⚙.
  - **Overall** — `BarChartWidget` (last 7 days; click a bar → Day tab at that date); stat grid (Listening time, Books started, Sessions, Longest/Last/Average session, Current/Longest streak); "Recently finished" `FinishedScrollRow` (≤ 20, hidden when empty).
  - **Timeline** — both `HourlyHeatmap` and `StreakGrid` built, one visible (default from `config.get_default_timeline_view()`); `TasselOverlay` toggles them with a conceal→reveal transition.
  - **Day / Week / Month** — ‹/› nav (right-click jumps to oldest/newest), wheel-scroll header (Day optionally accelerated), `BookDayRow` list (rows < 60s excluded), total label, "Finished" `FinishedScrollRow`.
  - **⚙** — day-start hour `QSpinBox` (0–23, rebuilds streak cache), period scroll-acceleration toggle, default-timeline-view toggle, "Reset all stats" (7s confirm).
- **`HourlyHeatmap`** — 14-day × 24-hour grid (CELL 14, GAP 1), today leftmost; cell alpha `40 + intensity×215` (intensity = `min(1, sec/3600)`); hover highlights + per-hour tooltip (date, total, per-book table). Mexico-wave reveal/conceal cell transition uses the shared `_grid_cell_anim` helper, style `"pop"` (cells scale up from a center-anchored inset as they reveal, shrink back on conceal — not a plain alpha fade); top date labels and left-gutter hour labels cascade via per-label opacity fade with enter/exit as true mirrors (left-to-right entering top labels / right-to-left exiting; top-to-bottom entering gutter labels / bottom-to-top exiting).
- **`StreakGrid`** — 26×14 = 364-day calendar, today top-left, backed by `streak_grid_cache`. Listened days filled accent; finished days get a small sharp centered 4×4 square dot (`_finished` set, `streak_grid_dot` per-theme override); the longest consecutive run **fills with a derived lighter/desaturated tint of accent and borders in plain accent** (`streak_grid_outline` per-theme override for the border color — fill/border roles were swapped from the original distinct-fill design), computed in-widget by `_compute_longest_run` (most-recent run wins on tie). Left gutter shows the current-streak icon + an animated count: linear count-up 0 → previously-shown value, then (only if the streak grew since last shown) a paused snappy tick up to the new value — see `animate_streak_count`/`catch_up_streak_count` and the two CLAUDE.md rules above on persistence and the panel-reopen catch-up exception. Same `_grid_cell_anim` "pop" transition as the heatmap.
- **`TasselOverlay`** — sliver tab pinned top-left (~7px peek), slides down → holds 1200 ms → switches view → retreats; clock icon (Streak) ↔ fire icon (Heatmap; was `calendar.svg`, swapped 2026-06-18 — rendered as a plain rectangle at 14px). Icon recolors via `accent_dark`/`bg_main` theme keys (was `accent`) and updates only once the bookmark is fully retreated at rest, not mid-transition — see `TasselOverlay.play(on_switch, on_retreated=...)`. `_switch_timeline_view` uses a 2-counter seam so the visibility flip waits for both conceal and label-out. A decorative tassel (cubic-Bezier cord looping from the tab's top-centre, vertically into a bound "head" rect, fanning into a 7-thread fringe — added 2026-06-19 Session 3, `_cord_color` from `accent_dark`/`bg_main`) hangs alongside the tab: a perpetual ~30fps idle micro-sway plus a decaying "kick" on slide-down/retreat, gated by `showEvent`/`hideEvent` + an `isVisible()` tick guard. The widget itself is wider/taller than the tab to give the tassel room, but `_tab_rect`/`REST_Y`/`EXT_Y`/the 7px peek are unchanged; clicking and the hand cursor are both driven by `_in_hit_region()` (tab rect OR a tight tassel-body box — see the CLAUDE.md rule above) so the cursor never shows over dead space.
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

- Themes tab, Controls tab (chapter digit mode by_name/by_index, autoplay/jump-only toggle), Audio tab, Library tab (folder management, naming pattern, chapter source Embedded/.cue, persist-filter, and an **Excluded Books** toggle line — `ui/excluded_books.py`'s `ExcludedBooksSection` — that opens `ExcludedBooksPopup`, a `MainWindow`-level popup, NOT an inline expanding widget; rebuilt on each panel open via `_reload_excluded_books`, restoring via `set_book_excluded(path, False)`). Bound dynamically via `SettingsController` through the five interface facades.

### Library state machine, scan & covers (`library_controller.py`, `library/`)

- **`compute_library_state`** → `{mode, has_book, has_locations, has_indexed_books}`. `mode` is `empty` (no locations OR no visible indexed books), `scanning` (locations + indexed + scanner running), or `ready`. `has_book` derives from `app.get_current_file()`; `has_indexed_books` from `get_visible_book_count()`.
- **`apply_library_state`** branches: **empty** (hide chrome/Library button/carousel, suppress bg, rotate quote, set prompt by sub-state: no-locations / scanning / no-books); **no-book** (show Library button, hide prompts, show metadata "go to library", suppress bg, show reshuffled carousel); **has-book** (show Library button, hide carousel, restore bg, delegate metadata visibility to `_load_cover_art`).
- **`apply_current_state`** is the sole compute+apply entry point (no scan side effects). **`_check_library_status(manual, force_refresh)`** = `apply_current_state` + `handle_background_tasks` (starts a scan when manual, force, or no indexed books, and not already scanning).
- **Location flows** — add (`_on_scan_now_clicked`): abspath-normalize, dedupe against sub/parent existing locations, `add_scan_location`, then **synchronous** `restore_books_under_path` (un-soft-deletes `is_deleted=1, is_excluded=0` books under the path), refresh, `_check_library_status(manual=True)`. Remove: `remove_scan_location` (soft-delete), unload the current book if it was under a removed folder, refresh. Excluded books stay hidden through both.
- **Scanner** (`scanner.py`) — `LibraryScanner` owns a `QThread`; `ScannerWorker` does the work, cancellable via a `threading.Event`. Phase 1 discovers one-level-deep book folders (any audio extension). Phase 2 builds `known_paths` from `get_all_book_paths()` (ALL rows regardless of flags) — on a non-force scan, known (incl. excluded/deleted/missing) paths are skipped and NOT resurrected; a force scan re-extracts everything and `upsert_books_batch` resets `is_deleted` and `is_missing` to 0 but keeps `is_excluded` sticky (see the "Sticky `is_excluded`" rule). A force scan additionally runs missing-book detection (2026-06-26, flag corrected to `is_missing` 2026-06-27): visible books under a scanned-and-reachable location whose folder is gone from disk are batch-flagged `is_missing=1` via `db.mark_books_missing` (see the "Scanner missing-book detection" rule above — NOT `is_excluded`, that was the ping-pong bug). Extracts cover (external image file → embedded tag), narrator/title/author/year (tag priority chains → folder-name fallback), `book_files` (multi-file only), summed duration; generates a 226×344 JPEG thumbnail under the cache dir and upserts a locked scanner cover (slot 0) if none exists.
- **Cover manager** (`cover_manager.py`) — `get_covers_dir` (user data dir), `save_cover_image`, `delete_cover_file`, `validate_cover_file` (size-only ≤ 5 MB).

### Database (`db.py`)

- SQLite, WAL per connection, `sqlite3.Row` factory, auto-commit/rollback context manager.
- **Tables**: `scan_locations`; `books` (+ `progress`, `year`, `started_at`/`finished_at`, `chapter_source`, soft-delete `is_deleted`/`is_excluded`/`is_missing`, four `*_locked` flags); `listening_sessions` (+ `book_id` FK, `furthest_position`); `book_events` (+ `book_id`, `event_type`, `source`); `book_tags` (`book_id`); `tags` (name PK, color); `book_covers` (locked/active/fit_mode/sort_order); `book_files` (sort_order, duration_ms, cumulative_start_ms, title); `streak_grid_cache` (date PK, listened) — a 364-row rolling window.
- **Soft-delete-ish flags** — `is_deleted` set by `remove_scan_location`, cleared by `restore_books_under_path` (only when `is_excluded=0`) or any upsert; `is_excluded` set by `set_book_excluded` (user-trash only), untouched by removal/restore, cleared only by `set_book_excluded(path, False)` (sticky through upserts); `is_missing` set by `set_book_missing`/`mark_books_missing` (confirmed gone from disk), self-heals on any upsert (the opposite of `is_excluded`'s stickiness) — see "DO NOT conflate" above. "Visible" = all three 0. `get_book_count()` (all rows, for stats) vs `get_visible_book_count()` (library); `get_all_book_paths()` is unfenced (drives the scanner's `known_paths`).
- **Upserts** — `upsert_book` / `upsert_books_batch` share identical SQL (execute vs executemany). ON CONFLICT guards: title/author updated only if not `*_locked`; narrator/year additionally NULLIF-guarded against empty/null; `progress` via `COALESCE(NULLIF(excluded.progress, 0.0), books.progress)`; `is_deleted` resets to 0; `is_excluded` is sticky (`CASE WHEN books.is_excluded THEN 1 ELSE 0 END`); `is_missing` resets to 0 unconditionally (self-healing, NOT sticky — do not copy the `is_excluded` CASE WHEN pattern onto it). All three must stay in lockstep between the two upserts.
- **Sessions/events** — `write_session` dual-writes `book_path` + `book_id` and updates the streak grid for the start and end dates; `write_book_event` writes events (only `source='playback'` finished events light a grid cell). `unfinish_book` / `clear_finished` / `delete_session` / `delete_book_stats` all re-evaluate the affected grid cells. `set_started_at` only writes when NULL.
- **Stats queries** — `get_book_stats`, `get_overall_stats`, `get_last_n_days` (zero-fills gaps in Python), `get_active_periods`, `get_listening_time_per_period`, `get_books_listened_in_period`, `get_daily_book_breakdown`, `get_finished_in_period`, `get_recently_finished`, `get_streaks`, `get_hourly_heatmap` (splits sessions across clock-hour boundaries in Python, caps 3600s/hour, wall-clock with no day-start offset). Stats queries are intentionally unfenced by the soft-delete flags and use `COALESCE(b.title, ls.book_title)` over LEFT JOINs so deleted books keep their title. Per-book period positions use correlated subqueries (and `has_finished_books` uses `EXISTS`) to avoid cartesian fan-out.
- **Streak grid** — `build_streak_grid_cache` seeds 364 dates at 0 then flips any date with a qualifying session (start OR end adjusted-date) or `source='playback'` finished event to 1; `_update_streak_grid_cache_for_date` does incremental updates; all date attribution uses a SQL `day_start_hour` offset (passed in, never read from config). **Invariant: a finished day is always a listened day** — a playback-finish lights its cell even with no session; manual (`source='manual'`) finishes never touch the grid (visible in Finished tab/detail only). `get_streaks` (the streak count) mirrors this same start∪end∪finished day-set — see CLAUDE.md rule below.
- **Tags** — `add_book_tag` (lowercased, ≤ 20 chars; per-book 5, global 50 limits), `remove_book_tag`, `get_all_tags` (LEFT JOIN color), `get_books_by_tag`, `get_paths_for_tag_prefix`, `rename_tag`, `delete_tag`, `set_tag_color`, `get_tag_suggestions`. **Covers** — `get_active_cover[_path]`, `get_covers_for_book`, `upsert_cover`, `set_active_cover` (maintains the single-active invariant manually), `set_fit_mode`, `delete_cover`.

### Session Recording (`session_recorder.py`)

`SessionRecorder(QObject)` owns all session state/persistence; `MainWindow` holds one and delegates. `_current_book` stays on `MainWindow` (passed via `get_book_fn`); day-start hour via `get_day_start_hour_fn`.

- **Lifecycle**: `open()` (start, seed furthest position, start checkpoint timer), `resume()` (after a short pause), `pause()` (accumulate the segment, start the 3-min `_pause_timer`), `close()` (accumulate, flush to DB if `listened ≥ 60`, reset). `is_active` property.
- **Thresholds**: 60s wall-clock minimum (else discarded), 3-min pause timeout (auto-close), 15s **seek credit** — a forward seek past the furthest sets `_post_seek_pending_position` and starts `_seek_credit_timer`; staying 15s promotes it (a backward seek cancels). `notify_seek(new_pos)` from slider-released handlers feeds this; `update_furthest_position(pos)` from the 200 ms loop advances the furthest only when no seek credit is pending.
- **Persistence**: `write_session` dual-writes `book_id` + `book_path` + title/author/duration + start/end/positions + `furthest_position` + `listened_seconds` + `day_start_hour`; sets `started_at` if unset; runs on a daemon thread and emits **`session_written`** (lives on the recorder, not `MainWindow`). A `session_checkpoint.json` is written every 30s and recovered on startup (writes a session if ≥ 60s, without emitting `session_written`). `close()` returns its flush daemon thread; `closeEvent` joins it (500 ms) then calls `clear_checkpoint()` **synchronously** so the checkpoint never survives a graceful close into the next startup's recovery (would otherwise double-write the session — see the `close()`/`clear_checkpoint()` rule above). The checkpoint `unlink` is NOT in the daemon thread.

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

### Logging (`logger_setup.py`, added 2026-07-01)

Pure plumbing, no call sites yet. `setup_logging()` (called first thing in `main.py`'s `__main__` block, before `QApplication`) configures the `fabulor` root logger **once** (idempotent): a `RotatingFileHandler` (2 MB × 3 backups) at `platformdirs.user_log_dir("fabulor")`, level from `FABULOR_LOG_LEVEL` (DEBUG/INFO/WARNING/ERROR, case-insensitive, invalid → WARNING default), format `"%(asctime)s %(levelname)-8s %(name)s — %(message)s"`, `propagate=False` — **file sink only, no stdout/console handler**. Emits one `logger.warning("Fabulor started")` at the end (WARNING, not INFO, so it lands in the file at the default level). Module-level `logger = logging.getLogger(__name__)` instances exist in `player.py`, `app.py`, `ui/theme_manager.py` but are **silent** — call sites land incrementally in later sessions. **Windows-port note:** the log dir uses the one-arg `user_log_dir("fabulor")` form (no appauthor), unlike the two-arg `user_data_dir("fabulor", "fabulor")` used everywhere else — see NOTES.md (2026-07-01) for why that matters on Windows.

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

### DO NOT make `get_streaks` use start-date-only attribution — it must union session_end, matching the grid
The streak grid (`build_streak_grid_cache`/`_update_streak_grid_cache_for_date`) has always
correctly lit a cell if a session's start OR end adjusted-date matches it — a session spanning the
day_start_hour boundary (e.g. 23:55→00:05, or 04:53→06:02 with `day_start_hour=5`) genuinely was
listened to on both of those adjusted-days, and the grid cells were right to reflect that. The bug
(found 2026-06-19, see NOTES.md "Streak count / grid cell mismatch") was that `get_streaks` — which
drives the streak NUMBER, not the cells — built its day-set from `get_active_periods` (start-date
only, by design: it also drives Day/Week/Month nav and must stay start-only there) plus finished
events, but never unioned session end-dates. So a spanning session lit two grid cells while the
streak count/label only credited one of those days. Fixed by adding a session_end-date query
directly inside `get_streaks` (NOT by changing `get_active_periods`, which must remain start-only
for the period navigator) and unioning it into `active_set` alongside the existing finished-event
union — mirroring `build_streak_grid_cache`'s three sources (start, end, finished) exactly. Do
NOT "fix" this again by making the grid start-only to match `get_active_periods` — that direction
was tried and reverted; the grid was correct, the streak count was the thing missing data. The
Day/Week/Month tabs are explicitly start-date-only and intentionally do NOT show a spanning
session twice — see NOTES.md for why full session-splitting there was scoped out as too large a
change for too small a benefit.

### DO NOT add a key to "The Color Purple" without checking `_NO_BASE_INHERIT_KEYS` (themes.py)
Every theme is resolved by `_resolve_theme()` as `THEMES["The Color Purple"].copy()` overlaid with
the requested theme's own dict — "The Color Purple" is the base template every other theme
inherits from for any key it doesn't set itself. This is correct for plain literal-value keys
(a theme that doesn't set `bg_deep` should get Purple's), but WRONG for any key whose intended
"unset" behavior is a *derived* per-theme fallback rather than Purple's literal value — e.g.
`streak_grid_outline`/`streak_grid_dot` (meant to fall back to a value derived from that theme's
own `accent`, via `StreakGrid._derive_longest_fill`/`_derive_finished_dot`) and `slider_progress`
(meant to fall back to `text_on_light_bg` → `text`). Without exclusion, Purple's literal value
would silently inherit into every theme that doesn't define its own, masking the derived fallback
entirely. `_NO_BASE_INHERIT_KEYS` (a tuple near `_resolve_theme`) lists every such key; `_resolve_theme`
pops them from the copied base before overlaying. **Any new optional/fallback-driven theme key
that "The Color Purple" itself ever defines a value for MUST be added to `_NO_BASE_INHERIT_KEYS` in
the same change** — added 2026-06-19 (Session 4): the five tassel/bookmark keys
(`bookmark_body`/`bookmark_icon`/`tassel_cord`/`tassel_head`/`tassel_fringe`) do NOT need to be in
the tuple today because "The Color Purple" doesn't set any of them yet — but if it ever does (e.g.
giving the reference theme an explicit tassel color), that addition must land together with adding
those keys to `_NO_BASE_INHERIT_KEYS`, or every other theme that relies on the
`tassel_cord`/`tassel_head` → `tassel_fringe` → `accent_light` fallback chain will silently start
showing Purple's literal tassel color instead.

### DO NOT fold `animate_conceal` duration logic into `HourlyHeatmap.animate_reveal`
`animate_conceal` (on both `HourlyHeatmap` and `StreakGrid`) is **additive-only**: it reuses the `reveal_progress` property in reverse (1.0→0.0, 600ms) and is the streak↔heatmap transition's drain phase. `HourlyHeatmap.animate_reveal` and `paintEvent` stay byte-for-byte unchanged. `animate_conceal` restores the 1000ms reveal duration in its `finished` callback so the following construct wave runs full-length, and tracks its pending slot in `self._conceal_slot` (disconnect only when present — avoids `Failed to disconnect (None)`). The asymmetric duration restore is the whole point; do NOT share a `setDuration(600)` between the two methods. Relatedly: `StreakGrid.set_data` must NOT call `animate_reveal()` — the caller (`_switch_timeline_view` / `_on_tab_changed`) fires exactly one reveal on the visible grid, else the tab-change reveal double-fires and hitches.

### DO NOT give the label-cascade enter/exit `_label_local` the same opacity-window formula
`HourlyHeatmap`/`StreakGrid`'s per-label cascade (top date labels, left-gutter date/hour labels) must
use a DIFFERENT window-placement formula for entering vs. exiting, not the same formula run with
`_label_progress` going the other direction. Enter anchors each label's fade-in window from the START
of the timeline (`start` to `start + span`); exit must anchor from the END (`end - span` to `end`,
where `end = 1.0 - start`). Reusing the enter formula for exit (just feeding it a falling
`_label_progress`) silently breaks because clamping (`max(0, min(1, ...))`) masks the asymmetry: the
"leading" label ends up holding at full opacity until late in the exit animation instead of fading
first, which reads as the wrong cascade direction even though the per-label rank assignment
(`cascade_pos`) is correct. This was found and fixed 2026-06-18 — see NOTES.md "Timeline tab visual
rework" for the verification approach (hand-computed opacity at several progress values per rank
before trusting it visually). Also: `_label_sweep_in` must be initialized in `__init__` (both
classes) — it was previously only ever set inside `animate_labels_in`/`animate_labels_out`, so the
very first paint before either had run raised `AttributeError`.

### DO NOT keep the streak count-up's "previous shown" value in-memory only
`StreakGrid.animate_streak_count(previous=...)` needs to know the streak value as of the last time it
actually animated, to decide whether to run the pause-then-tick second leg. That value MUST be
persisted via `Config.get_last_shown_streak()`/`set_last_shown_streak()` (QSettings-backed), not kept
only in `StreakGrid._last_animated_streak` (in-memory instance state). An in-memory-only value resets
to `None` on every app launch, so the session's first reveal always falls into the "no prior value,
skip the pause" branch — even when the streak genuinely grew while the app was closed. `None` (not
`0`) is the correct "never tracked" sentinel: defaulting to `0` would make a pre-feature upgrade with
a real non-zero streak misread "never tracked" as "previous was 0" and spuriously play a 0→N
pause-then-tick that implies growth from nothing.

### DO NOT let the Stats panel's Timeline slide-reopen skip the streak catch-up tick
`QTabWidget.currentChanged` only fires when the active tab index changes. If the Stats panel slides
open with Timeline already the remembered active tab (the normal case — panel was last closed on
Timeline/Streak), `_on_tab_changed` never runs that session; the only code path is
`refresh_current_tab() -> _refresh_time() -> StreakGrid.set_data()`, which correctly never animates the
grid (slide-reopen must never animate grid cells/labels — established rule, see the `animate_conceal`
rule above). Without an explicit exception, that same flow also silently swallowed the streak
count-up: `set_data()` snapped the number straight to its new value with zero comparison against the
persisted previous value, so a streak that grew while the panel was closed showed the new number with
no visual call-out at all. Fix: `StatsPanel._refresh_time(streak_mode=...)` takes `"full"` (tab click /
view-switch seam — runs the normal two-leg `animate_streak_count()`), `"catch_up"` (wired only from
`refresh_current_tab`'s Timeline branch — calls `StreakGrid.catch_up_streak_count(previous)`, which
snaps to the old value and ticks to the new one WITHOUT touching the grid at all), or `"none"`
(background refreshes like `refresh_all` — leaves `set_data()`'s plain snap untouched). This is the
one deliberate place where the streak number's animation rule diverges from the grid's blanket
"never animate on slide-reopen" rule — the grid stays fully static every time, the number gets a
narrow exception so a real change is never silently dropped.

### DO NOT animate a UI count-up toward a target derived from a coarser/truncated value than what live tracking will show
`_animate_percentage_label`'s tween must compute its end value as `round((new_progress/dur)*100, 1)`
— the SAME rounding the live 200ms tracker uses (`f"{percent:.1f}%"`) — not by re-deriving a percent
from the progress slider's `new_val` (`int((new_progress/dur)*1000)`, which TRUNCATES to the
slider's coarser 0-1000 scale). A true value like 739.97 truncates to slider tick 739 ("73.9%") but
rounds to "74.0%" — every book whose saved progress rounds up in its last digit reproduced a
guaranteed one-tick jump the instant the live tracker resumed after the tween. This is a
truncate-vs-round MATH mismatch, not a timing race — a settle-delay guard was tried first and
confirmed not to fix it (the jump was identical with or without the delay). Any future animated
label that shares a "coarse slider scale" data source with a "precise live display" must independently
verify both sides actually agree on rounding before assuming a delay/guard will paper over a gap.

### DO NOT trust a callee's busy/no-op guard to protect a caller's OWN side effects
`TasselOverlay.play()`'s `_busy` flag correctly no-ops repeat calls for the bookmark slide animation
itself, but `StatsPanel._on_tassel_clicked` also independently calls `_switch_timeline_view()` on
every click — and that call was NOT gated on anything, so rapid clicking queued up multiple
overlapping `_switch_timeline_view()` cycles (each its own `animate_conceal`/`animate_labels_out`
pair) racing over the same grid visibility state, which could hang the Timeline view indefinitely
with both grids left hidden. Fixed via a public `TasselOverlay.is_busy` property that
`_on_tassel_clicked` checks itself before doing anything. General rule: if a caller triggers a side
effect ALONGSIDE calling a method that has its own internal busy/idempotency guard, the guard
living inside that method does not protect the caller's side effect — the caller must check the
same busy state itself (via an exposed property, not by assuming the callee's no-op will be enough).

### DO NOT let `TasselOverlay`'s hand cursor and clickable region diverge
`TasselOverlay.__init__` does NOT call `setCursor(PointingHandCursor)` on the whole widget — that
was the original (2026-06-19) implementation and it was a real UX bug: the widget is wider/taller
than its actual clickable area (the tab rect plus the tight tassel body box, via
`_in_hit_region()`), so a blanket cursor showed a hand over dead space where clicking did nothing.
The cursor is instead set dynamically in `mouseMoveEvent`, calling `setCursor`/`unsetCursor` based
on the exact same `_in_hit_region()` test that `mousePressEvent` uses. Any future change to the
clickable region (`_tab_rect`, `_tassel_rect`) must keep reading through `_in_hit_region()` from
both methods — do not special-case the cursor logic or the click logic separately, or they will
silently drift apart again.

### DO NOT use `load_themed_icon` for `currentColor` SVGs — use `load_currentcolor_icon`
clock.svg / calendar.svg use `fill="currentColor"`. `load_themed_icon` only swaps `fill="#000000"`; it happens to tint these anyway via its `<style>`-injection fallback, but that is incidental, not contractual. `load_currentcolor_icon` recolors `currentColor` explicitly via regex (mirrors `render_logo_placeholder`). Use it for these icons; do not "simplify" back to `load_themed_icon` on the theory they're equivalent.

### DO NOT remove animation-state guards in `_sync_progress_sliders` / `_sync_chapter_ui`
Both check whether animation is running before setValue. Removing causes jitter from 200ms timer fighting animation.

### DO NOT touch MPV init block
`_ensure_mpv()`, `load_book()` MPV block, `locale.setlocale(LC_NUMERIC, "C")`, all MPV constructor args. Hard-won Wayland/libcaca/libtinfo/Qt locale bug fix. Changing anything breaks the app.

### DO NOT restore `show_metadata=False` to `library_controller.apply_library_state`
Removed in 2026-05-11 — it was silently overriding cover display on every book switch. `_load_cover_art` owns `metadata_label` visibility.

### DO NOT call `search_field.setText(...)` directly anywhere in `LibraryPanel` outside `set_search`/`clear_tag_filter_if_active`
Every direct write to the library search field must go through `self._programmatic_search_update = True` / `setText(...)` / `= False`, or through `clear_tag_filter_if_active()` (which already does this). `_on_search_changed` reads any unguarded `setText` as genuine user typing and overwrites `self._explicit_filter_text` — the value click-filter toggle-off/revert (author/narrator/year re-click, library reopen, left-click into the field) restores to instead of clearing to `""`. This bit twice in one day (2026-07-05, `6847330` and `a7271a5`) via two DIFFERENT pre-existing direct-`setText` call sites (`clear_tag_filter_if_active`'s old body, `focusInEvent`'s handler) that predated the guard and were never routed through it. If a new call site ever needs to change the field's text programmatically, route it through the guard or through `clear_tag_filter_if_active()` — never call `setText` on `search_field` bare.

### DO NOT use `active_cover_changed` on `BookDetailPanel` as a single-arg signal
It emits `(book_path, cover_path)` — both args required at all call sites. `CoverPanel.active_cover_changed` remains `Signal(str)`; the intermediate slot `_on_cover_panel_changed` in `BookDetailPanel` injects `self._book_path` and re-emits. Do not connect `CoverPanel.active_cover_changed` directly to `BookDetailPanel.active_cover_changed`.

### DO NOT pass raw DB rows directly to `BookDayRow` or `FinishedBookThumb`
Always call `StatsPanel._inject_active_covers()` on the row list first. Raw rows carry only `cover_path` (scanner thumbnail); `_inject_active_covers` adds `active_cover_path` from `book_covers`. Skipping it causes stats panel thumbnails to show scanner art instead of the user-selected cover.

### DO NOT remove the `has_progress` gate on speed application in `BookDelegate._resolve_playback`
Speed is only applied to `dur_disp` when `has_progress` is `True`. Books with no progress always show total duration at 1x regardless of per-book speed. Removing this gate causes incorrect duration display in the library view.

### DO NOT lay out a library row from the live viewport width — reserve the scrollbar's space
Any per-row geometry with **right-aligned** content (author, time column, progress %) must NOT derive its width or right edge from `option.rect.width()` / `r.right()` (the live viewport), because that value drops by `SCROLLBAR_EXTENT` (14px) when the vertical scrollbar appears and regains it when the scrollbar disappears — so filtering, which shrinks the list and toggles the scrollbar, makes right-aligned content jump by 14px. Lay out against a **stable** width/right edge that reserves the scrollbar gutter unconditionally: `BookDelegate._row_content_width(...)` (= `view.width() - 2*frameWidth - SCROLLBAR_EXTENT`) and `_row_stable_right(r)` (the stable right-edge x, use in place of `r.right()`) — 2026-07-06. The view width is fixed (the scrollbar takes space *inside* it, shrinking the viewport but not the view), so this is constant regardless of scrollbar state. Left-aligned content (title, the progress bar itself) is unaffected. **Fixed in both List (`_list_author_layout`, commit `9c20f40`) and 1-per-row (`_paint_one_per_row`, commit `9f8b06f`).** When adding ANY new right-aligned row content in ANY mode, route it through `_row_stable_right`/`_row_content_width`, never `r.right()`/`option.rect.width()` directly.

### DO NOT remove `_sized_cover_cache`/`_get_sized_cover` as "just an optimization"
This cache is load-bearing, not a performance nicety layered on top of an already-correct render.
Confirmed by direct measurement (2026-06-24): the scanner-side fixes alone (cover discovery,
LANCZOS thumbnail resampling, 320×480 cap) produced **zero visible improvement** in the library
grid, even after a full force rescan + app restart. The reason is `_draw_cover`'s own
`painter.drawPixmap(rect, cover, src_rect)` — a single Qt bilinear downscale straight from the
cached thumbnail (up to 320×480) down to the real cell size (as small as ~88×88) — which erases a
better source's quality gain regardless of how good that source is. `_get_sized_cover` exists
specifically to remove that downscale's *magnitude* (pre-shrink close to cell size via LANCZOS
first, so the final `drawPixmap` is a near-1:1 blit). If this cache is ever removed or bypassed,
the library grid will silently regress to the exact "no visible difference" state this was built
to fix — the scanner-side quality work is necessary but was proven, by measurement, insufficient
on its own.

### DO NOT change `_get_sized_cover`'s scale mode to `KeepAspectRatioByExpanding`
`_get_sized_cover` (`BookDelegate`, `library.py`) pre-scales the cached cover to roughly the grid
cell size before `_draw_cover` runs its square/crop/letterbox branching. It deliberately uses a
plain aspect-preserving bounded fit (scale by `max(dev_w/w, dev_h/h)`, same shape as
`KeepAspectRatio`), NOT `KeepAspectRatioByExpanding` cropped exactly to the cell. This looks like
the "more correct" choice for a pre-sized thumbnail cache — it isn't: `_draw_cover`'s letterbox
branch needs the pixmap's real, uncropped proportions to compute its own centered inset; feeding it
an already-cell-cropped pixmap breaks letterbox specifically while leaving the square/stretch/crop
branches looking fine, so the bug would only surface on covers whose aspect ratio lands in the
letterbox bucket (>8% ratio mismatch from the cell). Also do not raise the `UnsharpMask` strength
in `_lanczos_qimage` (currently `radius=0.8, percent=25`; this is where the scale logic lives as of
2026-07-04 — `_lanczos_scale` is now just its main-thread `QPixmap` tail) without re-checking against
a *photographic* cover, not just a flat-color graphic one — a stronger pass (`percent=60` was tried
and reverted) reads as fine on graphic art but produces visible edge haloing on photographic
gradients (skies, faces), described by the user as "out of focus, then we slapped an HDR filter on
it." Full root-cause writeup in NOTES.md, 2026-06-24.

### DO NOT write `_sized_cover_cache` from a worker thread, read DPR off the main thread, or let the preloader's key drift from `_get_sized_cover`'s
The idle preloader warms `_sized_cover_cache` off-thread (2026-07-04). Three invariants make that
safe; all are load-bearing:
- **The scale is split for thread-safety.** `_lanczos_qimage(QImage→QImage)` (the PIL LANCZOS +
  UnsharpMask) is the ONLY part that may run on a `CoverLoaderWorker` thread — it touches only
  `QImage` (a pure raster container) and PIL. `QPixmap` is a GUI-thread-only paint device: creating
  or reading one off-thread is undefined behaviour (works sometimes, crashes others). So the worker
  emits a `QImage` (`sized_cover_loaded`), and the `QImage→QPixmap` conversion + the `_sized_cover_cache`
  write happen on the main thread in `_on_preload_sized_cover_loaded` (QueuedConnection). NEVER write
  either cover cache from a worker; NEVER move the QPixmap step off-thread.
- **DPR is read on the main thread at enqueue time and passed by value** into the worker
  (`_current_sized_key_dims()` reads `self.screen()`), because `screen()`/DPR access off the GUI
  thread is unsafe. Do not read it inside the worker.
- **The preloader's key MUST equal `_get_sized_cover`'s paint-time key**, `(book_id, round(target_w*dpr),
  round(target_h*dpr))`. `BookDelegate.cover_cell_size()` is the single source of the per-view-mode
  `target_w/target_h` and MUST stay in lockstep with the cover-rect math in `_paint_grid_cell`
  (`r.width()-4, r.height()-4`), `_paint_one_per_row` (100×151), and `_paint_two_per_row` (113×172).
  A mismatch is silent: the preloaded entry keys on the wrong size, is never hit at paint time, and
  the LANCZOS runs on the main thread during the slide anyway — the exact stall this warming exists
  to remove. Verified matching for all five modes when added; re-verify if any cover-rect formula
  changes. Warming is **current view mode only** (all-modes doesn't scale by library size — see
  NOTES.md cost table and the "FUTURE IDEA" first-page-per-mode note). Batching is also load-bearing:
  dumping all workers at once froze the main thread ~766ms (completion slots pile onto it), so keep
  `PRELOAD_BATCH_SIZE` batched — 4 is the measured ceiling; do not raise without re-measuring the
  real two-slot completion path.

### DO NOT add an overlay-open path that skips `is_overlay_open_or_committed()`
Only ONE overlay (the six sidebar panels — library/settings/speed/sleep/stats/tags — the chapter-list dropdown, or a mid-flight sidebar handoff) may open at a time. `PanelManager.is_overlay_open_or_committed()` (`panels.py`) is the single gate: `is_any_full_panel_visible() OR is_any_panel_animating() OR _pending_panel_open is not None`. Every overlay-OPEN entry point consults it FIRST and early-returns (drops the request) if True — the six `_open_*_flow` methods, `_show_chapter_dropdown` (AFTER its own already-visible→`fade_out` toggle), and `_open_library_shortcut`. The speed/sleep buttons delegate to `_open_speed_flow`/`_open_sleep_flow` (which gate) instead of the old unconditional `_hide_popups()`-then-open. **Policy is DROP the second request (ignore), NOT switch or queue** — two opens inside the animation window aren't legitimate intent. Do NOT "fix" a collision by making an opener call `hide_all_panels()` then open: that starts a close-slide that fights the other panel's open-slide (the exact overlap bug this replaced — see `review/Review_260706_2.md`). Load-bearing exclusions that must stay: a **bare expanded sidebar** is NOT blocked (the gate excludes it so the sidebar-queued open path works); the sidebar handoff dispatches via `_start_*_entry` (not `_open_*_flow`) so it's never blocked by its own committed state; `open_book_detail` is intentionally UNGATED (reachable only from within an already-open library/stats/tags panel — never races a fresh open). `_close_*_flow` and the own-panel-visible→close toggles are never gated. The FUTURE "press L in Stats → dismiss Stats, open Library" switch behavior is deliberately NOT built (shortcuts are main-window-exclusive today). `tests/test_panel_exclusion.py` pins the gate's truth table.

### DO NOT replicate `apply_library_state(compute_library_state())` at a call site
`apply_current_state()` on `LibraryController` is the sole entry point for reconciling library UI state without scan side effects. Any call site that needs compute-and-apply (but not a scan trigger) must call `self.library_controller.apply_current_state()` — never inline the two-liner. Inlining the compute+apply pair creates sync-drift risk identical to the `upsert_book` / `upsert_books_batch` invariant: the pairing can drift independently from `apply_current_state`'s implementation. `_check_library_status` delegates to `apply_current_state` internally and additionally calls `handle_background_tasks`; use it only when a scan trigger is appropriate.

### DO NOT suppress the theme `bg_image` by overriding `visual_area` — regenerate the stylesheet without it
The theme `bg_image` is painted by `content_container`'s `QWidget#visual_area { background-image: url(...) }` rule in `get_player_stylesheet`. It is stripped in the no-book and empty-library states (where it overlapped the prompts/carousel/quote). The ONLY working suppression is `get_player_stylesheet(theme_name, suppress_bg_image=True)`, which omits the image at generation time. Do NOT attempt to cancel it with a child override (`visual_area` instance stylesheet, a `background-image: none` rule, or a dynamic property like the removed `carouselActive`): Qt's QSS cascade treats `background-image: none` as "unspecified", so the ancestor `url()` wins on the child per-property and the image survives (verified — a child `background-color` override applied while the image layered on top). `MainWindow._set_bg_suppressed(suppressed)` is the sole authority: it sets `_bg_suppressed`, sets `setAutoFillBackground(not suppressed)`, and re-applies the regenerated stylesheet. `apply_library_state` drives it (`True` for empty + no-book, `False` for has_book) and `ThemeManager._apply_stylesheets` reads `_bg_suppressed` so a theme change in those states keeps the image stripped. `_show_carousel`/`_hide_carousel` must NOT touch background or `autoFillBackground` — suppression is owned by the state machine, not the carousel.

### DO NOT revert `_update_cover_art_scaling` to reading `cover_art_label.height()` for `target_h`
`_update_cover_art_scaling` uses `COVER_AREA_HEIGHT` (a module-level constant in `app.py`) as `target_h`, not `self.cover_art_label.height()`. The live allocated height is transient and state-dependent — it reflects whatever the layout engine allocated at the moment of the call, which can be wrong during any state transition (empty→book, no-cover→cover, panel open/close). The constant decouples scaling from layout state and prevents any cover aspect ratio or state transition from breaking the layout. `cover_art_label` is also pinned with `setFixedHeight(COVER_AREA_HEIGHT)` in `_build_cover_art`. If the window layout ever changes, re-calibrate `COVER_AREA_HEIGHT` empirically by testing covers of various aspect ratios and confirming no bottom clipping in fit mode.

### DO NOT try to expand a widget's height inside the Library settings tab's `QVBoxLayout` — use a MainWindow-level popup instead
`settings_panel` (`main_window_builders.py` `build_settings_panel`) is a **fixed 500px height** widget, and no settings tab has its own `QScrollArea` (this is intentional — no panel in this app has a scrollbar: Stats, Sleep, and Playback don't, and Library must not either). Any widget inside a settings tab that tries to grow taller than the tab's already-fully-claimed vertical budget has nowhere to put the extra height: Qt either refuses to allocate it, or steals it from a sibling with a flexible size policy (visible as the whole tab drifting). Five inline approaches for the Excluded Books expandable list all failed this way — `QScrollArea.maximumHeight` animated alone (grew nothing — `QScrollArea.sizeHint()` is ~`(0,4)` regardless of content), `minimumHeight`+`maximumHeight` driven in lockstep (grew the list but stole space from the folder-list box, visible whole-tab drift), `QSizePolicy.Fixed` on the scroll area (drift became a flicker), and an absolute-overlay child of the section widget itself (every geometry/visibility check passed, nothing rendered live — independently reproduced by a different model attempting the same shape). Full blow-by-blow in NOTES.md "Excluded Books list wouldn't expand..." (2026-06-27). The fix: anything that needs to expand beyond a settings tab's available space must be a popup parented directly to `MainWindow` (see `ExcludedBooksPopup`, `ui/excluded_books.py`, which copies `ChapterList`'s — `ui/chapter_list.py` — architecture exactly: `QGraphicsOpacityEffect` fade only, no size `QPropertyAnimation`, `show()`/`raise_()`/`setGeometry()` from the click handler). It is never a descendant of the tab's layout, so nothing in that layout is ever asked to renegotiate space for it.

### DO NOT verify a settings-panel/tab visual layout bug with headless test scripts alone
For this exact class of bug (widgets inside a settings tab not sizing/showing correctly), every headless Python verification attempt — `processEvents()` loops, manual `QPropertyAnimation.setCurrentTime()`, synthetic `QMouseEvent` delivery, even instantiating `MainWindow()` without actually opening the settings panel through its real animated entry path or switching to the real active tab — reported "looks correct" at some point, including for an attempt that rendered nothing at all in the live app. The gap between a script reporting correct geometry/`isVisible()`/stylesheet state and what the real, live, actually-opened app shows was real and repeated, not a one-off fluke. For any settings-panel/tab layout or paint bug: do not trust headless assertions as a substitute for the user checking the live app. Make the change, ask them to check, and treat their report as ground truth over any script's output.

### DO NOT trust `QComboBox` popup pseudo-state QSS (`::item:hover`/`::item:selected`) or `::down-arrow` on this app's target desktop — paint them manually instead
Confirmed live on the primary dev desktop (KDE Plasma, Wayland, Fusion style — `QApplication.style().objectName() == "fusion"`, no `QT_QPA_PLATFORMTHEME` set): `QComboBox QAbstractItemView::item:hover` / `::item:selected` QSS rules do **not** reach the popup's paint at all. Proven, not guessed — the rule was swapped to a glaring, unmissable `red` and there was **zero visual change** live, ruling out a color/subtlety problem. Reproduced in complete isolation (a bare `QComboBox` outside the rest of the app) via `combo.view().setCurrentIndex(...)`, so it isn't an app-specific event-filter or timing interaction either. The SAME desktop also ignores `QComboBox::down-arrow`'s `image: none` + border-triangle QSS trick — the native style paints its own arrow glyph there regardless, which rendered as a plain light square. Fix for both, in `library.py`: `_ComboItemDelegate` (installed via `combo.view().setItemDelegate(...)`) paints popup item hover/selection backgrounds directly instead of relying on native pseudo-state painting; `_ThemedComboBox` (a `QComboBox` subclass, used in place of a plain `QComboBox()` for `sort_combo`/`style_combo`) overrides `paintEvent` to call `super().paintEvent()` first (background/border/text via the style still work fine — only the popup-item and arrow pseudo-states are broken) then paints its own triangle over just the arrow sub-control's rect. **Do not fill the arrow rect edge-to-edge** — `subControlRect(SC_ComboBoxArrow)` spans the FULL control height including the rounded top/bottom-right corners; a flat fill there squares off those corners (a regression hit and fixed live in the same session — see the `corner_clearance` inset in `_ThemedComboBox.paintEvent`). Do not attempt a QSS-only re-fix for either of these without re-confirming on the affected desktop first — this is a known-failed approach as of 2026-07-09 (see NOTES.md), and per the user this specific area (Library dropdown popup styling) was already attempted and abandoned once before, roughly 3 months prior, undocumented at the time.

### DO NOT let `open_book_detail` retarget or re-animate an already-visible Book Detail Panel
`open_book_detail` (`panels.py`) now no-ops entirely — does not call `load_book`, does not restart the slide-in animation — whenever `book_detail_panel.isVisible()` is already `True`, regardless of which book is showing. `_start_book_detail_entry` is unconditional (always moves the panel off-screen right then slides it back to `x=0`), so calling `open_book_detail` while already open visibly yanks the panel out and back — this is what Library's new Alt+Enter shortcut surfaced (repeatedly pressing it on the already-open book re-triggered the slide every time). Worse without the guard: arrow-navigating to a DIFFERENT book while detail is already open (e.g. after a right-click) and then pressing Alt+Enter would hijack the visible panel onto the new book instead of being blocked — same call path, no protection. The fix is scoped to book-detail-vs-book-detail only; it does **not** touch or weaken `PanelManager.is_overlay_open_or_committed()` (the cross-panel — library/settings/speed/sleep/stats/tags — one-overlay-at-a-time gate), which deliberately still excludes `open_book_detail` for the unrelated reason documented above (it's reachable only from within an already-open library/stats/tags panel, so it never races a *different* panel's opening animation). The user must close the panel via an existing close path (`_close_book_detail_flow` / the panel's own close button) before opening another book's detail.

---

## Pending / Known Debt

- `_cover_cache` has no eviction policy (unbounded LRU). Deferred.
- Theme transitions — long-term path is per-element `@Property(QColor)` animation, but Themes tab QSS complexity makes it non-trivial. `THEME_ANIM_TODO` comments mark instrumented widgets.
- `CoverLoaderWorker` anonymous type objects in stats_panel/tag_manager (path→ID migration context). Deferred to next cover refactor.
- Screen drag 4K→1080p: cover scaling doesn't update without scroll (needs `QWindow.screenChanged`).
- MP3 natural sort (2 before 10) — out of scope for v1.
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
├── shortcuts.py              # ShortcutDispatcher — data-driven global key bindings (Action enum, Binding table, declarative per-binding spam-guards); wired in MainWindow.keyPressEvent. See KEYBINDINGS.md
├── logger_setup.py           # setup_logging() — root fabulor logger, rotating file handler (called first in main.py)
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
    ├── excluded_books.py     # ExcludedBooksSection (toggle line) + ExcludedBooksPopup (MainWindow-level popup, ChapterList's architecture — hover-reveal-eye restore rows)
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

*Last updated: 2026-07-09 Session 1 — Library panel keyboard navigation, plus three follow-up
fixes surfaced by live-testing it. Arrow-key row/column selection, Enter/Space to play,
Alt+Enter to open detail, Tab toggle exclusive to search-field↔list, and a `_prefix` (title-
starts-with) search syntax — see the "Keyboard navigation" bullets under Library Panel above
and `fe4f0f9`. Two new DO-NOT rules from what live-testing found afterward, both added above:
(1) `QComboBox` popup `::item:hover`/`::item:selected` and `::down-arrow` QSS are silently
ignored on the primary dev desktop (KDE Plasma/Wayland/Fusion) — confirmed via a glaring-red
QSS swap that produced zero visual change, and reproduced in total isolation outside the app;
fixed with a custom `_ComboItemDelegate` (popup item paint) and `_ThemedComboBox` (arrow paint,
`f6388d2`/`3e8c241`/`8515605` — includes a corner-squaring regression caught and fixed live in
the same pass). The user confirmed this specific styling gap had already been attempted and
abandoned once before, roughly 3 months prior, undocumented at the time — do not re-attempt a
QSS-only fix without re-confirming on the affected desktop first. (2) `open_book_detail` now
drops any request while the panel is already visible, regardless of book — Alt+Enter on an
already-open book was re-triggering the slide-in animation every press, and arrow-navigating to
a DIFFERENT book while detail was open could hijack the visible panel onto it (`c521c39`). No
automated test coverage added for any of this — it's Qt widget/focus/paint-driven, not a pure
state machine like the seek logic `tests/` already covers; verification was entirely live,
including two rounds of screenshot-based isolation testing for the QComboBox desktop quirk (see
NOTES.md for the full diagnostic trail). `KEYBINDINGS.md` gained a new Library section
correcting its previous "library is mouse-only, not a planned gap" note, now stale.*

*Previously: 2026-07-08 Session 1 — `G`/`P`/`A`/`S`/`Z` shortcuts open Tags/Playback/Stats/
Settings/Sleep, mirroring `L`'s exact shape: open-only (no toggle-closed branch), the same
`COOLDOWN_DROP` (500ms) guard, and gated on `is_overlay_open_or_committed()` before delegating
to each panel's `_open_*_flow`. Each handler's availability check mirrors that panel's real
mouse-reachability: `G`/`A`/`S` (Tags/Stats/Settings — never hidden by `_set_interface_visible`)
gate on `db.get_book_count() > 0`, matching the sidebar's own right-click-open guard; `P`/`Z`
(Playback/Sleep) gate on their trigger button's `isHidden()`, since those buttons are already
hidden whenever no book is loaded. `tests/test_shortcuts.py` extended to cover the five new
bindings plus a no-duplicate-keys check across the whole table. `KEYBINDINGS.md`'s main-window
table and planned-keys note updated to mark all five implemented. No new DO-NOT rule — mirrors
`L`'s already-established shape exactly. (`634eef5`.)*

*Previously: 2026-07-07 Session 3 — per-theme library color pass, alphabetically through the
letter S (`library_bg`/`library_row_one`/`_two`/`library_item_hover_color`/`_alpha`/
`library_title`/`_author`/`_narrator`/`_elapsed`/`_total`/`_percentage`/`library_slider_bg`/
`_fill`/`library_input_bg`/`_text`). Several themes gained these keys for the first time (were
previously falling through to "The Color Purple" inheritance or a generic fallback); others had
existing hover-alpha values corrected (several were tuned down from very high values like 0.5
toward the more typical 0.1–0.25 band). Pure data/tuning pass — no code or architecture change,
no new DO-NOT rule. Remaining letters (T onward) still pending. (`ae4441c`.)*

*Previously: 2026-07-06 (Session 3) — extracted global key handling into `shortcuts.py`
(`ShortcutDispatcher`) and added the `L` → open-library shortcut. `MainWindow.keyPressEvent`
was a hand-written C/T/Q if/elif chain with T's spam-guard as loose `_theme_rotate_cooldown`/
`_theme_rotate_pending` attrs; it's now a one-line delegate to a data-driven dispatcher — an
`Action` enum, a `DEFAULT_BINDINGS` table (passed as a constructor arg so a future Config-backed
source can swap it wholesale — persistence NOT built this task), and a declarative per-binding
`GuardKind` (`NONE` / `COOLDOWN_COALESCE` = T's exact leading-then-coalesced-trailing behavior /
`COOLDOWN_DROP` = L's drop-repeats-during-slide). The dispatcher decides bind-ness + guard ONLY;
each action's app-state gating (C's clickability, Q's no-book state, L's panel/empty checks) stays
in its handler. New `L` is open-only (no-op when the library/any full panel is open or in the empty
state; sidebar-open uses the existing `_open_library_flow` queued flow), so `PanelManager` gained
`is_any_full_panel_visible()` (everything `is_any_panel_visible` checks minus the sidebar; the
latter now delegates to it — single panel list). Explicitly OUT of scope and untouched: `ChapterList`
keys, the four widget-scoped `Escape` handlers, all wheel input, and Q's eventual fate (migrated
as-is with its testing-only comment). New `KEYBINDINGS.md` is the full human-reference input map
(global keys, chapter-list keys, text-field Escapes, mouse/wheel, and the explicit note that the
library view has no keyboard nav). `tests/test_shortcuts.py` pins the three guard behaviors. No new
DO-NOT rule — the migration preserves behavior exactly rather than resolving a hard-won bug. The
audit that preceded this (full pre-migration key inventory) is `review/Review_260706_1.md`.
Follow-up (same session): added a per-binding `Binding.allow_autorepeat` (default False) — fixes a
confirmed live bug where holding `C` re-toggled the chapter dropdown every autorepeat tick
(flicker/fade-restart); `handle_key_event` drops a held-key repeat (returns False, falls through
like an unbound key) unless the binding opts in. Deliberately per-binding, NOT dispatcher-wide, so
the future hold-to-repeat keys sketched in `KEYBINDINGS.md` (skip/seek/volume) can enable it without
a today-introduced regression. All four current bindings keep the default (none should repeat).
The autorepeat fix later moved to `ChapterList.keyPressEvent` too (its own C/Escape close branch was
the real machine-gun source once the focused list stole the held-C repeats — 163 repeats reached the
list vs 2 the dispatcher; see SESSION.md). Second follow-up (same session): fixed a pre-existing
panel-overlap concurrency bug the `L` shortcut surfaced — added `is_overlay_open_or_committed()` and
gated every overlay-open path so only one opens at a time (new DO-NOT rule above; analysis in
`review/Review_260706_2.md`, gate test `tests/test_panel_exclusion.py`).*

*Previously: 2026-07-06 — List-mode author click-to-filter (segmented) + a scrollbar-space fix.
Author click-to-filter now works in List mode too (commit `799bcf9`), reusing the grid mechanism:
`_list_author_layout` is the single source of truth both `_paint_list_row` (draw) and
`_list_author_segment_at` (hit-test) call, so click always matches what's drawn — the extraction was
verified byte-identical to the prior render before the hit-test was added. Separately (`9c20f40`),
List rows now lay out against a stable width (`_row_content_width` = view width − scrollbar extent)
so right-aligned author/time don't shift when filtering toggles the scrollbar. **1-per-row's
time/progress got the same fix (`9f8b06f`) via the generalized `_row_content_width`/`_row_stable_right`.**
New DO-NOT rule ("DO NOT lay out a library row from the live viewport width"). One accepted
limitation in DEBT_INVENTORY.md: the first segment of an elided multi-author is unreachable when
hover-expanded (inherent invade geometry). Also earlier this
session (`d37507c`): List title/author now measured in their real draw fonts (14px bold / 13px
regular), fixing near-miss title overflow; three follow-up attempts at the separate title↔author
visual-gap issue were reverted (full arc in SESSION.md/NOTES.md, both 2026-07-06).*

*Previously: 2026-07-05 — click-to-filter on author/narrator/year added to the library grid
(1-per-row/2-per-row only; commits `5f637dc`..`a7271a5`, see SESSION.md for the full per-commit
narrative and NOTES.md for three bugs worth remembering the shape of). Two "What's Built" lines
under Library Panel. Fixed per-field-type row slots replace the old redistribute-to-fill layout in
`_paint_one_per_row` (a missing field now leaves its row blank instead of letting adjacent fields
shift) — chosen partly to keep hit-zone height a per-view-mode constant rather than a per-book
variable, given how much effort other timing-sensitive bugs in this project (chapter oscillation,
sidebar re-arm) have already cost. Same-day follow-up work (`6847330`/`f778828`/`a7271a5`) extended
toggle-off into a full revert-to-explicit-text mechanism reachable from every angle (re-click, tag
click, library reopen, left-click into the field) and added a Book Detail Panel tag-chip inert
state when its tag is already the active filter (`panels.py:open_book_detail` snapshots the
library's search text through `load_book`'s new `active_search_text` param — no prior plumbing
existed for `BookDetailPanel` to read it). One new DO-NOT rule: every direct `search_field.setText`
must go through the `_programmatic_search_update` guard or `clear_tag_filter_if_active()` — two
different pre-existing unguarded call sites silently broke the revert mechanism the same day it was
introduced, hitting the identical bug shape twice (NOTES.md).*

*Previously: 2026-07-04 Session 1 — idle preloader now warms `_sized_cover_cache` off-thread to
kill the library slide-in stall (first-time LANCZOS-in-`paint()` was the cause). Split `_lanczos_scale`
into a thread-safe `_lanczos_qimage(QImage→QImage)` + a main-thread `QPixmap` tail; `CoverLoaderWorker`
gained a sized mode emitting `sized_cover_loaded(book_id, dev_w, dev_h, QImage)`; new
`BookDelegate.cover_cell_size()` keys the preloader identically to `_get_sized_cover` (verified all
five modes); new `panel_manager.is_any_panel_animating()` + `_preload_paused()` gate; removed the 4s
app-start preload timer (armed once after startup, runs only after 5s idle); `PRELOAD_BATCH_SIZE`
3→4. Separately, scroll position is now preserved across view-mode switches by capturing the topmost
book's `_filtered` index (via the extracted `_first_visible_row()`) and `scrollTo(PositionAtTop)`
after — replacing the raw-pixel-`value()` carry that landed on a different book per mode. New DO-NOT
rule (worker-thread/DPR/keying invariants); "What's Built" cover-loading + `_sized_cover_cache`
descriptions updated; existing `_lanczos_scale` UnsharpMask rule repointed to `_lanczos_qimage`.
Session 2 (theme-hover restyle perf, `_load_svg_pixmap` LRU, redundant-`on_theme_changed` removal —
by Fable 5) added no new DO-NOT rules; writeups in NOTES.md + SESSION.md. Cost/warming-time table and
the first-page-per-mode future idea recorded in NOTES.md.*

*Previously: 2026-07-01 Session 2 — logging infrastructure added (plumbing only). New
`logger_setup.py`: `setup_logging()` configures the `fabulor` root logger once (rotating file
handler, 2 MB × 3, at `platformdirs.user_log_dir("fabulor")`; level from `FABULOR_LOG_LEVEL`,
default WARNING; file sink only, no console handler), called first thing in `main.py`. Startup
message logged at WARNING (not INFO) so it lands at the default level. Silent module-level
`logger` instances added to `player.py`/`app.py`/`ui/theme_manager.py` — no call sites yet, those
land incrementally. New "Logging" subsystem entry under What's Built; `logger_setup.py` added to
the file tree. No new DO-NOT rule (pure additive plumbing, no hard-won bug). Windows-port note
recorded in NOTES.md: log dir uses the one-arg `user_log_dir("fabulor")` form vs the two-arg
`user_data_dir("fabulor", "fabulor")` used elsewhere.*

*Previously: 2026-06-27 Session 3 — is_missing flag fixes the Excluded Books ping-pong; arrow
moved out of the toggle label. mark_books_missing/_mark_book_missing used to write is_excluded=1
for a book confirmed gone from disk — indistinguishable from a real user-trash, and the popup's
eye-click restore (set_book_excluded(path, False)) would put a file-less book back in the library,
which got re-flagged missing the next time the user tried to load it (infinite loop). Added a new,
independent is_missing column: self-heals on upsert (the opposite of is_excluded's stickiness),
fenced into every visibility query alongside is_deleted/is_excluded (get_visible_book_count,
get_all_books, has_books_with_progress, has_finished_books, get_finished_book_data,
get_all_cover_paths, get_visible_book_paths_under — found via a failing test when the first pass
only fixed get_excluded_books), folded into the existing _is_archived/is_archived checks in
stats_panel.py/book_detail_panel.py/tag_manager.py (no new icon — explicitly deferred, no
gravestone.svg asset exists yet). Separately, ExcludedBooksSection's always-visible ▼/▲ arrow was
split into its own inert QLabel (no click handler at all) shown only while the popup is open,
centered between the header and the now-arrow-less, still-right-aligned count label — matching
ChapterList's precedent where the arrow is pure state, never a second click target. New CLAUDE.md
rule consolidated three flags' semantics in one place (was two, now corrected for three).*

*Previously: 2026-06-27 Session 2 — Excluded Books list rebuilt as a MainWindow-level popup.
The inline collapsible-section design described below (one-line rows expanding inside the Library
tab's own layout) never worked — five distinct attempts to grow it within the settings panel's
fixed 500px box all failed (drift, flicker, or rendered nothing; full history in NOTES.md/SESSION.md
2026-06-27 Session 2). Rebuilt as `ExcludedBooksPopup`, parented directly to `MainWindow` and copying
`ChapterList`'s architecture exactly (opacity fade only, no size animation, `show()`/`raise_()`/
`setGeometry()` from the click handler) — see the two new CLAUDE.md rules above. `ExcludedBooksSection`
is now only the toggle line; the list itself is the popup. Two new CLAUDE.md rules added (don't
expand a settings-tab widget inline; don't trust headless scripts for this bug class).*

*Previously: 2026-06-27 Session 1 — Excluded Books restore UI + sticky exclusion + reparse lock fix.
Made `is_excluded` sticky through force rescans (both upserts now `CASE WHEN books.is_excluded`,
reversing the old "rescan resets both flags" behavior) and added a collapsible **Excluded Books**
section to the Library settings tab (`ui/excluded_books.py`, `db.get_excluded_books`) as the new
restore path — compact one-line rows with a hover-reveal eye (copies `_HistoryRow`'s slide anim,
`eye.svg`), restoring via `set_book_excluded(path, False)`. Restored the Naming pattern UI
(repositioned after Manage folders, folder box halved) and fixed a real `reparse_library` data-loss
bug — it was the one write path that ignored `title_locked`/`author_locked` and clobbered locked
metadata library-wide on a naming-pattern click; now CASE-WHEN-guarded. Four CLAUDE.md flag-reset
references corrected; two new rules (sticky `is_excluded`, `reparse_library` lock guard). Tests:
`test_excluded_books.py`, `test_reparse_library.py`. (Earlier this period: 2026-06-26 force-rescan
missing-book detection + unload-on-missing, already documented above.)*

*Previously: 2026-06-24 Session 1 — fixed library grid cover thumbnails crumbling at small sizes.
Two real bugs landed in `scanner.py` (cover-discovery only matched exact filenames, missing 98% of
available external covers; bilinear+low-quality-JPEG thumbnail resampling capped at 226×344). Both
alone made no visible in-app difference — the actual bottleneck was a second, paint-time bilinear
downscale in `BookDelegate._draw_cover`. Fixed with a per-(book_id, cell-size) pre-scaled pixmap
cache (`_sized_cover_cache`/`_get_sized_cover` in `library.py`) so paint time is a near-1:1 blit, the
resize itself done via PIL LANCZOS + a tuned `UnsharpMask` pass to recover contrast LANCZOS trades
away versus bilinear's edge overshoot. Added one new CLAUDE.md rule (scale-mode + sharpen-strength
traps in `_get_sized_cover`/`_lanczos_scale`). Full writeup, including two corrected
premature-success claims, in NOTES.md.*

*Previously: 2026-06-19 Session 4 — split `bookmark_body`/`bookmark_icon`/`tassel_cord`/
`tassel_head`/`tassel_fringe` into independently overridable theme keys (GROUP 9, themes.py), with
the fallback chain: `tassel_cord`/`tassel_head` → `tassel_fringe` → `accent_light`;
`bookmark_body`/`bookmark_icon` keep their original derivations as fallbacks (accent desaturated
35% / accent_dark→bg_main). Fixed a `tassel_fringe` fallback bug (was reading
`slider_overall_fill` instead of `accent_light`) found while wiring this up. Separately, fixed a
real streak-count bug — but the first attempt at it was wrong and reverted. A user testing
`day_start_hour` found the streak grid and streak number disagreeing. First diagnosis (wrong):
assumed the grid was the bug, made it start-date only to match `get_streaks`/Day tab. User caught
this — a session genuinely spanning the day_start_hour boundary SHOULD light two grid cells
(that's correct, matches reality); the actual bug was that `get_streaks` (the streak count/label)
only credited the session's start-date, never its end-date, so the number undercounted relative to
the cells. Reverted the grid change; fixed `get_streaks` instead to union session end-dates into
its day-set, mirroring `build_streak_grid_cache`'s three sources (start, end, finished) exactly.
`get_active_periods` (Day/Week/Month nav) deliberately stays start-only — full session-splitting
for Day/Week/Month was scoped out as too large a change for this. Added one new CLAUDE.md rule.*

*Previously: 2026-06-19 Session 3 — added a decorative dangling tassel to `TasselOverlay` (cord
looping vertically into a bound head, fanning into a fringe; idle micro-sway + decaying activation
kick). Went through three live correction rounds against the running app: a "pendulum with a
circle" first draft was rebuilt into a real tassel anatomy; a cursor/click-region mismatch (hand
cursor over dead space) was fixed via a shared `_in_hit_region()`; the cord's Bezier was corrected
twice (bulge, then approach angle) to read as a draped loop landing vertically in the head rather
than a straight or diagonal line. Geometry invariants (`_tab_rect`, 7px peek, slide targets)
verified numerically at every round via headless offscreen-Qt scripts. Added one new CLAUDE.md
rule (cursor/click region must share one source of truth).*

*Previously: 2026-06-19 Session 2 — fixed a percentage-label tween oscillation (truncate-vs-round mismatch
against the live tracker, not a timing race — see CLAUDE.md rule above and NOTES.md); fixed a
Timeline tassel click hang (caller didn't check `TasselOverlay.is_busy` before independently
triggering its own side effect — see CLAUDE.md rule above); added a streak-grid catch-up reveal that
dims the newest changed day-cells and pops them in one-by-one in lockstep with the counter's leg-2
tick (leg 2 is now a discrete per-day step timer, not a continuous tween); removed the
`_DEBUG_STREAK_*_OVERRIDE` test hooks. Added two new rules above.*

*Previously: 2026-06-18 — Timeline tab visual rework: `StreakGrid` longest-run fill/border roles
swapped (derived tint fill, accent border; `streak_grid_outline`/`streak_grid_dot` replace the old
`streak_longest_fill`/`streak_finished_dot` theme key names); grid reveal/conceal transition is now
`_grid_cell_anim` style `"pop"` (scale + alpha, not plain fade) shared by `HourlyHeatmap`/`StreakGrid`;
top/gutter label cascades reworked to per-label opacity with true mirrored enter/exit (fixed a
clamping bug that silently broke the exit direction — see CLAUDE.md rule above and NOTES.md); tassel
icon swap deferred until fully retreated, recolored, and `calendar.svg` replaced with `fire.svg`;
added an animated, two-leg, restart-persisted streak counter with a dedicated panel-reopen
catch-up path. Added three new rules above (label-cascade window asymmetry, streak-previous
persistence, panel-reopen catch-up exception).*

*Previously: 2026-06-13 (Session 3) — chapter-seek precision rework: split the overloaded `_CHAPTER_BOUNDARY_EPSILON` into three measured constants (`_CHAPTER_WALK_TOLERANCE` 0.5, `_EMBEDDED_CHAPTER_SEEK_OFFSET` −0.09, `_PAUSED_SEEK_UNDERSHOOT_COMP` 0.37); revised all chapter-nav rules; removed the embedded-M4B native-click exception (embedded chapter-list clicks now route through `Player.activate_chapter_index` → `seek_async`, fixing the chapter-UI freeze). Corrected the disproven "~0.25s short" rationale (mpv overshoots ~0.09s playing, undershoots ~0.37s paused).*

*Previously: 2026-06-13 — replaced the stale "Implemented Features (complete)" section with a full "What's Built" audit (5-agent factual sweep over app.py, player.py, session_recorder.py, config.py, db.py, scanner.py, cover_manager.py, library_controller.py, and all ui/ panels). Corrections vs. the old section: cover preview is 208×266 (not 205×270); StreakGrid longest-run uses a derived `_longest_fill` color with `streak_longest_fill`/`streak_finished_dot` per-theme overrides (not an `accent.lighter(150)` border / `streak_longest_border`); `write_session`/`write_book_event` still dual-write `book_path` + `book_id` (the old section claimed `book_path` was no longer written). Added previously-undocumented subsystems: app-shell UI states/wiring, carousel, controls/widgets, audio controls, icon utils, context menu, panels, full DB query inventory, scanner internals, cover manager, config key map, checkpoint recovery.*
