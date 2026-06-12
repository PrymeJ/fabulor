# Validation Runbook — Finished-Book Flow (B2) + Streak-Grid (B1)

> _Written 2026-06-12 against commit `4b3d8be`. Covers DEBT_INVENTORY.md items B1, B2, B3 — the two "blocks mandatory work" validation gaps. Hands-on; check each box. When a step disagrees with its expectation, capture the DB-query output next to what the UI showed (see "If something disagrees" at the end)._

---

## Setup (do this once, before anything)

- [ ] **Run from a terminal**, not a launcher — the session recorder prints breadcrumbs to stdout you'll watch live:
  ```bash
  source fabulorenv/bin/activate && python main.py
  ```
  (If an `entr` dev-loop is already running, check `ps aux` first — don't double-launch.)

- [ ] **Back up the DB** — several steps irreversibly mutate `book_events` / `listening_sessions` / `streak_grid_cache`:
  ```bash
  cp ~/.local/share/fabulor/library.db ~/.local/share/fabulor/library.db.pretest
  ```
  Restore between test blocks if you want a clean slate: `cp …/library.db.pretest …/library.db` (app must be closed).

- [ ] **Keep these breadcrumbs in view** (printed by `session_recorder.py`):
  - `[open_session] book='…' clock=HH:MM:SS pos=… (…%)` — a session opened
  - `[pause_session] listened_so_far=…min` — paused, 3-min timeout armed
  - `[close_session] book='…' …→… (…%) listened=…min` — flushed to DB (≥60s)
  - `[close_session] discarded — listened=…s < 60s threshold` — **not** written

- [ ] **DB ground-truth queries** (DB at `~/.local/share/fabulor/library.db`; set `DB=~/.local/share/fabulor/library.db`):
  ```bash
  # finished events — book_id must be non-NULL:
  sqlite3 "$DB" "SELECT id,book_id,book_path,event_type,event_time FROM book_events WHERE event_type='finished' ORDER BY event_time DESC LIMIT 10;"
  # streak cache — THIS is what the grid renders:
  sqlite3 "$DB" "SELECT date,listened FROM streak_grid_cache WHERE listened=1 ORDER BY date DESC LIMIT 20;"
  # raw sessions (cross-check a cell):
  sqlite3 "$DB" "SELECT id,book_id,session_start,session_end,listened_seconds FROM listening_sessions ORDER BY session_start DESC LIMIT 20;"
  # live checkpoint (exists only mid-session):
  ls -la ~/.local/share/fabulor/session_checkpoint.json 2>/dev/null || echo "no live checkpoint"
  ```

**Key thresholds (from source, so expectations are exact):**
- EOF fires when `pos >= duration - 1.5s` (via the pause observer, NOT an `end-file` event — `keep_open='always'`). `player.py:183`.
- A session is written only if `listened >= 60s` (or `at_eof=True`). `< 60s` is silently discarded. `session_recorder.py:111,216`.
- Checkpoint written every **30s** while a session is open. `session_recorder.py:47`.
- A midnight-spanning session marks **both** its start-day and end-day streak cells (intentional).

---

## Block A — Finished-book flow (B2)

### A1. Natural EOF writes the finished event
- [ ] Play a book through to its true end (let `pos` reach `dur - 1.5`; don't just seek near the end and stop short — a stall at `dur - 3` will NOT finish).
- [ ] **Expect:** sticky banner "Marked as finished." with **revert** + **close (✕)** buttons; play icon → restart.
- [ ] **DB:** finished-events query shows a new row, `book_id` **non-NULL**, correct `book_path`.

### A2. EOF arrival mode — playing vs. paused-at-end
- [ ] Reach EOF by **playing through** → banner appears.
- [ ] Separately: seek to the last ~1s and let it hit EOF while effectively paused → banner appears.
- [ ] **Expect:** banner + finished write in **both** arrival modes (the write fires from `_update_ui_sync`'s `is_eof` branch regardless).

### A3. Revert
- [ ] With the banner up, click **revert**.
- [ ] **Expect:** banner dismisses; book returns to in-progress in the library.
- [ ] **DB:** the finished row from A1 is **gone** (`unfinish_book` deleted it).
- [ ] If it was the **only** finished book: the **Finished** entry disappears from the sort dropdown, and the Finished filter no longer lists it.

### A4. Re-finish — dedup count (Pass 5 #1, the important one)
- [ ] After A3, finish the **same** book again (reach EOF).
- [ ] **DB:** `sqlite3 "$DB" "SELECT COUNT(*) FROM book_events WHERE book_id=<ID> AND event_type='finished';"` → **exactly 1** (the first was reverted, this is the second).
- [ ] **Sub-case (no revert):** with the book still loaded and finished, pause → resume → reach EOF again (or sit at EOF). **DB count stays 1** — `_eof_event_written` only clears on `load_book`, so a re-EOF on the same loaded book must NOT write a second row.

### A5. Close (✕) ≠ revert
- [ ] Finish a book, dismiss the banner with the **close (✕)** button (not revert).
- [ ] **Expect:** book stays **finished** (DB row intact); banner gone.
- [ ] **Expect:** no lingering revert affordance; a later unrelated action cannot revert this book.

### A6. EOF banner dismiss triggers — test each individually
For each, finish a book to bring the banner up, then perform the trigger; **expect the banner to retire silently and the book to stay finished** (dismiss ≠ revert):
- [ ] **Load a different book** from the library.
- [ ] **Seek within** the finished book (rewind/scrub away from EOF).
- [ ] **Restart** (click the restart icon).
- [ ] **Start the sleep timer.**
- [ ] **Add / remove / rescan a folder** (scan takes over the banner).

### A7. App-close with banner showing (B3)
- [ ] Finish **book A** (banner up) → **close the app entirely**.
- [ ] Reopen → **load book B**.
- [ ] **Expect:** NO revert affordance pointing at A anywhere. (Pass 5 concluded `closeEvent` doesn't clear `_eof_book_id` but it's benign because the process exits — this step confirms benign-in-practice.)
- [ ] **If any revert UI appears on reopen → that's a finding.** Note it.

### A8. Finished library filter/sort + dropdown gating
- [ ] After finishing, open the library Finished filter → book appears with the **correct finished date**.
- [ ] Toggle the **only** finished book between finished/in-progress (finish → revert) → the **Finished** dropdown entry appears/disappears accordingly.
- [ ] Same for **Progress**: with exactly one in-progress book, confirm the Progress entry appears; remove its progress → it disappears.

---

## Block B — Streak-grid (B1)

### B1. Day-boundary attribution matches the stats panel
- [ ] Set day-start-hour to something **non-midnight** (Settings → … day start).
- [ ] Listen to a session that crosses **that** boundary (e.g. if day-start = 4am, listen 3:50→4:10).
- [ ] **Expect:** the grid attributes it to the correct adjusted day, and the **stats panel Day/Week tab** agrees (both read `config.get_day_start_hour()`).
- [ ] **DB:** `streak_grid_cache` and the stats day-breakdown reference the same adjusted date.

### B2. Midnight-spanning session marks BOTH cells
- [ ] Listen across the boundary so `session_start` and `session_end` fall on different adjusted days.
- [ ] **Expect:** **TWO** grid cells light up (start-day AND end-day), not one.
- [ ] **DB:** two `listened=1` rows in `streak_grid_cache` for the two dates.
- [ ] Delete that session (per-session delete) → **both** cells clear (if no other session backs them).

### B3. Per-session delete updates the grid immediately (the Pass 7 fix — History panel path)
- [ ] Open the History panel (book detail), delete a single session via per-session delete.
- [ ] **Expect:** the streak cell for that day updates immediately (the row-collapse animation runs, then `history_deleted` fires).
- [ ] **DB:** `streak_grid_cache` for that date recomputed (still `1` if other sessions remain that day, `0` if it was the last).

### B4. Delete the day's only session → streak breaks; longest recalculates
- [ ] Pick a day with exactly one session that is **inside the current longest run**.
- [ ] Delete it.
- [ ] **Expect:** that cell goes empty; the streak visibly breaks at that day.
- [ ] **DB:** `get_streaks` recomputes — `sqlite3` the sessions, or just confirm the grid's "longest" highlight (the `accent.lighter(150)` border) moves to whatever the new longest run is. The in-widget invariant is `len(_longest_dates) == get_streaks()['longest']`; if the highlighted run length and the streak-info number disagree, that's a finding.

### B5. day_start_hour change rebuilds the whole grid
- [ ] With existing sessions present, **change** the day-start-hour in Settings.
- [ ] **Expect:** entire grid rebuilds (`_on_day_start_hour_changed` does full reset+build); a session near the old boundary re-attributes to a different cell.
- [ ] **Expect:** grid and stats panel still agree under the new hour.

### B6. Crash recovery — contributes to the right day
- [ ] Start a session, listen **> 60s**, wait for at least one `[checkpoint]`/30s tick (confirm `session_checkpoint.json` exists).
- [ ] **Kill the app hard** (`pkill -9 -f "python main.py"`) — no clean close.
- [ ] Reopen.
- [ ] **Expect:** on launch, the recovered session is written; its streak cell appears for the **day the session started** (the checkpoint preserves `session_start`).
- [ ] **DB:** new `listening_sessions` row + matching `streak_grid_cache` cell; `session_checkpoint.json` is **deleted** after recovery.

### B7. Crash recovery — threshold + double-apply boundaries
- [ ] **< 60s checkpoint:** force a checkpoint to exist representing `< 60s` listened (kill shortly after a 30s tick but before 60s of real listening). Reopen → **no** session written, checkpoint discarded (mirrors the live 60s rule).
- [ ] **Double-apply guard:** kill the app right at a clean-close moment (close triggers a write thread). Reopen → confirm **one** session row for that listening period, not two (a recovered checkpoint + an in-flight close must not both land).

---

## Block C — Combined interaction (why these are tested together)

### C1. Finish a book, delete its only session for a day → grid updates, finished survives (Pass 5 #7)
- [ ] Finish a book; ensure it has exactly one session for some day.
- [ ] Delete that session (per-session delete).
- [ ] **Expect:** streak cell for that day updates (clears if it was the last).
- [ ] **DB:** the **finished** `book_events` row is **untouched** — finished status does NOT depend on session-row existence.

### C2. Revert a finished book → sessions + streak cells untouched (the other half of independence; Pass 7 #4)
- [ ] Finish a book that has existing sessions; revert it.
- [ ] **Expect:** the finished `book_events` row is gone, but **`listening_sessions` rows and `streak_grid_cache` cells are unchanged** (revert only deletes the finished event, never sessions).

### C3. Pass 7 fix — the actual fan-out path (stats panel open, delete from book-detail over it)
- [ ] Open the **stats panel**, go to the **Timeline tab**, find a filled cell.
- [ ] From a stats row, open **book detail over the stats panel**.
- [ ] In book detail's History, delete that day's **only** session.
- [ ] Close book detail back to the Timeline tab.
- [ ] **Expect:** the cell is now empty **without a tab switch** (`history_deleted` → `stats_panel.refresh_all` + `library_panel.refresh`).
- [ ] **If the cell only updates after you change tabs → the Pass 7 fix regressed.** Finding.

### C4. Control — delete with stats panel CLOSED, then open (separates "cache right" from "widget refreshed")
- [ ] With the **stats panel closed**, delete a session from the standalone History panel.
- [ ] Then open the stats panel → Timeline.
- [ ] **Expect:** grid is correct (the cache was fixed transactionally in `delete_session`, independent of any open widget). This isolates a failure: if C3 is stale but C4 is correct, it's the *signal/refresh* that's broken, not the cache.

---

## If something disagrees

Capture the pair: **what the UI showed** + **the DB query output at that moment**. The decisive question is always *"is the cache wrong, or is the open widget stale?"* —
- `streak_grid_cache` row **wrong** → data-layer bug (`delete_session` / `write_session` / `_update_streak_grid_cache_for_date`).
- `streak_grid_cache` row **right** but the **grid shows stale** → refresh/signal bug (the `history_deleted` fan-out or a missing `_refresh_time`).
- finished-event **count** wrong → `_eof_event_written` dedup or `unfinish_book` targeting.

Paste that UI-vs-DB pair and the failing step number; that's enough to pinpoint the layer.

---

## Result log (fill as you go)

| Step | Expected | DB / breadcrumb actual | Pass / Fail | Notes |
|------|----------|------------------------|-------------|-------|
| A1 | | | | |
| A2 | | | | |
| A3 | | | | |
| A4 | | | | |
| A5 | | | | |
| A6 | | | | |
| A7 | | | | |
| A8 | | | | |
| B1 | | | | |
| B2 | | | | |
| B3 | | | | |
| B4 | | | | |
| B5 | | | | |
| B6 | | | | |
| B7 | | | | |
| C1 | | | | |
| C2 | | | | |
| C3 | | | | |
| C4 | | | | |
