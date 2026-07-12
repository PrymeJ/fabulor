# Fabulor — Input Bindings Reference

Human-reference inventory of every keyboard, mouse, and wheel binding in the app,
grouped by scope. Accurate as of the `shortcuts.py` migration (feat/shortcuts-module).

Global keys are dispatched by `src/fabulor/shortcuts.py` (`ShortcutDispatcher`, wired in
`MainWindow.keyPressEvent`). Everything else listed here is handled directly by the
widget that owns it and is **not** part of that module — it's documented here only so
this file is a complete map.

**Focus-ownership invariant (added 2026-07-11):** exactly one widget owns keyboard focus at
a time, and the global dispatcher only acts on a key when the focus owner is `MainWindow`
itself or nothing panel-local currently holds real focus (`MainWindow._focus_allows_global_
shortcuts`). Whenever a panel/overlay is open, its own widget owns focus for the whole time
it's open (`PanelManager._claim_panel_focus` on open, `_release_panel_focus` on close) — so
a key that widget doesn't want (e.g. `Up`/`Down` inside a text field) is simply dropped, not
forwarded to global shortcuts, and a key typed while editing never leaks out to change
volume/speed/etc. This is why, below, Library/Chapter-list keys "shadow" the global ones
while open — it isn't incidental first-refusal, it's the enforced invariant. See CLAUDE.md's
"Keyboard focus ownership" rule for the full architecture and the Qt gotchas behind it.

---

## Main window (global keys)

