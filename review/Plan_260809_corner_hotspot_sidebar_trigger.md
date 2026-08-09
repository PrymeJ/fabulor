# Plan: Corner-Hotspot Sidebar Trigger

**Status:** investigation + plan only, no code written. Branch `feature/sidebar-hotspot-trigger`
created off `main` at the start of this investigation, no commits yet.

**Scope:** add a second way to open the sidebar (LIBRARY/SETTINGS/PLAYBACK/SLEEP/STATS/TAGS nav) —
a small hover-intent hotspot in the top-left corner of the cover-art area — alongside the existing
right-click trigger, with method-specific dismissal rules.

---

## 1. What exists today (investigation findings)

### 1.1 The sidebar is not one of the six panels

`build_sidebar(mw)` (`ui/main_window_builders.py:507-564`) builds `mw.sidebar` as a plain `QWidget`,
fixed width 70, holding six `QPushButton`s (`library_trigger_btn`, `settings_trigger_btn`,
`speed_trigger_btn`, `sleep_trigger_btn`, `stats_trigger_btn`, `tags_trigger_btn`) plus
`sleep_cancel_btn`. All seven are `Qt.NoFocus` (`main_window_builders.py:554-557`). It is never
`hide()`/`show()`-toggled — it's permanently `show()`n and slid off-screen to `QPoint(-70, 56)` at
construction, then animated between that and `QPoint(0, 56)` via `sidebar_animation`
(`QPropertyAnimation` on `b"pos"`, 300ms, `OutCubic`). `sidebar.mousePressEvent` is **not**
overridden — clicks on its blank area (not on a button) propagate normally to
`MainWindow.mousePressEvent`.

`PanelManager.sidebar_expanded: bool` (`panels.py:167`) is the single source of truth for
open/closed. It flips synchronously inside `_toggle_sidebar()` (`panels.py:550-683`) before the
slide animation starts (not on animation-finished) — deliberate, see the long docstring at
`panels.py:551-577` explaining the two prior failed designs (silent-drop, then a runaway
open/close loop from queueing *relative* toggles instead of a *target state*). A toggle requested
mid-slide overwrites `_sidebar_pending_target` (an absolute desired end state) rather than queueing
another relative flip; `call_when_panels_settled` re-applies it once the running slide finishes, and
a no-op if the target already matches current state (an even number of clicks cancels out — this is
exactly the loop-prevention pattern the hotspot's re-arm rule needs to respect, see §4.3).

### 1.2 Right-click open/close flow

`visual_area.mousePressEvent` is monkey-patched to `MainWindow._on_drag_area_pressed`
(`app.py:685`, handler at `app.py:3058-3105`). Right-click branch:
1. Post-file-dialog 500ms cooldown guard (`_dialog_close_time`) — silently swallows the click.
2. `db.get_book_count() > 0` guard — sidebar right-click is inert with an empty library.
3. Calls `panel_manager.handle_drag_area_right_click(event)` (`panels.py:2101-2166`).

That method calls `active_full_panel()`. If a full panel (library/settings/speed/sleep/stats/tags/
book_detail/chapter_list) is open, it closes *that* panel. **Only in the `else` branch** (no full
panel open) does it call `_toggle_sidebar()` — so right-click is a genuine toggle: it opens the bare
sidebar when nothing is open, and closes the bare sidebar when it's the only thing open (there's no
separate "right-click again while sidebar open" special case — toggle covers both).

**No focus claim happens anywhere in this path.** `_claim_panel_focus`/`_release_panel_focus` are
only called from the six full-panel `_open_*_flow`/`_close_*_flow` methods (call sites enumerated
in §1.4) — never from `_toggle_sidebar`, `dismiss_sidebar`, or `handle_drag_area_right_click`'s
sidebar branch. This is consistent with `_focus_allows_global_shortcuts()`'s documented invariant
(§1.5): a bare sidebar holds no Qt focus, by design.

### 1.3 Current sidebar dismiss paths

- `PanelManager.dismiss_sidebar()` (`panels.py:2058-2068`) — idempotent `if sidebar_expanded:
  _toggle_sidebar()`. Called from: `_show_chapter_dropdown` (`app.py:2076`),
  `_toggle_remaining_time` (`app.py:2616`), `wheelEvent` over `speed_button` (`app.py:3333`),
  `wheelEvent` over `chapter_progress_slider` (`app.py:3348`).
