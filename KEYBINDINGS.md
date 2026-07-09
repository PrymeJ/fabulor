# Fabulor — Input Bindings Reference

Human-reference inventory of every keyboard, mouse, and wheel binding in the app,
grouped by scope. Accurate as of the `shortcuts.py` migration (feat/shortcuts-module).

Global keys are dispatched by `src/fabulor/shortcuts.py` (`ShortcutDispatcher`, wired in
`MainWindow.keyPressEvent`). Everything else listed here is handled directly by the
widget that owns it and is **not** part of that module — it's documented here only so
this file is a complete map.

A note that applies to every keyboard binding: a key only reaches these handlers if no
focused widget consumes it first. Typing in a text field (library search, sleep custom
time, metadata edit, tag name) sends the keystroke to that field, not to a global
shortcut.

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

Modifiers are ignored: `T` and `Ctrl+T` both rotate the theme, etc. (This matches the
pre-migration behavior and is intentional until configurable bindings land.)

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
Untouched by the shortcuts work; listed for completeness.

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

## Library view (added 2026-07-09)

Handled directly by `LibraryPanel`/`BookDelegate` (`ui/library.py`) — not part of
`shortcuts.py`. The list (`_list_view`) takes keyboard focus as soon as the panel opens
(no click or Tab needed first).

| Key | Does |
|-----|------|
| `Up` / `Down` | Move the book selection. Native `QListView` handling. |
| `Left` / `Right` | Move the selection by one column — **only** in the three grid view modes (2-per-row, 3-per-row, Square). No-op in 1-per-row and List (no adjacent column to move to). |
| `Enter` / `Return` | Play the selected book (same as left-click). |
| `Alt`+`Enter` / `Alt`+`Return` | Open Book Detail for the selected book, on the Stats tab (same as right-click). No-op if a Book Detail panel is already open — see below. |
| `Space` | Play the selected book (same as `Enter`). |
| `Tab` | Toggle focus between the search field and the list. From the list: focus moves to the search field. From the search field: focus moves back to the list (current selection, or the first row if none). This is a dedicated two-way toggle, not Qt's native tab-order chain — it never reaches the sort combo, view-mode combo, sort-direction button, or Back button. |
| `Up` / `Down` (search field focused) | Move the book selection by one and hand focus to the list immediately. `Left`/`Right` in the search field are unaffected (normal text-cursor movement). |
| `Escape` (search field focused) | See "Text fields" above — clears the field and drops focus. |

A keyboard-selected row shows a highlight: 1-per-row gets a themed tint; the three grid
modes (2-per-row/3-per-row/Square) show the same duration/progress overlay a mouse hover
would (no separate tint); List mode reuses the mouse's own hover-fade mechanism, so it
follows the Hover-fade setting (Fast/Normal/Slow/Off) in Settings → Library. The
highlight fades out after ~2.5s of no further keyboard movement, or is dropped/faded
immediately if the mouse takes over (hovering the same row clears it instantly; hovering
a different row fades it out quickly rather than waiting out its timer) — only one
highlight (mouse or keyboard) is ever visible at a time. Mouse hover also sets the real
selection, so `Enter`/`Alt+Enter` always act on whichever book is currently highlighted,
by mouse or keyboard, whichever moved last.

**Search syntax** (`BookModel._apply_filter_and_sort`): besides the existing `#tag` /
`>NNNN` / `<NNNN` / year-range special prefixes, a search string starting with `_`
matches only **titles that start with** the remainder (case-insensitive) — e.g. `_the`
matches "The Hobbit" but not "In the Woods". Title only, not author/narrator.

**Sort / view-mode dropdowns are deliberately mouse-only** — no keyboard shortcut opens
or drives them, same tier as tag-name editing elsewhere in the app. Clicking one to make
a selection (or dismissing it without choosing) returns keyboard focus to the list
afterward, so arrows keep driving book navigation rather than getting stranded on the
dropdown.

**Book Detail Panel re-open guard:** requesting detail (via `Alt+Enter`, right-click, or
any other entry point) while the panel is already visible is dropped entirely — it does
not re-animate, and it does not retarget onto a different book. The panel must be closed
first via its own close button or an existing close flow.

## Planned keys from a Claude chat conversation dated May 9 (Some of them are already stale and they are mostly tentative, pending decision)

Space — play/pause
Left/Right — skip back/forward (short skip)
l — library (already implemented)
c — chapter list (already implemented)
g — tags (already implemented)
p — playback (already implemented)
a — stats (already implemented)
s — settings (already implemented)
z — sleep timer (already implemented)

Skip/chapter/volume resolution:

Up/Down — next/prev chapter (reassigned from volume — chapters matter more than volume during a session)
Shift+Up/Down — volume (or left keyboard-free)
Shift+Left/Right — long skip
Ctrl+Left/Right — prev/next chapter (alternate binding, redundant with Up/Down)

Remaining ideas:

m — mini-player toggle | mute
b — back/dismiss current panel
Enter/Shift+Enter — book details for active book (different scope from the 2026-07-09 Alt+Enter added to the Library view above — that one acts on whichever row is keyboard-selected in the list, not the globally currently-playing book from anywhere in the app; this idea is still open)
f or / — search/filter in library (Library's own search field exists and can be Tab-focused as of 2026-07-09 — this idea may now just mean "a global shortcut to jump straight to it")
r — toggle remaining/total time
Escape — dismiss any open panel/overlay