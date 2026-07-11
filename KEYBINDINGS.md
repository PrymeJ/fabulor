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
| `Alt`+`Up` / `Alt`+`Down` | Speed up / down (± configured increment, clamped 0.25×–8.0×) | Book loaded. | Same step path as the speed-button wheel (`_nudge_speed` → `_set_speed`). **Repeats on hold**, self-throttled to one step per `_SPEED_NUDGE_THROTTLE_S` (0.12s, hand-tunable) so held repeat doesn't blow past a value at 0.05 increments; a single tap always applies one step. |
| `Shift`+`Left` / `Shift`+`Right` | Long skip back / forward (`long_skip_duration`) | Book loaded. | Same method as the rewind/forward button **right-click** (`handle_rewind(long_skip=True)` / `handle_forward(long_skip=True)`), including the undo capture. |
| `Ctrl`+`Left` / `Ctrl`+`Right` | Previous / next chapter | Book loaded with chapters. | Same method as the chapter nav buttons and the progress-slider wheel (`handle_prev` / `handle_next`). |
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

b — back/dismiss current panel
Enter/Shift+Enter — book details for active book (different scope from the 2026-07-09 Alt+Enter added to the Library view above — that one acts on whichever row is keyboard-selected in the list, not the globally currently-playing book from anywhere in the app; this idea is still open)
f or / — search/filter in library (Library's own search field exists and can be Tab-focused as of 2026-07-09 — this idea may now just mean "a global shortcut to jump straight to it")
r — toggle remaining/total time
Escape — dismiss any open panel/overlay