- `PanelManager.hide_all_panels()` (`panels.py:2070-2089`) — closes sidebar first
  (`if sidebar_expanded: _toggle_sidebar()`, `panels.py:2074-2075`), then all seven full panels.
  Called from `MainWindow._hide_popups()` (`app.py:2029-2031`, a thin wrapper) and directly from
  `toggle_play_pause()` (`app.py:3108`, unconditional at entry).
- **Two independent click-away mechanisms both terminate in `_hide_popups()`/`hide_all_panels()`,
  and neither currently lists the sidebar in its "click landed inside, don't dismiss" allowlist:**
  - `MainWindow.mousePressEvent` (`app.py:2749-2755`) — checks `[library_panel, settings_panel,
    speed_panel, sleep_panel, stats_panel, tags_panel, book_detail_panel]`; any click not inside one
    of those geometries calls `self._hide_popups()`. This is the **window-wide** click-away path —
    it fires for clicks on chrome that doesn't handle its own press (title bar background, empty
    areas), and would fire for a click on the sidebar's own blank area too, since `sidebar` isn't in
    the list and doesn't override its own `mousePressEvent`. **Needs live confirmation, not assumed
    — see Risk §3.1.**
  - `PanelManager.handle_mouse_press(event)` (`panels.py:2091-2099`) — same shape, same panel list
    (plus `book_detail_panel` conditionally), **but this method has zero call sites anywhere in the
    codebase.** It is dead code today. Do not build on the assumption it currently does anything; if
    it's reused, it must be wired in first as its own visible change.
  - `_on_drag_area_pressed`'s **left-click** branch (`app.py:3059-3066`) is a *third*, narrower
    click-away: on `visual_area` specifically, `if is_any_panel_visible(): hide_all_panels()`.
    Redundant with `MainWindow.mousePressEvent` for the same widget in practice (both would fire on
    a left click on `visual_area`), but it's the one that also handles the empty-library short
    circuit and the play/pause toggle-when-nothing-open case.
- **No Escape-to-dismiss for a bare sidebar.** `escape_active_panel()` (`panels.py:1959-1987`) only
  acts when `active_full_panel()` returns non-None; a bare sidebar is exactly the `None` case, so
  Escape no-ops on it today. Not in scope to change per the spec (spec doesn't mention Escape) — flag
  as a possible follow-up, not part of this plan.
- **No existing timer-based dismissal** of the sidebar anywhere.

### 1.4 `_claim_panel_focus` / `_release_panel_focus`

`panels.py:2028-2056`. Claims focus for the panel's first tab-cycle widget (`panel_tab_widgets`) or
the panel root itself; release clears focus only if the currently-focused widget is a descendant of
the panel, and **must be called after `.hide()`**, not before (`hide()` on a still-focused widget
silently re-grants it focus — documented at `panels.py:2048-2053` and in CLAUDE.md's keyboard-focus
rule). Called only from the six full panels' open/close flows — never from sidebar code. **The
sidebar itself should very likely stay this way (no focus claim)** — see §4.1 for why.

### 1.5 `_focus_allows_global_shortcuts()`

`app.py:2646-2659`:
```python
def _focus_allows_global_shortcuts(self) -> bool:
    focus = QApplication.focusWidget()
    return focus is None or focus is self
```
Its docstring explicitly lists sidebar trigger buttons among the always-`NoFocus` chrome that makes
"focus is None or MainWindow" equivalent to "nothing panel-local is focused." Because the sidebar
never claims focus, **global keyboard shortcuts stay fully live while only the bare sidebar is
open** — this is existing, unrelated-to-this-feature behavior, not something the hotspot changes.
Confirmed no interaction: the hotspot doesn't need to touch this method, and shouldn't.

### 1.6 Timer conventions to mirror

All in `theme_manager.py`. Convention: `QTimer(self)` (parented), module-level `_UPPER_SNAKE_MS`
constant near the top of the file, `.timeout.connect(handler)`, arm/disarm centralized in one method
tied to a boolean's transition edges (not scattered `.start()`/`.stop()` calls). Two shapes exist:

- **SingleShot debounce** — `_hover_debounce_timer` (`theme_manager.py:184-187`),
  `_HOVER_DEBOUNCE_MS = 150` (`:62`). `setSingleShot(True)`, restarted on each qualifying event,
  fires once after the quiet period. **This is the shape for the hotspot's hover-intent delay.**
- **Repeating backstop poll** — `_swatch_leave_backstop_timer` (`theme_manager.py:201-203`),
  `_SWATCH_LEAVE_BACKSTOP_MS = 500`, **not** singleShot. Armed/disarmed in exactly one place
  (`_mark_theme_applied`, the sole writer of the boolean it watches) on that boolean's False↔True
  edges. **This is closer to the shape for the idle-dismiss timer**, except the idle timer's
  "reset" semantics (restart on every qualifying event, not just poll-and-check) make it more like
  a singleShot-restarted-on-activity pattern than a fixed-interval poll — see §4.2 for the exact
  shape recommended.
- `_panel_guard_timer` / `_arm_settled_watch` (`panels.py:1799-1833`) — singleShot, **never
  restarted while running** (deliberately absolute deadline, not retriggerable) — this is the
  opposite of what an idle timer needs (idle timers must retrigger) and is a `DO NOT` pattern for
  this specific use, called out so it isn't copied by habit.

### 1.7 No existing app-wide mouse-move tracking

`QApplication.instance().installEventFilter(self)` is installed once (`app.py:528`), and
`MainWindow.eventFilter` (`app.py:3595-3702`) branches on `MouseButtonPress`, `KeyPress`, one
`Show` check, and `Enter`/`Leave` scoped narrowly to `eof_revert_btn`. **No `QEvent.MouseMove`
branch exists anywhere in this filter.** Every other hover-driven feature in this codebase
(`title_bar.py`, `cover_panel.py`, `book_detail_panel.py`, `excluded_books.py`) uses **widget-scoped**
`setMouseTracking(True)` + `enterEvent`/`leaveEvent`/`mouseMoveEvent` overrides, never app-wide
`QApplication`-level move tracking. This matters for two separate needs in this feature that must
NOT be conflated:
- **The hotspot's own hover-intent detection** — naturally widget-scoped (a small child widget with
  `enterEvent`/`leaveEvent`), matching every existing precedent. No new global tracking needed here.