Dispatched through `shortcuts.py`. Each key fires an action only when the surrounding
app state allows it (that gating lives in each action's handler, not in the dispatcher).

| Key | Action | When it does something | Guard (what a user notices) |
|-----|--------|------------------------|-----------------------------|
| `C` | Open/close the chapter list | Only when the current book has 2+ chapters. Pressing it again while the list is open closes it. | None — every press acts immediately. |
| `T` | Rotate the theme | Always (subject to the theme system's own rules: it defers while a panel is open and fires ~3s after the panel closes; it's inert in exclusive cover-art mode). | Throttled: the first press rotates immediately, then rapid repeat presses are collapsed into **one** further rotation ~2s later. Holding/spamming `T` yields about one change every 2 seconds — the last press always eventually lands. |
| `Q` | Rotate the empty-state quote | Only in the empty/no-book state (no book loaded and the quote is showing). Inert once a book is playing. | None. **Testing-only** — flagged for removal before release. |
| `L` | Open the library | Only when the library is browsable (not the empty-library state) and no full panel is already open. If the library is already open, `L` does nothing (it does not close it). If only the sidebar is open, `L` opens the library through the normal sidebar-close-then-open flow. | Repeat presses during the open animation are ignored (not queued) — you can't stack multiple opens of the same panel. |
| `G` | Open Tags | Only when at least one book is indexed, and no full panel is already open. Does not close the panel if it's already open. | Same as `L` — repeats during the open animation are ignored. |
| `P` | Open Playback (speed) | Only when a book is loaded (the Playback button is hidden otherwise), and no full panel is already open. Does not close the panel if it's already open. | Same as `L`. |
| `A` | Open Stats | Only when at least one book is indexed, and no full panel is already open. Does not close the panel if it's already open. | Same as `L`. |
| `S` | Open Settings | Only when at least one book is indexed, and no full panel is already open. Does not close the panel if it's already open. | Same as `L`. |
| `Z` | Open Sleep timer | Only when a book is loaded (the Sleep button is hidden otherwise), and no full panel is already open. Does not close the panel if it's already open. | Same as `L`. |

`G`/`P`/`A`/`S`/`Z` all share `L`'s shape exactly: **open-only** (pressing the key again while
its own panel is already open does nothing — these keys never close a panel, only the sidebar's
own buttons and the panel's own close controls do that) and gated by the same one-overlay-at-a-time
rule (`is_overlay_open_or_committed`) as every other panel-open path.

### Transport / player keys (added 2026-07-11)

Wired through the same dispatcher; each fires the **same method** the on-screen button or
wheel already uses (no parallel playback logic). All use `GuardKind.NONE` (fire on every
press). These keys act on the player, so most are inert with no book loaded.

| Key | Action | When it does something | Notes |
|-----|--------|------------------------|-------|
| `Space` | Play/pause toggle | Whenever a book is loaded. | Same method as the play/pause button (`toggle_play_pause`). Transport buttons are `Qt.NoFocus` so a focused button can't swallow `Space`. Correctly inert whenever any panel/overlay is open — the focus-ownership invariant above means `Space` belongs to whatever panel-local widget currently has focus (the library list, the chapter list, a text field, etc.), never to global shortcuts, while one is open. |
| `Up` / `Down` | Volume +5 / −5 | Book loaded (volume inert otherwise). | Same step path as the cover-area wheel (`_nudge_volume` → volume slider). **Repeats on hold.** |
| `Left` / `Right` | Seek back / forward (`skip_duration`) | Book loaded. | Same method as the rewind/forward button **left-click** (`handle_rewind(long_skip=False)` / `handle_forward(long_skip=False)`, `long_skip=False` is the default). **Repeats on hold** (no throttle — same small-step category as volume). Added 2026-07-12, alongside the Shift/Ctrl-modified variants below. |
| `Alt`+`Up` / `Alt`+`Down` | Speed up / down (± configured increment, clamped 0.25×–8.0×) | Book loaded. | Same step path as the speed-button wheel (`_nudge_speed` → `_set_speed`). **Repeats on hold**, self-throttled to one step per `_SPEED_NUDGE_THROTTLE_S` (0.12s, hand-tunable) so held repeat doesn't blow past a value at 0.05 increments; a single tap always applies one step. |
| `Shift`+`Left` / `Shift`+`Right` | Long skip back / forward (`long_skip_duration`) | Book loaded. | Same method as the rewind/forward button **right-click** (`_nudge_long_skip` → `handle_rewind(long_skip=True)` / `handle_forward(long_skip=True)`), including the undo capture. **Repeats on hold**, self-throttled to one step per `_LONG_SKIP_THROTTLE_S` (0.45s, hand-tunable, own constant — NOT derived from speed's) since each repeat is a large skip, not a small continuous adjustment; a single tap always applies one step. |
| `Ctrl`+`Left` / `Ctrl`+`Right` | Previous / next chapter | Book loaded with chapters. | Same method as the chapter nav buttons and the progress-slider wheel (`_nudge_chapter` → `handle_prev` / `handle_next`). **Repeats on hold**, self-throttled to one step per `_CHAPTER_NUDGE_THROTTLE_S` (0.45s, hand-tunable, own constant) since each repeat is a whole chapter, not a small continuous adjustment; a single tap always applies one step. |
| `m` | Mute toggle | Book loaded. | Minimal, built on the volume-slider path (no dedicated mute control exists): stores current volume, drops to 0, restores on next press. Moving the slider off 0 while muted counts as unmuted. |
| `u` | Undo last seek | Only while the on-screen undo affordance is showing (no-op otherwise). | Same method + visibility gate as clicking the undo overlay (`_perform_undo`, gated on `undo_overlay.isVisible()`). |

`Shift`+`Up`/`Down` and `Ctrl`+`Up`/`Down` are deliberately left unbound.

Modifier matching (changed 2026-07-11): a bare-key binding now matches **only** an
unmodified press, so `Ctrl+T` no longer rotates the theme (bare `T` still does). This was a
necessary consequence of adding real modifier support — `Up` (volume) and `Alt+Up` (speed),
and `Shift+Left` / `Ctrl+Left`, must be told apart. Matching masks `event.modifiers()` to
Shift/Ctrl/Alt only, so a keypad/platform-set flag on an arrow key can't defeat a bare-key
binding.

---

## Chapter list (active only while the chapter dropdown has keyboard focus)

Handled by `ChapterList.keyPressEvent` (`ui/chapter_list.py`). The dropdown takes real
Qt focus when it opens, so these keys apply only while it's up; when it closes, focus
returns and the global keys above are live again. Unrecognised keys are swallowed while
the list is focused.

| Key | Does |
|-----|------|
| `Up` / `Down` | Move the selection up/down the chapter list. |
| `Left` / `Right` | Expand / collapse the list — only when there are more chapters than fit in the default view. |
| `Enter` / `Return` | Jump to the selected chapter (without forcing playback). |
| `Space` | Jump to the selected chapter **and** start playing. |
| `Escape` or `C` | Close the chapter list. |
| `0`–`9` | Type a chapter number to jump to it (buffered ~800ms after the last digit). Whether it matches by chapter index or by name — and whether it auto-plays — follows the chapter-digit settings. |

---

## Text fields (Escape-to-cancel)

Each of these is a small, self-contained `Escape` handler scoped to that one input while
it has focus. They are not global shortcuts and are not part of `shortcuts.py`.

| Field | `Escape` does |
|-------|---------------|
| Library search field | Clear the field and drop focus. |
| Sleep-timer custom-time input | Clear the field and drop focus. |
| Book-detail metadata edit (title/author/narrator/year) | Cancel the edit without saving. |
| Tag-manager tag-name edit | Revert the name and drop focus. |

---

## Mouse and wheel

Handled in `MainWindow` (`_on_drag_area_pressed`, `wheelEvent`) and the chapter list.
Behavior unchanged by the shortcuts work, though the cover-area volume and speed-button
wheel now share their ±step logic with the `Up`/`Down` and `Alt`+`Up`/`Down` keys via the
extracted `_nudge_volume` / `_nudge_speed` methods (one implementation, two entry points).

| Gesture | Over | Does |
|---------|------|------|
| Left-click | Cover / drag area | Closes any open panel; otherwise toggles play/pause. (No-op in the empty-library state.) |
| Right-click | Cover / drag area | Opens the sidebar. (Suppressed briefly right after a file dialog closes; requires books to be indexed.) |
| Wheel | Cover area | Volume ±5. |
| Wheel | Speed button | Playback speed ± the configured increment (clamped 0.25×–8.0×). |
| Wheel | Progress slider | Previous / next chapter. |
| Wheel | Chapter-progress slider | Seek within the current chapter (with undo capture). |
| Left-click | Chapter list row | Jump to that chapter (without forcing playback). |
| Right-click | Chapter list row | Jump to that chapter and start playing. |

---

## Library view (added 2026-07-09, extended through 2026-07-10)

Handled directly by `LibraryPanel`/`BookDelegate` (`ui/library.py`) — not part of
`shortcuts.py`. The list (`_list_view`) takes keyboard focus as soon as the panel opens
(no click or Tab needed first).

| Key | Does |
|-----|------|
| `Up` / `Down` | Move the book selection. Native `QListView` handling, scrolled into view via an explicit `scrollTo()` in every view mode (`setAutoScroll(False)` disables Qt's native scroll-follow app-wide — see the `PageUp`/`PageDown`/`Home`/`End` row below for the same fix applied to those keys). |
| `Left` / `Right` | Move the selection by one column — in the three grid view modes (2-per-row, 3-per-row, Square). No-op in 1-per-row (no adjacent column). In **List mode**, Left/Right instead step the keyboard-selected row's title/author expand state — see the dedicated subsection below. |
| `PageUp` / `PageDown` | Jump the selection roughly a page's worth of rows (native Qt distance, unexamined/un-overridden — see `TODO.md`), scrolled into view. Added 2026-07-10 (`52b7abb`) — these keys were never actually non-functional; native Qt was already moving the selection correctly, but `setAutoScroll(False)` silently prevented the viewport from following it, so the jump was invisible. Confirmed via a live `FABULOR_LOG_LEVEL=DEBUG` focus trace before fixing. |
| `Home` / `End` | Jump the selection to the first / last row, scrolled into view. Same 2026-07-10 fix and same root cause as `PageUp`/`PageDown` above. |
| `.` (period) | Jump the selection straight to the exact middle row (`row_count // 2`), scrolled into view. Added 2026-07-10 (`6acb512`). Confirmed unbound everywhere else (list keys, sort/view-mode shortcuts, `ShortcutDispatcher`, search field) before choosing it. |
| `Enter` / `Return` | Play the selected book (same as left-click). |
| `Alt`+`Enter` / `Alt`+`Return` | Open Book Detail for the selected book, on the Stats tab (same as right-click). No-op if a Book Detail panel is already open — see below. |
| `Space` | Play the selected book (same as `Enter`). |
| `Tab` (list or "nothing focused") | Moves focus to the search field. |
| `Tab` (search field focused) | Moves focus to a "nothing focused" state — NOT back to the list. See "nothing focused" row below. This is a two-state `search field ↔ nothing` cycle (changed 2026-07-10 from an earlier `search field ↔ list` toggle — tabbing directly onto the list used to call `scrollTo(currentIndex())`, and since mouse hover also sets `currentIndex()`, that silently scrolled the list if the mouse happened to be hovering a partially-visible book when Tab was pressed). Tab never reaches the sort combo, view-mode combo, sort-direction button, or Back button. |
| Any arrow, `PageUp`/`PageDown`/`Home`/`End`, `.`, `Enter`/`Return`/`Space`+`Alt`, or a sort/view-mode letter/digit (**"nothing focused" state**) | Moves focus to the list AND performs that key's action in the same press — no wasted keypress "waking up" the list first. Every key the list itself handles is forwarded this way (`LibraryPanel._LIST_KEY_HANDLED_KEYS` is the single source of truth for this set, shared with `_list_key` so the two can't drift apart again — they did once, 2026-07-10, for `PageUp`/`PageDown`/`Home`/`End`, caught and fixed same-session). |
| `Up` / `Down` (search field focused) | Move the book selection by one and hand focus to the list immediately. `Left`/`Right` in the search field are unaffected (normal text-cursor movement). |
| `Escape` (search field focused) | See "Text fields" above — clears the field and drops focus. |
| `t` / `a` / `r` / `d` / `y` / `p` / `f` (list focused) | Sort by Title / Author / Recent / Duration / Year / Progress / Finished — mirrors the sort dropdown. Pressing the letter of the **inactive** field switches to it at that field's default direction; pressing the letter of the **already-active** field toggles direction (asc↔desc, same as the ↑/↓ button). `p` (Progress) and `f` (Finished) are silent no-ops when those fields aren't in the dropdown (no book with progress / no finished book). Held keys do not repeat. |
| `1` / `2` / `3` / `4` / `5` (list focused) | Switch view mode to 1-per-row / 2-per-row / 3-per-row / Square / List — mirrors the view-mode dropdown (by row count). The digit for the already-active mode is a no-op (no flicker/re-animation). Held keys do not repeat. |

### List mode: title/author keyboard expand (`Left`/`Right`, added 2026-07-10)

Only in List mode, where Left/Right have no column to move to. Mirrors the existing mouse-hover
title/author expand mechanism (same rendering code, `BookDelegate._list_author_layout`) but is a
per-row keyboard state, reset whenever the keyboard selection moves to a different row — never
persisted. Which states are reachable depends on which fields are actually long (elided):

- **Both short:** `Left`/`Right` do nothing.
- **Long title, short author:** starts **title-expanded** the instant the row becomes the
  keyboard selection (not only after pressing `Left`). `Right` returns it to normal; `Left`
  re-expands it; author never expands (too short).
- **Short title, long author:** starts at normal. `Right` expands the author; `Left` shrinks it
  back to normal.
- **Both long:** starts title-expanded (same start as above). `Right`/`Left` **toggle directly**
  between title-expanded and author-expanded — the normal/collapsed state is never revisited
  once both fields are long.

A keyboard-selected row shows a highlight: 1-per-row gets a themed tint; the three grid
modes (2-per-row/3-per-row/Square) show the same duration/progress overlay a mouse hover
would (no separate tint); List mode reuses the mouse's own hover-fade mechanism, so it
follows the Hover-fade setting (Fast/Normal/Slow/Off) in Settings → Library. The
highlight fades out after ~2.5s of no further keyboard movement, or is dropped/faded
immediately if the mouse takes over (hovering the same row clears it instantly; hovering
a different row fades it out quickly rather than waiting out its timer) — only one
highlight (mouse or keyboard) is ever visible at a time. Mouse hover also sets the real
selection, so `Enter`/`Alt+Enter` always act on whichever book is currently highlighted,
by mouse or keyboard, whichever moved last. Pressing `Tab` to leave the list drops the
highlight **instantly**, with no fade wait, in every mode except List (whose highlight is
the mouse-hover-fade mechanism itself, unaffected by this).

**Search syntax** (`BookModel._apply_filter_and_sort`): besides the existing `#tag` /
`>NNNN` / `<NNNN` / year-range special prefixes, a search string starting with `_`
matches only **titles that start with** the remainder (case-insensitive) — e.g. `_the`
matches "The Hobbit" but not "In the Woods". Title only, not author/narrator.

**Sort / view-mode selection** — the dropdowns themselves are still mouse-only to *open*,
but sort field/direction and view mode are now also driveable from the keyboard while the
list has focus (the `t/a/r/d/y/p/f` and `1`–`5` rows above), routing through the same
handlers the dropdowns use (`_apply_sort_shortcut` / `_apply_view_mode_shortcut` →
`_on_sort_changed` / `_toggle_sort_direction` / `_on_view_mode_changed`). These keys are
scoped to list focus: with the search field focused they type normally. Clicking a dropdown
to make a selection (or dismissing it without choosing) still returns keyboard focus to the
list afterward, so arrows keep driving book navigation rather than getting stranded on the
dropdown.

**Book Detail Panel re-open guard:** requesting detail (via `Alt+Enter`, right-click, or
any other entry point) while the panel is already visible is dropped entirely — it does
not re-animate, and it does not retarget onto a different book. The panel must be closed
first via its own close button or an existing close flow.

## Stats panel (added 2026-07-12)

`StatsPanel` is granted real Qt focus when opened (`PanelManager._claim_panel_focus` — it isn't
in `panel_tab_widgets`, so the panel root itself is the claim target), so it owns the key while
open, same shape as `ChapterList`'s own `keyPressEvent` — not the global dispatcher lane, which
is gated off entirely while any panel is open (see the focus-ownership invariant above).

| Key | Does | Scope |
|-----|------|-------|
| `Left` / `Right` | Previous / next period, same method as the `‹`/`›` nav buttons (`_day_prev`/`_day_next`, `_week_prev`/`_week_next`, `_month_prev`/`_month_next`) | Only while the Day, Week, or Month tab is the active tab. No-op (falls through) on Overall/Timeline/⚙ or any other key. |

Everything else in Stats (Options-tab toggles, the reset-stats confirm, etc.) is mouse-only —
not yet Tab-cycled (Stats isn't in `panel_tab_widgets`, unlike Settings/Speed/Sleep).

## Book Detail Panel (added 2026-07-12)

`BookDetailPanel` is granted real Qt focus when opened (`PanelManager._claim_panel_focus`, no
`panel_key` — the panel root itself is the claim target), so it owns keys the app-installed
`eventFilter` doesn't already intercept — same lane as `ChapterList`/`StatsPanel`'s own
`keyPressEvent`, not the global dispatcher (gated off entirely while any panel is open).
`Tab`/`Backtab`/`Escape` stay entirely in the `eventFilter` (unchanged by this work — Tab
toggles inline metadata edit / the tag-add field, Escape does tag-clear → edit-cancel →
panel-close in that priority). All bindings below are only reachable while NOT editing a
metadata field — entering edit mode gives a `QLineEdit` real focus instead, so it naturally
owns Left/Right/Del/letters/Enter for normal text editing (Enter specifically triggers the
field's native `returnPressed` → `_on_inline_save`, saving any dirty field exactly like
clicking the save icon would).

**While editing, `Up`/`Down` cycle metadata fields** (title → author → narrator → year,
wrapping) — the same `_cycle_metadata_field` method `Tab`/`Shift+Tab` already use. This is an
explicit exception, not a gap: a single-line `QLineEdit` has no native handling for `Up`/`Down`,
so unlike `Left`/`Right`/`Del`/letters (which the field genuinely owns), those two keys were
left unaccepted and propagated up to `BookDetailPanel.keyPressEvent` — before this fix
(2026-07-12) that meant they fired whatever TAB-LOCAL binding was active underneath the edit
(e.g. History row selection moving while the user was mid-edit of a metadata field). Fixed by
checking `_editing` first in `keyPressEvent` and routing `Up`/`Down` to field-cycling; every
other key still falls through to the field's own native handling untouched.

Every binding calls the exact same method the corresponding mouse control already uses — see
each row below.

**Focus-reclaim safety net (added 2026-07-12):** several buttons a user can mouse-click
(`_remove_btn`, the tag-chip `x` buttons, `_trash_btn` on a History row, `_delete_history_btn`)
hold real Qt focus while clicked, and Qt does NOT reliably hand that focus back to
`BookDetailPanel` when the widget is later hidden, disabled, or deleted (a confirm banner
appearing, a tag-chip rebuild after removal, a per-row delete). Left unhandled, this silently
broke the focus-ownership invariant above — with focus at `None`, the global dispatcher took
over and arrow keys fired volume/seek instead of this panel's own bindings, closing the panel
via `hide_all_panels()` in some cases. Fixed two ways: individual known-risk sites reclaim focus
directly (`_clear_tag_input`, `_exit_edit_mode`, `_rebuild_tag_chips`, the History per-row
delete callback), and `BookDetailPanel._ensure_panel_owns_focus()` — called at the top of
`eventFilter` on every `KeyPress` — is a general safety net that reclaims focus for the panel
whenever it's drifted outside the panel's widget tree, so any other site with the same shape
(found or not yet found) self-heals on the very next keypress rather than staying broken.

**Modal-dialog exception:** the safety net above (and `eventFilter`'s Tab/Escape handling)
must NOT run while a modal dialog — e.g. the Cover tab's `+` → `QFileDialog.getOpenFileName`
— is on top, since the `QApplication`-wide filter would otherwise intercept keys meant for the
dialog (confirmed live: `Escape` closed the panel BEFORE the dialog's own native
Escape-to-cancel ran, requiring a second `Escape` to actually cancel the dialog — backwards
from the expected order). `eventFilter` checks `QApplication.activeModalWidget() is not None`
first and declines to handle the event at all when true, letting Qt's normal modal-dialog
input delivery proceed untouched.

### Tab switching

| Key | Does |
|-----|------|
| `Left` / `Right` | Cycle Stats → History → Tags → Cover, wrapping both directions. Plain `QTabWidget.setCurrentIndex` — the same mechanism a mouse click on a tab header uses. |

### Top-level actions (any tab, not editing)

| Key | Does | Notes |
|-----|------|-------|
| `F` | Arm mark-finished/unfinished | Calls `_on_finished_clicked()` — the exact method the header icon's click uses. Shows the same real confirm banner (`"Confirm to mark finished"` / `"Confirm to mark unfinished"` — shortened 2026-07-12 so it fits), 7s auto-cancel. **Yields to the Cover tab's own `F` (fit mode) while that tab is active with a cover selected** — see the Cover section below; confirmed live, not assumed. |
| `Del` / `x` | Arm remove-from-library | Calls `_on_remove_clicked()` — the exact method the trash icon's click uses. Same real confirm banner (`"Confirm to remove from the library"`), 7s auto-cancel. |
| `k` | Metadata lock button | Calls `_on_meta_action_clicked()` only if the button is currently visible (`DIRTY`/`LOCKED` states). **No confirmation exists on the mouse path either** — DIRTY saves immediately, LOCKED clears all locks immediately (confirmed live) — so `k` matches that exactly: no arm/confirm step. |
| `Space` / `Enter` | Confirm whichever of finished/remove is currently armed | Calls `_on_confirm_finished()` / `_on_confirm_remove()` — the exact methods the confirm-label click uses. No-op if nothing is armed and the active tab has no local claim on Space/Enter (see History/Cover below). |
| `Escape` | Disarm whichever of the four confirmations (remove / mark finished-unfinished / bulk delete-history / per-row delete-session) is currently armed, panel stays open | Added 2026-07-12 after live feedback: with only a mouse, Escape while a confirm was armed fell through to the panel-close branch — the mouse-driven rationale ("clicked X but meant to cancel, hit Esc") has no keyboard equivalent otherwise. Checked FIRST, ahead of the tag-input-clear/edit-cancel/panel-close chain below — a confirmation being armed always wins. If nothing is armed, Escape falls through to its prior behavior unchanged (tag-clear → edit-cancel → panel-close). |

Confirmation copy was reworded from "Click to..." to **"Confirm to..."** so it reads
correctly for both mouse and keyboard users (`_confirm_remove_label`, `_confirm_finished_label`
— both branches, the latter shortened to drop "this book" so it fits the available width).
The metadata lock button has no such copy to update (icon-only, no confirmation step exists on
either input path).

### History tab

| Key | Does | Notes |
|-----|------|-------|
| `Up` / `Down` | Move keyboard row selection by one, clamped (no wrap) | Reuses `_HistoryRow.set_keyboard_selected`, which drives the exact same `_slide_overlay`/`_state` transition real mouse hover already uses — the trash-icon reveal on the row's right edge is the selection indicator, not a new visual. Moving selection clears the previous row's indicator first (mirrors `enterEvent`/`leaveEvent`'s own hover hand-off) and scrolls the row into view (`_history_scroll.ensureWidgetVisible`). |
| `Del` | Arm delete-confirmation for the selected row | Calls that row's own `_on_trash_clicked()` — the exact method its trash-icon click uses. |
| `Space` / `Enter` | Confirm the row currently armed (via the top-level Space/Enter row above) | Calls that row's own `_on_confirm_clicked()` — the exact method its "Delete this session?" label click uses. |

The bulk **"Delete listening history"** button is deliberately **not** given a keyboard path —
mouse-only, by explicit decision, not an oversight.

### Cover tab

The navigable sequence is: cover 1, cover 2, ..., last cover, then the **`+` add-cover slot**
IF it's visible (fewer than 4 custom covers) — clamped, no wrap in either direction. With
exactly 4 covers (`+` hidden — no room to add more), `Down` from the last cover wraps to the
first cover that ISN'T the book's currently-active one, rather than no-op'ing (landing back on
the cover already shown as active would be a wasted, indistinguishable-feeling wrap) — this
skip is scoped ONLY to that wrap; normal step-by-step `Up`/`Down` still visits the active cover
like any other on the way there. Redesigned 2026-07-12 from an earlier plain cover-only version
per live feedback that the active cover's accent border alone wasn't enough of a visual cue for
"where does Up/Down go next."

| Key | Does | Notes |
|-----|------|-------|
| `Up` / `Down` | Move the previewed cover to the prev/next entry (or to/from the `+` slot at the boundary — see above) | Cover-to-cover moves reuse `CoverPanel._select_cover` — the exact mechanism a mouse click-to-preview already uses (updates the large 208×266 preview pane and syncs the fit-mode buttons' checked state); this pane, not a new ring on the thumbnail, is the "what would Space/Enter/F-T-S-C apply to" indicator. Selecting `+` shows the **same visual a mouse hover over it already produces** (`QPushButton#CoverAddButton:hover`) via a `kbdSelected` dynamic QSS property, **not real Qt keyboard focus** — granting the button real focus was tried and reverted live: it broke Left/Right tab-cycling while `+` was selected, since a focused `QPushButton` starts owning keys itself. `BookDetailPanel` stays the sole real focus holder throughout. |
| `Space` / `Enter` | Set the previewed cover active, or — if the `+` slot is selected — open the add-cover file dialog | Calls `_on_thumb_set_active(cover_id)` (cover) or `_on_add_cover()` (`+`) — the exact methods their respective mouse click zones use. |
| `Del` | Delete the previewed cover | Calls `_on_thumb_delete(cover_id)` — the exact method a thumbnail's delete click zone uses. **No confirmation step exists on the mouse path either** — fires immediately, matching exactly. Already a no-op on the locked/embedded scanner cover (slot 0) via that same method's own `is_locked` guard, and a no-op while the `+` slot is selected (nothing to delete there) — confirmed live: the locked cover cannot be deleted via this UI at all, keyboard or mouse. |
| `F` / `T` / `S` / `C` | Fit / Top / Stretch / Crop | Simulates a click on the matching fit-mode button (`.click()`, reusing `QButtonGroup`'s exclusivity + the existing handler exactly). No-op while the `+` slot is selected (nothing to apply a fit mode to). **Wins over the top-level `F` (finished-toggle) while this tab is active with a cover selected** — confirmed live: pressing `F` on Cover tab changes fit mode and does NOT arm the finished-toggle banner; switching to any other tab (or Cover with nothing selected/`+` selected) restores `F`'s normal top-level meaning. |

## Planned keys from a Claude chat conversation dated May 9 (Some of them are already stale and they are mostly tentative, pending decision)

Implemented (see the tables above):

- `Space` — play/pause ✅
- `l`/`c`/`g`/`p`/`a`/`s`/`z` — panel/chapter-list keys ✅
- `Up`/`Down` — volume ✅ (kept on the bare arrows rather than the tentative `Shift+Up/Down`)
- `Alt+Up`/`Alt+Down` — speed ✅
- `Shift+Left`/`Shift+Right` — long skip ✅
- `Ctrl+Left`/`Ctrl+Right` — prev/next chapter ✅ (the "reassign `Up/Down` to chapters" idea below was **not** taken — `Up/Down` stayed volume, chapters live on `Ctrl+arrow`)
- `m` — mute ✅ (the "mini-player" alternative meaning was not built)
- `u` — undo last seek ✅ (was not in the original list; added because the on-screen undo affordance had no keyboard equivalent)

Short skip (`Left`/`Right` with no modifier) was **not** bound — the arrows are used by the
Library/Chapter overlays, and only long skip (`Shift+arrow`) was requested this pass.

Still open / not yet built:

b — back/dismiss current panel | superseded by Esc, defunct now
Enter/Shift+Enter — book details for active book (different scope from the 2026-07-09 Alt+Enter added to the Library view above — that one acts on whichever row is keyboard-selected in the list, not the globally currently-playing book from anywhere in the app; this idea is still open) | no need to change it, Alt+Enter could serve in the main window
f or / — search/filter in library (Library's own search field exists and can be Tab-focused as of 2026-07-09 — this idea may now just mean "a global shortcut to jump straight to it")
r — toggle remaining/total time
Escape — dismiss any open panel/overlay

### Theme pool (Settings → Themes tab) — not yet built (2026-07-12)

Prompted by investigating an intermittent right-click-miss report on the theme pool (traced to
mouse hardware, not app logic — see NOTES.md "Cover-pool right-click silent no-op" and the
hover-debounce race fix in `_on_theme_right_clicked`/`_on_cover_pool_btn_right_clicked`,
`theme_manager.py`). A keyboard path through the pool would sidestep mouse reliability
entirely, not just diagnose it. None of this is built — no keyboard-selection cursor exists yet
for the pool grid (unlike Library's `_kbd_selected_path`/`_move_selection_by`, the closest
existing precedent for this shape of feature). Needs its own selection cursor, not a rehash of
the "." diagnostic that was used to confirm the mouse theory and then removed (it borrowed
mouse-hover state as its target, which the real feature can't rely on).

- `Up`/`Down`/`Left`/`Right` (or just `Up`/`Down`) — move a keyboard-selection cursor through the
  pool grid, mirroring Library's arrow-nav pattern
- `Enter`/`Space` — act as left-click on the selected entry (toggle pool membership / select)
- Right-click equivalent — **undecided**; candidates not yet chosen. Worth revisiting whether a
  distinct key is even needed once Enter/Space + letter-jump + `T` exist, since right-click today
  is mostly "select and activate immediately," which overlaps those
- Letter keys — jump to / cycle through themes by name (e.g. press `a` to land on "Alzabo," press
  again to advance to "Anomander," etc.)
- `Ctrl+A` — Add all (bare `A` reserved for the existing `SHOW_STATS` global shortcut, so this
  needs the modifier even though it's panel-local, to avoid the same letter meaning two things
  depending on tab state)
- Remove all — **undecided modifier**; `Ctrl+D` or `Ctrl+R` are the two candidates, not yet chosen
- `T` — Change now (already implemented and working: `Action.TOGGLE_THEME`, bare `T`,
  `GuardKind.COOLDOWN_COALESCE` — see the main-window table above; no change needed here, just
  confirming it stays as-is when the rest of this is built)