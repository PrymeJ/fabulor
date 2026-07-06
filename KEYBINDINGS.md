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

## Library view

The library grid/list currently has **no keyboard navigation**: there is no arrow-key
row movement, no key to load the selected book, and no key to focus the search field.
Interaction there is mouse-only (plus typing once the search field is focused by
clicking it). This is a statement of current fact, not a planned gap.