- **The idle timer's "any mouse movement anywhere resets it" requirement** — this genuinely has no
  existing precedent and requires either (a) a new `QEvent.MouseMove` branch added to the existing
  `QApplication`-level `eventFilter` in `app.py`, gated to only run while the sidebar is open (cheap
  no-op check first, to avoid doing anything on every mouse pixel the rest of the time), or (b)
  `MainWindow.setMouseTracking(True)` plus tracking enabled on relevant children — rejected, because
  Qt only delivers `MouseMove` to the widget under the cursor unless every intervening child also has
  tracking enabled, which would mean flipping `setMouseTracking` on a large number of existing
  widgets just for this feature. **(a) is the only approach consistent with "movement anywhere in the
  app window" as literally specified**, and it's a natural, minimal extension of the filter that
  already exists at `app.py:3595`. See §4.2.

### 1.8 `visual_area` geometry and coordinate system

`visual_area = QWidget()` (`app.py:680`), object name `visual_area`, added to `content_layout` with
stretch 1. Window is fixed 300×564 (`app.py:651`). `sidebar_y = 32 (title bar) + 24 (progress bar)
= 56` is used elsewhere as the y-offset where content below chrome begins (`panels.py:642`,
comment at `panels.py:716`). `content_layout` has 10px margins. `visual_area`'s own local (0,0) is
**not** the same point as `MainWindow`'s (0,0) — there's roughly a 56-66px vertical offset from
title bar + progress bar + content margin before `visual_area` itself begins.

**The spec's "x 0, y 53 or 54" coordinates need a live geometry check before implementation** to
confirm which coordinate space they're given in (window-relative vs. `visual_area`-local) — the
numbers are close to but not exactly `sidebar_y = 56`, and CLAUDE.md's standing rule ("the user sees
the rendered pixels, trust their numbers, don't re-derive") applies: once given a live-verified
`(x, y, w, h)` in a stated coordinate space, implement it as given rather than recomputing it from
theory. Flagging the ambiguity now so it's resolved before code, not during.

### 1.9 No overlay can steal the hotspot's events

`TransportBarBlurOverlay._overlay` (`transport_bar_blur.py:294`) is parented to `content_container`
(a sibling ancestor of `visual_area`, not a child of it), is `WA_TransparentForMouseEvents`
regardless of z-order, and its bounding region tracks transport-bar controls at the bottom of the
window — nowhere near the top-left cover-art corner. `ClippedBlurEffect`
(`visual_area_blur.py:49-124`) is a `QGraphicsEffect`, not a widget — it only affects painting, never
mouse event delivery, and the module's own docstring records that an earlier widget-overlay approach
was deliberately reverted in favor of this effect specifically to avoid new-sibling z-order problems.
**Conclusion: no existing overlay can eat the hotspot's hover events under any current panel state.**
This risk is closed, not just deprioritized.

### 1.10 Settings toggle conventions

Two things to note, both different from a typical Qt app:
- **Getter/setter pattern**: `config.py`'s simplest boolean example is `persist_filter_enabled`
  (`config.py:330-334`) — `QSettings.value(key, "false") == "true"` / `str(bool).lower()`. Follow
  this exactly for the two new keys.
- **No `QCheckBox` exists anywhere in this codebase.** Every boolean-ish setting is a paired
  Off/On `QPushButton` segmented control styled via a `"selected"` Qt property (see
  `AudioSettingsTab` in `audio_controls.py:20-64` for the canonical shape, with
  `_update_setting`/`update_visuals` as the read-back/restyle pair). **The two new hotspot settings
  should follow this exact widget pattern**, not introduce a `QCheckBox` as the first one in the app.

---

## 2. Proposed design

### 2.1 `opened_via` flag

- Lives on `PanelManager` as `self._sidebar_opened_via: str | None`, alongside `sidebar_expanded`
  (same object, same lifecycle owner — there is no reason to put it anywhere else; it's sidebar
  state, and `PanelManager` already owns all sidebar state).
- Values: `"right_click"` | `"hotspot_hover"` | `None` (closed / not applicable).
- **Set at the exact two open call sites**: inside `handle_drag_area_right_click`'s `else` branch
  (right before/after the `_toggle_sidebar()` call that opens it) and inside the new hotspot-fire
  handler (§2.3), each hardcoding its own literal — not inferred from context after the fact.
- **Cleared** at the single point where `sidebar_expanded` flips back to `False` inside
  `_toggle_sidebar()`'s closing branch (`panels.py:653-655`) — this is the one place that already
  reliably fires on every dismissal path (idle timer, click-away, item click, hover-out, right-click
  toggle-closed), since every dismiss path in §1.3 ultimately funnels through `_toggle_sidebar()` or
  `dismiss_sidebar()`/`hide_all_panels()` which call it. Clearing it here — rather than duplicating a
  clear at every dismiss call site — avoids the exact kind of drift CLAUDE.md warns about elsewhere
  (e.g. the `upsert_book`/`upsert_books_batch` sync rule): one flag, one clear site, tied to the same
  transition that already exists for `sidebar_expanded` itself.
- Read at the two decision points that need it: the idle-timer setup (§2.4, timer starts identically
  regardless of value — actually doesn't need to *read* it, just needs "sidebar is open" which
  `sidebar_expanded` already gives), and the hover-out dismiss check (§2.5, must read `== "hotspot_hover"`
  before wiring `leaveEvent`-driven dismissal).

### 2.2 Hotspot widget

- A new small `QWidget` (name suggestion: `mw.sidebar_hotspot`), child of `visual_area`, fixed
  15×15, positioned at the live-verified corner coordinates (§1.8 — confirm before implementing).
- `setMouseTracking(True)` on it so `enterEvent`/`leaveEvent` fire reliably (matches every other
  hover widget in this codebase — no new pattern).
- Starts **invisible by default** (no default paint) — becomes visible only when the "show indicator"
  setting is on (§2.7); the widget always exists and always tracks hover regardless of indicator
  visibility (indicator is paint-only, not a hit-test gate) — this matches the spec's "invisible by
  default" phrasing meaning *no visual*, not *no functionality*.
- **Enabled/disabled by the "enable hotspot" setting** — when disabled, the widget should not merely
  hide, it should stop reacting to hover at all (right-click remains available regardless, per spec).
  Simplest correct approach: gate the top of the hover-intent handler on `config.get_hotspot_enabled()`
  and return immediately if False, rather than trying to enable/disable mouse tracking dynamically —
  keeps the widget's existence and geometry stable, avoids a whole class of "did I re-enable tracking
  correctly" bugs.

### 2.3 Hover-intent timer + fire handler

- `mw.sidebar_hotspot_timer = QTimer(mw.sidebar_hotspot)` (parented to the hotspot widget, following
  the "always parent your QTimer" convention from §1.6), `setSingleShot(True)`,
  `setInterval(_HOTSPOT_HOVER_INTENT_MS)` — new module constant, value in the 150-250ms range per
  spec, defined near the top of wherever the hotspot widget class lives (likely a small new class in
  `ui/` rather than inlined in `app.py`, given every other hover-driven micro-widget in this codebase
  — `TasselOverlay`, `HoverButton` — is its own class; see §2.8 for file placement).
- `enterEvent`: gated first on `config.get_hotspot_enabled()` and on the **armed** state (§2.6 —
  zone-exit tracking), then starts the timer.
- `leaveEvent`: stops the timer unconditionally (standard hover-intent cancel-on-early-leave; this is
  what "must NOT open on instantaneous mouse-pass-through" means mechanically — a pass-through leaves
  before the singleShot fires, `leaveEvent` stops it, nothing happens).
- `timeout` handler: the actual "fire" — sets `panel_manager._sidebar_opened_via = "hotspot_hover"`,
  then calls the same `_toggle_sidebar()` open path right-click uses (no duplicate open logic). Must
  **also** re-check `config.get_hotspot_enabled()` at fire time in case the setting was toggled off
  during the delay window (cheap, avoids a stale-timer edge case), and re-check "sidebar not already
  open" (`not sidebar_expanded`) since the no-op-while-open rule (§2.6) should already prevent
  `enterEvent` from arming the timer while open, but the fire handler double-checking is cheap
  insurance against a race between arming and a right-click opening it via another path in the same
  ~200ms window.

### 2.4 Idle timer (universal, both open methods)

- Lives on `PanelManager` as `self._sidebar_idle_timer = QTimer(self)`, `setSingleShot(True)`,
  interval from a new named constant `_SIDEBAR_IDLE_DISMISS_MS` (module-level in `panels.py`,
  10000-15000 range per spec — **the plan does not pick an exact value**; flag as a decision the user
  makes, not Claude).
- **Armed**: started (or restarted — same call, `QTimer.start()` restarts if already running) at the
  moment `sidebar_expanded` flips `True` inside `_toggle_sidebar()`'s opening branch
  (`panels.py:649-651`) — one call site, regardless of `opened_via`, satisfying "applies to BOTH
  open methods identically" by construction rather than by duplicating the arm call in two places.
- **Reset**: every qualifying global mouse-move event restarts it (`.start()` again — QTimer restarts
  its own deadline on repeated `.start()` calls, no need to `.stop()` first). Wired via a new
  `QEvent.Type.MouseMove` branch added to `MainWindow.eventFilter` (`app.py:3595`), gated
  `if self.panel_manager.sidebar_expanded:` as the very first check in that branch so it's a no-op
  in the overwhelmingly common case (sidebar closed) — this addresses the "global filter must not add
  meaningful cost to every mouse pixel app-wide" concern implicitly, without needing a separate
  perf-guard mechanism.
- **Disarmed**: stopped whenever `sidebar_expanded` flips back to `False` (same closing-branch
  location in `_toggle_sidebar()` where `opened_via` is cleared, §2.1) — again one site, not
  duplicated per dismiss path.
- **On timeout**: calls `_toggle_sidebar()` to close (only valid state to fire in, since it's
  disarmed on close and only armed on open — but the handler should still guard
  `if self.sidebar_expanded:` defensively, matching `dismiss_sidebar()`'s own idempotency style).

### 2.5 Hover-out dismissal (hotspot-opened only)

- Only meaningful while `sidebar_expanded and _sidebar_opened_via == "hotspot_hover"`.
- Needs to detect "cursor left the sidebar's rect entirely" — the sidebar itself already has no
  `leaveEvent` override. Two candidate mechanisms:
  1. Override `sidebar.leaveEvent` directly (requires `sidebar.setMouseTracking(True)`, currently not
     set — check before assuming it isn't already needed elsewhere). Simple, standard Qt, matches
     every other precedent in this codebase (widget-scoped enter/leave).
  2. Reuse the same `QEvent.MouseMove` app-wide filter branch from §2.4, and inside it, additionally
     check `not sidebar.geometry().contains(sidebar.mapFromGlobal(cursor_pos))` (or the window-coord
     equivalent) when `_sidebar_opened_via == "hotspot_hover"`, and dismiss if true.
  - **Recommend (1)**: it's the established pattern everywhere else, it's simpler (no coordinate
    translation math duplicated inside the global filter), and it naturally does nothing when
    `opened_via != "hotspot_hover"` if the handler itself checks the flag first — no risk of
    interfering with the right-click path. The one thing to verify live: whether the sidebar's
    animated position (it slides, so its geometry moves) causes any spurious `leaveEvent` mid-slide —
    should gate the handler to only act `if not sidebar_animation.isRunning()` as a safety check,
    since a `leaveEvent` firing while the widget is still animating into position is not a real
    "user moved the cursor away" signal.
- This is a genuinely new code path (§1.3 confirmed nothing like it exists today) — budget real
  implementation + live-verification time for it, not just a wiring change.

### 2.6 Hotspot no-op-while-open + re-arm (zone-exit tracking)

- **No-op while open**: the hover-intent `enterEvent` handler (§2.3) checks
  `not panel_manager.sidebar_expanded` before arming the timer at all. Simplest possible gate,
  reuses the existing flag, no new state needed for this half.
- **Re-arm requires exit-and-reentry**: this needs one new boolean on the hotspot widget itself,
  e.g. `self._armed: bool`, defaulting `True`. Set `False` the moment the sidebar opens **via this
  hotspot** (inside the fire handler, §2.3) — actually more precisely, set `False` at the point the
  sidebar transitions to open for ANY reason while the cursor is sitting in the zone, since the spec's
  loop scenario (§3 below) is about the idle timer firing while the cursor rests near the corner,
  which could correspond to either open method. Set back to `True` only in `leaveEvent` (cursor
  genuinely left the 15×15 zone) — **never** on a timer, never on sidebar-close alone. This is the
  literal "exit and re-enter" mechanism the spec requires and explicitly forbids implementing as a
  cooldown.
- Concretely: `enterEvent` checks `self._armed` (not just "not currently open") before starting the
  hover-intent timer; `leaveEvent` unconditionally sets `self._armed = True` (leaving the zone always
  re-arms, regardless of why) in addition to stopping the timer.
- **Where "disarm" is set is the subtle part** — it must disarm on **every** sidebar-open transition
  while the cursor is in the zone, not just hotspot-triggered opens, or the described loop is only
  half-fixed (a right-click open while resting in the zone, followed by an idle-timer close, would
  otherwise leave the hotspot armed and cursor-still-inside, ready to fire again). Cleanest
  implementation: rather than setting `_armed = False` only inside the hotspot's own fire handler,
  have it read current cursor containment at the moment ANY sidebar-open happens — i.e., disarm
  inside `_toggle_sidebar()`'s opening branch (same site as §2.1/§2.4) with a check like
  "if the hotspot widget currently contains the cursor, disarm it" — this makes the guarantee
  independent of which method opened the sidebar, matching the spec's framing ("after the sidebar
  dismisses... it requires the cursor to leave the zone entirely and re-enter" — stated generally,
  not scoped to hotspot-triggered opens only).

### 2.7 Settings

Two new `config.py` boolean keys, `persist_filter_enabled`-shaped getter/setter pairs:
- `get_sidebar_hotspot_enabled()` / `set_sidebar_hotspot_enabled(bool)` — default `True`.
- `get_sidebar_hotspot_indicator_enabled()` / `set_sidebar_hotspot_indicator_enabled(bool)` —
  default `True`.
- UI: two Off/On button-pairs in the Library (or a new "Interface"/general) settings tab, following
  the `AudioSettingsTab` pattern (§1.10) — exact tab placement is a UI-fit decision, not something
  this plan should force; flag as a small open question for the review pass rather than guessing.
- Gating: hotspot-enabled gates the `enterEvent` handler (§2.3) and, per spec, does **not** affect
  right-click. Indicator-enabled gates only the hotspot widget's own paint (a `paintEvent` override
  drawing a faint dot/square when true, nothing when false) and should itself be additionally gated
  by hotspot-enabled being true (spec: "only meaningful when the hotspot itself is enabled") — i.e.
  effective visibility = `hotspot_enabled and indicator_enabled`, computed once and cached on
  settings-change rather than re-read every paint.

### 2.8 File placement

- New small widget class (hotspot + its timer + armed-state + paintEvent) — a new file
  `ui/sidebar_hotspot.py`, mirroring how `TasselOverlay`/`carousel.py` each get their own small
  widget module rather than being inlined into `app.py`. Constructed and parented in
  `main_window_builders.py` (likely inside or near `build_cover_art`/wherever `visual_area`'s
  children are built), consistent with every other "small always-on chrome widget" in this app.
- `opened_via` and the idle timer live on `PanelManager` (`panels.py`) per §2.1/§2.4 — sidebar state
  belongs where all other sidebar state already lives, not split across files.
- The new `QEvent.MouseMove` branch goes into the existing `MainWindow.eventFilter`
  (`app.py:3595-3702`), as a new `elif` alongside the existing type checks — not a second installed
  filter.

---

## 3. Risk areas (confirmed vs. needing live verification)

| Risk | Status |
|---|---|
| Synthetic hide/show events (blur overlay) firing spurious enter/leave on the hotspot | **Closed** — §1.9. Neither `TransportBarBlurOverlay` nor `ClippedBlurEffect` can reach `visual_area`'s top-left corner or intercept its mouse events, by construction (mouse-transparent attribute / paint-only effect respectively). |
| Cover-art right-click conflicting with the new hover zone in the same widget | **Low risk, needs one live check.** The hotspot is a child widget layered inside `visual_area`, not a coordinate range checked in `_on_drag_area_pressed`. A right-click that lands within the hotspot's 15×15 rect will be delivered to the hotspot widget first (Qt child-widget event delivery), not to `visual_area.mousePressEvent`, **unless** the hotspot widget doesn't override `mousePressEvent`/doesn't accept the event, in which case it propagates up to `visual_area` as normal. Recommendation: do **not** override `mousePressEvent` on the hotspot widget at all — let right-clicks pass through untouched to preserve existing right-click behavior everywhere including inside the 15×15 corner. Verify live once built. |
| Sidebar's own `leaveEvent` firing spuriously mid-slide-animation | **Open, needs live verification** (§2.5) — recommended mitigation (gate on `not sidebar_animation.isRunning()`) is proposed but unverified. This codebase has hit synthetic-leave bugs from animation-driven hide/show before (the swatch-leave saga in `theme_manager.py`, extensively documented in CLAUDE.md) — treat this as the single highest-risk piece of new code in this feature and budget real live-testing time for it specifically, not just code review. |
| Whether `MainWindow.mousePressEvent`'s existing click-away already dismisses blank-sidebar clicks for free | **Needs live confirmation before deciding whether new code is needed for "click on sidebar blank area → dismiss."** Investigation (§1.3) strongly suggests it already works today (sidebar isn't in the panel-allowlist, has no own click handler, so clicks fall through to the existing `_hide_popups()` path) — but this is inference from reading code, not a verified observation, and CLAUDE.md's standing rule is explicit that inferred behavior must be checked, not asserted. First implementation step should be a live test of *current* behavior (right-click open sidebar, click its blank area, see if it already closes) before writing any code for that specific requirement — it may already be a no-op change. |
| `handle_mouse_press` (`panels.py:2091`) being dead code | **Confirmed** (§1.3) — zero call sites found via full-repo grep. Not to be relied upon as "the" click-away mechanism; the real one is `MainWindow.mousePressEvent`. Flagging so it isn't mistakenly wired in under the assumption it's already active. |
| Exact hotspot coordinates given in an ambiguous coordinate space | **Open** (§1.8) — "x 0, y 53 or 54" is close to but not identical to the `sidebar_y = 56` constant used elsewhere; needs a live-verified geometry check (per the CLAUDE.md rule on trusting live pixel measurements over derived theory) before implementation, not a recomputation from layout math. |

---

## 4. Reasoning restated (per the "restate before implementing" requirement)

- **Hover-out only applies to the hotspot path, not right-click**, because right-click is a
  deliberate, discrete user action with clear intent ("I want the sidebar open, full stop") — the
  cursor's subsequent position carries no signal about whether that intent still holds. Hover-intent
  opening, by contrast, is inherently provisional — the user didn't click anything, they just
  lingered near a corner, so the sidebar staying open is contingent on continued proximity in a way a
  click's outcome never is. Tying dismissal to cursor-leaves-the-rect for the hover path is the
  natural continuation of the same signal that opened it; applying that same rule to a right-click
  open would punish someone who deliberately opened the sidebar and then moved the mouse toward a nav
  button, which is the opposite of what they asked for.
- **The idle timer is universal but hover-out is not**, because they answer two different questions.
  Hover-out (hotspot-only) answers "does the original *opening* signal still hold" — a question that
  only has meaning for a method whose open signal was itself proximity-based. The idle timer answers
  a different question that applies regardless of how you got here: "has the user stopped paying
  attention to this UI at all," which is true whenever there's been no mouse motion anywhere in the
  window for the idle window, independent of intent at open time. A right-click-opened sidebar has no
  hover-based signal to lose, but it can still go stale from pure inactivity — that's what the idle
  timer alone is for.
- **The loop the re-arm rule prevents**: cursor rests inside the 15×15 zone → hotspot fires after the
  hover-intent delay → sidebar opens (`opened_via = hotspot_hover`) → cursor never moves (it's still
  resting in the same spot) → idle timer eventually expires with zero mouse movement → sidebar closes
  → if the hotspot re-armed itself immediately on close, the still-resting cursor would look like a
  brand-new hover-enter, restart the hover-intent timer, and reopen the sidebar seconds later → which
  then idles out again → repeating indefinitely with the user's hand nowhere near the mouse. Requiring
  a genuine zone-exit-then-re-entry before the hotspot can fire again breaks this cycle at its root:
  a cursor that never moved cannot satisfy "left and came back," so the loop cannot self-perpetuate.
  This is structurally the same shape as the sidebar's own already-solved relative-vs-target-state
  toggle bug (§1.1) — both bugs are "an automatic re-trigger mistakes a stale condition for a fresh
  user action" — which is why the fix is geometric/state-based (exit+reentry) rather than time-based
  (a cooldown), matching the spec's explicit prohibition on a cooldown mechanism.

---

## 5. Test additions (to write once plan is approved)

All in a new or existing `tests/test_sidebar_hotspot.py`-shaped file, following this codebase's
existing pattern of testing state machines without a live `QApplication` where possible (per
`tests/test_panel_exclusion.py`'s precedent for `PanelManager` truth-table testing):

1. Idle timer resets on any mouse-move event, regardless of location in the window (not scoped to
   sidebar/hotspot rect).
2. Idle timer, on expiry, dismisses the sidebar regardless of `opened_via`.
3. Right-click-opened sidebar does NOT dismiss on cursor leaving the sidebar rect (no hover-out for
   `opened_via == "right_click"`).
4. Hotspot-opened sidebar DOES dismiss on cursor leaving the sidebar rect.
5. Re-arm requires exit-and-reentry: simulate sidebar open (any method) while cursor sits inside the
   hotspot zone, sidebar dismiss (any method) with cursor still resting in the zone, confirm hotspot
   does NOT fire again without an intervening leave+enter.
6. Hotspot is a no-op while the sidebar is already open (hover-intent timer never arms).
7. Click on a sidebar nav item opens that panel and the sidebar itself closes (confirm existing
   behavior, regression-pin it).
8. Click on the sidebar's own blank area dismisses it (once §3's "does this already work" question
   is answered live, pin whichever code path turns out to be responsible).
9. Click anywhere outside the sidebar (elsewhere in the app) dismisses it (regression-pin existing
   `MainWindow.mousePressEvent` behavior).
10. Hotspot-enabled=False: hovering the zone does nothing; right-click still opens the sidebar
    normally.
11. Indicator-enabled=False (with hotspot-enabled=True): hotspot still functions on hover, but paints
    nothing.
12. Hover-intent delay: a mouse-pass-through shorter than the configured delay does not open the
    sidebar (timer started then cancelled by `leaveEvent` before firing).

---

## 6. Open questions for review (not decided by this plan)

1. Exact idle-timer duration within the stated 10-15s range.
2. Exact hover-intent delay within the stated 150-250ms range.
3. Which settings tab hosts the two new toggles.
4. Exact live-verified hotspot pixel rect (§1.8) — needs to be measured against the running app, not
   computed from this plan's layout arithmetic.
5. Visual treatment of the indicator (a dot? a faint square outline? what color/opacity?) — spec says
   "faint," nothing more specific.
